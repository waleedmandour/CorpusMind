#!/usr/bin/env bash
# CI source guards (v1.2.10) — the two "quiet regression" bug classes that
# reviews keep re-finding, institutionalized as grep gates so they cannot
# come back unnoticed. Cheap (pure grep, no Python env needed).
#
# Guard 1 — positional-index lookups in registry code.
#   The v1.2.7 USAS bug: a structured-entry list addressed as list[-1],
#   silently returning the wrong entry when the list layout changed.
#   String-split tails (foo.rsplit(".", 1)[-1]) are idiomatic and allowed —
#   the filter drops any line that got its index from a split/rsplit.
#   Scope: the registry/catalogue modules where structured lookups live.
#
# Guard 2 — raw model-name compares.
#   canonical_model_name (strict, catalogue) and model_name_matches
#   (tolerant, capability probes) in ai/providers.py are the ONLY two
#   places that may define model-name matching semantics. A re-inlined
#   `split(":")[0] ==` compares around the colon instead of the implicit
#   tag and drifts from both. All three historical sites were converted to
#   the helpers in v1.2.10; the guard keeps it that way.
#
# Usage: scripts/ci_source_guards.sh   (repo root cwd; exits 1 on violation)
set -euo pipefail

fail=0

echo "[guards] 1. positional-index lookups in registry code (excluding split-derived tails)"
# shellcheck disable=SC2086
hits1=$(grep -RInE '\[-[0-9]+\]' \
    engine/discourse engine/ai engine/reference_corpus engine/nlp \
    engine/app engine/semantic engine/stats engine/learner engine/multimodal \
    --include='*.py' 2>/dev/null \
    | grep -v '/tests/' \
    | grep -v 'split(' || true)
if [ -n "$hits1" ]; then
  echo "[guards] FAIL: positional-index lookup(s) — use a keyed dict/lookup, not list[-1]:"
  echo "$hits1"
  fail=1
else
  echo "[guards] OK   no positional-index lookups"
fi

echo "[guards] 2. raw model-name compares (must go through ai.providers helpers)"
hits2=$(grep -RInE 'split\(":"\)\[0\][[:space:]]*==|==[[:space:]]*[A-Za-z_][A-Za-z0-9_.]*\.split\(":"\)\[0\]' \
    engine \
    --include='*.py' 2>/dev/null \
    | grep -v '/tests/' || true)
if [ -n "$hits2" ]; then
  echo "[guards] FAIL: raw model-name compare(s) — use ai.providers.canonical_model_name (strict) or model_name_matches (tolerant):"
  echo "$hits2"
  fail=1
else
  echo "[guards] OK   no raw model-name compares"
fi

if [ "$fail" -ne 0 ]; then
  echo "[guards] FAIL"
  exit 1
fi
echo "[guards] PASS"
