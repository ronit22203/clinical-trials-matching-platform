# Production Startup Guide — Ubuntu 22.04 + NVIDIA L4

This guide covers standing the platform up from scratch on a headless Ubuntu 22.04 server with
an NVIDIA L4 GPU (Ada Lovelace, 23 GB VRAM). It replaces the [Quickstart](quickstart.md)
macOS-centric flow.

**Inference deployment path (choose one):**

| Path | When to use | Command |
|------|-------------|---------|
| **Docker (recommended)** | RunPod / any provider with NFS `/workspace` | `make inference-docker-run` |
| **Ollama fallback** | Docker unavailable; quick start; NFS environment | `make inference-ollama-serve` |
| **Native pip install** | Local SSD only (not NFS); CI/CD build machines | `make inference-install` |

> **Why Docker?** RunPod's `/workspace` is an NFS network mount. Installing `torch` + `sglang[all]` +
> flashinfer (~18 GB, millions of small files) over NFS via pip stalls for hours.
> The pre-baked image (`ghcr.io/ronit22203/clinical-trials-inference`) has everything baked in —
> `make inference-docker-run` pulls and starts it with zero NFS writes.

---

## Hardware assumptions

| Spec | Value |
|------|-------|
| OS | Ubuntu 22.04.5 LTS |
| CPU | AMD EPYC 9254 (48 threads) or equivalent |
| GPU | NVIDIA L4 — sm_89, 23 034 MiB VRAM, 300 GB/s |
| CUDA driver | 580+ (CUDA 12.x / 13.x) |
| Inference backend | SGLang via Docker image (primary) / Ollama (fallback) |
| Infrastructure | Native binaries (Qdrant, Neo4j) + Docker for inference |

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
| `core-llm-inference` | **Skipped** — use Docker or Ollama path (see Phase 0.4) |
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

### 0.4 Install module dependencies

#### Lightweight services (always do this)

```bash
make install-lightweight   # reasoning + acquisition + blueprint UI — ~2 min, no GPU wheels
```

#### Inference — choose ONE path

**Option A — Docker (recommended for RunPod / NFS environments)**

```bash
# Log in to GHCR once (personal access token with read:packages scope)
echo $GHCR_TOKEN | docker login ghcr.io -u ronit22203 --password-stdin

# Pull the pre-baked image — no pip, no NFS writes
docker pull ghcr.io/ronit22203/clinical-trials-inference:latest
```

`make inference-docker-run` (Phase 2.2) does the pull-and-run in one step.

**Option B — Ollama (if Docker is unavailable)**

```bash
make inference-ollama-install   # single ~200 MB binary via curl — fast over NFS
```

**Option C — Native pip install (local SSD only)**

> ⚠️ **Do not use on RunPod** — `/workspace` is NFS. Pip will stall writing ~18 GB of
> torch + sglang wheels across the network. Use Option A or B instead.

```bash
make inference-install   # requires local SSD; pip cache auto-redirected to /workspace if mounted
```

#### GPU-heavy ingestion stack

```bash
make ingestion-install   # OCR/Torch wheels for data-ingestion (~5–10 min; also NFS-sensitive)
```

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

#### Option A — Docker (recommended)

```bash
# Pull image if not already local, then start detached with GPU + shared memory
make inference-docker-run
# or with a different model:
make inference-docker-run INFERENCE_MODEL=meta-llama/Llama-3.1-8B-Instruct
```

This runs `ghcr.io/ronit22203/clinical-trials-inference:latest` detached on port **30000** with
`--gpus all` and `--shm-size 32g`. HuggingFace model weights are downloaded into
`$WORKSPACE/hf-cache` (volume-mounted) on first start — allow 3–5 min for ~14 GB Qwen2.5-7B.
Subsequent starts reuse the cache instantly.

Stop with `make inference-docker-stop`.

#### Option B — Ollama fallback

```bash
make inference-ollama-serve   # starts ollama serve + pulls qwen2.5:7b
```

Switch the reasoning module to Ollama in `config/app.yaml`:
```yaml
agent:
  model: ollama/qwen2.5:7b
```

Ollama serves on `:11434` (OpenAI-compatible). The reasoning module's `ollama/` provider
prefix routes to it automatically.

#### Option C — Native SGLang (local SSD only)

```bash
make inference-serve
# or with explicit model override:
make inference-serve INFERENCE_MODEL=Qwen/Qwen2.5-7B-Instruct
```

