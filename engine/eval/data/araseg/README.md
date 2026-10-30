# AraSEG data — fetch locally, do not commit

This directory holds NO data. The Arabic sentence-segmentation evaluation
(`eval/segmentation_araseg.py`, `eval/segmentation_downstream.py`) reads the
AraSEG corpus from a local path you provide.

## Source

- Paper: Elkholy, Elmadani, Habash & Alhafni (2026), "Arabic Sentence
  Segmentation Across Genres and Punctuation Conditions",
  arXiv preprint arXiv:2606.08025 (v2, 2026-08-31).
- Repository: https://github.com/mbzuai-nlp/araseg-shared-task-2026
- Datasets: HF `MBZUAI/AraSeg-2026-Shared-Task-{PA,NoPnx-PA,NP,NoPnx-NP}`
  (splits: train 174 / dev 222 / test 262 documents; 658 docs, 451K words total).
- Licence: the dataset cards state MIT. All four Hugging Face variants
  (`PA`, `NoPnx-PA`, `NP`, `NoPnx-NP`) carry `license: mit` in their front
  matter, and the shared-task GitHub repo is MIT (both checked live
  2026-10-30). One caveat, stated no stronger than the sources: the AraSEG
  paper describes part of the material as BAREC-derived, and BAREC-derived
  material is listed under CC BY-SA 4.0 in the paper's own data statement —
  we did not find that statement on the dataset cards, but the cards are
  not legal advice. CorpusMind only *fetches* this data for local
  evaluation and never redistributes it, so downstream risk is low.
  Correction history: an earlier version of this file claimed MIT, then a
  2026-10-29 note switched the claim to CC BY-SA 4.0 "per dataset card";
  a re-check of all four live cards on 2026-10-30 found no CC BY-SA
  statement on the cards themselves. The AraSEG team's released
  segmentation models (`MBZUAI/sentseg-camelbert-*`) are MIT.

## Format expected by the eval modules

JSON Lines, one document per object, with the fields as published:

```json
{"doc_id": "doc_00f88da2b078", "tokens": ["وَ", "فِي", "..."], "labels": [0, 1, ...]}
```

`labels[i] == 1` means a sentence boundary follows `tokens[i]`. Extra fields
(`text`, `label_str`) are ignored. If a future release renames fields, adapt
`load_documents()` in `eval/segmentation_araseg.py` — it is the single
ingestion point for both modules.

## Fetching

Download the split files for the condition you want from the GitHub README
links (they point at the HF datasets), e.g.:

```bash
huggingface-cli download MBZUAI/AraSeg-2026-Shared-Task-PA \
  --repo-type dataset --local-dir /tmp/araseg/PA
python -m eval.segmentation_araseg --data /tmp/araseg/PA/dev.jsonl --task PA
python -m eval.segmentation_downstream --data /tmp/araseg/PA/dev.jsonl --limit 5
```

## Which condition to report

The engine's Arabic segmenter is punctuation-conditional, so the meaningful
conditions are **PA** (paragraph-aware, punctuation present) and **NP**
(punctuation present, no paragraph structure). The NoPnx-* variants strip
punctuation — a rule-based splitter collapses there by construction; report
that as a documented ceiling, not as a bug. Follow the paper's protocol:
boundary P/R/F1 per document, macro-averaged.
