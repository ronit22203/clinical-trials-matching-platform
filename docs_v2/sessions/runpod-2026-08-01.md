# RunPod Deployment & Auth — Session Log (2026-08-01)

> **Status:** Services running, UI accessible via proxy. SGLang blocked on driver version.
> **Resume command:** `cd /workspace/clinical-trials-matching-platform && make dev`

---

## What Was Built

### 1. JWT Auth (completed, working in prod)

Full username/password auth across both FastAPI servers and the React UI.

| Component | Change |
|---|---|
| `agentic-reasoning/src/auth.py` | JWT utilities — `bcrypt` + `python-jose`, `verify_token()` FastAPI dep |
| `agentic-reasoning/src/server.py` | `POST /api/auth/login` (public), `Depends(verify_token)` on all routes, `_load_dotenv()` at module level |
| `data-ingestion/src/api/auth.py` | Token verification for ingestion server |
| `data-ingestion/src/api/server.py` | `Depends(verify_token)` on all 9 routes |
| `palantir-blueprint/src/lib/api.ts` | `getToken/setToken/clearToken`, `authHeaders()`, `login()`, 401 → logout |
| `palantir-blueprint/src/App.tsx` | `isAuthenticated` gate, `auth:logout` listener |
| `palantir-blueprint/src/components/LoginPage.tsx` | ⚕ Blueprint Card login form |
| `scripts/hash_password.py` | bcrypt hash generator CLI |
| `.env.local.example` | Documented `AUTH_*` vars |

**Default credentials:** `admin` / `admin123`

**Critical gotcha:** `AUTH_PASSWORD_HASH` value must be **single-quoted** in `.env.local`:
```bash
AUTH_PASSWORD_HASH='$2b$12$...'   # single quotes — bash treats $2 as positional param otherwise
```

**Generate new hash:**
```bash
python scripts/hash_password.py
```

---

### 2. RunPod `pre_requisites.sh` — All Fixes Applied

| Fix | Commit |
|---|---|
| `apt-utils` + git submodule force-init | d4fb5bf |
| `uv` install + `--python` flag on all uv pip calls | 536387c |
| Single resolver pass + `--index-strategy unsafe-best-match` | 02d1d4f |
| All pip installs switched to `uv pip` | 2b80458 |
| `UV_CACHE_DIR=/workspace/uv-cache` (prevents root-fs ENOSPC) | e14f931 |
| Auto-detect CUDA driver → skip sglang on driver < 570 | 0551757 |

**Run the script:**
```bash
cd /workspace/clinical-trials-matching-platform
git pull && git submodule update --init --recursive
bash scripts/pre_requisites.sh
```

Script is fully idempotent — re-running skips already-installed components.

---

### 3. SGLang / CUDA Driver Constraint

**Current pod:** driver `550.127.05` → max CUDA 12.4.
**sglang 0.5.x** requires CUDA 13.0 (driver ≥ 570). No cu124 wheels exist for any sglang release — `sgl-kernel` dropped cu124 support.

**Fix:** Use a RunPod pod/template with **driver 570+** (any template labeled "CUDA 13" or showing driver 570+).

The script auto-detects and skips sglang install on incompatible drivers. Everything else (ingestion, reasoning via fallback LLM, UI) works without SGLang.

**Fallback LLM:** Set `OPENAI_API_KEY` in `.env.local` and change `config/app.yaml` provider to `openai/gpt-4o-mini` for synthesis without SGLang.

---

### 4. Other Fixes

- `core-llm-inference/src/config.py`: `parents[2]` → `parents[1]` (config path was resolving to repo root instead of module root)
- `palantir-blueprint/vite.config.ts`: `hmr.clientPort: 443` for RunPod TLS proxy (fixes blank screen)
- `Dockerfile.runpod` + `docker/entrypoint.sh`: pre-baked image blueprint (use once GitHub Actions workflow is configured)
- `.github/workflows/docker-publish.yml`: auto-build + push on dep manifest changes

---

## Resume Checklist

```bash
# 1. SSH into pod (get fresh IP/port from RunPod → Connect)
ssh root@<ip> -p <port> -i ~/.ssh/id_ed25519

# 2. Check services are still up
cd /workspace/clinical-trials-matching-platform
curl -s http://localhost:8000/api/health   # reasoning
curl -s http://localhost:8001/api/health   # ingestion (may 401 — that's correct)
curl -s http://localhost:6333/healthz      # qdrant
curl -s http://localhost:7474              # neo4j

# 3. If services are down, restart
fuser -k 8001/tcp 2>/dev/null; true
make up       # Neo4j + Qdrant
make dev      # all three services

# 4. Access UI
# https://<pod-id>-5173.proxy.runpod.net
# Login: admin / admin123
```

---

## Pod Port Exposure

RunPod → My Pods → Edit → **Expose HTTP Ports:** `5173, 8000, 8001`

SSH port changes on every pod reset — always grab it fresh from **Connect**.

---

## Next Session Goals

- [ ] Load a PDF via the ingestion UI and verify chunking → Qdrant
- [ ] Run a clinical query end-to-end (Phase 1 retrieval → Phase 2 synthesis)
- [ ] Switch to a driver 570+ pod for SGLang inference
- [ ] Set up GitHub Actions Docker build (add `DOCKERHUB_USERNAME` + `DOCKERHUB_TOKEN` secrets)
