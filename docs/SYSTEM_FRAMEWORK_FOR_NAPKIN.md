# CorpusMind System Framework and Workflow
# For Napkin.AI Diagram Generation

## System Overview

CorpusMind is a three-tier local-first research environment for corpus
linguistics and multimodal discourse analysis. The system comprises:
  1. A FastAPI engine (Python 3.12) that performs all computation
  2. A Tauri 2 desktop shell (Rust) that supervises the engine lifecycle
  3. A React 18 PWA that provides the analyst interface

All three components run on the researcher's own machine. No data leaves
the device unless the user explicitly configures a remote AI provider.

---

## Diagram 1 — System Architecture (Three-Tier)

### Layout: stacked tiers, top to bottom

```
TIER 1: USER INTERFACE (React 18 PWA + Vite + TypeScript)
├── Ribbon navigation (8 analytical suites)
├── Command palette (Ctrl/Cmd+K)
├── Views: Home, Concordancer, Analysis, Arabic, Vision, Assistant, Corpus Manager, Settings, About
├── State: Zustand (app + UI stores)
├── Data fetching: native fetch to localhost:8765
└── PWA: installable, offline-capable, RTL Arabic support
        │
        │  HTTP (localhost:8765/api/v1/*)
        ▼
TIER 2: DESKTOP SHELL (Tauri 2 / Rust)
├── EngineSidecar supervisor (spawn, health-check, shutdown)
├── Process lifecycle management (no orphaned processes)
├── Log redirection (engine stdout/stderr → log files)
├── CSP enforcement (connect-src: 127.0.0.1:8765, 11434, 1234 only)
├── Capabilities: shell, dialog, fs, http (scoped to localhost)
└── Window management (1280×832, resizable, dark/light themes)
        │
        │  Spawns child process + polls /api/v1/health
        ▼
TIER 3: ANALYTICAL ENGINE (FastAPI / Python 3.12 / Uvicorn)
├── 85 API routes across 11 routers
├── SQLAlchemy 2.0 async (SQLite + optional AES-256-GCM encryption)
├── spaCy NLP pipeline (en_core_web_sm)
├── CAMeL Tools Arabic pipeline (morphology, dialect ID, NER)
├── OpenCV + Pillow vision pipeline
├── 20 statistical formulas (7 collocation + 6 keyness + 4 dispersion + 3 more)
├── 12 discourse-analysis frameworks (YAML schemas)
├── AI Assistant: 25 tool-calling agent, citation-enforced
└── Provenance: YAML record for every operation
        │
        │  Optional (user-elected)
        ▼
EXTERNAL (OPTIONAL): AI MODEL PROVIDERS
├── Local: Ollama (127.0.0.1:11434), LM Studio (127.0.0.1:1234)
└── Remote (opt-in): OpenAI, Anthropic, Google
```

---

## Diagram 2 — Engine Internal Architecture

### Layout: hub-and-spoke, FastAPI app at center

