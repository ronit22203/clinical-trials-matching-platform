# Copilot Instructions

## Repository Overview

Monorepo for a local-first clinical research AI platform. Three active Python modules and a static UI:

| Module | Purpose | Runtime |
|---|---|---|
| `agentic-reasoning/` | Deterministic two-phase pipeline: GraphRAG retrieval → LLM synthesis | Python 3.12+ |
| `data-acquisition/` | Multi-source PDF fetcher (ClinicalTrials.gov, PubMed, bioRxiv, medRxiv) with multi-cloud storage | Python 3.12+ |
| `data-ingestion/` | 5-stage document pipeline: PDF → OCR → Markdown → Clean → Chunk → Embed (Qdrant + Neo4j) | Python 3.11.14 |
| `simple-ui/` | Standalone HTML/JS/CSS frontend; no build step | Static |

End-to-end flow: `data-acquisition` fetches PDFs → `data-ingestion` processes them into Qdrant vectors + Neo4j graph → `agentic-reasoning` queries both → `simple-ui` visualises results.

---

## Commands

**Makefile topology:** one Makefile at the repo root. Do not use module-local Makefiles. Use root namespaced targets: `reasoning-*`, `acquisition-*`, `ingestion-*`.

### agentic-reasoning

```bash
# Setup (from repo root)
make reasoning-install              # create .venv if needed + pip install -e .

# Run
make reasoning-run                            # interactive CLI
make reasoning-run-query QUERY="..."          # single-shot query

# SGLang backend alternative
make reasoning-sglang-run-query QUERY="..."   # SGLANG_BASE_URL=http://localhost:30000/v1

# Test
make reasoning-test                           # pytest tests/ -v
# Single test (from agentic-reasoning/ with .venv active):
.venv/bin/python -m pytest tests/test_agent.py::TestClass::test_fn -v
```

### data-ingestion

```bash
# Setup (from repo root)
make ingestion-install                        # pip install -r requirements.txt (no venv)

# Run pipeline
make ingestion-run                            # all 5 stages (default N=2 PDFs)
make ingestion-run N=10 SKIP=ocr             # with count and stage skip (ocr|convert|clean|chunk|vectorize)

# Test
make ingestion-test                           # pytest tests/ -v
make ingestion-test-processors               # python tests/test_processors.py (standalone script)
make ingestion-test-embedder                 # python tests/test_embedder.py
make ingestion-test-qdrant                   # python tests/test_qdrant.py

# Infrastructure
make ingestion-qdrant-up                     # start Qdrant (data-ingestion/infra/docker-compose.yaml)
make ingestion-neo4j-build                   # build knowledge graph from chunks

# Debugging
make ingestion-inspect                        # file counts at each pipeline stage
make ingestion-list-documents                # list tracked docs with UUIDs
make ingestion-compare-runs DOC=<uuid> EXEC1=<uuid> EXEC2=<uuid>
```

### data-acquisition

```bash
# Setup (from repo root)
make acquisition-install

# Fetch PDFs
make fetch SOURCE=medrxiv MAX_PDFS=10        # aliases acquisition-fetch

# Test (skips integration tests requiring cloud credentials)
make acquisition-test                         # pytest -m "not integration"
# Single test file:
cd data-acquisition && .venv/bin/python -m pytest tests/storage/test_aws_s3.py -v
```

### Benchmarking

```bash
make benchmark-all                            # full evaluation harness (RUN_DIR auto-generated)
make benchmark-retrieval                      # Recall@K, NDCG, MRR, HitRate
make benchmark-reasoning                      # two-phase agent evaluation (20 golden queries)
make benchmark-report RUN_DIR=benchmarking/results/<run>

# Full deterministic end-to-end run (wipe → ingest → KG → all benchmarks → manifest.json):
make deterministic-run
make deterministic-run BENCH_PDF=data/pdfs/my.pdf BENCH_RUNS=5

# Reranker override (blank = disabled):
make benchmark-retrieval RERANKER_MODEL="BAAI/bge-reranker-base"
```

### Infrastructure

```bash
make up                                       # start Neo4j + Qdrant (docker-compose.local.yml)
make down
make validate                                 # check LM Studio, Qdrant, Neo4j connectivity
make status                                   # running containers + artifact counts

make simple-ui-serve                          # serve simple-ui on localhost
```

---

## Architecture

### Configuration-First Design

All behaviour is defined in YAML — no hardcoded values in source code. Python source is infrastructure; YAML is policy.

- **`config/app.yaml`** — single non-secret source of truth: agent model/prompt/params, GraphRAG config, acquisition sources/storage, ingestion settings
- **`.env.local`** — ports, URLs, and secrets (gitignored; copy from `.env.local.example`)

Pydantic v2 validates all YAML at load time; misconfigured files produce field-level errors before any execution begins. `${VAR}` patterns in YAML strings are resolved via `os.path.expandvars` / `_expand_env_vars()` at config load time.

### Execution Model (agentic-reasoning)

**Deterministic two-phase pipeline — not dynamic agent routing:**

- **Phase 1 (mandatory):** `GraphRAGTool.cached_execute(query)` always runs before the LLM sees anything. No LLM routing decision.
- **Phase 2 (conditional):** If evidence was found, the LLM synthesises an answer grounded exclusively in that evidence. If `found=False`, a fixed "No evidence found" string is returned without invoking the LLM.

The `Agent` class (`src/agent.py`) is the sole entry point. It holds one `GraphRAGTool` instance. The strict system prompt in `config/app.yaml` prohibits parametric memory use when evidence is available.

