# Design Document: Multi-Cloud GraphRAG

> **Scope:** Architecture decisions, problem framing, and engineering trade-offs.  
> For operational setup, see [INFRASTRUCTURE.md](INFRASTRUCTURE.md). For the ingestion pipeline, see [THE_INGESTION.md](THE_INGESTION.md).

---

## Problem Statement

Medical research is fragmented across ClinicalTrials.gov, PubMed, bioRxiv, and medRxiv. Researchers and clinical teams cannot query across these sources in natural language. Existing RAG systems are brittle: single-cloud, single-source, and expensive to run continuously.

This system addresses three root problems:

1. **Data fragmentation** — clinical trial protocols, PubMed abstracts, and preprints live in incompatible formats across four separate APIs with different rate limits, identifier schemes, and PDF structures.
2. **Cost unpredictability** — GPU OCR at scale is expensive. Without spend controls, a single misconfigured run can cost $50/day (observed on Day 5).
3. **Reliability brittleness** — single-cloud pipelines fail silently during spot termination events. There is no standard recovery pattern.

---

## Goals and Non-Goals

### Goals

| Goal | Success Metric | Current Status |
|------|----------------|----------------|
| Natural language search across all four sources | Recall@5 ≥ 0.85 | 0.89 (GPU), tracked via `benchmarking/evaluator.py` |
| End-to-end query latency under 30 seconds | p95 latency | ~15s measured |
| Monthly cost ≤ $30 for continuous operation | Actual cloud spend | $28.47 over a 7-day run |
| New data source integration without code changes | Config-only onboarding | 4 sources active |
| Zero duplicate vectors on pipeline retry | Deterministic point IDs | SHA-256 content-addressed |

### Non-Goals

- **Real-time ingestion**: The pipeline is batch-oriented. Sub-minute latency from publication to searchability is not required.
- **Multi-tenancy at the storage layer**: Namespace isolation between research organisations is handled via YAML config, not separate Qdrant collections.
- **Full-text search**: The retrieval layer is vector + graph only. BM25 or inverted-index search is out of scope.
- **Automated source discovery**: New sources must be explicitly configured; automatic crawling is not supported.

---

## Key Design Decisions

### 1. Spot Instances as Primary Compute

**Decision:** Route ~90% of OCR/embedding workload through `g4dn.xlarge` EC2 Spot instances.

**Rationale:** Spot instances are 60–90% cheaper than on-demand for GPU workloads. Medical PDF ingestion is highly parallelisable and inherently resumable — ideal for interruptible compute.

**Trade-offs:**
- Spot termination occurs in 3–5% of jobs. Recovery requires a 45-second failover path to Azure DI.
- A 30-second health check interval is mandatory to detect termination before the 2-minute AWS notice window.
- Per-instance determinism databases (SQLite) must be merged post-run; a dedicated merge script (`scripts/merge_determinism_dbs.py`) handles this.

---

### 2. S3-Backed Circuit Breaker (No Redis)

**Decision:** Track Azure DI page spend in a single S3 JSON object, not a Redis counter or database row.

**Rationale:** The circuit breaker must work across disconnected workers with zero additional infrastructure. S3 conditional puts (ETag-based optimistic locking) provide sufficient atomicity at our write frequency (one update per PDF).

**Trade-offs:**
- ~1 minute eventual consistency means a budget cap can be breached by at most (workers × 1 page budget window) pages before all workers observe the open state. Acceptable at our scale.
- This approach does not scale to thousands of concurrent workers without contention on the S3 object.

**State schema** (`s3://bucket/circuit-breaker/state.json`):
```json
{
  "azure_di_pages_used": 847,
  "azure_di_budget_pages": 10000,
  "status": "closed",
  "last_updated": "2024-01-15T14:23:11Z"
}
```

---

### 3. Deterministic SHA-256 Qdrant Point IDs

**Decision:** Derive Qdrant point IDs as `UUID(SHA-256(f"{stem}_{chunk_index}")[:32])` rather than `uuid4()`.

**Rationale:** Retrying a failed PDF must be idempotent. Random IDs produce duplicate vectors that degrade retrieval precision and waste storage. Content-addressed IDs make retry semantics safe by default.

**Trade-offs:**
- Point IDs must be computed before the upsert, adding a small per-chunk hashing overhead.
- SHA-256 truncation to 128 bits is collision-resistant for our expected corpus size (millions of chunks), but is not cryptographically collision-proof.

---

### 4. Config-Driven Fetcher Architecture

**Decision:** All source-specific parameters (API endpoints, rate limits, PDF URL patterns, storage prefixes) live in `config/data-acquisition/sources/{name}.yml`. No hardcoded values in Python.