```
                    ┌─────────────────┐
                    │  FastAPI App    │
                    │  (app/main.py)  │
                    │  85 routes      │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐  ┌──────────────────┐  ┌───────────────┐
│  INGESTION    │  │     NLP          │  │   STORAGE     │
│  ingestion/   │  │     nlp/         │  │   storage/    │
│               │  │                  │  │               │
│ • parsing.py  │  │ • general/       │  │ • models.py   │
│   (TXT,DOCX,  │  │   (spaCy:        │  │   (15 tables) │
│   PDF,HTML,   │  │   tokenize,      │  │ • session.py  │
│   XML,CSV,MD) │  │   lemma,POS,     │  │   (async DB)  │
│ • service.py  │  │   dep,NER)       │  │ • encryption  │
│   (charset,   │  │ • arabic/        │  │   (AES-256)   │
│   language ID)│  │   (CAMeL Tools:  │  │ • research.py │
│               │  │   morphology,    │  │   (saved      │
│               │  │   dialect,NER)   │  │   searches,   │
│               │  │ • bilingual.py   │  │   bookmarks)  │
└───────────────┘  │   (alignment)    │  └───────────────┘
                   └──────────────────┘
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐  ┌──────────────────┐  ┌───────────────┐
│   STATS       │  │   VISION         │  │ MULTIMODAL    │
│   stats/      │  │   vision/        │  │ multimodal/   │
│               │  │                  │  │               │
│ • measures.py │  │ • pipeline.py    │  │ • visual_     │
│   (MI, T-score│  │   (OpenCV:       │  │   grammar.py  │
│   LL, Dice,   │  │   objects, faces,│  │   (Kress &    │
│   LogDice,    │  │   OCR, colour,   │  │   van Leeuwen)│
│   chi-sq,DP)  │  │   composition)   │  │ • alignment.py│
│ • keyness     │  │ • facial.py      │  │   (image-text)│
│   (LL, chi-sq,│  │   (age,gender,   │  │ • discourse.py│
│   LogRatio,   │  │   emotion)       │  │   (8 frameworks│
│   %DIFF,      │  │                  │  │   on images)  │
│   OddsRatio)  │  │                  │  │               │
│ • dispersion  │  │                  │  │               │
│   (Juilland D,│  │                  │  │               │
│   Gries DP,   │  │                  │  │               │
│   ARF, AWT)   │  │                  │  │               │
└───────────────┘  └──────────────────┘  └───────────────┘
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐  ┌──────────────────┐  ┌───────────────┐
│  DISCOURSE    │  │   AI ASSISTANT   │  │   EXPORT      │
│  discourse/   │  │   ai/            │  │   api/export  │
│               │  │                  │  │               │
│ • service.py  │  │ • providers.py   │  │ • Excel (.xlsx│
│   (12         │  │   (Ollama,       │  │   concordance,│
│   frameworks: │  │   LM Studio,     │  │   frequency,  │
│   SFL, Visual │  │   OpenAI,        │  │   collocations│
│   Grammar,    │  │   Anthropic)     │  │   keyness)    │
│   CDA, DHA,   │  │ • tools.py       │  │ • Word (.docx)│
│   SCA, MCDA,  │  │   (25 tools:     │  │ • PDF         │
│   Appraisal,  │  │   concordance,   │  │   (methods.pdf│
│   CMT,        │  │   collocation,   │  │    with       │
│   Toulmin,    │  │   keyness,       │  │    citations) │
│   Aristotle)  │  │   vision, etc.)  │  │ • LaTeX       │
│               │  │ • assistant.py   │  │ • YAML        │
│               │  │   (citation-     │  │   (provenance)│
│               │  │   enforced agent)│  │               │
└───────────────┘  └──────────────────┘  └───────────────┘
```

---

## Diagram 3 — User Workflow (Research Lifecycle)

### Layout: horizontal flow, left to right, 7 stages

