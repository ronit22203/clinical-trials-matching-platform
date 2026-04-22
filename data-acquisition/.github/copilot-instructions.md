# Copilot Instructions

## Repository Overview

**Makefile topology:** use the single repo-root Makefile. The module-local Makefile is gone; use `make acquisition-*` for setup/tests and `make fetch SOURCE=<name> MAX_PDFS=<n>` for retrieval.

Two co-located but independent sub-projects:

1. **Root (`src/fetchers/`, `src/storage/`, `tests/`, `scripts/`)** — Multi-cloud PDF fetching layer. Fetches PDFs from ClinicalTrials.gov, bioRxiv, medRxiv, and PubMed; stores them in AWS S3 (primary) → Azure Blob (fallback) → local disk. Uses `pyproject.toml`, requires Python 3.12+.

2. **`src/ingestion-graphrag/`** — Historical MARA ingestion notes. Active ingestion now lives in the top-level `data-ingestion/` module and is controlled from the repo root Makefile via `make ingestion-*`.

---

## Build, Test, and Lint

### Root project

```bash
pip install -e ".[dev]"

pytest tests/ -v                                    # All tests
pytest tests/storage/test_aws_s3.py -v             # Single file
pytest -m "not integration" -v                     # Skip cloud-credential tests
pytest tests/storage/ --cov=src --cov-report=html  # With coverage
```

**Test markers** (defined in `pyproject.toml`): `aws`, `azure`, `local`, `storage`, `integration`, `slow`.  
Integration tests call `pytest.skip()` when credentials are absent — they don't fail hard.

**Required env vars for integration tests:**
```bash
export AWS_PROFILE=clinical-trials-fetcher
export AWS_DEFAULT_REGION=ap-south-1
export AZURE_STORAGE_CONNECTION_STRING="..."
```

Alternatively, put these in a `.env` file at the repo root — `scripts/fetch_pdfs.py` loads it automatically at startup (no external dependency). Shell env vars take precedence over `.env` values.

### Ingestion pipeline (`src/ingestion-graphrag/`)

Tests are **standalone scripts**, not pytest:

```bash
make acquisition-install    # Install acquisition dependencies
make acquisition-test       # Run acquisition tests
make ingestion-qdrant-up    # Start Qdrant if downstream ingestion tests need it

python src/ingestion-graphrag/tests/test_processors.py   # Single test script
python src/ingestion-graphrag/tests/test_qdrant.py
python src/ingestion-graphrag/tests/test_embedder.py
python src/ingestion-graphrag/tests/smoke_test.py

make fetch SOURCE=medrxiv MAX_PDFS=10   # Fetch sample PDFs
make ingestion-run N=10                 # Run the active ingestion pipeline
make ingestion-inspect                  # File counts + samples at each stage

make ingestion-qdrant-clear           # Clear embeddings collection
make ingestion-qdrant-delete          # Delete collection entirely
make ingestion-neo4j-build            # Build knowledge graph from chunks

make ingestion-list-documents
make ingestion-list-executions DOC=<uuid>
make ingestion-compare-runs DOC=<uuid> EXEC1=<uuid> EXEC2=<uuid>

make ingestion-clean        # Remove __pycache__, logs
make ingestion-clean-all    # Reset all data/ folders
```

---

## Architecture

### Root: Fetching + Multi-Cloud Storage

**Config-driven**: historical per-source/storage YAML references in this document now resolve to the unified `../config/app.yaml`. Do not hardcode any of this in code.

**Fetcher pattern** (`src/fetchers/base.py` → `BaseFetcher`):
- `search(query, max_results)` → `list[SearchRecord]`  — **must be `async`** for HTTP-based fetchers (medRxiv, ClinicalTrials, PubMed); `fetch_pdfs.py` uses `inspect.iscoroutinefunction()` to route between `await fetcher.search()` and sync call. Making a sync `search()` call `asyncio.get_event_loop().run_until_complete()` internally will fail because `fetch_pdfs.py` already runs inside `asyncio.run()`.
- `fetch_pdf(record_id, pdf_type)` → `Optional[FetchResult]`
- `generate_metadata(record, pdf_type)` → `dict`
- `cleanup()` — removes temp files tracked via `_track_temp_file()`