**Rationale:** Adding a new data source should require only a new YAML file and a fetcher class that reads it. The orchestrator (`scripts/fetch_pdfs.py`) handles rate limiting, metrics, and storage failover automatically.

**Trade-offs:**
- YAML schema is effectively a typed contract. Schema drift between config and code silently breaks fetchers. Strict validation at startup is essential.
- Config-driven systems are harder to unit-test than code-driven ones. Integration tests against a real API remain necessary.

**Adding a new source:** see [README.md § Adding a New Data Source](README.md#adding-a-new-data-source).

---

### 5. Azure DI as Fallback (Not Primary) OCR

**Decision:** Use Azure Document Intelligence only when GPU Spot is unavailable or for complex documents, not as the default OCR path.

**Rationale:** Azure DI produces higher-quality output on dense, structured clinical documents (tables, multi-column layouts), but at 15–100× the cost of GPU Spot. A budget incident on Day 5 ($50/day) validated that automatic spend controls are non-negotiable.

**Trade-offs:**
- Quality improvement from Azure DI is measurable: Entity Accuracy 94.2% (GPU) vs 95.1% (Azure DI). The delta does not justify routine use at $1.50/1k pages.
- Two fallback tiers (Azure DI → CPU Tesseract) create a quality cliff. CPU Tesseract quality (Recall@5 = 0.76) is significantly below GPU (0.89). Documents that reach Tesseract should be flagged for reprocessing.

---

### 6. Per-Instance JSONL Metrics

**Decision:** Each worker emits per-stage metrics as JSONL to a local file, synced to `s3://bucket/metrics/{instance_id}/` after each PDF.

**Rationale:** No external metrics infrastructure required. JSONL is git-friendly, appendable, and trivially parseable. Post-run aggregation via `scripts/generate_report.py` provides a full run report.

**Trade-offs:**
- Metrics are not real-time. Dashboards during a run require polling S3, not a streaming metrics backend.
- If an instance terminates before the final sync, the last PDF's metrics may be lost. The visibility timeout (20 min) mitigates but does not eliminate this.

---

### 7. Persistent `t4g.small` for Vector and Graph Databases

**Decision:** Run Qdrant and Neo4j on a permanently-on `t4g.small` instance rather than alongside the processing workers.

**Rationale:** Read latency for retrieval queries must be consistent. Co-locating databases with ephemeral Spot workers introduces a dependency between compute scaling and query availability.

**Trade-offs:**
- Single point of failure. A `t4g.small` outage takes both the vector store and knowledge graph offline. Backup strategy (Qdrant snapshots to S3, Neo4j dump) is documented in [INFRASTRUCTURE.md](INFRASTRUCTURE.md) but not yet automated.
- At current scale (12 GB vectors, 8 GB graph), a `t4g.small` is comfortably sized. At 5× load, upgrade to `t4g.medium` is required.

---

## Failure Mode Analysis

| Failure | Detection | Mitigation | Residual Risk |
|---------|-----------|------------|---------------|
| Spot termination | 30s health check + AWS 2-min notice | Failover to Azure DI; SQS requeues message after visibility timeout | ~45s gap in processing |
| Azure DI budget exhaustion | Circuit breaker polls S3 every 60s | Auto-fallback to CPU Tesseract | ~1 min over-spend window per worker |
| Qdrant OOM | Vector size monitoring | Auto-scaling policy on `t4g.small` | Queries fail during resize |
| S3 rate limiting | HTTP 503 response | Exponential backoff (observed on Day 2) | Increased latency |
| Metadata schema drift | Version field mismatch on read | Version field + migration path | Silent data corruption if undetected |
| Silent pipeline failure | Stage output hash mismatch in `determinism.db` | Per-stage output hashing + determinism drift alerts | Missed documents if drift rate > threshold |
| Both clouds unreachable | Health check returns unhealthy for both | CPU Tesseract fallback | 10× latency increase; quality degradation |

---

## Operational Constraints

- **Azure DI cost cap:** Budget threshold defined in `config/circuit_breaker.yml`. Auto-fallback prevents runaway spend. The Day 5 incident ($50/day) was caused by a missing cap on initial deployment.
- **No vendor lock-in:** Primary compute on AWS Spot; fallback on Azure; catastrophic on local CPU. No proprietary managed service is required for the critical path.
- **Deterministic output:** The same source PDF must produce byte-identical chunks and the same Qdrant point ID on every run. This is enforced via `DeterminismTracker` and verified post-run via the drift metric.

