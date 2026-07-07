#!/usr/bin/env bash
# scripts/build-macos-arm64.sh
#
# Build CorpusMind for macOS Apple Silicon (arm64).
#
# This script is designed to be robust. It handles three scenarios:
#   1. Full build with PyInstaller sidecar (default — produces a
#      self-contained .dmg with the engine bundled inside).
#   2. Desktop-only build without sidecar (--no-sidecar — the desktop
#      app will fall back to running `python -m app.main` from the
#      engine/ directory at runtime, which requires Python 3.12 on
#      the target machine but avoids the PyInstaller step entirely).
#   3. Engine-only build (--engine — just builds the sidecar binary).
#
# Usage:
#   ./scripts/build-macos-arm64.sh              # full build (sidecar + web + desktop)
#   ./scripts/build-macos-arm64.sh --no-sidecar # skip PyInstaller, build web + desktop only
#   ./scripts/build-macos-arm64.sh --engine     # sidecar binary only
#   ./scripts/build-macos-arm64.sh --web        # PWA only
#   ./scripts/build-macos-arm64.sh --desktop    # desktop bundle only (requires sidecar or --no-sidecar)
set -euo pipefail

# ─── config ────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENGINE_DIR="$REPO_ROOT/engine"
WEB_DIR="$REPO_ROOT/web"
DESKTOP_DIR="$REPO_ROOT/desktop/src-tauri"

TARGET_TRIPLE="aarch64-apple-darwin"
SIDECAR_NAME="corpusmind-engine-${TARGET_TRIPLE}"
SIDECAR_OUT="$DESKTOP_DIR/binaries/$SIDECAR_NAME"

# What to build
BUILD_ENGINE=1
BUILD_WEB=1
BUILD_DESKTOP=1
BUILD_SIDECAR=1
for arg in "$@"; do
    case "$arg" in
        --engine)     BUILD_DESKTOP=0; BUILD_WEB=0; BUILD_SIDECAR=1 ;;
        --web)        BUILD_ENGINE=0; BUILD_DESKTOP=0 ;;
        --desktop)    BUILD_ENGINE=0 ;;
        --no-sidecar) BUILD_SIDECAR=0 ;;
    esac
done

# ─── helpers ───────────────────────────────────────────────────────────────
log()  { printf '\033[1;34m[build]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ✓\033[0m  %s\n' "$*"; }
warn() { printf '\033[1;33m  ⚠\033[0m  %s\n' "$*"; }
die()  { printf '\033[1;31m  ✗\033[0m %s\n' "$*" >&2; exit 1; }

cd "$REPO_ROOT"
log "repo: $REPO_ROOT"
log "host: $(uname -sm)"

# ─── 0. prerequisites check ───────────────────────────────────────────────
log "checking prerequisites..."

# Xcode Command Line Tools
if ! xcode-select -p >/dev/null 2>&1; then
    warn "Xcode Command Line Tools not found. Installing..."
    xcode-select --install || die "please run 'xcode-select --install' manually, then re-run this script"
    die "Xcode tools installation started. Re-run this script after it completes."
fi
ok "Xcode Command Line Tools"

# Rust
if ! command -v cargo >/dev/null 2>&1; then
    warn "Rust not found. Installing via rustup..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    source "$HOME/.cargo/env"
fi
source "$HOME/.cargo/env" 2>/dev/null || true
ok "Rust $(rustc --version)"

# Tauri CLI
if ! command -v cargo-tauri >/dev/null 2>&1; then
    warn "Tauri CLI not found. Installing..."
    cargo install tauri-cli --version "^2.0" --locked
fi
ok "Tauri CLI"

# Add the arm64 target
rustup target add aarch64-apple-darwin 2>/dev/null || true
ok "Rust target aarch64-apple-darwin"

# Node
if ! command -v node >/dev/null 2>&1; then
    die "Node.js not found. Install with: brew install node@20"
fi
ok "Node $(node --version)"

# Python (only needed for sidecar or if --no-sidecar)
if [[ $BUILD_SIDECAR -eq 1 ]] || [[ $BUILD_ENGINE -eq 1 ]]; then
    PYTHON="$(command -v python3.12 || command -v python3)"
    if [[ -z "$PYTHON" ]]; then
        die "Python 3.12 not found. Install with: brew install python@3.12"
    fi
    ok "Python $($PYTHON --version)"
fi

