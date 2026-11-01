#!/usr/bin/env bash
# Dispatch a CorpusMind Gemini crawl slice on bench/freeze-1 with the frozen row params.
# Usage: GH_TOKEN=... dispatch_crawl.sh G-004 G-040 ...
# Refuses to dispatch if any run is in flight on the ref (cancel hazard).
set -euo pipefail
REPO="waleedmandour/CorpusMind"
REF="bench/freeze-1"
WF="benchmarks.yml"
: "${GH_TOKEN:?export GH_TOKEN first}"
IDS="$*"
[ -n "$IDS" ] || { echo "usage: dispatch_crawl.sh <ids...>" >&2; exit 2; }

api() { curl -s -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" "$@"; }

# 1. poll: refuse if anything is queued/in_progress on this ref
busy=$(api "https://api.github.com/repos/$REPO/actions/runs?branch=$REF&status=queued" | python3 -c 'import json,sys;print(json.load(sys.stdin)["total_count"])')
busy2=$(api "https://api.github.com/repos/$REPO/actions/runs?branch=$REF&status=in_progress" | python3 -c 'import json,sys;print(json.load(sys.stdin)["total_count"])')
if [ "$busy" != "0" ] || [ "$busy2" != "0" ]; then
  echo "REF BUSY (queued=$busy in_progress=$busy2) — NOT dispatching" >&2; exit 3
fi

# 2. dispatch with the frozen crawl params (see bench-state/STATE.md §2)
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
  -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$REPO/actions/workflows/$WF/dispatches" -d @- <<JSON
{"ref":"$REF","inputs":{"run_grounding":true,"grounding_provider":"cloud","cloud_vendor":"gemini","grounding_model":"gemini-3.8-flash","reasoning_effort":"low","grounding_pause":"2","grounding_timeout":"600","grounding_chat_deadline_s":"600","debug_raw":false,"commit_results":false,"grounding_only":"$IDS"}}
JSON
)
[ "$code" = "204" ] || { echo "dispatch failed HTTP $code" >&2; exit 4; }
sleep 10

# 3. report the new run id
api "https://api.github.com/repos/$REPO/actions/runs?branch=$REF&per_page=1" \
  | python3 -c 'import json,sys;r=json.load(sys.stdin)["workflow_runs"][0];print("run",r["id"],"|",r["head_sha"][:7],"|",r["status"],"|",r["created_at"])'
