# Changelog

All notable changes to CorpusMind are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once 1.0 ships. Until then, expect breaking changes between 0.x releases.

## [Unreleased] — Phase 3: Arabic depth pass

## [0.1.16] — 2026-07-23

### Fixed — Engine

- **AI Assistant greenlet_spawn error (HTTP 502)** — The AI Assistant chat
  endpoint returned HTTP 502 with `"greenlet_spawn has not been called;
  can't call await_only() here"` when answering any message. Root cause:
  `assistant.py` and `api/ai.py` accessed the `Conversation.turns`
  relationship via lazy loading inside async SQLAlchemy sessions. In
  SQLAlchemy async, lazy loading triggers implicit synchronous IO which
  is not permitted inside a greenlet. Fix: replaced all `session.get()`
  calls with `select(Conversation).options(selectinload(Conversation.turns))`
  to eagerly load the turns relationship. Affected files:
  `engine/ai/assistant.py` (2 locations) and `engine/api/ai.py` (2 locations).

### Changed — Web

- **Arabic subtitle** — Updated the Arabic home subtitle from
  "بيئة بحثية محلية أولاً" to
  "بيئة بحثية علي جهازك فقط في المقام الأول"
  (local-first → runs on your device only, primarily).

### Changed — Version

- Version bumped to 0.1.16 across all components (engine, web, desktop, shared, CITATION.cff).

## [0.1.15] — 2026-07-07

### Added — Engine

- **§8.21 Arabic NLP backend abstraction** (`nlp/arabic/pipeline.py`) —
  CAMeL Tools as the default backend (calima-msa-r13 morphology DB) with
  stubbed Farasa and SinaTools backends. The `ArabicBackend` Protocol means
  backends can be swapped per task/dialect without touching the rest of
  the engine (§3.3 mandate: "don't reinvent Arabic NLP — build an
  abstraction layer").
- **§8.21 Root extraction (الجذر)** — `extract_arabic_roots` returns the
  triliteral root for each token (e.g. `المكتبة → ك.ت.ب`). Useful for
  semantic-field analysis: all words sharing a root are semantically
  related.
- **§8.21 Pattern (وزن) identification** — patterns like `يُ1ْ2ِ3` and
  `المَ1ْ2َ3َة` are extracted alongside roots. The 1-2-3 placeholders
  represent the three root consonants.
- **§8.21 Lemma normalization** — CAMeL's disambiguated lemma (with
  diacritics when available) is returned per token.
- **§8.21 Diacritics handling** — `dediacritize_arabic` removes التشكيل
  (Harakat). User-controlled: the analyzer accepts a `dediacritize` flag.
- **§8.21 Buckwalter transliteration** — `transliterate_buckwalter`
  converts Arabic script to ASCII Buckwalter encoding (e.g. `الطلاب → AlTlAb`).
  Useful for researchers who can't read Arabic script but need to cite forms.