Requires `make inference-install` to have succeeded (local SSD; do not use on RunPod/NFS).

---

**VRAM headroom on 23 GB L4:**

| Model | VRAM | Fits? |
|-------|------|-------|
| `Qwen/Qwen2.5-7B-Instruct` (default) | ~14 GB | ✅ ~9 GB KV-cache headroom |
| `meta-llama/Llama-3.1-8B-Instruct` | ~16 GB | ✅ ~7 GB headroom |
| `Qwen/Qwen2.5-14B-Instruct` | ~28 GB | ❌ use GPTQ-4bit |

Monitor the native server in real time (foreground mode):

```bash
make inference-serve-fg   # Ctrl-C to stop (Option C only)
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

### 4.1 CLI

```bash
# Single-shot query
make reasoning-run-query QUERY="What biomarkers predict sepsis mortality?"

# Interactive CLI
make reasoning-run
```

### 4.2 Web UI (palantir-blueprint)

```bash
make reasoning-serve   # reasoning FastAPI on :8000 (if not already running via make dev)
make ingestion-api     # ingestion FastAPI on :8001  (if not already running via make dev)
make blueprint-dev     # Vite dev server on :5173
```

**Access on RunPod:**

```
https://{pod-id}-5173.proxy.runpod.net
```

> **Why only one port?** The UI runs on `:5173`. Vite's built-in proxy forwards
> `/api/ingest/*` → `localhost:8001` and `/api/*` → `localhost:8000` server-side.
> The browser only ever touches port 5173 — no other ports need to be exposed through
> RunPod's proxy.

To find your pod ID: RunPod dashboard → pod name → "Connect" → copy the proxy URL, or:

```bash
hostname   # pod hostname typically encodes the pod ID
```

For a production (non-hot-reload) serve:

```bash
make blueprint-preview   # build + serve on :4173 (same proxy rules apply)
# RunPod URL: https://{pod-id}-4173.proxy.runpod.net
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
make inference-docker-stop   # stop Docker inference container (Option A)
make inference-stop          # stop native SGLang process (Option C)
make down                    # stop Neo4j + Qdrant
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `make up` — Neo4j not ready after 30s | Java cold-start slower on large pods | Wait 30 more s; check `/tmp/neo4j.log` |
| `make inference-install` stalls for hours | `/workspace` is NFS — pip writing 18 GB of tiny files over network | **Use `make inference-docker-run` (Docker, recommended) or `make inference-ollama-serve` (Ollama fallback)** |
| `docker: Cannot connect to the Docker daemon` | Docker not installed / not running | `systemctl start docker`; or use Ollama fallback |
| `docker pull` — `unauthorized` from GHCR | Not logged in | `echo $GHCR_TOKEN \| docker login ghcr.io -u ronit22203 --password-stdin` |
| SGLang `CUDA out of memory` | Another process holds GPU memory | `nvidia-smi` → kill offending PID |
| `make inference-status` — 404 | Server not started yet | `make inference-docker-run`; wait 60 s for model load |
| `No chunks found` on reasoning | Ingest not run | Run Phase 3 |
| Neo4j password error | Initial password not set | `neo4j-admin dbms set-initial-password <password>` |
| `pre_requisites.sh` partial failure | Interrupted mid-run | Re-run — script is idempotent; check log output |
| HuggingFace download stalls | Rate limit / no token | Set `HF_TOKEN=<token>` in `.env.local`; `export $(grep -v ^# .env.local \| xargs)` |
| `No space left on device` during ingestion install | Root filesystem < 25 GB free; OCR/Torch wheels writing to root | Mount `/workspace`; `make ingestion-install` auto-redirects pip cache + tmp there |

---

## Port reference

| Service | Port | Protocol |
|---------|------|----------|
| Qdrant HTTP | 6333 | REST |
| Qdrant gRPC | 6334 | gRPC |
| Neo4j Bolt | 7687 | Bolt |
| Neo4j HTTP (browser) | 7474 | HTTP |
| SGLang / inference (Docker or native) | 30000 | OpenAI-compatible REST |
| Ollama (fallback) | 11434 | OpenAI-compatible REST |
| Reasoning API (FastAPI) | 8000 | HTTP |
| Ingestion API (FastAPI) | 8001 | HTTP |
| Blueprint UI — dev (Vite, **expose this on RunPod**) | 5173 | HTTP |
| Blueprint UI — preview (production build) | 4173 | HTTP |