```
STAGE 1          STAGE 2          STAGE 3          STAGE 4
PROJECT          CORPUS           NLP              ANALYSIS
CREATION         INGESTION        PROCESSING       TOOLS
                 │
                 ▼
┌─────────┐     ┌─────────┐      ┌─────────┐     ┌─────────┐
│ New     │────▶│ Import  │─────▶│ Charset │────▶│ Concord-│
│ Project │     │ docs:   │      │ detect  │     │ ance    │
│ (name,  │     │ TXT DOCX│      │ Language│     │ (KWIC,  │
│ lang)   │     │ PDF HTML│      │ Tokenize│     │ stable  │
│         │     │ XML CSV │      │ Lemma   │     │ line IDs│
│         │     │ MD      │      │ POS tag │     │         │
│         │     └─────────┘      │ Dep     │     │ Freq    │
│         │                      │ parse   │     │ (STTR)  │
│         │                      │ NER     │     │         │
│         │                      │         │     │ Colloc  │
│         │                      │ Arabic: │     │ (7      │
│         │                      │ CAMeL   │     │ measures│
│         │                      │ Tools   │     │         │
│         │                      │ (root,  │     │ Keyness │
│         │                      │ pattern,│     │ (6      │
│         │                      │ dialect)│     │ measures│
│         │                      └─────────┘     │         │
│         │                                      │ Dispers │
│         │                                      │ (4      │
│         │                                      │ measures│
│         │                                      │         │
│         │                                      │ N-grams │
│         │                                      │ Grammar │
│         │                                      │ Dep     │
│         │                                      │ Vocab   │
│         │                                      │ Sentiment│
│         │                                      │ Metaphor│
│         │                                      │ Metadisc│
└─────────┘                                      └────┬────┘
    │                                                 │
    │    STAGE 5          STAGE 6          STAGE 7    │
    │    VISION &         AI               EXPORT &   │
    │    MULTIMODAL       ASSISTANT        PROVENANCE │
    │    │                │                │          │
    │    ▼                ▼                ▼          │
    │  ┌─────────┐      ┌─────────┐      ┌─────────┐  │
    │  │ Image   │      │ Ask    │      │ Excel   │◀─┘
    │  │ ingest  │      │ question│      │ Word    │
    │  │ (JPG,   │      │         │      │ PDF     │
    │  │ PNG,    │      │ Agent   │      │ LaTeX   │
    │  │ TIFF,   │      │ selects │      │         │
    │  │ WebP)   │      │ tool    │      │ YAML    │
    │  │         │      │         │      │ proven- │
    │  │ Vision  │      │ Tool    │      │ ance    │
    │  │ pipeline│      │ executes│      │ record  │
    │  │ (OCR,   │      │         │      │         │
    │  │ objects,│      │ Answer  │      │ methods │
    │  │ faces,  │      │ GROUNDED│      │ .pdf    │
    │  │ colour, │      │ (cited) │      │ (auto-  │
    │  │ composi-│      │ OR      │      │  drafted│
    │  │ tion)   │      │ UNSUPP- │      │  methods│
    │  │         │      │ ORTED   │      │  section│
    │  │ Visual  │      │ (flagged│      │  with   │
    │  │ Grammar │      │  )      │      │  citat- │
    │  │ (Kress &│      └─────────┘      │  ions)  │
    │  │ van Leeu│                       └─────────┘
    │  │ wen)    │
    │  │         │
    │  │ Multimo-│
    │  │ dal     │
    │  │ align   │
    │  │ (image- │
    │  │ text)   │
    │  │         │
    │  │ 8       │
    │  │ discourse│
    │  │ frameworks│
    │  │ on images│
    │  └─────────┘
    └──────────────▶ (feeds back into AI Assistant as tool input)
```

---

## Diagram 4 — AI Assistant Citation-Enforced Contract

### Layout: vertical flow with decision branch

```
         ┌─────────────────────────┐
         │  USER ASKS A QUESTION   │
         │  e.g., "What are the    │
         │  strongest collocates   │
         │  of 'research'?"        │
         └────────────┬─────────────┘
                      │
                      ▼
         ┌─────────────────────────┐
         │  AI ASSISTANT AGENT     │
         │  (ai/assistant.py)      │
         │                         │
         │  Selects from 25 tools: │
         │  • search_concordance   │
         │  • compute_collocations │
         │  • get_frequency        │
         │  • compute_keyness      │
         │  • arabic_morphology    │
         │  • visual_grammar       │
         │  • ... (19 more)        │
         └────────────┬─────────────┘
                      │
                      ▼
         ┌─────────────────────────┐
         │  TOOL EXECUTES          │
         │  (ai/tools.py)          │
         │                         │
         │  Queries the corpus via │
         │  SQLAlchemy async session│
         │  Returns structured data│
         └────────────┬─────────────┘
                      │
                      ▼
              ┌───────────────┐
              │  EVIDENCE     │
              │  CHECK        │
              └───────┬───────┘
                      │
           ┌──────────┴──────────┐
           │                     │
      EVIDENCE FOUND        NO EVIDENCE
           │                     │
           ▼                     ▼
  ┌─────────────────┐  ┌─────────────────┐
  │  ANSWER MARKED  │  │  ANSWER MARKED  │
  │  "GROUNDED"     │  │  "UNSUPPORTED"  │
  │  (green badge)  │  │  (orange badge) │
  │                 │  │                 │
  │  Cites:         │  │  Explicitly     │
  │  • concordance  │  │  flagged to user│
  │    line ID      │  │  — never        │
  │  • collocation  │  │  presented as   │
  │    statistic    │  │  fact           │
  │  • vision       │  │                 │
  │    annotation   │  │                 │
  └─────────────────┘  └─────────────────┘
           │                     │
           └──────────┬──────────┘
                      │
                      ▼
         ┌─────────────────────────┐
         │  PROVENANCE RECORD      │
         │  (YAML)                 │
         │                         │
         │  • timestamp            │
         │  • tool called          │
         │  • input parameters     │
         │  • AI provider used     │
         │    (local or remote)    │
         │  • model name           │
         │  • grounded: true/false │
         └─────────────────────────┘
```

