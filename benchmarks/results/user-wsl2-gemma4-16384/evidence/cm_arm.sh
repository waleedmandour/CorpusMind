#!/usr/bin/env bash
# cm_arm.sh - run ONE new local-model arm of the CorpusMind grounding benchmark
# under the pre-specified plan v1 + addendum 1 (benchmarks/plans/2026-11-06_gemma4-e4b-arm-plan-v1*.md).
# Same protocol as the qwen2.5:7b Tier-B user run. One script, one step per command.
#
#   bash cm_arm.sh <step>
#
# Steps, in order:
#   prep            checks only (no measurement): versions, disk, RAM, commit, gold hash, plan on GitHub
#   serve           (re)start the pinned Ollama server with the fixed env + log file
#   pull            gate 1: ollama pull <MODEL>; on failure writes evidence/pull_failure.txt (addendum A2)
#   qwen-meta       record digest/quantisation of qwen2.5:7b (read-only, no pull)
#   probe0          gate 2: tool-call + thinking micro-probe on the engine's tool path
#   trunc-selftest  gate 4: throwaway server at ctx 2048 (port 11435) must log "truncated = 1"
#   probe-g076      gate 3: G-076 argument-serialization probe (one harness question)
#   probe5          gate 5: 5-question harness probe G-001..G-005
#   all             3 repetitions x 4 shards, warm-up before each (needs gates 1-5 PASS)
#   rep N           one repetition only (N = 1, 2 or 3); skips shards already complete
#   status          progress, shard stats, truncation count, resident model
#   rescue ID N     ONE rescue re-run of a transport-errored question ID in repetition N
#   mark-failed F   rename a shard invalidated by a protocol violation to *.FAILED.json (never deletes)
#   evidence        collect env, host, pip, logs, repo state into the results folder
#   validate        run scripts/validate_user_run.py (merge + score + flips vs CI arms)
#   manifest        write manifest.json over the whole results folder
#   upload-list     show what to upload and the Windows path of the folder
#
# Primary arm (plan v1 + addendum 1):  gemma4:e4b -> folder user-wsl2-gemma4-16384, tags g4_16k_r1..r3
# Fallback arm (ONLY if the primary's gate fails / pull fails; addendum A2):
#   MODEL=llama3.1:8b SLUG=llama3.1-8b TAG=l8_16k bash cm_arm.sh <step>
set -uo pipefail

PRIMARY_MODEL="gemma4:e4b"
MODEL="${MODEL:-$PRIMARY_MODEL}"
SLUG="${SLUG:-gemma4}"
TAG="${TAG:-g4_16k}"

CTX=16384
OLLAMA_PIN="0.40.13"
COMMIT="5a5e43fa0c9e6a903dc06f79579b732a9f666bca"
GOLD_PREFIX="480f5230"
QWEN_MODEL="qwen2.5:7b"
QWEN_DIGEST="845dbda0ea48"
CI_ARMS=(41306198564 41306203484 41306208341)   # bare run ids; the validator prefixes "run-"
PLAN_FILES=(benchmarks/plans/2026-11-06_gemma4-e4b-arm-plan-v1.md
            benchmarks/plans/2026-11-06_gemma4-e4b-arm-plan-v1-addendum-1.md)
RAW_BASE="${RAW_BASE:-https://raw.githubusercontent.com/waleedmandour/CorpusMind/main}"
SELFTEST_PORT=11435

REPO="${REPO:-$HOME/CorpusMind}"          # frozen engine checkout (tag v2.0.2): fetch only, never pull
MAIN="${MAIN:-$HOME/cm_main}"             # clone of main: plans, validator, manifest scripts
WORK="${WORK:-$HOME/cm_runs/$SLUG}"       # raw outputs of this arm
LOGDIR="$WORK/logs"
EVID="$WORK/evidence"
RES="$MAIN/benchmarks/results/user-wsl2-$SLUG-$CTX"
RUNS="$REPO/engine/eval/runs"
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
DRYRUN="${DRYRUN:-0}"

# ---------------------------------------------------------------- helpers
utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { printf '%s\n' "$*"; }
ok() { printf '  [ OK ] %s\n' "$*"; }
bad() { printf '  [FAIL] %s\n' "$*"; FAILS=$((FAILS + 1)); }
warn() { printf '  [WARN] %s\n' "$*"; }
note() { mkdir -p "$WORK"; printf '%s  %s\n' "$(utc)" "$*" >>"$WORK/notes.txt"; }
x() { if [ "$DRYRUN" = 1 ]; then printf '+ %s\n' "$*"; else "$@"; fi; }
FAILS=0

# Python helpers go through one function so every call is isolated (-I).
py() { python3 -I "$@"; }

keep_prev() {   # move an earlier attempt aside (never delete evidence)
  [ -e "$1" ] && { mv "$1" "${1%.json}.attempt-$(date -u +%Y%m%dT%H%M%S).json"; warn "earlier attempt kept as ${1%.json}.attempt-*.json"; }
  return 0
}

api_up() { curl -fsS --noproxy '*' "${1:-$OLLAMA_URL}/api/version" >/dev/null 2>&1; }

# gate bookkeeping: notes.txt carries "GATE n PASS|FAIL model=<tag>;" lines (last one counts)
gate_note() { note "GATE $1 $2 model=$MODEL; ${3:-}"; }
gate_status() {
  local l
  l=$(grep -F -e " GATE $1 PASS model=$MODEL;" -e " GATE $1 FAIL model=$MODEL;" "$WORK/notes.txt" 2>/dev/null | tail -1)
  case "$l" in *" PASS "*) echo PASS ;; *" FAIL "*) echo FAIL ;; *) echo NONE ;; esac
}
gate_guard() {   # all five gates PASS for this model, else refuse; writes ARM CHOICE once
  local n s missing=0
  for n in 1 2 3 4 5; do
    s=$(gate_status "$n")
    if [ "$s" = PASS ]; then ok "gate $n PASS"; else bad "gate $n is $s for $MODEL"; missing=1; fi
  done
  [ "$missing" = 0 ] || { say "  run the missing gate steps first (order: pull, probe0, trunc-selftest, probe-g076, probe5)"; return 1; }
  if ! grep -q 'ARM CHOICE' "$WORK/notes.txt" 2>/dev/null; then
    if [ "$MODEL" = "$PRIMARY_MODEL" ]; then
      note "ARM CHOICE: $MODEL (primary arm; plan v1 section 5 gates 1-5 passed) - written before the first full repetition"
    else
      note "ARM CHOICE: $MODEL (FALLBACK arm per plan v1 section 2 / addendum A2; primary-arm gate evidence committed) - written before the first full repetition"
    fi
    ok "arm choice written to notes.txt"
  fi
}