# ─── 1. engine sidecar (PyInstaller) ──────────────────────────────────────
if [[ $BUILD_SIDECAR -eq 1 ]] && [[ $BUILD_ENGINE -eq 1 ]]; then
    log "building engine sidecar → $SIDECAR_NAME"

    VENV="$ENGINE_DIR/.venv-build"
    if [[ ! -d "$VENV" ]]; then
        "$PYTHON" -m venv "$VENV"
        ok "created venv"
    fi
    # shellcheck disable=SC1091
    source "$VENV/bin/activate"

    pip install --upgrade pip wheel
    pip install -e "$ENGINE_DIR[dev,vision]"
    pip install pyinstaller python-multipart cryptography
    ok "engine deps installed"

    cd "$ENGINE_DIR"
    rm -rf build dist
    pyinstaller corpusmind-engine.spec --noconfirm
    cd "$REPO_ROOT"

    [[ -f "$ENGINE_DIR/dist/corpusmind-engine" ]] \
        || die "pyinstaller did not produce dist/corpusmind-engine"

    mkdir -p "$DESKTOP_DIR/binaries"
    cp "$ENGINE_DIR/dist/corpusmind-engine" "$SIDECAR_OUT"
    chmod +x "$SIDECAR_OUT"
    ok "sidecar → $SIDECAR_OUT ($(du -h "$SIDECAR_OUT" | cut -f1))"
elif [[ $BUILD_SIDECAR -eq 0 ]]; then
    warn "skipping sidecar build (--no-sidecar). The desktop app will fall back"
    warn "to running 'python -m app.main' from the engine/ directory at runtime."
    warn "This requires Python 3.12 + the engine deps on the target machine."
    # Remove the sidecar binary if it exists so Tauri doesn't try to bundle a stale one
    rm -f "$SIDECAR_OUT"
fi

# ─── 2. web PWA ───────────────────────────────────────────────────────────
if [[ $BUILD_WEB -eq 1 ]]; then
    log "building web PWA"
    cd "$WEB_DIR"
    npm install
    npm run build
    cd "$REPO_ROOT"
    [[ -f "$WEB_DIR/dist/index.html" ]] || die "web build missing dist/index.html"
    ok "PWA artifacts in web/dist/"
fi

# ─── 3. desktop bundle ────────────────────────────────────────────────────
if [[ $BUILD_DESKTOP -eq 1 ]]; then
    log "building desktop bundle (Tauri 2, arm64)"

    # If sidecar was built, verify it exists
    if [[ $BUILD_SIDECAR -eq 1 ]]; then
        [[ -x "$SIDECAR_OUT" ]] \
            || die "sidecar missing at $SIDECAR_OUT — run with --engine first"
    fi

    # If --no-sidecar, temporarily remove externalBin from tauri.conf.json
    # so cargo tauri build doesn't fail looking for a non-existent binary.
    CONF_FILE="$DESKTOP_DIR/tauri.conf.json"
    if [[ $BUILD_SIDECAR -eq 0 ]]; then
        log "temporarily removing externalBin from tauri.conf.json (--no-sidecar)"
        # Back up the original config
        cp "$CONF_FILE" "$CONF_FILE.bak"
        # Remove the externalBin line (python or sed)
        python3 -c "
import json
with open('$CONF_FILE') as f:
    c = json.load(f)
c['bundle']['externalBin'] = []
with open('$CONF_FILE', 'w') as f:
    json.dump(c, f, indent=2)
"
    fi

    cd "$DESKTOP_DIR"

    # Build for arm64. On Apple Silicon this is the host triple.
    cargo tauri build --target aarch64-apple-darwin || {
        # Restore config on failure
        if [[ $BUILD_SIDECAR -eq 0 ]] && [[ -f "$CONF_FILE.bak" ]]; then
            mv "$CONF_FILE.bak" "$CONF_FILE"
        fi
        die "cargo tauri build failed. See error above."
    }

    # Restore config on success
    if [[ $BUILD_SIDECAR -eq 0 ]] && [[ -f "$CONF_FILE.bak" ]]; then
        mv "$CONF_FILE.bak" "$CONF_FILE"
    fi

    cd "$REPO_ROOT"
    log "done. artifacts:"
    DMG=$(find "$DESKTOP_DIR/target/aarch64-apple-darwin/release/bundle/dmg" -name '*.dmg' 2>/dev/null | head -1)
    APP=$(find "$DESKTOP_DIR/target/aarch64-apple-darwin/release/bundle/macos" -name '*.app' -maxdepth 1 2>/dev/null | head -1)
    if [[ -n "$DMG" ]]; then
        ok "📦 $DMG"
    fi
    if [[ -n "$APP" ]]; then
        ok "📱 $APP"
    fi
    ok "build complete"
fi

# ─── 4. post-build instructions ───────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Build complete!"
echo "═══════════════════════════════════════════════════════════════"
if [[ $BUILD_DESKTOP -eq 1 ]]; then
    APP=$(find "$DESKTOP_DIR/target/aarch64-apple-darwin/release/bundle/macos" -name '*.app' -maxdepth 1 2>/dev/null | head -1)
    if [[ -n "$APP" ]]; then
        echo "  To open: open \"$APP\""
        echo "  First launch: right-click → Open → Open anyway (unsigned)"
    fi
fi
if [[ $BUILD_SIDECAR -eq 0 ]]; then
    echo ""
    echo "  ⚠ No sidecar bundled. To run the engine for the desktop app:"
    echo "    cd engine && python3.12 -m venv .venv && source .venv/bin/activate"
    echo "    pip install -e '.[dev,vision]' && corpusmind-engine"
fi
echo "═══════════════════════════════════════════════════════════════"
