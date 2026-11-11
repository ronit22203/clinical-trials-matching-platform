#!/usr/bin/env bash
# pre_requisites.sh — Production environment installer for Healthcare Platform.
# Target: Ubuntu 22.04 LTS, x86_64, NVIDIA GPU (CUDA 12.x / 13.x), root.
# Tested on: RunPod Secure Cloud Pod (Ubuntu 22.04 + CUDA 13.0, NVIDIA L4).
# Idempotent — safe to re-run.
#
# Design decisions:
#   - Python 3.12 via deadsnakes PPA (Python 3.11 via apt for data-ingestion)
#   - uv comes from the standalone installer. System pip is never used: Ubuntu
#     23.04+ rejects it with PEP 668 EXTERNALLY-MANAGED. Project deps go into
#     `python3 -m venv` environments only.
#   - Pip/uv cache and tmp always leave $HOME. /workspace when that mount
#     exists, otherwise /var/cache/healthcare-platform.
#   - Neo4j 5 via official neo4j apt repo (no Docker needed)
#   - Qdrant via static binary from GitHub releases (no Docker needed)
#   - Ollama for LLM inference (driver-agnostic; replaces SGLang / LM Studio)
#   - Docker is optional — Qdrant + Neo4j run natively if daemon unavailable
#   - Blank AUTH_PASSWORD_HASH / AUTH_JWT_SECRET are filled (login admin / admin)
#   - NVIDIA hosts with a running Docker daemon use Surya's vLLM OCR backend.
#     Hosts without Docker fall back to llama.cpp. llama-server is built from
#     source (tag b11429) only when nvidia-smi reports a numeric compute
#     capability; the published CUDA archive needs glibc 2.38.
#   - nvcc is resolved from CUDA_HOME, /usr/local/cuda, /usr/local/cuda-*,
#     /usr/lib/cuda, and PATH, then linked at /usr/local/cuda when that path
#     is missing. libcudart is registered with ldconfig.
#   - Neo4j, Qdrant, and both FastAPI servers bind 0.0.0.0. Client URLs in
#     .env.local use 127.0.0.1 so health checks do not follow localhost to ::1.

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ok()    { echo -e "${GREEN}✓${NC}  $*"; }
warn()  { echo -e "${YELLOW}⚠${NC}  $*"; }
fail()  { echo -e "${RED}✗${NC}  $*"; exit 1; }
info()  { echo -e "${CYAN}▸${NC}  $*"; }
header(){ echo -e "\n${BOLD}━━━  $*  ━━━${NC}\n"; }

# A usable llama-server prints a version and is not the Ubuntu 24.04 CUDA
# archive, which fails to start on this image's glibc 2.35.
llama_server_ok() {
  local bin="$1"
  local out
  [[ -e "$bin" ]] || return 1
  out="$("$bin" --version 2>&1)" || return 1
  case "$out" in
    *GLIBC_2.38*|*GLIBCXX_3.4.32*) return 1 ;;
  esac
  [[ -n "$out" ]]
}