# ---------------------------------------------------------------- plan guard
# Plan v1 + addendum 1 must already be on GitHub (public raw URL) and equal the local clone,
# so the commit timestamp proves they preceded the first measurement.
plan_guard() {
  local f base rc=0
  [ -d "$MAIN/.git" ] || { bad "no clone of main at $MAIN: run 'prep' first"; return 1; }
  mkdir -p "$WORK/plan_check"; : >"$WORK/plan_check/sha256.txt"
  for f in "${PLAN_FILES[@]}"; do
    base=$(basename "$f")
    if ! curl -fsS -o "$WORK/plan_check/$base" "$RAW_BASE/$f"; then
      bad "not found on GitHub: $RAW_BASE/$f"; rc=1; continue
    fi
    if [ ! -f "$MAIN/$f" ]; then bad "missing in local clone: $f (run: bash cm_arm.sh prep)"; rc=1; continue; fi
    if cmp -s "$WORK/plan_check/$base" "$MAIN/$f"; then
      ok "on GitHub, identical to local clone: $base (sha256 $(sha256sum "$MAIN/$f" | cut -c1-16))"
      (cd "$MAIN" && sha256sum "$f") >>"$WORK/plan_check/sha256.txt"
    else
      bad "GitHub copy differs from the local clone: $base"; rc=1
    fi
  done
  git -C "$MAIN" log --format='%H %cI %s' -- "${PLAN_FILES[@]}" >"$WORK/plan_check/plan_commits.txt" 2>/dev/null || true
  [ -s "$WORK/plan_check/plan_commits.txt" ] && sed 's/^/     plan commit: /' "$WORK/plan_check/plan_commits.txt"
  return "$rc"
}

# ---------------------------------------------------------------- shard stats
# usage: shard_stats file.json [file2.json ...]
shard_stats() {
  py - "$@" <<'PY'
import json, statistics, sys
for path in sys.argv[1:]:
    try:
        d = json.load(open(path))
    except Exception as e:
        print(f"  {path}: unreadable ({e})"); continue
    R = d.get("results", [])
    n = len(R)
    ans = [r for r in R if (r.get("answer") or "").strip()]
    tc = sum(1 for r in R if r.get("tool_calls"))
    ms = [r["elapsed_ms"] / 1000 for r in ans if r.get("elapsed_ms")]
    walls = [r.get("wall_ms", 0) / 1000 for r in R if r.get("wall_ms")]
    med = round(statistics.median(ms)) if ms else 0
    print(f"  {path.split('/')[-1]}: n={n} answered={len(ans)} no_answer={n-len(ans)} "
          f"with_tool_call={tc} median_elapsed_s={med} max_wall_s={round(max(walls, default=0))} "
          f"slow>=180s={sum(1 for w in walls if w>=180)}")
    miss = [r["id"] + "(" + str(r.get("http_status") or "no-answer") + ")" for r in R if not (r.get("answer") or "").strip()]
    if miss:
        print(f"      errored records (rescue candidates after the repetition ends): {' '.join(miss)}")
PY
}

# ---------------------------------------------------------------- truncation gate
# Run gate: plan section 5.4 / qwen precedent is the pattern 'truncated = 1' over the RUN server
# segments. I additionally count 'truncating input prompt' (stricter, never looser).
# The self-test log (selftest_server.log) is not named ollama_server_seg*, so it is excluded.
count_pat() {   # $1 = fixed pattern; prints total over run segments
  local n=0 c f
  for f in "$LOGDIR"/ollama_server_seg*.log; do
    [ -f "$f" ] || continue
    c=$(grep -c -F -e "$1" "$f" || true)
    n=$((n + ${c:-0}))
  done
  echo "$n"
}
trunc_count() { echo $(( $(count_pat 'truncated = 1') + $(count_pat 'truncating input prompt') )); }

kill_port() {   # $1 = port, $2 = pid of the process we started (optional). Never touches other ports.
  local port="$1" pid="${2:-}" pids=""
  [ -n "$pid" ] && { pkill -P "$pid" 2>/dev/null; kill "$pid" 2>/dev/null; }
  sleep 1
  if curl -fsS --noproxy '*' "http://127.0.0.1:$port/api/version" >/dev/null 2>&1; then
    if command -v ss >/dev/null; then pids=$(ss -ltnp "sport = :$port" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u)
    elif command -v lsof >/dev/null; then pids=$(lsof -t -i "TCP:$port" -sTCP:LISTEN 2>/dev/null)
    elif command -v fuser >/dev/null; then pids=$(fuser "$port/tcp" 2>/dev/null); fi
    [ -n "$pids" ] && kill $pids 2>/dev/null
  fi
  return 0
}

# ================================================================ steps
step_prep() {
  say "== prep: checks only (no measurement) =="
  mkdir -p "$LOGDIR" "$EVID"
  command -v ollama >/dev/null && ok "ollama present: $(ollama --version 2>&1 | tail -1)" || bad "ollama not on PATH"
  ollama --version 2>&1 | grep -q "$OLLAMA_PIN" && ok "Ollama pin $OLLAMA_PIN" || bad "Ollama is not $OLLAMA_PIN (do NOT upgrade mid-study)"
  command -v tmux >/dev/null && ok "tmux present" || warn "tmux missing: sudo apt install -y tmux (needed so the run survives a closed terminal)"
  command -v curl >/dev/null && ok "curl present" || bad "curl missing"
  api_up "http://127.0.0.1:$SELFTEST_PORT" && bad "port $SELFTEST_PORT is in use (needed for the truncation self-test)" || ok "port $SELFTEST_PORT free"
  local free_gb avail_gb
  free_gb=$(df -BG --output=avail "$HOME" | tail -1 | tr -dc 0-9)
  [ "${free_gb:-0}" -ge 25 ] && ok "disk free ${free_gb} GB" || bad "disk free ${free_gb} GB (<25 GB)"
  avail_gb=$(free -g | awk '/^Mem:/{print $7}')
  [ "${avail_gb:-0}" -ge 11 ] && ok "RAM available ${avail_gb} GB" || bad "RAM available ${avail_gb} GB (<11 GB): close apps / check .wslconfig"
  if [ -d "$REPO/.git" ]; then
    local head; head=$(git -C "$REPO" rev-parse HEAD)
    [ "$head" = "$COMMIT" ] && ok "engine checkout at $COMMIT" || bad "engine HEAD is $head, expected $COMMIT"
    local dirty; dirty=$(git -C "$REPO" status --porcelain | grep -v 'eval/runs' | wc -l)
    [ "$dirty" -eq 0 ] && ok "engine working tree clean" || warn "$dirty modified/untracked paths in $REPO (git status)"
  else bad "no git repo at $REPO"; fi
  [ -x "$REPO/.venv/bin/python" ] && ok "venv present" || bad "missing $REPO/.venv"
  local gold="$REPO/engine/eval/data/gold/grounding_gold.json"
  if [ -f "$gold" ]; then
    local h; h=$(sha256sum "$gold" | cut -c1-64)
    [ "${h:0:8}" = "$GOLD_PREFIX" ] && ok "gold sha256 ${h:0:16}..." || bad "gold hash ${h:0:16} != $GOLD_PREFIX"
  else bad "gold file missing"; fi
  # full clone (not --depth 1): the plan commit timestamps are read from git log
  if [ -d "$MAIN/.git" ]; then
    [ "$(git -C "$MAIN" rev-parse --is-shallow-repository)" = true ] && git -C "$MAIN" fetch --unshallow -q
    git -C "$MAIN" pull --ff-only -q && ok "main updated at $MAIN" || warn "could not fast-forward $MAIN (local edits, e.g. the validator patch?): git -C $MAIN status"
  else git clone -q https://github.com/waleedmandour/CorpusMind.git "$MAIN" && ok "cloned main to $MAIN" || bad "clone failed"; fi
  local f same=1
  for f in engine/eval/score.py engine/eval/questions.py engine/eval/run_grounding.py engine/eval/build_gold.py \
           engine/eval/corpus_snapshot.py engine/eval/data/gold/grounding_gold.json \
           engine/ai/providers.py engine/ai/assistant.py engine/ai/resilience.py engine/ai/tools.py; do
    cmp -s "$REPO/$f" "$MAIN/$f" || { warn "differs between engine checkout and main: $f"; same=0; }
  done
  [ "$same" = 1 ] && ok "scorer, harness, gold and AI layer identical in checkout and main"
  say "  -- plan files (plan v1 + addendum 1) on GitHub --"
  plan_guard || bad "plan files are not (yet) on GitHub or differ from the clone"
  say; [ "$FAILS" -eq 0 ] && say "prep: all checks passed" || say "prep: $FAILS check(s) failed - fix before continuing"
  note "prep done, fails=$FAILS"
  return "$FAILS"
}

