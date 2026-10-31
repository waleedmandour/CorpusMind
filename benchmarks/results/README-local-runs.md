# Local grounding rows — raw run artifacts (F1)

Raw `paper_run.json` / `paper_report.json` for every local (Ollama) run of
the A3 protocol, committed verbatim from the run snapshot branches / the
bench-state archive. Provenance per directory:

| run | config | protocol | source of the files | SHA |
|---|---|---|---|---|
| 41173022988 | qwen2.5:1.5b #1 | full 80, frozen gold | bench/snapshot-run-41173022988 | ee42bfa |
| 41176056150 | qwen2.5:3b #1 | full 80, frozen gold | bench/snapshot-run-41176056150 | ee42bfa |
| 41185282664 | qwen2.5:1.5b #2 | full 80, frozen gold | bench/snapshot-run-41185282664 | ee42bfa |
| 41189716613 | qwen2.5:1.5b #3 | full 80, frozen gold | bench/snapshot-run-41189716613 | ee42bfa |
| 41194918539 | qwen2.5:3b #2 | full 80, frozen gold | bench-state/artifacts/run-41194918539 | ee42bfa |
| 41202610042 | qwen2.5:3b #3 | full 80, frozen gold | bench-state/artifacts/run-41202610042 | ee42bfa |
| 41206910830 | qwen2.5:7b | 5-question timing probe only | bench-state/artifacts/run-41206910830 | ee42bfa |

Notes:
- All six full-bank runs: 80/80 clean answers, scored offline against the
  frozen gold (gold sha256 480f5230…; questions.py b521cbb1…) at ee42bfa.
- 3b #2 (41194918539) and 3b #3 (41202610042): only `paper_report.json` is
  archived anywhere reachable — the runs' snapshot branches race-predated
  the grounding artifact and `paper_run.json` was not copied to bench-state.
  Disclosed; the raw envelopes remain recoverable from Actions artifacts
  within their retention window.
- 41206910830 is a probe (commit_results=false), kept here as the 7b
  evidence row; it is NOT an A3 triple member.
- Earlier rows under this directory (40913999140 … 41055467044) predate this
  branch and were already committed at ee42bfa; the afce8fe 1.5b row
  (41028985957) is SUPERSEDED (kept for provenance only).
- Freeze gate: this branch adds data under benchmarks/ only —
  `git diff ee42bfa -- engine ':!engine/eval'` is empty (verified).
