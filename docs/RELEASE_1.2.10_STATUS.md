# Release 1.2.11 Status (Phase 0 audit + final report)

> Audit date: 2026-10-07. Branch: `release/1.2.11-prep` (from main @ `6471317`).
> **Final state: requirements below were then implemented and verified in
> this cycle; the table reflects the END state. Verification commands are
> listed in the "Final gates" section at the bottom.**
>
> **Version target decision: 1.2.11.** The `v1.2.10` git tag already exists
> (created 2026-09-28, with GitHub release + installers built from that tree).
> Re-pointing it is forbidden (same-version rebuilds give users no in-app
> update prompt; this has bitten the project twice). The existing partial
> work on main already self-describes as v1.2.11 work.

## Baseline at audit time (before any edits)

| Gate | Result |
| --- | --- |
| `ruff check .` (engine) | **FAIL — 14 errors** (all introduced by the partial ur/hi/fa commit: 2 unused imports in `ingestion/cleaning.py`, 12 duplicate set items in `nlp/stopwords.py`) |
| `pytest tests/` (engine) | **587 passed, 9 skipped, 0 failed** (last documented: 447+9 at v1.2.6) |
| `tsc -b` (web) | **FAIL — TS2345** `CorpusSelectionView.tsx:633` (`string` not assignable to `SetStateAction<"en" \| "ar">`) — the partial commit widened picker options but not the state type |
| `npm run build` (web) | blocked by tsc |
| `scripts/check_contrast.mjs` | **PASS — 86/86 token pairs** |

## Requirement table

Legend: DONE / PARTIAL / MISSING / BROKEN. "BROKEN" = exists but fails.

### Workstream A — Hindi (hi), Urdu (ur), Persian (fa)

