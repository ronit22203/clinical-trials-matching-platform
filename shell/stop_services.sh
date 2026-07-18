#!/usr/bin/env bash
# shell/stop_services.sh — Stop natively-running Neo4j + Qdrant.
# Used by `make down` when Docker is unavailable.

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC}  $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDS="$REPO_ROOT/.service_pids"

stop_service() {
  local name="$1" pid_file="$PIDS/$1.pid"
  if [[ -f "$pid_file" ]]; then
    local pid; pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" && ok "${name} stopped (PID ${pid})"
    else
      warn "${name} PID ${pid} not running (already stopped?)"
    fi
    rm -f "$pid_file"
  else
    # Fallback: kill by process name
    if pgrep -f "$name" >/dev/null 2>&1; then
      pkill -f "$name" && ok "${name} stopped" || warn "Could not stop ${name}"
    else
      ok "${name} not running"
    fi
  fi
}

stop_service "qdrant"
stop_service "neo4j"