# Cloud images often install a versioned toolkit and omit the /usr/local/cuda
# symlink (RunPod, DLAMI, Lambda, GCP). llama.cpp and Surya both need nvcc
# plus libcudart on the loader path, not just the driver from nvidia-smi.
resolve_cuda_home() {
  local candidate="" nvcc_bin="" versioned=""
  if [[ -n "${CUDA_HOME:-}" && -x "${CUDA_HOME}/bin/nvcc" ]]; then
    printf '%s\n' "$CUDA_HOME"
    return 0
  fi
  if [[ -x /usr/local/cuda/bin/nvcc ]]; then
    printf '%s\n' /usr/local/cuda
    return 0
  fi
  if command -v nvcc >/dev/null 2>&1; then
    nvcc_bin="$(readlink -f "$(command -v nvcc)")"
    candidate="$(cd "$(dirname "$nvcc_bin")/.." && pwd)"
    if [[ -x "${candidate}/bin/nvcc" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  fi
  versioned="$(find /usr/local -maxdepth 1 -type d -name 'cuda-[0-9]*' 2>/dev/null | sort -V | tail -1 || true)"
  if [[ -n "$versioned" && -x "${versioned}/bin/nvcc" ]]; then
    printf '%s\n' "$versioned"
    return 0
  fi
  if [[ -x /usr/lib/cuda/bin/nvcc ]]; then
    printf '%s\n' /usr/lib/cuda
    return 0
  fi
  return 1
}

persist_cuda_home() {
  local home="$1"
  local libdir=""
  export CUDA_HOME="$home"
  export CUDAToolkit_ROOT="$home"
  case ":${PATH}:" in
    *":${home}/bin:"*) ;;
    *) export PATH="${home}/bin:${PATH}" ;;
  esac
  if [[ -d "${home}/lib64" ]]; then
    libdir="${home}/lib64"
  elif [[ -d "${home}/lib" ]]; then
    libdir="${home}/lib"
  fi
  if [[ -n "$libdir" ]]; then
    case ":${LD_LIBRARY_PATH:-}:" in
      *":${libdir}:"*) ;;
      *) export LD_LIBRARY_PATH="${libdir}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" ;;
    esac
    printf '%s\n' "$libdir" > /etc/ld.so.conf.d/cuda-healthcare.conf
    ldconfig
  fi
  {
    printf 'export CUDA_HOME=%q\n' "$home"
    printf 'export CUDAToolkit_ROOT=%q\n' "$home"
    printf 'export PATH="%s/bin:$PATH"\n' "$home"
    if [[ -n "$libdir" ]]; then
      printf 'export LD_LIBRARY_PATH="%s${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\n' "$libdir"
    fi
  } > /etc/profile.d/cuda-healthcare.sh
  if [[ ! -e /usr/local/cuda ]]; then
    ln -sfn "$home" /usr/local/cuda
  elif [[ -L /usr/local/cuda && ! -x /usr/local/cuda/bin/nvcc ]]; then
    ln -sfn "$home" /usr/local/cuda
  fi
}

