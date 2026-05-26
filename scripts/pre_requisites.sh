#!/usr/bin/env bash
# pre_requisites.sh — Production environment installer for Healthcare Platform.
# Target: Ubuntu 22.04 LTS, x86_64, NVIDIA GPU (CUDA 12.x), root, no Docker.
# Tested on: RunPod Secure Cloud Pod (Ubuntu 22.04 + CUDA 12.8, NVIDIA L4).
# Idempotent — safe to re-run.
#
# Design decisions:
#   - Python 3.12 via pyenv (never touches add-apt-repository / apt_pkg bindings)
#   - Neo4j 5 via official neo4j apt repo (no Docker needed)
#   - Qdrant via static binary from GitHub releases (no Docker needed)
#   - make up/down uses shell/start_services.sh when Docker is absent

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

echo -e "\n${BOLD}Healthcare Platform — Production Prerequisites Installer${NC}"
echo -e "${CYAN}Repo root: ${REPO_ROOT}${NC}\n"

[[ "$(uname -s)" == "Linux" ]]  || fail "Linux only."
[[ "$(uname -m)" == "x86_64" ]] || fail "x86_64 required."
command -v apt-get >/dev/null    || fail "apt-get not found."
[[ "$(id -u)" -eq 0 ]]          || fail "Run as root."

. /etc/os-release
info "Detected: ${PRETTY_NAME} ($(uname -m))"

# ── 1. apt essentials ─────────────────────────────────────────────────────────
header "System Packages"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq

# NOTE: we do NOT call add-apt-repository — it breaks in containers because
# python3-apt bindings are compiled against the system Python version (3.10)
# and partial apt upgrades destroy those C extension symlinks.
apt-get install -y -qq \
  curl wget git jq ca-certificates gnupg lsb-release netcat-openbsd \
  build-essential pkg-config \
  libssl-dev libffi-dev zlib1g-dev libbz2-dev libreadline-dev \
  libsqlite3-dev libncursesw5-dev xz-utils libxml2-dev libxmlsec1-dev liblzma-dev \
  libgomp1 libmagic-dev poppler-utils tesseract-ocr \
  openjdk-21-jdk \
  unzip git-lfs

ok "System packages installed"

# ── 2. Python 3.12 via pyenv ──────────────────────────────────────────────────
# pyenv compiles from source; zero interaction with system Python or apt_pkg.
header "Python 3.12 (pyenv)"

export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"

if [[ ! -d "$PYENV_ROOT" ]]; then
  info "Installing pyenv…"
  curl -fsSL https://pyenv.run | bash
fi
eval "$(pyenv init -)"

# Resolve latest available 3.12.x
PY312_VER="$(pyenv install --list 2>/dev/null | grep -E '^\s+3\.12\.[0-9]+$' | tail -1 | tr -d ' ')"
info "Installing Python ${PY312_VER} via pyenv (compiles from source — ~3 min)…"
pyenv install -s "$PY312_VER"
pyenv global "$PY312_VER"

PYTHON312="$(pyenv which python3.12)"
PYTHON311="$(command -v python3.11 2>/dev/null || command -v python3)"

ok "python3.12 → $("$PYTHON312" --version)"
ok "python3.11 → $("$PYTHON311" --version)"

# Persist pyenv in shell profile
PYENV_INIT='export PYENV_ROOT="$HOME/.pyenv"; export PATH="$PYENV_ROOT/bin:$PATH"; eval "$(pyenv init -)"'
for profile in "$HOME/.bashrc" "$HOME/.profile"; do
  [[ -f "$profile" ]] && grep -q 'pyenv init' "$profile" 2>/dev/null && continue
  { echo ""; echo "# pyenv"; echo "$PYENV_INIT"; } >> "$profile" && ok "pyenv init added to $profile"
done

# ── 3. Node.js 20 LTS ─────────────────────────────────────────────────────────
header "Node.js 20 LTS"

if command -v node >/dev/null 2>&1 && node --version | grep -q '^v2[0-9]'; then
  ok "Node $(node --version)"
else
  info "Installing Node.js 20 via NodeSource…"
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -qq nodejs
  ok "Node $(node --version)"
