# CorpusMind evaluation harness

Labelled evaluation for the parts of CorpusMind that the unit suite cannot
cover: the **AI assistant's grounding fidelity** and the **Arabic sentence
segmenter**, plus the scaffolding for cross-implementation parity. This is
research infrastructure for the tool paper — every number reported in the
paper should be reproducible from this directory.

```
engine/eval/
├── corpus_snapshot.py      fixed bilingual snapshot + corpus layout (C1..C6)
├── data/snapshot/          9 original texts (sha256-frozen manifest)
├── questions.py            80-question bank with build-time gold specs
├── build_gold.py           ONE-TIME gold freezer (engine tool outputs, frozen)
├── data/gold/              grounding_gold.json — frozen 2026-10-29, engine 2.0.0
├── run_grounding.py        assistant-in-the-loop runner (any provider)
├── score.py                number-extraction + verdict classifier + bootstrap CI
├── segmentation_araseg.py  Arabic segmentation vs AraSEG (boundary P/R/F1)
├── segmentation_downstream.py  extrinsic deltas: KWIC, collocations, n-grams,
│                           CQL scope, sentiment, CAF, Gale-Church alignment
├── data/araseg/README.md   fetch + licence notes (data is NOT vendored)
└── runs/                   run + report artifacts (gitignored)
```

## 1. Assistant grounding fidelity

**Claim tested:** every number the assistant quotes comes from a tool output
for the selected corpus; trap questions (zero matches, CQL syntax errors,
unexposed measures) are answered honestly instead of inventing values.

Protocol — three steps, each a separate command:

```bash
cd engine
# (1) freeze gold — already committed; regenerate ONLY with review (see below)
python -m eval.build_gold --force
# (2) run the assistant over the bank (any OpenAI-compatible provider)
python -m eval.run_grounding --provider ollama --out runs/paper_run.json
# (3) score
python -m eval.score runs/paper_run.json --out runs/paper_report.json --verbose
```

Scoring: a quoted number is **grounded** if it matches a gold value (exact
for counts, 0.5% relative for floats, percent/fraction equivalence accepted),
**allowed** if it appears anywhere in that question's frozen tool outputs,
otherwise **hallucinated**. Verdicts per question: PASS / MISSING_NUMBER /
HALLUCINATED / TRAP_FAILURE / NO_ANSWER. The report carries per-category
pass rates and bootstrap 95% CIs (seed 42, 2000 resamples) — these are the
paper's numbers.

Gold discipline (inherited from `tests/data/goldens/measures_v2.json`):
gold is frozen ONCE from the engine's own tool registry, with the tool
outputs kept verbatim as provenance (`_meta` records engine version, commit,
spaCy model, snapshot hashes). Regeneration is a reviewable event: diff the
old gold, explain every change, commit with rationale. Never regenerate to
make a failing answer pass.

### Known tool-coverage gaps (measured 2026-10-29, engine 2.0.0)

The bank deliberately includes questions the CURRENT tool registry cannot
ground; a perfect honest assistant scores PASS on them (verdict class
`no_tool`). They double as a punch list:

| Gap | Questions | What the assistant cannot quote |
|---|---|---|
| `get_frequency` exposes `sttr` only | G-004, G-024–G-026, G-028 | TTR, MATTR, MTLD, Guiraud (incl. the v2.0.0 HD-D work) |
| `get_dispersion` exposes DP + Juilland's D only | G-019 | DP-norm and range (the v2.0.0 Lijffijt–Gries correction!) |
| no bundled-reference keyness tool | G-012 | keyness vs BE06 / camel-arabic references |
| no readability tool | G-077 | Flesch reading-ease |
| Arabic-only tools on an EN corpus | G-078 | (correct refusal expected) |

Also observed (cosmetic, unfixed by design here): `arabic_dialect_id` wraps
its distribution twice (`dialect_distribution.dialect_distribution.*`); the
keyness tool's N1/N2 are post-filter counts, not raw corpus tokens.

## 2. Arabic sentence segmentation (AraSEG)

