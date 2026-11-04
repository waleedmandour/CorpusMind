#!/usr/bin/env bash
# =============================================================================
# CorpusMind - Tier B user-run provenance, v2.1 (2026-11-05)
#
# What it does, in order:
#   0. syncs latest main  (brings down the analysis figures/docs bundle ef7e3e0);
#      any uncommitted/staged changes are auto-stashed first (recoverable)
#   1. auto-locates the folder holding your collected evidence files
#      (~/tierb_evidence is checked first)
#   2. saves them into benchmarks/results/user-wsl2-7b-16384/evidence/
#      (host_snapshot.txt is regenerated on this machine if absent)
#   3. verifies ollama_env.json (pinned 0.40.13 + context 16384)
#   4. re-runs the truncation gate on the three server-log segments
#   5. runs the repo validator (STRUCTURAL gate)
#   6. regenerates the full-folder manifest.json (supersedes old MANIFEST.json)
#   7. appends the README provenance note
#   8. review -> commit -> push (token typed once, hidden, never stored)
#
# Run INSIDE WSL2:   bash scripts/user_run_provenance.sh   (from any directory)
# Ollama server window: keep it open and idle (only needed if Stage 3 must
#                       re-record the env file).
#
# If the evidence folder is not auto-detected, run:
#   EVDIR=/path/to/folder bash scripts/user_run_provenance.sh
# =============================================================================
set -euo pipefail

REPO="${REPO:-$HOME/CorpusMind}"
EVDIR="${EVDIR:-}"                                          # empty = auto-detect
DATA="benchmarks/results/user-wsl2-7b-16384"
ENGINE_COMMIT="5a5e43fa0c9e6a903dc06f79579b732a9f666bca"    # commit under test (v2.0.2 tag)

# --- Stage 0: sync (repo is public; clean URL first so no stale creds break it)
echo "== Stage 0: sync =="
cd "$REPO"
git remote set-url origin https://github.com/waleedmandour/CorpusMind.git
if [ -n "$(git status --porcelain)" ]; then
  echo "NOTE: uncommitted/staged changes found - auto-stashing them (recoverable, nothing is lost)"
  git status --short | head -20
  git stash -u -m "pre-provenance auto-stash $(date -u +%F)"
  echo "inspect later with: git stash list ; git stash show -p stash@{0}"
fi
if ! git pull --rebase origin main; then
  echo "FAIL: pull --rebase did not complete."
  echo "  Run: git status   (inspect / stash local edits: git stash -u), then re-run."
  exit 1
fi
test -d "$DATA" || { echo "FAIL: $DATA missing"; exit 1; }
if [ -d "$DATA/analysis/figures" ]; then
  echo "OK: analysis bundle present ($(ls "$DATA/analysis/figures" | wc -l) figure files on your machine)"
else
  echo "WARN: analysis bundle not found - check the Stage 0 pull output"
fi

# --- Stage 1: locate the collected evidence folder ----------------------------
echo "== Stage 1: locate evidence folder =="
if [ -z "$EVDIR" ]; then
  for c in "$HOME/tierb_evidence" "$HOME/evidence-stage" "$HOME/evidence" \
           "$HOME/Downloads/evidence" "$HOME/Downloads" "$HOME/Desktop" "$HOME"; do
    if [ -f "$c/ollama_env.json" ] && compgen -G "$c/ollama_server*" >/dev/null; then
      EVDIR="$c"; break
    fi
  done
fi
[ -n "$EVDIR" ] || { echo "FAIL: evidence folder not found. Re-run with: EVDIR=/path/to/folder bash $0"; exit 1; }
echo "evidence source: $EVDIR"
ls -la "$EVDIR"

# --- Stage 2: save the evidence files into the repo folder --------------------
echo "== Stage 2: save evidence =="
mkdir -p "$DATA/evidence"
for f in env_qwen2.5-7b.json ollama_env.json pip_freeze.txt; do
  if [ -f "$EVDIR/$f" ]; then cp -v "$EVDIR/$f" "$DATA/evidence/"; else echo "note: $f not present in $EVDIR (skipped)"; fi
done
cp -v "$EVDIR"/ollama_server* "$DATA/evidence/"
if [ ! -f "$DATA/evidence/host_snapshot.txt" ]; then
  { uname -a; lscpu 2>/dev/null | head -30; free -h; cat /etc/os-release; } \
    > "$DATA/evidence/host_snapshot.txt"
  echo "generated $DATA/evidence/host_snapshot.txt (was not in your collected set)"
fi
ls -la "$DATA/evidence/"

# --- Stage 3: verify ollama_env.json (pin + context window) -------------------
echo "== Stage 3: verify ollama_env.json =="
E="$DATA/evidence/ollama_env.json"
if grep -q '0\.40\.13' "$E" && grep -q '16384' "$E"; then
  echo "OK: pinned 0.40.13 + 16384 present in the collected env file"
