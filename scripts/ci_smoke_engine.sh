#!/usr/bin/env bash
# Post-build smoke gate for the packaged engine sidecar (v1.2.8, review #6;
# v1.2.9 adds the Student Mode classroom stack; v1.2.11 follow-up branches on
# the camel-tools data pack and adds dialect-ID + AI-chat Arabic tool checks).
#
# Launches the PyInstaller-built engine binary on a scratch port and asserts
# that the features that regressed in the shipped v1.2.8 actually work
# inside the bundle:
#   - the USAS semantic lexicon resolves (reference-data path fix)
#   - the Academic Word List is found (same fix, silent degradation)
#   - the persuasion-index package imports (dependency manifest + spec fix)
#   - the bundled web-dist + Caddy binary exist (Student Mode prerequisites)
#
# CAMeL data pack (v1.2.11 follow-up), two modes driven by the SAME build
# flag the spec reads (CORPUSMIND_BUNDLE_CAMEL_DATA):
#   - =1 (data-bundled build): the bundle MUST contain camel-tools-data/,
#     /health/resources must report it, and the smoke then exercises
#     REAL Arabic analysis, REAL dialect identification (DIDModel6 city
#     scores), and ONE AI-chat Arabic tool call end-to-end through a fake
#     OpenAI-compatible provider (scripts/ci_smoke_fake_provider.py).
#   - unset/0 (default build): the bundle MUST NOT contain the pack; with a
#     scratch HOME (simulating a bare machine) Arabic analysis must answer
#     the fast 503 + hint, and /health must stay responsive throughout.
#
# The release workflow runs this on every platform BEFORE the Tauri
# packaging step; a failure fails the release. Usage:
#   scripts/ci_smoke_engine.sh <path-to-engine-binary>
set -euo pipefail

BIN="${1:?usage: ci_smoke_engine.sh <engine-binary>}"
PORT="${CORPUSMIND_SMOKE_PORT:-8799}"
BASE="http://127.0.0.1:${PORT}"
BUNDLE_CAMEL_DATA="${CORPUSMIND_BUNDLE_CAMEL_DATA:-0}"

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

# v1.2.11 follow-up: camel-tools data pack content gate, mode-driven.
if [ "${BUNDLE_CAMEL_DATA}" = "1" ]; then
  if [ -f "${INTERNAL_DIR}/camel-tools-data/catalogue.json" ]; then
    echo "[smoke] OK   camel-tools-data/catalogue.json (data pack bundled)"
  else
    echo "[smoke] FAIL: CORPUSMIND_BUNDLE_CAMEL_DATA=1 but camel-tools-data/catalogue.json is missing from the bundle"
    exit 1
  fi
else
  if [ ! -e "${INTERNAL_DIR}/camel-tools-data" ]; then
    echo "[smoke] OK   camel-tools-data correctly ABSENT (default build; in-app installer covers it)"
  else
    echo "[smoke] FAIL: default build must NOT bundle camel-tools-data (GPL-2.0-only data is opt-in via CORPUSMIND_BUNDLE_CAMEL_DATA=1)"
    exit 1
  fi
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

echo "[smoke] launching ${BIN} on port ${PORT} (BUNDLE_CAMEL_DATA=${BUNDLE_CAMEL_DATA})"
if [ "${BUNDLE_CAMEL_DATA}" = "1" ]; then
  # Bundled mode: the pack resolves from the bundle itself. Also wire the
  # fake OpenAI-compatible cloud provider so the AI-chat Arabic tool call
  # can run without Ollama/LM Studio.
  FAKE_PROVIDER_PORT="${CORPUSMIND_SMOKE_FAKE_PROVIDER_PORT:-8791}"
  FAKE_PROVIDER_URL="http://127.0.0.1:${FAKE_PROVIDER_PORT}/v1"
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  python3 "${SCRIPT_DIR}/ci_smoke_fake_provider.py" "${FAKE_PROVIDER_PORT}" &
  FAKE_PID=$!
  CORPUSMIND_PORT="${PORT}" \
  CORPUSMIND_CLOUD_PROVIDER="custom" \
  CORPUSMIND_CLOUD_BASE_URL="${FAKE_PROVIDER_URL}" \
  CORPUSMIND_CLOUD_API_KEY="smoke-not-a-real-key" \
  CORPUSMIND_CLOUD_DEFAULT_MODEL="smoke-fake" \
    "${BIN}" &
  ENGINE_PID=$!
