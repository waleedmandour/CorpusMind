# CorpusMind Architecture

> Living document. Updated as decisions in §19 of the build prompt get resolved.

## The one big call: a headless engine, multiple shells

The single most important architectural decision in CorpusMind (§6 of the
build prompt) is the separation of concerns between a **headless engine**
(`corpusmind-engine`) and a **single frontend** (`corpusmind-web`) that ships
in three shells.

```
┌────────────────────────────────────────────────────────────────────┐
│                        Shells (UI only)                            │
│                                                                    │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │  PWA             │  │  Tauri desktop   │  │  Self-hosted     │  │
│  │  (installable,   │  │  (Win/Linux/mac) │  │  (lab server)    │  │
│  │   offline-ready) │  │  sidecar engine  │  │  multi-user      │  │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘  │
│           │  HTTP/WS            │  HTTP/WS            │  HTTP/WS    │
└───────────┼─────────────────────┼─────────────────────┼────────────┘
            │                     │                     │
            ▼                     ▼                     ▼
┌────────────────────────────────────────────────────────────────────┐
│                  corpusmind-engine (FastAPI)                       │
│                                                                    │
│  ┌──────────┐  ┌─────────┐  ┌─────────┐  ┌──────────┐  ┌────────┐ │
│  │ingestion │  │  nlp    │  │  stats  │  │  vision  │  │multi-  │ │
│  │          │  │ general │  │  (§12)  │  │          │  │modal   │ │
│  │          │  │ arabic  │  │         │  │          │  │        │ │
│  └──────────┘  └─────────┘  └─────────┘  └──────────┘  └────────┘ │
│                                                                    │
│  ┌──────────────────────────┐    ┌─────────────────────────────┐  │
│  │   AI layer (§11)         │    │   Storage                   │  │
│  │                          │    │                             │  │
│  │  ModelProvider           │    │  SQLite (metadata)          │  │
│  │   ├── Ollama             │    │  + positional full-text     │  │
│  │   ├── LM Studio          │    │    index (corpus)           │  │
│  │   └── Cloud (opt-in)     │    │  + annotation versions      │  │
│  │                          │    │                             │  │
│  │  ToolRegistry            │    │  File-backed projects       │  │
│  │  Conversation audit trail│    │                             │  │
│  └──────────────────────────┘    └─────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
            │
            ▼
   ┌─────────────────────┐
   │  Local LLM runtime  │
   │  (Ollama / LM Studio│
   │   on localhost)     │
   └─────────────────────┘
```

### Why this shape

The tension this resolves (§6 of the build prompt): a **PWA** is sandboxed
browser code — it cannot itself run spaCy / Stanza / CAMeL Tools pipelines or
a local LLM. A **Tauri desktop app** can, via sidecar processes. So "PWA for
seamless access" and "Ollama/LM Studio for local LLMs" pull in different
directions unless you design for it explicitly.

The resolution: one backend service does all heavy lifting, one frontend
talks only to its HTTP/WebSocket API, and the frontend ships three ways.
The AI Assistant never assumes where the model lives — it calls a
`ModelProvider` interface with three concrete implementations.

### Consequence for the desktop app

On first launch, `corpusmind-desktop` detects whether Ollama/LM Studio is
already installed and running; if not, it offers to launch a bundled sidecar
Ollama and lets the user pick/pull a model sized to their detected hardware
(RAM/VRAM). The Rust supervisor in `desktop/src-tauri/src/lib.rs` handles
the sidecar lifecycle per the known pitfalls (§3.4 of the build prompt):
target-triple binary naming, macOS quarantine stripping, log-to-file (not
piped — piped stdout hangs on buffer-size limits), and full child-process
detachment on app exit to avoid orphaned "zombie" Ollama processes.

## Module map (Phase 0)

| Path | Purpose | Phase |
| --- | --- | --- |
| `engine/app/` | FastAPI app factory, settings, logging | 0 ✅ |
| `engine/ai/providers.py` | `ModelProvider` abstraction (Ollama/LM Studio/Cloud) | 0 ✅ |
| `engine/ai/assistant.py` | Grounded-AI Assistant scaffold + tool registry + audit trail | 0 ✅ |
| `engine/api/` | REST routes (health, system, AI chat) | 0 ✅ |
| `engine/stats/measures.py` | All §12 formulas — collocation, keyness, dispersion, STTR | 0 ✅ |
| `engine/ingestion/` | Upload, cleaning, encoding/language detection | 1 |
| `engine/nlp/general/` | spaCy / Stanza / Trankit pipelines | 1 |
| `engine/nlp/arabic/` | CAMeL Tools, Farasa, SinaTools wrappers | 3 |
| `engine/discourse/` | Metadiscourse, stance/appraisal, metaphor (MIP/MIPVU), sentiment | 2 |
| `engine/vision/` | OCR, object/scene detection, composition/color | 4 |
| `engine/multimodal/` | Image-text alignment, cross-modal meaning, visual grammar scoring | 4 |
| `engine/storage/` | Corpus index, project DB, annotation store, versioning | 1 |
| `web/src/` | React + Vite + TS PWA | 0 ✅ (shell) |
| `desktop/src-tauri/` | Tauri 2 shell + Rust sidecar supervisor | 0 ✅ |
| `shared/` | OpenAPI-generated TS client (scaffold) | 0 ✅ |
| `reference-data/frameworks/` | Theoretical-lens prompt templates (§11.3) | 0 ✅ (one) |
| `infra/` | Docker Compose for self-hosted engine | 0 ✅ |

