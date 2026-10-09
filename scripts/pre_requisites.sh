#!/usr/bin/env bash
# pre_requisites.sh — Production environment installer for Healthcare Platform.
# Target: Ubuntu 22.04 LTS, x86_64, NVIDIA GPU (CUDA 12.x / 13.x), root.
# Tested on: RunPod Secure Cloud Pod (Ubuntu 22.04 + CUDA 13.0, NVIDIA L4).
# Idempotent — safe to re-run.
#
# Design decisions:
#   - Python 3.12 via deadsnakes PPA (Python 3.11 via apt for data-ingestion)
#   - Neo4j 5 via official neo4j apt repo (no Docker needed)
#   - Qdrant via static binary from GitHub releases (no Docker needed)
#   - Ollama for LLM inference (driver-agnostic; replaces SGLang / LM Studio)
#   - Docker is optional — Qdrant + Neo4j run natively if daemon unavailable

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ok()    { echo -e "${GREEN}✓${NC}  $*"; }
warn()  { echo -e "${YELLOW}⚠${NC}  $*"; }
fail()  { echo -e "${RED}✗${NC}  $*"; exit 1; }
info()  { echo -e "${CYAN}▸${NC}  $*"; }
header(){ echo -e "\n${BOLD}━━━  $*  ━━━${NC}\n"; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Redirect pip cache + tmp to /workspace when available (avoids root-fs exhaustion
# on RunPod / Colab pods where root overlay is ≤20 GB but /workspace is large).
if [[ -d /workspace ]]; then
  export PIP_CACHE_DIR=/workspace/pip-cache
  export UV_CACHE_DIR=/workspace/uv-cache
  export TMPDIR=/workspace/pip-tmp
  mkdir -p "$PIP_CACHE_DIR" "$UV_CACHE_DIR" "$TMPDIR"
  info "Pip + uv cache + tmp redirected → /workspace (root-fs protection)"
fi

echo -e "\n${BOLD}Healthcare Platform — Production Prerequisites Installer${NC}"
echo -e "${CYAN}Repo root: ${REPO_ROOT}${NC}\n"

[[ "$(uname -s)" == "Linux" ]]  || fail "Linux only."
[[ "$(uname -m)" == "x86_64" ]] || fail "x86_64 required."
command -v apt-get >/dev/null    || fail "apt-get not found."
[[ "$(id -u)" -eq 0 ]]          || fail "Run as root."

. /etc/os-release
info "Detected: ${PRETTY_NAME} on $(uname -m)"

# ── 1. System Packages ────────────────────────────────────────────────────────
header "System Packages"

export DEBIAN_FRONTEND=noninteractive

info "Updating apt cache…"
apt-get update -qq

APT_PKGS=(
  # suppress debconf / package-config warnings on minimal images
  apt-utils
  # core tools
  curl wget git jq ca-certificates gnupg lsb-release netcat-openbsd
  # build tools
  build-essential software-properties-common pkg-config
  # Python build / runtime deps
  libssl-dev libffi-dev zlib1g-dev libbz2-dev libreadline-dev
  libsqlite3-dev libncursesw5-dev xz-utils libxml2-dev libxmlsec1-dev liblzma-dev
  python3-dev python3-venv python3-pip
  # Python 3.11 for data-ingestion (3.11 pins)
  python3.11 python3.11-venv python3.11-dev
  # OCR / ML system libs
  poppler-utils tesseract-ocr libmagic-dev libgomp1
  # Java 21 — required by Neo4j 5
  openjdk-21-jdk
  # Misc
  zstd unzip zip git-lfs
)

info "Installing system packages…"
apt-get install -y -qq "${APT_PKGS[@]}"
ok "System packages installed"

# ── 2. Git Submodules ─────────────────────────────────────────────────────────
header "Git Submodules"

# A shallow/partial clone leaves empty mount dirs that git refuses to clone into.
# Force-remove any submodule dirs that exist but are missing pyproject.toml so
# `git submodule update --init --force` can repopulate them cleanly.
while IFS= read -r sub_path; do
  full_path="$REPO_ROOT/$sub_path"
  if [[ -d "$full_path" && ! -f "$full_path/pyproject.toml" && ! -f "$full_path/setup.py" ]]; then
    warn "Stale/empty submodule dir: $sub_path — removing before init"
    rm -rf "${full_path:?}"
  fi
done < <(git -C "$REPO_ROOT" submodule foreach --quiet --recursive 'echo $displaypath' 2>/dev/null || true)

git -C "$REPO_ROOT" submodule update --init --force --recursive
ok "Submodules initialised"

# ── 3. uv — fast parallel wheel installer ────────────────────────────────────
header "uv (parallel wheel installer)"

if ! command -v uv >/dev/null 2>&1; then
  info "Installing uv…"
  pip install uv --quiet
fi
ok "uv $(uv --version)"
header "Python 3.12"

if command -v python3.12 >/dev/null 2>&1; then
  ok "python3.12 already installed: $(python3.12 --version)"
else
  info "Adding deadsnakes PPA (direct GPG import — bypasses add-apt-repository which requires python3-apt, absent in minimal RunPod images)…"
  # Purge ALL pre-existing deadsnakes entries (old-style without Signed-By, or from prior runs)
  # to prevent "Conflicting values set for option Signed-By" apt error.
  rm -f /etc/apt/sources.list.d/*deadsnakes* /etc/apt/trusted.gpg.d/deadsnakes* 2>/dev/null || true
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0xF23C5A6CF475977595C89F51BA6932366A755776" \
    | gpg --dearmor -o /etc/apt/keyrings/deadsnakes.gpg
  echo "deb [signed-by=/etc/apt/keyrings/deadsnakes.gpg] https://ppa.launchpadcontent.net/deadsnakes/ppa/ubuntu $(lsb_release -cs) main" \
    > /etc/apt/sources.list.d/deadsnakes-ppa.list
  apt-get update -qq
  apt-get install -y -qq python3.12 python3.12-venv python3.12-dev
  ok "python3.12: $(python3.12 --version)"
fi

PYTHON312="$(command -v python3.12)"
PYTHON311="$(command -v python3.11 2>/dev/null || command -v python3)"
ok "Python 3.12 → $PYTHON312 ($(python3.12 --version))"
ok "Python 3.11 → $PYTHON311 ($("$PYTHON311" --version))"

# ── 3. Node.js 20 LTS ─────────────────────────────────────────────────────────
header "Node.js 20 LTS"

if command -v node >/dev/null 2>&1 && node --version | grep -q '^v2[0-9]'; then
  ok "Node $(node --version)"
else
  info "Installing Node.js 20 LTS via NodeSource…"
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -qq nodejs
  ok "Node $(node --version)"
fi

# ── 4. Qdrant (native static binary) ─────────────────────────────────────────
header "Qdrant (native binary)"

QDRANT_BIN="/usr/local/bin/qdrant"

if [[ -x "$QDRANT_BIN" ]]; then
  ok "Qdrant already installed: $("$QDRANT_BIN" --version 2>/dev/null | head -1 || echo 'present')"
else
  info "Resolving latest Qdrant release…"
  QDRANT_VER="$(curl -s https://api.github.com/repos/qdrant/qdrant/releases/latest \
    | grep '"tag_name"' | cut -d'"' -f4)"
  info "Downloading Qdrant ${QDRANT_VER} (musl static binary)…"
  curl -fsSL \
    "https://github.com/qdrant/qdrant/releases/download/${QDRANT_VER}/qdrant-x86_64-unknown-linux-musl.tar.gz" \
    | tar xz -C /usr/local/bin/ qdrant
  chmod +x "$QDRANT_BIN"
  ok "Qdrant ${QDRANT_VER} → $QDRANT_BIN"
fi

# ── 5. Neo4j 5 (official apt repo) ───────────────────────────────────────────
header "Neo4j 5 (native apt)"

if command -v neo4j >/dev/null 2>&1; then
  ok "Neo4j already installed: $(neo4j --version 2>/dev/null | head -1)"
else
  info "Adding Neo4j 5 official apt repository…"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://debian.neo4j.com/neotechnology.gpg.key \
    | gpg --dearmor -o /etc/apt/keyrings/neotechnology.gpg
  echo "deb [signed-by=/etc/apt/keyrings/neotechnology.gpg] https://debian.neo4j.com stable 5" \
    > /etc/apt/sources.list.d/neo4j.list
  apt-get update -qq
  apt-get install -y -qq neo4j
  ok "Neo4j installed: $(neo4j --version 2>/dev/null | head -1)"
fi

info "Configuring Neo4j credentials…"
neo4j-admin dbms set-initial-password testpassword 2>/dev/null || true
NEO4J_CONF="/etc/neo4j/neo4j.conf"
if [[ -f "$NEO4J_CONF" ]] && ! grep -q 'UseContainerSupport' "$NEO4J_CONF"; then
  echo "server.jvm.additional=-XX:+UseContainerSupport" >> "$NEO4J_CONF"
fi
ok "Neo4j configured (user: neo4j / testpassword)"

# ── 6. Python: agentic-reasoning ─────────────────────────────────────────────
header "Python: agentic-reasoning (.venv, python3.12, editable)"

REASONING_DIR="$REPO_ROOT/agentic-reasoning"
if [[ ! -d "$REASONING_DIR/.venv" ]]; then
  info "Creating venv…"
  "$PYTHON312" -m venv "$REASONING_DIR/.venv"
fi
REASONING_PIP="$REASONING_DIR/.venv/bin/pip"
REASONING_PYTHON="$REASONING_DIR/.venv/bin/python"
info "Installing uv + dependencies…"
"$REASONING_PIP" install --quiet --upgrade pip uv
REASONING_UV="$REASONING_DIR/.venv/bin/uv"
"$REASONING_UV" pip install --python "$REASONING_PYTHON" \
  --extra-index-url "https://download.pytorch.org/whl/cu124" \
  --index-strategy unsafe-best-match \
  -e "$REASONING_DIR"
ok "agentic-reasoning venv ready"

# ── 7. Python: data-acquisition ──────────────────────────────────────────────
header "Python: data-acquisition (.venv, python3.12, editable)"

ACQUISITION_DIR="$REPO_ROOT/data-acquisition"
if [[ ! -d "$ACQUISITION_DIR/.venv" ]]; then
  info "Creating venv…"
  "$PYTHON312" -m venv "$ACQUISITION_DIR/.venv"
fi
ACQUISITION_PIP="$ACQUISITION_DIR/.venv/bin/pip"
ACQUISITION_PYTHON="$ACQUISITION_DIR/.venv/bin/python"
info "Installing uv + dependencies…"
"$ACQUISITION_PIP" install --quiet --upgrade pip uv
ACQUISITION_UV="$ACQUISITION_DIR/.venv/bin/uv"
"$ACQUISITION_UV" pip install --python "$ACQUISITION_PYTHON" \
  --index-strategy unsafe-best-match \
  -e "$ACQUISITION_DIR"
"$ACQUISITION_UV" pip install --python "$ACQUISITION_PYTHON" \
  --index-strategy unsafe-best-match \
  -e "$ACQUISITION_DIR[cloud]" \
  || warn "Cloud extras (boto3/azure) skipped — install manually if needed."
ok "data-acquisition venv ready"

# ── 8. Python: data-ingestion (CUDA-aware torch) ─────────────────────────────
header "Python: data-ingestion (python3.11 venv, CUDA-aware torch)"

INGESTION_DIR="$REPO_ROOT/data-ingestion"
if [[ ! -d "$INGESTION_DIR/.venv" ]]; then
  info "Creating venv (python3.11)…"
  # data-ingestion pins Python 3.11 (see .python-version). torch + heavy GPU deps
  # are in requirements.txt; PIP_CACHE_DIR is redirected to /workspace above when
  # available, so large wheels don't exhaust the root overlay filesystem.
  "$PYTHON311" -m venv "$INGESTION_DIR/.venv"
fi

INGESTION_PIP="$INGESTION_DIR/.venv/bin/pip"
INGESTION_PYTHON="$INGESTION_DIR/.venv/bin/python"

info "Upgrading pip + installing uv into ingestion venv…"
"$INGESTION_PIP" install --quiet --upgrade pip uv
INGESTION_UV="$INGESTION_DIR/.venv/bin/uv"

info "Installing requirements via uv (torch, surya-ocr, sentence-transformers, etc.)…"
"$INGESTION_UV" pip install --python "$INGESTION_PYTHON" \
  --extra-index-url "https://download.pytorch.org/whl/cu124" \
  --index-strategy unsafe-best-match \
  -r "$INGESTION_DIR/requirements.txt"
ok "data-ingestion dependencies installed"

if "$INGESTION_PYTHON" -c "import spacy; spacy.load('en_core_web_lg')" >/dev/null 2>&1; then
  ok "spaCy model en_core_web_lg (already present)"
else
  info "Downloading spaCy model en_core_web_lg…"
  "$INGESTION_PYTHON" -m spacy download en_core_web_lg
  ok "en_core_web_lg downloaded"
fi

info "Verifying CUDA is visible to torch…"
if "$INGESTION_PYTHON" -c "import torch; assert torch.cuda.is_available()" 2>/dev/null; then
  GPU="$("$INGESTION_PYTHON" -c "import torch; print(torch.cuda.get_device_name(0))")"
  ok "torch CUDA device: ${GPU}"
else
  warn "torch.cuda.is_available() = False — check container GPU flags (--gpus all)."
fi

# ── 9. Ollama (LLM inference — driver-agnostic) ───────────────────────────────
header "Ollama (LLM inference)"

if command -v ollama &>/dev/null; then
  ok "ollama already installed: $(ollama --version 2>/dev/null | head -1)"
else
  info "Installing Ollama…"
  curl -fsSL https://ollama.com/install.sh | sh
  ok "Ollama installed"
fi

# Pull the local Ollama chat model if it is not already cached.
if ollama list 2>/dev/null | grep -q "medgemma:4b"; then
  ok "medgemma:4b already pulled"
else
  info "Pulling medgemma:4b (~3.3 GB, uses GPU automatically)…"
  ollama serve >/tmp/ollama_pull.log 2>&1 &
  OLLAMA_PID=$!
  sleep 4
  ollama pull medgemma:4b \
    || warn "Model pull failed — run 'ollama pull medgemma:4b' manually after starting ollama serve"
  kill "$OLLAMA_PID" 2>/dev/null || true
  ok "medgemma:4b ready"
fi

# ── 10. palantir-blueprint node_modules ──────────────────────────────────────
header "palantir-blueprint (npm)"

BLUEPRINT_DIR="$REPO_ROOT/palantir-blueprint"
if [[ -d "$BLUEPRINT_DIR/node_modules" ]]; then
  ok "node_modules already present"
else
  info "Running npm ci…"
  (cd "$BLUEPRINT_DIR" && npm ci --legacy-peer-deps)
  ok "node_modules installed"
fi

# ── 11. Data Directories ──────────────────────────────────────────────────────
header "Data Directories"

for d in \
  data/pdfs/raw \
  data/artifacts/extract \
  data/artifacts/convert \
  data/artifacts/clean \
  data/artifacts/chunk \
  data/neo4j \
  data/qdrant \
  data/models; do
  mkdir -p "$REPO_ROOT/$d"
done
ok "data/ subdirectory tree ready"

# ── 12. .env.local ────────────────────────────────────────────────────────────
header ".env.local"

if [[ -f "$REPO_ROOT/.env.local" ]]; then
  ok ".env.local already exists (skipping)"
else
  cp "$REPO_ROOT/.env.local.example" "$REPO_ROOT/.env.local"
  ok "Created .env.local from .env.local.example"
  warn "OLLAMA_BASE_URL defaults to http://localhost:11434 — no changes needed for single-machine setup."
fi

# ── 12. Summary ───────────────────────────────────────────────────────────────
header "Done"

echo -e "${GREEN}${BOLD}All prerequisites installed.${NC}\n"
echo -e "  ${BOLD}Next steps:${NC}\n"
echo -e "  1. ${CYAN}Start Neo4j + Qdrant:${NC}"
echo -e "       make up"
echo ""
echo -e "  2. ${CYAN}Start Ollama inference server:${NC}"
echo -e "       ollama serve &"
echo ""
echo -e "  3. ${CYAN}Start all platform services:${NC}"
echo -e "       make dev"
echo ""
echo -e "  4. ${CYAN}Verify services:${NC}"
echo -e "       make validate"
echo ""
echo -e "  5. ${CYAN}Fetch + ingest data:${NC}"
echo -e "       make acquisition-fetch SOURCE=medrxiv MAX_PDFS=10"
echo -e "       make ingestion-run N=10"
echo ""
echo -e "  6. ${CYAN}Run the agent:${NC}"
echo -e "       make reasoning-run-query QUERY=\"your question here\""
echo ""