step_serve() {
  say "== serve: pinned Ollama server, fixed env =="
  mkdir -p "$LOGDIR"
  if systemctl is-active --quiet ollama 2>/dev/null; then
    say "stopping the systemd ollama service (sudo password may be asked)"; x sudo systemctl stop ollama
  fi
  x pkill -f "ollama serve" 2>/dev/null; sleep 2
  local n; n=$(ls "$LOGDIR"/ollama_server_seg*.log 2>/dev/null | wc -l); n=$((n + 1))
  local log="$LOGDIR/ollama_server_seg$n.log"
  say "server log: $log"
  if [ "$DRYRUN" = 1 ]; then
    echo "+ OLLAMA_CONTEXT_LENGTH=$CTX OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_KEEP_ALIVE=30m setsid nohup ollama serve > $log 2>&1 &"
    return 0
  fi
  OLLAMA_CONTEXT_LENGTH=$CTX OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_KEEP_ALIVE=30m \
    setsid nohup ollama serve >"$log" 2>&1 &
  local i
  for i in $(seq 1 30); do api_up && break; sleep 1; done
  api_up || { bad "server did not come up; see $log"; return 1; }
  ok "server up: $(curl -fsS --noproxy '*' "$OLLAMA_URL/api/version")"
  note "server started seg$n ctx=$CTX parallel=1 max_loaded=1 keep_alive=30m"
}

api_show_json() {  # $1 model, $2 outfile ; exit 0 only if capability 'tools' present
  py - "$OLLAMA_URL" "$1" "$2" <<'PY'
import json, sys, urllib.request
base, model, out = sys.argv[1:4]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
req = urllib.request.Request(base + "/api/show", data=json.dumps({"model": model}).encode(),
                             headers={"Content-Type": "application/json"})
d = json.load(opener.open(req, timeout=60))
json.dump(d, open(out, "w"), indent=1)
det = d.get("details", {})
mi = d.get("model_info") or {}
ctxlen = next((v for k, v in mi.items() if k.endswith(".context_length")), None)
print(f"  family={det.get('family')} parameter_size={det.get('parameter_size')} "
      f"quantization={det.get('quantization_level')} context_length={ctxlen} capabilities={d.get('capabilities')}")
sys.exit(0 if "tools" in (d.get("capabilities") or []) else 3)
PY
}

api_tags_json() {  # $1 outfile ; prints full digest per model
  py - "$OLLAMA_URL" "$1" <<'PY'
import json, sys, urllib.request
base, out = sys.argv[1:3]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
d = json.load(opener.open(base + "/api/tags", timeout=60))
json.dump(d, open(out, "w"), indent=1)
for m in d.get("models", []):
    print(f"  {m.get('name')}: digest {m.get('digest')}")
PY
}

step_pull() {
  say "== pull (gate 1): $MODEL =="
  mkdir -p "$EVID"
  api_up || { bad "server not running: bash cm_arm.sh serve"; return 1; }
  if [ "$DRYRUN" = 1 ]; then echo "+ ollama pull $MODEL"; return 0; fi
  local raw="$EVID/pull_raw.txt" rc
  { echo "# command: ollama pull $MODEL"; echo "# utc: $(utc)"; echo "# ollama: $(ollama --version 2>&1 | tail -1)"; echo; } >"$raw"
  ollama pull "$MODEL" 2>&1 | tee -a "$raw"
  rc=${PIPESTATUS[0]}
  if [ "$rc" -ne 0 ]; then
    # addendum A2.3: exact command + complete error output, committed as protocol evidence
    local pf="$RES/evidence/pull_failure.txt"
    mkdir -p "$RES/evidence"
    { echo "command: ollama pull $MODEL"
      echo "exit code: $rc"
      echo "utc: $(utc)"
      echo "ollama: $(ollama --version 2>&1 | tail -1)"
      echo "--- complete output (ANSI codes stripped, carriage returns split; percentage progress lines removed; unfiltered text in pull_raw.txt) ---"
      sed -E 's/\x1b\[[0-9;?]*[A-Za-z]//g' "$raw" | tr '\r' '\n' | grep -v -E '^pulling [0-9a-f]{12}: +[0-9]+% '
    } >"$pf"
    cp "$raw" "$RES/evidence/pull_failure_raw.txt"
    gate_note 1 FAIL "pull failed rc=$rc"
    bad "pull failed (exit $rc). Evidence written: $pf"
    say
    say "  ADDENDUM A2: do NOT upgrade Ollama. The primary arm cannot run; the pre-specified fallback"
    say "  (llama3.1:8b) is activated. Next:"
    say "    1) bash cm_arm.sh evidence          # packs pull_failure.txt etc. into $RES/evidence"
    say "    2) upload that one folder to GitHub (protocol evidence), then tell me"
    say "    3) fallback arm, repeating ALL gates:  MODEL=llama3.1:8b SLUG=llama3.1-8b TAG=l8_16k bash cm_arm.sh pull"
    return 1
  fi
  ollama show "$MODEL" >"$EVID/ollama_show_$SLUG.txt" 2>&1
  ollama show "$MODEL" --modelfile >"$EVID/ollama_modelfile_$SLUG.txt" 2>&1 || true
  ollama ls >"$EVID/ollama_ls_$SLUG.txt" 2>&1
  api_tags_json "$EVID/api_tags_$SLUG.json" || warn "could not read /api/tags (full digest)"
  if api_show_json "$MODEL" "$EVID/api_show_$SLUG.json"; then
    ok "capability 'tools' present"; gate_note 1 PASS "tools capability present; digest/quantisation/context/template recorded"
  else
    gate_note 1 FAIL "capability tools missing"
    bad "capability 'tools' MISSING - the engine would silently fall back to NO tools. Plan section 5: gate 1 failed -> fallback arm. Send me $EVID first."
    return 1
  fi
  say "  digest line: $(grep -F "${MODEL%%:*}" "$EVID/ollama_ls_$SLUG.txt" | head -1)"
  note "pulled $MODEL"
}