else
  echo "WARN: pin/context not found - re-record from the live server."
  echo "      Confirm the Ollama server window is open and idle, then press Enter."
  read -r _
  OLLAMA_CONTEXT_LENGTH=16384 python3 scripts/record_ollama_env.py \
    --model qwen2.5:7b --pin 0.40.13 --out "$E"
  grep -q '0\.40\.13' "$E" && grep -q '16384' "$E" \
    || { echo "FAIL: re-recorded env file still missing pin/context"; exit 1; }
fi

# --- Stage 4: truncation gate --------------------------------------------------
echo "== Stage 4: truncation gate =="
tot=$(cat "$DATA/evidence"/ollama_server* | grep -c 'truncated = 1' || true)
echo "truncated-prompts total: $tot"
[ "$tot" = "0" ] || { echo "FAIL: gate nonzero - stop and investigate before committing"; exit 1; }

# --- Stage 5: repo validator (STRUCTURAL gate; also refreshes merged/) ---------
echo "== Stage 5: validate_user_run =="
python3 scripts/validate_user_run.py --data-dir "$DATA" --engine-dir engine --repo . \
  --ci-arm 41306198564 --ci-arm 41306208341 --ci-arm 41306203484 2>&1 | tee /tmp/cm_validate.log
grep -q "STRUCTURAL: PASS" /tmp/cm_validate.log \
  || { echo "FAIL: validator did not pass - do not commit"; exit 1; }

# --- Stage 6: full-folder manifest ----------------------------------------------
echo "== Stage 6: manifest =="
python3 benchmarks/scripts/make_manifest.py "$DATA" \
  --run-url "local://Waleed-Desktop/WSL2-Ubuntu24.04-tierB-user-run" \
  --commit "$ENGINE_COMMIT"
if [ -f "$DATA/MANIFEST.json" ]; then
  # -f is required: the Stage 5 validator rewrites MANIFEST.json on every pass,
  # so git always sees it as locally modified here. It is superseded by the
  # full-folder manifest.json generated above.
  git rm -qf "$DATA/MANIFEST.json"
fi
ls -la "$DATA/manifest.json"

# --- Stage 7: README provenance note (idempotent) -------------------------------
grep -q "Provenance update (2026-11-05)" "$DATA/README.md" || cat >> "$DATA/README.md" <<'EOF'

## Provenance update (2026-11-05)

- `evidence/` completed: `ollama_env.json` + `env_qwen2.5-7b.json` (pinned
  Ollama 0.40.13, OLLAMA_CONTEXT_LENGTH=16384; server install unchanged since
  the runs), `pip_freeze.txt`, `host_snapshot.txt`, and the three
  `ollama_server` log segments (truncation gate re-checked after copy: 0
  matches for `truncated = 1`).
- `merged/`: repo-scored per-rep merges from `scripts/validate_user_run.py`
  (gold 480f5230...; STRUCTURAL: PASS).
- `analysis/`: faithful analysis bundle incl. the pre-registered 3b context
  contrast (pinned 4k control `run-41306198564` vs 16384 `run-41306203484`):
  exact McNemar p = 0.00258 (Holm-adjusted; single executed test in the
  declared family).
- `manifest.json` regenerated over the full folder with
  `benchmarks/scripts/make_manifest.py` (commit-under-test 5a5e43fa...);
  supersedes the earlier partial `MANIFEST.json` (probe-stage files only).
EOF

# --- Stage 8: review, commit, push ----------------------------------------------
echo "== Stage 8: commit + push =="
git add -A
if git diff --cached --quiet; then
  echo "Nothing to commit (already pushed on a previous run) - DONE."
  exit 0
fi
git status --short
read -r -p "Commit and push the files above? [y/N] " ans
[ "$ans" = "y" ] || { echo "Aborted - nothing committed (evidence stays saved in $DATA/evidence)."; exit 0; }
read -rsp 'GitHub token (input hidden): ' GH_TOKEN; echo
git commit -q -m "data(bench): user-wsl2-7b-16384 provenance evidence + full-folder manifest.json

- evidence/: ollama_env.json + env_qwen2.5-7b.json (pinned 0.40.13, ctx 16384),
  pip_freeze.txt, host_snapshot.txt, ollama_server log segments (gate: 0)
- manifest.json regenerated over the full folder (make_manifest.py,
  commit-under-test 5a5e43fa); supersedes partial MANIFEST.json"
if ! git push https://x-access-token:${GH_TOKEN}@github.com/waleedmandour/CorpusMind.git main; then
  echo "FAIL: push rejected. If the error is 403, the token lacks 'Contents: Read and write'."
  unset GH_TOKEN
  exit 1
fi
unset GH_TOKEN
echo "DONE - provenance is on the repo. Manuscript figures: $DATA/analysis/figures/"
echo "SECURITY: revoke/rotate this token at https://github.com/settings/tokens (it was shared in chat)."
