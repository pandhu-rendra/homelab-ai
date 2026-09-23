#!/usr/bin/env bash
# ==============================================================================
#  HomeLab AI — Release Builder
#  Builds an encrypted release tarball for VPS distribution.
#  Usage: ./scripts/build-release.sh [version]
# ==============================================================================
set -euo pipefail

VERSION="${1:-}"
INSTALL_SCRIPT="$(dirname "$0")/../install.sh"
INSTALL_PS_SCRIPT="$(dirname "$0")/../install.ps1"
RELEASES_DIR="$(dirname "$0")/../releases"
DIST_DIR="$(dirname "$0")/../dist"

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info() { printf "  ${CYAN}➜${NC} %s\n" "$*"; }
ok()   { printf "  ${GREEN}✓${NC} %s\n" "$*"; }
fail() { printf "  ${RED}✗${NC} %s\n" "$*"; exit 1; }

# ── Pre-flight ───────────────────────────────────────────────────────────────
if [[ ! -f "$INSTALL_SCRIPT" ]]; then
  fail "install.sh not found at $INSTALL_SCRIPT. Run this script from the project root."
fi
if [[ ! -f "$INSTALL_PS_SCRIPT" ]]; then
  fail "install.ps1 not found at $INSTALL_PS_SCRIPT. Run this script from the project root."
fi

for cmd in python3 openssl tar git; do
  command -v "$cmd" &>/dev/null || fail "'$cmd' is required but not found."
done
ok "All prerequisites met"

# ── Version ───────────────────────────────────────────────────────────────────
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

if [[ -z "$VERSION" ]]; then
  VERSION=$(python3 -c "
try:
    import tomllib
    with open('pyproject.toml','rb') as f:
        print(tomllib.load(f)['project']['version'])
except Exception:
    print('2.1.0')
" 2>/dev/null || echo "2.1.0")
fi
RELEASE_NAME="homelab-ai-v${VERSION}"
ok "Building release ${RELEASE_NAME}"

# ── Temp workspace ───────────────────────────────────────────────────────────
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT
BUILD_DIR="$TEMP_DIR/build"

# ── Copy project, clean cruft ────────────────────────────────────────────────
info "Copying project files..."
cp -a "$PROJECT_DIR/." "$BUILD_DIR/"
cd "$BUILD_DIR"

# Remove development-only files
rm -rf .git .github __pycache__ .venv .mypy_cache .pytest_cache
rm -rf tests/ scripts/ releases/ dist/
rm -f *.log *.db *.bak *.json.bak *~
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -name '*.pyc' -delete
ok "Cleaned"

# ── Create tarball ───────────────────────────────────────────────────────────
cd "$TEMP_DIR"
info "Creating tarball..."
tar czf "${RELEASE_NAME}.tar.gz" \
  --exclude='.env' \
  --exclude='.env.*' \
  --exclude='.venv' \
  --exclude='__pycache__' \
  -C "$BUILD_DIR" .
ok "Tarball created (${RELEASE_NAME}.tar.gz)"

# ── Generate key & encrypt ───────────────────────────────────────────────────
RELEASE_KEY=$(openssl rand -hex 16)
mkdir -p "$PROJECT_DIR/$RELEASES_DIR"

openssl enc -aes-256-cbc -salt \
  -in "${RELEASE_NAME}.tar.gz" \
  -out "$PROJECT_DIR/$RELEASES_DIR/${RELEASE_NAME}.tar.gz.enc" \
  -pass pass:"$RELEASE_KEY"
ok "Encrypted → releases/${RELEASE_NAME}.tar.gz.enc"
if command -v sha256sum &>/dev/null; then
  sha256sum "$PROJECT_DIR/$RELEASES_DIR/${RELEASE_NAME}.tar.gz.enc" > "$PROJECT_DIR/$RELEASES_DIR/${RELEASE_NAME}.tar.gz.enc.sha256"
else
  shasum -a 256 "$PROJECT_DIR/$RELEASES_DIR/${RELEASE_NAME}.tar.gz.enc" > "$PROJECT_DIR/$RELEASES_DIR/${RELEASE_NAME}.tar.gz.enc.sha256"
fi
ok "Checksum → releases/${RELEASE_NAME}.tar.gz.enc.sha256"

# ── Build installer with embedded key ────────────────────────────────────────
mkdir -p "$PROJECT_DIR/$DIST_DIR"
sed "s/__HOMELAB_RELEASE_KEY__/$RELEASE_KEY/g" "$INSTALL_SCRIPT" \
  > "$PROJECT_DIR/$DIST_DIR/install.sh"
chmod +x "$PROJECT_DIR/$DIST_DIR/install.sh"
ok "Installer → dist/install.sh"
sed "s/__HOMELAB_RELEASE_KEY__/$RELEASE_KEY/g" "$INSTALL_PS_SCRIPT" \
  > "$PROJECT_DIR/$DIST_DIR/install.ps1"
ok "Installer → dist/install.ps1"

# ── Summary ──────────────────────────────────────────────────────────────────
printf "\n  ${GREEN}${BOLD}Release ${RELEASE_NAME} built!${NC}\n"
printf -- "  ─────────────────────────────────────────\n"
printf "\n"
printf "  ${BOLD}Files:${NC}\n"
printf "    ${CYAN}releases/${RELEASE_NAME}.tar.gz.enc${NC}\n"
printf "    ${CYAN}releases/${RELEASE_NAME}.tar.gz.enc.sha256${NC}\n"
printf "    ${CYAN}dist/install.sh${NC}\n"
printf "    ${CYAN}dist/install.ps1${NC}\n"
printf "\n"
printf "  ${BOLD}Decryption key:${NC} ${YELLOW}%s${NC}\n" "$RELEASE_KEY"
printf "\n"
printf "  ${BOLD}Upload to VPS:${NC}\n"
printf "    scp releases/${RELEASE_NAME}.tar.gz.enc user@altivon.my.id:/var/www/html/releases/homelab-ai.tar.gz.enc\n"
printf "    scp releases/${RELEASE_NAME}.tar.gz.enc.sha256 user@altivon.my.id:/var/www/html/releases/homelab-ai.tar.gz.enc.sha256\n"
printf "    scp dist/install.sh              user@altivon.my.id:/var/www/html/install.sh\n"
printf "    scp dist/install.ps1             user@altivon.my.id:/var/www/html/install.ps1\n"
printf "\n"
printf "  ${YELLOW}⚠${NC} The key is embedded in dist/install.sh — upload both together.\n"
printf "\n"
