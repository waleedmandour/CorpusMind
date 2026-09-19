# Changelog

All notable changes to CorpusMind are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once 1.0 ships. Until then, expect breaking changes between 0.x releases.

## [1.2.6] — 2026-09-19 — Multi-taxonomy Discourse page, floating-assistant alignment fix, resilience hardening, honest troubleshooting docs, Settings regrouping, green-button audit

This release answers one field report (the floating AI Assistant showing
responses "without proper alignment" in every analysis tool), one feature
request (other discourse taxonomies besides Hyland 2005, plus putting the
existing CLAWS semantic tagset to work), two Settings corrections (the
Gemini Interpretation card split, and a rule-by-rule green-button audit),
and ships the resilience work (502 for dropped Ollama connections, engine
self-heal) together with a rewritten, troubleshooting-first User Guide.

> Note: v1.2.6 was rebuilt before publication completed its rollout — the
> original build's Settings grouping (Gemini block inside the Smart
> Troubleshooting card) did not match the agreed design and three
> verification buttons carried non-white text on green. If you installed
> the first v1.2.6 build, reinstall this one (same version number, so
> there is no in-app update prompt).

### Added

- **Discourse page: four citable taxonomies behind a selector** (was
  Hyland-only). Every result names and cites its taxonomy so findings stay
  reportable and comparable across studies.
  - `hyland2005` — Hyland's interactive/interactional metadiscourse
    (unchanged default; a bodyless POST keeps the old behaviour, and the
    old response fields are unchanged).
  - `hallidayhasan1976` — Halliday & Hasan cohesion: reference pronouns,
    the four conjunction classes, and computed lexical-repetition chains
    across adjacent sentences. Substitution and ellipsis need parse-level
    analysis and are intentionally not covered (stated in the citation).
  - `martinwhite2005` — Martin & White Appraisal: engagement
    (entertain/attribute/deny/counter/proclaim), graduation-force
    intensifiers, and an inscribed-affect starter set. Invoked attitude is
    not covered (stated in the citation).
  - `usas` — the CLAWS-family USAS top-level semantic tagset (v1.2.0's
    bundled lexicon, CC BY-NC-SA 4.0) re-read as discourse-relevant
    features: each of the 24 top-level categories is annotated with a
    discourse-functional group (communication, cognition, emotion,
    politics, ...) and top matched lemmas; lexicon misses are honestly
    reported as `unmatched_percent` — still a lexicon lookup, NOT the
    licensed CLAWS/USAS tagger. Missing lexicon for the corpus language →
    HTTP 503; unknown taxonomy key → 400 with the supported list.
  - New endpoint `GET /corpora/{cid}/discourse/taxonomies` returns the
    registry (keys, display names, citations, category keys) so the UI
    selector and exports stay in sync with the engine.
  - Tests: 7 new (`engine/tests/test_v126_discourse_taxonomies.py`).

- **User Guide rebuilt (comprehensive but concise, EN + AR + in-app)** —
  new "Troubleshooting Common Issues" section documents the confirmed
  Grammarly/security-software × Ollama interference case (HTTP 500 on a
  fresh install; quitting the interfering app stops the errors), Ollama
  reachability (503), missing models (409 + the v1.2.2 tag-matching
  history), CPU embedding timeouts with the v1.2.5 chunking and env
  knobs, engine reachability and port/firewall guidance, the macOS
  window-lifecycle behaviour, Arabic/CAMeL prerequisites, and where the
  logs live. The guide body is refreshed to the v1.2.x feature set
  (Vector KWIC, Learner Research, multi-taxonomy Discourse, floating
  assistant) and tightened throughout; regenerated as
  `CorpusMind_User_Guide_v1.2.6.pdf` (EN) and
  `CorpusMind_User_Guide_Arabic_v1.2.6.pdf` (AR); the installer-bundled
  PDF is refreshed too. The in-app guide's Troubleshooting section gains
  the same common-issues list and documents the Settings-based Gemini key
  entry alongside the env-var path.

### Fixed

- **Floating AI Assistant responses were rendered without proper
  alignment in every analysis tool** — the drawer's message articles used
  bare role classes (`ai-drawer-msg assistant`), which ALSO matched the
  full Assistant view's page-layout rule
  `.assistant { display: grid; grid-template-columns: 260px 1fr;
  height: 100% }`. Each AI reply was therefore laid out as a two-column
  grid: the "ASSISTANT / grounded" header squeezed into a 260px column
  (visually invisible), the response text squeezed into the leftover
  narrow column, and `height: 100%` clipping the bubble under its own
  overflowing text — exactly the "narrow right column + stray text below
  the bubble" screenshot. Role modifiers are now namespaced
  (`ai-role-user` / `ai-role-assistant`) and cannot collide with
  page-level classes. Verified end-to-end with a scripted browser session
  against the dev engine reproducing the exact screenshot before/after.
- **Discourse examples without a sentence preview pushed the matched cue
  to the far edge of the panel** — the flex-grow evidence-id styling
  (shared with KWIC) only made sense when a preview followed it; the
  growth is now scoped out inside `.discourse-examples`.
- The PDF generator parsed `**bold**` but rendered literal `*asterisks*`
  for emphasis; single-asterisk emphasis now maps to italics, and the
  cover/footer/metadata version strings follow the release (they were
  still hardcoded v0.1.0).
- **Green buttons always carry white text** — the three verification
  actions (accept/reject/edit) rendered green/red text on the solid
  green `.btn-small` background (green-on-green / red-on-green); they
  are now ghost/outline buttons with themed borders, consistent with
  the other secondary controls. A rule-by-rule audit of every
  green-background rule in the app's stylesheet (39 rules) confirmed
  every other text-bearing green button — primary/small/toolbar/search/
  run/onboarding/source-tab buttons, badges, and the user message bubble
  — already renders white text; the only non-text match (the toggle
  switch slider) contains no text by design.

### Changed

- **Settings: "Gemini Interpretation" is its own card, and "Smart
  Troubleshooting" + "Mute Notifications" share one card** — the Gemini
  status/consent/API-key entry gets a dedicated block, while error
  detection, its explanation, and the mute toggle live together, with
  the card badge switching between Active and Muted (v1.2.6 rebuild per
  user request; supersedes the earlier same-card reorder, which had put
  the Gemini block at the top of the troubleshooting card).
