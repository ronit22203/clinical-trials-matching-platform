# Copilot Instructions

## Repository Overview

Monorepo for a clinical research AI platform. Four independent modules, each with its own Python environment or Node stack:

| Module | Purpose | Runtime |
|---|---|---|
| `agentic-reasoning/` | LangGraph ReAct + Temporal durable workflow engine for clinical queries | Python 3.12+ |
| `data-acquisition/` | Multi-source PDF fetcher (ClinicalTrials.gov, PubMed, bioRxiv, medRxiv) with multi-cloud storage | Python 3.12+ |
| `data-ingestion/` | 5-stage document pipeline: PDF → OCR → Markdown → Clean → Chunk → Embed (Qdrant + Neo4j) | Python 3.11.14 |
| `platform-ui/` | Next.js 16 App Router frontend; currently wired to static mock data only | Node / TypeScript |

End-to-end flow: `data-acquisition` fetches PDFs → `data-ingestion` processes them into Qdrant vectors + Neo4j graph → `agentic-reasoning` agents query both alongside public APIs → `platform-ui` visualises results.

---

## Commands

**Makefile topology:** there is one Makefile at the repo root. Do not use module-local Makefiles. Use root namespaced targets: `reasoning-*`, `acquisition-*`, and `ingestion-*`.

### agentic-reasoning

```bash
# Setup (from repo root)
make reasoning-install              # create venv if needed + pip install -e .

# Run
make reasoning-run                            # interactive CLI
make reasoning-run-query QUERY="..."          # single-shot, no Temporal
make reasoning-temporal-up                    # start Temporal infrastructure
make reasoning-temporal-worker                # start activity worker
make reasoning-temporal-run QUERY="..."       # durable workflow query
make reasoning-temporal-run-hitl QUERY="..."  # with human-in-the-loop gate

# Test
make reasoning-test                 # pytest tests/ -v
.venv/bin/python -m pytest tests/test_agent.py::TestClass::test_fn -v  # single test
```

### data-ingestion

```bash
# Setup (from repo root)
make ingestion-install

# Run pipeline
make ingestion-run                    # all 5 stages
make ingestion-run SKIP=ocr           # skip a stage (ocr|convert|clean|chunk|vectorize)

# Test
make ingestion-test                   # test suite
make ingestion-test-processors        # python tests/test_processors.py
make ingestion-test-embedder          # python tests/test_embedder.py
make ingestion-test-qdrant            # python tests/test_qdrant.py

# Infrastructure
make ingestion-qdrant-up              # start Qdrant
make ingestion-neo4j-build            # build knowledge graph from chunks
```

### data-acquisition

```bash
# Setup (from repo root)
make acquisition-install

# Fetch PDFs
make fetch SOURCE=medrxiv MAX_PDFS=10

# Test (storage tests)
make acquisition-test
```

### platform-ui

```bash
# Setup (from platform-ui/)
npm install
npm run dev    # http://localhost:3000 → redirects to /cases/990219
npm run build
```

---

## Architecture

### Configuration-First Design

All behaviour is defined in YAML — no hardcoded values in source code. Python source is infrastructure; YAML is policy.

- **Unified app config** (`config/app.yaml`): single non-secret source of truth for services, agent definitions, tool definitions, acquisition sources/storage, and ingestion settings

Pydantic v2 validates all YAML at load time; misconfigured files produce field-level errors before any execution begins.

### Dual Runtime (agentic-reasoning)

The same agent YAML drives two execution paths switchable via CLI flags:

- **LangGraph ReAct** (`--agent`): synchronous, LLM autonomously selects tools via `create_react_agent`. Suitable for low-latency interactive use.
- **Temporal Workflow** (`--use-temporal`): durable, parallel tool execution, full audit trail, optional HITL gate. All tool activities run concurrently via `asyncio.gather` inside `ClinicalResearchWorkflow.run()`.

### Tool Plugin System (agentic-reasoning)

Adding a new tool requires exactly two files:
1. `src/tools/implementations/<tool>.py` — subclass `BaseTool`, implement `execute(self, input: Any) -> Any`
2. `config/app.yaml` — add the tool definition under `agentic_reasoning.tools` with `name`, `module`, `class_name`, `config`, optionally `auth` and `enabled`

`ToolRegistry` loads tool definitions from `config/app.yaml` at startup. A tool that fails to load does not prevent others from loading (fault isolated).

`BaseTool` provides a `TTLCache` via `cached_execute()` — prefer this over `execute()` for repeated identical queries.

### Temporal Workflow Constraints

`agentic-reasoning/src/temporal/workflows.py` **must remain deterministic**. Rules:
- No I/O, logging, `random`, `time`, or non-deterministic calls inside `@workflow.run` or `@workflow.signal`/`@workflow.query` methods
- All side effects go in `activities.py` (`@activity.defn`)
- Use `workflow.unsafe.imports_passed_through()` for any non-deterministic import needed inside the workflow file

### Multi-Cloud Fallback (data-acquisition)

Provider chain: **S3 (priority 1) → Azure Blob (priority 2) → Local (priority 99)**

Chain order is defined in `config/app.yaml` under `data_acquisition.storage.providers`. Per-provider retry settings are defined in the same file. `MultiCloudStorageManager` tracks consecutive failures per provider and skips degraded ones.

### GraphRAG Retrieval (data-ingestion)

`HybridRetriever` combines Qdrant vector search with Neo4j graph traversal. In `agentic-reasoning`, the `graphrag_search` tool wraps this retriever and the synthesis prompt explicitly weights internal knowledge-base results as primary evidence over public API results.

### platform-ui Mock Data

All data in `platform-ui/src/lib/mock/` is fabricated for UI development. TypeScript interfaces in `src/lib/types/` are intentionally shaped to match the execution log JSON emitted by `agentic-reasoning` (`log/{execution_id}.json`). To wire live data: replace `src/lib/mock/` with `fetch("/api/…")` calls — the interfaces require no changes.

---

## Key Conventions

### Python Modules

- Each module has its own `.venv`; never share environments across modules.
- `agentic-reasoning` uses `src/` editable install (`pip install -e .`); others use `requirements.txt`.
- `data-acquisition` Python version is 3.12+; `data-ingestion` pins to 3.11.14 (check `.python-version`).
- Relative imports are used within packages (`from ..schemas.tool import ToolConfig`). Fetcher files use `try/except ImportError` for dual-mode support (package import vs. direct `python file.py` execution).
- `export PYTHONDONTWRITEBYTECODE=1` is set in `agentic-reasoning/Makefile` — replicate when running Python directly.

### Next.js (platform-ui)

Per `AGENTS.md`: **This Next.js version has breaking changes from common training data.** Before writing any Next.js code, check `node_modules/next/dist/docs/` for the current API. Heed deprecation notices. App Router conventions apply (`src/app/` with `page.tsx`, `layout.tsx`).

### Logging

Every `agentic-reasoning` execution produces:
- `log/{execution_id}.json` — full execution record
- `log/summary.jsonl` — append-only execution index

Always use structured logging via `logging_handler.py`. Do not use `print()` for observability in Python.

### Secrets and Env Vars

Copy `.env.example` → `.env` in each module that requires it. API keys are referenced by environment variable name in tool YAML (`auth.key: OPENFDA_API_KEY`). Never hardcode credentials in source or config files. `data-acquisition` resolves `${VAR}` patterns in config strings via `_resolve_env_vars()`.