fi

# ── 4. Qdrant — static binary ─────────────────────────────────────────────────
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
  ok "Qdrant ${QDRANT_VER} installed → $QDRANT_BIN"
fi

# ── 5. Neo4j 5 — official apt repo ───────────────────────────────────────────
header "Neo4j 5 (native apt)"

if command -v neo4j >/dev/null 2>&1; then
  ok "Neo4j already installed: $(neo4j --version 2>/dev/null | head -1)"
else
  info "Adding Neo4j 5 official apt repository…"
  curl -fsSL https://debian.neo4j.com/neotechnology.gpg.key \
    | gpg --dearmor -o /etc/apt/keyrings/neotechnology.gpg
  echo "deb [signed-by=/etc/apt/keyrings/neotechnology.gpg] https://debian.neo4j.com stable 5" \
    > /etc/apt/sources.list.d/neo4j.list
  apt-get update -qq
  apt-get install -y -qq neo4j
  ok "Neo4j installed: $(neo4j --version 2>/dev/null | head -1)"
fi

# Set initial password to match .env.local.example (testpassword)
info "Configuring Neo4j credentials (neo4j / testpassword)…"
neo4j-admin dbms set-initial-password testpassword 2>/dev/null || true

# Disable systemd requirement — allow direct console launch in container
NEO4J_CONF="/etc/neo4j/neo4j.conf"
if [[ -f "$NEO4J_CONF" ]] && ! grep -q 'server.jvm.additional.*UseContainerSupport' "$NEO4J_CONF"; then
  echo "server.jvm.additional=-XX:+UseContainerSupport" >> "$NEO4J_CONF"
fi
ok "Neo4j configured"

# ── 6. LM Studio — lms CLI ────────────────────────────────────────────────────
header "LM Studio — lms CLI (headless Linux)"

LMS_BIN="$HOME/.lmstudio/bin/lms"
if [[ -x "$LMS_BIN" ]]; then
  ok "lms already installed: $("$LMS_BIN" --version 2>/dev/null || echo 'present')"
else
  info "Installing lms CLI…"
  TMP="$(mktemp -d)"
  curl -fsSL "https://installers.lmstudio.ai/linux/x64/lms-installer.sh" \
    -o "$TMP/lms-installer.sh" \
  && bash "$TMP/lms-installer.sh" --no-shell-integration \
  && ok "lms installed → $LMS_BIN" \
  || warn "lms install failed — try: https://lmstudio.ai/download?os=linux"
  rm -rf "$TMP"
fi

LMS_EXPORT='export PATH="$HOME/.lmstudio/bin:$PATH"'
for profile in "$HOME/.bashrc" "$HOME/.profile"; do
  [[ -f "$profile" ]] && grep -q '\.lmstudio/bin' "$profile" 2>/dev/null && continue
  { echo ""; echo "# lms CLI"; echo "$LMS_EXPORT"; } >> "$profile"
done
export PATH="$HOME/.lmstudio/bin:$PATH"
command -v lms >/dev/null 2>&1 && ok "lms on PATH" || warn "lms not yet on PATH — source ~/.bashrc"

# ── 7. Ollama ─────────────────────────────────────────────────────────────────
header "Ollama"

if command -v ollama >/dev/null 2>&1; then
  ok "Ollama: $(ollama --version 2>/dev/null | head -1)"
else
  info "Installing Ollama…"
  curl -fsSL https://ollama.com/install.sh | sh
  ok "Ollama installed"
fi

# ── 8. Python: agentic-reasoning ──────────────────────────────────────────────
header "Python: agentic-reasoning"

REASONING_DIR="$REPO_ROOT/agentic-reasoning"
[[ -d "$REASONING_DIR/.venv" ]] || "$PYTHON312" -m venv "$REASONING_DIR/.venv"
"$REASONING_DIR/.venv/bin/pip" install -q --upgrade pip
"$REASONING_DIR/.venv/bin/pip" install -q -e "$REASONING_DIR"
ok "agentic-reasoning venv ready"

# ── 9. Python: data-acquisition ───────────────────────────────────────────────
header "Python: data-acquisition"

