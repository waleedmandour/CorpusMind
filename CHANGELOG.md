# Changelog

All notable changes to CorpusMind are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once 1.0 ships. Until then, expect breaking changes between 0.x releases.

## [Unreleased]

### Added
- **Project scaffold.** Monorepo layout per §7.1 of the build prompt:
  `engine/`, `web/`, `desktop/`, `shared/`, `reference-data/`, `infra/`,
  `docs/`.
- **`corpusmind-engine` (Python 3.12 + FastAPI).** Skeleton service with:
  - Health-check endpoints (`/api/v1/health`, `/api/v1/health/ready`)
  - System endpoints (`/api/v1/version`, `/api/v1/providers`,
    `/api/v1/providers/{name}/models`, `/api/v1/settings`)
  - `ModelProvider` abstraction (§11.4) with three concrete implementations:
    `OllamaProvider`, `LMStudioProvider`, `CloudProvider` (off by default,
    hard-disable switch for self-hosted deployments)
  - Grounded-AI Assistant scaffold (§11) with `ToolRegistry`,
    `Conversation` audit trail, and the load-bearing `grounded: bool` flag
    on every turn
  - AI routes: `/api/v1/ai/chat`, `/api/v1/ai/chat/stream`,
    `/api/v1/ai/conversations/{cid}`, `/api/v1/ai/tools`
- **Statistics engine (`engine/stats/measures.py`).** All §12 formulas
  implemented: MI, T-score, log-likelihood, Dice, LogDice, chi-square,
  Delta P (both directions), Log Ratio, %DIFF, Simple Maths, Odds Ratio,
  Juilland's D, Gries' DP, TTR, STTR. 23 unit tests, all passing.
- **`corpusmind-web` (React 18 + Vite + TS + PWA).** Installable PWA with:
  - Ribbon-style shell UI (Office-like tabs: File / Text / Vision /
    Assistant / View) per §8.25, §10.3
  - Assistant view demonstrating the grounded/ungrounded badge contract
    (§11.1)
  - Dark/light theme tokens with CSS custom properties
  - Full RTL mirroring via logical CSS properties + `dir` attribute
  - Command palette (Ctrl/Cmd+K) per §10.3
  - Settings view showing engine health, provider status, reproducibility
    and privacy notices
- **`corpusmind-desktop` (Tauri 2).** Shell with:
  - `tauri.conf.json` configured for sidecar binary bundling
  - Rust sidecar lifecycle manager (`src/lib.rs`) handling all §3.4
    pitfalls: target-triple naming, log-to-file (not piped), full child
    detachment on exit, dev fallback to `python -m app.main` when the
    PyInstaller binary isn't present
  - Capability set scoped to localhost (engine, Ollama, LM Studio)
- **`shared/`** — `@corpusmind/shared` TypeScript package with hand-written
  types covering the Phase 0 API surface, plus an `npm run generate` script
  for OpenAPI → TS regeneration.
- **`reference-data/frameworks/kress-van-leeuwen.yaml`** — the first of the
  twelve §9.24 framework prompt templates, with the §11.3 schema (categories,
  output schema, guardrails, example output) defined.
- **`infra/`** — Docker Compose for self-hosted lab deployments: engine +
  optional Ollama side-by-side, with `CORPUSMIND_CLOUD_DISABLED_HARD=true`
  by default for shared-infrastructure safety.
- **Documentation.** Comprehensive `README.md` (quickstart, architecture,
  statistical transparency table, license rationale), `docs/ARCHITECTURE.md`
  (living diagram), `docs/METHODOLOGY.md` (every §12 formula with citations
  and worked examples), `CONTRIBUTING.md` (DCO, code style, review process),
  `THIRD_PARTY_LICENSES.md`.
- **`LICENSE`** — full AGPL-3.0-only text.

### Decisions locked in (§19 of the build prompt)

| Decision | Choice | Rationale |
| --- | --- | --- |
| Product name | `CorpusMind` | confirmed; placeholder from the build prompt promoted to the canonical name |
| Engine language | Python 3.12 + FastAPI | best NLP/CV ecosystem access (§7.2) |
| Frontend framework | React 18 + Vite + TS | broadest hiring pool, mature PWA tooling |
| Collaboration model | save-and-sync (CRDT deferred) | scope-appropriate; CRDT is a Phase 6 decision |
| Project license | AGPL-3.0-only | strong copyleft, compatible with all current deps, aligns with open-science norms |
| Reference corpora | open-frequency-derived approximations | no BNC/COCA bundling without confirmed rights |
| CEFR wordlist | open frequency-band approximation | EVP carries redistribution restrictions (§8.10) |
| Facial-analysis module | opt-in, off by default | legally sensitive (§18); ship in Phase 5 behind explicit consent gate |
| Self-hosting model | Docker, single-tenant per instance | multi-tenant deferred to Phase 6 |

### Known limitations (Phase 0)

- The only registered grounded-AI tool is `ping`. Full tool surface
  (`search_concordance`, `get_frequency`, `compute_collocations`,
  `compute_keyness`, `get_dispersion`, etc.) lands in Phase 1.
- The engine's conversation store is in-memory (lost on restart). SQLite
  persistence lands in Phase 1.
- The desktop shell's sidecar binary is not yet built — Tauri dev falls
  back to spawning `python -m app.main`. PyInstaller bundling lands in
  Phase 1 alongside the first Suite A features.
- The web frontend's Text and Vision suite views are placeholders. Their
  feature implementations land in Phases 1 and 4 respectively.
- No reference corpora are bundled yet. The license-gate CI check (Phase 1)
  will refuse to bundle anything without a recorded license.
- No telemetry, analytics, or error reporting is shipped — by design (§13.2).
  An explicit opt-in mechanism will land in Phase 6 if there is user demand.

## [0.1.0] — Phase 0

Initial public release. See "Added" above.