else
  # Default mode: run with a scratch HOME so the smoke reflects a BARE
  # end-user machine (no ~/.camel_tools), regardless of what the build
  # machine happens to have provisioned.
  SCRATCH_HOME="$(mktemp -d)"
  CORPUSMIND_PORT="${PORT}" HOME="${SCRATCH_HOME}" CAMELTOOLS_DATA="" "${BIN}" &
  ENGINE_PID=$!
fi
cleanup() {
  kill "${ENGINE_PID}" 2>/dev/null || true
  if [ -n "${FAKE_PID:-}" ]; then kill "${FAKE_PID}" 2>/dev/null || true; fi
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
# build contractually ships must be true here. The camel_tools keys follow
# the build mode: REQUIRED true in bundled builds, REQUIRED false in default
# builds (with a scratch HOME they cannot silently come from the machine).
# Report-only keys (spacy_model, sentiment) are printed for the record.
# ---------------------------------------------------------------------------
echo "${RES_JSON}" | CORPUSMIND_SMOKE_CAMEL_MODE="${BUNDLE_CAMEL_DATA}" python3 -c "
import json, os, sys
d = json.load(sys.stdin)
mode = os.environ.get('CORPUSMIND_SMOKE_CAMEL_MODE', '0')
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
          'quranic_arabic_freq', 'dialectal_tweets_top1000',
          'urdu_freq_top1000', 'hindi_freq_top1000', 'farsi_freq_top1000'):
    need(f'reference_corpora.{k}', rc.get(k) is True, f'reference corpus missing: {k}')

fw = d.get('frameworks', {}).get('count', 0)
if fw < 12:
    problems.append(f'framework catalogue incomplete: {fw} YAMLs (floor 12)')

need('spacy_model.en_core_web_sm', d.get('spacy_model', {}).get('en_core_web_sm') is True,
     'spaCy en_core_web_sm not collected in bundle')

need('wordfreq.installed', d.get('wordfreq', {}).get('installed') is True, 'wordfreq missing')

cam = d.get('languages', {}).get('camel_tools', {})
if mode == '1':
    need('languages.camel_tools.morphology_db_msa', cam.get('morphology_db_msa') is True,
         'CAMeL calima-msa-r13 not collected in bundle')
    need('languages.camel_tools.dialectid_model6', cam.get('dialectid_model6') is True,
         'CAMeL dialectid model6 not collected in bundle')
else:
    need('languages.camel_tools.installed', cam.get('installed') is False,
         'default build reported a camel data pack (must be installer-only)')

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
for ep in "health/ready" "server-mode/status" "encryption/status" "facial-analysis/status" "troubleshoot/status" "arabic/data/install/status"; do
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

# ---------------------------------------------------------------------------
# v1.2.11 follow-up: CAMeL mode-specific Arabic behaviour.
# ---------------------------------------------------------------------------
if [ "${BUNDLE_CAMEL_DATA}" = "1" ]; then
  # 1. REAL morphology analysis inside the bundle.
  ANALYZE_JSON="$(curl -fsS -X POST "${BASE}/api/v1/arabic/analyze" \
    -H "Content-Type: application/json" \
    -d '{"text": "الطلاب يدرسون في المكتبة", "dialect": "msa"}')" \
    || fail "POST /arabic/analyze failed in the data-bundled build"
  echo "${ANALYZE_JSON}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('backend') == 'camel', d