**Currently registered sources** (in `scripts/fetch_pdfs.py` `_SOURCES` / `_FETCHERS`):
| `--source` | Config | Fetcher |
|---|---|---|
| `clinical_trials` | `config/app.yaml → data_acquisition.sources.clinical_trials` | `ClinicalTrialsFetcher` |
| `biorxiv` | `config/app.yaml → data_acquisition.sources.biorxiv` | `BioRxivFetcher` |
| `medrxiv` | `config/app.yaml → data_acquisition.sources.medrxiv` | `MedRxivFetcher` |
| `pubmed` | `config/app.yaml → data_acquisition.sources.pubmed` | `PubMedFetcher` |

**Source-specific notes:**
- **bioRxiv**: uses the `arxiv` Python library; `search()` is sync; identifier = arXiv short ID (e.g. `2301.12345v1`).
- **medRxiv**: uses medRxiv REST API (`api.medrxiv.org/details/medrxiv/{start}/{end}/{cursor}/json`); date-range scan + client-side keyword filter; `search()` is `async`; identifier = DOI (e.g. `10.1101/2025.09.25.25336651`). DOIs contain `/` — replace with `_` in S3 key path components.

**Storage pattern** (`src/storage/base.py` → `BaseStorageProvider`): async interface — `initialize()`, `store()`, `retrieve()`, `exists()`, `delete()`, `store_metadata()`. Metadata sidecars stored as `{key}.metadata.json`. Failover chain: AWS S3 (ap-south-1, directory bucket) → Azure Blob (centralindia) → local disk.

**Storage tiers** (`src/storage/manager.py` → `MultiCloudStorageManager`): orchestrates failover. Configuration flows exclusively from `config/app.yaml` under `data_acquisition.storage` — do not hardcode bucket/container names. `${ENV_VAR}` patterns in YAML values are resolved via `os.path.expandvars`.

**S3 bucket**: `<your-bucket-name>` (S3 Express One Zone / directory bucket format — set via `config/app.yaml`).

**Storage path prefixes** (by source): `raw/biorxiv/`, `raw/medrxiv/`, `raw/clinical_trials/`.

### Ingestion Layer: 5-Stage MARA Pipeline

```
data/raw/*.pdf
  → [Stage 1] Surya OCR       → data/ocr/*_ocr.json + debug PNGs
  → [Stage 2] Converter       → data/markdown/*_converted.md
  → [Stage 3] TextCleaner     → data/cleaned/*_cleaned.md
  → [Stage 4] MarkdownChunker → data/chunks/*_chunks.json
  → [Stage 5] MedicalVectorizer → Qdrant (localhost:6333)
```

Orchestrator: `../data-ingestion/scripts/run_pipeline.py`  
Config: `../config/app.yaml`  
Docker: `../data-ingestion/infra/docker-compose.yaml`

**Module layout** (`src/ingestion-graphrag/src/`):
```
extractors/base.py           # BaseExtractor ABC
extractors/pdf_marker_v2.py  # Stage 1: Surya OCR
extractors/surya_converter.py # Stage 2: OCR JSON → Markdown
processors/cleaner.py        # Stage 3: TextCleaner + PII redaction
processors/chunker.py        # Stage 4: MarkdownChunker
storage/embedder.py          # Stage 5: MedicalVectorizer + ConfigLoader
storage/qdrant_manager.py    # Qdrant CRUD & stats
retrieval/hybrid.py          # HybridRetriever: vector + Neo4j graph
determinism.py               # DeterminismTracker: SQLite fingerprinting
```

**Determinism tracking** (`determinism.py`): each run recorded in `data/determinism.db` with document UUIDs (deterministic SHA-256 of filename), execution UUIDs (random), per-stage SHA-256 output hashes, and environment fingerprints. Artifacts stored content-addressably at `data/artifacts/{stage}/{hash[:2]}/{hash}.ext`.

### Bulk Fetch Scripts (`utils/`)

```bash
# Bulk fetch 500 PDFs from bioRxiv (arXiv), resumable
python utils/generate_500_pdfs.py --target 500
python utils/generate_next_batch_v2.py --target 500   # Next batch variant

# Bulk fetch 500 PDFs from medRxiv, resumable
python utils/generate_500_pdf_medrxiv.py --target 500 --dry-run

# Parse logs and manifests into a report
python utils/data_from_fetch.py                       # Combined report (all sources)
python utils/data_from_fetch.py --source medrxiv      # Single-source filter
python utils/data_from_fetch.py --stats               # Summary only
python utils/data_from_fetch.py --export json         # JSON export
python utils/data_from_fetch.py --by-keyword          # Per-keyword table
```