### LLM Backends (agentic-reasoning)

`llm_factory.build_llm()` routes on the `provider/model-name` prefix in `config/app.yaml`:

| Prefix | Default URL | Override env var |
|---|---|---|
| `lmstudio/` | `http://localhost:1234/v1` | `LM_STUDIO_BASE_URL` |
| `ollama/` | `http://localhost:11434` | `LLM_BASE_URL` or `OLLAMA_BASE_URL` |
| `sglang/` | `http://localhost:30000/v1` | `SGLANG_BASE_URL` |

Default config model: `lmstudio/qwen3-8b`. Run `make validate` to check connectivity.

### GraphRAGTool

`src/tools/graphrag.py` — hybrid retrieval combining Qdrant semantic search with Neo4j graph traversal:
1. Encode query with `BAAI/bge-small-en-v1.5` → vector search Qdrant collection
2. Optional CrossEncoder reranker (configured via `reranker_model` in `config/app.yaml`)
3. Extract keywords → Cypher query Neo4j for `(h)-[r]->(t)` triples
4. Returns `{"found": bool, "vector_results": [...], "graph_facts": [...]}`

All clients (Qdrant, Neo4j, embedder, reranker) are lazy-initialised on first use. `BaseTool.cached_execute()` provides a TTL cache — always prefer this over `execute()` for repeated queries.

### Multi-Cloud Fallback (data-acquisition)

Provider chain: **S3 (priority 1) → Azure Blob (priority 2) → Local (priority 99)**

Chain order and per-provider retry settings are in `config/app.yaml` under `data_acquisition.storage.providers`. `MultiCloudStorageManager` tracks consecutive failures per provider and skips degraded ones. Metadata sidecars stored as `{key}.metadata.json`.

### 5-Stage Ingestion Pipeline (data-ingestion)

```
data/pdfs/raw/      →  [1] Surya OCR          →  data/artifacts/extract/
                    →  [2] SuryaConverter      →  data/artifacts/convert/
                    →  [3] TextCleaner + PII   →  data/artifacts/clean/
                    →  [4] MarkdownChunker     →  data/artifacts/chunk/
                    →  [5] MedicalVectorizer   →  Qdrant (localhost:6333)
                                               +  Neo4j (via build_knowledge_graph.py)
```

Each stage persists intermediate files for debugging (`make ingestion-inspect`). Every run is fingerprinted in `data/determinism.db` (SHA-256 per-stage output hashes + environment).

**PII redaction** (Stage 3): Presidio with custom recognisers for Singapore NRIC (`[STFG]\d{7}[A-Z]`) and MCR numbers (`\d{6}`). Controlled by `cleaning.remove_pii` in `config/app.yaml`.

**Chunking** (Stage 4): `MarkdownChunker` creates hierarchical parent-child chunks preserving document structure. Each chunk carries `content` (with breadcrumb prefix `"Context: A > B\n\n"`), `context`, `level`, `parent_id`, `depth`, `section_title`.

**Embedding model**: `BAAI/bge-small-en-v1.5` (384 dimensions). Must match exactly between ingestion and retrieval. Auto-detects MPS (Apple Silicon) or CUDA.

---

## Key Conventions

### Python Environments

- Each module has its own `.venv`; never share environments across modules.
- `agentic-reasoning` and `data-acquisition` use editable installs (`pip install -e .`); `data-ingestion` uses `requirements.txt` with system `python3` (no venv).
- `data-acquisition` Python 3.12+; `data-ingestion` pins to 3.11.14 (see `.python-version`).
- Within packages, use relative imports (`from ..schemas.tool import ToolConfig`). Fetcher files use `try/except ImportError` for dual-mode (package vs direct `python file.py`).

### Adding a New Data Source (data-acquisition)

1. Add `data_acquisition.sources.{name}` to `config/app.yaml` following existing structure.
2. Register in `scripts/fetch_pdfs.py` `_SOURCES` and `_FETCHERS` dicts.
3. Implement class inheriting `BaseFetcher`. Make `search()` `async` if it does HTTP calls — `fetch_pdfs.py` uses `inspect.iscoroutinefunction()` to route; do not call `asyncio.run()` inside a sync `search()` as the script already runs inside `asyncio.run()`.

### Adding a New Ingestion Processor

Inherit `BaseExtractor` from `src/extractors/base.py` (must return `{'content': str, 'metadata': dict}`). For clean/chunk stages, follow `TextCleaner`/`MarkdownChunker` pattern in `src/processors/`.

### Logging

`agentic-reasoning` structured logging via `src/logging_handler.py`. Do not use `print()` for observability. Execution logs: `agentic-reasoning/log/{execution_id}.json` (full) + `log/summary.jsonl` (append-only index).

`data-ingestion` pipeline logs to `data/artifacts/ingestion.log`.

### Secrets and Env Vars

Copy `.env.local.example` → `.env.local` at repo root. Module-level secrets are also in `{module}/.env` where applicable. API keys referenced by env var name in YAML (`auth.key: OPENFDA_API_KEY`). Never hardcode credentials.

`data-acquisition` integration tests call `pytest.skip()` when cloud credentials are absent — run `make acquisition-test` (which adds `-m "not integration"`) to avoid failures without credentials.

### Benchmarking

`benchmarking/` evaluators use the reasoning module's `.venv` (`BENCH_PYTHON` in Makefile). Golden query set: `benchmarking/golden/queries.json`. Results written to `benchmarking/results/run_{date}_{hash}/`. `make deterministic-run` is the canonical way to produce a reproducible, fully-annotated manifest.
