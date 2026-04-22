# Parallel GPU Ingestion of 1,036 Medical PDFs

> **Status:** Implementation spec. For the pipeline stage reference, see [README.md](README.md). For infrastructure costs and topology, see [INFRASTRUCTURE.md](INFRASTRUCTURE.md).

## Overview

Run the existing **MARA 5-stage pipeline** across **4 spot GPU instances** in parallel to ingest 1,036 bioRxiv/medRxiv PDFs. The goal is a published metrics report demonstrating production readiness: cost, reliability, performance, and quality — all with hard numbers.

Core constraints: no duplicate processing, idempotent writes, no Azure DI budget blowout, reproducible results.

**Coordination strategy: AWS SQS FIFO queue.** Pre-populate with 1,036 messages (one per PDF). Workers poll and process. Visibility timeout handles crashes (message reappears after 20 min if not deleted). Zero new infrastructure dependencies beyond the existing AWS-native stack.

---

## Architecture

```
[S3: raw/*/pdfs]
       │
       ▼
[queue_manager.py]  ──→  [SQS FIFO Queue: mara-ingestion.fifo]
                                   │
         ┌─────────────────────────┼──────────────────────────┐
         ▼                         ▼                          ▼
[GPU Worker 1]             [GPU Worker 2]             [GPU Worker 3/4]
run_pipeline_worker.py     run_pipeline_worker.py     ...
         │                         │
         └───────────┬─────────────┘
                     ▼
         [t4g.small: Qdrant + Neo4j]   ← all workers write here
                     │
         [S3: metrics/{instance_id}/*.jsonl]
                     │
         [generate_report.py]  ──→  report.md
```

### Design Decisions

| Concern | Decision |
|---|---|
| **Coordination** | SQS FIFO — `MessageDeduplicationId` prevents double-enqueue; visibility timeout requeues crashed PDFs; DLQ after 3 failures. |
| **Idempotency** | Deterministic Qdrant point IDs (stem + chunk index hash) + Neo4j `MERGE` make concurrent writes safe. SQLite determinism DB is per-instance. |
| **Cost control** | Spot `g4dn.xlarge` instances with `MAX_RUNTIME_HOURS` budget wall; S3-backed circuit breaker caps Azure DI page spend across all workers. |
| **Observability** | Per-stage JSONL metrics synced to S3 per PDF; aggregated post-run into `report.md`. |
| **Reproducibility** | Pinned Dockerfile, exact AMI ID in launch script, raw JSONL metrics published to S3. |

---

## Prerequisites (Phase 0 — Bug Fix)

**`embedder.py` uses `uuid.uuid4()` (random) for Qdrant point IDs.** Retrying a PDF creates duplicate chunks. Fix before any parallel run:

```python
id = str(uuid.UUID(hashlib.sha256(f"{stem}_{i}".encode()).hexdigest()[:32]))
```

---

## Implementation Phases

### Phase 1 — SQS Work Coordinator

**`scripts/queue_manager.py`** — CLI tool for managing the work queue:

```
python scripts/queue_manager.py populate --source s3://bucket/raw/  # scan S3, enqueue PDFs
python scripts/queue_manager.py status                               # pending/in-flight/done counts
python scripts/queue_manager.py drain                                # clear queue (emergency)
```

- SQS FIFO; `MessageGroupId = "mara"`; `MessageDeduplicationId` = S3 key hash
- Message schema: `{"s3_key": "raw/medrxiv/foo.pdf", "stem": "foo", "source": "medrxiv"}`
- Config: `config/sqs.yml` (queue URL, region, `visibility_timeout=1200`, `max_receive_count=3`)
- Dead-letter queue for PDFs that fail 3 times

---

### Phase 2 — SQS Worker

**`scripts/run_pipeline_worker.py`** — wraps `MedicalDataPipeline` with an SQS polling loop:

```python
while True:
    msg = sqs.receive_message(VisibilityTimeout=1200, WaitTimeSeconds=20)
    if not msg: break
    pdf = download_from_s3(msg['s3_key'], local='data/raw/')
    pipeline.run(pdf, skip_existing=True)
    emit_metrics(msg, timings, instance_id)
    sqs.delete_message(receipt_handle)
    upload_metrics_to_s3()
```

Key behaviours:
- `skip_existing=True`: each stage checks for its output before running (S3 marker for Stage 5)
- Instance ID: EC2 metadata service (`169.254.169.254/latest/meta-data/instance-id`) or `$INSTANCE_ID` env var
- Graceful SIGTERM: extend visibility timeout, finish current PDF, then exit
- Per-instance log: `logs/worker_{instance_id}.log`

---

### Phase 3 — Idempotent Writes

**Neo4j retry** — add exponential backoff to `build_knowledge_graph.py` `ingest_triplets()`:
- Max 3 retries; backoff 1s → 2s → 4s on `ServiceUnavailable` / `TransientError`
- `MERGE` is already semantically idempotent; concurrent writes produce no duplicates

**Qdrant pre-flight check** — belt-and-suspenders on top of deterministic IDs:
```python
existing = qdrant_client.scroll(filter=FieldCondition(key="source", match=MatchValue(value=stem)))
if existing[0]:
    logger.info("Already vectorized, skipping")
    continue
```

**Per-instance determinism DB** — modify `DeterminismTracker` to accept a `db_path` override; worker passes `data/determinism_{instance_id}.db`. Consolidate after run:
```
python scripts/merge_determinism_dbs.py --pattern "data/determinism_*.db" --out data/determinism.db
```

---

### Phase 4 — Circuit Breaker (Azure DI Budget)

**`src/ingestion-graphrag/src/circuit_breaker.py`** — shared state stored in S3:

```json
{"azure_di_pages_used": 0, "azure_di_budget_pages": 10000, "status": "closed"}
```

- Workers call `CircuitBreaker.check("azure_di")` before each Azure DI fallback
- Over budget: `status = "open"`, skip Azure DI, fall back to CPU
- Counter incremented atomically via S3 conditional put (ETag check)
- Config: `config/circuit_breaker.yml` with per-provider budgets
- Workers poll S3 state every 60s — no Prometheus required

---

### Phase 5 — Metrics Collection

**`src/ingestion-graphrag/src/metrics.py`** — lightweight JSONL emitter:

```python
@dataclass
class StageMetric:
    execution_id: str
    instance_id: str
    document_stem: str
    stage: str            # ocr|convert|clean|chunk|vectorize
    status: str           # success|failure|skipped
    duration_seconds: float
    input_bytes: int
    output_bytes: int
    error: Optional[str]
    timestamp: str        # ISO 8601
```

Each worker appends to `logs/metrics_{instance_id}.jsonl` and syncs to `s3://bucket/metrics/{instance_id}/metrics.jsonl` after each PDF.

**`scripts/generate_report.py`** — reads all `s3://bucket/metrics/*/metrics.jsonl` and produces `report.md`:

| Metric | Value |
|---|---|
| Total PDFs processed | 1,036 |
| End-to-end wall time | Xh Ym |
| p50 / p95 per-PDF time | Xs / Xs |
| Stage breakdown (avg) | OCR: Xs · Convert: Xs · Clean: Xs · Chunk: Xs · Embed: Xs |
| Fallback activation rate | X% |
| Total cost | $X.XX |
| Qdrant vectors stored | N |
| Neo4j nodes / relationships | N / N |
| Determinism drift rate | X% |

---

### Phase 6 — Cost Control & Launch

**Budget wall** in `run_pipeline_worker.py`:
```python
MAX_RUNTIME_HOURS = float(os.getenv("MAX_RUNTIME_HOURS", "12"))
if time.time() - start_time > MAX_RUNTIME_HOURS * 3600:
    logger.warning("Budget wall hit — shutting down")
    os.system("sudo shutdown -h now")
```

