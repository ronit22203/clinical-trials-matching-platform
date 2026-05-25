#!/usr/bin/env bash
# pre_requisites.sh — Full production environment installer for Healthcare Platform.
# macOS (Apple Silicon / Intel) only. Idempotent — safe to re-run.
#
# Installs:
#   System:      Homebrew, git, curl, wget, jq, nc
#   Runtimes:    Python 3.12, Python 3.11, Node.js 20
#   Inference:   LM Studio (app + lms CLI), Ollama
#   Docker:      Docker Desktop, pulls neo4j:5 + qdrant/qdrant:latest
#   OCR/ML deps: poppler, tesseract, libmagic
#   Python envs: agentic-reasoning (.venv, editable), data-acquisition (.venv, editable)
#                data-ingestion (pip into system python3.11)
#   Config:      .env.local from .env.local.example (skip if exists)
#   Directories: data/{pdfs,artifacts,neo4j,qdrant,models}

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
[[ "$(uname -s)" == "Darwin" ]] || fail "This script targets macOS only."

ARCH="$(uname -m)"
info "Detected: macOS $(sw_vers -productVersion) on ${ARCH}"

# ── 1. Homebrew ───────────────────────────────────────────────────────────────
header "Homebrew"

if ! command -v brew >/dev/null 2>&1; then
  info "Installing Homebrew…"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  # Add to PATH for this session (Apple Silicon default path)
  if [[ "$ARCH" == "arm64" ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  else
    eval "$(/usr/local/bin/brew shellenv)"
  fi
else
  ok "Homebrew $(brew --version | head -1)"
fi

info "Updating Homebrew…"
brew update --quiet

# ── 2. Core system tools ──────────────────────────────────────────────────────
header "System Tools"

BREW_PKGS=(git curl wget jq netcat)
for pkg in "${BREW_PKGS[@]}"; do
  if brew list "$pkg" &>/dev/null; then
    ok "$pkg (already installed)"
  else
    info "Installing $pkg…"
    brew install "$pkg"
    ok "$pkg"
  fi
done

# ── 3. OCR & ML system deps ───────────────────────────────────────────────────
header "OCR / ML System Libraries"

# poppler: required by pdf2image (data-ingestion stage 1 fallback)
# tesseract: OCR fallback
# libmagic: filetype detection used by ingestion

OCR_PKGS=(poppler tesseract libmagic)
for pkg in "${OCR_PKGS[@]}"; do
  if brew list "$pkg" &>/dev/null; then
    ok "$pkg (already installed)"
  else
    info "Installing $pkg…"
    brew install "$pkg"
    ok "$pkg"
  fi
done

# ── 4. Python runtimes ────────────────────────────────────────────────────────
header "Python Runtimes"

# agentic-reasoning + data-acquisition require Python 3.12+
# data-ingestion pins to Python 3.11.x via .python-version

if brew list python@3.12 &>/dev/null; then
  ok "Python 3.12 (already installed)"
else
  info "Installing Python 3.12…"
  brew install python@3.12
  ok "Python 3.12"
fi

if brew list python@3.11 &>/dev/null; then
  ok "Python 3.11 (already installed)"
else
  info "Installing Python 3.11…"
  brew install python@3.11
  ok "Python 3.11"
fi

PYTHON312="$(brew --prefix python@3.12)/bin/python3.12"
PYTHON311="$(brew --prefix python@3.11)/bin/python3.11"

"$PYTHON312" --version && ok "python3.12 → $("$PYTHON312" --version)"
"$PYTHON311" --version && ok "python3.11 → $("$PYTHON311" --version)"

# ── 5. Node.js ────────────────────────────────────────────────────────────────
header "Node.js"

if brew list node@20 &>/dev/null || command -v node >/dev/null 2>&1; then
  ok "Node $(node --version 2>/dev/null || echo '(path reload needed)')"
else
  info "Installing Node.js 20 LTS…"
  brew install node@20
  brew link node@20 --force --overwrite
  ok "Node $(node --version)"
fi

# ── 6. Docker Desktop ─────────────────────────────────────────────────────────
header "Docker Desktop"

if command -v docker >/dev/null 2>&1; then
  ok "Docker $(docker --version | awk '{print $3}' | tr -d ',')"
else
  info "Installing Docker Desktop (this may open a GUI installer)…"
  brew install --cask docker
  warn "Open Docker Desktop from Applications and wait for the engine to start."
  warn "Then re-run this script to continue with the Docker image pulls."
fi

# Wait for Docker daemon (up to 60 s)
info "Waiting for Docker daemon…"
_docker_wait=0
until docker info >/dev/null 2>&1; do
  if (( _docker_wait >= 60 )); then
    warn "Docker daemon not ready after 60 s. Start Docker Desktop, then re-run."
    break
  fi
  sleep 3
  (( _docker_wait += 3 ))
done

if docker info >/dev/null 2>&1; then
  ok "Docker daemon is running"

  # ── 6a. Pull service images ───────────────────────────────────────────────
  header "Docker Images (Neo4j + Qdrant)"

  info "Pulling neo4j:5 (community — APOC bundled)…"
  docker pull neo4j:5
  ok "neo4j:5"

  info "Pulling qdrant/qdrant:latest…"
  docker pull qdrant/qdrant:latest
  ok "qdrant/qdrant:latest"
fi

# ── 7. LM Studio ─────────────────────────────────────────────────────────────
header "LM Studio"

if [[ -d "/Applications/LM Studio.app" ]]; then
  ok "LM Studio already installed"
else
  info "Installing LM Studio via Homebrew Cask…"
  brew install --cask lm-studio
  ok "LM Studio installed → /Applications/LM Studio.app"
fi

# Add lms CLI to PATH via shell profile (idempotent)
LMS_BIN_DIR="$HOME/.lmstudio/bin"
LMS_PATH_LINE='export PATH="$HOME/.lmstudio/bin:$PATH"'

for profile in "$HOME/.zshrc" "$HOME/.bash_profile"; do
  if [[ -f "$profile" ]] && grep -q '\.lmstudio/bin' "$profile" 2>/dev/null; then
    ok "lms CLI path already in $profile"
  elif [[ -f "$profile" ]]; then
    echo "" >> "$profile"
    echo "# lms CLI (LM Studio)" >> "$profile"
    echo "$LMS_PATH_LINE" >> "$profile"
    ok "Added lms CLI path to $profile"
  fi
done

# Activate for current session
export PATH="$LMS_BIN_DIR:$PATH"

if command -v lms >/dev/null 2>&1; then
  ok "lms CLI: $(lms --version 2>/dev/null || echo 'available')"
else
  warn "lms CLI not yet available — open LM Studio once to complete CLI setup."
  warn "Then run: export PATH=\"\$HOME/.lmstudio/bin:\$PATH\""
fi

# ── 8. Ollama (optional) ──────────────────────────────────────────────────────
header "Ollama (optional inference backend)"

if command -v ollama >/dev/null 2>&1; then
  ok "Ollama $(ollama --version 2>/dev/null | head -1)"
else
  info "Installing Ollama…"
  brew install --cask ollama
  ok "Ollama installed"
fi

# ── 9. Python environments ────────────────────────────────────────────────────
header "Python: agentic-reasoning (.venv, editable)"

REASONING_DIR="$REPO_ROOT/agentic-reasoning"
if [[ ! -d "$REASONING_DIR/.venv" ]]; then
  info "Creating .venv for agentic-reasoning…"
  "$PYTHON312" -m venv "$REASONING_DIR/.venv"
fi
info "Installing agentic-reasoning dependencies…"
"$REASONING_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$REASONING_DIR/.venv/bin/pip" install --quiet -e "$REASONING_DIR"
ok "agentic-reasoning venv ready"

# ─────────────────────────────────────────────────────────────────────────────
header "Python: data-acquisition (.venv, editable)"

ACQUISITION_DIR="$REPO_ROOT/data-acquisition"
if [[ ! -d "$ACQUISITION_DIR/.venv" ]]; then
  info "Creating .venv for data-acquisition…"
  "$PYTHON312" -m venv "$ACQUISITION_DIR/.venv"
fi
info "Installing data-acquisition dependencies…"
"$ACQUISITION_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$ACQUISITION_DIR/.venv/bin/pip" install --quiet -e "$ACQUISITION_DIR"
# Cloud extras (boto3, azure-storage-blob) — install if available; skip on auth failure
"$ACQUISITION_DIR/.venv/bin/pip" install --quiet -e "$ACQUISITION_DIR[cloud]" || \
  warn "Cloud extras install failed (boto3/azure) — run manually if cloud storage needed."
ok "data-acquisition venv ready"

# ─────────────────────────────────────────────────────────────────────────────
header "Python: data-ingestion (system python3.11, requirements.txt)"

INGESTION_DIR="$REPO_ROOT/data-ingestion"
info "Installing data-ingestion dependencies (this may take several minutes — torch, surya-ocr, etc.)…"
"$PYTHON311" -m pip install --quiet --upgrade pip
"$PYTHON311" -m pip install --quiet -r "$INGESTION_DIR/requirements.txt"
ok "data-ingestion dependencies installed"

# Spacy model (en_core_web_lg) — required by Presidio PII stage
if "$PYTHON311" -c "import spacy; spacy.load('en_core_web_lg')" >/dev/null 2>&1; then
  ok "spaCy model en_core_web_lg (already present)"
else
  info "Downloading spaCy model en_core_web_lg…"
  "$PYTHON311" -m spacy download en_core_web_lg
  ok "en_core_web_lg downloaded"
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
ok "data/ subdirectory tree created"

# ── 11. .env.local ────────────────────────────────────────────────────────────
header ".env.local"

if [[ -f "$REPO_ROOT/.env.local" ]]; then
  ok ".env.local already exists (skipping — review manually)"
else
  cp "$REPO_ROOT/.env.local.example" "$REPO_ROOT/.env.local"
  ok "Created .env.local from .env.local.example"
  warn "Edit .env.local and set LLM_MODEL to a model you've loaded in LM Studio."
fi

# ── 12. Summary & next steps ──────────────────────────────────────────────────
header "Done"

echo -e "${GREEN}${BOLD}All prerequisites installed.${NC}\n"
echo -e "  ${BOLD}Next steps:${NC}"
echo ""
echo -e "  1. ${CYAN}Open LM Studio${NC} → load a GGUF model → enable Local Server (port 1234)"
echo -e "     Recommended: Qwen2.5-7B-Instruct-GGUF or any 7-8B instruction model"
echo ""
echo -e "  2. ${CYAN}Start infrastructure:${NC}"
echo -e "       make up           # starts Neo4j (:7474/:7687) + Qdrant (:6333)"
echo ""
echo -e "  3. ${CYAN}Verify connectivity:${NC}"
echo -e "       make validate"
echo ""
echo -e "  4. ${CYAN}Fetch + ingest data:${NC}"
echo -e "       make fetch        # download sample PDFs (SOURCE=medrxiv MAX_PDFS=5)"
echo -e "       make ingest       # OCR → clean → chunk → embed → graph"
echo ""
echo -e "  5. ${CYAN}Run the agent:${NC}"
echo -e "       make reasoning-run"
echo ""
warn "Reload your shell (or open a new terminal) for PATH changes to take effect."
echo ""