| # | Requirement | Status | Where / Notes |
| --- | --- | --- | --- |
| A0 | Fix baseline regressions | **BROKEN** | ruff 14 errors; tsc 1 error (see above) |
| A1 | Language capability registry (single source of truth, API + UI) | **MISSING** | No registry exists. Scattered: `STANZA_PREFERRED_LANGUAGES` (nlp/general/pipeline.py:227), stopwords map, tagsets map. UI has no capability surface. |
| A2 | fa/ur normalization (ي/ی, ك/ک, ہ/ه/ھ, ے/ی; NO Arabic rules on fa/ur) | **MISSING** | Only Arabic `arnorm` (storage/session.py:53) + mirrors (stats/service.py:104, semantic/vector_kwic.py:111, ingestion/cleaning.py:155). `normalize_arabic=true` on an fa corpus silently applies Arabic folding (ة→ه, alef unification). |
| A2 | Hindi normalization (nukta क़/क, anusvara/chandrabindu, no case folding) | **MISSING** | Nothing exists. |
| A2 | ZWNJ (U+200C) meaningful in fa/ur; documented option | **MISSING** | No ZWNJ handling anywhere; tokenization via spacy.blank treats it as part of tokens (accidentally correct) but nothing is documented or testable. |
| A2 | Digits (Latin, Arabic-Indic, Extended, Devanagari) documented | **MISSING** | No digit policy. Cleaning `remove_numbers` uses `\d` (ASCII only). |
| A2 | Sentence splitting: danda । / double danda ॥ (hi), ۔ (ur) | **MISSING** | ArabicPipeline terminals exclude danda; spacy.blank('hi'/'ur') sentencizer unreliable for danda. Stanza (optional) handles natively. |
| A2 | Urdu word-segmentation limitation documented + tested | **MISSING** | Nothing documented. |
| A2 | SQL scalar normalizer + Python mirror in lockstep + parity tests | **MISSING** | `arnorm`/`ar_norm` exist (ar only) without parity tests; no fa/ur/hi SQL normalizers. |
| A2 | Detection guard: Arabic script must not route fa/ur into Arabic pipeline | **BROKEN** | `learner/caf.py:45,147` — any `[\u0600-\u06FF]` token auto-routes CAF to Arabic rules (fa/ur chars are in that range). `learner/errors.py:249` + `api/learner.py:99` same binary branch. |
| A3 | NLP backend decision recorded (versions, licenses) | **PARTIAL** | Stanza chosen in code (optional dep, `[urdu-hindi-farsi]` extra) but NOT recorded in docs/METHODOLOGY.md or THIRD_PARTY_LICENSES.md; no SHA-256-verified model download path (stanza self-downloads). |
| A4 | Arabic regression guard + golden tests | **PARTIAL** | Existing Arabic tests pass (pytest baseline green) but no golden-output tests pinning Arabic normalization/concordance behavior against the new normalizers. |
| A5 | Per-tool support matrix with explicit unavailable messaging | **MISSING** | Tools silently degrade: sentiment falls back to EN lexicon for fa/ur; readability suppresses Flesch (en-only, OK) but returns no language note; learner errors fall back to EN rules silently; query suggestions return Arabic labels for fa/ur. No API surface says what a language supports. |
| A5 | Vector KWIC with language-appropriate normalization | **BROKEN** | `_normalize_for_embedding` (semantic/vector_kwic.py:111) always applies Arabic folding when flag on — wrong for fa/ur. bge-m3 itself is multilingual (works untested). |
| A6 | Stopword lists editable via stopword manager | **PARTIAL** | Lists exist (nlp/stopwords.py) and cleaning uses them, but wordlists API exposes only `builtin:en`/`builtin:ar` — `builtin:ur/hi/fa` not selectable. |
| A6 | Corpus Hub: hi/ur/fa (Wikipedia, HF datasets-server, OPUS) | **PARTIAL** | API pattern accepts ur/hi/fa but `_hf_search`/`_wikipedia_search` binary-map to en/ar; Wikipedia excluded for ur/hi/fa; OPUS cache/fetch lacks ur/hi/fa slices; HF catalogue lacks `config_ur/hi/fa`. |
| A6 | Reference corpora (open, SHA-256-pinned, licensed) for hi/ur/fa | **MISSING** | `ReferenceLanguage = Literal["en","ar"]` gate; no entries. |
| A6 | health/resources reports new resources | **MISSING** | `usas` loop is en/ar; no stopword/normalizer reporting. |
| A7 | Frontend: RTL for ur/fa, bidi in KWIC/tables/exports/network, fonts | **MISSING** | UI language stays en/ar (OK per scope). No per-corpus dir/bidi handling in KWIC (`ConcordancerView.tsx:183-208`, Vector KWIC, dep concordance); KWIC cells use mono font with no Devanagari/Nastaliq coverage; no bundled fonts at all (no @font-face in repo); engine CSV export lacks UTF-8 BOM (Excel mangles RTL); collocation network canvas font has no Arabic-script stack. One latent TS error (A0). |
| A7 | Tagset/recipe display + onboarding updated | **PARTIAL** | TagsetSelector binary ar/en (ur/hi/fa get upos-only via server default — works but UI shows EN list); onboarding copy says "work bilingually (English and Arabic)" — now stale. |
| A8 | Student Mode route allowlist decision + test | **MISSING** | No new routes gated/tested (no new routes exist yet). |
| A9 | Per-language test fixtures + ingestion tests + parity tests | **MISSING** | Only an out-of-repo smoke script referenced in the old commit message (`/home/z/my-project/scripts/smoke_test_ur_hi_fa.py` — not in repo, unverifiable). No engine tests for ur/hi/fa exist. |

### Workstream B — Gemma 4 via Ollama

| # | Requirement | Status | Where / Notes |
| --- | --- | --- | --- |
| B1 | Verify tags/sizes/quants/context/tools/multilingual/license/min-Ollama from authoritative sources | **PARTIAL** | VERIFIED 2026-10-07 (ollama.com/library/gemma4 + /tags; ai.google.dev model card; arXiv 2607.02770): tags gemma4:latest/:e2b/:e4b/:12b/:26b/:31b/:cloud + `-it-qat`, `-it-q4_K_M`, `-it-q8_0`, `-it-bf16`, `-mlx`; capabilities vision/tools/thinking/audio; 128K (e2b/e4b) & 256K (12b+) context; license Apache 2.0; "140+ languages pre-trained, 35+ out-of-the-box". Explicit hi/ur/fa enumeration: NOT in official docs (will be stated honestly). Min Ollama version: NOT verifiable — will implement error classification instead of a fabricated number. |
| B2 | Catalogue entries + canonical-name helper + fit badges + pull flow | **MISSING** | No gemma4 entries in `RECOMMENDED_OLLAMA_MODELS` (system.py:99). Helper `canonical_model_name` verified tag-safe (tests exist). |
| B3 | Capability gating + auto-ground fallback | **PARTIAL** | Gating via `/api/tags` capabilities exists and is tested; gemma4 advertises `tools` so it passes. No test with a gemma4-style tag. |
| B4 | Defaults unchanged; classroom model separate; capacity real footprint | **DONE (verified)** | `pick_default_model` only applies when request has no model; classroom `student_model` is a separate persisted setting (default llama3.2:3b); capacity uses on-disk size from /api/tags. No change planned. |
| B5 | Clear message when Ollama too old (not 409/502) | **MISSING** | No Ollama version probe; pull/run errors surface raw. |
| B6 | Measurement (tokens/s, TTFT) + 5-language grounded smoke | **NOT DONE** | No Ollama daemon in the build environment — cannot measure; will be reported honestly. |
| B7 | Terms in THIRD_PARTY_LICENSES.md (Apache 2.0 note) | **MISSING** | Not present. |

