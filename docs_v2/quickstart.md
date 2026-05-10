# Quickstart

## Prerequisites

| Requirement | Minimum Version | Notes |
|-------------|----------------|-------|
| Docker Desktop | 4.x (Compose v2) | `docker compose version` must succeed |
| Python | 3.11.14 (ingestion) / 3.12+ (reasoning, acquisition) | Use `pyenv` to manage versions |
| Node.js | 18+ | Required for `platform-ui` |
| LM Studio | 0.3+ | Provides local LLM inference on port 1234 |
| Make | GNU Make | Pre-installed on macOS/Linux |

---

## Step 1 — Clone and configure

```bash
git clone https://github.com/ronit22203/clinical-trials-matching-platform
cd clinical-trials-matching-platform
```

Copy environment files for each module that requires them:

```bash
cp data-ingestion/.env.example data-ingestion/.env
cp agentic-reasoning/.env.example agentic-reasoning/.env
cp platform-ui/.env.local.example platform-ui/.env.local
```

Edit each `.env` to match your environment. At minimum, set:

```bash
# All modules share these (via config/app.yaml env-var substitution)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=testpassword
QDRANT_URL=http://localhost:6333
LM_STUDIO_BASE_URL=http://localhost:1234/v1
```

---

## Step 2 — Start infrastructure

```bash
make up
```

This starts Neo4j and Qdrant via Docker Compose. Wait for all health checks to pass (~30 seconds).

Verify:

```bash
make validate
```

Expected output: all services `✓ reachable`.

---

## Step 3 — Install dependencies

```bash
make bootstrap
```

This creates per-module Python virtual environments and installs all dependencies. Node modules for `platform-ui` are also installed.

---

## Step 4 — Load a model in LM Studio

Launch LM Studio, download **Qwen3-8B** (Q5_K_S quantisation, ~5 GB), and start the local server on port `1234`.

The model identifier in LM Studio must match `config/app.yaml`:

```yaml
agentic_reasoning:
  defaults:
    model: lmstudio/qwen3-8b
```

Verify inference is available:

```bash
curl http://localhost:1234/v1/models
```

---

## Step 5 — Fetch and ingest documents

```bash
make fetch SOURCE=medrxiv MAX_PDFS=3
make ingest N=3
```

`make ingest` runs the full six-stage pipeline:

1. OCR (Surya)
2. Markdown conversion
3. PII cleaning
4. Chunking
5. Qdrant vectorisation
6. Neo4j KG extraction

Monitor progress in the terminal. On an M4 MacBook, expect ~3–5 minutes per document for the full pipeline.

Check results:

```bash
make status                    # shows container status and artifact counts
make ingestion-neo4j-stats     # shows node and relationship counts in Neo4j
```

---

## Step 6 — Start the API and UI

```bash
make serve
```

This starts:
- FastAPI reasoning server at `http://localhost:8000`
- Next.js UI at `http://localhost:3000`

Navigate to `http://localhost:3000/cases/990219` to open the case view.

---

## Step 7 — Run a query

In the UI chat panel, type a query such as:

```
Do sepsis early-warning systems detect biological signal or care-process intensity?
```

Or from the terminal:

```bash
make reasoning-run-query QUERY="What biomarkers predict sepsis mortality?"
```

---

## Verify the full stack

```bash
curl -s -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is AUROC?", "mode": "langgraph"}' \
  | jq '{synthesis: .synthesis[:120], tools: .executionLog.toolsCalled}'
```

Expected: non-empty `synthesis` and at least one entry in `toolsCalled`.

---

## Common issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `make validate` fails on Neo4j | Password mismatch from previous install | `docker compose -f docker-compose.local.yml down -v && make up` |
| `No chunks found` on ingest | `data/artifacts/chunk/` empty | Run `make fetch` first, or check that PDFs landed in `data/pdfs/` |
| LM Studio 400 on KG extraction | `response_format` type mismatch | Ensure `config/app.yaml` knowledge_graph section does not set `response_format: {type: json_object}` |
| `asyncio.run() cannot be called from a running event loop` | Sync `asyncio.run()` inside FastAPI endpoint | Ensure `agent.run_parallel()` is `async def` and is `await`ed in `server.py` |
| UI shows no evidence after query | `NEXT_PUBLIC_USE_MOCK=true` | Set `NEXT_PUBLIC_USE_MOCK=false` in `platform-ui/.env.local` |
| Port conflict | Another process on 7474 / 6333 / 8000 / 3000 | `lsof -i :<port>` to identify and stop the conflicting process |

---

## Teardown

```bash
make down               # stop Docker services (preserve data volumes)
make clean-hard         # wipe ALL state — artifacts, vectors, graph
```
