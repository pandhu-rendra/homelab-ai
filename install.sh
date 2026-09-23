#!/usr/bin/env bash
# ==============================================================================
#  HomeLab AI — Cross-Platform Installer
#  Usage:
#    curl -fsSL https://altivon.my.id/install.sh | sh
#    ./install.sh [options]
# ==============================================================================
set -euo pipefail

INSTALL_LOG="${TMPDIR:-/tmp}/homelab-ai-install.log"
exec > >(tee -a "$INSTALL_LOG") 2>&1

# ── Defaults ─────────────────────────────────────────────────────────────────
INSTALL_DIR="${INSTALL_DIR:-$HOME/.homelab-ai}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
RELEASE_URL="${RELEASE_URL:-https://altivon.my.id/releases/homelab-ai.tar.gz.enc}"
# build-release.sh replaces __HOMELAB_RELEASE_KEY__ with a real key
RELEASE_KEY="${HOMELAB_RELEASE_KEY:-__HOMELAB_RELEASE_KEY__}"
USE_PIP="${USE_PIP:-0}"
DRY_RUN="${DRY_RUN:-0}"
CHECKSUM="${RELEASE_CHECKSUM:-}"
PROTECT_SOURCE="${HOMELAB_PROTECT_SOURCE:-0}"

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()  { printf "  ${BLUE}➜${NC} %s\n" "$*"; }
ok()    { printf "  ${GREEN}✓${NC} %s\n" "$*"; }
warn()  { printf "  ${YELLOW}⚠${NC} %s\n" "$*"; }
fail()  { printf "  ${RED}✗${NC} %s\n" "$*"; exit 1; }

# ── Help ─────────────────────────────────────────────────────────────────────
usage() {
  cat <<EOF
Usage: install.sh [options]

Options:
  -d, --dir DIR      Install to DIR (default: \$HOME/.homelab-ai)
  -u, --url URL      Download URL (default: $RELEASE_URL)
  -k, --key KEY      Decryption key (default: embedded)
  --checksum HASH    Expected SHA-256 checksum of encrypted release
  --no-uv            Use pip instead of uv
  --dry-run          Validate download/checksum without changing the system
  -h, --help         Show this help message

Examples:
  curl -fsSL https://altivon.my.id/install.sh | sh
  ./install.sh --dir /opt/homelab-ai --key mykey123
EOF
  exit 0
}

# ── Argument parsing ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--dir)     INSTALL_DIR="$2"; shift 2 ;;
    -u|--url)     RELEASE_URL="$2"; shift 2 ;;
    -k|--key)     RELEASE_KEY="$2"; shift 2 ;;
    --checksum)   CHECKSUM="$2"; shift 2 ;;
    --no-uv)      USE_PIP=1;        shift ;;
    --dry-run)    DRY_RUN=1;        shift ;;
    -h|--help)    usage ;;
    *)            fail "Unknown option: $1";;
  esac
done

# ── OS detection ─────────────────────────────────────────────────────────────
OS="linux"
case "$(uname -s)" in
  Linux*)         OS="linux"  ;;
  Darwin*)        OS="macos"  ;;
  CYGWIN*|MINGW*|MSYS*) OS="windows" ;;
esac

# ── Pre-flight checks ────────────────────────────────────────────────────────
printf "\n  ${CYAN}${BOLD}HomeLab AI${NC} ${GREEN}Installer${NC}\n"
printf -- "  ─────────────────────────────────────────\n\n"

if ! command -v python3 &>/dev/null; then
  fail "Python3 is required. Install it first."
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
  fail "Python >= 3.10 required (found $(python3 --version 2>&1))"
fi
ok "Python $(python3 --version 2>&1 | awk '{print $2}')"

if ! command -v openssl &>/dev/null; then
  fail "openssl is required for decryption. Install it first."
fi
ok "openssl"

if ! command -v curl &>/dev/null; then
  fail "curl is required for download. Install it first."
fi
ok "curl"

# ── Install uv (optional accelerator) ────────────────────────────────────────
USE_UV=1
[[ "$USE_PIP" == "1" ]] && USE_UV=0

if [[ "$USE_UV" == "1" ]] && ! command -v uv &>/dev/null; then
  info "Installing uv (fast package installer)..."
  if python3 -m pip install --user uv -q &>/dev/null; then
    ok "uv installed"
  else
    warn "uv install failed, falling back to pip"
    USE_UV=0
  fi
fi

[[ "$USE_UV" == "1" ]] && ok "uv" || ok "pip"

# ── Handle key placeholder ───────────────────────────────────────────────────
if [[ "$RELEASE_KEY" == "__HOMELAB_RELEASE_KEY__" ]]; then
  fail "This installer hasn't been configured with a decryption key. Use --key or re-download from altivon.my.id"
fi

# ── Download ──────────────────────────────────────────────────────────────────
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

info "Downloading HomeLab AI..."
curl -fsSL -o "$TMP_DIR/release.tar.gz.enc" "$RELEASE_URL"
ok "Downloaded ($(du -h "$TMP_DIR/release.tar.gz.enc" | cut -f1))"
if [[ -n "$CHECKSUM" ]]; then
  ACTUAL_CHECKSUM=$(sha256sum "$TMP_DIR/release.tar.gz.enc" | awk '{print $1}')
  [[ "$ACTUAL_CHECKSUM" == "$CHECKSUM" ]] || fail "Release checksum verification failed."
  ok "Checksum verified"