### Workstream C — Release hygiene

| # | Requirement | Status | Where / Notes |
| --- | --- | --- | --- |
| C1 | Version sync 1.2.11 in every surface + failing check | **BROKEN** | Surfaces currently inconsistent: engine=1.2.10, root pkg=1.2.10, shared pkg=1.2.9, root lock=1.2.9, docker-compose tag=1.2.9, README badge=1.2.6 + health example=1.2.6, useEngineVersion fallback=1.2.9, USER_GUIDE*.md headers=1.2.6/0.1.0, tauri/Cargo/web=1.2.10. Lockstep test covers only 4 surfaces. |
| C2 | CHANGELOG entry (honest) | **MISSING** | — |
| C3 | README refresh + language matrix + METHODOLOGY update | **PARTIAL** | README: stale v1.2.6 status, Phase list, "7 12 measures" / "4.8 reproducibility" / "4 Principle 3" glitches, static CI badge, v1.2.10 citation. METHODOLOGY lacks normalizer docs. |
| C4 | User Guide EN+AR + PDFs + version-match rejection | **PARTIAL** | Guide scripts hardcode v1.2.10 in 11 places; no in-repo version validation; USER_GUIDE*.md stale. |
| C5 | THIRD_PARTY_LICENSES.md sync (incl. Caddy from v1.2.9) | **PARTIAL** | Caddy entry present? (verify); Stanza, Gemma 4, fonts, datasets missing. |
| C6 | Packaging: smoke gate for new resources; wheel smoke; Docker boot; installer size | **MISSING** | ci_smoke_engine.sh asserts en/ar resources only. |
| C7 | Final gates all green | **BROKEN** | ruff + tsc failing at baseline (see above). |

## Immediate fix list (in order)

1. ruff + tsc baseline fixes (A0)
2. A1 registry module + API + health + UI consumption
3. A2 normalizers (SQL + Python) + sentence splitters + detection guard + parity tests
4. A5 tool matrix + per-language honesty in API + Vector KWIC normalization fix
5. A6 resources (stopword manager, hub, reference corpora, health)
6. A7 frontend fonts/bidi/exports + onboarding + tagset display
7. A8/A9 tests (student allowlist, fixtures, ingestion, golden Arabic)
8. B2-B5, B7 (catalogue, gating tests, version-probe messaging, licenses)
9. C1-C7 (version sync + lockstep test, CHANGELOG, README, METHODOLOGY, guides+PDFs, licenses, packaging gates)

---

## Final gates (executed 2026-10-07, on `release/1.2.11-prep` @ `59cd84a`)

| Gate | Command | Result |
| --- | --- | --- |
| ruff | `ruff check .` (engine) | PASS (0 errors) |
| engine tests | `pytest tests/` | **661 passed, 9 skipped, 0 failed** (baseline at cycle start: 587/9; documented v1.2.6 baseline: 447/9) |
| web typecheck | `tsc -b` | PASS |
| web build | `npm run build` | PASS (fonts precached into the PWA bundle) |
| contrast | `node scripts/check_contrast.mjs` | PASS 86/86 |
| version lockstep | `pytest tests/test_version_lockstep.py` | PASS (9 checks over every version surface) |
| wheel build | `python -m build --wheel` | PASS — `corpusmind_engine-1.2.11-py3-none-any.whl`; 15/15 packages present |
| wheel boot / Docker | NOT RUN in this environment (no Docker daemon available) — the Docker CI job's resource probe was updated in lockstep and runs on push |
| PyInstaller onedir boot | NOT RUN (Windows/macOS toolchains unavailable here); `ci_smoke_engine.sh/.ps1` now assert the three new reference files, so the release pipeline enforces them at packaging time |
| installer size growth | +~2.0 MB (fonts) + ~0.1 MB (TSVs) before compression; the packaged app does NOT bundle stanza/torch, so no model-weight growth |