step_qwen_meta() {
  say "== qwen-meta: read-only record of $QWEN_MODEL (no pull) =="
  mkdir -p "$WORK/qwen_meta"
  api_up || { bad "server not running"; return 1; }
  ollama show "$QWEN_MODEL" >"$WORK/qwen_meta/ollama_show_qwen2.5-7b.txt" 2>&1 || { bad "$QWEN_MODEL not installed locally"; return 1; }
  ollama show "$QWEN_MODEL" --modelfile >"$WORK/qwen_meta/ollama_modelfile_qwen2.5-7b.txt" 2>&1 || true
  ollama ls >"$WORK/qwen_meta/ollama_ls.txt" 2>&1
  api_tags_json "$WORK/qwen_meta/api_tags.json" || true
  api_show_json "$QWEN_MODEL" "$WORK/qwen_meta/api_show_qwen2.5-7b.json" || true
  if grep -q "$QWEN_DIGEST" "$WORK/qwen_meta/ollama_ls.txt"; then ok "digest $QWEN_DIGEST unchanged"
  else bad "qwen2.5:7b digest differs from $QWEN_DIGEST - tell me before going on"; fi
  say "  files in $WORK/qwen_meta (upload to the qwen folder's evidence/)"
}

# Gate 2. Writes JSON; prints a summary table. The judged variant is exactly the engine's request.
step_probe0() {
  say "== probe0 (gate 2): tool-call + thinking micro-probe on the engine's tool path =="
  mkdir -p "$EVID"
  api_up || { bad "server not running"; return 1; }
  keep_prev "$EVID/probe0_$SLUG.json"
  py - "$OLLAMA_URL" "$MODEL" "$EVID/probe0_$SLUG.json" <<'PY'
import json, statistics, sys, time, urllib.request
base, model, out = sys.argv[1:4]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def post(path, body, timeout=900):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t = time.monotonic()
    d = json.load(opener.open(req, timeout=timeout))
    return d, time.monotonic() - t
print("  loading model (first request; cold load may take a minute)...")
_, load_s = post("/api/generate", {"model": model, "prompt": "ok", "stream": False,
                                    "keep_alive": "30m", "options": {"num_predict": 1}})
print(f"  load+first token: {load_s:.0f} s")
tools = [{"type": "function", "function": {
    "name": "get_frequency",
    "description": "Return the token count and the most frequent items of a corpus.",
    "parameters": {"type": "object",
                   "properties": {"corpus_id": {"type": "string"},
                                  "unit": {"type": "string", "enum": ["word", "lemma"]},
                                  "limit": {"type": "integer"}},
                   "required": ["corpus_id"]}}}]
msgs = [{"role": "system", "content": "You are a corpus assistant. Use tools to answer; never guess numbers."},
        {"role": "user", "content": "How many tokens does the corpus with id c123 contain? Use the tool."}]
def run(label, extra):
    rows = []
    for i in range(3):
        body = {"model": model, "messages": msgs, "temperature": 0.2, "stream": False, "tools": tools}
        body.update(extra)
        d, s = post("/v1/chat/completions", body)
        m = d["choices"][0]["message"]
        reasoning = (m.get("reasoning") or m.get("reasoning_content") or m.get("thinking") or "")
        rows.append({"wall_s": round(s, 1), "tool_calls": len(m.get("tool_calls") or []),
                     "completion_tokens": (d.get("usage") or {}).get("completion_tokens"),
                     "reasoning_chars": len(reasoning), "finish": d["choices"][0].get("finish_reason")})
    print(f"  [{label}]")
    for r in rows: print("    ", r)
    return rows
engine_rows = run("engine path (no thinking parameter) - this is what the gate judges", {})
try:
    diag_rows = run("diagnostic only: reasoning_effort=none", {"reasoning_effort": "none"})
except Exception as e:  # diagnostic only; the gate never depends on it
    diag_rows = [{"error": repr(e)}]
    print("  diagnostic request failed (ignored):", repr(e)[:160])
med = lambda k, rows: statistics.median([r[k] for r in rows if r[k] is not None] or [0])
gate = {
    "tool_call_in_>=2_of_3": sum(1 for r in engine_rows if r["tool_calls"] > 0) >= 2,
    "median_wall_<=45s": med("wall_s", engine_rows) <= 45,
    "median_completion_tokens_<=300": med("completion_tokens", engine_rows) <= 300,
    "no_reasoning_text": all(r["reasoning_chars"] == 0 for r in engine_rows),
}
json.dump({"model": model, "load_s": round(load_s, 1), "engine": engine_rows,
           "diag_reasoning_effort_none": diag_rows, "gate": gate}, open(out, "w"), indent=1)
print("  gate:", gate)
print("  PROBE0 GATE:", "PASS" if all(gate.values()) else "FAIL")
sys.exit(0 if all(gate.values()) else 4)
PY
  local rc=$?
  if [ "$rc" -eq 0 ]; then gate_note 2 PASS "probe0"; else gate_note 2 FAIL "probe0 rc=$rc"; fi
  return $rc
}

# Gate 4: throwaway server at ctx 2048 on its own port and its own log.
step_trunc_selftest() {
  say "== trunc-selftest (gate 4): does the log pattern fire on this Ollama build? =="
  mkdir -p "$LOGDIR" "$EVID"
  api_up || { bad "main server not running: bash cm_arm.sh serve"; return 1; }
  local url="http://127.0.0.1:$SELFTEST_PORT" slog="$LOGDIR/selftest_server.log"
  if api_up "$url"; then bad "something already listens on port $SELFTEST_PORT"; return 1; fi
  [ -e "$slog" ] && mv "$slog" "$slog.$(date -u +%H%M%S).old"        # never delete evidence
  # free RAM: only one model resident at a time (main server unloads, throwaway loads at ctx 2048)
  ollama stop "$MODEL" >/dev/null 2>&1 || true
  say "  throwaway server: port $SELFTEST_PORT, OLLAMA_CONTEXT_LENGTH=2048, log $slog"
  OLLAMA_HOST="127.0.0.1:$SELFTEST_PORT" OLLAMA_CONTEXT_LENGTH=2048 OLLAMA_NUM_PARALLEL=1 \
    OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_KEEP_ALIVE=1m setsid nohup ollama serve >"$slog" 2>&1 &
  local tpid=$!
  local i; for i in $(seq 1 30); do api_up "$url" && break; sleep 1; done
  api_up "$url" || { bad "throwaway server did not start; see $slog"; kill_port "$SELFTEST_PORT" "$tpid"; gate_note 4 FAIL "selftest server did not start"; return 1; }
  py - "$url" "$MODEL" <<'PY'
import json, sys, urllib.request
base, model = sys.argv[1:3]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
prompt = "The corpus contains many short sentences about language and numbers. " * 700
body = {"model": model, "prompt": prompt, "stream": False, "keep_alive": "1m", "options": {"num_predict": 1}}
req = urllib.request.Request(base + "/api/generate", data=json.dumps(body).encode(),
                             headers={"Content-Type": "application/json"})
d = json.load(opener.open(req, timeout=900))
print(f"  deliberate overflow sent (~8k tokens into a 2048 context): prompt_eval_count={d.get('prompt_eval_count')}")
PY
  local prc=$?
  sleep 3
  kill_port "$SELFTEST_PORT" "$tpid"; sleep 2
  api_up "$url" && warn "throwaway server still answering on port $SELFTEST_PORT - stop it (ps aux | grep 'ollama serve') before probe5/rep"
  cp "$slog" "$EVID/selftest_server.log"
  local a b
  a=$(grep -c -F 'truncated = 1' "$slog" || true); b=$(grep -c -F 'truncating input prompt' "$slog" || true)
  say "  matches in the self-test log: 'truncated = 1' = $a ; 'truncating input prompt' = $b"
  if [ "$prc" -eq 0 ] && { [ "$a" -gt 0 ] || [ "$b" -gt 0 ]; }; then
    ok "truncation self-test marker fired (addendum-2 A3: either pattern)"
    [ "$a" -gt 0 ] && grep -F 'truncated = 1' "$slog" | tail -2 | cut -c1-200 | sed 's/^/     A /'
    [ "$b" -gt 0 ] && grep -F 'truncating input prompt' "$slog" | tail -2 | cut -c1-200 | sed 's/^/     B /'
    gate_note 4 PASS "truncated=1 lines: $a; truncating-input-prompt lines: $b (addendum-2 A3)"
  else
    gate_note 4 FAIL "truncated=1 lines: $a; truncating-input-prompt lines: $b; request rc=$prc"
    bad "gate 4 NOT passed: the plan's pattern 'truncated = 1' did not appear (rc=$prc)."
    say "     STOP. Do not switch arms and do not improvise a new pattern: this needs a plan amendment."
    say "     Send me $EVID/selftest_server.log (tail -60)."
    return 1
  fi
  say "  (the next request reloads the model at ctx $CTX on the main server - 'warm' does that)"
}