- **Resilience hardening shipped** (carried over from the unreleased
  work): embed transport retries now cover ANY dropped Ollama connection
  (`httpx.TransportError` — `RemoteProtocolError`, `ConnectError`,
  `ReadError`), not just timeouts; an exhausted non-timeout budget raises
  `EmbeddingConnectionError` → semantic
  `EmbeddingModelUnreachableError` → **HTTP 502 `embedding_unreachable`**
  with a restart hint, reserving the 409 "run ollama pull" for genuinely
  missing models. New `ensure_engine` Tauri command probes backend health
  and restarts ONLY what is down; the frontend auto-invokes it on
  connection errors and retries once; boot health-wait extended 60s →
  120s (antivirus + PyInstaller one-file extraction). Vector KWIC shows a
  friendly 502 card (EN/AR) mirroring the 503 card.

### Tests

- **Engine: 447 passed, 9 skipped** (the 9 are the pre-existing
  environmental `en_core_web_sm` skips), 0 failed — includes the 7 new
  multi-taxonomy discourse tests.
- **Ruff**: All checks passed (0.16.8).
- **Web typecheck (tsc) + build**: passed.

## [1.2.5] — 2026-09-17 — Engine/Ollama lifecycle fix (macOS), CPU-friendly embedding, connection self-healing

Three field reports, three fronts. First: "the engine and Ollama keep
disconnecting from the app" — a process-lifecycle bug in the desktop
shell, not anything flaky in the engine, in Ollama, or on the network.
Second (Windows 11, CPU-only): a search could still time out even right
after a successful warm-up — a batch-size problem that only hosts running
Ollama on CPU could hit. Third (same machine): a dropped Ollama connection
surfaced as the misleading 409 "Run: ollama pull bge-m3" while the engine
itself intermittently failed with a raw reqwest error and no recovery.

### Fixed

- **Desktop shell killed the engine and Ollama whenever the window was
  closed (macOS)** — a process-lifecycle bug, not a network one. The
  Tauri shell registered two shutdown hooks: one on
  `WindowEvent::Destroyed` (kept from earlier as a "fallback") and one on
  the run-loop's `ExitRequested`/`Exit` events. On macOS, closing the
  window destroys the window while the app itself keeps running in the
  dock — the framework neither exits nor fires the exit events — so the
  `Destroyed` fallback silently killed a live engine AND a live
  `ollama serve`, leaving the app with a dead backend until a full quit +
  relaunch. That is why "the engine and Ollama keep disconnecting" hit
  Vector KWIC and every other feature at once, and only "from time to
  time": it followed how the window was closed, not anything flaky in
  the engine or in Ollama. The `Destroyed` hook is gone; real quits
  (Cmd+Q, Quit menu, programmatic exit) still clean up via the run-loop
  handler on every platform. New on macOS: clicking the dock icon with
  no window recreates the main window and, only if a backend is
  actually down (health-probe first), restarts it — so a plain
  dock-click can never flush a warm bge-m3 from memory.

- **A warm model + a big search could still time out on CPU-only hosts
  (Windows 11 field report)** — Vector KWIC embeds up to 1500 context
  windows, and they all went out as ONE `/api/embed` request. On a
  CPU-only Ollama (the common case on Windows machines without GPU
  compute) that single request needs minutes to answer even when the
  model is resident in RAM, so the client ReadTimeout fired — and the
  automatic retry queued behind the still-running first attempt,
  guaranteeing a second timeout and a misleading "press Warm up model"
  hint. Large batches are now split into sequential sub-requests of 64
  texts each (override with `CORPUSMIND_EMBED_BATCH`, floor 1), keeping
  every request in the seconds range on CPU, with results concatenated
  in unchanged order. The timeout error now reports the request size
  and names both causes (cold load vs warm-large-batch-on-CPU), and the
  503 hint offers narrowing the search or raising
  `CORPUSMIND_EMBED_TIMEOUT_S` instead of telling a user who just
  warmed the model to warm it again.

- **A dropped Ollama connection masqueraded as a missing model (409
  "Run: ollama pull bge-m3")** — when Ollama crashes or restarts under
  RAM pressure mid-embed, the client sees `RemoteProtocolError: Server
  disconnected without sending a response`. That is neither a timeout
  nor a 404, so it fell into the generic error bucket and the API
  answered 409 `embedding_model_missing` — wrong advice when the model
  IS installed (the `/api/tags` pre-flight had already passed). Embeds
  now retry once on ANY connection-level transport error (dropped
  connection, refused dial, read error — not just timeouts), and an
  exhausted budget raises a typed error the API answers as **502
  `embedding_unreachable`**: "Ollama may have crashed, restarted, or is
  not running — start it, press Warm up model, run the search again;
  the model is installed, no pull is needed." The Vector KWIC panel
  renders it as a friendly card with a re-run button, mirroring the
  503 warm-up card.