---

## Session 2 (2026-10-07, `release/1.2.11-prep`): Arabic Tools "Analysis spins forever"

Field bug report: the Arabic Tools panel's Analysis never finishes. Root cause found
BEFORE any code change; reproduced behaviorally on both v1.2.9 and this branch (the
Arabic engine code is byte-identical between them, so this is NOT a v1.2.11
regression).

| Layer | Defect (verified) | Fix (verified) |
| --- | --- | --- |
| Data resolution | `MorphologyDB.builtin_db()` on a machine without `~/.camel_tools` triggers `Catalogue.update_catalogue()` — a blocking, TIMEOUT-LESS `requests.get` to GitHub; on an offline/firewalled machine it never returns (measured: >120 s, no return, blackholed proxy). | Filesystem pre-flight in `nlp/arabic/pipeline.py` (`_require_camel_data` + `camel_tools_data_dir()` in `app/resource_paths.py`); missing data raises `ArabicDataMissingError` → HTTP 503 with the install command in 0.07 s. `CAMELTOOLS_DATA` is pinned to the resolved pack before camel_tools is imported. |
| Event loop | Every `/arabic/*` route ran CPU-bound CAMeL work inline in `async def` handlers; `/health` latency equalled the analysis duration (measured 2304 ms during a 2.3 s analysis). `ai/tools.py::execute_tool` had the same defect. | All Arabic routes + the grounded-AI tool dispatcher run CAMeL work via `asyncio.to_thread`; `/health` during a 64k-token analysis now answers in 20-24 ms (measured). |
| Deadline | No server-side timeout, no client timeout, no cancel → infinite spinner. | Hard deadline `CORPUSMIND_ARABIC_TIMEOUT_S` (default 30 s) → HTTP 504 with a hint (measured: 504 at 1 s deadline in 1.72 s, `/health` still 200 immediately after); client 45 s deadline in `api.ts`; panel shows elapsed seconds and a working Cancel (react-query signal → fetch abort). |
| Tests | `_camel_is_usable()` called the nonexistent `MorphologyDB.built_db` (typo) → the 9 CAMeL-backed tests skipped silently everywhere, CI included. | Typo fixed; new tests: skip-guard typo canary, 503-fast, 504 deadline, `/health` responsiveness during a REAL analysis (fails loudly if skipped where camel+data exist), `/health/resources` camel block. |
| Packaging | The spec bundled neither camel_tools code+data nor provisioned anything; release workflow never installed `[arabic]`. The desktop app could never run Arabic Tools. | Spec collects `camel_tools` + `camel-tools-data/`; release.yml provisions CPU-torch + camel-tools + `camel_data -i` in all four OS jobs; both smoke gates assert the payload. Linux onedir boot VERIFIED: boots 1.5 s, resolves its own pack, real morphology (root ط.ل.ب) inside the frozen app; `ci_smoke_engine.sh` full PASS. |

Gates this session (Linux, Python 3.12.14): engine `pytest` **674 passed / 1 skipped** (only
the optional Stanza skip; was 660/10 with 9 false skips); `ruff check` clean; `tsc -b`,
`npm run build`, `check_contrast.mjs` 86/86 all PASS; Linux PyInstaller onedir boot + full
smoke gate PASS. Installer size: onedir 716 MB total; camel payload 161 MB (data) + ~0.1 MB
(code) — NO torch/transformers bundled (excluded; morphology and DIDModel6 paths are
non-neural, verified by import-chain probe).

Human decision required before release: the calima-msa-r13 DB is GPL v2 (AraMorph/LDC
provenance, per the LICENSE file shipped inside the DB) and the dialectid-model6 files
carry no license statement; bundling reverses the previously documented "NOT bundled"
choice. THIRD_PARTY_LICENSES.md records both facts and the flag. Fallback if the
maintainer declines: drop the `camel-tools-data` block from the spec (the 503 +
hint path stays correct either way).

## Session 3 (2026-10-08, `release/1.2.11-prep`): rc1 field report — "cannot analyze after installing the Arabic data pack"

User report on the rc1 build (clean machine, data pack installed from inside the app):
the Arabic Tools sample text still cannot be analyzed. Two independent defects,
root-caused in code BEFORE any change and reproduced against the rc1 tree
(`b14357e`) with a standalone repro + new regression tests:

