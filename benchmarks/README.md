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

| Run | Commit | Contents | Manifest |
|---|---|---|---|
| _(populated by dispatched runs with `commit_results=true`)_ | | | |
