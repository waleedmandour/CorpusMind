#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# CorpusMind v0.1.0 — One-Shot macOS Apple Silicon Build
# ═══════════════════════════════════════════════════════════════════════════
#
# This script clones the CorpusMind repository from GitHub and builds the
# desktop application on macOS Apple Silicon (M1/M2/M3/M4) with no errors.
#
# It uses the --no-sidecar build path, which is the most reliable approach:
#   - Builds the web PWA (React + Vite)
#   - Builds the Tauri 2 desktop shell (Rust)
#   - Sets up the Python engine venv separately
#   - The desktop app connects to the engine at localhost:8765
#
# The PyInstaller sidecar step (which is the #1 source of macOS build
# failures) is skipped entirely. The engine runs as a separate process.
#
# Usage:
#   chmod +x build-corpusmind-mac.sh
#   ./build-corpusmind-mac.sh
#
# Prerequisites: NONE. The script installs everything it needs.
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

# Colors
RED='\033[1;31m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
NC='\033[0m'

log()  { printf "${BLUE}[build]${NC} %s\n" "$*"; }
ok()   { printf "${GREEN}  ✓${NC}  %s\n" "$*"; }
warn() { printf "${YELLOW}  ⚠${NC}  %s\n" "$*"; }
die()  { printf "${RED}  ✗${NC} %s\n" "$*" >&2; exit 1; }

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  CorpusMind v0.1.0 — macOS Apple Silicon Build"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ─── 0. Verify we're on macOS Apple Silicon ───────────────────────────────
log "checking platform..."
if [[ "$(uname)" != "Darwin" ]]; then
    die "This script only runs on macOS. You are on $(uname)."
fi
ARCH="$(uname -m)"
if [[ "$ARCH" != "arm64" ]]; then
    warn "You are on $ARCH, not arm64 (Apple Silicon). The build will target $ARCH."
    warn "If you're on an Intel Mac, this will still work but produce an x86_64 build."
fi
ok "macOS $ARCH"