ACQUISITION_DIR="$REPO_ROOT/data-acquisition"
[[ -d "$ACQUISITION_DIR/.venv" ]] || "$PYTHON312" -m venv "$ACQUISITION_DIR/.venv"
"$ACQUISITION_DIR/.venv/bin/pip" install -q --upgrade pip
"$ACQUISITION_DIR/.venv/bin/pip" install -q -e "$ACQUISITION_DIR"
"$ACQUISITION_DIR/.venv/bin/pip" install -q -e "$ACQUISITION_DIR[cloud]" \
  || warn "Cloud extras (boto3/azure) skipped — install manually if needed."
ok "data-acquisition venv ready"

# ── 10. Python: data-ingestion ────────────────────────────────────────────────
header "Python: data-ingestion (CUDA-aware torch)"

INGESTION_DIR="$REPO_ROOT/data-ingestion"
[[ -d "$INGESTION_DIR/.venv" ]] || "$PYTHON311" -m venv "$INGESTION_DIR/.venv"
INGESTION_PIP="$INGESTION_DIR/.venv/bin/pip"
INGESTION_PYTHON="$INGESTION_DIR/.venv/bin/python"

"$INGESTION_PIP" install -q --upgrade pip

# Install torch with CUDA 12.4 wheels first — driver 12.8 is backward-compatible.
# Prevents PyPI from serving the CPU-only wheel for the pinned version.
info "Installing torch with CUDA 12.4 wheels…"
"$INGESTION_PIP" install -q torch torchvision \
  --extra-index-url https://download.pytorch.org/whl/cu124

info "Installing remaining requirements (surya-ocr, sentence-transformers, etc.) — ~5 min…"
"$INGESTION_PIP" install -q -r "$INGESTION_DIR/requirements.txt"
ok "data-ingestion packages installed"

if "$INGESTION_PYTHON" -c "import spacy; spacy.load('en_core_web_lg')" >/dev/null 2>&1; then
  ok "spaCy en_core_web_lg present"
else
  info "Downloading spaCy en_core_web_lg…"
  "$INGESTION_PYTHON" -m spacy download en_core_web_lg
  ok "en_core_web_lg downloaded"
fi

info "Verifying CUDA…"
if "$INGESTION_PYTHON" -c "import torch; assert torch.cuda.is_available()" 2>/dev/null; then
  GPU="$("$INGESTION_PYTHON" -c "import torch; print(torch.cuda.get_device_name(0))")"
  ok "CUDA device: ${GPU}"
else
  warn "torch.cuda.is_available() = False — check container GPU flags."
fi

# ── 11. Data directories ──────────────────────────────────────────────────────
header "Data Directories"

mkdir -p "$REPO_ROOT"/{data/pdfs/raw,data/artifacts/{extract,convert,clean,chunk},data/neo4j,data/qdrant,data/models}
ok "data/ tree ready"

# ── 12. .env.local ────────────────────────────────────────────────────────────
header ".env.local"

if [[ -f "$REPO_ROOT/.env.local" ]]; then
  ok ".env.local exists (skipping)"
else
  cp "$REPO_ROOT/.env.local.example" "$REPO_ROOT/.env.local"
  ok "Created .env.local — edit LLM_MODEL before running make validate"
fi

# ── 13. Summary ───────────────────────────────────────────────────────────────
header "Done"

echo -e "${GREEN}${BOLD}All prerequisites installed.${NC}\n"
echo -e "  ${BOLD}Next steps:${NC}\n"
echo -e "  1. ${CYAN}Start Neo4j + Qdrant:${NC}       make up"
echo -e "  2. ${CYAN}Verify services:${NC}             make validate"
echo -e "  3. ${CYAN}Load a model (lms):${NC}          lms get qwen2.5-7b-instruct && lms server start"
echo -e "  4. ${CYAN}Fetch + ingest:${NC}              make fetch && make ingest"
echo -e "  5. ${CYAN}Run agent:${NC}                   make reasoning-run"
echo ""
warn "Reload shell profile: source ~/.bashrc"
echo ""
#
# Installs:
#   System:      apt essentials, build tools, OCR/ML libs (poppler, tesseract, libmagic)
#   Runtimes:    Python 3.12 (deadsnakes PPA), Node.js 20 LTS
#   Docker:      Engine via official apt repo; pulls neo4j:5 + qdrant/qdrant:latest
#   Inference:   LM Studio lms CLI (headless Linux), Ollama
#   Python envs: agentic-reasoning (.venv python3.12, editable)
#                data-acquisition (.venv python3.12, editable + cloud extras)
#                data-ingestion (python3.11 venv, CUDA-aware torch, requirements.txt)
#   Config:      .env.local from .env.local.example (skip if exists)
#   Directories: data/{pdfs/raw,artifacts/*,neo4j,qdrant,models}

