# CorpusMind benchmark battery

Manuscript-facing benchmarks. Every number reported in the tool paper's
evaluation section is produced by one of the three pieces below, on a
standardized GitHub Actions runner, from a pinned commit, with machine-readable
artifacts and a full provenance trail — so a reviewer can re-run and confirm
each table independently.

| # | Piece | What it measures | Where |
|---|---|---|---|
| 1 | **Arabic pipeline throughput** | The real production path — `analyze_arabic` (CAMeL calima-msa-r13 morphology) and `identify_arabic_dialect` (DIDModel6) — at corpus scale: tokens/s, spread over repetitions, projections to 500K/1M tokens. Motivates the default `CORPUSMIND_ARABIC_TIMEOUT_S`. | `scripts/benchmark_arabic_corpus.py`, job `perf-arabic` |
| 2 | **Arabic sentence segmentation vs AraSEG** | Intrinsic boundary P/R/F1 against the AraSEG shared-task dev splits (PA, NP), macro-averaged per the shared-task protocol; plus the extrinsic deltas through the real engine (KWIC, collocations, n-grams, CQL scope, sentiment, CAF, Gale–Church). | `engine/eval/segmentation_*.py`, job `seg-araseg` |
| 3 | **Assistant grounding fidelity** | Whether every number the AI assistant quotes comes from a real tool output on the fixed snapshot (80-question bank with traps; bootstrap CIs). | `engine/eval/run_grounding.py` + `score.py`, job `grounding` (dispatch-only) |

Workflow: [`.github/workflows/benchmarks.yml`](../.github/workflows/benchmarks.yml)
— runs automatically on PRs touching the benchmark/eval code, and via
**workflow_dispatch** for the citable manuscript runs.

## Provenance rules (what makes a number citable)

1. **Pinned commit** — the workflow always runs on a specific commit; every
   result JSON carries `_meta.commit` and the run URL is derivable from
   `_meta.github`.
2. **Pinned data** — AraSEG parquet splits are downloaded and verified against
   `benchmarks/data/araseg_sha256.txt`; a checksum mismatch fails the job
   instead of silently evaluating a new data snapshot. The grounding gold is
   frozen in `engine/eval/data/gold/` with the same discipline.
3. **Environment recorded** — runner platform, CPU count, Python and
   camel-tools versions, exact command, UTC time: all inside `_meta`.
4. **Repetitions, not single runs** — throughput numbers report every
   repetition plus median/min/max/CV%. CI runners are standardized but shared;
   we show the variance rather than hide it.
5. **Committed snapshots** — a dispatched run with `commit_results=true`
   commits artifacts under `benchmarks/results/run-<id>/` together with a
   `manifest.json` (run URL, commit, sha256 of every file). The manuscript
   cites that run URL + manifest checksums.

## Reproducing locally

```bash
# environment (mirrors CI)
python -m venv .venv && . .venv/bin/activate        # Python 3.12
pip install -e "./engine[dev]" python-multipart cryptography \
    camel-tools docopt pyrsistent muddler emoji pyarrow
camel_data -i morphology-db-msa-r13 && camel_data -i dialectid-model6

# 1. throughput
python scripts/benchmark_arabic_corpus.py --sizes 20000,100000 --reps 3 \
    --label local --out /tmp/perf.json

# 2. segmentation (fetch + verify + convert + evaluate)
bash benchmarks/scripts/fetch_araseg.sh /tmp/araseg
python benchmarks/scripts/araseg_parquet_to_jsonl.py \
    --parquet /tmp/araseg/PA_dev.parquet --out /tmp/araseg/PA/dev.jsonl
cd engine
python -m eval.segmentation_araseg --data /tmp/araseg/PA/dev.jsonl --task PA
python -m eval.segmentation_downstream --data /tmp/araseg/PA/dev.jsonl --limit 5

# 3. grounding (needs any OpenAI-compatible provider configured)
python -m eval.run_grounding --provider ollama --out runs/paper_run.json
python -m eval.score runs/paper_run.json --out runs/paper_report.json --verbose
```

## Known caveats (stated up front)