| # | Defect (verified) | Fix (verified) |
| --- | --- | --- |
| 1 | Stale resolver cache: `camel_tools_data_dir()` (`app/resource_paths.py`) is `@lru_cache(1)`. On a clean machine the FIRST Arabic request or `/health/resources` poll runs before any pack exists → the resolver returns `None` and the cache stores that `None` forever. The in-app installer then installs the pack fine (its own `_resolve_target_dir()` never used the cached resolver), but every later analysis in the SAME process still 503s "not installed" until the whole app is restarted. Reproduced deterministically: poison → fabricate pack → `_require_camel_data` still raises → `cache_clear()` → passes. | `refresh_camel_tools_data_dir()` added; the installer job calls it when the on-disk state changes (after the catalogue marker is written, after EACH package lands, after cancelled/failed cleanup). Analysis works immediately after "done", no restart. Regression test runs the REAL installer job against a local fake-zip server in the poisoned-cache sequence. |
| 2 | Dialect DB trap: the panel's dropdown offered `egy`/`glf`/`lev` DBs that no installer path provisions (installer = `morphology-db-msa-r13` + `dialectid-model6` only). Selecting Egyptian (as in the user's screenshot) can only ever 503 "incomplete: missing calima-egy-r13" with a hint that pointed back at the in-app installer — whose answer ("already installed", 409) could never fix it. | (a) `camel_data_status()` now reports `morphology_dbs: {msa, egy, glf, lev}` on the install-status payload the UI already polls; (b) the ArabicView dropdown disables DBs that are not on disk, labelled "data pack not installed" (EN+AR i18n), and falls back to MSA if the selection becomes unavailable; (c) the 503 message for a missing dialect DB names the exact terminal package (`camel_data -i morphology-db-egy-r13`, `-glf-01`, `-lev-01`); (d) the installer card refreshes the backends badge when an install reaches "done". The installer card no longer dead-ends: the UI never offers a request that cannot succeed. |

Gates this session (Linux sandbox, Python 3.12.14, camel_tools installed but the
~170 MB data pack NOT downloadable here - GitHub release CDN blackholes past ~3 MB;
CI provisions it in every job): new regression suite
`tests/test_v1211_arabic_cache_refresh.py` 6/6 PASS (incl. the full user sequence:
poison → REAL installer job over local fake zips → pre-flight passes in-process);
full engine suite chunked: **699 passed / 12 skipped** (the 11 real-DB Arabic tests
skip here exactly as designed; 1 environment-only failure: Arabic ingestion needs
the provisioned pack, same failure on the pre-fix tree on this machine);
`ruff check .` clean; mypy per-package report **PASS (1829 = 1829, +0 everywhere)**
after typing the new test file; web `tsc --noEmit` PASS; `npm run build` PASS.
Real-morphology end-to-end (DB load + root extraction through the fixed path) is
verified by CI's provisioned-pack jobs on push (test-gate + four OS smoke gates).
CHANGELOG.md gained both fixes under [1.2.11] Fixed.

## Session 4 (2026-10-08, `release/1.2.11-prep`): rc2 field report — radar Export dead + installer learns dialect packs; final v1.2.11