Reference: Mohammed Elkholy, Khalid N. Elmadani, Nizar Habash & Bashar
Alhafni, "Arabic Sentence Segmentation Across Genres and Punctuation
Conditions", arXiv preprint arXiv:2606.08025 (v2, 2026-08-31). The paper is
an arXiv preprint; the data comes from the **AraSEG shared-task release**
run at ArabicNLP 2026 @ EMNLP 2026
([mbzuai-nlp/araseg-shared-task-2026](https://github.com/mbzuai-nlp/araseg-shared-task-2026),
HF `MBZUAI/AraSeg-2026-Shared-Task-{PA,NoPnx-PA,NP,NoPnx-NP}`).

**Data licence: the dataset cards state MIT** — all four Hugging Face
variants carry `license: mit` in their front matter, and the shared-task
repo is MIT (both checked live 2026-10-30). Stated no stronger than the
sources: the AraSEG paper describes part of the material as BAREC-derived,
and BAREC-derived material is listed under CC BY-SA 4.0 in the paper's own
data statement; we did not find that statement on the dataset cards.
CorpusMind fetches the data for local evaluation and never redistributes
it. An earlier note here and in `data/araseg/README.md` claimed CC BY-SA
4.0 for the dataset; no CC BY-SA statement exists on the cards themselves.
The data is fetched, not vendored (see `data/araseg/README.md`).

**Shared-task release splits** (per the dataset cards): train 174 documents
(128K words) / dev 222 documents (164K words) / test 262 documents (159K
words) — 658 documents, ~451K words, 8 genres. This evaluation uses the dev
split only (222 docs per condition); the test split is never touched for
tuning.

```bash
python -m eval.segmentation_araseg --data /tmp/araseg/PA/dev.jsonl --task PA
python -m eval.segmentation_downstream --data /tmp/araseg/PA/dev.jsonl --limit 5
```

Intrinsic: boundary P/R/F1 per document, macro-averaged (shared-task
protocol). Report PA and NP conditions; the NoPnx conditions are a
documented ceiling for a punctuation-conditional rule splitter.

Extrinsic (this is the novel part): for each document the consumer endpoints
run twice — engine segmentation vs gold segmentation (newlines force the
gold boundaries) — and the report carries paired deltas:
`delta_sentences`, collocation `rows_delta`/`sum_O_delta`, n-gram
`sum_freq_delta`, CQL `within sentence` delta, sentiment
`delta_positive/delta_negative/delta_avg`, CAF `delta_mean_sentence_length`,
and (with `--en-text`) the Gale-Church `alignment_pair_count`. These deltas
are the paper's evidence that segmentation quality propagates into every
analysis the tool sells.

SIGN CONVENTION (authoritative, matches the code in
`segmentation_downstream.measure_pair`): every `*_delta` field is computed as
**gold minus engine** (`sents["gold"] - sents["engine"]`, etc.). A POSITIVE
delta therefore means the GOLD segmentation produced MORE of that quantity
than the ENGINE segmentation (e.g. `delta_sentences = +68` = the engine
merged 68 sentences relative to gold); a NEGATIVE delta means the engine
produced MORE. Beware summaries that phrase the convention as "engine minus
gold" — that phrasing corresponds to negating every delta reported here.
`boundary_errors` in the same report is a symmetric count of differing
boundary positions (unsigned). Extrinsic coverage note: from the A4 rerun
(2026-10-31) the extrinsic deltas are computed on ALL 222 AraSEG dev
documents per condition (`seg_limit=222`), not the earlier 20-document
subset (runs 41173011756 and earlier are superseded for the extrinsic
view; the 20-doc numbers remain in their snapshot branches for audit).

Calibration: `calibration_sentence.py` scores NLTK Punkt (trained per
condition on the AraSEG train split), pySBD (`language='ar'`) and the spaCy
sentencizer (blank `ar` pipeline, default `punct_chars`) through the SAME
owner-map protocol as `segmentation_araseg`. In the PA conditions punkt and
the sentencizer are run per paragraph (AraSEG `\n` markers count as
boundaries) and pysbd splits newlines natively — this reproduces Table 4 of
arXiv:2606.08025 (dev set) to within 0.21 F1:
PA punkt 65.18 vs 65.2, pysbd 63.31 vs 63.1, spacy 67.29 vs 67.3;
NP punkt 52.32 vs 52.3, pysbd 52.05 vs 52.1, spacy 54.31 vs 54.3.

    python -m eval.calibration_sentence --data /tmp/araseg/PA/dev.jsonl \
        --task PA --punkt-train /tmp/araseg/PA/train.jsonl --out calib_PA.json

## 3. Determinism & CI

- The snapshot texts are hash-frozen; the scorer refuses to run against a
  changed snapshot (`SnapshotIntegrityError`).
- `build_gold` and `run_grounding` boot the real engine in-process
  (in-memory SQLite), same pattern as the test suite; no network needed
  except the assistant provider and (first time only) the Arabic data pack.
- `engine/tests/test_eval_grounding.py` runs offline in CI: snapshot
  integrity, scorer units (incl. Arabic-Indic digits and line-id exclusion),
  a gold-subset rebuild check, and an end-to-end grounding pass with a
  scripted stub provider (perfect assistant → 100% pass; corrupted answer →
  HALLUCINATED/WRONG classified).
