#!/usr/bin/env bash
# Live end-to-end verification of the in-app Arabic data pack installer
# against the FROZEN default (installer-only) bundle:
#   bare machine -> engine 503s -> in-app install (real download from CAMeL
#   Lab releases, size+SHA verified) -> engine reports installed -> REAL
#   Arabic analysis + dialect ID now succeed.
set -uo pipefail

BIN="/home/z/my-project/CorpusMind/engine/dist/corpusmind-engine/corpusmind-engine"
TARGET=/tmp/camel-install-test
BAREHOME=/tmp/cm-bare-home2
PORT=8801
BASE="http://127.0.0.1:${PORT}"

rm -rf "${TARGET}" "${BAREHOME}"
mkdir -p "${TARGET}" "${BAREHOME}"

CAMELTOOLS_DATA="${TARGET}" HOME="${BAREHOME}" CORPUSMIND_PORT="${PORT}" "${BIN}" > /tmp/cm-installer-test.log 2>&1 &
EPID=$!
trap 'kill ${EPID} 2>/dev/null' EXIT

for _ in $(seq 1 30); do
  curl -fsS "${BASE}/api/v1/health" >/dev/null 2>&1 && break
  sleep 1
done
echo "[e2e] engine up (bare machine)"

CODE=$(curl -s -o /tmp/e2e-503.json -w '%{http_code}' -X POST "${BASE}/api/v1/arabic/analyze" -H "Content-Type: application/json" -d '{"text": "الطلاب يدرسون في المكتبة"}')
echo "[e2e] pre-install analysis -> HTTP ${CODE} (expect 503)"
python3 -c "import json; d=json.load(open('/tmp/e2e-503.json')); assert 'data is not installed' in d['detail'], d" || exit 1

curl -fsS -X POST "${BASE}/api/v1/arabic/data/install" -H "Content-Type: application/json" -d '{"include_dialect_id": true}' > /tmp/e2e-start.json || exit 1
echo "[e2e] install started: $(python3 -c "import json; d=json.load(open('/tmp/e2e-start.json')); print(d['state'], round(d['bytes_total']/1048576,1), 'MB')")"

LAST=""
for i in $(seq 1 200); do
  S=$(curl -fsS "${BASE}/api/v1/arabic/data/install/status")
  STATE=$(echo "$S" | python3 -c "import json,sys; print(json.load(sys.stdin)['state'])")
  CUR=$(echo "$S" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('stage'), f\"{d.get('bytes_done',0)/1048576:.0f}MB/{d.get('bytes_total',1)/1048576:.0f}MB\", d.get('current_package'))")
  if [ "$CUR" != "$LAST" ]; then echo "[e2e] [$STATE] $CUR"; LAST="$CUR"; fi
  if [ "$STATE" != "running" ]; then
    echo "$S" > /tmp/e2e-final.json
    break
  fi
  sleep 3
done
python3 -c "
import json
d = json.load(open('/tmp/e2e-final.json'))
print('[e2e] final state:', d['state'])
assert d['state'] == 'done', d
print('[e2e] installed:', d['installed'])
" || { echo "[e2e] FAIL: install did not complete"; cat /tmp/e2e-final.json 2>/dev/null | head -5; exit 1; }

ls "${TARGET}/catalogue.json" "${TARGET}/versions.json" >/dev/null || exit 1
echo "[e2e] target dir contents verified (catalogue.json + versions.json + data/)"
python3 -c "import json; print('[e2e] versions.json:', json.load(open('${TARGET}/versions.json')))"

# The engine pins CAMELTOOLS_DATA at camel_tools import time; a fresh
# process is the honest end-user path: restart and re-check.
kill ${EPID} 2>/dev/null; sleep 2
CAMELTOOLS_DATA="${TARGET}" HOME="${BAREHOME}" CORPUSMIND_PORT="${PORT}" "${BIN}" >> /tmp/cm-installer-test.log 2>&1 &
EPID=$!
for _ in $(seq 1 30); do
  curl -fsS "${BASE}/api/v1/health" >/dev/null 2>&1 && break
  sleep 1
done
echo "[e2e] engine restarted; /health/resources camel section:"
curl -fsS "${BASE}/api/v1/health/resources" | python3 -c "import json,sys; print(' ', json.load(sys.stdin)['languages']['camel_tools'])"

A=$(curl -fsS -X POST "${BASE}/api/v1/arabic/analyze" -H "Content-Type: application/json" -d '{"text": "الطلاب يدرسون في المكتبة"}')
echo "$A" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d['backend'] == 'camel' and d['token_count'] >= 3, d
assert any('ك.ت.ب' in t['root'] for t in d['tokens']), d
print('[e2e] POST /arabic/analyze after install: REAL analysis, root ك.ت.ب present')
" || exit 1

D=$(curl -fsS -X POST "${BASE}/api/v1/arabic/dialect" -H "Content-Type: application/json" -d '{"text": "شلون الحال اليوم", "include_cities": true}')
echo "$D" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('city_scores'), d
print('[e2e] POST /arabic/dialect after install: DIDModel6 city scores present, top =', d.get('top_city'))
" || exit 1

echo "[e2e] PASS: installer fixed the bare machine end-to-end inside the frozen bundle"
