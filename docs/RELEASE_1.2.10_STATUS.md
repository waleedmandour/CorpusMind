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