assert d.get('token_count', 0) >= 3, d
assert any('ك.ت.ب' in (t.get('root') or '') for t in d.get('tokens', [])), 'no root ك.ت.ب in bundle analysis'
" || fail "Arabic morphology analysis did not return a real calima analysis"
  echo "[smoke] OK   POST /arabic/analyze (real calima morphology in bundle)"

  # 2. REAL dialect identification (DIDModel6, city-level scores).
  DIALECT_JSON="$(curl -fsS -X POST "${BASE}/api/v1/arabic/dialect" \
    -H "Content-Type: application/json" \
    -d '{"text": "شلون الحال اليوم وين رايح", "include_cities": true}')" \
    || fail "POST /arabic/dialect failed in the data-bundled build"
  echo "${DIALECT_JSON}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
dist = d.get('dialect_distribution') or {}
assert set(('msa', 'egy', 'glf', 'lev')) <= set(dist), f'dialect buckets missing: {dist}'
assert abs(sum(float(v) for v in dist.values()) - 1.0) < 0.05, f'distribution does not sum to 1: {dist}'
cities = d.get('city_scores') or {}
assert cities, f'city_scores missing (include_cities=true): {d}'
assert d.get('top_city'), f'top_city missing: {d}'
" || fail "Arabic dialect ID did not return a real DIDModel6 result"
  echo "[smoke] OK   POST /arabic/dialect (DIDModel6 + city scores in bundle)"

  # 3. ONE AI-chat Arabic tool call through the fake OpenAI-compatible
  #    provider: the model asks for arabic_morphology, the ENGINE executes
  #    it (real CAMeL, inside the bundle), the result feeds the final answer.
  CHAT_JSON="$(curl -fsS -X POST "${BASE}/api/v1/ai/chat" \
    -H "Content-Type: application/json" \
    -d '{"message": "What are the roots of the words in: الكتب المفيدة في المكتبة", "provider": "cloud", "model": "smoke-fake"}')" \
    || fail "POST /ai/chat with the fake provider failed"
  echo "${CHAT_JSON}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
content = d.get('content') or ''
assert 'SMOKE_ARABIC_TOOL_OK' in content, f'AI-chat Arabic tool call did not execute: {content[:300]}'
calls = d.get('tool_calls') or []
assert calls and calls[0].get('name') == 'arabic_morphology', f'tool_calls wrong: {calls}'
assert calls[0].get('ok') is True, f'tool call recorded as failed: {calls}'
" || fail "the AI-chat Arabic tool call did not produce a grounded answer"
  echo "[smoke] OK   POST /ai/chat arabic_morphology tool call executed in bundle"

  echo "[smoke] PASS: full resource registry + persuasion + status endpoints + Arabic analysis + dialect ID + AI-chat Arabic tool call verified in the bundle"
else
  # Default (installer-only) build: with a scratch HOME the Arabic routes
  # must refuse fast with the actionable 503, and /health must stay live.
  T0="$(date +%s)"
  HTTP_CODE="$(curl -s -o /tmp/cm-smoke-503.json -w '%{http_code}' -X POST "${BASE}/api/v1/arabic/analyze" \
    -H "Content-Type: application/json" \
    -d '{"text": "الطلاب يدرسون في المكتبة", "dialect": "msa"}' || echo 000)"
  T1="$(date +%s)"
  if [ "${HTTP_CODE}" != "503" ]; then
    fail "default build: POST /arabic/analyze on a bare machine returned ${HTTP_CODE}, expected fast 503 (body: $(cat /tmp/cm-smoke-503.json 2>/dev/null | head -c 200))"
  fi
  python3 -c "
import json
d = json.load(open('/tmp/cm-smoke-503.json'))
detail = str(d.get('detail', ''))
assert 'data is not installed' in detail, f'unexpected 503 detail: {detail[:200]}'
assert 'never downloads data at request time' in detail, '503 hint lost its contract line'
" || fail "503 detail is not the actionable missing-data hint"
  echo "[smoke] OK   default build: POST /arabic/analyze answered fast 503 + hint on a bare machine ($((T1-T0))s)"
  if ! curl -fsS "${BASE}/api/v1/health" >/dev/null 2>&1; then
    fail "engine /health stopped answering after the 503 (event loop blocked?)"
  fi
  echo "[smoke] OK   /health still live after the 503"

  echo "[smoke] PASS: full resource registry + persuasion + status endpoints verified in the bundle (installer-only Arabic mode)"
fi
