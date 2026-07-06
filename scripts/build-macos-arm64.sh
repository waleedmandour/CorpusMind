#!/usr/bin/env bash
# scripts/build-macos-arm64.sh
#
# Build CorpusMind for macOS Apple Silicon (arm64) on a developer machine.
#
# Produces:
#   web/dist/                            — PWA artifacts
#   desktop/src-tauri/binaries/
#       corpusmind-engine-aarch64-apple-darwin   — bundled engine sidecar
#   desktop/src-tauri/target/release/bundle/
#       dmg/CorpusMind_0.1.0_aarch64.dmg         — installer
#       macos/CorpusMind.app                     — the .app bundle
#
# Prerequisites (install once via `brew install python@3.12 node@20 rustup-init`):
#   - macOS 13+ on Apple Silicon
#   - Xcode Command Line Tools:  xcode-select --install
#   - Python 3.12, Node 20, Rust (stable)
#   - PyInstaller:  pip install pyinstaller
#
# Usage:
#   ./scripts/build-macos-arm64.sh           # full build
#   ./scripts/build-macos-arm64.sh --engine  # engine sidecar only
#   ./scripts/build-macos-arm64.sh --desktop # desktop bundle only
set -euo pipefail

# ─── config ────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENGINE_DIR="$REPO_ROOT/engine"
WEB_DIR="$REPO_ROOT/web"
DESKTOP_DIR="$REPO_ROOT/desktop/src-tauri"

# Target triple for Apple Silicon — Tauri's sidecar lookup uses this suffix.
TARGET_TRIPLE="aarch64-apple-darwin"
SIDECAR_NAME="corpusmind-engine-${TARGET_TRIPLE}"
SIDECAR_OUT="$DESKTOP_DIR/binaries/$SIDECAR_NAME"

# What to build — default: everything
BUILD_ENGINE=1
BUILD_WEB=1
BUILD_DESKTOP=1
if [[ "${1:-}" == "--engine" ]]; then BUILD_DESKTOP=0; BUILD_WEB=0; fi
if [[ "${1:-}" == "--desktop" ]]; then BUILD_ENGINE=0; fi
if [[ "${1:-}" == "--web" ]]; then BUILD_ENGINE=0; BUILD_DESKTOP=0; fi

# ─── helpers ───────────────────────────────────────────────────────────────
log()  { printf '\033[1;34m[build]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ok\033[0m  %s\n' "$*"; }
die()  { printf '\033[1;31m fail\033[0m %s\n' "$*" >&2; exit 1; }

command -v python3.12 >/dev/null || command -v python3 >/dev/null || die "python3 not found"
command -v node   >/dev/null || die "node not found"
command -v cargo  >/dev/null || die "cargo not found (install via rustup)"
command -v pyinstaller >/dev/null || die "pyinstaller not found (pip install pyinstaller)"

# Pick the right python
PYTHON="$(command -v python3.12 || command -v python3)"

cd "$REPO_ROOT"
log "repo: $REPO_ROOT"
log "host: $(uname -sm)"

# ─── 1. engine sidecar ─────────────────────────────────────────────────────
if [[ $BUILD_ENGINE -eq 1 ]]; then
  log "building engine sidecar → $SIDECAR_NAME"

  # Use a dedicated venv so we don't pollute the system python or pick up
  # unrelated dev packages that bloat the bundle.
  VENV="$ENGINE_DIR/.venv-build"
  if [[ ! -d "$VENV" ]]; then
    "$PYTHON" -m venv "$VENV"
    ok "created venv"
  fi
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"

  pip install --upgrade pip wheel >/dev/null
  pip install -e "$ENGINE_DIR[dev,vision]" >/dev/null
  pip install pyinstaller python-multipart cryptography >/dev/null
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
  ok "sidecar → $SIDECAR_OUT"
  ok "size: $(du -h "$SIDECAR_OUT" | cut -f1)"
fi

# ─── 2. web PWA ────────────────────────────────────────────────────────────
if [[ $BUILD_WEB -eq 1 ]]; then
  log "building web PWA"
  cd "$WEB_DIR"
  npm install --silent
  npm run build
  cd "$REPO_ROOT"
  [[ -f "$WEB_DIR/dist/index.html" ]] || die "web build missing dist/index.html"
  [[ -f "$WEB_DIR/dist/sw.js"       ]] || die "web build missing dist/sw.js"
  ok "PWA artifacts in web/dist/"
fi

# ─── 3. desktop bundle ────────────────────────────────────────────────────
if [[ $BUILD_DESKTOP -eq 1 ]]; then
  log "building desktop bundle (Tauri 2, arm64)"

  # Verify the sidecar is present (either we just built it, or it was
  # pre-built and --desktop was passed).
  [[ -x "$SIDECAR_OUT" ]] \
    || die "sidecar missing at $SIDECAR_OUT — run with --engine first"

  cd "$DESKTOP_DIR"

  # Build for arm64 explicitly. On an Apple Silicon Mac this is the host
  # triple, but we pass --target to be unambiguous and to make universal
  # builds possible later (add x86_64-apple-darwin + lipo).
  rustup target add aarch64-apple-darwin 2>/dev/null || true

  # cargo tauri build picks up tauri.conf.json (frontendDist, bundle config).
  # We skip the beforeBuildCommand because we already built the web PWA above
  # and Tauri's bundled npm invocation can race with our manual build.
  cargo tauri build --target aarch64-apple-darwin

  cd "$REPO_ROOT"
  log "done. artifacts:"
  ls -lh "$DESKTOP_DIR/target/aarch64-apple-darwin/release/bundle/dmg/"*.dmg 2>/dev/null || true
  ls -ld  "$DESKTOP_DIR/target/aarch64-apple-darwin/release/bundle/macos/CorpusMind.app" 2>/dev/null || true
  ok "build complete"
fi

# ─── 4. codesign + notarize (optional, manual) ────────────────────────────
#
# The .dmg / .app produced above is unsigned. To distribute outside your own
# machine you must codesign and notarize. Run these manually (they need an
# Apple Developer ID and an App Store Connect API key):
#
#   APP="desktop/src-tauri/target/aarch64-apple-darwin/release/bundle/macos/CorpusMind.app"
#   codesign --deep --force --options runtime \
#     --sign "Developer ID Application: Your Name (TEAMID)" "$APP"
#
#   dmg="desktop/src-tauri/target/aarch64-apple-darwin/release/bundle/dmg/CorpusMind_0.1.0_aarch64.dmg"
#   xcrun notarytool submit "$dmg" \
#     --apple-id you@example.com --team-id TEAMID --password app-specific-pwd --wait
#   xcrun stapler staple "$dmg"
#
# Until you have a Developer ID, the app will run on your own Mac after
# right-click → Open → "Open anyway" in System Settings → Privacy & Security.
