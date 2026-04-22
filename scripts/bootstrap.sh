#!/usr/bin/env bash
# bootstrap.sh — verify dependencies and set up local dev environment.
# Run once after cloning: ./scripts/bootstrap.sh

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RESET='\033[0m'
ok()   { echo -e "${GREEN}✓${RESET}  $*"; }
warn() { echo -e "${YELLOW}⚠${RESET}  $*"; }
fail() { echo -e "${RED}✗${RESET}  $*"; exit 1; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo ""
echo "Healthcare Platform — local environment bootstrap"
echo "================================================="
echo ""

# ── Dependency checks ──────────────────────────────────────────────────────────

echo "Checking dependencies…"

command -v docker >/dev/null 2>&1 || fail "Docker not found. Install from https://docs.docker.com/get-docker/"
docker info >/dev/null 2>&1 || fail "Docker daemon is not running. Start Docker Desktop."
ok "Docker"

command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 \
  || fail "Docker Compose v2 not found. Upgrade Docker Desktop."
ok "Docker Compose"

command -v ollama >/dev/null 2>&1 \
  && ok "Ollama (available — set LLM_PROVIDER=ollama in .env.local to use)" \
  || warn "Ollama not found. Not required — LM Studio is the default provider."

PYTHON_BIN=""
for candidate in python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON_BIN="$candidate"
    break
  fi
done
[ -n "$PYTHON_BIN" ] || fail "Python 3.11+ not found."
PYTHON_VERSION=$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ok "Python $PYTHON_VERSION"

command -v node >/dev/null 2>&1 || fail "Node.js not found. Install via nvm or https://nodejs.org/"
NODE_VERSION=$(node --version)
ok "Node $NODE_VERSION"

echo ""

# ── LM Studio connectivity probe ──────────────────────────────────────────────

echo "Checking LM Studio server…"
LM_STUDIO_URL="${LM_STUDIO_BASE_URL:-http://localhost:1234/v1}"
if curl -sf "${LM_STUDIO_URL}/models" -o /dev/null 2>&1; then
  ok "LM Studio server responds at ${LM_STUDIO_URL}"
else
  warn "LM Studio not running at ${LM_STUDIO_URL}."
  warn "Start LM Studio, load a model, and enable the local server (port 1234)."
  warn "Then re-run 'make serve'. See README for setup instructions."
fi

# ── Ollama model check (optional — only if Ollama is installed) ───────────────

if command -v ollama >/dev/null 2>&1; then
  echo ""
  echo "Checking Ollama models (optional provider)…"
  OLLAMA_MODELS=$(ollama list 2>/dev/null || echo "")
  if echo "$OLLAMA_MODELS" | grep -q "nomic-embed-text"; then
    ok "nomic-embed-text (embedding model)"
  else
    warn "nomic-embed-text not in 'ollama list'. Ingestion embeddings may fail if using Ollama."
    warn "Pull if needed: ollama pull nomic-embed-text"
  fi
fi

echo ""

# ── .env.local ────────────────────────────────────────────────────────────────

echo "Setting up .env.local…"
if [ -f "$REPO_ROOT/.env.local" ]; then
  ok ".env.local already exists (skipping)"
else
  cp "$REPO_ROOT/.env.local.example" "$REPO_ROOT/.env.local"
  ok "Created .env.local from .env.local.example"
  warn "Review .env.local and set LLM_MODEL to a model you have loaded in LM Studio."
fi

if [ -f "$REPO_ROOT/platform-ui/.env.local" ]; then
  ok "platform-ui/.env.local already exists (skipping)"
else
  cp "$REPO_ROOT/platform-ui/.env.local.example" "$REPO_ROOT/platform-ui/.env.local"
  ok "Created platform-ui/.env.local"
fi

echo ""

# ── Data directories ──────────────────────────────────────────────────────────

echo "Creating data directories…"
for d in data/pdfs data/artifacts data/neo4j data/qdrant "data/temporal/postgres" data/models; do
  mkdir -p "$REPO_ROOT/$d"
done
ok "data/ subdirectories ready"

echo ""

# ── Summary ───────────────────────────────────────────────────────────────────

echo "Bootstrap complete. Next steps:"
echo ""
echo "  1. Start LM Studio, load a GGUF model, enable Local Server (port 1234)"
echo "  make up         # Start Docker services (Neo4j, Qdrant, Temporal)"
echo "  make validate   # Verify all services are reachable"
echo "  make fetch      # Download sample PDFs (MAX_PDFS=5 default)"
echo "  make ingest     # Run OCR → chunk → embed → graph pipeline"
echo "  make serve      # Start API (:8000) + UI (:3000)"
echo ""
