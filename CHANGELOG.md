# Changelog

All notable changes to CorpusMind are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once 1.0 ships. Until then, expect breaking changes between 0.x releases.

## [Unreleased] — Phase 1: Suite A MVP

### Added — Engine

- **Storage layer (`engine/storage/`)** — SQLAlchemy 2.0 async models for
  projects, corpora, documents, tokens (CoNLL-U-compatible: text, lemma,
  UPOS, XPOS, morph, dep_head, dep_rel), annotation versions (§4.8
  reproducibility), and persisted conversations with their grounded-AI
  audit trail. Backed by SQLite via aiosqlite.
- **Ingestion (`engine/ingestion/`)** — multi-format file parsing:
  TXT (charset-normalizer encoding detection), DOCX (python-docx),
  PDF (pypdf), HTML (BeautifulSoup + lxml), XML, CSV (auto-detects `text`
  column), and Markdown. Visible "pipeline recipe" per corpus recording
  the exact spaCy model + version that produced the annotations.
- **NLP pipeline (`engine/nlp/general/pipeline.py`)** — spaCy wrapper
  with a `Pipeline` Protocol so Phase 3 can swap in CAMeL Tools / SinaTools
  for Arabic without touching the rest of the engine. Loads lazily on
  first use so the engine starts fast.
- **Corpus management API (`engine/api/corpora.py`)** — full CRUD for
  projects + corpora + documents. Drag-and-drop multi-file upload.
- **Concordance API (`engine/api/analysis.py` + `engine/stats/service.py`)** —
  KWIC search at word/lemma/POS level with wildcard support, stable line
  IDs (`doc:sentence:token` format, cited by the AI Assistant), configurable
  context window, pagination.
- **Frequency API** — word/lemma/POS frequency with per-million and
  percent columns, STTR (standardized TTR over 1000-token chunks) as the
  comparably valid default, raw TTR available but labeled.
- **Collocation API** — all §12 measures (MI, T-score, log-likelihood,
  Dice, LogDice, chi-square, Delta P in both directions) with configurable
  window and minimum-frequency filter. Window size is always surfaced
  alongside results (reproducibility).
- **Keyness API** — target vs reference comparison with **both significance
  (log-likelihood, chi-square) AND effect-size (Log Ratio, %DIFF, Simple
  Maths, Odds Ratio) measures** — the load-bearing §4 Principle 3
  implementation. Returns positive and negative keywords.
- **Dispersion API** — Juilland's D and Gries' DP across documents, with
  per-part frequency breakdown.
- **Grounded-AI tool surface (`engine/ai/tools.py`)** — registered tools:
  `search_concordance`, `get_frequency`, `compute_collocations`,
  `compute_keyness`, `get_dispersion`, `ping`. The Assistant auto-injects
  the active `corpus_id` so users don't have to. Conversations persist in
  SQLite with full audit trail (every turn, tool call, and evidence item).
- **Export APIs (`engine/api/export.py`)** — Excel (openpyxl) for
  concordance / frequency / collocation / keyness; PDF (reportlab)
  auto-drafted Methods Section naming the exact pipeline recipe + formula
  citations (§8.23 reproducibility).

### Added — Web

- **Corpus manager view** (`CorpusManagerView.tsx`) — three-column layout
  (projects / corpora / documents), drag-and-drop file upload, modal
  dialogs for creating projects + corpora, inline pipeline-recipe display.
- **Concordancer view** (`ConcordancerView.tsx`) — KWIC table with
  color-coded POS tags, stable line IDs, Excel export, lemma/word/POS
  level selector, configurable window.
- **Analysis view** (`AnalysisView.tsx`) — tabbed frequency / collocation
  / keyness / dispersion panels with measure selectors and Excel/PDF
  export buttons. Keyness panel shows positive AND negative keywords with
  both significance and effect-size columns always visible.
- **Assistant view (Phase 1)** — now sends the active `corpus_id` with
  each chat request, displays clickable evidence citations (concordance
  line IDs open the concordancer), and shows the full tool surface.
- **App state** (`store/app.ts`) — persisted active project / corpus /
  reference corpus selection.

### Added — Reference data

- `reference-data/wordlists/en/top200.tsv` — open English top-200
  frequency wordlist (CC-0) for use as a default keyness reference.

### Added — Tests

- `engine/tests/test_api.py` — 9 integration tests covering the full
  API surface (project/corpus CRUD, upload + ingest, concordance,
  frequency, collocations, keyness, Excel export, PDF methods export,
  AI tools list). All pass against an in-memory SQLite DB via httpx
  ASGI transport.

### Changed

- Engine version bumped to 0.2.0.
- `app/main.py` now initializes the DB on startup (`init_db()` called
  in the lifespan context).
- `ai/assistant.py` rewritten to use the new tool registry + persist
  conversations + auto-inject `corpus_id`.
- `ai/__init__.py` no longer exports the old `ToolRegistry` / `ToolSpec`
  (the new `ai/tools.py` replaces them with a function-based registry).
- `storage/session.py` `get_session` dependency now commits on success
  (previously it was read-only by accident, which broke cross-request
  visibility).
- `stats/measures.py` — `log_ratio` and `pct_diff` now handle edge cases
  (f1=0 or f2=0) without raising math domain errors.

### §20 Definition of Done — Phase 1 MVP status

A researcher with no programming background can, without help:

- ✅ install the desktop app or open the PWA
- ✅ create a project
- ✅ upload a multi-file text corpus (TXT, DOCX, PDF, HTML, XML, CSV, MD)
- ✅ watch it auto-clean/tokenize/tag (spaCy pipeline, visible pipeline recipe)
- ✅ run a concordance search (KWIC with stable line IDs, lemma/word/POS levels, wildcards)
- ✅ generate a collocation list with at least two selectable statistical measures (all 7 §12 measures available)
- ✅ generate a keyness comparison against a reference corpus showing both a significance test and an effect-size measure (LL + Log Ratio + %DIFF + Simple Maths + Odds Ratio)
- ✅ export results to Excel/PDF (frequency, concordance, collocations, keyness, methods-section PDF)
- ⚠️ ask the AI Assistant a natural-language question about the corpus and receive an answer whose claims are clickable back to real concordance lines — **the plumbing is complete (tools registered, evidence cited, UI renders clickable citations), but a live Ollama/LM Studio model is required for the end-to-end flow**. The smoke test verifies the engine side; the user must run `ollama serve` + `ollama pull llama3.2:3b` to see grounded answers in the UI.
- ✅ the AI Assistant works fully offline against a local Ollama or LM Studio model, with no data leaving the machine (cloud provider opt-in only, hard-disable switch for self-hosted deployments)
- ⚠️ the desktop build runs cleanly on Windows, Linux, and macOS with no orphaned background processes — **the Rust supervisor is written and compiles, but the PyInstaller-bundled sidecar binary is not yet produced by CI**. Dev mode (`cargo tauri dev`) falls back to spawning `python -m app.main` and works correctly.

## [0.1.0] — Phase 0

Initial release. See "Added" section in the previous changelog entry for the
Phase 0 foundations: monorepo scaffold, engine skeleton, web PWA shell,
Tauri 2 desktop shell, ModelProvider abstraction, grounded-AI Assistant
scaffold, §12 statistics engine with 23 unit tests, full docs.
