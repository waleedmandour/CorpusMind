# Changelog

All notable changes to CorpusMind are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once 1.0 ships. Until then, expect breaking changes between 0.x releases.

## [1.0.3] — 2026-09-05 — Windows installer hardening

The v1.0.1 Windows packages could fail to install or appear broken on real
machines. This release fixes every identified install-time defect for both
desktop apps.

### Fixed (Windows installers)

- **Zombie engine sidecar locked files**: the stock NSIS template only stops
  the main executable, so a surviving `corpusmind-engine.exe` (crashed
  session, Task-Manager close) made install/upgrade fail with *Error opening
  file for writing*. Custom NSIS `PREINSTALL`/`PREUNINSTALL` hooks now
  tree-kill the app and the sidecar before any file operation (both apps).
- **First-run "engine offline" on slower machines**: Windows Defender scans
  the entire ~700-file PyInstaller sidecar tree on first launch, which could
  exceed the previous 30-second shell wait and 15-second UI wait. Both
  budgets are now 60 seconds; the UI keeps polling and recovers
  automatically once the engine is up.
- **Publisher metadata**: Windows "Apps & features" and the MSI now show the
  authors ("Dr. Waleed Mandour (Sultan Qaboos University) & Prof. Wesam
  Ibrahim (PNU)") instead of the identifier fallback "corpusmind".
- **CI verification steps**: the Windows jobs' size/model verification steps
  called a broken `ath]::Round` (a corrupted `[math]::Round`) which crashed
  the steps with a PowerShell ParserError; syntax restored.

### Notes

- The `.exe` (NSIS) installs per-user without administrator rights; the
  `.msi` installs per-machine and requires elevation. Machines without the
  WebView2 runtime need internet access during installation (the runtime is
  fetched from Microsoft at install time).

## [1.0.1] — 2026-09-05 — Linguistics QA round: statistical validity + missing core features

An expert corpus-linguistics review of the v1.0.0 code found seven validity
issues and a set of missing table-stakes features. This release fixes all of
them (the full methodology now lives in `docs/METHODOLOGY.md`; new tests in
`engine/tests/test_linguistics_qa.py`).

### Fixed (statistical validity)

- **Gries' DP is now size-weighted**: expected proportions use each document's
  token share instead of uniform `1/n`, which is the correct treatment for
  corpora of unequal document lengths. **DP-norm** (`DP·n/(n−1)`) is reported
  alongside for cross-corpus comparability, and dispersion results now include
  **range** (documents containing the term) and `range_percent`.
- **Collocation marginals aligned with the Sketch Engine / AntConc convention**:
  `f(node)`, `f(collocate)` and `N` are whole-corpus frequencies (previously
  computed only within node-containing sentences, which made rankings
  incomparable with other tools).
- **Collocates aggregate under the same case+diacritic folding as the node** —
  `The`/`the` and كِتَاب/كتاب are single rows (previously split).
- **Keyness vs bundled top-N lists**: words absent from the reference list are
  excluded from the ranking instead of scoring `f2 = 0` (which produced floods
  of spurious infinite Log Ratio / %DIFF), with a machine-readable `warnings`
  array surfaced in the UI. `camel-arabic-top1000.tsv` — which contained the
  literal text "404: Not Found" from a failed download — was rebuilt from the
  Leipzig `ara_news_2022_10K` corpus (CC BY 4.0) with its registry SHA updated.
- **χ² Cochran diagnostic**: collocation rows carry `chi2_min_expected`; the UI
  warns when expected cells fall below 5.
- **Odds Ratio** now applies the **Haldane–Anscombe 0.5 correction** on zero
  cells, so keyness tables are always finite and rankable.
- **Arabic sentence segmentation**: documents are split into sentences by a
  rule-based sentencizer (terminal punctuation, newlines, decimal-protection)
  instead of one giant "sentence" per document — this fixes KWIC context
  clipping, n-gram sentence boundaries and same-sentence collocation scoping
  for Arabic. Arabic tokens are now flagged `is_stop` from a shared MSA
  stopword list, making stopword filtering work for Arabic n-grams and
  collocations.

### Added (missing core features)

- **KWIC sorting** — AntConc-style sort levels (L1/R1/L2/R2, up to three),
  applied over the full match set before pagination.
- **Regex search** (Python syntax, SQLite `REGEXP` UDF) and **phrase
  queries** (whitespace = multi-word sequence with wildcard support).
- **Asymmetric collocation spans** (`span_left`/`span_right`), collocate
  **POS include/exclude** filters, and **stopword-list filtering** for
  collocations, frequency and keyness.
- **Fisher's exact test** added to the collocation measure battery.
- **Lexical diversity battery**: MATTR (rolling-window TTR), MTLD and
  Guiraud's root TTR join TTR/STTR in every frequency result.
- **Readability**: Flesch Reading Ease and Flesch–Kincaid grade (English),
  plus language-neutral LIX/RIX for every language — corpus-level and
  per-document endpoints.
- **Per-document statistics** table (tokens, types, sentences, TTR, LIX, RIX).
- **Compare groups**: frequency pivot by any document metadata variable
  (genre, year, register …) with per-million normalization per group.
- **User-editable stopword lists**: CRUD API + Settings manager card; built-in
  English and Arabic lists resolve virtually.
- **Root & pattern frequency levels** for Arabic corpora (aggregates the CAMeL
  morph layer), plus root/pattern concordance levels.
- **Server-side exports** through the async export queue for n-grams, POS
  analysis, dispersion, vocabulary profile, readability, document stats and
  group comparisons (previously client-side JSON only).
- **Full Coxhead (2000) Academic Word List** (570 families, 10 sublists)
  replaces the 57-word starter in vocabulary profiling.

## [1.0.0] — 2026-09-05 — Unified stable release: CorpusMind 1.0.0 + CorpusMind Lens 1.0.0

Both applications ship as **1.0.0** on the same release page. This entry
consolidates the fix rounds that were folded into the 1.0.0 artifacts
(the earlier 1.1.0/1.2.0 entries below document the same work as it
progressed; the published release page is v1.0.0).

### Main app

- **AI Assistant grounding fixed.** The assistant no longer dead-ends in
  "I cannot ground this in corpus evidence — answering from parametric
  memory only." Three changes: (1) a live corpus snapshot
  (`get_corpus_overview`, cached 5 min) is injected into the system prompt
  on every turn; (2) UI context ("the user is viewing X") now actually
  reaches the prompt — `ChatRequest.context` was accepted but dropped;
  (3) when a tool-capable model fails to emit tool calls, the assistant
  auto-runs the most relevant corpus tools deterministically (concordance,
  frequency, collocations, dispersion, n-grams, POS) and answers from the
  real results. With no corpus selected, it now guides the user instead of
  refusing.
- **Interactive collocation network rebuilt.** NetworkX-backed graph
  assembly on the engine (`/collocations/network` + `/expand`: nodes =
  word + top collocates, depth-2 meshing so degrees are informative) and a
  Graphology + Sigma.js (WebGL) frontend: node size ∝ corpus frequency,
  edge thickness ∝ the selected association measure — MI, T-score,
  log-likelihood, Dice, Log-Dice, χ², ΔP — switchable without a refetch
  (every edge carries all measures), click-to-expand second-order
  collocates, collapse, right-click to re-center, node dragging,
  zoom/pan, hover tooltips with exact statistics, and PNG + JSON export.
- **Cloud AI providers.** Settings now offers Google Gemini (via its
  OpenAI-compatible endpoint, default `gemini-2.5-flash`), OpenAI,
  Anthropic, and ANY OpenAI-compatible cloud API (DeepSeek, Mistral, Groq,
  OpenRouter, xAI, Together, …) via a required Base URL for `custom`.
  Consent-gated and in-memory-key only, as before.
- **Vision Suite guidance.** The Vision view now shows a first-run card
  pointing to the Ollama model library for `qwen3-vl` downloads and
  explaining that CorpusMind and CorpusMind Lens analyse text and images
  with the same engine — and that the AI Assistant can interpret both
  apps' data together in one conversation.

### CorpusMind Lens

The full Lens fix round (16 issues) ships in these artifacts: Lens
installers restored to the tag-gated release pipeline (previously missing
from every release since v1.0.0), capability-aware vision-model selection,
qwen3-vl model catalogue with multilingual (incl. Arabic) OCR guidance,
encryption-aware image reads, VisionView i18n (en/ar), discourse-lenses
panel wired to the 8 Phase-5 routes, batch runner, set/image export and
deletion, Lens-aware onboarding and branding, upload hardening, frameworks
catalogue endpoint, and richer vision-LM outputs (`max_tokens=2048`).

Engine suite 306 green (+15 tests for auto-grounding, network endpoints,
cloud provider config); web production build clean.

## [1.2.0] — 2026-09-05 — User-reported issues: downloads, tagsets, assistant, interactive network

Eight user-reported issues fixed end-to-end (code-level root causes verified
before implementation; engine suite 254 green; web build clean).

### Lens round (same release page — CorpusMind Lens installers restored)

A second pass focused on **CorpusMind Lens**, the vision-LM desktop shell.
Lens installers had been silently missing from every tag-gated release since
v1.0.0 (the lens build jobs lived only in the dispatch-only workflow) — they
are now first-class `release.yml` jobs and are back on this release page.
Engine suite 291 green (+37 new Lens-round tests); web build clean.

#### Lens — Added
- **Vision model intelligence** — capability-aware model selection
  (`supports_vision` / `pick_vision_model` via Ollama `/api/tags`, name
  heuristics for older servers and LM Studio): auto-picking a text-only
  model now yields an actionable 400 (`ollama pull qwen3-vl:2b`) instead of
  a confusing provider error. Model catalogue adds **qwen3-vl:2b/8b**
  (32-language OCR incl. Arabic) and marks gemma3 4b+ as vision-capable;
  moondream / llama3.2-vision demoted to English-only notes.
- **Batch runner** — `POST /image-sets/{id}/run-batch` (+ status/cancel):
  describe and/or all 8 discourse lenses over a whole image set with
  per-image error isolation, skip-if-cached and consent-gate enforcement.
- **Discourse lenses UI** — the 8 Phase-5 routes (social semiotics, CDA,
  persuasion, framing, narrative, visual metaphor, emotion, cultural) are
  finally reachable: lens dropdown, CDA sub-framework variant, LLM/heuristic
  mode, provenance badges (mode/model/confidence), fallback + redaction
  notices.
- **Export** — `GET /image-sets/{id}/export?format=xlsx|csv|tsv|txt|json`:
  one row per image (metadata, OCR, colour/composition stats, latest VLM
  description, discourse summary); wired to the ExportButton in VisionView.
- **Deletion** — `DELETE /images/{id}` and `DELETE /image-sets/{id}` remove
  DB rows AND on-disk bytes (privacy remediation for photos), with
  confirm-dialog UI.
- **`GET /frameworks`** — the 12 reference-data framework YAMLs (shipped but
  unread since v1.0.0) are now served as a catalogue.
- **Cross-modal assistant tools** — `list_image_sets`,
  `get_image_set_summary`, `get_corpus_overview` (text side + vision side in
  one grounded call). Lens's assistant can now interpret the main app's text
  corpora and image sets together.
- **Lens app identity** — top bar / status bar / onboarding are Lens-branded
  and Lens-scoped (the onboarding no longer tells users to click a sidebar
  item that only exists in the main app); the sidebar genuinely filters out
  reference corpora; the command-palette mismatch is gone.
- **User guide** — new "CorpusMind Lens and the Main App" section: shared
  engine/data dir, cross-modal interpretation, vision-model install.
- **Home (Lens)** — cross-modal overview card: text documents beside image
  sets, with Vision/Assistant shortcuts.

#### Lens — Fixed
- **Vision installers** — release pipeline builds Lens for Linux/macOS/
  Windows on every tag (fail_on_unmatched_files), and SHA256SUMS covers them.
- **Versions** — Lens `tauri.conf.json` 1.1.0 and both `Cargo.toml` 1.0.0
  bumps aligned at 1.2.0.
- **Encryption blind spot** — `/describe`, `/align`, discourse-LLM and
  alignment-LLM read image bytes through one decrypt-aware helper; with
  at-rest encryption enabled they previously sent ciphertext to the model.
- **Upload hardening** — 25 MB per-file cap (413), 50-file batch cap,
  magic-byte sniffing + extension-mismatch rejection (a text file named
  .png now fails clearly instead of crashing Pillow); docstring no longer
  claims SVG support.
- **Truncation** — vision call sites pass `max_tokens=2048` (rich claim
  sets were cut at 512 and degraded to the single-claim fallback).
- **i18n** — VisionView was 100% hardcoded English; it is now fully
  en/ar (≈150 keys) with RTL-safe logical CSS.
- **Error paths** — `alert()` replaced with inline messages routed into
  Smart Troubleshooting; 6 new vision-specific Fix: rules.
- **CSS** — 4 used-but-undefined selectors defined; dead
  `.vision-coming-soon` block retired.

### Fixed
- **Top-bar status pill (1)** — shows the active corpus's name
  ("{name} · Corpus ready", i18n en/ar) instead of a bare "Corpus ready".
- **Smart Troubleshooting (2)** — every issue card now shows an instant
  offline one-line **Fix:** suggestion (status-code + message rules table,
  no Gemini key needed); the mute toggle's malformed `"\u1F50A"` escape
  (rendered "ὐA On") is fixed; the whole panel + Settings mute toggle are
  internationalized (en/ar). Reference-corpus failures now reach the
  troubleshooter (they previously bypassed React Query entirely).
- **AI Assistant 502 (7a)** — defense in depth: tool schemas sent to local
  OpenAI-compatible servers are sanitized (older Ollama 400s on
  default/minimum/maximum keywords); an HTTP 400 on the tools payload now
  retries once WITHOUT tools so the user gets an (un-grounded) answer
  instead of `Model call failed`; models are capability-gated via
  /api/tags `capabilities` (embedding models never receive tool payloads);
  auto-selection prefers tool-capable models; error text includes the
  server's response body.
- **Buttons (6)** — one consistent button language: export triggers are
  solid brand like Compute/Search (the outline override is gone), uniform
  touch height, and every analysis panel places its Export control in the
  toolbar row (phase-2 panels had it inside the note box).
- **Feature labels (5)** — the trailing " 2" is gone from
  N-grams/POS/Grammar/Dependency/Discourse/Vocabulary/Sentiment/Metaphor.

### Added
- **Tagset selection (4)** — per-corpus tagset choice, persisted and used
  as the analysis default: grammatical **UD UPOS / Penn Treebank /
  CLAWS-7** (English), **UD UPOS / CAMeL native Calima** (Arabic), and
  semantic **USAS top-level** (new experimental
  `/corpora/{cid}/semantic-analysis`; lexicon derived from UCREL
  Multilingual-USAS, CC BY-NC-SA 4.0, see
  `reference-data/tagsets/`). Selector card in "Your Corpus", tagset
  picker in the POS panel and the Arabic tool; Arabic POS output is now
  color-coded. Recompile persists the full annotation (it previously
  dropped `pos_fine`/`morph`/`dep_*`, which would have silently broken
  PTB/CLAWS-7/Calima after re-tagging).
- **Floating AI Assistant (7b)** — floating button on every screen opens
  an in-window chat drawer (grounded tool calls, evidence, grounded badge)
  that survives navigation; context-aware ("user is viewing X" is sent
  with each turn); suggested query chips from corpus-derived dynamic
  suggestions.
- **Interactive Collocation Network (8)** — click a collocate to expand
  its collocates on a local orbit (progressive, cached per pivot), click
  again to collapse, hover pauses rotation with tooltips, drag to orbit,
  wheel zoom, set-as-center via context menu, node budget + depth counter,
  HiDPI-sharp canvas, labels on all nodes, "Export view (PNG)". Zero new
  frontend dependencies.

### Changed
- **Reference corpus downloads (3)** — the Oxford Text Archive gateway
  routinely 504s large archives (reproduced for BAWE and BNC Baby). The
  full-corpus pipeline now streams to disk in chunks (no more 108 MB in
  RAM), retries with backoff, resumes via HTTP Range, reports REAL
  byte-level progress, and supports cancellation. BAWE carries a
  CC-BY-NC-SA-compliant processed mirror hosted on the project's GitHub
  releases (tried first; BNC Baby cannot be redistributed and keeps the
  canonical source). New **"Import archive"** option installs a manually
  downloaded ZIP/tar.gz — the guaranteed path when every remote source
  fails. All six other bundled sources verified healthy.

## [1.1.0] — 2026-09-05 — Verified fixes, security hardening, feature completion

Issue-numbered fixes verified by execution (fresh-clone install, 230+ test
suite, live reproductions). See the unified fix prompt for full detail.

- **Issue 3: Fixed** — engine packaging: real `engine/README.md`, in-project
  readme path, hatchling upper bound. The documented Quickstart
  (`pip install -e ".[dev]"`) failed on any fresh environment with current
  hatchling (readme path validation) — the same command CI runs.
- **Issue 1: Fixed** — `POST /corpora/{cid}/recompile` was a complete silent
  no-op: three stacked bugs (nonexistent `parsed.tokens`; invalid
  AnnotationVersion kwargs; a NEW annotation version created per document so
  the latest version only ever held the last document's tokens) hid behind a
  per-document `except Exception` that returned HTTP 200 with
  `recompiled: 0`. Now: one version per recompile, correct column mapping,
  per-document `failed` list + `success` flag in the response. Regression
  tests added (would have failed three ways).
- **Issue 2: Fixed** — subcorpus filtering was broken (`session.get_sync`
  does not exist on AsyncSession) and wired to nothing. Concordance /
  frequency / collocations / keyness now accept an optional `subcorpus_id`,
  resolved against the saved filter's criteria; empty-criteria subcorpora
  yield empty results (never unrestricted). 7 regression tests added.
- **Issue 4: Fixed** — self-hosted Docker path was dead on arrival:
  `reference_corpus` missing from wheel packages (container crash-looped at
  startup), `engine/README.md` missing from git (COPY failed on fresh
  clone), and a curl-based healthcheck in an image that ships no curl
  (unhealthy forever). Fixed all three; ci.yml now builds the image, boots
  it, probes /health, and asserts the container reaches healthy.
- **Issue 5: Fixed** — the human-in-the-loop AI verification loop was
  unreachable end-to-end: the persisted assistant turn's DB id was never
  returned, so the frontend's Accept/Reject/Edit buttons could never render
  and /research/verify-turn was dead code. turn_id now flows through
  AssistantTurn → ChatResponse → ChatTurnResponse → AssistantView; failed
  verifications no longer mask themselves as verified.
- **Issue 6: Fixed** — consent-gate bypass: `/images/{id}/analysis` and
  `/image-sets/{id}/batch-analysis` served the RAW cached Vision-LM output
  (only /describe filtered), defeating the §18 ethical guardrails. Both read
  paths now route descriptions and discourse claims through the consent
  gate; `filter_discourse_claims` also filters `summary` as its docstring
  always promised. Tests assert raw person-descriptive text never reaches
  any read route while the gate is closed.
- **Issue 7: Fixed** — cloud providers were broken for EVERYONE (not just
  Anthropic): httpx concatenates base path + request path, so
  `https://api.openai.com/v1` + `/v1/chat/completions` produced
  `/v1/v1/chat/completions` (404 always). Client base now strips a trailing
  /v1; Anthropic sends the required anthropic-version header. Tests pin the
  exact final URLs for openai, anthropic, and custom base_url overrides.
- **Issue 8: Added** — minimal shared-bearer-token auth for non-loopback
  deployments (`CORPUSMIND_AUTH_TOKEN`): every /api request except /health
  requires `Authorization: Bearer <token>`; loopback + unset token keep the
  local-first no-auth default. docker-compose documents the shared-trust-
  boundary nature of the shared-lab mode.
- **Issue 9: Fixed** — zip-slip/tar-slip: reference-corpus archives now use
  tarfile's `filter="data"` (tar) and a member-path validator (zip). E2E
  test: a hostile `../../` zip is refused, job reports failure.
- **Issue 10: Fixed** — Tauri capabilities scoped: unused shell-spawn and
  fs-mutating grants removed in both shells; fs reads scoped to app data +
  user folders; CSP `script-src 'unsafe-inline'` dropped.
- **Issue 11: Documented** — at-rest encryption covers IMAGE FILES ONLY; the
  database is NOT encrypted (SQLCipher remains a future task). Compose
  comments no longer imply otherwise.
- **Issue 12: Fixed** — Gemini API key moves from URL query parameter (log
  leak) to the `x-goog-api-key` header; raw upstream error bodies are no
  longer echoed to clients; setting a key now requires the same explicit
  data-leaves-device acknowledgment as the other cloud paths (backend 422 +
  Settings checkbox).
- **Issue 13: Fixed** — raw provider responses (which can embed
  corpus-derived model output) are no longer embedded in error strings and
  logs by default; gated behind `CORPUSMIND_DEBUG_RAW=1`.
- **Issue 14: Fixed** — single test-gated release pipeline: a test-gate job
  (ruff + engine pytest + web typecheck/build) gates all platform jobs;
  build-release.yml is dispatch-only (tag-race eliminated); uploads fail on
  unmatched files; SHA256SUMS manifest attached to releases.
- **Issue 15: Documented** — ~30 engine endpoints shipped without frontend
  consumers (Phase-5 discourse suite, collaboration, open-access, research
  workflow, bilingual align, conversation history, export queue); marked
  experimental in the README until their UI surfaces ship.
- **Issue 16: Added** — per-image "Run Vision-LM describe" action; the batch
  view's VLM descriptions column can now actually be populated.
- **Issue 17: Added** — real server-side random sampling for the
  concordancer (seeded, reproducible, sampled from the full match set; seed
  echoed in the response). The UI toggle previously did nothing.
- **Issue 18: Added** — delete corpora and projects from the UI (confirm-
  guarded), wiring the previously-unused engine DELETE routes.
- **Issue 19: Added** — Vision Suite image previews via a new scoped
  `GET /images/{id}/thumbnail` (downscaled derivative, honours at-rest
  decryption); the grid previously rendered placeholder cards only.
- **Issue 20: Removed** — retired `Ribbon.tsx` dead component.
- **Issue 21: Fixed** — frontend/desktop robustness batch: unhandled
  rejections (image upload, set creation, corpus creation), reference-
  download Cancel is now terminal (no more 10-minute zombie polls), Ollama
  pull poller overlap/unmount leak, desktop cleanup moved to
  RunEvent::ExitRequested/Exit, hazardous unused `test_sidecar` command
  removed.
- **Issue 22: Fixed** — README "Status" section rewritten around the current
  release (it still advertised Suite B as "Coming Soon" and Phase 4 as
  🚧); version metadata unified at 1.1.0 across pyproject, both Tauri
  shells, CITATION.cff, compose image tag, and the frontend fallback.
- **Issue 23: Documented** — mypy strict mode is configured but not enforced
  (397 errors at the time of writing); CI tracks the count rather than
  pretending the guarantee holds.
- **Issue 24: Fixed** — this entry restores the missing release paper-trail;
  a versioning-scheme note now explains the mid-project 0.1.x→phase switch.
- **Issue 25: Deferred** — THIRD_PARTY_LICENSES.md sync + committed
  reference-data license records (tracked for the next docs pass).
- **Issue 26: Fixed** — npm ci (not npm install) and pinned Tauri CLI (@2)
  across workflows; Cargo.lock no longer gitignored.

## [0.1.16] — 2026-07-22 — Critical Issues Resolution

This release addresses 5 critical functionality, reliability, and usability
issues identified in v0.1.15. Each issue has a per-issue patch file in
`patches/` for targeted review, plus a combined patch for one-shot apply.

### Issue 1: Reference Corpus Download & Persistence — Added

- **New `engine/reference_corpus/` package** — full download/persistence
  subsystem for bundled reference corpora.
  - `registry.py` — declarative catalogue of bundled references (BE06 with
    a real, pinned SHA-256; BNC Baby + arTenTen stubs for follow-up PRs)
  - `manifest.py` — JSON-backed manifest of installed references with
    atomic writes + corrupt-manifest recovery
  - `manager.py` — `ReferenceCorpusManager` with:
    * Resumable downloads (HTTP Range, `.part` suffix)
    * SHA-256 verification (download is rejected on mismatch)
    * Retry logic (3 attempts with 1/2/4s backoff)
    * Per-name async locks (concurrent requests share one download stream)
    * Cancellation (idempotent, checked between chunks)
    * Orphan cleanup (deletes files not in the manifest)
  - `keyness_bridge.py` — `compute_keyness_with_reference_list()` runs
    keyness against an installed reference frequency list (TSV/CSV/JSON),
    reusing the existing `compute_keyness_row` math so the results are
    identical to keyness against a full Corpus row.
- **New API endpoints** under `/api/v1/reference-corpora`:
  - `GET /` — list catalogue + install status
  - `GET /{name}/status` — poll download progress
  - `POST /{name}/download` — download + verify + install
  - `POST /{name}/cancel` — cancel in-flight download
  - `DELETE /{name}` — delete installed reference
  - `POST /cleanup-orphans` — clean stale files
  - `POST /corpora/{cid}/keyness-with-reference/{ref_name}` — keyness
    against an installed reference frequency list, with language-compat
    validation (422 on cross-language keyness)

### Issue 5: Export Functionality — Added

- **New `engine/export_queue/` package** — async export queue for large
  exports that would otherwise time out the synchronous endpoint.
  - `ExportJob` dataclass with full status tracking (queued/running/done/
    failed/cancelled) + progress (0..1) + result bytes
  - `ExportQueue` with semaphore-bounded concurrency (max 2 concurrent),
    per-job cancellation, 1-hour history retention, automatic cleanup
  - Format serializers for xlsx/csv/tsv/txt/json, all with:
    * **UTF-8 BOM on CSV/TSV** so Excel for Windows correctly detects
      UTF-8 (without it, Arabic/CJK in the data shows as mojibake)
    * NFC-normalized Unicode filenames, safe across Windows/macOS/Linux
    * Per-format MIME types
  - Producer registry pattern: lazy-registered adapters for the existing
    analysis functions (concordance/frequency/collocations/keyness/
    keyness_with_reference)
- **New API endpoints** under `/api/v1/export/jobs`:
  - `POST /` — enqueue, returns job ID immediately
  - `GET /` — list all jobs
  - `GET /{id}` — poll status
  - `GET /{id}/download` — stream finished bytes
  - `POST /{id}/cancel` — cancel in-flight job
  - `DELETE /{id}` — drop from history
- All existing synchronous export endpoints kept untouched for backwards
  compatibility.

### Issue 2: AI Assistant Stability + Dynamic Query Generation — Added

- **New `engine/ai/query_suggestions.py` module**:
  - `PREFABRICATED_QUERIES` — 16 research-question templates across 10
    categories (frequency, collocation, keyness, concordance, dispersion,
    ngrams, pos, compare, methodology, explore). Each template is
    **bilingual (English + Arabic)** and tagged with `requires_corpus` /
    `requires_reference` so the UI can grey out unavailable suggestions.
  - `generate_dynamic_queries()` — uses the existing `ModelProvider`
    abstraction to ask the LLM for context-aware follow-up questions.
    Strict JSON parsing tolerates ```json fences, caps at 8 suggestions,
    and returns `[]` on garbage input (never raises).
  - `has_reference_for_language()` — checks the Issue 1 manifest to mark
    keyness-related queries as available/greyed-out.
- **New API endpoints** under `/api/v1/ai`:
  - `GET /query-suggestions` — always-visible pre-fabricated queries with
    availability flags (respecting current corpus + reference state)
  - `POST /query-suggestions/dynamic` — LLM-generated follow-ups (best-
    effort; returns pre-fabricated only if LLM unavailable)
- The existing Ollama integration in `engine/ai/providers.py` (multi-URL
  health checks, proxy bypass, Qwen3 thinking-strip) is left untouched —
  it was already robust.

### Issue 4: Dark Mode Accessibility — Fixed

- **Audited every `--text-subtle` usage in dark mode** and fixed 7
  specific WCAG AA contrast failures:
  - `--text-subtle` bumped from `#6c7480` (4.18:1) to `#8b919e` (5.85:1)
  - `--text-muted` bumped from `#9aa3ad` to `#b3bac3` (6.9:1 on subtle bg)
  - `.status-chip.info` now uses dedicated `--info-bg/fg` tokens (5.4:1)
  - `.verify-badge.edited` no longer uses `--brand-600` (unreadable in
    dark mode) — uses `--ribbon-tab-fg-active` instead
  - `.evidence-list` content bumped to `--text-muted` + left accent border
  - `.engine-offline-banner` no longer uses 0.08-opacity red — solid
    `--danger-bg` for visibility
  - 8 small-text components (`.hint`, `.evidence-note`, `.empty`,
    `.status-idle`, `.msg-meta`, `.kwic-table .line-id`, `.status-sep`,
    `.ribbon-item-phase`) bumped from `--text-subtle` to `--text-muted`
- **New design tokens**: `--info-bg/fg/border`, `--notice-bg/fg`,
  `--danger-bg/fg`, `--success-bg/fg`
- **New `.cm-notification` component** with semantic variants
  (info/success/warning/error), each guaranteed AA contrast
- **New high-contrast mode** (`data-theme="dark-high-contrast"`)
  targeting WCAG AAA (7:1). Toggleable from Settings → Accessibility.
- Strengthened focus-visible ring in dark mode (2px solid `--brand-400`)
- Added CSS for the new Issue 1/2/5 components (`.reference-progress`,
  `.reference-card`, `.export-job-row`, `.query-suggestion`)

### Issue 3: Comprehensive Arabic Localization — Added

- **New `web/src/lib/arabic-glossary.ts`** — academic terminology
  glossary with 80+ entries covering:
  - Corpus linguistics core concepts (corpus, concordance, collocation,
    keyness, frequency, dispersion, token, type, TTR, lemma, POS tag,
    dependency parsing, n-gram, register, genre, annotation)
  - Statistical measures (log-likelihood, chi-square, mutual information,
    T-score, Dice, LogDice, log ratio, odds ratio, %DIFF, simple maths,
    Delta P, Juilland's D, Gries' DP, effect size, p-value)
  - Discourse analysis (CDA, metadiscourse, multimodal discourse, visual
    grammar, metafunctions, appraisal, semiotics, ideology, power
    relations, metaphor, conceptual metaphor theory, argumentation)
  - Arabic-specific NLP (normalization, alef/teh marbuta, diacritics,
    root patterns, dialect identification, MSA, Classical, Quranic)
  - AI/LLM terminology (grounded, ungrounded, tool call, evidence,
    citation, language model, LLM, inference, local inference, prompt,
    temperature, embedding, RAG)
  - Each entry includes English + Arabic + alternatives + reviewer notes
    citing sources (KACST, al-Masdi, Sinclair, McEnery & Hardie, Baker,
    Hyland, Kress & van Leeuwen, Martin & White, Lakoff & Johnson)
  - 3 exported helpers: `lookupTerm()`, `translateTerm()`,
    `translateTermsInText()` (for swapping English terms in column
    headers like "log-likelihood" → "الاحتمالية اللوغاريتمية")
- **Extended `web/src/lib/i18n.ts`** with 80+ new translation keys in
  BOTH `en` and `ar` sections covering: reference corpus UI (Issue 1),
  AI query suggestions (Issue 2), accessibility settings (Issue 4),
  export queue (Issue 5), and the notification component.
  - All Arabic translations use academic terminology from the glossary
    (e.g. `ref_install_title: "الدخائر المرجعية"`,
    `ai_suggestions_category_keyness: "الكلمة المفتاحية"`)

### Tests — Added

- **New `engine/tests/test_critical_issues.py`** with 24 critical-path
  tests covering all 5 issues (run in <2s without a running engine):
  - 6 tests for Issue 1 (manifest round-trip, corrupt-manifest recovery,
    unknown-reference, real-SHA-256, TSV loader, JSON loader)
  - 6 tests for Issue 5 (filename sanitizer, format serializers, UTF-8
    BOM, enqueue→done lifecycle, in-flight cancellation)
  - 5 tests for Issue 2 (bilingual coverage, required categories,
    JSON-fence parsing, garbage tolerance, 8-item cap)
  - 3 tests for Issue 3 (spec terms in glossary, Arabic chars in every
    entry, i18n keys present in both languages)
  - 2 tests for Issue 4 (high-contrast theme present, bumped
    `--text-subtle` value)
  - 2 smoke tests (all new modules + API routers import cleanly)

### Documentation — Added

- Patch files in `patches/` (one per issue + a combined patch)
- Implementation report (`IMPLEMENTATION_REPORT.md`) summarizing every
  change, decision, and known limitation

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
