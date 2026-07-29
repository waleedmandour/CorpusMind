# CorpusMind

[![DOI](https://img.shields.io/badge/DOI-10.5281%2Fzenodo.21226650-blue)](https://doi.org/10.5281/zenodo.21226650)
[![License: AGPL-3.0-only](https://img.shields.io/badge/License-AGPL--3.0--only-blue.svg)](https://www.gnu.org/licenses/agpl-3.0.html)
[![GitHub release](https://img.shields.io/badge/release-v1.0.0-blue)](https://github.com/waleedmandour/CorpusMind/releases)
[![Build Status](https://img.shields.io/badge/CI-passing-brightgreen)](https://github.com/waleedmandour/CorpusMind/actions)

> A local-first, AI-native research environment for corpus linguistics and multimodal discourse analysis.

CorpusMind lets a linguist go from raw texts and images to publication-ready
quantitative and qualitative analysis — without writing a line of code, without
sending unpublished data to a third-party server unless they explicitly choose
to, and without losing the methodological transparency that peer review demands.

It ships as two integrated suites sharing one project system, one AI layer, and
one design language:

- **CorpusMind Text** — a next-generation corpus-analysis workbench
  (concordancing, frequency, collocation, keyness, n-grams, dispersion,
  vocabulary / POS / grammar / dependency / semantic / discourse / pragmatic /
  metaphor / sentiment analysis, with first-class Arabic support).
- **CorpusMind Vision** — an AI research assistant for multimodal discourse
  analysis, grounded in Visual Grammar (Kress & van Leeuwen), Systemic
  Functional Linguistics, Critical Discourse Analysis, Multimodal CDA, Social
  Semiotics, and Cognitive Linguistics.

Both suites are reachable from a **Progressive Web App** (installable,
offline-capable, deployed at [corpus-mind-web.vercel.app](https://corpus-mind-web.vercel.app/))
and from **native desktop apps** for Windows, Linux, and macOS (built with Tauri 2).
Local LLM inference via **Ollama** and/or **LM Studio** lets the AI Assistant
run entirely on the researcher's own machine.

---

## Status

**Suite A (Text):** complete through Phase 6 (cleaning, corpus hub, research features,
deterministic AI layer, Ollama auto-start, multi-format export, professional UI).

**Suite B (Vision):** backend implemented (20+ endpoints for image analysis, Visual
Grammar, multimodal alignment), UI integration in progress — currently shows
"Coming Soon" in the app.

### Phase 0 — Foundations ✅
- ✅ Monorepo scaffold
- ✅ `corpusmind-engine` skeleton with health-check API
- ✅ `corpusmind-web` skeleton as an installable PWA
- ✅ `corpusmind-desktop` Tauri 2 shell that can spawn the engine as a sidecar
- ✅ `ModelProvider` abstraction wired to Ollama, LM Studio, and an opt-in Cloud provider
- ✅ Working "hello world" grounded-AI chat round-trip (with citation-or-flag contract)
- ✅ Statistical measures from 12 (collocation, keyness, dispersion, STTR) with unit tests
- ✅ Ribbon-style shell UI and theme system (dark/light, RTL-ready)

### Phase 1 — Suite A MVP ✅
- ✅ Storage layer — SQLAlchemy 2.0 async models (projects, corpora, documents, tokens, annotation versions, persisted conversations)
- ✅ Ingestion — TXT / DOCX / PDF / HTML / XML / CSV / MD parsing with charset detection + spaCy NLP
- ✅ Corpus management — full CRUD + drag-and-drop upload + visible pipeline recipe (4.8 reproducibility)
- ✅ Concordancer — KWIC search with stable line IDs (cited by the AI Assistant), lemma/word/POS levels, wildcards
- ✅ Frequency analysis — word / lemma / POS with STTR as the comparably valid default
- ✅ Collocation analysis — all 7 12 measures (MI, T-score, LL, Dice, LogDice, χ², ΔP) with configurable window
- ✅ Keyness analysis — significance (LL, χ²) AND effect size (Log Ratio, %DIFF, Simple Maths, Odds Ratio) always together (4 Principle 3)
- ✅ Dispersion — Juilland's D and Gries' DP across documents
- ✅ Grounded-AI tool surface — `search_concordance`, `get_frequency`, `compute_collocations`, `compute_keyness`, `get_dispersion`; conversations persist in SQLite
- ✅ Export — Excel + CSV + TSV + TXT + JSON (concordance/frequency/collocation/keyness) + collocation network diagrams (SVG + PNG) + auto-drafted Methods PDF
- ✅ Web UI — corpus manager, concordancer, analysis tabs, Assistant with clickable evidence citations

### Phase 2 — Suite A completion ✅
- ✅ 8.8 N-grams + lexical bundles (frequency-and-range criterion, Biber et al.)
- ✅ 8.10 Vocabulary profiling (K1/K2-K9/AWL/Off-list bands; rare words; academic words)
- ✅ 8.11 POS analysis (distribution + POS n-grams 1–5)
- ✅ 8.12 Grammar analysis (dependency-driven: passive, modal, negation, relative clause, complex NP, tense)
- ✅ 8.13 Dependency analysis (governor-dependent pairs for any UD relation)
- ✅ 8.15 Discourse analysis (Hyland's interactive + interactional metadiscourse taxonomy)
- ✅ 8.17 Metaphor candidates (MIPVU-inspired, LLM-triaged, human-verified gate)
- ✅ 8.18 Sentiment analysis (lexicon-based, per-sentence timeline)
- ✅ 8 new grounded-AI tools (14 total): `get_ngrams`, `get_pos_analysis`, `grammar_query`, `dependency_query`, `discourse_analysis`, `vocab_profile`, `sentiment`, `metaphor_candidates`
- ✅ 46 tests passing (23 stats + 9 Phase 1 API + 14 Phase 2 API)
- ✅ Code review completed: 149 ruff lint errors → 0; spec compliance audit documented

### Phase 3 — Arabic depth pass ✅
- ✅ 8.21 CAMeL Tools integration (calima-msa-r13 morphology DB; Egyptian/Gulf/Levantine DBs available)
- ✅ 8.21 Root extraction (الجذر) — e.g. `المكتبة → ك.ت.ب`
- ✅ 8.21 Pattern (وزن) identification — e.g. `يُ1ْ2ِ3`, `المَ1ْ2َ3َة`
- ✅ 8.21 Lemma normalization + diacritics handling (user-controlled)
- ✅ 8.21 Buckwalter transliteration — `الطلاب → AlTlAb`
- ✅ 8.21 Clitic segmentation
- ✅ 8.21 Dialect identification (MSA/Egyptian/Gulf/Levantine; heuristic starter)
- ✅ 8.21 Register detection (Classical / MSA / Dialectal)
- ✅ 8.21 Normalization (alef variants, teh marbuta, alef maksura)
- ✅ 8.21 Backend abstraction (CAMeL default; Farasa + SinaTools stubbed — swappable per 3.3)
- ✅ 5 new grounded-AI tools (19 total): `arabic_morphology`, `arabic_dialect_id`, `arabic_roots`, `arabic_register`, `arabic_transliterate`
- ✅ Web UI: 8-tool Arabic workbench with RTL input + sample texts + dialect picker
- ✅ 56 tests passing (23 stats + 9 Phase 1 + 14 Phase 2 + 10 Phase 3 Arabic)

### Phase 6 — Polish, tooling, and research workflow ✅
- ✅ **Smart Troubleshooting** — backend error detection during app use, shown in the taskbar; optional Gemini-powered interpretation + suggested fix; one-click "Report to developer" email flow
- ✅ **In-app User Guide** — 18-section professional guide in the sidebar (Getting Started, Concordance, Frequency/STTR, Collocation, Keyness, Arabic Tools, Vision Suite, AI Assistant, Privacy, Troubleshooting, Reproducibility, Shortcuts, Citation)
- ✅ **Corpus Cleaning** — per-corpus on-demand re-cleaning with 16 options (whitespace, URLs, emails, lowercase, punctuation, numbers, emoji, stopwords, min token length, Arabic normalization/diacritics/tatweel)
- ✅ **Corpus Hub** — search + download open-access corpora in Arabic and English from three hubs: HuggingFace datasets-server (Wikipedia, OSCAR, CC-100), Wikipedia live (ar + en), OPUS (parallel ar↔en translation pairs)
- ✅ **Multi-format export** — all analysis results exportable in 5 formats (Excel, CSV, TSV, TXT, JSON) via a unified format-parameterized API
- ✅ **Diagram export** — collocation network diagrams exportable as SVG (vector) and PNG (raster 1600×1200)
- ✅ **Windows build script** — `scripts/build-corpusmind-windows.ps1` produces both NSIS `.exe` and MSI `.msi`, uninstalls previous versions, installs for the current user
- ✅ **CI fixes** — Desktop (Rust) job now passes (externalBin clearing pattern + E0597 lifetime fix); engine tests improved from 71→88 passing by downloading the spaCy model in CI

### 🚧 Phase 4 — Suite B MVP (Vision)
- 🚧 Image ingestion, OCR, Visual Grammar (Kress & van Leeuwen), multimodal image–text alignment; + 8.22 bilingual tools + full CAMeL DialectIdentifier model

---

## Non-Negotiable Design Principles

These translate the [research-basis gap analysis](docs/AI_AGENT_BUILD_PROMPT.md#3-research-basis) into concrete engineering mandates. Do not trade these away for convenience.

1. **Local-first, cloud-optional.** By default, corpus text, images, and AI queries never leave the user's machine. Cloud LLM providers are an explicit, per-project, opt-in fallback with a visible indicator whenever active.
2. **Grounded AI, never a bare chatbot.** Every AI Assistant answer that makes an empirical claim must carry a citation back to a concordance line ID, an image region, or a computed statistic the engine can reproduce on demand.
3. **Effect size and significance, always together.** A "key" word is never reported as important on frequency-of-occurrence-in-a-huge-corpus grounds alone — Log Ratio, %DIFF, Simple Maths, and Odds Ratio ride alongside log-likelihood.
4. **Zero-code, not zero-transparency.** Every one-click automatic output (a POS tag, a keyness list, a "power relation" score) is inspectable: the user can always see which model / formula / version produced it, and can export that as citeable methodology text.
5. **Interpretive claims are hypotheses, framework-lensed, not facts.** Anything in the CDA / MCDA / ideology / power / persuasion family is labeled with the theoretical framework that produced it and phrased as *"under a [Framework] reading, X may indicate Y"* — never as a bare assertion.
6. **Arabic is a first-class citizen, not a bolt-on.** RTL layout, dialect-aware tooling, and the CAMeL Tools / SinaTools / Farasa ecosystem are part of the core architecture from day one.
7. **Practical scale, honestly stated.** Currently tested with corpora up to ~100K tokens on consumer hardware. The collocation and concordance analysis loads token streams into memory per query (MVP implementation). A SQLite FTS5 positional index for production-scale corpora (millions of tokens) is a roadmap item, not yet implemented.
8. **Reproducibility is a feature.** Every project pins the exact tokenizer, tagger, model, and formula versions used, and can emit a "Methods" paragraph for a paper's methodology section.
9. **Consent and restraint around biometric-adjacent features.** Facial/body "age group," "gender presentation," "emotion," "gaze," and dominance/submission inference ship as an opt-in module, disabled by default, and never perform identity recognition or re-identification of real individuals.

---

## Quickstart

### Prerequisites

- Python 3.12+
- Node.js 20+ (for the web frontend)
- [Rust + Cargo](https://rustup.rs/) (only if you want to build the Tauri desktop app)
- [Ollama](https://ollama.com/) **or** [LM Studio](https://lmstudio.ai/) for local LLM inference

### 1. Run the engine

```bash
cd engine
python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
corpusmind-engine            # serves on http://127.0.0.1:8765
```

Health check:

```bash
curl http://127.0.0.1:8765/api/v1/health
# {"status":"ok","engine":"corpusmind-engine","version":"0.1.2"}
```

### 2. Run the web frontend (PWA)

```bash
cd web
npm install
npm run dev                  # serves on http://localhost:5173
```

Open http://localhost:5173 — the app talks to the engine on :8765 by default.
To install as a PWA, use your browser's "Install app" menu item.

**Live demo:** The PWA is also deployed at
[corpus-mind-web.vercel.app](https://corpus-mind-web.vercel.app/).
Note: the demo PWA needs a running engine instance to function. Point it at
your engine by setting `VITE_ENGINE_URL` during build or in the Vercel
environment variables. See [docs/BUILD_GUIDE.md](docs/BUILD_GUIDE.md) for
Vercel deployment instructions.

### 3. Run the desktop app (Tauri 2)

```bash
cd desktop/src-tauri
cargo tauri dev
```

On first launch the desktop app spawns `corpusmind-engine` as a sidecar
process and (optionally) a bundled Ollama binary.

### 4. Try the grounded-AI round-trip

```bash
curl -X POST http://127.0.0.1:8765/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"ping the engine to prove tool-calling works","provider":"ollama"}'
```

The response includes `grounded: true` and a `tool_calls` array. The UI renders
grounded answers with citations; ungrounded answers (no tool was invoked) get a
visible badge — this is the load-bearing implementation of Principle 2.

### 5. End-to-end Phase 1 workflow (create → upload → analyze → export)

```bash
# Create a project + corpus
PID=$(curl -s -X POST http://127.0.0.1:8765/api/v1/projects \
  -H "Content-Type: application/json" \
  -d '{"name":"My Research","language":"en"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")

CID=$(curl -s -X POST http://127.0.0.1:8765/api/v1/projects/$PID/corpora \
  -H "Content-Type: application/json" \
  -d '{"name":"Corpus A","language":"en"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")

# Upload text files (drag-drop in the UI; here via curl)
curl -X POST http://127.0.0.1:8765/api/v1/corpora/$CID/documents \
  -F "files=@some_text.txt" -F "files=@another.docx"

# Concordance search
curl -X POST http://127.0.0.1:8765/api/v1/corpora/$CID/concordance \
  -H "Content-Type: application/json" \
  -d '{"query":"research","level":"lemma","window":5,"limit":20}'

# Collocations
curl -X POST http://127.0.0.1:8765/api/v1/corpora/$CID/collocations \
  -H "Content-Type: application/json" \
  -d '{"node":"research","level":"lemma","window":5,"min_freq":2}'

# Frequency with STTR
curl -X POST http://127.0.0.1:8765/api/v1/corpora/$CID/frequency \
  -H "Content-Type: application/json" -d '{"unit":"word","limit":50}'

# Export — multi-format (xlsx, csv, tsv, txt, json)
curl -X POST "http://127.0.0.1:8765/api/v1/corpora/$CID/export/frequency?fmt=csv" \
  -H "Content-Type: application/json" -d '{"unit":"word","limit":200}' -o frequency.csv

# Collocation network diagram (SVG or PNG)
curl -X POST http://127.0.0.1:8765/api/v1/corpora/$CID/export/collocations.network.svg \
  -H "Content-Type: application/json" -d '{"node":"research","level":"lemma","window":5,"min_freq":2}' -o network.svg

# Auto-drafted Methods Section PDF
curl http://127.0.0.1:8765/api/v1/corpora/$CID/methods.pdf -o methods.pdf
```

Or just open http://localhost:5173 and use the ribbon UI — Text Suite tab has
Manage / Concordance / Analyze sub-tabs.

---

## Architecture

```
corpusmind/
├── engine/            # corpusmind-engine — Python (FastAPI) service
│   ├── ingestion/     # upload, cleaning, encoding/language detection
│   ├── nlp/           # tokenization, POS, lemmatization, dependency parsing
│   │   ├── general/   # spaCy / Stanza / Trankit pipelines
│   │   └── arabic/    # CAMeL Tools, Farasa, SinaTools, CamelParser2.0 wrapper
│   ├── stats/         # frequency, collocation, keyness, dispersion, n-grams  ← 12 formulas
│   ├── discourse/     # metadiscourse, stance/appraisal, metaphor (MIP/MIPVU), sentiment
│   ├── vision/        # OCR, object/scene detection, composition/color analysis
│   ├── multimodal/    # image-text alignment, cross-modal meaning, visual grammar scoring
│   ├── ai/            # ModelProvider abstraction, RAG index, tool-calling layer, prompt templates
│   ├── storage/       # corpus index, project DB, annotation store, versioning
│   └── api/           # REST + WebSocket routes, OpenAPI schema
├── web/               # corpusmind-web — single frontend (PWA + embedded in Tauri)
│   ├── src/
│   ├── public/manifest.webmanifest
│   └── service-worker.ts
├── desktop/           # corpusmind-desktop — Tauri 2 project
│   ├── src-tauri/
│   │   ├── tauri.conf.json   # sidecar + capability config
│   │   └── src/              # Rust: sidecar lifecycle, OS integration
│   └── binaries/             # platform-tagged sidecar executables
├── shared/            # shared TS types / OpenAPI-generated client
├── reference-data/    # bundled reference corpora, wordlists, framework prompt templates
├── docs/              # architecture, methodology, the build prompt itself
└── infra/             # Docker Compose for self-hosted engine, CI
```

The single most important architectural call: **a headless engine, multiple shells.**
A PWA is sandboxed browser code — it cannot itself run spaCy / Stanza / CAMeL
Tools pipelines or a local LLM. A Tauri desktop app can. So we build one backend
service (`corpusmind-engine`) that does all heavy lifting, one frontend
(`corpusmind-web`) that talks only to its HTTP/WebSocket API, and ship that
frontend three ways: as a PWA, embedded in Tauri, and as a self-hosted
multi-user engine for labs.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the living diagram.

---

## Statistical Transparency

Every formula is implemented to the precise, named definition in
[docs/METHODOLOGY.md](docs/METHODOLOGY.md) — and is unit-tested against
published worked examples. A wrong constant in a keyness formula is a silent,
serious validity bug, so this is treated as a release-blocking test category.

| Measure | Use | Definition |
| --- | --- | --- |
| MI (Church & Hanks 1990) | Collocation | `log2(O / E)`, `E = R·C / N` |
| T-score | Collocation | `(O − E) / sqrt(O)` |
| Log-likelihood / G² (Dunning 1993) | Collocation, keyness | `2 · Σ Oᵢⱼ · ln(Oᵢⱼ / Eᵢⱼ)` |
| Dice | Collocation | `2·f(x,y) / (f(x) + f(y))` |
| LogDice (Rychlý 2008) | Collocation | `14 + log2( 2·f(x,y) / (f(x) + f(y)) )` |
| Chi-square | Collocation, keyness | Pearson χ² on the 2×2 table |
| Delta P (Gries 2013; Ellis 2007) | Collocation (directional) | `P(y|x) − P(y|¬x)`, both directions |
| Log Ratio (Hardie 2014) | Keyness effect size | `log2( (f1/N1) / (f2/N2) )` |
| %DIFF (Gabrielatos & Marchi 2012) | Keyness effect size | `((norm_f1 − norm_f2) / norm_f2) × 100` |
| Simple Maths (Kilgarriff 2009) | Keyness score | `(norm_f1 + SMOOTH) / (norm_f2 + SMOOTH)` |
| Odds Ratio | Keyness effect size | `(f1 · (N2−f2)) / (f2 · (N1−f1))` |
| Juilland's D | Dispersion | `1 − (CV / sqrt(n−1))` across n parts |
| Gries' DP (2008) | Dispersion | `0.5 · Σ |observed_proportionᵢ − expected_proportionᵢ|` |
| STTR | Lexical variation | TTR over fixed-size chunks, averaged |

All statistics are **computed by these pure functions**, never by an LLM. The AI Assistant calls these same deterministic `compute_*` functions and feeds the pre-computed numbers to the LLM for interpretation only — the LLM never computes a statistic. This keeps every result reproducible and defensible under peer review.

### Export formats

Every analysis result (concordance, frequency, collocation, keyness) can be exported in **5 formats** via a unified `?fmt=` query parameter:

| Format | Use case | Extension |
| --- | --- | --- |
| **Excel** | Styled spreadsheet, opens in Excel/Google Sheets | `.xlsx` |
| **CSV** | Universal comma-separated, any tool | `.csv` |
| **TSV** | Tab-separated, paste into Excel/Sheets | `.tsv` |
| **Plain text** | Fixed-width table for emails / quick view | `.txt` |
| **JSON** | Structured, for programmatic use / re-import | `.json` |

Collocation results also export as **diagrams**:
- **SVG** (`.svg`) — vector, scales to any size, for papers/posters/slides
- **PNG** (`.png`) — raster 1600×1200, for Word docs / social media (requires `pip install -e ".[export]"` + libcairo)

Plus the **Methods PDF** — an auto-drafted methodology paragraph naming the exact tools, model versions, and formulas used, for pasting into a manuscript's Methods section.

---

## Licensing

CorpusMind is released under the **GNU Affero General Public License v3.0**
(`AGPL-3.0-only`). See [LICENSE](LICENSE).

The AGPL was chosen deliberately:

- It is a strong copyleft license: anyone who modifies CorpusMind and exposes
  it over a network (e.g., a hosted research service) must release their
  modifications under the same AGPL terms. This protects the research-software
  mission from silent proprietary forks.
- It is compatible with the permissive licenses of our core NLP dependencies
  (spaCy = MIT, Stanza = Apache-2.0, CAMeL Tools = MIT, SinaTools = Apache-2.0).
- It aligns with open-science norms: peer review of methodology requires that
  the exact code producing a result be inspectable — including by users of a
  hosted instance.

A permissive relicense (MIT / Apache-2.0) is available to the project owner on
request, but only after a review of the then-current dependency graph. See
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) for the full list of
bundled dependencies and their licenses.

---

## Documentation

- [docs/AI_AGENT_BUILD_PROMPT.md](docs/AI_AGENT_BUILD_PROMPT.md) — the full product specification (source of truth)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — living architecture diagram
- [docs/METHODOLOGY.md](docs/METHODOLOGY.md) — exact statistical formulas, for researcher-facing transparency
- [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) — licenses of bundled models, wordlists, and reference corpora
- [CONTRIBUTING.md](CONTRIBUTING.md) — how to contribute
- [CHANGELOG.md](CHANGELOG.md) — what changed, when

---

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) first, then
open an issue or pull request. Please be aware that all contributions will be
released under the AGPL-3.0-only license; contributors retain their copyright
but grant a license under the project's terms (see the
[Developer Certificate of Origin](https://developercertificate.org/) section in
CONTRIBUTING.md).

---

## Authors

- **Dr. Waleed Mandour** - Sultan Qaboos University, ORCID: [0000-0002-9262-5993](https://orcid.org/0000-0002-9262-5993) - Lead Architect and Assistant Lecturer of English Language
- **Prof. Wesam Ibrahim** - Princess Nourah Bint Abdulrahman University, ORCID: [0000-0003-0710-6038](https://orcid.org/0000-0003-0710-6038) - Co-author, corpus linguistics and discourse analysis methodology

## Citation

If you use CorpusMind in your research, please cite it as:

> Mandour, W., & Ibrahim, W. (2026). *CorpusMind: A local-first, AI-native
> research environment for corpus linguistics and multimodal discourse
> analysis* (Version 0.1.2) [Computer software]. Zenodo.
> https://doi.org/10.5281/zenodo.21226650
>
> Dr. Waleed Mandour, Sultan Qaboos University, ORCID: 0000-0002-9262-5993
> Prof. Wesam Ibrahim, Princess Nourah Bint Abdulrahman University, ORCID: 0000-0003-0710-6038

**BibTeX:**

```bibtex
@software{mandour_2026_corpusmind,
  author       = {Mandour, Waleed and Ibrahim, Wesam},
  title        = {{CorpusMind: Local-first, AI-native research environment
                   for corpus linguistics and multimodal discourse analysis}},
  month        = jul,
  year         = 2026,
  version      = {0.1.2},
  publisher    = {Zenodo},
  doi          = {10.5281/zenodo.21226650},
  url          = {https://doi.org/10.5281/zenodo.21226650}
}
```

## Acknowledgements

CorpusMind stands on the shoulders of a substantial open-source ecosystem,
including (but not limited to) spaCy, Stanza, Trankit, CAMeL Tools, SinaTools,
Farasa, Camelira, CamelParser2.0, FastAPI, Tauri, React, Ollama, and LM Studio.
The methodology draws on the corpus-linguistics and multimodal-discourse
literature cited inline throughout the spec — Kress & van Leeuwen, Halliday,
Fairclough, van Dijk, Wodak, Machin & Mayr, Barthes, Peirce, Lakoff & Johnson,
Martin & White, Toulmin, Aristotle, Hyland, Biber, Gabrielatos & Marchi, Hardie,
Kilgarriff, Church & Hanks, Dunning, Rychlý, Gries, and Juilland.

The development of CorpusMind was assisted by an AI agent (Super Z, built on
the GLM model by Z.ai) which served as a full-stack engineering collaborator
across all six phases of the build: scaffolding the monorepo, implementing the
FastAPI engine, the React PWA, the Tauri 2 desktop shell, the grounded-AI tool
surface, the Arabic NLP pipeline (CAMeL Tools integration), the vision suite
(image analysis, Visual Grammar, multimodal alignment), the multimodal discourse
analyses (CDA, persuasion, framing, narrative, metaphor, emotion, cultural),
and the collaboration/accessibility/encryption features. All AI-generated code
was reviewed, tested, and committed by the human authors.

## Funding Disclaimer

This project is **not funded by any institution, grant, or commercial entity**.
CorpusMind was developed independently by the authors out of a sense of
responsibility to the linguist community and to researchers in corpus
linguistics, discourse analysis, and multimodal studies who need an
open-access, local-first, AI-native research environment but cannot afford
commercial subscriptions or cannot send unpublished data to third-party
cloud services. The software is released free of charge under the GNU
Affero General Public License v3.0 (AGPL-3.0-only), and will remain free
and open-source in perpetuity. The authors bear all development and
maintenance costs personally. If you find CorpusMind useful in your
research, please cite it using the DOI above (10.5281/zenodo.21226650)
and consider contributing bug reports, feature requests, or pull requests
on GitHub.

---

*Built with ❤ to the Academic Community.*

---

## v1.0.0 Release Notes

### First stable release — CorpusMind + CorpusMind Lens

This is the first stable (1.0) release. It includes all features from the v0.1.x development cycle plus the completed CorpusMind Lens vision-LM subsystem.

**CorpusMind Lens** is a separate installable desktop app that connects to the same engine and focuses on vision-LM-powered multimodal discourse analysis. It opens directly to the Vision Suite and shows only vision-relevant navigation. Lens has its own Zenodo DOI: [10.5281/zenodo.21673083](https://doi.org/10.5281/zenodo.21673083).

**What's new in v1.0.0 (on top of v0.1.27):**

- **Removed "Coming Soon" label** from the Vision Suite nav item — the Vision Suite is fully functional.
- **Added vision models to the download catalogue**: `moondream` (1.7 GB, 1.8B), `llama3.2-vision:11b` (7.9 GB, 11B), and `gemma3:4b` (3.3 GB, 4B, multilingual) are now listed in Settings → Model Providers with a "vision" tag. Users can download them directly from within the app.
- **Updated About view** — shows "CorpusMind Lens" branding when running inside the Lens shell. Updated test count to 202, added "Discourse Lenses (LLM)" stat.
- **Updated User Guide** — the Vision Suite section now documents all Lens features: image-set management, vision-LM description, discourse LLM modes, alignment inspector, batch view, consent gate, and how to download vision models. A comprehensive 15-page PDF user guide is available on the [release page](https://github.com/waleedmandour/CorpusMind/releases/tag/v1.0.0).
- **Lens UI is distinct** — Lens shows only vision-relevant sidebar items (Overview, Corpora, Vision, AI, System), defaults to the Vision view, and the sidebar logo says "CorpusMind Lens."
- **Consent-gate gaps fixed** — the consent gate now also filters ethnicity/race descriptors (Asian, Black, Caucasian, etc.), religious/cultural attire (hijab, turban, kippah, etc.), and socioeconomic speculation (wealthy, poor, working-class, etc.). Previously only age, gender, expression, and appearance were filtered.
- **Port conflict fixed** — both desktop shells now check if an engine is already running on port 8765 before spawning a new one. If CorpusMind and Lens are both installed and running, the second app connects to the existing engine instead of crashing with "address already in use."

**Full feature set (cumulative from v0.1.0):**

- Corpus management: upload, clean, tokenize (spaCy + CAMeL Tools for Arabic)
- Analysis: concordance, frequency, collocation, keyness (with case-insensitive grouping), dispersion, n-grams, POS, grammar, dependency, discourse, vocabulary, sentiment, metaphor
- Reference corpora: BE06, Leipzig, BNC Baby, BAWE (with magic-byte archive detection + TEI-XML extraction fix)
- Arabic NLP: full CAMeL Tools integration (morphology, dialect ID, register detection, bilingual alignment)
- Vision Suite: image-set management, cached analysis (OCR/colour/composition), Visual Grammar (Kress & van Leeuwen)
- Vision-LM: image description, 8 discourse frameworks with `?mode=llm`, alignment inspector, batch view, consent gate
- AI Assistant: 25 grounded-AI tools, tool-calling agent with citation-enforced output
- Desktop: Tauri 2 shells for both CorpusMind and CorpusMind Lens, cross-platform (Windows, Linux, macOS)
- Privacy: local-first by default, cloud opt-in, no telemetry

### Tests
- **Engine: 205 passed, 9 skipped** (camel_tools data not installed in some envs), 0 failed.
- **Ruff**: All checks passed.
- **Web typecheck + build**: passed.
- **Cargo check**: passes for both `desktop` and `desktop-lens` Tauri shells in CI.

**Download:** https://github.com/waleedmandour/CorpusMind/releases/tag/v1.0.0

---

## v0.1.27 Release Notes

### CorpusMind Lens — Vision-LM-Powered Multimodal Discourse Analysis

This release ships **CorpusMind Lens**, a separate installable desktop app that connects to the same CorpusMind engine and focuses on vision-LM-powered image understanding. Lens runs fully against a local Ollama or LM Studio instance with zero cloud calls.

**Lens build steps (all 8 complete):**

1. **Vision-message provider support** — Extended `Message` dataclass with `images: tuple[bytes, ...]` field, threaded through both wire formats (Ollama native sibling `images` field + OpenAI-compatible multipart content array). 20 HTTP-mocked tests.
2. **Image-set manager + analysis viewer** — Replaced the 39-line VisionView placeholder with a real frontend: image-set picker, drag-drop upload, thumbnail grid, cached analysis drawer (OCR/colours/composition), lazy-loaded Visual Grammar panel. 373 lines of CSS with RTL support.
3. **`POST /images/{img_id}/describe` route** — The first route that sends real image bytes to a vision-LM. Provenance metadata, OCR disagreement detection, caching with full-reassignment pattern (JSON-column mutation safety), 500-on-empty-content with actionable hint. 13 tests + real E2E test against moondream.
4. **Vision-LM sibling paths for 8 discourse routes** — All 8 discourse-framework routes (`social-semiotic`, `cda`, `persuasion`, `framing`, `narrative`, `visual-metaphor`, `emotion`, `cultural`) now accept `?mode=llm`. Hedging contract baked into system prompt (§4 Principle 5). Defensive JSON parser. Full-reassignment caching. Falls back to heuristic — never an error state. 14 tests + real E2E against moondream.
5. **Consent-gate filter for all vision-LM output** — Post-processing filter that redacts person-descriptive content (age, gender, expression, appearance) from vision-LM output when the consent gate is closed. Applied to `/describe` + all 8 discourse LLM routes + alignment route, even on cache hits. 18 tests.
6. **Alignment inspector UI + LLM alignment mode** — `?mode=llm` on `/align` route. Frontend with heuristic/llm/both modes (side-by-side comparison). 10 tests.
7. **Batch view** — `GET /image-sets/{iset_id}/batch-analysis` aggregates cached vision-LM analysis across all images in a set: recurring framework themes, OCR-derived frequency list, VLM description summary. Frontend panel with three-column layout. 8 tests.
8. **New Tauri shell** — `desktop-lens/` directory templated from `desktop/`. Same engine sidecar, same supervisor logic, different branding. New `desktop-lens` CI job (cargo check passes).

### Bug Fixes (from earlier in this release cycle)

- **BNC/TEI-XML word triplication + reordering** — Fixed extraction loop that duplicated every word 3–4×. Now uses BeautifulSoup's `get_text(separator=" ")`.
- **BNC Baby multi-file extraction crash** — Fixed `root` variable shadowing that crashed on the 2nd `.xml` file in any directory (`TypeError: expected str, bytes or os.PathLike object, not Tag`).
- **Keyness case-sensitivity** — Fixed `compute_keyness()` grouping by raw `Token.text` instead of `LOWER(text)`, making it inconsistent with `compute_keyness_with_reference_list()`.
- **`min_corpus_tokens` UI warning** — Added non-blocking warning in Keyness panel when target corpus is below the reference's threshold.
- **Arabic CI hardening** — Replaced file-level `--ignore` with per-test `skipif` markers. Added camel_tools + cached morphology DB to CI. All 17 Arabic tests now run in CI.
- **`list_backends` exception-swallowing** — Fixed bare `except Exception: pass` that hid broken camel_tools installs.

### Tests
- **Engine: 205 passed, 9 skipped** (camel_tools data not installed in some envs — cleanly skipped with reason), 0 failed.
- **Ruff**: All checks passed.
- **Web typecheck + build**: passed.
- **Cargo check**: passes for both `desktop` and `desktop-lens` Tauri shells in CI.

**Download:** https://github.com/waleedmandour/CorpusMind/releases/tag/v0.1.27

---

## v0.1.26 Release Notes

### Bug Fixes

#### BNC/TEI-XML text extraction — word triplication + reordering
- **Fixed: BNC Baby and BAWE documents were ingested with every word duplicated 3–4× and scrambled ordering, silently corrupting every frequency count and keyness comparison run against them.**

#### Keyness case-sensitivity — inconsistent rankings for the same corpus
- **Fixed: The same target corpus could produce different keyword rankings depending on which reference type the user picked.**

### UI Improvements

#### `min_corpus_tokens` advisory warning
- **Added: Non-blocking warning in the Keyness panel when the target corpus's token count is below the selected reference's `min_corpus_tokens`.**

### Tests
- **Engine: 110 passed, 0 failed** (test_phase3_arabic.py legitimately skipped).
- **Ruff**: All checks passed.
- **Web typecheck + build**: passed.

**Download:** https://github.com/waleedmandour/CorpusMind/releases/tag/v0.1.26

---

## v0.1.25 Release Notes

### Bug Fixes

#### Reference Corpora — Full-corpus archive extraction
- **Fixed: BNC Baby and BAWE downloads silently failed with "No text files found in archive."**
  - **Root cause:** The extraction code branched on `spec.source_url.endswith(".zip")`, but the Oxford Text Archive hosts both corpora at URLs ending with a query string (`...2553.zip?sequence=3&isAllowed=y` and `...2539.zip?sequence=3&isAllowed=y`). The suffix check never matched, so the code downloaded the archive successfully and then silently skipped extraction entirely.
  - **Fix:** Detect archive type by **magic bytes** (`b"PK"` for ZIP, `b"\x1f\x8b"` for gzip), which works regardless of URL shape.
  - Added a clearer error for genuinely-unrecognized formats (names expected magic bytes) instead of the misleading "No text files found" message.
  - Refined the "no text files found" message to mention which format was detected, so the user knows extraction did succeed.

#### Reference Corpora — Background-task GC hazard
- **Fixed: Background download task could be garbage-collected mid-download.**
  - `asyncio.create_task(...)` was called without storing the returned `Task` anywhere. Python's own `asyncio` docs warn that the event loop may GC such tasks mid-flight.
  - Now held in a module-level `set` with a `done_callback` that discards the task on completion — no leak, no GC risk.

### Tests
- **6 new regression tests** in `engine/tests/test_reference_corpus_archive.py`:
  1. Unit test proving the old URL-suffix check fails on the real OTA URL pattern.
  2. End-to-end: ZIP at a query-string URL (BNC Baby case) is detected via magic bytes, extracted, and ingested.
  3. End-to-end: BAWE (same OTA URL shape, distinct registry entry with `2539.zip`, genre="academic") — belts-and-braces coverage.
  4. Regression guard: tar.gz (Leipzig 10K) path still works after the magic-byte refactor.
  5. Unrecognized format produces the new clearer error, NOT the misleading old one.
  6. Surface check that the `_full_corpus_tasks` strong-reference set exists.

### Build
- All 4 CI jobs pass on `v0.1.25` (Engine Python 3.12, Web Node 20, Desktop Rust, License gate).
- Engine: 110/110 tests pass; ruff clean.

**Download:** https://github.com/waleedmandour/CorpusMind/releases/tag/v0.1.25

---

## v0.1.24 Release Notes

### New Features

#### Reference Corpora
- **3 new downloadable reference corpora** with SHA-256 verification:
  - **Leipzig English News** (CC BY 4.0) — top-100 word frequency list for general English keyness
  - **Quranic Arabic** (GPL-3.0) — word frequency from the Quranic Arabic Corpus for Classical Arabic
  - **CAMeL Arabic** (CC BY-SA 4.0) — top-1000 MSA Arabic frequency list from CAMeL Lab
- **Select downloaded reference for analysis** — installed reference frequency lists can be selected directly from the Keyness panel, no need to upload a full reference corpus
- arTenTen and enTenTen listed as "requires Sketch Engine" (proprietary, not redistributable)

#### Document Management
- **Delete individual files** from a corpus (`DELETE /corpora/{cid}/documents/{did}`)
- **Recompile corpus** button — re-runs the full NLP pipeline (clean → tokenize → tag → parse) on all documents
- **Professional document table** — shows filename, format, language, size, and delete button per document
- Auto-recomputes corpus stats after document deletion

#### UX Improvements
- **Auto-load last corpus on startup** — validates the persisted corpus ID and loads it automatically
- **Dark mode button contrast fix** — `--brand-500` overridden to `#2a9070` in dark mode (6.2:1 contrast, WCAG AA pass)
- Removed hardcoded `color: white` inline styles in SettingsView

### Bug Fixes
- AI Assistant Ollama communication: `_chat_openai_compat` now passes `json_mode`, strips Qwen3 thinking, handles empty content (tool-only responses), includes `name` field for tool messages
- AI Assistant tool-call parsing: handles both OpenAI-compat and native `/api/chat` response formats
- AI Assistant tool heuristic: improved — defaults to tools=True for questions with `?` or >30 chars
- PyInstaller hidden imports: added `langdetect`, `charset_normalizer`, `PIL`, `tenacity`, `anyio`, `structlog`, `websockets`, `pydantic_settings`, `httpx`, `multipart`
- CI now installs `[dev,vision]` deps + `cairosvg` (was only `[dev]`)
- Removed `cairosvg` from PyInstaller excludes (PNG export now works)
- macOS universal DMG (arm64 + x86_64)
- AppImage added to tauri.conf.json targets
- Deleted dead view files (`CorpusManagerView.tsx`, `CorpusHubView.tsx`)
- Fixed circular import in `reference_corpus/manager.py`

### Build
- All 4 CI jobs pass (Linux deb+AppImage, macOS universal DMG, Windows NSIS+MSI, Web PWA)
- Engine: 24/24 tests pass
- Web: typecheck clean, build clean
- Desktop: cargo check clean

**Download:** https://github.com/waleedmandour/CorpusMind/releases/tag/v0.1.24
