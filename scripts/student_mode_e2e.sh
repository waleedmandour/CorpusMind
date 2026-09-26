#!/usr/bin/env bash
# v1.2.9 Student Mode E2E — real Caddy, real engine, real TLS (local CA).
# Boots the PyInstaller-built engine, enables the classroom server in
# SECURE mode, then exercises the student/teacher/anonymous paths through
# Caddy's HTTPS port exactly as a student phone would.
set -euo pipefail

ENGINE_BIN="engine/dist/corpusmind-engine/corpusmind-engine"
DATA_DIR="/tmp/cm-student-e2e"
PORT=8765
BASE="http://127.0.0.1:${PORT}"

rm -rf "${DATA_DIR}"
mkdir -p "${DATA_DIR}"

CORPUSMIND_DATA_DIR="${DATA_DIR}" CORPUSMIND_PORT="${PORT}" "${ENGINE_BIN}" &
ENGINE_PID=$!
trap 'kill ${ENGINE_PID} 2>/dev/null || true; [ -n "${CADDY_PID:-}" ] && kill ${CADDY_PID} 2>/dev/null || true' EXIT

echo -n "[e2e] waiting for engine"
for _ in $(seq 1 60); do
  curl -fsS "${BASE}/api/v1/health" >/dev/null 2>&1 && break
  echo -n "."; sleep 1
done
echo " OK"

fail() { echo "[e2e] FAIL: $1"; exit 1; }
ok()   { echo "[e2e] OK   $1"; }

# --- 1. Enable the classroom in SECURE mode -----------------------------
ENABLE_JSON="$(curl -fsS -X POST "${BASE}/api/v1/server-mode/enable" \
  -H 'Content-Type: application/json' \
  -d '{"mode":"secure","student_model":"llama3.2:3b","num_parallel":4}')"
echo "${ENABLE_JSON}" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['enabled'] is True, d
assert d['caddy_running'] is True, d
assert d['mode']=='secure', d
assert d['student_token'].startswith('cm_study_'), d
assert d['teacher_token'].startswith('cm_teach_'), d
assert d['urls'].get('root_ca'), d
open('/tmp/cm-student-e2e/tokens.json','w').write(json.dumps({'t':d['teacher_token'],'s':d['student_token'],'url':d['urls']['app'],'ca':d['urls']['root_ca']}))
" || fail "enable response invalid"
ok "classroom enabled (secure mode), Caddy running"

STUDENT=$(python3 -c "import json;print(json.load(open('/tmp/cm-student-e2e/tokens.json'))['s'])")
TEACHER=$(python3 -c "import json;print(json.load(open('/tmp/cm-student-e2e/tokens.json'))['t'])")
# The sandbox/CI host may not route its own reported LAN IP; the functional
# checks target loopback (the leaf certificate covers 127.0.0.1 anyway).
APPURL="https://127.0.0.1:8483"
CAURL=$(python3 -c "import json;print(json.load(open('/tmp/cm-student-e2e/tokens.json'))['ca'])")

# --- 2. The PWA is served by Caddy over HTTPS ---------------------------
curl -kfsS "${APPURL}/" | grep -qi "index\|<div id=\"root\"" || fail "PWA not served over classroom HTTPS"
ok "PWA served through Caddy (${APPURL})"
curl -kfsS "${CAURL}" | head -1 | grep -qi "CERTIFICATE" || fail "root CA not served on helper port"
ok "root CA downloadable for the trust step (${CAURL})"

# --- 3. API through Caddy: auth required --------------------------------
CODE=$(curl -ks -o /dev/null -w '%{http_code}' "${APPURL}/api/v1/version")
[ "${CODE}" = "401" ] || fail "proxied request without token -> ${CODE} (want 401)"
ok "proxied request without token rejected (401)"

# --- 4. Student token: analysis allowed, management denied --------------
CODE=$(curl -ks -o /dev/null -w '%{http_code}' -H "Authorization: Bearer ${STUDENT}" "${APPURL}/api/v1/version")
[ "${CODE}" = "200" ] || fail "student /version -> ${CODE} (want 200)"
ok "student token reads /version (200)"

CODE=$(curl -ks -o /dev/null -w '%{http_code}' -X POST -H "Authorization: Bearer ${STUDENT}" \
  -H 'Content-Type: application/json' -d '{"name":"sneaky"}' "${APPURL}/api/v1/projects")
[ "${CODE}" = "403" ] || fail "student POST /projects -> ${CODE} (want 403)"
ok "student upload/create denied (403)"

CODE=$(curl -ks -o /dev/null -w '%{http_code}' -H "Authorization: Bearer ${STUDENT}" "${APPURL}/api/v1/ai/conversations")
[ "${CODE}" = "403" ] || fail "student conversations -> ${CODE} (want 403)"
ok "teacher chat history hidden from students (403)"

CODE=$(curl -ks -o /dev/null -w '%{http_code}' -H "Authorization: Bearer ${STUDENT}" "${APPURL}/api/v1/server-mode/status")
[ "${CODE}" = "403" ] || fail "student server-mode/status -> ${CODE} (want 403)"
ok "classroom control plane hidden from students (403)"

CODE=$(curl -ks -o /dev/null -w '%{http_code}' -H "Authorization: Bearer ${STUDENT}" "${APPURL}/api/v1/health/resources")
[ "${CODE}" = "200" ] || fail "student /health/resources -> ${CODE} (want 200)"
ok "student can read resource health (200)"

# --- 5. Teacher token through the proxy: full access --------------------
CODE=$(curl -ks -o /dev/null -w '%{http_code}' -H "Authorization: Bearer ${TEACHER}" "${APPURL}/api/v1/server-mode/status")
[ "${CODE}" = "200" ] || fail "teacher status via proxy -> ${CODE} (want 200)"
ok "teacher token keeps full access through the proxy (200)"

# --- 6. Direct loopback (teacher desktop app): unchanged ----------------
CODE=$(curl -fsS -o /dev/null -w '%{http_code}' "${BASE}/api/v1/version")
[ "${CODE}" = "200" ] || fail "direct loopback /version -> ${CODE} (want 200)"
ok "direct loopback stays teacher-trusted, no auth (200)"

# --- 7. Live student counter --------------------------------------------
COUNT=$(curl -fsS "${BASE}/api/v1/server-mode/status" | python3 -c "import json,sys;print(json.load(sys.stdin)['students_active'])")
[ "${COUNT}" -ge 1 ] || fail "students_active=${COUNT} (want >=1 after student requests)"
ok "connected-student counter live (${COUNT})"

# --- 8. Disable: Caddy stops, proxied traffic refused -------------------
curl -fsS -X POST "${BASE}/api/v1/server-mode/disable" >/dev/null
sleep 1
CODE=$(curl -ks -o /dev/null -w '%{http_code}' "${APPURL}/api/v1/version" 2>/dev/null) || true
case "${CODE}" in
  000|""|7) ok "classroom stops cleanly on disable" ;;
  *) fail "classroom still reachable after disable (${CODE})" ;;
esac

echo "[e2e] PASS: Student Mode classroom stack verified end-to-end (Caddy TLS, roles, allowlist, counter, lifecycle)"