**DOI deduplication files**: `temp/fetched_arxiv_ids.txt` (arXiv IDs for bioRxiv), `temp/fetched_medrxiv_dois.txt` (DOIs for medRxiv). Bulk scripts load these on startup to skip already-fetched papers.

**Manifests**: `scripts/fetch_pdfs.py` writes per-run JSON manifests to `temp/manifests/{trace_id}.json`. `data_from_fetch.py` uses these to supplement `logs/pipeline.log` for sources (like medRxiv) whose subprocess output doesn't appear in the log file.

**Log formats differ by source**: bioRxiv subprocess logs appear in `pipeline.log` with format `HH:MM:SS  INFO  logger  message`. medRxiv's outer script logs use `YYYY-MM-DD HH:MM:SS,mmm [LEVEL] message` — only the outer script messages appear in the log; per-document data comes from manifests.

---

## Key Conventions

### Adding a new data source

1. Add `data_acquisition.sources.{name}` to `../config/app.yaml` following the existing source structure (`api`, `rate_limit`, `search`, `storage`, `processing`, `metrics`, `chaos`, `cost_tracking`).
2. Register config path and fetcher class in `scripts/fetch_pdfs.py` `_SOURCES` and `_FETCHERS` dicts.
3. Implement a class inheriting `BaseFetcher` in `src/fetchers/`. Make `search()` `async` if it does HTTP calls.
4. Constructor receives the full config dict; access via `self.config`, `self.api_config`, `self.rate_limit_config`, `self.storage_config`.

### Adding a new storage provider

Inherit `BaseStorageProvider` from `src/storage/base.py`. Use `_generate_metadata_key(key)` for sidecar paths. `StorageResult.fallback_chain` records which providers were attempted. Register in `MultiCloudStorageManager.from_configs()` and `../config/app.yaml`.

### Adding a new ingestion extractor

Inherit `BaseExtractor` from `src/ingestion-graphrag/src/extractors/base.py`. Must return `{'content': str, 'metadata': dict}`. For processors (clean/chunk), follow `TextCleaner`/`MarkdownChunker` pattern instead.

### Chunker output format

Each chunk dict: `content` (with `"Context: A > B\n\n"` breadcrumb prepended), `context` (breadcrumb string), `level` (header depth), `chunk_index`, `parent_id`, `depth`, `section_title`. Never split atomic blocks (lists, code).

### PII Redaction (ingestion Stage 3)

Uses Presidio with custom recognizers for Singaporean medical data (defined in `settings.yaml`):
- `SG_NRIC`: `[STFG]\d{7}[A-Z]`
- `MCR_NO`: `\d{6}`

Controlled by `cleaning.remove_pii` in `settings.yaml`, or `TextCleaner(remove_pii=False)`. Set `fail_safe_on_pii_error: true` to return original text on Presidio errors.

### ConfigLoader (ingestion)

```python
from src.storage.embedder import ConfigLoader
config = ConfigLoader.load(config_path)  # Falls back to ../config/app.yaml if None
```

### Test data hygiene

Test objects in cloud storage are prefixed `test-{uuid}/` and cleaned up after each test. Use `StorageTestUtils` helpers rather than hardcoding keys.

### Embedding model

`BAAI/bge-small-en-v1.5` (384 dimensions). Auto-detects MPS (Apple Silicon) or CUDA. Adjust `batch_size` in `settings.yaml` if OOM.

### Benchmarking retrieval quality

`src/ingestion-graphrag/benchmarking/evaluator.py` runs recall@k against `golden.json`. Requires Qdrant running with the `medical_papers` collection populated. Uses the same `BAAI/bge-small-en-v1.5` model — must match the ingestion model exactly.

### Ingestion pipeline documentation

Detailed docs live in `src/ingestion-graphrag/docs/`: `architecture.md`, `data_flow.md`, `determinism.md`, `processor.md`, `storage.md`, `retrieval.md`, `debugging.md`, `extractor.md`.