---

## Diagram 5 — Data Flow and Privacy Boundary

### Layout: concentric zones showing what stays local vs. what goes out

```
    ┌─────────────────────────────────────────────────────────┐
    │                   RESEARCHER'S MACHINE                  │
    │                                                         │
    │  ┌───────────────────────────────────────────────────┐  │
    │  │              LOCAL-FIRST ZONE (default)           │  │
    │  │                                                   │  │
    │  │  ┌─────────────┐  ┌─────────────┐  ┌───────────┐ │  │
    │  │  │  Corpus     │  │  Engine     │  │  Desktop  │ │  │
    │  │  │  data       │  │  (FastAPI)  │  │  (Tauri)  │ │  │
    │  │  │  (SQLite +  │  │  :8765      │  │  shell    │ │  │
    │  │  │  encrypted) │  │             │  │           │ │  │
    │  │  └─────────────┘  └─────────────┘  └───────────┘ │  │
    │  │          │              │                │        │  │
    │  │          └──────────────┴────────────────┘        │  │
    │  │                    localhost only                 │  │
    │  │                                                   │  │
    │  │  ┌─────────────────────────────────────────────┐  │  │
    │  │  │  OPTIONAL: LOCAL AI (Ollama / LM Studio)    │  │  │
    │  │  │  :11434 / :1234                             │  │  │
    │  │  │  Fully offline — no data leaves the machine │  │  │
    │  │  └─────────────────────────────────────────────┘  │  │
    │  └───────────────────────────────────────────────────┘  │
    │                                                         │
    │  ┌───────────────────────────────────────────────────┐  │
    │  │  OPT-IN ZONE (only if user explicitly configures) │  │
    │  │                                                   │  │
    │  │  ┌─────────────────────────────────────────────┐  │  │
    │  │  │  REMOTE AI PROVIDER (OpenAI / Anthropic)    │  │  │
    │  │  │                                             │  │  │
    │  │  │  Only the AI prompt is transmitted.         │  │  │
    │  │  │  The corpus itself NEVER leaves the device. │  │  │
    │  │  │  The provider + model are recorded in the   │  │  │
    │  │  │  provenance YAML.                           │  │  │
    │  │  └─────────────────────────────────────────────┘  │  │
    │  └───────────────────────────────────────────────────┘  │
    │                                                         │
    └─────────────────────────────────────────────────────────┘

    CSP enforcement (tauri.conf.json):
      connect-src: 'self'
                   http://127.0.0.1:8765    (engine)
                   http://127.0.0.1:11434   (Ollama)
                   http://127.0.0.1:1234    (LM Studio)
    No other outbound connections permitted by default.
```

---

## Diagram 6 — Technology Stack (Layered)

### Layout: vertical stack, foundation to user

