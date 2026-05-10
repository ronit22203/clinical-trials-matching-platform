# Make Reference

All make targets are defined in the repository root `Makefile`. Module-level tasks are namespaced (`reasoning-*`, `ingestion-*`, `acquisition-*`) to prevent collisions. Do not create or modify module-level Makefiles.

---

## Root Orchestration

| Target | Description |
|--------|-------------|
| `make help` | List all available targets |
| `make status` | Show Docker container states and artifact counts |
| `make validate` | Check `.env`, LM Studio, Qdrant, and Neo4j connectivity |
| `make bootstrap` | Create Python venvs and install all module dependencies |
| `make up` | Start shared Docker infrastructure (Neo4j, Qdrant) |
| `make down` | Stop Docker services (data volumes are preserved) |

---

## Platform Entry Points

| Target | Description |
|--------|-------------|
| `make serve` | Start FastAPI API (port 8000) and Next.js UI (port 3000) together |
| `make serve-api` | Alias for `reasoning-serve-api` |
| `make serve-ui` | Alias for `ui-dev` |

---

## Data Acquisition

| Target | Parameters | Description |
|--------|------------|-------------|
| `make fetch` | `SOURCE=<name> MAX_PDFS=<n>` | Fetch PDFs via `data-acquisition` |
| `make acquisition-install` | — | Create acquisition venv and install package |
| `make acquisition-fetch` | `SOURCE=<name> MAX_PDFS=<n>` | Fetch PDFs (direct target) |
| `make acquisition-source-search` | `SOURCE=<name> SEARCH_QUERY=...` | Search a source fetcher |
| `make acquisition-source-fetch` | `SOURCE=<name> RECORD_ID=... PDF_TYPE=paper\|supplementary` | Fetch a single record |
| `make acquisition-source-validate` | `SOURCE=<name>` | Validate a source fetcher |
| `make acquisition-test` | — | Run acquisition storage and unit tests |

**Source names:** `medrxiv`, `biorxiv`, `pubmed`, `clinicaltrials`

---

## Data Ingestion

### Setup and pipeline

| Target | Parameters | Description |
|--------|------------|-------------|
| `make ingest` | `N=<max-pdfs>` | Run full 6-stage pipeline then build knowledge graph |
| `make ingestion-install` | — | Install ingestion dependencies |
| `make ingestion-run` | `N=<max-pdfs> SKIP=<stage>` | Run pipeline, optionally skipping a stage |

**SKIP values:** `ocr`, `convert`, `clean`, `chunk`, `vectorize`

### Infrastructure

| Target | Description |
|--------|-------------|
| `make ingestion-qdrant-up` | Start Qdrant (ingestion instance) |
| `make ingestion-qdrant-down` | Stop Qdrant |
| `make ingestion-qdrant-logs` | Stream Qdrant logs |

### Knowledge graph

| Target | Description |
|--------|-------------|
| `make ingestion-neo4j-build` | Run KG extraction on existing chunks (no re-OCR) |
| `make ingestion-neo4j-stats` | Show node and relationship counts |
| `make ingestion-neo4j-delete` | Delete all Neo4j knowledge graph data |

### Inspection and audit

| Target | Parameters | Description |
|--------|------------|-------------|
| `make ingestion-inspect` | — | Summary of all artifact directories |
| `make ingestion-list-documents` | — | Registry of tracked documents |
| `make ingestion-list-executions` | `DOC=<uuid>` | List pipeline executions for a document |
| `make ingestion-compare-runs` | `DOC=<uuid> EXEC1=<uuid> EXEC2=<uuid>` | Diff two pipeline runs |

### Tests

| Target | Description |
|--------|-------------|
| `make ingestion-test` | Run full ingestion test suite |
| `make ingestion-test-processors` | Run processor unit tests |
| `make ingestion-test-embedder` | Run embedder tests |
| `make ingestion-test-qdrant` | Run Qdrant integration tests |

---

## Agentic Reasoning

### Setup and runtime

| Target | Parameters | Description |
|--------|------------|-------------|
| `make reasoning-install` | — | Create venv and install package |
| `make reasoning-run` | `AGENT=<name>` | Interactive CLI (LangGraph) |
| `make reasoning-run-query` | `QUERY="..."` | Single query (LangGraph) |
| `make reasoning-serve-api` | — | Start FastAPI server on port 8000 |

### SGLang variants

| Target | Description |
|--------|-------------|
| `make reasoning-sglang-run` | Interactive CLI against SGLang backend |
| `make reasoning-sglang-run-query` | Single query via SGLang |

### Services

| Target | Description |
|--------|-------------|
| `make reasoning-services-up` | Start all reasoning-local services |
| `make reasoning-services-down` | Stop all reasoning-local services |
| `make reasoning-graphrag-up` | Start only Qdrant and Neo4j (GraphRAG dependencies) |
| `make reasoning-graphrag-down` | Stop GraphRAG backing services |

### Tests and utilities

| Target | Description |
|--------|-------------|
| `make reasoning-test` | Run pytest suite |
| `make reasoning-download-models` | Download local models for reasoning |

---

## Platform UI

| Target | Description |
|--------|-------------|
| `make ui-install` | Install Node dependencies |
| `make ui-dev` | Start dev server (port 3000, hot reload) |
| `make ui-build` | Production build |
| `make ui-start` | Build (if needed) and start in production mode |

---

## Cleanup

| Target | Description | Destructive? |
|--------|-------------|-------------|
| `make clean` | Remove ingestion caches and logs | No |
| `make clean-all` | Remove all ingestion data outputs | Yes |
| `make clean-artifacts` | Remove all generated repo-wide artifacts | Yes |
| `make clean-ocr` | Remove OCR outputs only | Yes |
| `make clean-md` | Remove Markdown and cleaned outputs | Yes |
| `make clean-chunks` | Remove chunk outputs | Yes |
| `make clean-vectors` | Delete the Qdrant collection | Yes |
| `make clean-graph` | Delete all Neo4j graph data | Yes |
| `make clean-hard` | Wipe ALL state — artifacts, vectors, graph | **Destructive** |

---

## Benchmarks

| Target | Description |
|--------|-------------|
| `make benchmark-sepsis` | Run the Sepsis Falsification paper through the full pipeline and query the agent end-to-end |

---

## Adding a Target

All targets live in the root `Makefile`. Follow this pattern:

```makefile
my-target: ## One-line description shown in make help
	@echo "Running my-target"
	cd my-module && $(MAKE) internal-target
```

The `## comment` is required — `make help` parses it to build the help table.
