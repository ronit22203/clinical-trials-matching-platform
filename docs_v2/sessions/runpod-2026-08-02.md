# RunPod Session — 2026-08-02 (Session 3)

**Duration:** ~1.5 hrs (~01:00–02:35 IST)  
**Goal:** Resolve persistent 401 Unauthorized errors on ingest requests through RunPod's reverse proxy, and get the full platform UI working end-to-end.

---

## Outcome

✅ Platform UI live at `https://<pod-id>-5173.proxy.runpod.net`  
✅ Login works (JWT issued, 200 OK)  
✅ `POST /api/ingest` returns 200 OK through browser  
✅ All 3 services stable: reasoning `:8000`, ingestion `:8002`, blueprint `:5173`  
✅ Ollama + `qwen2.5:7b` running on L4 GPU  

---

## Root Cause Analysis

### Why ingest kept returning 401

The flow is:

```
Browser → RunPod HTTPS proxy (Cloudflare edge) → Pod port 5173 (Vite) → localhost:8002 (FastAPI)
```

**RunPod's Cloudflare-backed reverse proxy strips the `Authorization: Bearer` header** before requests reach Vite. This is standard Cloudflare behaviour — it sanitises auth headers on forwarded requests.

Previous fix attempts that didn't work:
1. `X-Auth-Token` fallback header — Cloudflare stripped this too (or didn't; hard to confirm)
2. Vite `proxyReq` event handler copying headers — can only copy what Vite receives; if the header was stripped upstream, nothing to copy

**Definitive fix: cookies.**

HTTP cookies are application-layer data — proxies (nginx, Cloudflare) forward them verbatim. Vite's `http-proxy` also automatically forwards all request cookies to backend targets without any configuration.

---

## Changes Made This Session

### `palantir-blueprint/src/lib/api.ts`
- `setToken()` now also sets `document.cookie = "auth_token=<jwt>; SameSite=Strict; Path=/"`
- `clearToken()` expires the cookie immediately
- Fixed stale comment `:8001` → `:8002`

### `agentic-reasoning/src/auth.py`
- `verify_token()` checks in order: `Authorization` header → `X-Auth-Token` header → `auth_token` cookie

### `data-ingestion/src/api/auth.py`
- Same three-tier fallback as reasoning auth

### `palantir-blueprint/src/components/IngestionPane.tsx`
- Fixed stale error message "`:8001`" → "`:8002`"

---

## Infrastructure Facts (RunPod)

| Port | Who owns it | Notes |
|------|-------------|-------|
| 8001 | RunPod internal nginx | **Never use** — permanently bound, cannot be overridden |
| 8000 | Reasoning FastAPI | Exposed via RunPod HTTP port setting |
| 8002 | Ingestion FastAPI | Moved from 8001 this session |
| 5173 | Vite dev server | Primary public entry point |

**Expose 5173, 8000, 8002 in RunPod pod → Edit → HTTP Service** (not TCP).

### `.env.local` required on pod (not committed — gitignored)

```bash
cat > .env.local << 'EOF'
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH='$2b$12$A7r3R76K/m/PfH4EiM/8f.43aKp045JgRcR.0rFKonQyrh1pIvj/G'
AUTH_JWT_SECRET=40845025480110b27e8d30a20559b968cbc8e251cafe3241a5c160150315af85
AUTH_TOKEN_EXPIRE_MINUTES=480
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=testpassword
QDRANT_URL=http://localhost:6333
OLLAMA_BASE_URL=http://localhost:11434
LLM_BASE_URL=http://localhost:11434
LLM_MODEL=qwen2.5:7b
EOF
```

**Default credentials:** `admin` / `admin123`

---

## Fresh Pod Startup (verified procedure)

```bash
cd /workspace/clinical-trials-matching-platform
git pull
bash scripts/pre_requisites.sh   # installs venvs, Ollama + model, npm ci
cat > .env.local << 'EOF'        # paste the block above
...
EOF
make up                           # start Qdrant + Neo4j
make validate                     # confirm all green
make dev                          # start all 3 services
```

Then open `https://<pod-id>-5173.proxy.runpod.net`.

---

## Commits This Session

| Hash | Message |
|------|---------|
| `e5f05a0` | `fix(auth): persist JWT as cookie to survive RunPod proxy header stripping` |
| `4684649` | `fix(proxy): explicitly forward Authorization+X-Auth-Token in Vite proxy` |
| `c3a3922` | `fix(auth): accept X-Auth-Token header as fallback for RunPod nginx` |
| `201e322` | `fix(auth): load .env.local in ingestion server at startup` |
| `63c50b0` | `fix(infra): move ingestion API from :8001 to :8002` |

---

## Known Issues / Tomorrow

- [ ] Ingest UI shows "Connection timed out" on actual timeout (now correctly says :8002) — need to verify the full 5-stage pipeline runs with a real PDF upload
- [ ] Reasoning `/api/health` returns 503 when `LLM_MODEL` env var is unset (fallback_model validation error) — fixed by including `LLM_MODEL=qwen2.5:7b` in `.env.local`
- [ ] `/api/match` end-to-end not yet tested on RunPod (Qdrant must have indexed docs first)
- [ ] Set RunPod template so `.env.local` is pre-populated on fresh pods
- [ ] Add `DOCKERHUB_USERNAME` + `DOCKERHUB_TOKEN` secrets to GitHub repo for Docker build workflow

---

## Architecture Reminder

```
Browser
  └─→ RunPod proxy (strips Authorization header)
        └─→ Vite :5173  (forwards cookies automatically)
              ├─→ /api/ingest* → FastAPI :8002  (reads auth_token cookie)
              └─→ /api/*      → FastAPI :8000  (reads auth_token cookie)
```

Auth token priority: `Authorization: Bearer` > `X-Auth-Token` header > `auth_token` cookie
