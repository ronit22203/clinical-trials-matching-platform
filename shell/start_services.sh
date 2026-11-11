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
    info "Starting Qdrant (storage: data/qdrant, bind: 0.0.0.0:6333)…"
    # Host is explicit: a config that says 127.0.0.1, or a probe that uses
    # `localhost` (often ::1 on Ubuntu), fails the startup health check.
    qdrant_args=()
    if [[ -f "$REPO_ROOT/config/qdrant.yaml" ]]; then
      qdrant_args=(--config-path "$REPO_ROOT/config/qdrant.yaml")
    fi
    QDRANT__STORAGE__STORAGE_PATH="$REPO_ROOT/data/qdrant" \
    QDRANT__SERVICE__HOST=0.0.0.0 \
    QDRANT__SERVICE__HTTP_PORT=6333 \
    QDRANT__SERVICE__GRPC_PORT=6334 \
    nohup /usr/local/bin/qdrant "${qdrant_args[@]}" > /tmp/qdrant.log 2>&1 &
    echo $! > "$PIDS/qdrant.pid"
    qdrant_ready=0
    for _ in $(seq 1 15); do
      if curl -sf http://127.0.0.1:6333/healthz >/dev/null 2>&1 \
        || curl -sf http://127.0.0.1:6333/readyz >/dev/null 2>&1; then
        qdrant_ready=1
        break
      fi
      sleep 1
    done
    if [[ "$qdrant_ready" -eq 1 ]]; then
      ok "Qdrant running (PID $(cat "$PIDS/qdrant.pid")) → http://127.0.0.1:6333"
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
    info "Starting Neo4j (bolt: 0.0.0.0:7687, http: 0.0.0.0:7474)…"
    # 'neo4j console' is the correct way to start Neo4j without systemd in a container.
    # Probe 127.0.0.1, not localhost: Ubuntu resolves localhost to ::1 first.
    nohup neo4j console > /tmp/neo4j.log 2>&1 &
    echo $! > "$PIDS/neo4j.pid"
    info "Waiting for Neo4j bolt :7687 (up to 30s)…"
    neo4j_ready=0
    for _ in $(seq 1 15); do
      if nc -z -w 2 127.0.0.1 7687 >/dev/null 2>&1; then
        neo4j_ready=1
        break
      fi
      sleep 2
    done
    if [[ "$neo4j_ready" -eq 1 ]]; then
      ok "Neo4j running (PID $(cat "$PIDS/neo4j.pid")) → bolt://127.0.0.1:7687"
    else
      warn "Neo4j not ready after 30s — check /tmp/neo4j.log"
    fi
  fi
else
  warn "neo4j not found. Run: ./scripts/pre_requisites.sh"
fi