User confirmed rc2 resolved the "cannot analyze after install" report ("Everything
looks good now"), then filed the pre-final blockers: (1) the Discourse radar
charts' Export PNG button does nothing (bar-graph export works), and (2) the
installer must fetch the dialect packs before v1.2.11 is tagged.

| # | Root cause (verified before any change) | Fix (verified) |
| --- | --- | --- |
| 1 | Radar Export dead in every framework: `ChartExportButton` located the chart via `targetRef.current.querySelector("svg")` — descendants only. The bar charts pass a `<figure>` wrapper ref (svg inside → works), but `TaxonomyRadar` and `PersuasionRadar` attach the ref directly to the `<svg>` element; querying that svg for a DESCENDANT svg matches nothing and the handler silently returned. The prop type even declared `RefObject<SVGSVGElement>` as supported — the implementation just never handled it. | `ChartExportButton` now matches the ref host itself when it IS an `SVGSVGElement` (`instanceof`), else falls back to the descendant search; a missing svg logs a console warning instead of failing silently. One fix in the shared component covers every framework's radar (Hyland, Halliday & Hasan, Martin & White, Cialdini, SFG, persuasion). |
| 2 | The installer managed exactly two packages (`morphology-db-msa-r13`, `dialectid-model6`); the UI's egy/glf/lev options relied on the terminal fallback. | `catalog_packages()` grew the three dialect morphology DBs with pins observed against the LIVE release assets on 2026-10-08 (each zip downloaded and hashed: egy 67,255,921 B `eb8a2d3a…`, glf 7,977,135 B `385a29aa…`, lev 10,622,164 B `34f01238…`); all three show the same +214-byte upstream re-upload drift as msa — third independent proof that the observed digest, not the catalogue's stale metadata, is the pin. Zip structure and shipped LICENSE verified (root `morphology.db` + `LICENSE`, same layout as the proven msa pack; egy GPL-2.0-only, glf/lev CC BY 4.0). `start()` gained `include_dialects` (default True — one click must fix every data-driven 503 the UI can produce); install order msa → egy → glf → lev → dialectid. InstallRequest exposes both flags; Settings preview lists all five packages with licences (EN+AR i18n); THIRD_PARTY_LICENSES.md states the five-package download and keeps "never bundled" exact. |

Gates this session (Linux sandbox, Python 3.12.14): full engine suite **688 passed /
13 skipped, 0 failed** (one env-only failure during bring-up was the reset sandbox's
missing `en_core_web_sm`, not a regression; passes with the model installed); Arabic
installer + cache-refresh suites 26/26 (incl. the new `test_installer_dialects_flag`
and the updated snapshot-integrity test asserting all five pins); `ruff check .`
clean; mypy strict report **PASS, 1829 → 1820** (baseline re-locked, lower is fine);
web `tsc --noEmit` PASS; `npm run build` PASS.

## Session 5 (2026-10-08, `release/1.2.12-prep`): classroom toggle white screen — two engine defects, a UI boundary, and a real end-to-end toggle proof

Field report on the v1.2.11 desktop build: toggling the Student Mode classroom
server (Settings) intermittently white-screens the window. Investigation pinned
two reproduced engine defects plus one fragile render path; fixes verified by
four new tests and a real end-to-end toggle run (real engine, real Caddy).

| # | Root cause (verified before any change) | Fix (verified) |
| --- | --- | --- |
| 1 | Linux `PR_SET_PDEATHSIG` is delivered when the forking THREAD exits, not the process (prctl(2)); the v1.2.10 phased start spawned Caddy from a throw-away `threading.Thread`, so the kernel SIGTERMed a healthy Caddy the moment the thread returned — `enabled=True`, `caddy_running=False`, empty error text. | The start worker runs on a long-lived single-thread executor (`app.server_mode.SPAWN_EXECUTOR`, prefix `classroom-spawn`). A self-validating Linux test forks a child from a throw-away thread (dies — proves the test can detect the bug) and from the executor (survives). |
| 2 | `/server-mode/disable` ran `stop_caddy()` (terminate + wait up to 10 s) inline on the event loop; a stalled `/health` exceeds the desktop shell's 3 s probe and `ensure_engine` force-restarts the engine, killing the classroom. All `_status_payload` call sites had the same inline-blocking shape. | `/server-mode/*` handlers offload blocking work (`stop_caddy`, `_status_payload`) via `asyncio.to_thread`; the Ollama `/api/ps` status probe drops 3 s → 1 s. A test polls `/health` at 50 ms during a 1.5 s patched stop and asserts worst-case latency < 0.5 s. |
| 3 | Render fragility: `StudentModeServerCard` dereferenced `s.urls.app` / `s.urls.root_ca` directly, so a status snapshot taken before Caddy is live could throw during render and unmount the whole tree (white window). | Defensive optional chaining with empty-string guards in the URL memos and QR block; a new top-level `ErrorBoundary` (EN+AR) catches any render error, records it in Smart Troubleshooting, and offers Try again / Reload app. A failed phase now always carries a reason (fallback names `caddy-stdout.log`). |

Also in this change: the classroom control plane (`/server-mode/*`) can no
longer trigger the shell-level engine restart from the web `jsonFetch` retry
path — a restart kills the engine AND the Caddy it supervises and leaves
pending Tauri IPC callbacks ("Couldn't find callback id") after a reload.
Failed classroom calls now fail fast and report their own error.

Real end-to-end toggle proof (Linux sandbox, real engine + pinned Caddy
2.10.0, `scripts/toggle_smoke_test.py`): **11/11** — enable → live and still
live after 8 s of polling (the old bug killed Caddy here), disable right
after enable (0.02 s response), status off, no orphan Caddy, re-enable live,
and `kill -9` of the engine takes Caddy down with it ("die with the engine"
preserved).

Deferred, stated honestly: the Rust-side hardening of `ensure_engine`
(wait ≈ 15 s, restart only if the engine process is actually dead) is NOT in
this build — this sandbox has no Rust toolchain or webkit2gtk headers to
compile-verify a bootstrap change. The web-side classroom guard and the
engine-side event-loop fixes remove the two reproduced triggers; the Rust
change remains recommended belt-and-suspenders for a machine with the Tauri
toolchain.

Known order-dependence, separate look: `test_batch_describe_run_completes`
and `test_batch_describe_skips_cached` (vision batch) fail in the reporter's
full-suite run but pass alone, pass in the author's full run (692 passed /
13 skipped, 0 failed), pass with `--ignore=tests/test_phase3_arabic.py`
(681 / 2 skipped), and CI's Test gate is green. Suspected mechanism: ~10
test modules mutate `CORPUSMIND_DB_URL` at import time and share the global
provider registry (`app.state.providers._instances`), so failure depends on
machine-specific import/state order. Not fixed here — no repro, and a
speculative fix would violate the root-cause-first rule. Needs the
reporter's full-suite `--tb=short` output; a conftest-level isolation pass
(env + registry snapshot/restore) is the likely shape.