fi
if [[ "$DRY_RUN" == "1" ]]; then
  ok "Dry run complete; no files changed. Target: $INSTALL_DIR"
  exit 0
fi

# ── Decrypt ───────────────────────────────────────────────────────────────────
info "Decrypting..."
openssl enc -d -aes-256-cbc -salt -in "$TMP_DIR/release.tar.gz.enc" \
  -out "$TMP_DIR/release.tar.gz" -pass pass:"$RELEASE_KEY"
ok "Decrypted"

# ── Extract ──────────────────────────────────────────────────────────────────
mkdir -p "$INSTALL_DIR"
tar xzf "$TMP_DIR/release.tar.gz" -C "$INSTALL_DIR"
ok "Extracted to ${INSTALL_DIR}"

cd "$INSTALL_DIR"

# ── Compile .py → .pyc & remove source ───────────────────────────────────────
info "Compiling bytecode..."
python3 -c "
import compileall, os
compileall.compile_dir('.', force=True, quiet=1)
" 2>/dev/null

# Only remove .py if compilation succeeded
if python3 -c "import homelab_ai" 2>/dev/null || PYTHONPATH="$PWD" python3 -c "import homelab_ai" 2>/dev/null; then
  if [[ "$PROTECT_SOURCE" == "1" ]]; then
    find . -name '*.py' -not -path './.env*' -delete
    ok "Source protected (compiled to .pyc)"
  else
    ok "Bytecode compiled; source retained"
  fi
else
  warn "Package import check failed — keeping .py files"
fi

# ── Virtual environment ──────────────────────────────────────────────────────
VENV_DIR="$INSTALL_DIR/.venv"
if [[ "$USE_UV" == "1" ]]; then
  info "Creating virtual environment (uv)..."
  uv venv "$VENV_DIR" --python python3 &>/dev/null
  ok "Virtual environment created"
  info "Installing dependencies (uv)..."
  uv pip install --python "$VENV_DIR" -r "$INSTALL_DIR/requirements.txt" &>/dev/null
  ok "Dependencies installed"
else
  info "Creating virtual environment (pip)..."
  python3 -m venv "$VENV_DIR" &>/dev/null
  ok "Virtual environment created"
  info "Installing dependencies (pip)..."
  "$VENV_DIR/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt" 2>/dev/null
  ok "Dependencies installed"
fi

# ── .env setup ───────────────────────────────────────────────────────────────
if [[ ! -f "$INSTALL_DIR/.env" && -f "$INSTALL_DIR/.env.example" ]]; then
  cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
  warn "Created .env from .env.example — add your API keys"
fi

# ── Launcher ──────────────────────────────────────────────────────────────────
if [[ "$OS" == "windows" ]]; then
  mkdir -p "$BIN_DIR"
  if command -v cygpath &>/dev/null; then
    INSTALL_DIR_WIN="$(cygpath -w "$INSTALL_DIR")"
    VENV_PYTHON_WIN="$(cygpath -w "$INSTALL_DIR/.venv/Scripts/python.exe")"
  else
    INSTALL_DIR_WIN="$INSTALL_DIR"
    VENV_PYTHON_WIN="$INSTALL_DIR/.venv/Scripts/python.exe"
  fi
  cat <<EOF > "$BIN_DIR/homelab.cmd"
@echo off
setlocal
pushd "$INSTALL_DIR_WIN"
"$VENV_PYTHON_WIN" -m homelab_ai %*
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%
EOF
  LAUNCHER="$BIN_DIR/homelab.cmd"
else
  mkdir -p "$BIN_DIR"
  LAUNCHER="$BIN_DIR/homelab"
  cat <<EOF > "$LAUNCHER"
#!/usr/bin/env bash
PYTHONPATH="$INSTALL_DIR" exec "$INSTALL_DIR/.venv/bin/python" -m homelab_ai "\$@"
EOF
  chmod +x "$LAUNCHER"
fi
ok "Launcher created: ${LAUNCHER}"

# ── PATH injection ───────────────────────────────────────────────────────────
if [[ "$OS" != "windows" ]]; then
  SHELL_RC=""
  case "${SHELL:-}" in
    */bash) SHELL_RC="$HOME/.bashrc" ;;
    */zsh)  SHELL_RC="$HOME/.zshrc" ;;
    */fish) SHELL_RC="$HOME/.config/fish/config.fish" ;;
  esac
  if [[ -n "$SHELL_RC" ]] && ! grep -sq "$BIN_DIR" "$SHELL_RC" 2>/dev/null; then
    case "${SHELL:-}" in
      */fish) echo "fish_add_path $BIN_DIR" >> "$SHELL_RC" ;;
      *)      echo "export PATH=\"\$PATH:$BIN_DIR\"" >> "$SHELL_RC" ;;
    esac
    ok "Added ${BIN_DIR} to PATH (${SHELL_RC})"
  fi
else
  warn "Add ${BIN_DIR} to your PATH manually, or restart your terminal"
fi

# ── Cleanup temp ─────────────────────────────────────────────────────────────
rm -rf "$TMP_DIR"

# ── Success ──────────────────────────────────────────────────────────────────
printf "\n  ─────────────────────────────────────────\n"
printf "  ${GREEN}${BOLD}HomeLab AI installed successfully!${NC}\n"
printf -- "  ─────────────────────────────────────────\n"
printf "\n  ${BOLD}Run:${NC} ${CYAN}homelab${NC}\n"
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
  printf "\n  ${BOLD}First step:${NC} Edit ${YELLOW}${INSTALL_DIR}/.env${NC}\n"
fi
printf "\n"