- **The engine now self-heals on every platform** — a connection
  failure from the webview ("error sending request for url
  http://127.0.0.1:8765/…") used to surface raw and stay broken until
  the user clicked Restart engine. A new `ensure_engine` shell command
  probes `/api/v1/health` and restarts the sidecar ONLY if it is
  genuinely down; the frontend asks for it automatically on any
  connection error and retries the request once, showing an actionable
  message instead of plugin internals. The boot health-wait also rose
  from 60 s to 120 s — on Windows, real-time antivirus scanning the
  ~700-file PyInstaller one-file tree can outrun a minute on slow
  disks, and every click during that window used to fail.

### Changed

- **Settings**: the “Gemini interpretation” block (API key + consent)
  moved above the Smart Troubleshooting explanation, so the key input is
  the first thing on the card (user request).

## [1.2.4] — 2026-09-17 — Embedding model management: warm-up in the app, model deletion, nomic-embed-text for Vector KWIC, tunable timeout

A follow-up to v1.2.3's honest `503 embedding_timeout`: a host whose cold
bge-m3 load exceeds even the 120 s × 2 attempts got truthful advice but had
to open a terminal to act on it. This release moves all of that into the
app and adds the model-management basics users expect.

### Added

- **In-app "Warm up model"** — the Vector KWIC panel gains a Warm up button
  (with a progress state: "Loading model into memory… first run can take
  several minutes"). Backed by `POST /api/v1/ollama/warmup` +
  `/ollama/warmup/status` (background task + polling, the pull-flow
  pattern) with a single generous 1800 s attempt — no retry needed, Ollama
  keeps loading between attempts. When a search still times out, the panel
  no longer dumps the raw 503 JSON: it shows a friendly card explaining
  the cold load, with the warm-up button right inside it.
  *Downloading an embedding model now auto-warms it on success*, so the
  first real search never pays the cold load (text LLMs are deliberately
  NOT auto-warmed — loading a multi-GB chat model into RAM uninvited would
  be rude).
- **Delete downloaded models** — Settings → Models shows an ✕ button next
  to every Installed model (curated and Hugging Face rows alike). A
  confirmation dialog ("Delete {model} from Ollama? This frees its disk
  space. You can re-download it anytime.") guards the action, backed by
  `DELETE /api/v1/ollama/models` → Ollama `DELETE /api/delete`; deleting
  an already-removed model answers 404 instead of a generic error.
- **Vector KWIC embedding-model selector** — the panel's form now includes
  a model dropdown: **bge-m3** (multilingual, strong Arabic, ~1.2 GB) or
  **nomic-embed-text** (English-focused, ~0.27 GB, loads several times
  faster) — the engine's request → settings → bge-m3 chain has accepted
  an explicit model since v1.2.0; the UI just never exposed it. Selecting
  nomic-embed-text on an English-only corpus is the fastest fix for
  slow-to-load hosts; the 409 setup card pulls whatever model is selected.
- **`CORPUSMIND_EMBED_TIMEOUT_S`** — the embed timeout is now tunable via
  environment variable (seconds, 30 s floor, default 120) in both the
  Ollama provider and the Vector KWIC embed path, for hosts whose cold
  load legitimately needs more than the default (field report: >4 minutes
  on a low-RAM machine).

### Changed

- The 503 `embedding_timeout` hint now points at the in-app Warm up
  button first (the `warmup_cmd` remains for terminal users).

## [1.2.3] — 2026-09-17 — Vector KWIC cold-start timeouts, Smart Troubleshooting out of the box, citation clarity, analysis tool cards

A follow-up patch release to v1.2.2, driven by more first-run feedback:
Vector KWIC could still fail with the familiar 409 even when the model
was correctly installed — this time from a different code path — and
three usability issues were addressed at the same time.

### Fixed

- **Vector KWIC 409 on a cold embedding model (the second 409 path)** —
  on v1.2.2, a request for `bge-m3` could pass the fixed pre-flight and
  then *still* fail with 409 `embedding_model_missing` and the note
  "[ollama] embed failed: " (empty error). Root cause: the provider's
  embed call used the legacy `/api/embeddings` endpoint with a 30-second
  timeout, no retry, and one text per HTTP call. The *first* embed on a
  cold Ollama has to load the ~1.2 GB model into RAM, which frequently
  exceeds 30 seconds; httpx timeout exceptions stringify to an empty
  message, and the engine misclassified the resulting failure as
  "model missing" with a misleading "ollama pull" hint. The provider now
  uses the modern batch `POST /api/embed` endpoint with a request-level
  `keep_alive` (default 30 minutes, tunable via
  `CORPUSMIND_OLLAMA_EMBED_KEEP_ALIVE`), a 120-second timeout, and one
  automatic retry on timeout; Ollama versions older than 0.1.32 fall
  back to the legacy endpoint. Timeout failures are now typed end to end
  and answered as HTTP 503 `embedding_timeout` with an actionable hint
  and a ready-to-run warm-up command, while a genuinely missing model
  still returns 409. Vector KWIC embeds whole batches per call instead
  of one request per text. Regression-tested with a real-TCP fake Ollama
  (`tests/test_v123_embed_timeout.py`): batch payload + keep-alive,
  retry-then-succeed, typed non-empty timeout errors, legacy fallback,
  and the API-level 503 mapping.
  *Immediate workaround on any version:* warm the model once with
  `curl http://localhost:11434/api/embed -d '{"model":"bge-m3","input":"warmup"}'`
  (first call loads it, 1–2 minutes), or set `OLLAMA_KEEP_ALIVE=30m`.

### Changed

- **Smart Troubleshooting is now visible out of the box** — the
  troubleshooting bar ships muted by default (a default inherited from
  the repository's history), so the badge never appeared and the panel
  had no reachable entry point while muted, even though errors were
  still being captured silently. New installs now start unmuted, and
  existing installs are migrated once on upgrade (a plain default change
  would never reach them through persisted localStorage state). The
  Command Palette gains "Open Smart Troubleshooting" and a mute/unmute
  toggle, so the bar can always be summoned or silenced from the
  keyboard.

### Added

- **Analysis tools as interactive colored cards** — the horizontal tool
  strip at the top of the Analyze view (Concordance, Vector KWIC,
  Frequency, Keywords, N-grams, Collocations, Dispersion, Readability,
  …) is now a grid of colored, theme-aware cards instead of flat tabs.
  Card colors come from 24 new hue tokens per theme (light and dark), so
  they match the rest of the interface in both themes; labels reuse the
  sidebar's bilingual (EN/AR) i18n keys; and the card order mirrors the
  Analyze group in the sidebar one-to-one. Clicking a card switches
  tools and syncs the sidebar highlight; the Concordance card navigates
  to the full Concordancer view.

### Documentation

- **Anthony (2025) citation spelled out** — the Vector KWIC footnote
  abbreviated the journal as "ACL 5(3)", which reads like the ACL
  conference. The citation now reads "Anthony 2025, Applied Corpus
  Linguistics 5(3): 100164" with the DOI
  (doi.org/10.1016/j.acorp.2025.100164) in the UI (EN/AR), the About
  acknowledgements (adding Laurence Anthony), the User Guide, and the
  project homepage.

## [1.2.2] — 2026-09-16 — Vector KWIC 409 after a successful model pull

A one-fix patch release: on v1.2.1, Vector KWIC could still reject a
request with HTTP 409 `embedding_model_missing` immediately after the
embedding model had been pulled successfully through Settings.

### Fixed

- **Vector KWIC 409 after a successful pull (`bge-m3`, `nomic-embed-text`)** —
  v1.2.1 taught the engine-internal check and the Settings model list to
  compare model names canonically (so a request for `bge-m3` matches
  Ollama's installed `bge-m3:latest`), but one exact-string comparison
  was missed: the cheap pre-flight in the API layer, which runs before
  the engine code and can answer 409 on its own. A real Ollama reports
  installed models with the implicit `:latest` tag, so requesting the
  bare catalogue name still failed there with `embedding_model_missing`
  ("Run: ollama pull bge-m3") even right after a successful download —
  the same 409-after-successful-pull symptom v1.2.1 was meant to fix.
  The pre-flight now canonicalises both sides of the comparison,
  mirroring the v1.2.1 fix. A regression test with a tag-reporting
  provider double (`test_vector_kwic_untagged_pull_matches_bare_model`)
  locks the behaviour in; the in-app model download really did succeed,
  so no re-download is needed after updating.

## [1.2.1] — 2026-09-15 — Model-download fixes, HF catalogue repair, UI polish

A patch release driven by first-run feedback on v1.2.0: the two new
embedding models could not actually be downloaded through the app, the new
Hugging Face explorer showed nothing, and several UI details were below
the app's usual polish bar. This release also completes the Lens
separation: **CorpusMind Lens is no longer built, shipped, or referenced
as a shell in this repository** — it lives in its own repository
(`waleedmandour/CorpusMind-Lens`) and stays fully functional there.

### Fixed

- **Embedding-model downloads (bge-m3, nomic-embed-text)** — a successful
  pull could never be recognised by the app:
  * Ollama registers untagged pulls as `bge-m3:latest`, but every
    "is it installed?" comparison used exact string matching against the
    catalogue's bare `bge-m3`, so Settings never showed the model as
    *Installed* and the Vector KWIC pre-flight kept returning HTTP 409
    ("Run: ollama pull bge-m3") even right after a successful download.
    Comparisons now go through a canonical name helper that strips the
    implicit `:latest` tag (engine pre-flight + the Settings model list).
  * The pull endpoint swallowed every Ollama error: `{"error": ...}`
    progress lines were ignored, non-200 responses were never checked, and
    the stream always ended as `status: "success"`. Failed downloads now
    surface the real error message in Settings, and the progress bar no
    longer resets to 0% on the final stream line.
  * The pull request now uses the modern `{"model": ..., "stream": true}`
    payload (the `name` field is deprecated) and bypasses system proxies
    for loopback traffic, matching the Ollama provider's behaviour.
- **Hugging Face models not showing at all** — three compounding bugs in
  the new `hf_catalog` explorer:
  * the per-repo detail fetches ran on an already-closed HTTP client, so
    every repo was silently skipped and the tab stayed empty no matter
    what the user searched;
  * an empty search box short-circuited to "no results" — the tab now
    *browses* the most-downloaded GGUF repositories on open (and seeds an
    `embed` search for the Embedding task chip);
  * the quantisation regex missed the most common K-quants (Q4_K_M, Q6_K,
    IQ4_XS, …), so most variants lost their quant label and would have
    pulled the repo default instead of the selected quantisation.

### Changed

- **Typography scaled up professionally** — every explicit font size in
  the stylesheet (411 rules) and all inline component sizes (70) were
  increased by one consistent +10% step (e.g. 14→15px, 12→13px, 16→18px),
  preserving the entire type hierarchy.
- **Corpus list: the bare "✕" next to the Active/Reference badge is now a
  proper, labelled *Delete* button** (danger-outlined, localised EN/AR,
  same confirmation dialog, same action) on both the Your Corpus and
  Reference Corpus pages; the badge itself is now styled.

### Removed

- **CorpusMind Lens is no longer part of this repository**: the
  `desktop-lens/` Tauri shell, its three release jobs and CI job, the
  `?shell=lens` frontend mode (`isLensMode`, `LENS_NAV_TARGETS`, lens
  onboarding pages, lens branding/icons), and the orphaned vision views
  (`VisionView`, `VisionCorporaView`) are gone. Release pages now contain
  ONLY CorpusMind installers — no more Lens/companion `.exe` confusion.
  The engine's Companion-Mode contract with the separate Lens app
  (`GET /corpora/{id}`, `GET /corpora/{id}/frequency`, `GET /health`) is
  untouched, and the app icon no longer carries the green border.

## [1.2.0] — 2026-09-15 — Learner Research, Vector KWIC, and the companion-first redesign

With v1.1.0 out, the vision workbench moves fully into its home in the
**CorpusMind Lens** companion, and the main app gains what it was missing
for learner-corpus research: a **Learner Research** suite (CAF battery,
Contrastive Interlanguage Analysis, rule-based error candidates), a
**Vector KWIC** tool grounded in Anthony (2025), a **Hugging Face GGUF
explorer** in Settings, and Arabic normalization as a first-class toggle
across the search tools. The welcome flow is now companion-first and fully
bilingual.

### Added

- **Learner Research** — a new sidebar group (`أبحاث لغة المتعلم`) with three
  tools grounded in current literature (Housen & Kuiken 2009; the CAF volume
  2022; Lu 2012; Granger 1998; ERRANT-lineage annotation incl. 2024–25
  multilingual work):
  * **CAF Report** (`learner-caf`): Complexity–Accuracy–Fluency battery per
    corpus or per learner facet. Lexical diversity: TTR + MATTR, MTLD, and
    the new **HD-D** (McCarthy & Jarvis 2010, exact hypergeometric
    recurrence) in `stats/measures.py`. Syntactic complexity (EN, via the
    dependency parser): mean sentence/clause length, clauses per sentence;
    AR: sentence-length + morphological-richness proxies. Accuracy is an
    honestly-labelled heuristic proxy (error-free-sentence rate from the
    rule detectors; AR spelling-candidate rate). Sentence-length
    distribution histogram. Exportable index table with formulas +
    citations.
  * **CIA Compare** (`learner-compare`): guided Contrastive Interlanguage
    Analysis — learner corpus vs reference corpus (reusing the
    language-matched keyness machinery, DB or bundled reference), L1 group
    vs L1 group, and CAF deltas — one combined, exportable report.
  * **Error-pattern finder** (`learner-errors`): rule-based error
    *candidates* (framed like metaphor candidates — human verification
    required, `verified_count` stays 0): EN articles/prepositions/
    agreement/spelling; AR hamza variants, ة/ه and ى/ي confusions. Candidate
    lines + counts + export.
  * **Learner metadata facets**: optional `L1` + CEFR `proficiency`
    (A1–C2) fields at corpus creation (idempotent column migration);
    group-by L1/level across all three panels; document-level overrides via
    the existing `Document.meta` mechanism (ALC-style corpora).
  * **AI-vs-learner comparator (light)**: paste an AI-produced text → the
    same CAF battery runs on it → side-by-side delta table
    (`POST /api/v1/learner/caf-text`), responding to the 2025
    LLM-vs-learner-writing literature.
- **Vector KWIC** (`POST /api/v1/corpora/{cid}/concordance/vector`) —
  semantic concordancing following Anthony, L. (2025). "Concordancing with
  AI: Applications of word and sentence embeddings." *Applied Corpus
  Linguistics* 5(3), 100164. Mode A: keyword KWIC re-ranked by cosine
  similarity between each line's context embedding and the query. Mode B:
  no node word → top-k most similar sentences (scan capped at 6,000, cap
  reported). Model chain request → setting → env → **bge-m3** (multilingual,
  strong Arabic). Missing model → HTTP **409** with a one-click setup hint
  that pulls the model through the normal Ollama flow. Vectors cached in a
  new `kwic_vector_cache` table, reused only per exact model + context
  window. Pure-Python cosine, similarities rounded to 4; the response
  carries an explicit "raw cosine, no confidence claim" note. New
  **Vector KWIC** tab in Analysis Tools with a Similarity column and
  similarity-aware export. `tests/test_vector_kwic.py` runs the full
  pipeline against a deterministic mock embedder (7 tests).
- **Hugging Face GGUF explorer** (Settings → Models): live HF search
  (`GET /api/v1/ollama/catalogue?source=huggingface&query=…&task=…`,
  sorted by downloads; results only after a query is typed — the Lens
  pattern), real per-quant file sizes via the blobs API, quant-variant
  picker (Q4_K_M → Q4_K_S → Q4_0 → Q5_K_M → Q8_0 …), machine-aware
  rule-of-thumb **fit badges** (gpu / cpu / tight / too-big) computed from
  actual RAM (stdlib probe) and VRAM (nvidia-smi when present), task filter
  chips (all / text / embedding), empty-state hint. Pulls reuse the
  existing `/ollama/pull` progress flow — `hf.co/<user>/<repo>:<quant>`
  resolves natively through Ollama. Ported from CorpusMind Lens v0.3.2
  (`engine/ai/hf_catalog.py`).
- **Arabic normalization everywhere** (item 6): an "Arabic normalization"
  toggle on the Concordancer, Frequency, Collocation, and Keyness tools
  (strip diacritics; unify أ إ آ → ا, ة → ه, ى → ي). Implemented twice, in
  lockstep: a SQL `arnorm()` scalar function (registered on every
  connection) for aggregation paths, and a Python `ar_norm()` mirror for
  matching paths — documented in METHODOLOGY.md. Vector KWIC accepts the
  same flag before embedding.
- **Companion-first onboarding**: a 4th welcome page ("Go multimodal &
  audio") presenting **CorpusMind Lens** (vision-LM multimodal discourse
  analysis) and **CorpusMind Voice** (audio-to-corpus) with buttons opening
  their pages on waleedmandour.org in the system browser (AboutView's
  plain-anchor mechanism). All main-app onboarding pages were hardcoded
  English — they are now fully i18n (`onb_main_*`) with complete Arabic
  translations, and the stale "Click Projects in the sidebar" step is
  rewritten to "Open Corpus and upload texts" (no such nav item existed).
- **Floating AI assistant improvements**: the assistant drawer is widened
  from 390 px to 560 px (720 px tall, viewport-capped; small-screen media
  query) and now renders responses with `pre-wrap` + long-token wrapping so
  LLM output is readable instead of squeezed into a narrow column. The
  FAB is available on the new Learner Research and Vector KWIC screens
  automatically (global mount), and the view-context labeler now maps
  hyphenated nav ids to their i18n keys (it previously displayed raw ids
  like "corpus-target").
- **2-page PDF quick-start guide** (`download/CorpusMind_User_Guide_v1.2.0.pdf`,
  regenerated via `scripts/generate_user_guide_pdf_v120.py`) covering
  corpora, analysis tools incl. Vector KWIC, Learner Research, companion
  apps, and the HF explorer. The guide ships **inside every installer**
  (bundled as a Tauri resource in both desktop shells) and is attached to
  the GitHub Release next to the installers.
- **Multi-platform release pipeline** (`.github/workflows/release.yml`):
  tag-gated builds for **Windows (NSIS .exe + WiX .msi), Linux (.deb +
  .AppImage), macOS Apple Silicon (.dmg) and macOS Intel (.dmg — new
  `macos-intel` job on `macos-15-intel`)**, each bundling the PyInstaller
  engine sidecar + the User Guide PDF; Lens installers build on every tag
  too; a SHA256SUMS manifest and the guide PDF are attached last.
  The legacy dispatch-only `build-release.yml` is removed (superseded).

### Changed

- **Vision Suite tab removed (thorough)**: the parent-app sidebar group +
  item, the `vision` nav target/route, the Home quick card, and the
  "Go to Vision Suite" palette command are gone; the User Guide section is
  replaced by "Companion Apps". Stale persisted targets auto-redirect via
  the Lens guard (same safe migration as v1.1.0). **Kept**: `VisionView.tsx`
  (it exports shared panels consumed by `VisionCorporaView`), every engine
  vision endpoint (the Lens companion depends on them), and all `vision_*`
  i18n content keys.
- **Settings model catalogue**: vision models (qwen3-vl, moondream,
  llama3.2-vision) are de-surfaced from `RECOMMENDED_OLLAMA_MODELS` — they
  remain in Lens's own catalogue; **bge-m3** is added as the recommended
  embedding model (feeding Vector KWIC) alongside nomic-embed-text; every
  entry carries a `task` tag. The Facial-Analysis ethics card stays (it is
  consent, not a model card).
- Readability stays honest for Arabic: LIX/RIX (script-generic) plus
  word-length / average-sentence-length descriptive stats, labelled as
  such rather than dressed up as validated Arabic readability formulas.
- Version strings synchronized across engine, web, desktop shells, docker
  image tag and CITATION.cff.

### Fixed

- Floating-assistant context labels synthesized non-existent i18n keys for
  hyphenated nav ids (`nav_corpus-target`) — ids are now normalized to the
  underscore key convention.
- Onboarding step 1 referenced a "Projects" sidebar item that does not
  exist (see above).
- **Release gate restored**: 22 ruff violations in the new v1.2.0 modules
  (`learner/`, `semantic/vector_kwic.py`, `ai/hf_catalog.py`, tests) failed
  the lint step of every CI/release gate; all fixed (`ruff check .` clean).
- **Docker / wheel packaging**: `learner` and `semantic` were missing from
  `[tool.hatch.build.targets.wheel] packages`, so the Dockerized engine
  crashed at boot with `ModuleNotFoundError: No module named 'learner'`.
  Both packages are now declared and verified by a wheel smoke build.
- Workflow corruption from the v1.2.0 commit (`[main]` → `ain]`,
  `[math]::Round` → `ath]::Round`) repaired; `scripts/build-macos-arm64.sh`
  now stages the PyInstaller **onedir** sidecar directory (it previously
  expected a stale onefile layout and aborted).

## [1.1.0] — 2026-09-07 — Your Vision Corpora: the merged workbench + the visual-linguistics battery

Lens's two top-level tabs ("Your Corpora" and "Your Vision") split one
workflow across two views — the same image sets were managed in one tab and
analysed in another, with duplicated pickers, dropzones and grids. This
release merges them into a single **"Your Vision Corpora"** workbench and
gives the visual side what corpus linguistics has for text: a research-
grounded annotation scheme plus the standard measurement battery computed
over it. The engine's ingest pipeline is also fixed to match how
researchers actually work on local machines. **The main CorpusMind app is
unchanged** — every UI change is Lens-gated or additive.

### Added

- **"Your Vision Corpora" (Lens)**: `VisionCorporaView` — corpus list +
  set management (provenance notes, export, delete) + four workflow tabs:
  *Overview* (set statistics + coverage), *Corpus* (upload, grid, metadata,
  tags, annotations), *Measures* (the linguistic battery), and *Vision
  Analysis* (VLM describe, visual grammar, discourse lenses, alignment,
  opt-in facial analysis, batch runner/view). The former `LensCorporaView`
  is retired; `VisionView` remains for the main app and its panels are
  shared components.
- **Five-dimension visual annotation framework** (research-grounded, EN+AR,
  schema served by the engine — single source of truth for the UI):
  *Visual Morphology* (Cohn 2013; 12 categories), *Attentional Framing*
  (Kress & van Leeuwen 2006; Bateman 2008; 15), *Filmic Shot Scale*
  (social-distance mapping; 8), *Path Structure and Transitions*
  (McCloud 1993; Halliday & Hasan 1976; 10), and *Multimodal Integration*
  (Barthes 1977; Royce 2007; 9). Multi-select values + annotator notes per
  dimension; unknown category ids are rejected (a typo never corrupts a
  corpus). Annotations live in `Image.meta` — zero DB migration.
- **Corpus-linguistics battery over visual annotations** (reuses the §12
  formulas in `stats/measures.py` — the exact code the text side uses):
  frequency profile per dimension, diversity battery (TTR, Guiraud, MATTR,
  STTR), sequence n-grams over the reading order (chains of shot scales or
  transitions, optional `<gap>` surfacing), co-occurrence association
  between dimensions (MI, t-score, Dice, log-Dice, ΔP, G²), set-vs-set
  keyness (full battery, LL-ranked), dispersion (Juilland's D, Gries' DP/
  DP-norm with per-bin histograms), and a visual KWIC (sequence
  concordance with left/right context).
- **Free multi-value researcher tags** on images (per-image and bulk, add/
  replace modes) — the tagging capability the single-value IPTC fields
  could not express.
- **Image-set-count badge on Lens corpus rows** (issue #8): every corpus
  row in the "Your Vision Corpora" list now carries a badge with the number
  of image sets attached (icon + count, EN+AR tooltip via `vc_sets_badge`),
  and corpora with image sets sort first (stable — created_at-desc order
  preserved within each group), so text-only corpora no longer read the
  same as image-bearing ones. Engine: additive `image_set_count` on
  `CorpusOut` (list + detail endpoints).
- **Upload OCR-language control**: per-upload override + corpus-language
  resolution (Arabic corpora OCR with `ara+eng`); the resolved language is
  recorded in the cached analysis.
- **Re-analysis path**: `POST /images/{id}/reanalyse` and the batch runner's
  new `analyse` action (gap-filling by default, `refresh=true` re-runs) —
  if Tesseract or a language pack was missing at ingest, OCR is no longer
  empty forever. Cached LLM results are preserved.

### Fixed

- **Upload event-loop blocking**: the synchronous Pillow/Tesseract/numpy
  analysis now runs in a worker thread (`asyncio.to_thread`) — batch
  ingest no longer freezes the whole engine.
- **Upload all-or-nothing failure**: one bad file aborted (and rolled back)
  the entire batch; failures are now isolated per file and reported
  (`{uploaded, failed}` response, surfaced in the UI).
- **At-rest encryption gap**: uploads wrote plaintext while every read path
  decrypted — writes now go through `encrypt_file` when
  `CORPUSMIND_ENCRYPTION_KEY` is set (verified by round-trip test).
- **`list_image_sets` N+1 query** (pipeline review): the route ran one
  COUNT query per set (1 + S queries per request), noticeable on corpora
  with many sets on a researcher laptop. Now a single GROUP BY aggregate
  join — one query per request, counts verified identical by a regression
  test (upload and delete paths).
- **`list_corpora` N+1 query** (issue #8 follow-through): the route ran one
  COUNT query per corpus; now two GROUP BY aggregates (documents, image
  sets) per request regardless of corpus count — verified by a regression
  test covering zero/many/deleted cases and the detail endpoint.
- **Lens icon reverted** to the "CorpusMind" mark with the blue surround
  (per maintainer decision — the purpose-made aperture-eye icon shipped in
  the v1.0.9 re-issue is retired).

### Release housekeeping

- Deleted stale release pages `v0.1.25`, `v0.1.26`, `v0.1.27` with all
  their artifacts (tag commits preserved in main history).

## [1.0.9] — 2026-09-07 — CorpusMind Lens: the image-corpus workbench (re-issued)

Lens's corpus layer was inherited verbatim from the text app: its "Corpora"
section offered a text uploader, POS tagsets, text cleaning, a tokenize → tag
→ parse compile gate, and a tokens/types/TTR dashboard — none of which mean
anything for an image corpus. This round rebuilds the visual side's scholarly
apparatus to match corpus-linguistics practice for multimodal corpora
(CLARIN multimodal resource family; CASS corpus-methods-for-multimodal-data;
IPTC photo-metadata standards). **The main CorpusMind app's behaviour is
unchanged** — every UI change is Lens-gated or additive.

### Added

- **Image Corpora view (Lens)**: a dedicated `LensCorporaView` replaces the
  text view in Lens mode — image sets as first-class corpus cards with
  provenance/sampling notes, set-level statistics (formats, orientation mix,
  resolution and date ranges, OCR/caption/VLM/metadata coverage, genre and
  source distributions), genre filtering, and one-click entry to the Vision
  Suite.
- **Image metadata (IPTC-Core-aligned)**: per-image source/publication, date,
  licence/rights, genre, language of embedded text, and notes — editable per
  image or in bulk ("Tag All Images"); non-destructive merge; the
  machine-extracted blocks are never user-overwritable.
- **EXIF/XMP extraction at ingest** (`vision/image_meta.py`): Pillow-based
  EXIF (camera, dates) + XMP/IPTC-Core packet scan (headline, creator,
  rights, usage terms, keywords). **GPS coordinates are deliberately never
  extracted** (research-ethics default).
- **OCR Corpus Tools** (Lens): KWIC-style search over OCR text + captions
  with match counts and context windows; a word-frequency list with the
  engine's shared EN/AR stopword lists and minimum-length control; and
  set-vs-set keyword comparison — the full keyness battery
  (log-likelihood, log ratio, chi-square, odds ratio, % diff, simple maths)
  ranked by log-likelihood.
- **OCR corpus export**: the set's text as a `<doc>`-marked corpus file
  (filename + caption + metadata attributes per image) or structured JSON —
  so the visual side's text can be analysed with the main app's full text
  tooling. This closes the cross-modal loop.
- **Facial analysis opt-in UI (§18)**: Settings → Ethics → Facial Analysis
  toggle (persisted marker in the data directory; env override respected),
  plus an in-drawer facial-analysis panel. The backend, redaction gate and
  API wrapper existed since Phase 5 — the UI and the promised Settings
  toggle did not.
- **Vision-aware AI suggestions**: `/query-suggestions?shell=lens` serves a
  vision catalogue first (set overview, OCR vocabulary, Visual Grammar
  patterns, cross-modal comparison, model setup); the Lens Assistant passes
  the shell and uses a vision-aware input placeholder.
- **Pagination** for image grids (engine `limit`/`offset` +
  `X-Total-Count`, exposed via CORS) with load-more in both the Vision grid
  and the Lens corpora grid.

### Fixed

- **Set/image deletion failed silently in the desktop shell**: VisionView
  still used `window.confirm`, which trips the Tauri ACL (the same bug fixed
  for corpus deletes in v0.1.19). Both deletes now use ConfirmDialog, and
  delete failures surface on the card instead of vanishing.
- **The Lens boundary was cosmetic**: `setActiveNav` accepted any navigation
  target, so Home's text-tool cards opened views the Lens sidebar hides. The
  Lens shell now enforces its navigation set (out-of-scope targets redirect
  to Vision), Home shows Lens-aware quick actions, and the hardcoded
  suite-wide stat tiles are hidden in Lens.
- **Arabic typos**: "الدخيرة" → "الذخيرة" (30 occurrences across UI +
  engine suggestion catalogue); "ال تأطير" → "التأطير"; the discourse-lens
  framework dropdown label "Lens" (colliding with the product name) is now
  "Framework" / "الإطار".
- **Lens onboarding was English-only**: the entire Lens onboarding flow is
  now i18n'd (en/ar) and describes the Image Corpora workflow; footer
  buttons (Back/Skip/Next/Get Started) are translated too.
- **TIFF/BMP support mismatch**: the engine accepted TIFF and BMP but the
  file pickers silently excluded them; both pickers now match the engine.
- **Docs accuracy**: USER_GUIDE.md (EN/AR) section 8 described the Vision
  Suite as "Coming Soon"; it now documents the shipped Vision Suite and the
  Lens image-corpus workflow (incl. metadata, OCR corpus tools, ethics).

### Technical

- Engine: `ImageSet.description` + `Image.meta` columns with an idempotent
  PRAGMA-based migration for existing data directories; new endpoints
  (PATCH image-set / image, bulk metadata, set stats, OCR search /
  frequency / keyness / corpus); facial opt-in persistence; 14 new engine
  tests (suite: 352 passed).
- Web: `LensCorporaView` (new), Lens-gated `App.tsx` / `ui.ts` /
  `HomeView`, ConfirmDialog + pagination + facial panel in `VisionView`,
  Ethics card in `SettingsView`, i18n en/ar for all new surfaces.

### Re-issued closeout (2026-09-07): Lens identity, endpoint tests, housekeeping

The v1.0.9 tag was re-pointed and every release asset rebuilt to carry a
closeout round driven by a review that cloned the repo and ran the real
test suite. No engine behaviour changes. (An interim 1.0.10 version bump
was rolled back — v1.0.10 was never tagged or released, and the decision
was to re-issue 1.0.9 with the fixes rather than supersede it.)

- **CorpusMind Lens now has its own purpose-made icon — an aperture-eye
  mark.** Every icon file in `desktop-lens/src-tauri/icons/` was
  byte-for-byte identical to the main app's, and the web UI's logo
  (`Sidebar.tsx`, `App.tsx`, `AboutView.tsx`) hardcoded the main-app asset
  even inside the Lens shell — with both apps installed side by side there
  was no way to tell them apart in the taskbar/dock/Start menu or Alt-Tab.
  Lens now carries a purpose-made mark: an eye whose iris is a camera
  aperture (gold barrel ring + six blades) with a corpus-constellation
  pupil, on the Lens-blue badge (`#2563eb`) — eye for vision, aperture for
  imaging, constellation for the corpus — while the badge family (rounded
  square, gradient, gold accents, bottom bar) is shared with the main app
  so the two still read as siblings. The in-app logos switch on
  `isLensMode`, and `index.html` swaps the favicon, theme color, and
  document title when `?shell=lens` is present. The vector source of
  record is `download/icon-lens.svg`; the raster set was generated from it
  with cairosvg + Pillow (no Rust toolchain was available in the build
  environment, so `cargo tauri icon` could not be used — see issue #9).
- **Version files were inconsistent**: root and shared `package.json` were
  still at `1.0.0` (and `web/package-lock.json` at `0.1.0`) while every
  other package had moved on. All version files now read `1.0.9`
  consistently.
- **CITATION.cff was stale**: it still declared `1.2.0` (an abandoned
  numbering line) and its DOI description referenced `v0.1.16`. Updated to
  `1.0.9` with a version-agnostic concept-DOI description; minting the
  1.0.9 version DOI on Zenodo happens at release time
  (see `docs/ZENODO_DOI_GUIDE.md`).
- **Added end-to-end coverage for `POST /api/v1/ai/chat`** — the endpoint
  both apps call, previously untested as an assembled route:
  `tests/test_ai_chat_endpoint_e2e.py` runs a real HTTP round trip through
  the FastAPI app (with lifespan), verifies the response shape the
  frontend consumes plus conversation/turn persistence, and proves that a
  corpus shared between CorpusMind and CorpusMind Lens (annotated text +
  analysed image set in the same corpus) grounds the system prompt the
  model actually receives in both text-side stats and the vision-side
  image sets, including the explicit cross-modal instruction. The provider
  stub patches `health()` and `pick_default_model()` — the endpoint's
  health gate and auto-selection run before `.chat()` is ever reached.
  Suite: 354 passed, 9 skipped (pre-existing optional CAMeL Tools skips).

## [1.0.8] — 2026-09-06 — Collocation network: guaranteed rendering everywhere

The collocation network could still come up blank on machines whose webview
cannot provide a working WebGL2 context (Sigma v3 is WebGL2-only): VMs and
remote-desktop sessions without a GPU, disabled hardware acceleration, and
locked-down WebView2/WebKitGTK installs all silently produce an empty canvas.
The network now renders on **every** machine.

### Added

- **Built-in 2D-canvas fallback renderer** (`NetworkCanvas2D`): when WebGL2 is
  unavailable or Sigma fails to start, the exact same graphology graph — same
  ForceAtlas2 layout, same colour system, same per-measure edge weighting — is
  drawn with plain Canvas2D. Full interaction parity: wheel zoom, drag-pan,
  node drag, hover tooltips with exact statistics, click-to-expand / collapse,
  right-click re-center, measure re-weighting, and PNG/JSON export. A small
  "2D mode" badge in the toolbar explains why it is active.
- **WebGL2 capability probe** up front, with a `localStorage
  ["cm-network-renderer"]` override (`"canvas"` / `"webgl"`) for diagnostics.
- The network canvas is now full-width and taller (`min(72vh, 680px)`, min
  460px) — a network reads much better wide than boxed in a fixed column.

### Fixed

- Sigma construction and first refresh are wrapped in try/catch and fall back
  to the 2D renderer instead of disappearing silently.
- A `ResizeObserver` kicks a refresh whenever the container's observed size
  changes, so a canvas mounted before its parent has been laid out (font-load
  reflow, panel animation) self-heals instead of staying blank.
- Hover-tooltip text is now shared between both renderers (single source).

### Verified

- End-to-end in a real browser against a freshly compiled corpus: WebGL path
  renders (12 nodes / 35 edges); forced 2D path renders identically (badge
  shown, hover tooltip, click-to-expand 12 → 13 nodes, measure switch redraws
  edges); zero console or page errors in either path.

## [1.0.7] — 2026-09-06 — Corpus-construction workflow + collocation network fix

Five user-reported fixes and workflow upgrades in the parent app.

### Fixed

- **Collocation network rendered a blank canvas** (v1.0.0 regression): the
  Sigma.js edge reducer closed over the empty graph instance created at mount
  time, so the moment the real graph was loaded via `setGraph()` every reducer
  call threw `NotFoundGraphError`, aborting Sigma's re-index mid-refresh and
  leaving the canvas permanently blank. The fetch's catch block then swallowed
  the error into a 2.6-second toast. The reducer now reads the graph through
  the renderer (`renderer.getGraph()`), and load failures render as a
  persistent, styled error line.
- **The app no longer reopens on the last-visited screen**: `activeNav` is
  removed from the persisted UI state (with a storage migration), so every
  launch opens on Home (Vision for Lens), as users expect.

### Changed

- **Your Corpus: the Tagset card now comes FIRST** — before the upload zone
  and the document list, matching the corpus-construction norm (pick the
  annotation scheme, then upload/tag/parse against it).
- **Tag all files at once**: a new "Tag All Files" control applies the same
  genre / register / year to every document in one action (new engine
  endpoint `PATCH /corpora/{cid}/documents/meta`), after which the UI prompts
  for recompilation.
- **Compile gate**: the document list now shows an explicit corpus-compile
  status — a warning ("not compiled yet" / "tags changed, recompile") when
  analysis would run against a stale corpus, and a green "Compiled
  successfully — N/M documents, T tokens" confirmation when a recompile
  succeeds. Per-document compile failures surface as an explicit error state
  instead of a silent pass.
- **Reference corpus size guidance**: the Upload tab now states the engine's
  hard limit (50 MB per file, enforced with HTTP 413) and a recommended total
  corpus size computed from the machine (RAM via `navigator.deviceMemory`
  with an 8 GB fallback, plus CPU core count).
- **Larger AI response text**: floating-assistant messages 12.5px → 14px and
  full-Assistant message bodies 15px, both at 1.6 line-height.

## [1.0.6] — 2026-09-05 — Complete release asset matrix

Every tag-gated release since v1.0.1 silently shipped without the parent
Linux AppImage and the web PWA zip. The Linux build job produced both files
on every run but its upload globs referenced only the .deb, so the AppImage
was built and then discarded, and no PWA archive was ever attached.

### Added

- **Parent Linux AppImage restored as a release asset**: `CorpusMind_<ver>_amd64.AppImage`
  is now uploaded to the workflow artifacts and attached to the GitHub
  release (it was already being built every run). Linux users again get a
  no-sudo install option, matching what the CorpusMind Lens job has always
  shipped.
- **Web PWA zip is now built by CI**: `corpusmind-web-<tag>.zip` (the
  installable PWA archive) is packaged from the Linux job's PWA build and
  attached to every release. v1.0.0 carried a manually-uploaded copy; the
  asset is now reproducible on every tag.

### Fixed

- Release asset matrix: a release now carries the full intended set —
  CorpusMind (NSIS .exe, .msi, arm64 .dmg, .deb, .AppImage, PWA zip),
  CorpusMind Lens (NSIS .exe, .msi, universal .dmg, .deb, .AppImage) and
  SHA256SUMS.txt — enforced by `fail_on_unmatched_files` on every job.

## [1.0.5] — 2026-09-05 — Windows installer hardening

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
- **Publisher metadata broke the MSI build**: the earlier publisher string
  contained a raw ampersand which, embedded unescaped into the generated
  WiX source, made candle abort on every Windows MSI bundle ("failed to
  run ...candle.exe"). The publisher now uses "and".
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