Gates this session (Linux sandbox, Python 3.12.14): the four new tests pass
(`test_student_mode.py` 36/36); full suite in one process **692 passed /
13 skipped / 0 failed**; `ruff check` clean on changed files; mypy strict
report **PASS 1820 = 1820** (the 9 new test-side errors were annotated away,
baseline untouched); web `tsc --noEmit` PASS; `npm run build` PASS; contrast
regression check **86/86 PASS**.

## Session 6 (2026-10-08, `release/1.2.12-prep`): field report — "POS in KWIC finds nothing" — degraded (blank) tagging is now recorded, surfaced, and repairable

Repro first: with `en_core_web_sm` present, upload → `concordance level=pos`
returns rows (5 hits for `NOUN` on a two-sentence fixture). With the model
UNRESOLVABLE, `SpaCyPipeline._load()` strategy 4 silently degraded to
`spacy.blank()` — every token stored with `pos='X'`, lemmas = surface forms —
and **nothing recorded it**: `PipelineInfo` still reported the requested
model name, so the AnnotationVersion row claimed a tagger that never ran.
The user's corpora ingested under that condition can never be detected or
repaired, and POS-based analyses are empty forever. (Arabic is separately
guarded: ingestion without the MSA morphology DB fails loudly via the 503
install-hint flow, so the silent path is the spaCy/blank one.)

Fix (honest degradation + repair path):
- `PipelineInfo.degraded: bool` — set by strategy 4; `get_pipeline`
  docstring updated.
- `ingestion/service.py` + `api/corpora.py::recompile_corpus` record it:
  version row `model_name="spacy:<model>:degraded-blank"`,
  `pipeline_recipe["degraded"]`, loud `ingest_degraded_pipeline` /
  `recompile_degraded_pipeline` warnings.
- `CorpusOut.tagging_degraded` (create/list/get) drives the UI: the corpus
  list shows a "⚠ POS missing" chip and the Documents view shows a
  persistent alert banner ("tagged WITHOUT the NLP model … Recompile").
  Recompile's response carries `degraded`; when the model is STILL absent
  the UI says so plainly instead of claiming success (and a real recompile
  clears the flag — the POS banner disappears and POS-KWIC works again).

Tests: new `tests/test_degraded_tagging.py` (4) — blank-fallback visibility,
degraded upload → API surfacing, recompile-with-model clears the flag and
re-tags (POS-KWIC then returns rows), recompile-still-missing stays honest.
Full suite one process: **696 passed / 13 skipped / 0 failed**; `ruff`
clean; web `tsc` + build PASS; contrast 86/86 PASS. mypy: the diff adds
**zero** new errors (A/B diff of api error sets is byte-identical modulo
line numbers); the rebuilt sandbox venv (mypy 2.3.1) reads HEAD itself at
1822–1825 vs the 1820 baseline — environmental stub drift, baseline left
untouched (CI env is pinned and still 1820).