step_warm() {
  say "== warm: load $MODEL at the server default context =="
  api_up || { bad "server not running"; return 1; }
  x py - "$OLLAMA_URL" "$MODEL" <<'PY'
import json, sys, time, urllib.request
base, model = sys.argv[1:3]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
body = {"model": model, "prompt": "ok", "stream": False, "keep_alive": "30m", "options": {"num_predict": 1}}
t = time.monotonic()
req = urllib.request.Request(base + "/api/generate", data=json.dumps(body).encode(),
                             headers={"Content-Type": "application/json"})
opener.open(req, timeout=900).read()
print(f"  warm in {time.monotonic()-t:.0f} s")
PY
  [ "$DRYRUN" = 1 ] && { echo "+ ollama ps"; return 0; }
  local psout val seg
  psout=$(ollama ps 2>&1); printf '%s\n' "$psout"
  mkdir -p "$EVID"; { echo "# $(utc)"; printf '%s\n' "$psout"; } >>"$EVID/warm_ps_$SLUG.txt"
  # columns are separated by 2+ spaces (PROCESSOR and UNTIL contain single spaces): locate CONTEXT in the header
  val=$(printf '%s\n' "$psout" | awk -F'  +' 'NR==1{for(i=1;i<=NF;i++) if($i=="CONTEXT") c=i} NR==2&&c{print $c}')
  if [ -n "$val" ]; then
    [ "$val" = "$CTX" ] && ok "resident context is $CTX (ollama ps)" \
      || { bad "resident context is '$val', expected $CTX: restart the server with 'serve' and warm again"; return 1; }
  else
    seg=$(ls "$LOGDIR"/ollama_server_seg*.log 2>/dev/null | tail -1)
    if [ -n "$seg" ] && grep -q -E "(ctx-size|n_ctx|num_ctx|NumCtx)[ =:]+$CTX" "$seg"; then ok "server log shows context $CTX"
    else warn "cannot verify the resident context (no CONTEXT column in 'ollama ps', no $CTX in the log): the truncation gate is the safeguard"; fi
  fi
  ollama ps 2>/dev/null | grep -q -F "$MODEL" || { bad "$MODEL is not the resident model"; return 1; }
}

harness() {   # $1 = out (relative to engine/), $2 = log file, rest = question ids
  local out="$1" log="$2"; shift 2
  if [ "$DRYRUN" = 1 ]; then
    echo "+ (cd $REPO/engine && CORPUSMIND_CHAT_TIMEOUT_S=900 CORPUSMIND_OLLAMA_KEEP_ALIVE=30m python -m eval.run_grounding --provider ollama --model $MODEL --pause 0 --rate-retries 4 --timeout 900 --only $* --out $out) | tee -a $log"
    return 0
  fi
  ( cd "$REPO/engine" && source "$REPO/.venv/bin/activate" && \
    CORPUSMIND_CHAT_TIMEOUT_S=900 CORPUSMIND_OLLAMA_KEEP_ALIVE=30m \
    python -m eval.run_grounding --provider ollama --model "$MODEL" --pause 0 \
      --rate-retries 4 --timeout 900 --only "$@" --out "$out" ) 2>&1 | tee -a "$log"
  return "${PIPESTATUS[0]}"
}

shard_ids() { local s="$1" lo hi; lo=$((20 * (s - 1) + 1)); hi=$((20 * s)); printf 'G-%03d ' $(seq "$lo" "$hi"); }

shard_complete() {   # $1 = file ; exit 0 if valid JSON with exactly 20 results
  py - "$1" <<'PY'
import json, sys
try: n = len(json.load(open(sys.argv[1]))["results"])
except Exception: sys.exit(2)
sys.exit(0 if n == 20 else 1)
PY
}

run_shard() {   # $1 = file stem (e.g. g4_16k_r1), $2 = shard number 1..4, $3 = log file
  local stem="$1" s="$2" log="$3" out ids
  ids=$(shard_ids "$s"); out="eval/runs/${stem}_shard${s}.json"
  if [ -e "$REPO/engine/$out" ]; then
    if shard_complete "$REPO/engine/$out"; then ok "$out already complete (20 records) - skipped"; return 0; fi
    bad "$out exists but is not a complete 20-record shard: inspect it, then 'mark-failed ${stem}_shard${s}.json'"; return 1
  fi
  say "-- $stem shard $s: $(echo $ids | awk '{print $1".."$NF}')  $(utc)"
  harness "$out" "$log" $ids || { bad "harness exited non-zero for shard $s"; return 1; }
  [ "$DRYRUN" = 1 ] || shard_stats "$REPO/engine/$out"
}

