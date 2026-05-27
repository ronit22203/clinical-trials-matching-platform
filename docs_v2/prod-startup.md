# Production Startup Guide — Ubuntu 22.04 + NVIDIA L4

This guide covers standing the platform up from scratch on a headless Ubuntu 22.04 server with
an NVIDIA L4 GPU (Ada Lovelace, 23 GB VRAM). It replaces the [Quickstart](quickstart.md)
macOS-centric flow: no LM Studio, no Ollama, no Docker daemon required.

---

## Hardware assumptions

| Spec | Value |
|------|-------|
| OS | Ubuntu 22.04.5 LTS |
| CPU | AMD EPYC 9254 (48 threads) or equivalent |
| GPU | NVIDIA L4 — sm_89, 23 034 MiB VRAM, 300 GB/s |
| CUDA driver | 580+ (CUDA 12.x / 13.x) |
| Inference backend | SGLang via `core-llm-inference` |
| Infrastructure | Native binaries (no Docker daemon) |

---

## Phase 0 — One-time prerequisites

> Skip this phase on subsequent restarts; jump straight to [Phase 2](#phase-2--start-services).

### 0.1 Clone the repository

```bash
git clone https://github.com/ronit22203/clinical-trials-matching-platform
cd clinical-trials-matching-platform
git checkout feat/palantir-react-ui     # production branch
```

### 0.2 Bootstrap system packages, Python runtimes, and native binaries

```bash
bash scripts/pre_requisites.sh
```

What it installs (non-interactive, ~5–10 min):

| Step | What |
|------|------|
| apt packages | build-essential, git, curl, python3.12+3.11, openjdk-21, Node 20, neo4j binary |
| Qdrant binary | `/usr/local/bin/qdrant` from GitHub releases |
| `core-llm-inference` | `.venv` under `core-llm-inference/` with `torch cu124` + `sglang[all]` + flashinfer wheels |
| Python venvs | `agentic-reasoning/.venv`, `data-acquisition/.venv`, `data-ingestion` pip install |
| Data directories | `data/pdfs/`, `data/artifacts/`, `data/qdrant/` |
| `.env.local` | Scaffolded from `.env.local.example` if not present |

If the script was already run, re-running it is idempotent (it skips existing binaries/venvs).

### 0.3 Set environment variables

```bash
cp .env.local.example .env.local
```

Edit `.env.local` — minimum required values:

```bash
# Infrastructure
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=testpassword
QDRANT_URL=http://localhost:6333

# SGLang inference (matches core-llm-inference default port)
SGLANG_BASE_URL=http://localhost:30000/v1
```

> **Note:** `.env.local` is gitignored. Never commit credentials.

### 0.4 Install module dependencies (if not already done by pre_requisites.sh)

```bash
make reasoning-install     # agentic-reasoning .venv
make acquisition-install   # data-acquisition .venv
make ingestion-install     # data-ingestion (system python3.11)
make inference-install     # core-llm-inference .venv + torch cu124 + sglang
```

`make inference-install` will take the longest (~10–15 min on first run — downloads ~4 GB of
CUDA wheels).

---

## Phase 1 — Set Neo4j initial password (first boot only)

Neo4j ships with a mandatory password-change gate. Run this once:

```bash
# With neo4j not yet running:
neo4j-admin dbms set-initial-password testpassword
# or whatever password you set in .env.local → NEO4J_PASSWORD
```

If you see `Password already set` the step is already done.

---

## Phase 2 — Start services

Run these commands every time you restart the machine or the pod is recycled.

### 2.1 Start Neo4j + Qdrant

```bash
make up
```

Docker is not available on RunPod Secure Cloud pods — `make up` detects this and falls back to
`shell/start_services.sh`, which starts both services as background processes using their native
binaries. Logs go to `/tmp/qdrant.log` and `/tmp/neo4j.log`.

Expected output:

```
▸  Starting Qdrant (storage: data/qdrant, port: 6333)…
✓  Qdrant running (PID 12345) → http://localhost:6333
▸  Starting Neo4j (bolt: 7687, http: 7474)…
✓  Neo4j running (PID 12346) → http://localhost:7474
```

Wait ~15 s for Neo4j's JVM to finish initialising before proceeding.

### 2.2 Start the SGLang inference server

```bash
make inference-serve
# or with explicit model override:
make inference-serve MODEL=Qwen/Qwen2.5-7B-Instruct
```

This starts SGLang detached in the background on port **30000**. On first load, the model
weights are downloaded from HuggingFace (~14 GB for Qwen2.5-7B) — allow 3–5 min on a fresh
pod. Subsequent starts reuse the HuggingFace cache.

**VRAM headroom on 23 GB L4:**

| Model | VRAM | Fits? |
|-------|------|-------|
| `Qwen/Qwen2.5-7B-Instruct` (default) | ~14 GB | ✅ ~9 GB KV-cache headroom |
| `meta-llama/Llama-3.1-8B-Instruct` | ~16 GB | ✅ ~7 GB headroom |
| `Qwen/Qwen2.5-14B-Instruct` | ~28 GB | ❌ use GPTQ-4bit |

Monitor the server in real time (foreground mode):

```bash
make inference-serve-fg   # Ctrl-C to stop
```

### 2.3 Verify everything is healthy

```bash
make inference-status     # checks SGLang :30000 health + GPU utilisation
make status               # container/artifact counts
```

Check Qdrant and Neo4j manually:

```bash
curl -s http://localhost:6333/collections | python3 -m json.tool
curl -s http://localhost:7474               # should return Neo4j browser HTML
```

---

## Phase 3 — Ingest documents (first time or to add papers)

```bash
# Fetch PDFs from medRxiv (adjust MAX_PDFS as needed)
make fetch SOURCE=medrxiv MAX_PDFS=10

# Run the full 5-stage pipeline (OCR → Markdown → Clean → Chunk → Embed)
make ingest N=10
```

Monitor progress:

```bash
make ingestion-inspect         # file counts at each stage
make ingestion-list-documents  # UUIDs of tracked documents
```

After ingestion, build the Neo4j knowledge graph:

```bash
make ingestion-neo4j-build
```

Verify:

```bash
# Qdrant collection size
curl -s http://localhost:6333/collections/medical_papers | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print('vectors:', d['result']['points_count'])"
```

---

## Phase 4 — Query the agent

```bash
# Single-shot query
make reasoning-run-query QUERY="What biomarkers predict sepsis mortality?"

# Interactive CLI
make reasoning-run
```

The agent executes the deterministic two-phase pipeline:
1. **GraphRAG retrieval** — Qdrant semantic search + Neo4j triple lookup
2. **Grounded synthesis** — SGLang/Qwen generates answer strictly from retrieved evidence

---

## Phase 5 — Benchmark (optional)

```bash
make benchmark-retrieval           # Recall@K, NDCG, MRR, HitRate
make benchmark-reasoning           # 20 golden queries end-to-end
make benchmark-all                 # full suite
```

Or benchmark just the inference layer:

```bash
make inference-benchmark           # 10 queries, throughput + MBU%
make inference-benchmark-all       # all queries + Prometheus push
```

---

## Shutdown

```bash
make inference-stop   # gracefully terminate SGLang server
make down             # stop Neo4j + Qdrant
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `make up` — Neo4j not ready after 30s | Java cold-start slower on large pods | Wait 30 more s; check `/tmp/neo4j.log` |
| SGLang `CUDA out of memory` | Another process holds GPU memory | `nvidia-smi` → kill offending PID |
| `make inference-status` — 404 | Server not started yet | `make inference-serve`; wait 60 s for model load |
| `No chunks found` on reasoning | Ingest not run | Run Phase 3 |
| Neo4j password error | Initial password not set | `neo4j-admin dbms set-initial-password <password>` |
| `pre_requisites.sh` partial failure | Interrupted mid-run | Re-run — script is idempotent; check log output |
| HuggingFace download stalls | Rate limit / no token | Set `HF_TOKEN=<token>` in `.env.local`; `export $(grep -v ^# .env.local \| xargs)` |

---

## Port reference

| Service | Port | Protocol |
|---------|------|----------|
| Qdrant HTTP | 6333 | REST |
| Qdrant gRPC | 6334 | gRPC |
| Neo4j Bolt | 7687 | Bolt |
| Neo4j HTTP (browser) | 7474 | HTTP |
| SGLang / agentic-reasoning | 30000 | OpenAI-compatible REST |
| Reasoning API (FastAPI) | 8000 | HTTP |