```
┌─────────────────────────────────────────────────────────────┐
│  USER INTERFACE LAYER                                       │
│  React 18 · Vite 5 · TypeScript 5.6 · Zustand             │
│  vite-plugin-pwa (installable, offline)                     │
│  TanStack Query · full RTL Arabic support                   │
├─────────────────────────────────────────────────────────────┤
│  DESKTOP SHELL LAYER                                        │
│  Tauri 2 (Rust) · reqwest (blocking) · tokio               │
│  tauri-plugin-shell · dialog · fs · http                   │
│  EngineSidecar supervisor · CSP enforcement                 │
├─────────────────────────────────────────────────────────────┤
│  API LAYER                                                  │
│  FastAPI · Pydantic 2 · Uvicorn · OpenAPI auto-docs         │
│  85 routes across 11 routers · CORS (localhost only)        │
├─────────────────────────────────────────────────────────────┤
│  NLP LAYER                                                  │
│  spaCy (en_core_web_sm) — tokenize, lemma, POS, dep, NER   │
│  CAMeL Tools — Arabic morphology, dialect ID, NER          │
│  SinaTools — Arabic tokenize/lemma                         │
│  Farasa — Arabic segmentation                              │
├─────────────────────────────────────────────────────────────┤
│  STATISTICS LAYER                                           │
│  NumPy · SciPy · statsmodels · pingouin                    │
│  7 collocation measures · 6 keyness measures               │
│  4 dispersion measures · STTR · n-grams                    │
├─────────────────────────────────────────────────────────────┤
│  VISION LAYER                                               │
│  OpenCV · Pillow · Tesseract OCR (with Arabic pack)        │
│  Object detection · facial analysis · colour · composition │
├─────────────────────────────────────────────────────────────┤
│  DISCOURSE LAYER                                            │
│  12 framework YAML schemas:                                 │
│  Halliday SFL · Kress & van Leeuwen Visual Grammar         │
│  Barthes · Peirce · Fairclough CDA · Wodak DHA             │
│  van Dijk SCA · Machin & Mayr MCDA · Martin & White        │
│  Lakoff & Johnson CMT · Toulmin · Aristotle                │
├─────────────────────────────────────────────────────────────┤
│  AI ASSISTANT LAYER                                         │
│  25 tool-calling agent · citation-enforced contract         │
│  Providers: Ollama · LM Studio · OpenAI · Anthropic        │
│  Grounded (cited) or Unsupported (flagged)                  │
├─────────────────────────────────────────────────────────────┤
│  STORAGE LAYER                                              │
│  SQLAlchemy 2.0 async · SQLite · aiosqlite                 │
│  15 tables (Project, Corpus, Document, Token, etc.)        │
│  Optional AES-256-GCM at-rest encryption (PBKDF2, 600k)    │
├─────────────────────────────────────────────────────────────┤
│  PROVENANCE LAYER                                           │
│  YAML records for every operation                           │
│  methods.pdf export (auto-drafted methodology section)      │
│  Reproducible by design — peer-review ready                 │
├─────────────────────────────────────────────────────────────┤
│  FOUNDATION                                                 │
│  Python 3.12 · Rust 1.77+ · Node 20 · AGPL-3.0-only        │
│  Cross-platform: macOS (arm64 + x86_64) · Windows · Linux  │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Numbers (for diagram annotations)

- **85** API routes
- **25** AI assistant tools
- **12** discourse-analysis frameworks
- **20** statistical formulas (7 collocation + 6 keyness + 4 dispersion + 3 more)
- **15** database tables
- **8** analytical suites in the UI
- **6** export formats (Excel, Word, PDF, LaTeX, YAML, methods.pdf)
- **4** AI model providers (Ollama, LM Studio, OpenAI, Anthropic)
- **3** tiers (UI, desktop shell, engine)
- **2** NLP pipelines (English via spaCy, Arabic via CAMeL Tools)
- **1** citation-enforced contract (grounded or unsupported)

---

## Color Palette (for Napkin.AI styling)

- Primary (navy): #0A1C3C
- Secondary (CorpusMind green): #0b6e4f
- Accent (teal): #1A5F7A
- Light: #f0f4f7
- Warm (citations): #8B4513
- Paper (citation background): #FFF8E7

---

## Notes for Napkin.AI

1. Diagram 1 (System Architecture) is the most important — it shows the
   three-tier separation and the privacy boundary.

2. Diagram 3 (User Workflow) should be read left-to-right with a feedback
   loop from Stage 5/6 back to Stage 4 (vision and AI feed into analysis).

3. Diagram 4 (AI Citation Contract) is the unique selling proposition —
   no other corpus tool has this. Emphasize the GROUNDED vs UNSUPPORTED
   branch.

4. Diagram 5 (Privacy Boundary) shows what stays local vs. what goes out.
   The opt-in zone should be visually distinct (dashed border) to show
   it is not the default.

5. All diagrams should use the CorpusMind green (#0b6e4f) as the primary
   accent color, with navy (#0A1C3C) for text.