# Gate 3: the argument-serialization probe (plan v1 section 5.3).
step_probe_g076() {
  say "== probe-g076 (gate 3): is the tool-call argument serialization well-formed? =="
  plan_guard || return 1
  mkdir -p "$LOGDIR" "$EVID"; step_warm || return 1
  local out="eval/runs/${TAG}_probe_g076.json" log="$LOGDIR/${TAG}_probe_g076.log"
  keep_prev "$REPO/engine/$out"
  harness "$out" "$log" G-076
  [ "$DRYRUN" = 1 ] && return 0
  py - "$REPO/engine/$out" <<'PY'
import json, re, sys
R = json.load(open(sys.argv[1]))["results"]
r = next((x for x in R if x.get("id") == "G-076"), None)
why = []
if r is None:
    why.append("no G-076 record")
else:
    calls = r.get("tool_calls") or []
    ans = (r.get("answer") or "").strip()
    cql = [c for c in calls if c.get("name") == "search_cql"]
    wf = [c for c in cql if isinstance((c.get("args") or {}).get("query"), str) and c["args"]["query"].strip()]
    empty = [c for c in calls if not (set((c.get("args") or {}).keys()) - {"corpus_id"})]
    argerr = [c for c in calls if c.get("ok") is False and re.search(
        r"missing|required|argument|unexpected keyword|validation|invalid param", str(c.get("error", "")), re.I)]
    parse_err = [c for c in cql if c.get("ok") is False and re.search(r"position|parse|unexpected character", str(c.get("error", "")), re.I)]
    relay = bool(re.search(r"error|invalid|pars|syntax|unexpected|malformed|not valid|unable|could not|couldn't|fail", ans, re.I))
    print(f"  tool calls: {[(c.get('name'), (c.get('args') or {}).get('query'), c.get('ok'), c.get('error')) for c in calls]}")
    print(f"  answer ({len(ans)} chars): {ans[:400]!r}")
    print(f"  http_status={r.get('http_status')} error={r.get('error')}")
    if r.get("error") or r.get("http_status"): why.append(f"record errored ({r.get('http_status')} {str(r.get('error'))[:80]})")
    if not wf: why.append("no search_cql call with a non-empty query string (no well-formed tool call)")
    if empty: why.append(f"{len(empty)} tool call(s) arrived with empty arguments (silently {{}} in the engine)")
    if argerr: why.append(f"{len(argerr)} malformed-argument rejection(s)")
    if wf and not parse_err: why.append("no CQL parse error from the engine (the model altered the query?): needs a human read")
    if not ans: why.append("empty answer")
    elif not relay: why.append("answer does not appear to relay the CQL error: needs a human read")
ok = not why
print("  PROBE-G076 GATE:", "PASS" if ok else "FAIL")
for w in why: print("   -", w)
sys.exit(0 if ok else 6)
PY
  local rc=$?
  if [ "$rc" -eq 0 ]; then gate_note 3 PASS "probe-g076"; else
    gate_note 3 FAIL "probe-g076 rc=$rc"
    say "  The checks are heuristics. Before switching arms, send me $RUNS/${TAG}_probe_g076.json."
  fi
  return $rc
}

# Gate 5 (plan v1 section 5.5). G-004 is a no_tool trap: no tool call is CORRECT there.
step_probe5() {
  say "== probe5 (gate 5): 5-question harness probe (protocol check, not a result) =="
  plan_guard || return 1
  mkdir -p "$LOGDIR"; step_warm || return 1
  local out="eval/runs/${TAG}_probe.json" log="$LOGDIR/${TAG}_probe.log"
  keep_prev "$REPO/engine/$out"
  harness "$out" "$log" G-001 G-002 G-003 G-004 G-005
  [ "$DRYRUN" = 1 ] && return 0
  shard_stats "$REPO/engine/$out"
  py - "$REPO/engine/$out" <<'PY'
import json, sys
R = {r["id"]: r for r in json.load(open(sys.argv[1]))["results"]}
for i in ("G-001", "G-002", "G-003", "G-004", "G-005"):
    r = R.get(i) or {}
    print(f"  {i}: answered={bool((r.get('answer') or '').strip())} tool_calls={len(r.get('tool_calls') or [])} "
          f"wall_s={round((r.get('wall_ms') or 0)/1000)} err={r.get('error')}")
ans = sum(1 for i in R if (R[i].get("answer") or "").strip())
tc = [i for i in ("G-001", "G-002", "G-003", "G-005") if (R.get(i) or {}).get("tool_calls")]
ok = ans >= 4 and len(tc) >= 3
print(f"  PROBE5 GATE: answered={ans}/5 (need >=4); tool call in {len(tc)}/4 of G-001,G-002,G-003,G-005 (need >=3) ->", "PASS" if ok else "FAIL")
print("  (G-004 is the capability-gap trap: no tool call + an explicit unavailability statement is correct and not gated)")
sys.exit(0 if ok else 5)
PY
  local rc=$?
  if [ "$rc" -eq 0 ]; then gate_note 5 PASS "probe5"; else gate_note 5 FAIL "probe5 rc=$rc"; fi
  return $rc
}

step_rep() {
  local n="${1:-}"; [[ "$n" =~ ^[123]$ ]] || { bad "usage: rep 1|2|3"; return 1; }
  plan_guard || return 1
  [ "$DRYRUN" = 1 ] || gate_guard || return 1
  mkdir -p "$LOGDIR"
  local stem="${TAG}_r${n}" log="$LOGDIR/${TAG}_r${n}.log" s
  note "rep $n start ($stem)"
  step_warm || return 1
  for s in 1 2 3 4; do
    run_shard "$stem" "$s" "$log" || { note "rep $n shard $s FAILED"; return 1; }
    if [ "$n" = 1 ] && [ "$s" = 1 ] && [ "$DRYRUN" != 1 ]; then
      py - "$REPO/engine/eval/runs/${stem}_shard1.json" <<'PY' || { note "ABORT RULE hit after rep1 shard1"; say "ABORT RULE: stop here and disclose (plan section 6). Send me the shard file."; return 3; }
import json, sys
R = json.load(open(sys.argv[1]))["results"]
na = sum(1 for r in R if not (r.get("answer") or "").strip()); tc = sum(1 for r in R if r.get("tool_calls"))
print(f"  abort-rule check: no_answer={na} (stop at >=10), with_tool_call={tc} (stop at <5)")
sys.exit(1 if (na >= 10 or tc < 5) else 0)
PY
    fi
  done
  local t; t=$(trunc_count)
  say "  truncation gate after rep $n: $t matching log lines (must be 0)"
  [ "$t" = 0 ] && ok "no truncation" || warn "truncation lines found - do NOT ignore; tell me"
  note "rep $n done, truncation_lines=$t"
}

step_all() {
  local r
  for r in 1 2 3; do step_rep "$r" || { say "stopped at rep $r"; return 1; }; done
  say "all repetitions finished: $(utc). Next: rescue (only for transport-errored records), evidence, validate, manifest."
}

step_status() {
  say "== status $(utc) =="
  api_up && say "server: up ($(curl -fsS --noproxy '*' "$OLLAMA_URL/api/version"))" || say "server: DOWN"
  ollama ps 2>&1 | sed 's/^/  /'
  local f; for f in "$RUNS/${TAG}"_r[123]_shard[1-4].json; do [ -f "$f" ] && shard_stats "$f"; done
  say "  shard files complete: $(ls "$RUNS/${TAG}"_r[123]_shard[1-4].json 2>/dev/null | wc -l)/12"
  say "  truncation lines in run segments: $(trunc_count) ('truncated = 1': $(count_pat 'truncated = 1'))"
  local lg; lg=$(ls -t "$LOGDIR/${TAG}"_r[123].log 2>/dev/null | head -1)
  [ -n "$lg" ] && { say "  last lines of $(basename "$lg"):"; tail -4 "$lg" | cut -c1-160 | sed 's/^/     /'; }
  say "  gates: 1=$(gate_status 1) 2=$(gate_status 2) 3=$(gate_status 3) 4=$(gate_status 4) 5=$(gate_status 5)"
}