- **Throughput is steady-state on repetitive text.** The benchmark corpus
  repeats 8 fixed sentences (mixed MSA/Gulf/Egyptian/Levantine); after the
  2K-token warmup the morphology cache is warm, so tokens/s measures
  production-path throughput for repetitive classroom corpora, not cold-cache
  cost. `_meta.unique_input_tokens` records the vocabulary size of every input.
- **CI runners are shared infrastructure.** Absolute times vary run to run;
  the battery therefore reports repetitions and CV%. Relative comparisons
  (e.g. morphology vs dialect-ID cost) are stable.
- **Grounding runs are provider-dependent.** The CI job only runs when
  dispatched with a provider configured (`CORPUSMIND_CLOUD_*` secrets);
  without a real LLM the offline suite (`tests/test_eval_grounding.py`)
  validates the harness mechanics only. Report the provider, model, and
  dispatch date next to any grounding number.
- **AraSEG dev, not test.** We evaluate on the dev splits (222 documents per
  condition); the shared-task test split is reserved for the shared task
  itself. The NoPnx conditions are reported as a documented ceiling for a
  punctuation-conditional rule splitter (see `engine/eval/README.md`).

## Results snapshots

| Run | Commit | Contents | Manifest | Status |
|---|---|---|---|---|
| [40913999140](https://github.com/waleedmandour/CorpusMind/actions/runs/40913999140) | `9cad418` | perf-arabic + seg-araseg (PA/NP) | [`run-40913999140/manifest.json`](results/run-40913999140/manifest.json) | **Superseded** — its PA micro-F1 (0.107) was an evaluation-harness artifact (boundary mis-alignment on AraSEG `\n` marker tokens; fixed in PR #28) |
| [40935967239](https://github.com/waleedmandour/CorpusMind/actions/runs/40935967239) | `ee5001c` | perf-arabic + seg-araseg (PA/NP), corrected evaluator, pre-Tier-1 rules | [`run-40935967239/manifest.json`](results/run-40935967239/manifest.json) | **Superseded by the Tier-1 snapshot below** (v2.0.1 rule fixes): seg PA micro-F1 0.673 / macro 0.648, NP 0.528; analyze_arabic 3,243–3,266 tok/s (CV < 0.6%), dialect-ID ~107K tok/s |
| [40970859593](https://github.com/waleedmandour/CorpusMind/actions/runs/40970859593) | `06de47b` | perf-arabic + seg-araseg (PA/NP), first run WITH the v2.0.1 Tier-1 rules | [`run-40970859593/manifest.json`](results/run-40970859593/manifest.json) | **Canonical manuscript snapshot**: seg PA micro-F1 **0.709** (P 0.877, R 0.595) / macro 0.667, NP 0.556 (macro 0.545); grounding fidelity is provider-quota-gated and will be reported from a dispatched run separately |
| [41026068623](https://github.com/waleedmandour/CorpusMind/actions/runs/41026068623) | `afce8fe` | grounding probe re-run: G-004, G-040, G-073 on `gemini-3.8-flash` (`reasoning_effort=low`, cloud tool-round timeout 240 s, chat deadline 300 s) | [`run-41026068623/grounding/paper_report.json`](results/run-41026068623/grounding/paper_report.json) | **Probe (3 questions, quota-guarded)**: G-040 **PASS** (masked line_id scoring proven end-to-end), G-004 honest no-tool trap failure (TTR not exposed — the §5 tool-coverage gap), G-073 chat-deadline timeout (not quota). Validates the #41 pass-2 flattening fix against real Gemini 3.x |
| [41028985957](https://github.com/waleedmandour/CorpusMind/actions/runs/41028985957) | `afce8fe` | **grounding fidelity PRIMARY row**: full 80-question bank on local Ollama `qwen2.5:1.5b` (no provider quota — local-first), re-frozen gold | [`run-41028985957/grounding/paper_report.json`](results/run-41028985957/grounding/paper_report.json) | **pass_rate 0.1375** (CI95 0.0625–0.2125), hallucination_rate 0.65 (CI95 0.5375–0.75); verdicts 11 PASS / 14 MISSING_NUMBER / 41 HALLUCINATED / 14 TRAP_FAILURE; ~33 min bank time on ubuntu-latest CPU. Re-scored unchanged against the post-#44 deterministic gold. Gemini full row still pending a PAID key (free tier 20 RPD < the ~160+ calls needed) |
