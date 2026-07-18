#!/usr/bin/env bash
# shell/start_services.sh — Start Neo4j + Qdrant natively (no Docker).
# Used by `make up` when Docker is unavailable (e.g., RunPod Secure Cloud Pod).

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC}  $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
info() { echo -e "${CYAN}▸${NC}  $*"; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDS="$REPO_ROOT/.service_pids"
mkdir -p "$PIDS"

# ── Qdrant ────────────────────────────────────────────────────────────────────
if [[ -x /usr/local/bin/qdrant ]]; then
  if pgrep -f '/usr/local/bin/qdrant' >/dev/null 2>&1; then
    ok "Qdrant already running"
  else
    info "Starting Qdrant (storage: data/qdrant, port: 6333)…"
    QDRANT__STORAGE__STORAGE_PATH="$REPO_ROOT/data/qdrant" \
    QDRANT__SERVICE__HTTP_PORT=6333 \
    QDRANT__SERVICE__GRPC_PORT=6334 \
    nohup /usr/local/bin/qdrant > /tmp/qdrant.log 2>&1 &
    echo $! > "$PIDS/qdrant.pid"
    sleep 2
    if curl -sf http://localhost:6333/healthz >/dev/null 2>&1; then
      ok "Qdrant running (PID $(cat "$PIDS/qdrant.pid")) → http://localhost:6333"
    else
      warn "Qdrant started but health check pending — check /tmp/qdrant.log"
    fi
  fi
else
  warn "Qdrant binary not found. Run: ./scripts/pre_requisites.sh"
fi

# ── Neo4j ─────────────────────────────────────────────────────────────────────
if command -v neo4j >/dev/null 2>&1; then
  if pgrep -f 'neo4j' >/dev/null 2>&1; then
    ok "Neo4j already running"
  else
    info "Starting Neo4j (bolt: 7687, http: 7474)…"
    # 'neo4j console' is the correct way to start Neo4j without systemd in a container
    nohup neo4j console > /tmp/neo4j.log 2>&1 &
    echo $! > "$PIDS/neo4j.pid"
    info "Waiting for Neo4j to be ready (up to 30s)…"
    _w=0
    until curl -sf http://localhost:7474 >/dev/null 2>&1; do
      (( _w >= 30 )) && { warn "Neo4j not ready after 30s — check /tmp/neo4j.log"; break; }
      sleep 3; (( _w += 3 ))
    done
    curl -sf http://localhost:7474 >/dev/null 2>&1 \
      && ok "Neo4j running (PID $(cat "$PIDS/neo4j.pid")) → http://localhost:7474" \
      || true
  fi
else
  warn "neo4j not found. Run: ./scripts/pre_requisites.sh"
fi