# One rescue attempt per transport-errored record (qwen-arm rule, plan v1 section 3).
step_rescue() {
  local id="${1:-}" n="${2:-}"
  [[ "$id" =~ ^G-(0[0-7][0-9]|080)$ && "$id" != G-000 ]] || { bad "usage: rescue G-0NN <rep 1|2|3>"; return 1; }
  [[ "$n" =~ ^[123]$ ]] || { bad "usage: rescue G-0NN <rep 1|2|3>"; return 1; }
  plan_guard || return 1
  [ "$DRYRUN" = 1 ] || gate_guard || return 1
  local num=$((10#${id#G-})) s stem="${TAG}_r${n}" f out log
  s=$(( (num - 1) / 20 + 1 ))
  f="$RUNS/${stem}_shard${s}.json"; out="eval/runs/${stem}_rescue_${id}.json"; log="$LOGDIR/${stem}_rescue.log"
  [ -f "$f" ] || { bad "no shard file $f yet: finish the repetition first (rescues run after the repetition)"; return 1; }
  local k; for k in 1 2 3 4; do [ -f "$RUNS/${stem}_shard${k}.json" ] || { bad "repetition $n is not complete (shard $k missing)"; return 1; }; done
  [ -e "$REPO/engine/$out" ] && { bad "a rescue for $id in rep $n already exists ($out): one attempt per record - stop and disclose"; return 1; }
  py - "$f" "$id" <<'PY' || { bad "$id in rep $n is not a transport-errored record (answer present): a rescue is NOT allowed"; return 1; }
import json, sys
R = {r["id"]: r for r in json.load(open(sys.argv[1]))["results"]}
r = R.get(sys.argv[2])
if r is None: print("  record not found"); sys.exit(2)
errored = not (r.get("answer") or "").strip()
print(f"  original record: answer_empty={errored} http_status={r.get('http_status')} wall_s={round((r.get('wall_ms') or 0)/1000)} error={str(r.get('error'))[:120]}")
sys.exit(0 if errored else 1)
PY
  mkdir -p "$LOGDIR"; step_warm || return 1
  note "rescue $id rep $n start"
  harness "$out" "$log" "$id"
  local rc=$?
  [ "$DRYRUN" = 1 ] && return 0
  shard_stats "$REPO/engine/$out"
  note "rescue $id rep $n done rc=$rc (applied to the merge only if the original was errored AND this re-run is clean; both attempts kept)"
  return $rc
}

step_mark_failed() {
  local fn="${1:-}"
  [[ "$fn" =~ ^${TAG}_r[123]_shard[1-4]\.json$ ]] || { bad "usage: mark-failed ${TAG}_rN_shardK.json  (file name inside $RUNS)"; return 1; }
  [ -f "$RUNS/$fn" ] || { bad "no such file: $RUNS/$fn"; return 1; }
  local dst="$RUNS/${fn%.json}.FAILED.json"
  [ -e "$dst" ] && dst="${dst%.json}.$(date -u +%Y%m%dT%H%M%S).json"
  mv "$RUNS/$fn" "$dst" && ok "renamed to $(basename "$dst") (kept, never deleted)"
  note "protocol violation: $fn renamed to $(basename "$dst"); reason must be written to notes.txt by the operator"
  say "  now add one line to $WORK/notes.txt saying WHY (host sleep, server crash, ...), then re-run: bash cm_arm.sh rep N"
}

copy_immutable() {   # $1 src, $2 dst ; never overwrites a different file
  local src="$1" dst="$2"
  if [ -e "$dst" ]; then cmp -s "$src" "$dst" || bad "$(basename "$dst") already in results folder and differs from $src"; return 0; fi
  cp "$src" "$dst"
}

step_evidence() {
  say "== evidence: collect everything into $RES =="
  mkdir -p "$RES/logs" "$RES/evidence" "$RES/rescues" "$RES/failed_attempts" "$EVID"
  local f
  for f in "$RUNS/${TAG}"_r[123]_shard[1-4].json "$RUNS/${TAG}_probe.json"; do
    [ -f "$f" ] && copy_immutable "$f" "$RES/$(basename "$f")"
  done
  for f in "$RUNS/${TAG}_probe_g076.json" "$RUNS/${TAG}"_probe*.attempt-*.json; do
    [ -f "$f" ] && copy_immutable "$f" "$RES/evidence/$(basename "$f")"     # gate probes live in evidence/, not at top level
  done
  for f in "$RUNS/${TAG}"_r[123]_rescue_G-*.json; do [ -f "$f" ] && copy_immutable "$f" "$RES/rescues/$(basename "$f")"; done
  for f in "$RUNS/${TAG}"_r[123]_shard[1-4].FAILED*.json; do [ -f "$f" ] && copy_immutable "$f" "$RES/failed_attempts/$(basename "$f")"; done
  cp "$LOGDIR/${TAG}"_*.log "$RES/logs/" 2>/dev/null
  cp "$LOGDIR"/ollama_server_seg*.log "$RES/evidence/" 2>/dev/null     # same place the qwen arm keeps its server logs
  cp "$LOGDIR"/selftest_server.log* "$RES/evidence/" 2>/dev/null
  { echo "# host snapshot $(utc)"; uname -a; lscpu; free -h; cat /etc/os-release; echo; ollama ps; } >"$RES/evidence/host_snapshot.txt" 2>&1
  "$REPO/.venv/bin/pip" freeze >"$RES/evidence/pip_freeze.txt" 2>&1
  { echo "commit: $(git -C "$REPO" rev-parse HEAD)"; echo "describe: $(git -C "$REPO" describe --tags 2>&1)"
    echo "status:"; git -C "$REPO" status --porcelain; } >"$RES/evidence/repo_state.txt"
  cp "$0" "$RES/evidence/cm_arm.sh" 2>/dev/null
  cp "$WORK/notes.txt" "$RES/evidence/notes.txt" 2>/dev/null
  cp "$WORK"/plan_check/sha256.txt "$RES/evidence/plan_sha256.txt" 2>/dev/null
  cp "$WORK"/plan_check/plan_commits.txt "$RES/evidence/plan_commits.txt" 2>/dev/null
  cp "$EVID"/* "$RES/evidence/" 2>/dev/null
  local t a b
  t=$(trunc_count); a=$(count_pat 'truncated = 1'); b=$(count_pat 'truncating input prompt')
  { echo "truncation gate over RUN server segments only (ollama_server_seg*.log; the self-test log is excluded):"
    echo "  'truncated = 1'            : $a   (plan / qwen-precedent pattern; must be 0)"
    echo "  'truncating input prompt'  : $b   (additional, stricter pattern; must be 0)"
    echo "  total                      : $t"; } >"$RES/evidence/truncation_gate.txt"
  cat "$RES/evidence/truncation_gate.txt"
  py - "$OLLAMA_URL" "$MODEL" "$RES/evidence" "$SLUG" "$CTX" "$OLLAMA_PIN" <<'PY' || warn "could not write the env JSON (model not pulled / server down?)"
import json, subprocess, sys, urllib.request, datetime
base, model, outdir, slug, ctx, pin = sys.argv[1:7]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
req = urllib.request.Request(base + "/api/show", data=json.dumps({"model": model}).encode(),
                             headers={"Content-Type": "application/json"})
show = json.load(opener.open(req, timeout=60)); det = show.get("details", {})
tags = json.load(opener.open(base + "/api/tags", timeout=60))
full = next((m.get("digest") for m in tags.get("models", []) if m.get("name") == model), None)
ls = subprocess.run(["ollama", "ls"], capture_output=True, text=True).stdout
row = next((l.split() for l in ls.splitlines() if l.startswith(model)), [])
mi = show.get("model_info") or {}
env = {"utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
       "ollama_version": subprocess.run(["ollama", "--version"], capture_output=True, text=True).stdout.strip().splitlines()[-1],
       "install_pin": pin, "model": model,
       "config_digest": row[1] if len(row) > 1 else None, "config_digest_source": "ollama ls (short id)",
       "full_digest": full, "full_digest_source": "/api/tags",
       "family": det.get("family"), "parameter_size": det.get("parameter_size"),
       "quantization_level": det.get("quantization_level"), "capabilities": show.get("capabilities"),
       "model_context_length": next((v for k, v in mi.items() if k.endswith(".context_length")), None),
       "context": {"OLLAMA_CONTEXT_LENGTH_env": int(ctx),
                   "note": "v2.0.2 engine does not expose num_ctx; the server-side default governs truncation"}}
for name in ("ollama_env.json", f"env_{slug}.json"):
    json.dump(env, open(f"{outdir}/{name}", "w"), indent=1)
print("  wrote ollama_env.json and env_%s.json (digest %s, quantisation %s)" % (slug, env["config_digest"], env["quantization_level"]))
PY
  find "$RES" -type f | sed "s|$RES/||" | sort | sed 's/^/     /'
  [ "$FAILS" -eq 0 ] || return 1
}

patch_validator() {
  # The committed validator crashes on list-valued gold numbers (G-018, G-023: per-part
  # frequencies) in its independent re-score. Idempotent one-block fix; the repo
  # scorer (eval.score) is NOT touched. Disclose this in the README/notes.
  py - "$MAIN/scripts/validate_user_run.py" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
old = '        required = [g["value"] for g in q.get("gold", {}).get("numbers", [])]\n'
new = ('        required: list[float] = []\n'
       '        for g in q.get("gold", {}).get("numbers", []):\n'
       '            val = g["value"]\n'
       '            if isinstance(val, list):  # e.g. G-018/G-023 per-part frequencies\n'
       '                required.extend(float(t) for t in val)\n'
       '            else:\n'
       '                required.append(float(val))\n')
if s.count(old) == 1:
    open(p, "w").write(s.replace(old, new)); print("  validator patched (list-valued gold numbers)")
elif "isinstance(val, list)" in s:
    print("  validator already patched / fixed upstream")
else:
    print("  WARNING: validator text differs from what I expected - tell me"); sys.exit(1)
PY
}

step_validate() {
  say "== validate: merge + score + flips vs the CI arms =="
  [ -d "$RES" ] || { bad "run 'evidence' first"; return 1; }
  patch_validator || return 1
  mkdir -p "$RES/evidence"
  git -C "$MAIN" diff -- scripts/validate_user_run.py >"$RES/evidence/validator_patch.diff" 2>/dev/null   # disclosure of the local fix
  # the validator globs *.json at the top level: a manifest.json from an earlier run would be read as a run
  [ -f "$RES/manifest.json" ] && { mv "$RES/manifest.json" "$WORK/manifest.json.prev.$(date -u +%H%M%S)"; say "  (earlier manifest.json moved to $WORK; 'manifest' regenerates it)"; }
  local args=() a
  for a in "${CI_ARMS[@]}"; do args+=(--ci-arm "$a"); done
  # --data-dir MUST be absolute: the scorer subprocess runs with cwd=engine/
  ( cd "$MAIN" && "$REPO/.venv/bin/python" scripts/validate_user_run.py \
      --data-dir "$RES" --engine-dir "$REPO/engine" --repo "$MAIN" \
      --expect-ids-full G-001..G-080 --probe-ids G-001..G-005 "${args[@]}" ) 2>&1 | tee "$WORK/validator_log.txt"
  local rc=${PIPESTATUS[0]}
  cp "$WORK/validator_log.txt" "$RES/evidence/validator_log.txt"
  rm -f "$RES/MANIFEST.json"   # committed convention is manifest.json (next step)
  say "  validator exit code: $rc (0 = structural checks passed)"
  if [ "$rc" -eq 0 ] && grep -q 'STRUCTURAL: PASS' "$WORK/validator_log.txt"; then ok "STRUCTURAL: PASS"
  else bad "validator did not pass - do not upload; send me $WORK/validator_log.txt"; return 1; fi
}

step_manifest() {
  say "== manifest =="
  [ -d "$RES" ] || { bad "no results folder"; return 1; }
  ( cd "$MAIN" && "$REPO/.venv/bin/python" benchmarks/scripts/make_manifest.py \
      "benchmarks/results/user-wsl2-$SLUG-$CTX" \
      --run-url "local://Waleed-Desktop/WSL2-Ubuntu24.04-tierB-user-run" --commit "$COMMIT" )
  ls -la "$RES/manifest.json"
}

step_upload_list() {
  say "== upload =="
  say "Folder to upload (Windows path): $(wslpath -w "$RES" 2>/dev/null || echo "$RES")"
  say "Files: $(find "$RES" -type f | wc -l)   (GitHub web upload: max 100 files per commit, 25 MB per file)"
  local d; for d in "$RES"/*/; do say "   $(basename "$d")/: $(find "$d" -type f | wc -l) files"; done
  say "Largest files:"; find "$RES" -type f -printf '%s %p\n' | sort -rn | head -5 | awk '{printf "  %.1f MB  %s\n",$1/1048576,$2}'
  [ -d "$WORK/qwen_meta" ] && say "Also upload: $WORK/qwen_meta/*  ->  benchmarks/results/user-wsl2-7b-16384/evidence/"
}

main() {
  local step="${1:-}"; shift || true
  case "$step" in
    prep) step_prep ;; serve) step_serve ;; pull) step_pull ;; qwen-meta) step_qwen_meta ;;
    probe0) step_probe0 ;; trunc-selftest) step_trunc_selftest ;; probe-g076) step_probe_g076 ;;
    probe5) step_probe5 ;; warm) step_warm ;;
    all) step_all ;; rep) step_rep "${1:-}" ;; status) step_status ;;
    rescue) step_rescue "${1:-}" "${2:-}" ;; mark-failed) step_mark_failed "${1:-}" ;;
    evidence) step_evidence ;; validate) step_validate ;; manifest) step_manifest ;; upload-list) step_upload_list ;;
    *) sed -n '2,37p' "$0"; return 2 ;;
  esac
}
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then main "$@"; fi