# ─── 1. Install Homebrew ──────────────────────────────────────────────────
log "checking Homebrew..."
if ! command -v brew >/dev/null 2>&1; then
    warn "Homebrew not found. Installing..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add to PATH for this session
    if [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -f /usr/local/bin/brew ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
fi
eval "$(brew shellenv 2>/dev/null)" || true
ok "Homebrew"

# ─── 2. Install Xcode Command Line Tools ──────────────────────────────────
log "checking Xcode Command Line Tools..."
if ! xcode-select -p >/dev/null 2>&1; then
    warn "Xcode CLT not found. Installing..."
    xcode-select --install 2>/dev/null || true
    echo ""
    echo "  ⏸ Xcode CLT installation has started in a separate window."
    echo "  Wait for it to complete, then re-run this script."
    echo ""
    exit 1
fi
ok "Xcode Command Line Tools"

# ─── 3. Install Python, Node, Git ─────────────────────────────────────────
log "installing Python 3.12, Node 20, and Git..."
brew install python@3.12 node@20 git pkg-config 2>/dev/null || true
ok "Python $(python3.12 --version 2>/dev/null || python3 --version)"
ok "Node $(node --version)"

# ─── 4. Install Rust ──────────────────────────────────────────────────────
log "checking Rust..."
if ! command -v cargo >/dev/null 2>&1; then
    warn "Rust not found. Installing via rustup..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    source "$HOME/.cargo/env"
fi
source "$HOME/.cargo/env" 2>/dev/null || true
ok "Rust $(rustc --version)"

# Add the arm64 target (harmless if already present)
rustup target add aarch64-apple-darwin 2>/dev/null || true
ok "Rust target aarch64-apple-darwin"

# ─── 5. Install Tauri CLI ─────────────────────────────────────────────────
log "checking Tauri CLI..."
if ! command -v cargo-tauri >/dev/null 2>&1; then
    warn "Tauri CLI not found. Installing (this takes ~3 minutes)..."
    cargo install tauri-cli --version "^2.0" --locked
fi
ok "Tauri CLI $(cargo tauri --version 2>/dev/null | head -1)"

# ─── 6. Clone or update the repository ────────────────────────────────────
log "cloning CorpusMind..."
WORKDIR="$HOME/Documents/CorpusMind"
if [[ -d "$WORKDIR/.git" ]]; then
    cd "$WORKDIR"
    warn "repo already exists at $WORKDIR — pulling latest..."
    git stash 2>/dev/null || true
    git pull origin main
else
    git clone https://github.com/waleedmandour/CorpusMind.git "$WORKDIR"
    cd "$WORKDIR"
fi
ok "repo at $(pwd)"
git log --oneline -1

# ─── 7. Set up the engine venv ────────────────────────────────────────────
log "setting up Python engine venv..."
cd "$WORKDIR/engine"
if [[ ! -d ".venv" ]]; then
    python3.12 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip wheel
pip install -e ".[dev,vision]"
pip install python-multipart cryptography
ok "engine venv ready"

# Download the spaCy model
log "downloading spaCy English model..."
python -m spacy download en_core_web_sm 2>/dev/null || warn "spaCy model download failed (non-fatal)"
ok "spaCy model"

cd "$WORKDIR"

# ─── 8. Build the web PWA ─────────────────────────────────────────────────
log "building web PWA..."
cd "$WORKDIR/web"
# Bake the engine sidecar's fixed address into the bundle so the Tauri
# webview (served from tauri://localhost, with no Vite dev proxy) can reach
# http://127.0.0.1:8765. See web/src/lib/api.ts for the full story.
VITE_ENGINE_URL="http://127.0.0.1:8765" npm install
VITE_ENGINE_URL="http://127.0.0.1:8765" npm run build
cd "$WORKDIR"
[[ -f "web/dist/index.html" ]] || die "web build failed — missing dist/index.html"
ok "PWA built → web/dist/"

# ─── 9. Temporarily clear externalBin from tauri.conf.json ────────────────
# This is the key step that prevents the build failure. Without a sidecar
# binary, Tauri's bundler will fail if externalBin is set. We clear it
# temporarily and restore it after the build.
log "preparing tauri.conf.json (clearing externalBin for no-sidecar build)..."
CONF_FILE="$WORKDIR/desktop/src-tauri/tauri.conf.json"
cp "$CONF_FILE" "$CONF_FILE.bak"
python3 -c "
import json
with open('$CONF_FILE') as f:
    c = json.load(f)
c['bundle']['externalBin'] = []
with open('$CONF_FILE', 'w') as f:
    json.dump(c, f, indent=2)
"
ok "tauri.conf.json patched"

# ─── 10. Build the Tauri desktop app ──────────────────────────────────────
log "building Tauri desktop bundle (this takes 5-10 minutes on first run)..."
cd "$WORKDIR/desktop/src-tauri"

# Use a trap to restore the config file no matter what happens
trap 'cp "$CONF_FILE.bak" "$CONF_FILE" 2>/dev/null; rm -f "$CONF_FILE.bak" 2>/dev/null' EXIT

cargo tauri build --target aarch64-apple-darwin || {
    cp "$CONF_FILE.bak" "$CONF_FILE"
    die "cargo tauri build failed. See the error above."
}

# Restore the config
cp "$CONF_FILE.bak" "$CONF_FILE"
rm -f "$CONF_FILE.bak"
trap - EXIT

cd "$WORKDIR"
ok "Tauri build complete"

# ─── 11. Locate and show the artifacts ────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Build Complete!"
echo "═══════════════════════════════════════════════════════════════"
echo ""

DMG=$(find "$WORKDIR/desktop/src-tauri/target/aarch64-apple-darwin/release/bundle/dmg" -name '*.dmg' 2>/dev/null | head -1)
APP=$(find "$WORKDIR/desktop/src-tauri/target/aarch64-apple-darwin/release/bundle/macos" -name '*.app' -maxdepth 1 2>/dev/null | head -1)

if [[ -n "$DMG" ]]; then
    ok "📦 Installer: $DMG"
    ls -lh "$DMG" 2>/dev/null | awk '{print "     Size:", $5}'
fi
if [[ -n "$APP" ]]; then
    ok "📱 App bundle: $APP"
fi

echo ""
echo "───────────────────────────────────────────────────────────────"
echo "  How to run CorpusMind"
echo "───────────────────────────────────────────────────────────────"
echo ""
echo "  The desktop app needs the Python engine running in the"
echo "  background. Open TWO terminal windows:"
echo ""
echo "  Terminal 1 — start the engine:"
echo "    cd $WORKDIR/engine"
echo "    source .venv/bin/activate"
echo "    corpusmind-engine"
echo ""
echo "  Terminal 2 — open the app:"
echo "    open \"$APP\""
echo ""
echo "  First launch: right-click the app → Open → Open anyway"
echo "  (needed because the app is unsigned)."
echo ""
echo "  Alternatively, just use the PWA in your browser:"
echo "    open http://localhost:5173   (after 'npm run dev' in web/)"
echo "  or the live PWA: https://corpus-mind-web.vercel.app/"
echo ""
echo "═══════════════════════════════════════════════════════════════"
