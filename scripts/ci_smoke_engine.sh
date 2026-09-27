#!/usr/bin/env bash
# Post-build smoke gate for the packaged engine sidecar (v1.2.8, review #6;
# v1.2.9 adds the Student Mode classroom stack: web-dist + Caddy).
#
# Launches the PyInstaller-built engine binary on a scratch port and asserts
# that the features that regressed in the shipped v1.2.8 actually work
# inside the bundle:
#   - the USAS semantic lexicon resolves (reference-data path fix)
#   - the Academic Word List is found (same fix, silent degradation)
#   - the persuasion-index package imports (dependency manifest + spec fix)
#   - the bundled web-dist + Caddy binary exist (Student Mode prerequisites)
#
# The release workflow runs this on every platform BEFORE the Tauri
# packaging step; a failure fails the release. Usage:
#   scripts/ci_smoke_engine.sh <path-to-engine-binary>
set -euo pipefail

BIN="${1:?usage: ci_smoke_engine.sh <engine-binary>}"
PORT="${CORPUSMIND_SMOKE_PORT:-8799}"
BASE="http://127.0.0.1:${PORT}"

# Content gate (hard): the data files the regressed features need must be
# in THIS bundle before anything else is checked. Mirrors the Windows
# gate's content checks so all three platforms enforce them.
INTERNAL_DIR="$(dirname "${BIN}")/_internal"
for rel in \
  "reference-data/tagsets/usas-en-top.tsv" \
  "reference-data/tagsets/usas-ar-top.tsv" \
  "reference-data/wordlists/awl-sublists.tsv" \
  "reference-data/wordlists/en/top200.tsv" \
  "reference-data/reference-corpora/en/be06-freq-top1000.tsv"; do
  if [ -f "${INTERNAL_DIR}/${rel}" ]; then
    echo "[smoke] OK   ${rel}"
  else
    echo "[smoke] FAIL: missing data file in bundle: ${rel}"
    exit 1
  fi
done
if [ -d "${INTERNAL_DIR}/wordfreq/data" ]; then
  echo "[smoke] OK   wordfreq data ($(find "${INTERNAL_DIR}/wordfreq/data" -type f | wc -l) files)"
else
  echo "[smoke] FAIL: missing wordfreq data directory in bundle"
  exit 1
fi

# v1.2.9 Student Mode classroom stack (hard content gate):
# the PWA build Caddy serves + the Caddy binary itself.
if [ -f "${INTERNAL_DIR}/web-dist/index.html" ]; then
  echo "[smoke] OK   web-dist/index.html (student PWA bundle)"
else
  echo "[smoke] FAIL: missing web-dist/index.html in bundle (Student Mode cannot serve students)"
  exit 1
fi
CADDY_EXE="caddy"; case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) CADDY_EXE="caddy.exe" ;; esac
if [ -f "${INTERNAL_DIR}/caddy/${CADDY_EXE}" ]; then
  CADDY_VERSION_OUT="$("${INTERNAL_DIR}/caddy/${CADDY_EXE}" version 2>/dev/null | head -1 || echo '?')"
  echo "[smoke] OK   caddy sidecar present (${CADDY_VERSION_OUT})"
else
  echo "[smoke] FAIL: missing caddy/caddy binary in bundle (Student Mode cannot start)"
  exit 1
fi

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

# ---------------------------------------------------------------------------
# v1.2.10: /health/resources is the SINGLE asserted registry. Every key the
# build contractually ships must be true here — asserting the whole payload
# (instead of the three keys that regressed in v1.2.8) is what generalizes
# the gate: a future resource added to the registry without being added to
# the bundle fails HERE, on every platform, before release.
# Report-only keys (spacy_model, sentiment) are printed for the record;
# user-supplied resources can never be asserted.
# ---------------------------------------------------------------------------
echo "${RES_JSON}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
problems = []

def need(path, ok, what):
    if not ok:
        problems.append(f'{what} ({path})')

need('usas.en', d.get('usas', {}).get('en') is True, 'USAS en lexicon missing')
need('usas.ar', d.get('usas', {}).get('ar') is True, 'USAS ar lexicon missing')
need('wordlists.awl', d.get('wordlists', {}).get('awl') is True, 'AWL wordlist missing')
need('wordlists.k1_top200', d.get('wordlists', {}).get('k1_top200') is True, 'K1 top200 wordlist missing')

rc = d.get('reference_corpora', {})
for k in ('be06_top1000', 'leipzig_news_top100', 'ellipse_learner_top1000',
          'pd_persuasive_top1000', 'camel_arabic_top1000',
          'quranic_arabic_freq', 'dialectal_tweets_top1000'):
    need(f'reference_corpora.{k}', rc.get(k) is True, f'reference corpus missing: {k}')

fw = d.get('frameworks', {}).get('count', 0)
if fw < 12:
    problems.append(f'framework catalogue incomplete: {fw} YAMLs (floor 12)')

need('spacy_model.en_core_web_sm', d.get('spacy_model', {}).get('en_core_web_sm') is True,
     'spaCy en_core_web_sm not collected in bundle')

need('wordfreq.installed', d.get('wordfreq', {}).get('installed') is True, 'wordfreq missing')

pi = d.get('persuasion_index') or {}
need('persuasion_index.installed', pi.get('installed') is True, 'persuasion-index not importable in bundle')
if not pi.get('version'):
    problems.append('persuasion-index version unknown')

if d.get('reference_data_dir') is None:
    problems.append('reference_data_dir did not resolve in bundle')

print(f\"[smoke] report-only: sentiment={d.get('sentiment')}\", flush=True)
if problems:
    print('[smoke] registry problems:', flush=True)
    for p in problems:
        print(f'[smoke]   - {p}', flush=True)
    sys.exit(1)
" || fail "bundled-resource registry incomplete (see problems above)"

# 4. The persuasion health endpoint answers with installed=true
PI_JSON="$(curl -fsS "${BASE}/api/v1/discourse/persuasion/health")"
echo "[smoke] /api/v1/discourse/persuasion/health -> ${PI_JSON}"
echo "${PI_JSON}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('installed') is True, f\"persuasion health installed!=true: {d}\"
" || fail "persuasion health endpoint reports the lens as not installed"

# ---------------------------------------------------------------------------
# v1.2.10: the stateless status endpoints must all answer. This is the
# allowlisted subset of "every registered status endpoint" — per-object
# routes (/image-sets/{id}/run-batch/status, /ollama/pull/status, ...) need
# runtime state and are intentionally excluded. /health/ready's providers
# are all expected FALSE on a CI runner (no Ollama/LM Studio/cloud); only
# the response SHAPE is asserted.
# ---------------------------------------------------------------------------
for ep in "health/ready" "server-mode/status" "encryption/status" "facial-analysis/status" "troubleshoot/status"; do
  if curl -fsS "${BASE}/api/v1/${ep}" >/dev/null 2>&1; then
    echo "[smoke] OK   /api/v1/${ep}"
  else
    fail "status endpoint failed: /api/v1/${ep}"
  fi
done
curl -fsS "${BASE}/api/v1/health/ready" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert isinstance(d.get('providers'), dict), f\"health/ready providers shape wrong: {d}\"
" || fail "health/ready did not report a providers object"

echo "[smoke] PASS: full resource registry + persuasion + status endpoints verified in the bundle"