**`scripts/launch_instances.sh`** — spin up 4 spot GPU instances:
- AMI: Deep Learning OSS Nvidia Driver AMI GPU PyTorch (pinned AMI ID)
- Instance type: `g4dn.xlarge` (spot)
- User data: clone repo → `make install` → set env vars → `python scripts/run_pipeline_worker.py`
- Instance profile with SQS + S3 permissions
- `--instance-initiated-shutdown-behavior terminate`

---

### Phase 7 — Containerization

**`Dockerfile`** — CPU/GPU toggle via build arg:
```dockerfile
ARG DEVICE=cpu
FROM nvidia/cuda:12.1-runtime-ubuntu22.04 AS gpu
FROM python:3.12-slim AS cpu
```
- Pins exact `requirements.txt` with hash verification
- Config baked in via `COPY config/ config/`; secrets injected at runtime via env vars

**`docker-compose.worker.yml`** — GPU worker variant:
```yaml
services:
  worker:
    build: {context: src/ingestion-graphrag, target: gpu}
    deploy:
      resources:
        reservations:
          devices: [{capabilities: [gpu]}]
    environment:
      - AWS_PROFILE
      - INSTANCE_ID
      - MAX_RUNTIME_HOURS=12
    command: python scripts/run_pipeline_worker.py
```

Update `src/ingestion-graphrag/README.md` with exact reproduction steps: AMI ID, instance type, queue URL format, `docker build` command.

---

## File Map

| File | Status |
|---|---|
| `src/ingestion-graphrag/src/storage/embedder.py` | Modified — deterministic point IDs |
| `src/ingestion-graphrag/src/determinism.py` | Modified — accept `db_path` param |
| `src/ingestion-graphrag/scripts/build_knowledge_graph.py` | Modified — retry backoff |
| `src/ingestion-graphrag/src/metrics.py` | New — `StageMetric` + JSONL emitter |
| `src/ingestion-graphrag/src/circuit_breaker.py` | New — S3-backed budget circuit breaker |
| `src/ingestion-graphrag/scripts/queue_manager.py` | New — SQS populate / status / drain |
| `src/ingestion-graphrag/scripts/run_pipeline_worker.py` | New — SQS polling worker |
| `src/ingestion-graphrag/scripts/merge_determinism_dbs.py` | New — DB consolidation |
| `src/ingestion-graphrag/scripts/generate_report.py` | New — metrics → `report.md` |
| `src/ingestion-graphrag/scripts/launch_instances.sh` | New — EC2 spin-up |
| `src/ingestion-graphrag/config/sqs.yml` | New — queue config |
| `src/ingestion-graphrag/config/circuit_breaker.yml` | New — per-provider budgets |
| `src/ingestion-graphrag/Dockerfile` | New — CPU/GPU image |
| `src/ingestion-graphrag/docker-compose.worker.yml` | New — GPU worker compose |

---

## Quality Metrics Framework

| Dimension | Metrics | Source |
|---|---|---|
| **Cost** | Total spend, $/PDF, $/1k pages, spot savings | Billed usage + circuit breaker Azure DI page counter |
| **Reliability** | Success rate, fallback rate, p95 recovery time, DLQ count | Per-stage status logs, SQS receive count, circuit breaker hits |
| **Performance** | p50/p95/p99 end-to-end time, per-stage breakdown, GPU vs. CPU latency | Stage timestamps in metrics JSONL |
| **Quality** | Qdrant vector count, Neo4j nodes/relationships, determinism drift, chunk stats | Post-run DB queries + determinism DB merge |

---

## Expected Outcomes

- **100%** of 1,036 PDFs processed without silent failures
- **Total cost** < $20 (spot + fallback + persistent DB)
- **Wall-clock time** < 2 hours (vs. ~7 hours on a single instance)
- A published `report.md` with all raw metrics — definitive proof of production readiness

---

## Next Steps

1. Fix `embedder.py` point IDs (Phase 0) and merge to `main`
2. Test `queue_manager.py` with a small batch
3. Validate the worker loop on a single GPU instance in staging
4. Scale to 4 instances for the full run