add_deadsnakes_ppa() {
  if [[ -f /etc/apt/sources.list.d/deadsnakes-ppa.list ]]; then
    return 0
  fi
  info "Adding deadsnakes PPA (direct GPG import — bypasses add-apt-repository)…"
  # Purge ALL pre-existing deadsnakes entries (old-style without Signed-By, or from prior runs)
  # to prevent "Conflicting values set for option Signed-By" apt error.
  rm -f /etc/apt/sources.list.d/*deadsnakes* /etc/apt/trusted.gpg.d/deadsnakes* 2>/dev/null || true
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0xF23C5A6CF475977595C89F51BA6932366A755776" \
    | gpg --dearmor -o /etc/apt/keyrings/deadsnakes.gpg
  echo "deb [signed-by=/etc/apt/keyrings/deadsnakes.gpg] https://ppa.launchpadcontent.net/deadsnakes/ppa/ubuntu $(lsb_release -cs) main" \
    > /etc/apt/sources.list.d/deadsnakes-ppa.list
  apt-get update -qq
}

ensure_python() {
  local ver="$1"
  if command -v "python${ver}" >/dev/null 2>&1 \
    && dpkg -s "python${ver}-venv" >/dev/null 2>&1 \
    && dpkg -s "python${ver}-dev" >/dev/null 2>&1; then
    ok "python${ver} already installed: $(python${ver} --version)"
    return 0
  fi
  info "Installing python${ver} (interpreter, venv, headers)…"
  if ! apt-get install -y -qq "python${ver}" "python${ver}-venv" "python${ver}-dev"; then
    warn "python${ver} is not in the distro repos — trying deadsnakes"
    add_deadsnakes_ppa
    apt-get install -y -qq "python${ver}" "python${ver}-venv" "python${ver}-dev"
  fi
  ok "python${ver}: $(python${ver} --version)"
}

# Neo4j 5's apt package leaves bolt on localhost unless these keys are set.
# A health check that arrives on the instance address, or via IPv4 127.0.0.1
# while `localhost` resolved to ::1, then fails even though the process is up.
neo4j_set() {
  local key="$1" value="$2" escaped
  [[ -f "${NEO4J_CONF:-}" ]] || return 0
  escaped="$(printf '%s' "$key" | sed 's/[.[*^$]/\\&/g')"
  if grep -qE "^[# ]*${escaped}=" "$NEO4J_CONF"; then
    sed -i -E "s|^[# ]*${escaped}=.*|${key}=${value}|" "$NEO4J_CONF"
  else
    printf '%s=%s\n' "$key" "$value" >> "$NEO4J_CONF"
  fi
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Torch / Surya wheels are multi-GB. On RunPod the root overlay is ~20 GB and
# /workspace is the large disk. Other cloud VMs get a dedicated cache root so
# pip never falls back to ~/.cache on a full root filesystem.
if [[ -d /workspace && -w /workspace ]]; then
  CACHE_ROOT=/workspace
else
  CACHE_ROOT=/var/cache/healthcare-platform
fi
export PIP_CACHE_DIR="${CACHE_ROOT}/pip-cache"
export UV_CACHE_DIR="${CACHE_ROOT}/uv-cache"
export TMPDIR="${CACHE_ROOT}/tmp"
mkdir -p "$PIP_CACHE_DIR" "$UV_CACHE_DIR" "$TMPDIR"
chmod 1777 "$PIP_CACHE_DIR" "$UV_CACHE_DIR" "$TMPDIR"
cat > /etc/profile.d/healthcare-pip-cache.sh <<EOF
export PIP_CACHE_DIR=${PIP_CACHE_DIR}
export UV_CACHE_DIR=${UV_CACHE_DIR}
export TMPDIR=${TMPDIR}
EOF
info "Pip + uv cache + tmp → ${CACHE_ROOT}"

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
  # build tools (cmake + libcurl + ninja: from-source llama-server)
  build-essential cmake ninja-build software-properties-common pkg-config libcurl4-openssl-dev
  # Python build / runtime deps. Versioned 3.11/3.12 interpreters are installed
  # later so a missing distro package does not abort this batch (PEP 668 hosts
  # still need python3-venv before `python3 -m venv` will succeed).
  libssl-dev libffi-dev zlib1g-dev libbz2-dev libreadline-dev
  libsqlite3-dev libncursesw5-dev xz-utils libxml2-dev libxmlsec1-dev liblzma-dev
  python3-dev python3-venv python3-pip
  # Surya v2 / OpenCV / poppler runtime on a minimal cloud image
  poppler-utils tesseract-ocr libmagic-dev libgomp1
  libglib2.0-0 libgl1 libsm6 libxext6 libxrender1
  # Java 21 — required by Neo4j 5
  openjdk-21-jdk
  # Misc
  zstd unzip zip git-lfs
)

info "Installing system packages…"
apt-get install -y -qq "${APT_PKGS[@]}"
ok "System packages installed"

header "CUDA toolkit"

if cuda_home="$(resolve_cuda_home)"; then
  persist_cuda_home "$cuda_home"
  ok "CUDA toolkit: ${CUDA_HOME} ($(${CUDA_HOME}/bin/nvcc --version 2>/dev/null | tail -1))"
else
  warn "nvcc not found under CUDA_HOME, /usr/local/cuda, /usr/local/cuda-*, /usr/lib/cuda, or PATH."
  warn "The NVIDIA driver alone is not enough to compile llama-server. Install the CUDA toolkit or symlink it to /usr/local/cuda."
fi

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

# Never `pip install` into the system interpreter. Ubuntu 23.04+ and Debian 12
# ship EXTERNALLY-MANAGED and abort that command. The Astral installer drops a
# static binary; project packages are installed later inside venvs.
if ! command -v uv >/dev/null 2>&1; then
  info "Installing uv via the standalone installer (not system pip)…"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi
if ! command -v uv >/dev/null 2>&1; then
  for candidate in /usr/local/bin/uv /root/.local/bin/uv "${HOME}/.local/bin/uv"; do
    if [[ -x "$candidate" ]]; then
      ln -sfn "$candidate" /usr/local/bin/uv
      break
    fi
  done
fi
command -v uv >/dev/null 2>&1 || fail "uv install did not put a binary on PATH"
ok "uv $(uv --version)"

header "Python 3.12 and 3.11"

ensure_python 3.12
ensure_python 3.11

PYTHON312="$(command -v python3.12)"
PYTHON311="$(command -v python3.11)"
[[ -n "$PYTHON312" && -x "$PYTHON312" ]] || fail "python3.12 is not on PATH after install"
[[ -n "$PYTHON311" && -x "$PYTHON311" ]] || fail "python3.11 is not on PATH after install"
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

QDRANT_CFG="$REPO_ROOT/config/qdrant.yaml"
if [[ ! -f "$QDRANT_CFG" ]]; then
  cat > "$QDRANT_CFG" <<'EOF'
storage:
  storage_path: data/qdrant
service:
  host: 0.0.0.0
  http_port: 6333
  grpc_port: 6334
EOF
  ok "Wrote config/qdrant.yaml (bind 0.0.0.0:6333)"
elif grep -qE '^[[:space:]]*host:[[:space:]]*(127\.0\.0\.1|localhost|::1)[[:space:]]*$' "$QDRANT_CFG"; then
  sed -i -E 's|^([[:space:]]*host:)[[:space:]]*.*$|\1 0.0.0.0|' "$QDRANT_CFG"
  ok "Qdrant service host set to 0.0.0.0"
else
  ok "config/qdrant.yaml binds a non-loopback host"
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
neo4j_set server.default_listen_address 0.0.0.0
neo4j_set server.bolt.listen_address 0.0.0.0:7687
neo4j_set server.http.listen_address 0.0.0.0:7474
neo4j_set server.bolt.enabled true
neo4j_set server.http.enabled true
ok "Neo4j configured (user: neo4j / testpassword, bolt 0.0.0.0:7687)"

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

AUTH_GENERATED=0
if [[ ! -f "$REPO_ROOT/.env.local" ]]; then
  cp "$REPO_ROOT/.env.local.example" "$REPO_ROOT/.env.local"
  ok "Created .env.local from .env.local.example"
else
  ok ".env.local already exists"
fi

# Inject host/port values from the process environment when a cloud template
# set them, fill anything the example left out, and stop client URLs using
# `localhost` (on Ubuntu that often resolves to ::1, so a service bound on
# IPv4 fails `make validate` and the native startup probes).
"$PYTHON312" - "$REPO_ROOT/.env.local" <<'PY'
import os
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
lines = env_path.read_text().splitlines()

CLIENT_DEFAULTS = {
    "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
    "NEO4J_URI": "bolt://127.0.0.1:7687",
    "QDRANT_URL": "http://127.0.0.1:6333",
}
BIND_DEFAULTS = {
    "REASONING_API_HOST": "0.0.0.0",
    "INGESTION_API_HOST": "0.0.0.0",
}
PORT_DEFAULTS = {
    "REASONING_API_PORT": "8000",
    "INGESTION_API_PORT": "8002",
}
# Copied in only when the cloud environment set them and the file is blank.
# Auth is included so a template secret is not replaced by the generated one.
INJECT_IF_BLANK = (
    "NEO4J_USER",
    "NEO4J_PASSWORD",
    "AUTH_USERNAME",
    "AUTH_PASSWORD_HASH",
    "AUTH_JWT_SECRET",
    "AUTH_TOKEN_EXPIRE_MINUTES",
)


def parse(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    if " #" in value:
        value = value.split(" #", 1)[0]
    return value.strip()


def find(key: str) -> tuple[int | None, str]:
    prefix = f"{key}="
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            return index, parse(line.split("=", 1)[1])
    return None, ""


def render(value: str) -> str:
    if value == "" or any(char in value for char in " #'\"$"):
        return "'" + value.replace("'", "'\"'\"'") + "'"
    return value


def put(key: str, value: str) -> None:
    index, _current = find(key)
    line = f"{key}={render(value)}"
    if index is None:
        lines.append(line)
    else:
        lines[index] = line


def rewrite_loopback(url: str) -> str:
    for host in ("localhost", "[::1]", "::1"):
        url = url.replace(f"://{host}", "://127.0.0.1")
    return url


for key, default in {**CLIENT_DEFAULTS, **BIND_DEFAULTS, **PORT_DEFAULTS}.items():
    env_value = os.environ.get(key, "").strip()
    _index, current = find(key)
    if env_value:
        value = env_value
    elif current:
        value = current
    else:
        value = default
    if key in CLIENT_DEFAULTS:
        value = rewrite_loopback(value)
    if key in BIND_DEFAULTS and value in {"127.0.0.1", "localhost", "::1"}:
        value = "0.0.0.0"
    put(key, value)

for key in INJECT_IF_BLANK:
    env_value = os.environ.get(key, "").strip()
    _index, current = find(key)
    if env_value and not current:
        put(key, env_value)

env_path.write_text("\n".join(lines) + "\n")
PY
ok "Service URLs point at 127.0.0.1; API bind hosts are 0.0.0.0"

# Fill only blank auth keys. An existing hash or secret is left alone so a
# re-run does not rotate the password. The bcrypt hash is single-quoted
# because the loaders strip one pair of quotes and otherwise keep `$2b$…`.
auth_status="$("$REASONING_PYTHON" - "$REPO_ROOT/.env.local" "$REPO_ROOT/scripts/hash_password.py" <<'PY'
import secrets
import subprocess
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
hasher = Path(sys.argv[2])
lines = env_path.read_text().splitlines()


def parse(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    if " #" in value:
        value = value.split(" #", 1)[0]
    return value.strip()


def find(key: str) -> tuple[int | None, str]:
    prefix = f"{key}="
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            return index, parse(line.split("=", 1)[1])
    return None, ""


def put(index: int | None, key: str, rendered: str) -> None:
    line = f"{key}={rendered}"
    if index is None:
        lines.append(line)
    else:
        lines[index] = line


hash_index, hash_value = find("AUTH_PASSWORD_HASH")
secret_index, secret_value = find("AUTH_JWT_SECRET")
generated_hash = False
filled_secret = False

if not hash_value:
    hashed = subprocess.check_output(
        [sys.executable, str(hasher), "admin"],
        text=True,
    ).strip()
    put(hash_index, "AUTH_PASSWORD_HASH", f"'{hashed}'")
    generated_hash = True

if not secret_value:
    put(secret_index, "AUTH_JWT_SECRET", secrets.token_hex(32))
    filled_secret = True

if generated_hash or filled_secret:
    env_path.write_text("\n".join(lines) + "\n")

if generated_hash:
    print("generated")
elif filled_secret:
    print("secret")
else:
    print("kept")
PY
)"

case "$auth_status" in
  generated)
    AUTH_GENERATED=1
    ok "Login credentials written — username admin, password admin"
    ;;
  secret)
    ok "AUTH_JWT_SECRET was blank and has been written; existing password hash left unchanged"
    ;;
  kept)
    ok "AUTH_PASSWORD_HASH and AUTH_JWT_SECRET already set (left unchanged)"
    ;;
  *)
    fail "Unexpected auth setup result: ${auth_status}"
    ;;
esac

# ── 13. OCR runtime ───────────────────────────────────────────────────────────
header "OCR runtime"

# The repository default stays device: mps / inference_backend: auto for Mac.
# On this host, rewrite only the data_ingestion.ocr block of the working copy.
# Docker present → pin vllm. A previous failed run may have written llama.cpp,
# and `auto` can miss a virtualized GPU whose compute capability is [N/A].
USE_LLAMA_CPP=0
OCR_BACKEND_SELECTED=""
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  ocr_backend=""
  if docker info >/dev/null 2>&1; then
    info "Docker is running — OCR recognition will use vLLM."
    ocr_backend="vllm"
    OCR_BACKEND_SELECTED="vllm"
  else
    info "No Docker daemon — OCR recognition will use llama.cpp instead of vLLM."
    ocr_backend="llama.cpp"
    OCR_BACKEND_SELECTED="llama.cpp"
    USE_LLAMA_CPP=1
  fi

  ocr_status="$(python3 - "$REPO_ROOT/config/app.yaml" "$ocr_backend" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
backend = sys.argv[2]
lines = path.read_text().splitlines()

start = next(
    (index for index, line in enumerate(lines) if line == "  ocr:"),
    None,
)
if start is None:
    raise SystemExit("data_ingestion.ocr block not found in config/app.yaml")

end = len(lines)
for index in range(start + 1, len(lines)):
    line = lines[index]
    if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":"):
        end = index
        break

updates = {"device": "cuda"}
if backend:
    updates["inference_backend"] = backend

changed = False
for key, value in updates.items():
    pattern = re.compile(rf"^(    {key}:\s*)(\S+)(.*)$")
    found = False
    for index in range(start, end):
        match = pattern.match(lines[index])
        if not match:
            continue
        found = True
        if match.group(2) != value:
            lines[index] = f"{match.group(1)}{value}{match.group(3)}"
            changed = True
        break
    if not found:
        raise SystemExit(f"{key} not found in the data_ingestion.ocr block")

if changed:
    path.write_text("\n".join(lines) + "\n")
    print("updated")
else:
    print("unchanged")
PY
)"
  case "$ocr_status" in
    updated)
      if [[ -n "$ocr_backend" ]]; then
        ok "Set data_ingestion.ocr device=cuda and inference_backend=${ocr_backend}"
      else
        ok "Set data_ingestion.ocr device=cuda (inference_backend unchanged)"
      fi
      ;;
    unchanged)
      ok "data_ingestion.ocr already matches this host"
      ;;
    *)
      fail "Unexpected OCR config result: ${ocr_status}"
      ;;
  esac
else
  warn "nvidia-smi unavailable — leaving config/app.yaml OCR settings unchanged."
fi

# ── 14. llama-server ──────────────────────────────────────────────────────────
if [[ "$USE_LLAMA_CPP" -eq 1 ]]; then
  header "llama-server (CUDA, built from source)"

  existing_bin="$(command -v llama-server 2>/dev/null || true)"
  if [[ -n "$existing_bin" ]] && llama_server_ok "$existing_bin"; then
    ok "llama-server already usable: $("$existing_bin" --version 2>&1 | head -1)"
  else
    if [[ -z "${CUDA_HOME:-}" || ! -x "${CUDA_HOME}/bin/nvcc" ]]; then
      if cuda_home="$(resolve_cuda_home)"; then
        persist_cuda_home "$cuda_home"
      fi
    fi
    nvcc="${CUDA_HOME:-}/bin/nvcc"
    if [[ ! -x "$nvcc" ]]; then
      fail "CUDA toolkit compiler not found. Searched CUDA_HOME, /usr/local/cuda, /usr/local/cuda-*, /usr/lib/cuda, and PATH. Install the toolkit or symlink it to /usr/local/cuda."
    fi

    compute_cap="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1 | tr -d '[:space:]')"
    if [[ ! "$compute_cap" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
      fail "nvidia-smi compute capability is '${compute_cap:-empty}', which nvcc cannot target. Do not build llama.cpp on this host. Install Docker, start the daemon, and re-run this script so OCR uses vLLM."
    fi
    cuda_arch="${compute_cap//./}"
    info "Building llama.cpp b11429 for sm_${cuda_arch} with ${nvcc}"

    if [[ -d /opt/llama.cpp && ! -d /opt/llama.cpp/.git ]]; then
      warn "Removing incomplete /opt/llama.cpp"
      rm -rf /opt/llama.cpp
    fi
    if [[ ! -d /opt/llama.cpp/.git ]]; then
      git clone --depth 1 --branch b11429 \
        https://github.com/ggml-org/llama.cpp.git /opt/llama.cpp
    else
      current_tag="$(git -C /opt/llama.cpp describe --tags --exact-match 2>/dev/null || true)"
      if [[ "$current_tag" != "b11429" ]]; then
        git -C /opt/llama.cpp fetch --depth 1 origin refs/tags/b11429:refs/tags/b11429
        git -C /opt/llama.cpp checkout --detach refs/tags/b11429
      fi
    fi

    export PATH="${CUDA_HOME}/bin:${PATH}"
    export CUDAToolkit_ROOT="${CUDA_HOME}"
    build_jobs="$(nproc)"
    if (( build_jobs > 8 )); then
      build_jobs=8
    fi
    cmake -S /opt/llama.cpp -B /opt/llama.cpp/build \
      -DGGML_CUDA=ON \
      -DCMAKE_CUDA_ARCHITECTURES="${cuda_arch}" \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_CUDA_COMPILER="${nvcc}" \
      -DCUDAToolkit_ROOT="${CUDA_HOME}"
    cmake --build /opt/llama.cpp/build -j "${build_jobs}" --target llama-server
    ln -sfn /opt/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server
    llama_server_ok /usr/local/bin/llama-server \
      || fail "llama-server at /usr/local/bin/llama-server failed --version (refusing a glibc-mismatched binary)"
    ok "llama-server $(/usr/local/bin/llama-server --version 2>&1 | head -1)"
  fi
fi

# ── 15. Summary ───────────────────────────────────────────────────────────────
header "Done"

echo -e "${GREEN}${BOLD}All prerequisites installed.${NC}\n"
if [[ "$AUTH_GENERATED" -eq 1 ]]; then
  echo -e "  ${BOLD}Login:${NC} admin / admin"
  echo ""
fi
if [[ "$USE_LLAMA_CPP" -eq 1 ]]; then
  echo -e "  ${BOLD}OCR recognition:${NC} llama.cpp (llama-server on PATH)."
  echo -e "  The first ingest still downloads the Surya GGUF from Hugging Face."
  echo -e "  If ${CYAN}make dev${NC} is already running, restart it from the repo root."
  echo -e "  Uvicorn reads config/app.yaml once and caches the OCR backend."
  echo ""
elif [[ "$OCR_BACKEND_SELECTED" == "vllm" ]]; then
  echo -e "  ${BOLD}OCR recognition:${NC} vLLM (Surya starts it through Docker on the first ingest)."
  echo -e "  Confirm the GPU is visible inside Docker before ingesting:"
  echo -e "    docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu24.04 nvidia-smi"
  echo -e "  Chat inference stays on Ollama (medgemma:4b). vLLM is the OCR backend only."
  echo -e "  If ${CYAN}make dev${NC} is already running, restart it from the repo root."
  echo -e "  Uvicorn reads config/app.yaml once and caches the OCR backend."
  echo ""
fi
echo -e "  ${BOLD}Next steps:${NC}\n"
echo -e "  ${BOLD}Bind:${NC} reasoning :8000, ingestion :8002, Qdrant :6333, and Neo4j :7687 listen on 0.0.0.0."
echo -e "  Health checks use 127.0.0.1 (not localhost) so they do not follow ::1."
echo ""
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
