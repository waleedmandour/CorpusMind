#!/usr/bin/env bash
# Post-build smoke gate for the packaged engine sidecar (v1.2.8, review #6).
#
# Launches the PyInstaller-built engine binary on a scratch port and asserts
# that the features that regressed in the shipped v1.2.8 actually work
# inside the bundle:
#   - the USAS semantic lexicon resolves (reference-data path fix)
#   - the Academic Word List is found (same fix, silent degradation)
#   - the persuasion-index package imports (dependency manifest + spec fix)
#
# The release workflow runs this on every platform BEFORE the Tauri
# packaging step; a failure fails the release. Usage:
#   scripts/ci_smoke_engine.sh <path-to-engine-binary>
set -euo pipefail

BIN="${1:?usage: ci_smoke_engine.sh <engine-binary>}"
PORT="${CORPUSMIND_SMOKE_PORT:-8799}"
BASE="http://127.0.0.1:${PORT}"

echo "[smoke] launching ${BIN} on port ${PORT}"
CORPUSMIND_PORT="${PORT}" "${BIN}" &
ENGINE_PID=$!
cleanup() {
  kill "${ENGINE_PID}" 2>/dev/null || true
  wait "${ENGINE_PID}" 2>/dev/null || true
}
trap cleanup EXIT

echo -n "[smoke] waiting for /api/v1/health"
READY=0
for _ in $(seq 1 60); do
  if ! kill -0 "${ENGINE_PID}" 2>/dev/null; then
    echo
    echo "[smoke] FAIL: engine exited early (see its output above)"
    exit 1
  fi
  if curl -fsS "${BASE}/api/v1/health" >/dev/null 2>&1; then
    READY=1
    break
  fi
  echo -n "."
  sleep 1
done
echo
if [ "${READY}" -ne 1 ]; then
  echo "[smoke] FAIL: engine did not become healthy within 60s"
  exit 1
fi
echo "[smoke] engine is up"

RES_JSON="$(curl -fsS "${BASE}/api/v1/health/resources")"
echo "[smoke] /api/v1/health/resources -> ${RES_JSON}"

fail() {
  echo "[smoke] FAIL: $1"
  exit 1
}

# 1. USAS lexicon (review #1: 503 "not installed" in the shipped bundle)
echo "${RES_JSON}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('usas', {}).get('en') is True, f\"USAS en lexicon missing: {d.get('usas')}\"
" || fail "USAS en lexicon did not resolve inside the bundle"

# 2. AWL wordlist (same path-resolution bug class, silent degradation)
echo "${RES_JSON}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('wordlists', {}).get('awl') is True, f\"AWL wordlist missing: {d.get('wordlists')}\"
" || fail "AWL wordlist did not resolve inside the bundle"

# 3. persuasion-index (review #3: package absent from the shipped bundle)
echo "${RES_JSON}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
pi = d.get('persuasion_index') or {}
assert pi.get('installed') is True, f\"persuasion-index not installed in bundle: {pi}\"
assert pi.get('version'), f\"persuasion-index version unknown: {pi}\"
print(f\"[smoke] persuasion-index {pi.get('version')} present\")
" || fail "persuasion-index did not import inside the bundle"

# 4. The persuasion health endpoint answers with installed=true
PI_JSON="$(curl -fsS "${BASE}/api/v1/discourse/persuasion/health")"
echo "[smoke] /api/v1/discourse/persuasion/health -> ${PI_JSON}"
echo "${PI_JSON}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('installed') is True, f\"persuasion health installed!=true: {d}\"
" || fail "persuasion health endpoint reports the lens as not installed"

echo "[smoke] PASS: USAS lexicon, AWL wordlist and persuasion-index all present in the bundle"