## Cross-cutting concerns

### Reproducibility (§4 Principle 8)

Every project pins the exact tokenizer, tagger, model, and formula versions
used. The engine stores an annotation-version UUID alongside every parsed
corpus, and the AI Assistant's audit trail records which model + provider +
prompt template produced each turn. The "Export Methods Section" feature
(§8.23, Phase 1) auto-drafts a methodology paragraph naming the exact
tools/versions/formulas used, for the user to paste into a manuscript.

### Grounded AI (§4 Principle 2, §11)

The Assistant is a tool-using agent, not a chatbot. On every user question:

1. The engine retrieves the smallest sufficient evidence — matching
   concordance lines, computed statistics, or image regions — via the same
   deterministic engine functions the UI itself calls.
2. The LLM is given the retrieved evidence plus a strict output schema
   (`claim`, `evidence_ids`, `confidence`, `framework`).
3. The UI renders the answer with every claim clickable back to its evidence.
4. If the LLM's claim cannot be tied to retrieved evidence, the UI visibly
   flags it as **UNGROUND** rather than silently presenting it as equal-weight
   fact — this is the load-bearing implementation of Principle 2.

The Phase 0 scaffold implements all four steps for the trivial `ping` tool;
Phase 1 expands the tool surface to `search_concordance`, `get_frequency`,
`compute_collocations`, `compute_keyness`, `get_dispersion`, `run_pos_query`,
`get_dependency_matches`, `describe_image_region`, `get_alignment`, and
`get_framework_template` (§11.2).

### Privacy (§4 Principle 1, §13.2)

- **Local-first by default.** Corpus text, images, and AI queries never leave
  the user's machine unless they explicitly opt in.
- **Cloud is opt-in and visibly indicated.** The `CloudProvider` is off by
  default; activating it requires explicit user action, and the UI shows an
  unmissable indicator whenever a cloud request is in flight.
- **Hard-disable switch.** Self-hosted lab deployments set
  `CORPUSMIND_CLOUD_DISABLED_HARD=true` (see `infra/docker-compose.yml`) —
  any request that would route to CloudProvider then returns 403. This is the
  belt-and-suspenders guarantee for shared/institutional machines.
- **No telemetry or analytics** without explicit, separate opt-in.

### Accessibility & i18n (§13.3)

- **WCAG 2.1 AA** target.
- **Full RTL mirroring** for Arabic — menus, ribbon, alignment — not just RTL
  text within an otherwise LTR-only UI. The `dir` attribute on `<html>` flips
  at runtime via the UI store, and the CSS uses logical properties
  (`inline-start`/`inline-end`, `block-start`/`block-end`) so layout mirrors
  automatically.
- **UI string externalization** from day one, so additional languages are a
  translation task, not a re-engineering task.

### Licensing compliance (§13.5)

Every bundled model, wordlist, and reference corpus has its license recorded
in `THIRD_PARTY_LICENSES.md`. The build (Phase 1) refuses to bundle anything
whose license hasn't been recorded there. This is release-blocking because
silently redistributing a non-redistributable asset is a legal liability for
both the project and its users.

## Open architectural decisions (§19)

These are tracked in the build prompt's §19. The Phase 0 build has resolved
them with the recommended defaults, but they remain explicitly reversible
before the first public release:

| Decision | Phase 0 choice | Reversible until |
| --- | --- | --- |
| Final product name | `CorpusMind` (placeholder confirmed) | First public commit |
| Engine language | Python 3.12 + FastAPI | Phase 0 lock |
| Frontend framework | React 18 + Vite + TS | Phase 0 lock |
| Collaboration model | Save-and-sync (CRDT deferred — see §7.4) | Phase 6 |
| Project license | AGPL-3.0-only | First public commit |
| Reference corpora | Open-frequency-derived approximations (no BNC/COCA bundling) | Phase 1 |
| CEFR wordlist | Open frequency-band approximation (no EVP bundling) | Phase 1 |
| Facial-analysis module | Opt-in, off by default (§18) | Phase 5 |
| Self-hosting model | Docker, single-tenant per instance (multi-tenant deferred) | Phase 6 |
