# Healthcare Platform

**Local-first, open‑source clinical trial matching.**
No API keys. No cloud. Just `git clone` + `docker-compose up`.

also a space heater that occasionally outputs a JSON file

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Made with Python](https://img.shields.io/badge/Python-3.12-blue)](https://python.org)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED)](https://docker.com)
![Compliance: HIPAA Aligned](https://img.shields.io/badge/Compliance-HIPAA--Aligned-green)
---

watch the [demo video](https://www.ronitsaxena.in/projects/clinical-trial-matching-api/) or read on for setup instructions, architecture overview, and troubleshooting tips.

---

## What this repository is (and isn't)

This is a **local-first, consolidated quickstart** — not the production codebase.

The production infrastructure is intentionally split across specialized repositories. Each one is optimized for a single concern and independently deployable. This monorepo exists so that anyone can run the full end-to-end system on a laptop with a single `git clone`, without configuring cloud credentials, GPU hardware, or distributed infrastructure.

| This module | Origin repo | What was simplified for local |
|---|---|---|
| `agentic-reasoning` | [`clinical-graphrag-agents`](https://github.com/ronit22203/clinical-graphrag-agents) | Temporal durable workflows and LangGraph routing replaced by a deterministic two-phase pipeline (ADR-008) |
| `data-ingestion` | [`ingestion-layer-graphrag`](https://github.com/ronit22203/ingestion-layer-graphrag) | AWS GPU-accelerated OCR (g4dn/T4) swapped for local Surya (MPS/CPU) |
| `data-acquisition` | [`aws-data-acquisition`](https://github.com/ronit22203/aws-data-acquisition) | Multi-cloud S3 → Azure fallback chain still present; S3/Azure credentials optional |
| LLM inference | [`core-llm-inference`](https://github.com/ronit22203/core-llm-inference) | SGLang production engine (RTX 5080, continuous batching) swapped for LM Studio or Ollama locally |

Architecture decisions and failure register: [`clinical-platform-manifest`](https://github.com/ronit22203/clinical-platform-manifest).

## Quickstart (5 minutes)

```bash
git clone https://github.com/ronit22203/healthcare-platform
cd healthcare-platform
make bootstrap          # checks dependencies + creates .env.local
make up                 # starts Neo4j, Qdrant
make fetch MAX_PDFS=5   # downloads sample PDFs
make ingest             # OCR → chunk → embed → graph
make reasoning-run-query QUERY="What biomarkers predict sepsis mortality?"
```

---

## Architecture (4 modules)

| Module | What it does |
|--------|--------------|
| `data-acquisition` | Fetches PDFs from medRxiv, PubMed, ClinicalTrials |
| `data-ingestion` | OCR (Surya) → PII redaction → chunking → Qdrant + Neo4j |
| `agentic-reasoning` | Deterministic two-phase pipeline: GraphRAG retrieval → LLM synthesis (LM Studio / SGLang / Ollama) |
| `palantir-blueprint` | React + Blueprint.js dashboard for clinicians (Vite, hot-reload) |

---

## Services

| Service | URL | Credentials |
|---------|-----|-------------|
| Neo4j Browser | <http://localhost:7474> | - |
| Qdrant Dashboard | <http://localhost:6333/dashboard> | – |
| Reasoning API | <http://localhost:8000> | – |
| UI Dev Server | <http://localhost:5173> | – |

---

## Make targets

All `make` commands now live in the **repo root**. For module-level control, use the namespaced targets: `reasoning-*`, `acquisition-*`, and `ingestion-*`.

```bash
make up                         # start shared Docker services
make fetch MAX_PDFS=5           # download PDFs
make ingestion-run N=5          # run the ingestion pipeline directly
make reasoning-run-query QUERY="..."  # one-shot reasoning query
make reasoning-serve-api        # start the FastAPI backend
make blueprint-dev              # start the Blueprint.js UI dev server (:5173)
make help                       # list the full root control surface
```

---

## Configuration

- **`config/app.yaml`** – the single non-secret source of truth for ingestion, acquisition, and agent/tool config
- **`.env.local`** – ports, URLs, secrets (gitignored; copy from `.env.local.example`)

Change any setting → rerun `make ingest` – deterministic rebuild.

---

## Prerequisites

- [Docker Desktop](https://docker.com) (Compose v2)
- Python 3.12+ + Node.js 20+
- LLM backend — pick one:
  - **[LM Studio](https://lmstudio.ai)** (default; local, no GPU required)
  - **[SGLang](https://github.com/sgl-project/sglang)** (production; recommended for GPU, e.g. RTX 5080)
  - **[Ollama](https://ollama.ai)** (`brew install ollama`) — alternative

### LM Studio / Ollama models

Pull `qwen3:8b` (reasoning) for whichever backend you use. The model name is set in `config/app.yaml` — prefix it with `lmstudio/`, `sglang/`, or `ollama/` to select the backend:

```yaml
# config/app.yaml
agent:
  model: "lmstudio/qwen3-8b"   # or sglang/qwen3-8b, ollama/qwen3:8b
```

---

## Troubleshooting (common)

**Port conflict?**
`lsof -i :7474` (Neo4j) / `:6333` (Qdrant) / `:8000` (API) / `:5173` (UI)

**Neo4j password mismatch?**
`docker compose -f docker-compose.local.yml down -v && make up`

**LLM backend not responding?**
- LM Studio: ensure the server is running on `http://localhost:1234/v1`
- SGLang: `SGLANG_BASE_URL=http://localhost:30000/v1` (set in `.env.local`)
- Ollama: `ollama serve` (in a separate terminal)

**UI shows stale data?**
Ensure the reasoning API (`:8000`) and ingestion API (`:8001`) are running, then hard-refresh the browser. Copy `palantir-blueprint/.env.local.example` → `.env.local` and check the `VITE_API_*` URLs match your setup.

---

## Data layout

```
data/
├── pdfs/          # raw PDFs (input)
├── artifacts/     # ocr/, markdown/, cleaned/, chunks/
├── neo4j/         # graph DB
└── qdrant/        # vector DB
```

---

## Built with

- **Surya OCR** (MPS/CPU)
- **Qdrant** (vector search)
- **Neo4j** (graph reasoning)
- **LM Studio / SGLang / Ollama** (local LLM inference — model-agnostic via `config/app.yaml`)

---

# Issues

Infrastructure is heavy (multiple Docker services) → consider lightweight alternatives for local dev.

It is big and slow

Might be overkill for simple use cases → modular design allows swapping components, currently focusing on simplification and product reliability. Collaboration welcome

## License

MIT – use it, break it, improve it.

---

**Questions?** Open an issue or reach out.
`CHPA®` · `AI-102` · `DP-100` – compliant by design.
