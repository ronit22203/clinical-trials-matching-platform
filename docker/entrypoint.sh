#!/usr/bin/env bash
# docker/entrypoint.sh — RunPod pod startup script.
#
# Called once per pod start. Takes ~30 seconds:
#   1. Clone or pull the repo into /workspace
#   2. Symlink pre-baked /opt/venvs/* into the repo (deps already installed)
#   3. `pip install -e .` in each module (instant — just writes .pth files)
#   4. Set up .env.local from env vars or copy from example
#   5. Start Neo4j + Qdrant, then all platform services via `make dev`

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC}  $*"; }
info() { echo -e "${CYAN}▸${NC}  $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }

REPO_URL="${REPO_URL:-https://github.com/ronit22203/clinical-trials-matching-platform.git}"
REPO_DIR="/workspace/clinical-trials-matching-platform"
REPO_BRANCH="${REPO_BRANCH:-main}"

echo ""
echo "━━━  Healthcare Platform — Pod Startup  ━━━"
echo ""

# ── 1. Clone or pull repo ─────────────────────────────────────────────────────
if [[ -d "$REPO_DIR/.git" ]]; then
  info "Pulling latest code…"
  git -C "$REPO_DIR" pull --ff-only 2>/dev/null || warn "git pull failed — using existing code"
else
  info "Cloning repository…"
  git clone --depth 1 --branch "$REPO_BRANCH" "$REPO_URL" "$REPO_DIR"
  git -C "$REPO_DIR" submodule update --init --force --recursive
fi
ok "Code: $REPO_DIR"

# ── 2. Symlink pre-baked venvs ────────────────────────────────────────────────
# Venvs live in /opt/venvs/* (baked into image). Symlink them into the repo so
# make targets, Makefile PYTHON vars, and `pip install -e .` all work normally.
info "Linking pre-baked venvs…"
for module in agentic-reasoning data-acquisition data-ingestion core-llm-inference; do
  target="$REPO_DIR/$module/.venv"
  source="/opt/venvs/$module"
  if [[ -d "$source" && ! -e "$target" ]]; then
    ln -s "$source" "$target"
    ok "  $module/.venv → $source"
  elif [[ -e "$target" ]]; then
    ok "  $module/.venv already linked"
  else
    warn "  /opt/venvs/$module not found — module may need manual install"
  fi
done

# ── 3. Editable installs (instant — deps already in venv) ────────────────────
info "Registering editable installs…"
cd "$REPO_DIR"

/opt/venvs/agentic-reasoning/bin/pip install --quiet -e agentic-reasoning
/opt/venvs/data-acquisition/bin/pip install --quiet -e data-acquisition
/opt/venvs/data-ingestion/bin/pip install --quiet -r data-ingestion/requirements.txt
/opt/venvs/core-llm-inference/bin/pip install --quiet -e core-llm-inference
ok "Editable installs registered"

# ── 4. Blueprint npm deps ─────────────────────────────────────────────────────
info "Linking blueprint node_modules…"
if [[ ! -d "$REPO_DIR/palantir-blueprint/node_modules" && -d /opt/blueprint-node-modules ]]; then
  ln -s /opt/blueprint-node-modules "$REPO_DIR/palantir-blueprint/node_modules"
  ok "node_modules linked"
fi

# ── 5. .env.local ─────────────────────────────────────────────────────────────
ENV_FILE="$REPO_DIR/.env.local"
if [[ ! -f "$ENV_FILE" ]]; then
  cp "$REPO_DIR/.env.local.example" "$ENV_FILE"
  info "Created .env.local from example"
fi

# Inject AUTH vars from pod environment variables (set in RunPod template secrets)
for var in AUTH_USERNAME AUTH_PASSWORD_HASH AUTH_JWT_SECRET AUTH_TOKEN_EXPIRE_MINUTES; do
  if [[ -n "${!var:-}" ]]; then
    # Remove existing line and append fresh value (single-quoted for bcrypt $ safety)
    sed -i "/^${var}=/d" "$ENV_FILE"
    printf "%s='%s'\n" "$var" "${!var}" >> "$ENV_FILE"
  fi
done

ok ".env.local ready"

# ── 6. Data directories ───────────────────────────────────────────────────────
for d in data/pdfs/raw data/artifacts/{extract,convert,clean,chunk} data/neo4j data/qdrant; do
  mkdir -p "$REPO_DIR/$d"
done

# ── 7. Start Neo4j + Qdrant ───────────────────────────────────────────────────
info "Starting Neo4j…"
neo4j start 2>/dev/null || true
# Wait up to 30s for Neo4j bolt port
for i in $(seq 1 15); do
  nc -z -w 2 127.0.0.1 7687 2>/dev/null && break || sleep 2
done
nc -z -w 2 127.0.0.1 7687 2>/dev/null && ok "Neo4j :7687 ready" || warn "Neo4j not responding — check logs"

info "Starting Qdrant…"
# Env overrides keep the process on 0.0.0.0:6333 even if the yaml host drifted.
qdrant_cmd=(qdrant)
if [[ -f "$REPO_DIR/config/qdrant.yaml" ]]; then
  qdrant_cmd+=(--config-path "$REPO_DIR/config/qdrant.yaml")
fi
QDRANT__SERVICE__HOST=0.0.0.0 \
QDRANT__SERVICE__HTTP_PORT=6333 \
nohup "${qdrant_cmd[@]}" > /workspace/qdrant.log 2>&1 &
qdrant_ready=0
for _ in $(seq 1 15); do
  if nc -z -w 2 127.0.0.1 6333 2>/dev/null; then
    qdrant_ready=1
    break
  fi
  sleep 1
done
if [[ "$qdrant_ready" -eq 1 ]]; then
  ok "Qdrant :6333 ready"
else
  warn "Qdrant not responding — check /workspace/qdrant.log"
fi

# ── 8. Start platform services ────────────────────────────────────────────────
echo ""
echo "━━━  Starting platform services  ━━━"
echo ""
echo "  Reasoning API  → http://localhost:8000"
echo "  Ingestion API  → http://localhost:8002"
echo "  Blueprint UI   → http://localhost:5173"
echo ""
echo "  RunPod public URL: https://\${RUNPOD_POD_ID}-5173.proxy.runpod.net"
echo ""

cd "$REPO_DIR"
exec make dev