set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ok()    { echo -e "${GREEN}✓${NC}  $*"; }
warn()  { echo -e "${YELLOW}⚠${NC}  $*"; }
fail()  { echo -e "${RED}✗${NC}  $*"; exit 1; }
info()  { echo -e "${CYAN}▸${NC}  $*"; }
header(){ echo -e "\n${BOLD}━━━  $*  ━━━${NC}\n"; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo -e "\n${BOLD}Healthcare Platform — Production Prerequisites Installer${NC}"
echo -e "${CYAN}Repo root: ${REPO_ROOT}${NC}\n"

# ── 0. Platform guard ─────────────────────────────────────────────────────────
[[ "$(uname -s)" == "Linux" ]]  || fail "This script targets Linux only."
[[ "$(uname -m)" == "x86_64" ]] || fail "x86_64 architecture required."
command -v apt-get >/dev/null 2>&1 || fail "apt-get not found — Debian/Ubuntu required."
[[ "$(id -u)" -eq 0 ]] || fail "Run as root (sudo ./scripts/pre_requisites.sh)."

. /etc/os-release
info "Detected: ${PRETTY_NAME} on $(uname -m)"

# ── 1. apt essentials ─────────────────────────────────────────────────────────
header "System Packages"

export DEBIAN_FRONTEND=noninteractive

info "Updating apt cache…"
apt-get update -qq

APT_PKGS=(
  # core tools
  curl wget git jq ca-certificates gnupg lsb-release netcat-openbsd
  # build tools
  build-essential software-properties-common pkg-config
  # Python build deps
  libssl-dev libffi-dev python3-dev python3-venv python3-pip
  # OCR / ML system libs
  poppler-utils          # required by pdf2image (data-ingestion stage 1)
  tesseract-ocr          # OCR fallback engine
  libmagic-dev           # filetype detection (python-magic)
  libgomp1               # OpenMP runtime for scikit-learn / torch
  # Misc
  unzip zip git-lfs
)

info "Installing system packages…"
apt-get install -y -qq "${APT_PKGS[@]}"
ok "System packages installed"

# ── 2. Python 3.12 (deadsnakes PPA) ──────────────────────────────────────────
header "Python 3.12"

if command -v python3.12 >/dev/null 2>&1; then
  ok "python3.12 already installed: $(python3.12 --version)"
else
  info "Adding deadsnakes PPA…"
  add-apt-repository -y ppa:deadsnakes/ppa
  apt-get update -qq
  apt-get install -y -qq python3.12 python3.12-venv python3.12-dev
  ok "python3.12: $(python3.12 --version)"
fi

# Resolve Python binaries
PYTHON312="$(command -v python3.12)"
PYTHON311="$(command -v python3.11 2>/dev/null || command -v python3 2>/dev/null)"
ok "Python 3.12 → $PYTHON312"
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

# ── 4. Docker Engine ──────────────────────────────────────────────────────────
header "Docker Engine"

if command -v docker >/dev/null 2>&1; then
  ok "Docker already installed: $(docker --version)"
else
  info "Installing Docker Engine (official apt repo)…"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
  ok "Docker installed: $(docker --version)"
fi

# Start Docker daemon if not running (handles DinD / privileged containers)
if ! docker info >/dev/null 2>&1; then
  info "Starting Docker daemon…"
  dockerd &>/tmp/dockerd.log &
  _wait=0
  until docker info >/dev/null 2>&1; do
    (( _wait >= 30 )) && { warn "Docker daemon did not start — skipping image pulls."; break; }
    sleep 2; (( _wait += 2 ))
  done
fi

if docker info >/dev/null 2>&1; then
  ok "Docker daemon is running"

  header "Docker Images (Neo4j + Qdrant)"
  info "Pulling neo4j:5 (community — APOC bundled)…"
  docker pull neo4j:5 && ok "neo4j:5"

  info "Pulling qdrant/qdrant:latest…"
  docker pull qdrant/qdrant:latest && ok "qdrant/qdrant:latest"
else
  warn "Docker daemon unavailable — pull images manually after starting Docker."
fi

# ── 5. LM Studio — lms CLI (headless Linux) ───────────────────────────────────
header "LM Studio — lms CLI"

LMS_DIR="$HOME/.lmstudio"
LMS_BIN="$LMS_DIR/bin/lms"

if [[ -x "$LMS_BIN" ]]; then
  ok "lms CLI already installed: $("$LMS_BIN" --version 2>/dev/null || echo 'present')"
else
  info "Downloading LM Studio lms CLI for Linux x64…"
  # Official LM Studio headless CLI bootstrapper
  TMP_LMS="$(mktemp -d)"
  curl -fsSL "https://installers.lmstudio.ai/linux/x64/lms-installer.sh" \
    -o "$TMP_LMS/lms-installer.sh" && \
  bash "$TMP_LMS/lms-installer.sh" --no-shell-integration && \
  ok "lms CLI installed → $LMS_BIN" || \
  warn "lms installer failed — download manually: https://lmstudio.ai/download?os=linux"
  rm -rf "$TMP_LMS"
fi

# Add lms to PATH permanently
LMS_PATH_EXPORT='export PATH="$HOME/.lmstudio/bin:$PATH"'
for profile in "$HOME/.bashrc" "$HOME/.profile"; do
  if [[ -f "$profile" ]] && grep -q '\.lmstudio/bin' "$profile" 2>/dev/null; then
    ok "lms PATH already in $profile"
  else
    { echo ""; echo "# LM Studio lms CLI"; echo "$LMS_PATH_EXPORT"; } >> "$profile"
    ok "Added lms PATH to $profile"
  fi
done
export PATH="$LMS_DIR/bin:$PATH"

if command -v lms >/dev/null 2>&1; then
  ok "lms: $(lms --version 2>/dev/null || echo 'available')"
else
  warn "lms not on PATH yet — run: export PATH=\"\$HOME/.lmstudio/bin:\$PATH\""
fi

# ── 6. Ollama ─────────────────────────────────────────────────────────────────
header "Ollama (optional inference backend)"

if command -v ollama >/dev/null 2>&1; then
  ok "Ollama already installed: $(ollama --version 2>/dev/null | head -1)"
else
  info "Installing Ollama…"
  curl -fsSL https://ollama.com/install.sh | sh
  ok "Ollama installed"
fi

# ── 7. Python: agentic-reasoning ──────────────────────────────────────────────
header "Python: agentic-reasoning (.venv, python3.12, editable)"

REASONING_DIR="$REPO_ROOT/agentic-reasoning"
if [[ ! -d "$REASONING_DIR/.venv" ]]; then
  info "Creating venv…"
  "$PYTHON312" -m venv "$REASONING_DIR/.venv"
fi
info "Installing dependencies…"
"$REASONING_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$REASONING_DIR/.venv/bin/pip" install --quiet -e "$REASONING_DIR"
ok "agentic-reasoning venv ready"

# ── 8. Python: data-acquisition ───────────────────────────────────────────────
header "Python: data-acquisition (.venv, python3.12, editable)"

ACQUISITION_DIR="$REPO_ROOT/data-acquisition"
if [[ ! -d "$ACQUISITION_DIR/.venv" ]]; then
  info "Creating venv…"
  "$PYTHON312" -m venv "$ACQUISITION_DIR/.venv"
fi
info "Installing dependencies…"
"$ACQUISITION_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$ACQUISITION_DIR/.venv/bin/pip" install --quiet -e "$ACQUISITION_DIR"
"$ACQUISITION_DIR/.venv/bin/pip" install --quiet -e "$ACQUISITION_DIR[cloud]" || \
  warn "Cloud extras (boto3/azure) failed — install manually if needed."
ok "data-acquisition venv ready"

# ── 9. Python: data-ingestion ─────────────────────────────────────────────────
header "Python: data-ingestion (python3.11 venv, CUDA-aware torch)"

INGESTION_DIR="$REPO_ROOT/data-ingestion"

if [[ ! -d "$INGESTION_DIR/.venv" ]]; then
  info "Creating venv…"
  "$PYTHON311" -m venv "$INGESTION_DIR/.venv"
fi

INGESTION_PIP="$INGESTION_DIR/.venv/bin/pip"
INGESTION_PYTHON="$INGESTION_DIR/.venv/bin/python"

info "Upgrading pip…"
"$INGESTION_PIP" install --quiet --upgrade pip

# Install torch with CUDA 12.4 wheels first (driver 12.8 is backward-compatible).
# This prevents the CPU-only wheel being pulled from PyPI for the pinned version.
info "Installing torch with CUDA 12.4 wheels (compatible with CUDA 12.8 driver)…"
"$INGESTION_PIP" install --quiet \
  torch torchvision \
  --extra-index-url https://download.pytorch.org/whl/cu124

info "Installing remaining requirements (surya-ocr, sentence-transformers, neo4j, etc.) — this takes a few minutes…"
"$INGESTION_PIP" install --quiet -r "$INGESTION_DIR/requirements.txt"
ok "data-ingestion dependencies installed"

# spaCy en_core_web_lg — required by Presidio PII stage
if "$INGESTION_PYTHON" -c "import spacy; spacy.load('en_core_web_lg')" >/dev/null 2>&1; then
  ok "spaCy model en_core_web_lg (already present)"
else
  info "Downloading spaCy model en_core_web_lg…"
  "$INGESTION_PYTHON" -m spacy download en_core_web_lg
  ok "en_core_web_lg downloaded"
fi

# Smoke-test CUDA visibility inside the venv
info "Verifying CUDA is visible to torch…"
if "$INGESTION_PYTHON" -c "import torch; assert torch.cuda.is_available(), 'CUDA not available'" 2>/dev/null; then
  CUDA_DEV="$("$INGESTION_PYTHON" -c "import torch; print(torch.cuda.get_device_name(0))")"
  ok "torch CUDA device: ${CUDA_DEV}"
else
  warn "torch.cuda.is_available() = False — check CUDA driver / container flags."
fi

# ── 10. Data directories ──────────────────────────────────────────────────────
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

# ── 11. .env.local ────────────────────────────────────────────────────────────
header ".env.local"

if [[ -f "$REPO_ROOT/.env.local" ]]; then
  ok ".env.local already exists (skipping)"
else
  cp "$REPO_ROOT/.env.local.example" "$REPO_ROOT/.env.local"
  ok "Created .env.local from .env.local.example"
  warn "Edit .env.local — set LLM_MODEL to the model you'll load via lms or Ollama."
fi

# ── 12. Summary ───────────────────────────────────────────────────────────────
header "Done"

echo -e "${GREEN}${BOLD}All prerequisites installed.${NC}\n"
echo -e "  ${BOLD}Next steps:${NC}\n"
echo -e "  1. ${CYAN}Start LM Studio server (headless):${NC}"
echo -e "       lms server start"
echo -e "       lms get <model-name>   # e.g. lms get qwen2.5-7b-instruct"
echo ""
echo -e "  2. ${CYAN}Start infrastructure (Neo4j + Qdrant):${NC}"
echo -e "       make up"
echo ""
echo -e "  3. ${CYAN}Verify all services:${NC}"
echo -e "       make validate"
echo ""
echo -e "  4. ${CYAN}Fetch + ingest data:${NC}"
echo -e "       make fetch SOURCE=medrxiv MAX_PDFS=10"
echo -e "       make ingest N=10"
echo ""
echo -e "  5. ${CYAN}Run the agent:${NC}"
echo -e "       make reasoning-run"
echo ""
warn "Source your shell profile to activate lms PATH: source ~/.bashrc"
echo ""
