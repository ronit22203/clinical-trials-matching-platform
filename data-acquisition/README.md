# Data Acquisition

> **Makefile topology changed:** run all `make` commands from the **repo root**. Use `make acquisition-install`, `make acquisition-test`, and `make fetch SOURCE=<name> MAX_PDFS=<n>`.

### Medical PDF Ingestion → RAG Pipeline
> Fetch from 4 research sources, process through a 5-stage ingestion pipeline, query with hybrid vector + graph retrieval, across multiple clouds with automatic failover.

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![AWS](https://img.shields.io/badge/AWS-S3%20%7C%20EC2-orange)](https://aws.amazon.com/s3/)
[![Azure](https://img.shields.io/badge/Azure-DI%20%7C%20Blob-blue)](https://azure.microsoft.com/en-us/products/ai-services/document-intelligence)
[![Qdrant](https://img.shields.io/badge/Qdrant-vector%20store-red)](https://qdrant.tech/)
[![Neo4j](https://img.shields.io/badge/Neo4j-knowledge%20graph-green)](https://neo4j.com/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## Overview

Two co-located sub-systems that together form a complete medical research RAG pipeline:

**1. Fetching Layer** — pulls PDFs from ClinicalTrials.gov, PubMed, bioRxiv, and medRxiv and stores them across AWS S3 → Azure Blob → local disk with automatic failover.

**2. MARA Ingestion Pipeline** — a 5-stage document processor (OCR → Markdown → Clean → Chunk → Embed) that turns raw PDFs into searchable vectors in Qdrant and a knowledge graph in Neo4j.

The system is **configuration-driven**: every source, rate limit, and storage target is defined in YAML — no hardcoding. Processing tiers fall back automatically across GPU Spot → Azure Document Intelligence → CPU Tesseract. Everything is measured: cost, latency, quality, and failure modes.

---

## End-to-End Data Flow

```
Sources: ClinicalTrials.gov · PubMed · bioRxiv · medRxiv
    ↓  config-driven fetch (scripts/fetch_pdfs.py)
Multi-Cloud Storage: S3 (primary) → Azure Blob → Local disk
    ↓  raw PDFs land in data/raw/
MARA Ingestion Pipeline  (src/ingestion-graphrag/)
    Stage 1  Surya OCR          →  data/ocr/
    Stage 2  Converter          →  data/markdown/
    Stage 3  TextCleaner + PII  →  data/cleaned/
    Stage 4  MarkdownChunker    →  data/chunks/
    Stage 5  MedicalVectorizer  →  Qdrant (vectors) + Neo4j (graph)
    ↓
Hybrid Retrieval: vector search (Qdrant) + graph traversal (Neo4j)
    ↓
Natural Language Query Interface
```

---

## Infrastructure Topology

| Tier | Instance / Service | Runtime Pattern | Hourly Cost | % Traffic |
|------|--------------------|-----------------|-------------|-----------|
| **Primary GPU** | `g4dn.xlarge` (spot) | Few hours/week | $0.10–0.15 | 90% |
| **Persistent DB** | `t4g.small` (24/7) | Always on | $0.0084 ($12/mo) | – |
| **Fallback 1** | Azure Document Intelligence | On-demand | $1.50 / 1k pages | 8% |
| **Fallback 2** | CPU Tesseract | Rare (catastrophic) | $0.01/hr | 2% |

**Monthly baseline:** ~$5–7 + variable Azure DI costs.  
**Circuit breaker:** Azure DI spend is tracked in S3 (works across disconnected workers). Auto-fallback to CPU when budget cap is hit.

---

## Fallback Matrix

| Trigger                        | Primary → Fallback       | Measured Recovery |
|--------------------------------|--------------------------|-------------------|
| Spot termination               | GPU → Azure DI           | 45s (p50)         |
| Complex document (OCR‑heavy)   | GPU → Azure DI           | Immediate         |
| Document >50 pages             | GPU → CPU Tesseract      | 2.3× slower       |
| Azure DI budget cap            | Azure DI → CPU           | Configurable      |
| Both clouds unreachable        | Any → CPU fallback       | Depends on outage |

All failure modes are instrumented; recovery times are continuously measured.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  CONFIGURATION LAYER                                         │
│  config/app.yaml → data_acquisition.sources / data_acquisition.storage         │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  FETCHER LAYER  (src/fetchers/)                              │
│                                                              │
│  BaseFetcher (ABC)                                           │
│  ├── search(query, max_results) → list[SearchRecord]         │
│  ├── fetch_pdf(record_id) → Optional[FetchResult]            │
│  ├── generate_metadata(record) → dict                        │
│  └── cleanup()                                               │
│                                                              │
│  ClinicalTrialsFetcher · BioRxivFetcher                      │
│  MedRxivFetcher · PubMedFetcher                              │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  PROCESSING TIERS  (scripts/fetch_pdfs.py orchestrates)      │
│                                                              │
│  PRIMARY          FALLBACK 1          FALLBACK 2             │
│  GPU Spot    ──►  Azure DI       ──►  CPU Tesseract          │
│  $0.12/hr         $1.50/1k pg         $0.01/hr               │
│  90% traffic      8% traffic           2% traffic            │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  MULTI-CLOUD STORAGE  (src/storage/)                         │
│                                                              │
│  S3 (ap-south-1)  →  Azure Blob (centralindia)  →  Local    │
│                                                              │
│  raw/{source}/*.pdf      →  raw PDFs                         │
│  raw/{source}/*.metadata.json  →  metadata sidecars          │
│  temp/manifests/{trace_id}.json  →  run manifests            │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  MARA INGESTION PIPELINE  (src/ingestion-graphrag/)          │
│                                                              │
│  Stage 1  Surya OCR          data/raw/   → data/ocr/         │
│  Stage 2  Converter          data/ocr/   → data/markdown/    │
│  Stage 3  TextCleaner + PII  data/markdown/ → data/cleaned/  │
│  Stage 4  MarkdownChunker    data/cleaned/ → data/chunks/    │
│  Stage 5  MedicalVectorizer  data/chunks/ → Qdrant + Neo4j   │
│                                                              │
│  Determinism: SHA-256 point IDs · SQLite fingerprinting      │
│  PII: Presidio (SG_NRIC, MCR_NO)                             │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  RETRIEVAL  (src/ingestion-graphrag/src/retrieval/)          │
│                                                              │
│  HybridRetriever                                             │
│  ├── Vector search  →  Qdrant  (BAAI/bge-small-en-v1.5)      │
│  └── Graph traversal  →  Neo4j  (knowledge graph)            │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  OBSERVABILITY                                               │
│  Prometheus · Grafana · Structured JSONL logs                │
│  cost_per_doc · p99_latency · fallback_rate · recall@5       │
└──────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/ronit22203/multi-cloud-graphrag.git
cd multi-cloud-graphrag

python -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
```

> **Python 3.12+ required.**

### 2. Configure

```bash
# AWS credentials for S3 (ap-south-1)
aws configure --profile clinical-trials-fetcher

# Optional: create a .env file at the repo root for credentials
# (shell env vars take precedence over .env values)
cat > .env <<EOF
AWS_PROFILE=clinical-trials-fetcher
AWS_DEFAULT_REGION=ap-south-1
AZURE_STORAGE_CONNECTION_STRING=your_connection_string
EOF
```

Source configs and storage configs now live in `config/app.yaml` under `data_acquisition.sources` and `data_acquisition.storage`. No hardcoded values anywhere.

### 3. Fetch PDFs

```bash
# Dry run (no uploads)
python scripts/fetch_pdfs.py \
  --source clinical_trials \
  --query "cancer immunotherapy" \
  --max-pdfs 5 \
  --dry-run

# Real run
python scripts/fetch_pdfs.py \
  --source medrxiv \
  --query "LLM clinical trials" \
  --max-pdfs 50

# Bulk fetch 500 papers (resumable — skips already-fetched IDs)
python utils/generate_500_pdf_medrxiv.py --target 500   # medRxiv
python utils/generate_500_pdfs.py --target 500           # bioRxiv
```

### 4. Run the Ingestion Pipeline

```bash
# Install ingestion deps (isolated venv inside src/ingestion-graphrag/)
make acquisition-install

# Start Qdrant + Neo4j
make ingestion-qdrant-up

# Run all 5 stages
make ingestion-run N=10

# Skip a stage (ocr | convert | clean | chunk | vectorize)
make ingestion-run SKIP=ocr

# Inspect output at each stage
make ingestion-inspect
```

### 5. Query & Evaluate

```bash
# Retrieval quality benchmark (recall@5, NDCG@5)
python src/ingestion-graphrag/benchmarking/evaluator.py

# Parse fetch logs into a report
python utils/data_from_fetch.py --stats
python utils/data_from_fetch.py --source medrxiv --by-keyword
python utils/data_from_fetch.py --export json
```

### 6. Metrics

```bash
# Start observability stack
docker compose up -d prometheus grafana

# Grafana: http://localhost:3000  (admin / admin)
# Prometheus: http://localhost:9090
```

---

## Project Structure

```
multi-cloud-graphrag/
├── config/
│   ├── sources/                   # One YAML per data source
│   │   ├── clinicaltrials.yml
│   │   ├── biorxiv.yml
│   │   ├── medrxiv.yml
│   │   └── pubmed.yaml
│   └── storage/                   # Cloud storage configs
│       ├── aws_s3.yml
│       ├── azure_blob.yml
│       ├── local_fallback.yml
│       └── providers.yml
├── src/
│   ├── fetchers/                  # Source implementations
│   │   ├── base.py                # BaseFetcher ABC
│   │   ├── clinical_trials_pdf.py
│   │   ├── biorxiv.py
│   │   ├── medrxiv.py
│   │   └── pubmed.py
│   ├── storage/                   # Multi-cloud storage adapters
│   │   ├── base.py                # BaseStorageProvider ABC
│   │   ├── aws_s3.py
│   │   ├── azure_blob.py
│   │   ├── local.py
│   │   └── manager.py             # MultiCloudStorageManager (failover)
│   └── ingestion-graphrag/        # MARA ingestion pipeline
│       ├── ../config/app.yaml
│       ├── infra/docker-compose.yaml
│       ├── scripts/run_pipeline.py
│       ├── src/
│       │   ├── extractors/        # Stage 1–2: OCR + Converter
│       │   ├── processors/        # Stage 3–4: Cleaner + Chunker
│       │   ├── storage/           # Stage 5: Embedder + Qdrant manager
│       │   ├── retrieval/         # HybridRetriever (Qdrant + Neo4j)
│       │   └── determinism.py     # SHA-256 dedup + SQLite tracking
│       ├── tests/
│       │   ├── test_processors.py
│       │   ├── test_qdrant.py
│       │   ├── test_embedder.py
│       │   └── smoke_test.py
│       └── benchmarking/
│           └── evaluator.py       # Recall@k against golden.json
├── scripts/
│   └── fetch_pdfs.py              # Main fetch orchestrator
├── utils/
│   ├── generate_500_pdfs.py       # Bulk bioRxiv fetch (resumable)
│   ├── generate_500_pdf_medrxiv.py # Bulk medRxiv fetch (resumable)
│   ├── generate_next_batch_v2.py
│   └── data_from_fetch.py         # Log + manifest report generator
├── tests/                         # Root project tests (pytest)
├── Makefile                       # All make commands operate in src/ingestion-graphrag/
├── pyproject.toml                 # Root project (Python 3.12+)
└── README.md
```

---

## MARA Ingestion Pipeline

The **M**edical **A**rticle **R**etrieval **A**rchitecture (`src/ingestion-graphrag/`) processes PDFs into searchable, deduplicated vectors.

### Stages

| Stage | Module | Input → Output |
|-------|--------|---------------|
| 1 — OCR | `extractors/pdf_marker_v2.py` | `data/raw/*.pdf` → `data/ocr/*_ocr.json` |
| 2 — Convert | `extractors/surya_converter.py` | OCR JSON → `data/markdown/*_converted.md` |
| 3 — Clean | `processors/cleaner.py` | Markdown → `data/cleaned/*_cleaned.md` + PII redaction |
| 4 — Chunk | `processors/chunker.py` | Cleaned MD → `data/chunks/*_chunks.json` |
| 5 — Embed | `storage/embedder.py` | Chunks → Qdrant vectors + Neo4j graph nodes |

### Determinism

Every run is fingerprinted with SHA-256 hashes stored in `data/determinism.db`. Document UUIDs are deterministic (SHA-256 of filename); execution UUIDs are random. This means retries never create duplicate vectors — Qdrant point IDs are stable across re-runs.

```bash
make ingestion-list-documents
make ingestion-list-executions DOC=<uuid>
make ingestion-compare-runs DOC=<uuid> EXEC1=<uuid> EXEC2=<uuid>
```

### PII Redaction (Stage 3)

Uses [Presidio](https://microsoft.github.io/presidio/) with custom recognizers for Singaporean medical data:

| Entity | Pattern |
|--------|---------|
| `SG_NRIC` | `[STFG]\d{7}[A-Z]` |
| `MCR_NO` | `\d{6}` |

Controlled by `cleaning.remove_pii` in `config/app.yaml`. Set `fail_safe_on_pii_error: true` to return original text on Presidio errors.

### Embedding Model

`BAAI/bge-small-en-v1.5` — 384 dimensions. Auto-detects MPS (Apple Silicon) or CUDA. Adjust `batch_size` in `config/app.yaml` if OOM.

### Make Commands

```bash
make acquisition-install          # Install acquisition dependencies
make fetch SOURCE=medrxiv MAX_PDFS=10
make ingestion-qdrant-up          # Start Qdrant
make ingestion-run N=10           # Active ingestion pipeline
make ingestion-run SKIP=ocr
make ingestion-inspect            # File counts + samples at each stage
make acquisition-test             # Run acquisition tests
make ingestion-neo4j-build        # Build knowledge graph from chunks
make ingestion-qdrant-clear       # Clear embeddings collection
make ingestion-qdrant-delete    # Delete collection entirely
make ingestion-clean            # Remove __pycache__, logs
make ingestion-clean-all        # Reset all data/ folders
```

Every pipeline run produces:

| Category     | Metrics Tracked |
|--------------|-----------------|
| **Reliability** | Fallback activation rate, recovery time, MTBF, silent failures |
| **Performance** | p50/p95/p99 latency, throughput, stage breakdown, long‑tail analysis |
| **Cost**        | $/document, $/page, by provider, breakeven curves |
| **Quality**     | Recall@5, NDCG@5, entity accuracy, hallucination rate |

---

## Adding a New Data Source

1. **Create a config** in `config/app.yaml` under `data_acquisition.sources.{name}` following the existing source structure (`api`, `rate_limit`, `search`, `storage`, `processing`, `metrics`, `cost_tracking`).
2. **Register** the config path and fetcher class in `scripts/fetch_pdfs.py` (`_SOURCES` and `_FETCHERS` dicts).
3. **Implement a fetcher** inheriting `BaseFetcher`. Make `search()` `async` if it does HTTP calls — the orchestrator uses `inspect.iscoroutinefunction()` to route between `await` and sync calls.

```python
from src.fetchers.base import BaseFetcher, SearchRecord, FetchResult

class MySourceFetcher(BaseFetcher):
    async def search(self, query: str, max_results: int) -> list[SearchRecord]:
        # call your API
        ...

    async def fetch_pdf(self, record_id: str, pdf_type: str = "full") -> FetchResult | None:
        # download PDF bytes
        ...

    def generate_metadata(self, record: SearchRecord, pdf_type: str) -> dict:
        # return sidecar metadata dict
        ...
```

Metrics, storage failover, and manifests are handled automatically by the orchestrator.

---

## Testing

### Root project (pytest)

```bash
pip install -e ".[dev]"

pytest tests/ -v                                      # All tests
pytest tests/storage/test_aws_s3.py -v               # Single file
pytest -m "not integration" -v                        # Skip cloud-credential tests
pytest tests/storage/ --cov=src --cov-report=html    # With coverage
```

**Test markers:** `aws`, `azure`, `local`, `storage`, `integration`, `slow`.  
Integration tests call `pytest.skip()` when credentials are absent — they don't fail hard.

### Ingestion pipeline (standalone scripts)

```bash
make ingestion-qdrant-up   # Required: start Qdrant + Neo4j first

python src/ingestion-graphrag/tests/test_processors.py
python src/ingestion-graphrag/tests/test_qdrant.py
python src/ingestion-graphrag/tests/test_embedder.py
python src/ingestion-graphrag/tests/smoke_test.py
```

| Day | Incident                              | Resolution |
|-----|---------------------------------------|------------|
| 2   | S3 rate limiting                      | Exponential backoff |
| 5   | Azure DI cost spike ($50/day)         | Budget alerts + auto‑fallback |
| 8   | Slow spot termination detection       | Detection time 2 min → 30 s |
| 12  | Simultaneous cloud degradation        | Health checks + circuit breakers |
| 19  | Metadata schema drift                 | Version field + migration path |
| 24  | Qdrant OOM under load                 | Vector size monitoring + auto‑scaling |

---

## Contributing

Areas where contributions are welcome:

- Additional data source fetchers (OpenFDA, EuropePMC, WHO trials registry)
- Qdrant backup/restore automation
- Streaming ingestion via SQS FIFO (currently batch)
- Multi-tenant namespace isolation in Qdrant collections
- Grafana dashboard templates for cost-per-document tracking
- Additional chaos experiments

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## Documentation

> See Docs/
---

## License

MIT

---