- **§8.21 Clitic segmentation** — `segment_arabic_clitics` returns surface +
  stem + POS per token. Phase 4 will swap in a proper clitic segmenter
  (CAMeL's `MorphologyDB` with `clitic` segmentation enabled).
- **§8.21 Dialect identification** — `identify_arabic_dialect` returns a
  probability distribution over {msa, egy, glf, lev}. Phase 3 ships a
  heuristic starter (lexicon-based); Phase 4 will swap in the full CAMeL
  DialectIdentifier model (274 MB) behind the same interface.
- **§8.21 Register detection** — `detect_arabic_register` distinguishes
  Classical (Quranic/Classical) / MSA / Dialectal. Useful for diachronic
  corpus analysis.
- **§8.21 Normalization** — `normalize_arabic` unifies alef variants
  (أ/إ/آ → ا), teh marbuta (ة → ه), and alef maksura (ى → ي).
- **5 new grounded-AI tools** registered (`ai/tools.py`):
  `arabic_morphology`, `arabic_dialect_id`, `arabic_roots`,
  `arabic_register`, `arabic_transliterate`. These are stateless (sync,
  no DB session needed) — the `execute_tool` dispatcher was refactored
  to handle both async session-backed tools and sync stateless tools.
- **Phase 3 API routes** (`api/arabic.py`) — 8 new endpoints under
  `/api/v1/arabic/`: analyze, roots, clitics, buckwalter, dediacritize,
  normalize, dialect, register, backends.
- Engine version bumped to 0.4.0. Total grounded-AI tools: 19
  (Phase 1: 6 + Phase 2: 8 + Phase 3: 5).

### Added — Web

- **ArabicView** (`ArabicView.tsx`) — 8-tool Arabic analysis workbench
  with RTL text input, sample texts, dialect picker, and result rendering:
  - Morphology table (token, root, pattern, lemma, POS, stem, Buckwalter)
  - Root extractor table
  - Clitic segmenter table
  - Buckwalter transliteration
  - Dediacritized text
  - Normalized text
  - Dialect ID distribution bars
  - Register detection distribution bars
- All Arabic text in the UI uses `dir="rtl"` + `lang="ar"` + Arabic font stack.
- Ribbon "Arabic" group under Text Suite tab now routes to the Arabic view.
- Command palette adds "Go to Arabic Analysis" action.

### Added — Tests

- `engine/tests/test_phase3_arabic.py` — 10 integration tests covering
  morphology analysis (root, pattern, lemma, POS, Buckwalter), root
  extraction (semantic field of ك.ت.ب), dialect ID (probability distribution
  + Egyptian lexicon detection), register detection, Buckwalter
  transliteration (ASCII output), dediacritization (harakat removal),
  normalization (teh marbuta), backend listing, clitic segmentation, and
  the 5 Arabic tools registered in the grounded-AI surface.

### Added — Review audit

- `scripts/REVIEW_AUDIT_PHASE2.md` — one-time Phase 2 spec compliance audit
  confirming all §8.8, §8.10–8.13, §8.15, §8.17, §8.18 features are
  implemented and tested.

### Changed

- `ai/tools.py` — refactored `execute_tool` to handle stateless sync tools
  (Arabic, ping) alongside async session-backed tools (Phase 1+2). New
  `_STATELESS_TOOLS` set identifies tools that don't need a DB session.
- `app/main.py` — wires the `arabic` router; engine version 0.4.0.
- `store/ui.ts` + `Ribbon.tsx` + `App.tsx` — `activeTab` type extended
  with `"arabic"`; ribbon "Arabic" group items now navigate to the
  Arabic view; command palette gets a new action.

### §16 Phase 3 scope status

Per the phased roadmap, Phase 3 = dedicated hardening of §8.21 against
the CAMeL Tools / SinaTools / Farasa ecosystem. Status:

- ✅ §8.21 CAMeL Tools integration (calima-msa-r13 + dialect DBs available)
- ✅ §8.21 Root extraction (الجذر)
- ✅ §8.21 Pattern (وزن) identification
- ✅ §8.21 Lemma normalization
- ✅ §8.21 Diacritics handling (removal, user-controlled)
- ✅ §8.21 Buckwalter transliteration
- ✅ §8.21 Clitic segmentation (Phase 4 will improve)
- ✅ §8.21 Dialect identification (heuristic starter; Phase 4 swaps in full model)
- ✅ §8.21 Register handling (Classical / MSA / Dialectal)
- ✅ §8.21 Backend abstraction (CAMeL default; Farasa + SinaTools stubbed)
- ✅ Grounded-AI tool surface extended (5 new Arabic tools)
- ✅ RTL UI hardening (Arabic view, dir/lang attrs, Arabic font stack)
- 🚧 §8.22 Bilingual corpus tools (Arabic–English alignment) — Phase 4
- 🚧 §8.21 Broken plurals / dual forms / gender detection — Phase 4
  (CAMeL morphology DB exposes these via the `gen` feature)

## [0.3.0] — Phase 2: Suite A completion

### Added — Engine

- **§8.8 N-grams + lexical bundles** (`discourse/service.py:compute_ngrams`) —
  2–10-grams with the standard frequency-and-range criterion (Biber et al.):
  both a minimum frequency per million words AND a minimum number of distinct
  documents are required to qualify as a lexical bundle. Raw frequency alone
  is not enough to distinguish genuine bundles from single-text artifacts.
- **§8.11 POS analysis** (`discourse/service.py:compute_pos_analysis`) — POS
  distribution (top tags by frequency + percent) and POS n-grams (1–5) for
  stylistic analysis.
- **§8.12 Grammar analysis** (`discourse/service.py:compute_grammar_analysis`) —
  dependency-parse-driven pattern detectors (not regex over surface text):
  passive voice (aux:pass / auxpass), modal verbs, negation, relative clauses,
  complex noun phrases (NOUN with ≥2 modifiers), and tense (past/present/future
  from morph features). Handles both UD v2 labels and spaCy legacy labels.
- **§8.13 Dependency analysis** (`discourse/service.py:compute_dependency_analysis`) —
  thin queries over the same dependency parses already produced in §8.1:
  most common governor-dependent pairs for any UD relation (nsubj, obj, iobj,
  obl, amod, compound, etc.). Each result includes example evidence IDs.
- **§8.15 Discourse analysis** (`discourse/service.py:compute_discourse_analysis`) —
  Hyland's interactive + interactional metadiscourse taxonomy (Hyland 2005):
  transitions, frame markers, endophoric markers, evidentials, code glosses,
  hedges, boosters, attitude markers, self-mentions, engagement markers.
  Every result is citable because it's pinned to a named taxonomy.
- **§8.10 Vocabulary profiling** (`discourse/service.py:compute_vocab_profile`) —
  K1 / K2-K9 / AWL / Off-list frequency bands using the bundled CC-0 English
  top-200 wordlist as K1 approximation + a starter Academic Word List subset
  (Coxhead 2000). Reports rare words and academic words. Phase 3 swaps in a
  proper open frequency corpus.
- **§8.18 Sentiment analysis** (`discourse/service.py:compute_sentiment`) —
  lexicon-based per-sentence sentiment (-1 to +1) with positive/negative/neutral
  counts and a per-sentence timeline. Phase 3 swaps in VADER or a transformers
  model behind the same interface — results stay comparable because the model
  + version is pinned per project (§4 Principle 8).
- **§8.17 Metaphor candidates** (`discourse/service.py:compute_metaphor_candidates`) —
  LLM-assisted MIPVU-inspired pipeline scaffold. Produces candidates (verbs
  with abstract subjects) which the LLM triages via MIPVU decision steps and
  a human must verify before any candidate counts as a confirmed metaphor in
  export/statistics. The verification gate is load-bearing for validity (§8.17
  +ADD).
- **8 new grounded-AI tools** registered (`ai/tools.py`): `get_ngrams`,
  `get_pos_analysis`, `grammar_query`, `dependency_query`, `discourse_analysis`,
  `vocab_profile`, `sentiment`, `metaphor_candidates`. The Assistant's tool
  surface is now 14 tools total (Phase 1's 6 + Phase 2's 8).
- **Phase 2 API routes** (`api/phase2.py`) — 9 new endpoints for the above
  features, all under `/api/v1/corpora/{cid}/…`.
- Engine version bumped to 0.3.0.

### Added — Web

- **8 new analysis tabs** in `AnalysisView.tsx`: N-grams, POS, Grammar,
  Dependency, Discourse, Vocabulary, Sentiment, Metaphor. Each tab is marked
  with a `·2` badge to distinguish Phase 2 features from Phase 1.
- **Metaphor verification queue UI** — candidates render with the load-bearing
  "Needs verification" badge, evidence IDs, the source sentence, and the
  detector's reasoning. Phase 3 will wire the verify button to a persistence
  layer.
- **Sentiment timeline visualization** — per-sentence sentiment bars
  (green/red/grey) for diachronic or narrative corpora.
- **Grammar pattern selector** — multi-checkbox filter for the 6 grammar
  detectors.
- **Discourse category breakdown** — Hyland's 10 categories each rendered
  with frequency, per-million, and example sentences with evidence IDs.

### Added — Tests

- `engine/tests/test_phase2.py` — 14 integration tests covering n-grams
  (including the min_range criterion), POS distribution + bigrams, grammar
  detectors (passive, modal, negation), dependency queries, Hyland's
  metadiscourse, vocabulary bands, sentiment (positive/negative/neutral),
  metaphor candidates with stable evidence IDs, and the full Phase 2 tool
  registry. All pass against in-memory SQLite via httpx ASGI transport.

### Added — Review audit

- `scripts/REVIEW_AUDIT.md` — one-time spec compliance audit of Phase 0 + 1.
  Verified every §4 principle, every §8.1–8.9 feature, every §11 grounded-AI
  requirement. Found and fixed 149 ruff lint errors (72 auto-fixed, 9 manual)
  and updated the ruff ignore list with documented justifications.

### Changed

- `pyproject.toml` ruff ignore list expanded with documented justifications
  for B008 (FastAPI Depends), N803/N806 (ORM class names as variables),
  E741 (math notation matching literature), RUF002/RUF003 (Unicode math
  symbols in docstrings).
- All `raise HTTPException(...)` calls in `api/` now use `raise ... from e`
  to preserve exception chains (B904).
- Grammar detectors handle both UD v2 labels (`aux:pass`, `acl:relc`) and
  spaCy legacy labels (`auxpass`, `relcl`) — `en_core_web_sm` still uses
  the latter.

### §16 Phase 2 scope status

Per the phased roadmap, Phase 2 = §8.8–8.18, §8.21–8.25. Status:

- ✅ §8.8 N-grams + lexical bundles
- ✅ §8.10 Vocabulary profiling (open approximation; EVP not bundled)
- ✅ §8.11 POS analysis
- ✅ §8.12 Grammar analysis (dependency-driven)
- ✅ §8.13 Dependency analysis
- ✅ §8.15 Discourse analysis (Hyland's taxonomy)
- ✅ §8.17 Metaphor candidates (LLM-triaged, human-verified)
- ✅ §8.18 Sentiment analysis
- 🚧 §8.14 Semantic analysis (embeddings) — deferred to Phase 3 with Arabic
- 🚧 §8.16 Pragmatics — deferred to Phase 3 (LLM-assisted)
- 🚧 §8.21 Arabic-specific features — Phase 3
- 🚧 §8.22 Bilingual corpus tools — Phase 3
- 🚧 §8.23 Research workflow (saved searches, bookmarks) — partial (Methods PDF done)
- 🚧 §8.24 Collaboration (share projects) — Phase 6
- ✅ §8.25 Ease of use polish — ribbon, themes, command palette, RTL

## [0.2.0] — Phase 1: Suite A MVP

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
