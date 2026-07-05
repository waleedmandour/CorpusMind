# CorpusMind — AI Agent Build Prompt

> The canonical specification for CorpusMind. This document is the source of
> truth for the product; every section number referenced from the rest of the
> documentation points back here. Keep this file in sync with the codebase as
> the project evolves — when a decision is made or a feature is shipped, the
> corresponding section here should be updated to reflect the new state.
>
> The original prompt is preserved verbatim below. Section numbering is
> preserved across all other docs (README, ARCHITECTURE, METHODOLOGY, etc.)
> so cross-references like "§11.1" or "§12" are unambiguous.

---

You are acting as the lead architect and full-stack engineer for a new research-software product in corpus linguistics and multimodal discourse analysis. You have the combined skill set of: a corpus linguist familiar with quantitative and qualitative methods, an Arabic computational linguist, a computer-vision engineer, an LLM application engineer, and a desktop/web product engineer who knows Tauri 2, PWA architecture, and local-model runtimes (Ollama OR LM Studio).
Your client is a corpus-linguistics/discourse-analysis researcher building a tool for other researchers, most of whom have zero programming ability and expect a point-and-click, Microsoft-Office-like experience, while still getting research-grade statistical rigor underneath.
Your job in this document is to understand the product, the reasons behind every major decision below, and then build it in the phased order specified in §16 — asking before, not after, you make a choice that would be expensive to reverse.

2. Product Vision
Working title: "CorpusMind" (placeholder — see §19, first open decision).
One sentence: CorpusMind is a local-first, AI-native research environment that lets a linguist go from raw texts and images to publication-ready quantitative and qualitative analysis without writing a line of code, without sending unpublished data to a third-party server unless they explicitly choose to, and without losing the methodological transparency that peer review demands.
CorpusMind ships as two integrated suites sharing one project system, one AI layer, and one design language:
Suite A — "CorpusMind Text": a next-generation corpus-analysis workbench (concordancing, frequency, collocation, keyness, n-grams, dispersion, vocabulary/POS/grammar/dependency/semantic/discourse/pragmatic/metaphor/sentiment analysis, with first-class Arabic support).
Suite B — "CorpusMind Vision": an AI research assistant for multimodal discourse analysis, grounded in Visual Grammar (Kress & van Leeuwen), Systemic Functional Linguistics, Critical Discourse Analysis, Multimodal CDA, Social Semiotics, and Cognitive Linguistics — analyzing images, text, and the meaning made between them.
Both suites are reachable from:
A Progressive Web App (PWA) — installable, offline-capable, for seamless cross-device access.
Native desktop apps for Windows, Linux, and macOS, built with Tauri 2.
Local LLM inference via Ollama and/or LM Studio, so the AI Assistant can run entirely on the researcher's own machine.

3. Research Basis: Why This Product, and What It Must Do Differently
You are not building "AntConc with a chatbot bolted on." Before writing code, internalize the gap analysis below — it drives nearly every design principle in §4.
3.1 The existing landscape, and its limits.
AntConc, WordSmith Tools, LancsBox are mature, free, single-user desktop concordancers. They are the reference point most linguists already know, but they are not built for AI-era workflows: no built-in generative assistant, limited collaboration, and (for AntConc/WordSmith especially) thinner statistical option sets than modern keyness research recommends.
Sketch Engine / CQPweb are the power tools of the field (word sketches, CQL, huge corpora), but are server-side and largely subscription- or institution-hosted — meaning unpublished or sensitive corpora leave the researcher's machine, and dialect/Arabic support is not their focus.
Wordless is the closest existing open-source comparator: a free, cross-platform, multilingual desktop tool explicitly aimed at removing technical barriers for non-programmer researchers, built on spaCy/Stanza. It has no native LLM/agent layer and no multimodal (image+text) analysis — CorpusMind's job is to be "Wordless plus a grounded AI layer plus multimodal discourse analysis," not to duplicate it.
Qualitative tools (NVivo, ATLAS.ti, MAXQDA) are adding AI coding assistants, but they are qualitative-coding tools first; they do not natively compute logDice, log-likelihood, dispersion indices, or Arabic morphology, and they do not implement Visual Grammar as a structured, scored analysis.
Multimodal Critical Discourse Analysis is, today, an almost entirely manual, qualitative practice. There is no widely used software that automatically scores an image against Kress & van Leeuwen's representational/interactional/compositional meaning, or automatically links an image region to a co-occurring text span. This is a genuine, large research gap — and the hardest, most novel part of this build (see §16's phasing: ship it after Suite A is solid).
3.2 What the corpus-linguistics + LLM literature actually shows (as of early 2026).
There is active, serious research on using LLMs for corpus-based discourse analysis (e.g., prompt-engineering pipelines for corpus-assisted discourse studies), but findings are mixed: LLMs are useful for assisting quantitative and qualitative analysis, but are not a reliable drop-in replacement for validated statistical measures or fine-tuned detectors. For example, LLM-only metaphor detection following the MIPVU procedure still under-performs supervised, rule-grounded methods and struggles to filter false positives.
The broad RAG literature is consistent on one point that must shape this whole product: grounding an LLM's output in retrieved, citable evidence measurably reduces hallucination and is the standard way to make an AI assistant trustworthy for research use — but retrieval alone does not guarantee correctness, so citation-enforcement and human verification loops still matter.
Conclusion for this build: the LLM is a co-pilot that talks to and about a deterministic, auditable statistics/NLP engine — it never replaces that engine, and every one of its interpretive claims must be traceable back to a real concordance line, a real image region, or a real number the engine computed.
3.3 Arabic NLP tooling that already exists — do not reinvent it. For Arabic, mature open building blocks already exist and should be the backbone of the Arabic-specific module (§8.21): CAMeL Tools (open-source Python toolkit — morphology, disambiguation, dialect ID, NER, sentiment; MSA + dialectal via CAMeLBERT models), Farasa (fast segmentation/POS/lemmatization, but a smaller tagset and ambiguous undiacritized lemmas), MADAMIRA (high accuracy, 40-tag POS set, but not open-source and slower), Camelira (multi-dialect morphological disambiguator), CamelParser2.0 (Arabic dependency parsing), and SinaTools (a newer open-source toolkit that in independent benchmarking led on both speed and accuracy across two tasks). Build an abstraction layer so the engine can call whichever backend is best per task/dialect, rather than committing to one.
3.4 Tauri 2 + local LLMs is a proven, documented pattern. The standard architecture bundles the inference runtime (Ollama binary, or a llama.cpp/candle-based server) as a Tauri "sidecar" process, spawned and supervised by the Rust core, communicating with the webview over local HTTP (Ollama's REST API on localhost:11434; LM Studio's OpenAI-compatible server on localhost:1234/v1). Known pitfalls to design around from the start: sidecar binaries must be named with the target-triple suffix; macOS quarantines unsigned bundled binaries (must be stripped at build time); logs must be redirected to files, not piped, to avoid buffer-size hangs; child processes must be fully detached/cleaned up on app exit to avoid orphaned "zombie" Ollama processes; and consumer hardware realistically ceilings out around 2–3B parameters without a discrete GPU, or 7–14B with one — so the UI must show a hardware-appropriate model picker, not assume large-model performance.

4. Non-Negotiable Design Principles
These translate §3 into concrete engineering mandates. Do not trade these away for convenience.
Local-first, cloud-optional. By default, corpus text, images, and AI queries never leave the user's machine. Cloud LLM providers (Anthropic/OpenAI/etc.) are available only as an explicit, per-project, opt-in fallback with a visible indicator whenever active.
Grounded AI, never a bare chatbot. Every AI Assistant answer that makes an empirical claim ("X collocates with Y", "this image is left-heavy in information value") must carry a citation back to a concordance line ID, an image region, or a computed statistic the engine can reproduce on demand. See §11.
Effect size and significance, always together. The original feature list asks for significance tests (MI, log-likelihood, chi-square, T-score, Dice, Delta P) for collocation/keyness. Add the effect-size measures the keyness literature says significance tests alone cannot give you (Log Ratio, %DIFF, Simple Maths, Odds Ratio) so a "key" word is never reported as important on frequency-of-occurrence-in-a-huge-corpus grounds alone. See §12.
Zero-code, not zero-transparency. Every one-click automatic output (a POS tag, a keyness list, a "power relation" score) must be inspectable: the user can always see which model/formula/version produced it, and can export that as citeable methodology text for a paper.
Interpretive claims are hypotheses, framework-lensed, not facts. Anything in the CDA/MCDA/ideology/power/persuasion family must be labeled with the theoretical framework that produced it (Fairclough vs. van Dijk vs. Machin & Mayr, etc.) and phrased as "under a [Framework] reading, X may indicate Y" — never as a bare assertion. A human-verification step is required before such a claim is marked "confirmed" in a project's findings.
Arabic is a first-class citizen, not a bolt-on. RTL layout, dialect-aware tooling, and the CAMeL Tools/SinaTools/Farasa ecosystem are part of the core architecture from day one, not a later localization pass.
Practical scale, honestly stated. Do not promise literally unlimited corpus size. Design for disk-backed, incrementally-indexed corpora in the hundreds-of-millions-of-tokens range on consumer hardware, with graceful degradation and clear in-UI feedback as size grows, rather than an unqualified "no limit" claim.
Reproducibility is a feature. Every project pins the exact tokenizer, tagger, model, and formula versions used, and can emit a "Methods" paragraph with correct citations for a paper's methodology section.
Consent and restraint around biometric-adjacent features. Facial/body "age group," "gender presentation," "emotion," "gaze," and dominance/submission inference (§9.4) are powerful for media/propaganda studies but legally and ethically sensitive. They ship as an opt-in module, disabled by default, with an in-app notice, and must never perform identity recognition or re-identification of real individuals. See §18.

5. Product Structure: Two Suites, One Platform
Both suites share:
One project/workspace system (a "project" can contain text corpora, image sets, or both).
One AI Assistant layer (§11), with suite-specific tools and prompt templates.
One design system (ribbon-style UI, dark/light themes — see §10).
One storage, sync, and collaboration layer (§7.4).
They are built and can be shipped separately (see the phased roadmap, §16), but must never diverge into two different data models or two different AI layers.

6. Critical Architecture Decision: Reconciling PWA + Tauri 2 + Local LLMs + Heavy NLP
This is the single most important architectural call in the whole project, and it is not obvious from the feature list alone, so read carefully.
The tension: A PWA is, by definition, sandboxed browser code. It cannot itself run spaCy/Stanza/CAMeL Tools pipelines, dependency parsers, or a local LLM — those need a real OS process. A Tauri desktop app can run all of that, via sidecars. So "PWA for seamless access" and "Ollama/LM Studio for local LLMs" pull in different directions unless you design for it explicitly.
The resolution — a headless engine, multiple shells:
Build one backend service, corpusmind-engine, that does all heavy lifting: corpus ingestion/cleaning, tokenization/tagging/parsing (via spaCy/Stanza/Trankit and the Arabic stack from §3.3), the statistics engine (§12), the vision pipeline (§9), and the Model Provider abstraction that talks to Ollama/LM Studio/cloud APIs. It exposes everything over a local HTTP + WebSocket API (OpenAPI-documented) on localhost.
Build one frontend, corpusmind-web (a single codebase — see §14), that talks only to that HTTP/WebSocket API. It never contains NLP logic itself.
Ship corpusmind-web three ways:
As an installable PWA (service worker + manifest + IndexedDB for local caching/offline queueing of UI state), which the user points at a corpusmind-engine instance — either one running on localhost (installed as a lightweight background service/Docker container) or one they run on a machine on their own LAN/server (for a lab that wants one shared engine).
Inside a Tauri 2 desktop shell (corpusmind-desktop) for Windows/Linux/macOS, where Tauri manages corpusmind-engine (and, optionally, the Ollama binary) as sidecar processes, so the desktop build is genuinely double-click-and-run with nothing else to install. This is the "batteries included" distribution.
The same web build can be self-hosted by an institution as a always-on multi-user engine, for labs that want shared/collaborative corpora (§10.2) without every member running a local copy.
The AI Assistant never assumes where the model lives. It calls a ModelProvider interface with three concrete implementations from day one: OllamaProvider (native API + OpenAI-compatible /v1 endpoint), LMStudioProvider (OpenAI-compatible /v1 endpoint on port 1234), and CloudProvider (opt-in, e.g., Anthropic/OpenAI, disabled by default). Because both Ollama and LM Studio speak the OpenAI chat-completions schema, one thin client can drive both with only base URL and model name differing — implement it once.
Vision-language tasks (image captioning, framework-lensed multimodal analysis) use local vision-capable models served the same way (e.g., a vision-capable Ollama model) through the same ModelProvider, so Suite B has no separate integration story.
Consequence for the desktop app specifically: on first launch, corpusmind-desktop should detect whether Ollama/LM Studio is already installed and running; if not, offer to launch the bundled sidecar Ollama, and let the user pick/pull a model sized to their detected hardware (RAM/VRAM), rather than silently trying to load something too large.

7. System Architecture
7.1 Monorepo layout
corpusmind/
├── engine/                  # corpusmind-engine — Python (FastAPI) service
│   ├── ingestion/           # upload, cleaning, encoding/language detection
│   ├── nlp/                 # tokenization, POS, lemmatization, dependency parsing
│   │   ├── general/         # spaCy / Stanza / Trankit pipelines
│   │   └── arabic/          # CAMeL Tools, Farasa, SinaTools, CamelParser2.0 wrapper
│   ├── stats/                # frequency, collocation, keyness, dispersion, n-grams
│   ├── discourse/            # metadiscourse, stance/appraisal, metaphor (MIP/MIPVU), sentiment
│   ├── vision/                # OCR, object/scene detection, composition/color analysis
│   ├── multimodal/            # image-text alignment, cross-modal meaning, visual grammar scoring
│   ├── ai/                    # ModelProvider abstraction, RAG index, tool-calling layer, prompt templates
│   ├── storage/                # corpus index, project DB, annotation store, versioning
│   └── api/                    # REST + WebSocket routes, OpenAPI schema
├── web/                        # corpusmind-web — single frontend (PWA + embedded in Tauri)
│   ├── src/
│   ├── public/manifest.webmanifest
│   └── service-worker.ts
├── desktop/                     # corpusmind-desktop — Tauri 2 project
│   ├── src-tauri/
│   │   ├── tauri.conf.json      # sidecar + capability config
│   │   └── src/                 # Rust: sidecar lifecycle, OS integration
│   └── binaries/                 # platform-tagged sidecar executables
├── shared/                        # shared TS types / OpenAPI-generated client
├── reference-data/                 # bundled reference corpora, wordlists, framework prompt templates
├── docs/                             # this file, architecture decisions, methodology docs
└── infra/                             # Docker Compose for self-hosted engine, CI
7.2 Engine language and NLP stack [recommendation — confirm in §19]
Python (FastAPI + asyncio), because the mature NLP/CV ecosystem (spaCy, Stanza, Trankit, CAMeL Tools, transformers, OpenCV) is overwhelmingly Python-first, and because PyInstaller-style packaging into a single sidecar binary is a proven pattern for Tauri. Wrap performance-critical hot paths (corpus indexing, concordance search over very large corpora) in a proper search index rather than naive in-memory scans — see §7.3.
7.3 Corpus storage & search
Store raw + cleaned text, per-token annotations (CoNLL-U-compatible: token, lemma, POS, morph features, dependency head/relation), and metadata (project/language/genre/year/author/register/discipline) in a local embedded database (e.g., SQLite for metadata/relations) plus a dedicated full-text/positional index (e.g., an inverted index library capable of phrase/proximity/CQL-like queries) so KWIC concordancing and n-gram/collocation queries stay fast as corpora grow into the hundreds of millions of tokens, instead of re-scanning text on every query.
Support incremental re-indexing (so adding one file to a 50M-token corpus doesn't require reprocessing everything).
Every corpus is versioned: re-running the pipeline with an upgraded tagger creates a new annotation version rather than silently overwriting the old one (reproducibility, §4.8).
7.4 Collaboration & sync
Local-first by default (SQLite/files on disk). For shared projects, support an opt-in sync layer against the self-hosted engine mode (§6.3) with per-project public/private visibility, matching the original requirement in §10's "Collaboration" features.
[DECISION NEEDED]: real-time multi-user co-editing (CRDT-based) vs. simpler "share a project, everyone syncs on save" — confirm required collaboration intensity with the project owner before building CRDT infrastructure, which is a significant scope increase.

8. Suite A — "CorpusMind Text": Full Feature Specification
Build in the order these are numbered; later phases (§16) group them into milestones. Items marked (+ADD) are additions beyond the original feature request, justified by §3.
8.1 Zero-Programming Ingestion & Preprocessing
Drag-and-drop upload; formats: TXT, DOCX, PDF, HTML, XML, CSV, EPUB.
No hard-coded word-count limit in the product logic, but see Principle 7 (§4): design and message around a realistic, disk-backed scaling target rather than an absolute "unlimited" claim.
Automatic: encoding detection, language detection, corpus cleaning (boilerplate/markup stripping), sentence segmentation, tokenization, lemmatization, POS tagging, dependency parsing.
(+ADD) A visible "pipeline recipe" per corpus (which tokenizer/tagger/parser + version ran) — feeds reproducibility (§4.8).
(+ADD) Emoji/homoglyph/Unicode-normalization handling as an explicit, inspectable preprocessing step — different corpus tools are known to silently disagree here, so make the behavior visible and configurable rather than a hidden default.
8.2 Corpus Management
Unlimited number of corpora and projects (bounded only by disk, per Principle 7).
Organize by project, language, genre, year, author, register, discipline (user-definable metadata schema, not a fixed list).
Merge, split, and filter corpora (filter by any metadata field or by a saved query).
8.3 Advanced Search
Simple, advanced (boolean/proximity), POS, lemma, and multi-word-expression search.
(+ADD) A CQL-like structured query mode for power users, alongside the point-and-click query builder for everyone else — the query builder should generate and show the equivalent structured query, so non-programmers can learn it incidentally.
8.4 Concordancer
KWIC view, expandable context, color coding, sorting, filtering, grouping.
Save and annotate concordances; export to Excel and PDF.
(+ADD) Every concordance line gets a stable line ID, used by the AI Assistant (§11) to cite evidence.
8.5 Frequency Analysis
Word, lemma, POS, n-gram, and character frequency; sentence length; lexical density; type-token ratio.
(+ADD) Standardized type-token ratio (STTR) alongside raw TTR — raw TTR is highly sensitive to corpus/sample size and its uncritical use is a known pitfall; offer STTR (computed over fixed-size chunks) as the comparably valid default, with raw TTR available but labeled.
8.6 Collocation Analysis
User-selectable statistical tests, any subset or all at once: MI, LogDice, T-score, Log-likelihood, Dice, Chi-square, Delta P (exact formulas in §12).
(+ADD) Configurable span/window size and minimum frequency threshold, shown next to every result (a collocation measure without a stated window size is not reproducible).
8.7 Keyword (Keyness) Analysis
Built-in reference corpora per supported language (with license terms tracked — see §13.5) and support for user-supplied reference corpora.
Automatic keyness statistics; positive vs. negative keywords; downloadable (Excel/PDF) key semantic domains (as list and as bubble/word-cloud diagrams); keyword clusters.
(+ADD, load-bearing) Effect-size measures alongside significance tests: Log Ratio, %DIFF, Simple Maths, Odds Ratio (§12). Default sort should combine a significance filter with an effect-size ranking, per the standard "significance ≠ effect size" caution in the keyness literature (Gabrielatos & Marchi 2012; Hardie 2014) — never present a bare log-likelihood ranking as "the" keyword list without surfacing effect size.
8.8 N-grams
2–10 grams, skip-grams, cluster extraction, formulaic language.
Lexical bundles: implement with the standard frequency-and-range criterion (a minimum frequency per million words and a minimum number of distinct texts/speakers it must occur in), not raw frequency alone — this is the established method (Biber et al.) for distinguishing genuine bundles from single-text artifacts.
8.9 Dispersion
Dispersion plots, heat maps, chronological/genre/speaker distribution.
(+ADD, load-bearing) Actual dispersion statistics, not only visualizations: Juilland's D and Gries' DP (deviation of proportions), computed across user-defined corpus parts. A plot shows unevenness; a dispersion index quantifies it and is what gets reported in a paper.
8.10 Vocabulary Analysis
Academic/technical vocabulary, vocabulary profiling, frequency bands, rare words, neologisms.
CEFR levels: implement via configurable wordlist providers (e.g., a project's own frequency-band lists, or, where licensing permits, the English Vocabulary Profile / CEFR-J style resources). (+ADD, important): EVP-style CEFR wordlists carry redistribution licensing restrictions — do not bundle third-party CEFR data without confirming license terms (§13.5); ship with an open frequency-band-based approximation (e.g., derived from open frequency corpora) by default, and let advanced users plug in a licensed CEFR list if they have rights to one.
8.11 POS Analysis
POS distribution, POS sequences, POS n-grams, cross-corpus POS comparison.
8.12 Grammar Analysis
Passive voice, tense, aspect, modality, negation, relative/conditional clauses, complex noun phrases — implemented as dependency-parse-driven pattern detectors (not regex over surface text), so they generalize across genres.
8.13 Dependency Analysis
Subject-object relations, verb patterns — surfaced as filterable, exportable query results over the parsed corpus (build this as thin queries over the same dependency parses already produced in §8.1, not a separate pipeline).
8.14 Semantic Analysis
Semantic domains, semantic similarity (embedding-based), semantic change (diachronic corpora), frame semantics.
(+ADD) Ship semantic-similarity/embedding features with a stated model + version, since results are only reproducible if the embedding model is pinned (Principle 8).
8.15 Discourse Analysis
Discourse markers, hedges, boosters, metadiscourse, evaluation, stance, engagement markers.
(+ADD, grounding) Implement metadiscourse categories against an established taxonomy (Hyland's interactive/interactional metadiscourse model: hedges, boosters, attitude markers, engagement markers, self-mentions, transitions, frame markers, evidentials, code glosses) rather than an ad hoc term list — this makes results citable and comparable across studies.
8.16 Pragmatics
Speech acts, implicature indicators, hedging, intensifiers, mitigation — flag these to the user as AI-assisted, not fully automatic, in line with §4 Principle 5: pragmatic categories are interpretive and should be presented as flagged candidates for the researcher to confirm, with the underlying LLM reasoning and cited spans shown.
8.17 Metaphor Detection
Automatic metaphor candidates, conceptual metaphors, metaphor frequency/comparison, manual verification.
(+ADD, load-bearing) Implement as an LLM-assisted, MIP/MIPVU-inspired pipeline: for each candidate lexical unit, the system runs a structured prompt that mirrors the MIPVU decision steps (contextual meaning vs. more basic/concrete meaning, contrast-but-comprehensible-via-comparison test) and requires the human-verification step before a candidate counts as a confirmed metaphor in any export or statistic. Current evidence shows LLMs alone under-perform supervised detectors and especially struggle to filter literal false positives — the verification step is not optional UI polish, it is load-bearing for validity.
8.18 Sentiment Analysis
Positive/negative/neutral, emotion categories, emotion timeline (for diachronic or narrative corpora).
8.19 AI Assistant (Suite A)
Natural-language Q&A over the loaded corpus: "compare male and female speech," "find persuasive strategies," "identify metaphor patterns," "summarize this corpus," "explain these collocations," "suggest research questions."
Must follow the grounded-AI architecture in §11 — every answer resolves to real tool calls against the stats/NLP engine, with cited evidence, not free generation from the model's parametric memory.
8.20 Visualization
Word clouds, network graphs, tree maps, timelines, heatmaps, bubble charts, bar/line charts, scatterplots, collocation networks — all exportable as static images (for papers) and as interactive views (for exploration).
8.21 Arabic-Specific Features
Root extraction, pattern (وزن) identification, lemma normalization, diacritics handling (removal or retention, user-controlled), Buckwalter transliteration, clitic segmentation, broken plurals, dual forms, gender detection, dialect identification (Gulf, Egyptian, Levantine, and others), and register handling across Quranic Arabic, Classical Arabic, and Modern Standard Arabic.
Implementation backbone: build this module as a thin, swappable-backend wrapper over CAMeL Tools (general MSA + dialectal morphology, dialect ID, NER, sentiment; MSA/dialectal via CAMeLBERT models), SinaTools (open-source, competitive speed/accuracy), Farasa (fast segmentation where speed matters more than tagset granularity), Camelira (multi-dialect disambiguation), and CamelParser2.0 (dependency parsing) — do not write a from-scratch Arabic morphological analyzer; integrate and benchmark against these.
8.22 Bilingual Corpus Tools
Arabic–English alignment, parallel corpus analysis, translation equivalents, translation shifts, alignment visualization, comparable corpora.
8.23 Research Workflow
Saved searches, bookmarks, favorites, automatic screenshots, automatic tables, automatic figure numbering, project management.
(+ADD) One-click "Export Methods Section": auto-drafts a methodology paragraph naming the exact tools/versions/formulas used for a given analysis, for the user to paste into a manuscript (ties directly to Principle 8, reproducibility).
8.24 Collaboration
Share projects; mark an uploaded corpus public (others can work on it) or private.
8.25 Ease of Use
Ribbon-style interface (Office-like), dark/light themes, search history, undo/redo, customizable workspace, keyboard shortcuts, interactive tutorials.

9. Suite B — "CorpusMind Vision": Full Feature Specification
This suite is the most novel and least precedented part of the build (§3.1) — phase it in after Suite A is solid (§16), and treat every "automatically identify ideology/power/bias" feature as producing a framework-lensed hypothesis with cited evidence, per Principle 5, not a ground-truth label.
9.1 Project Management
Unlimited projects; Arabic, English, and bilingual projects; full dataset import; version control; team collaboration (shared with Suite A's project system, §5).
9.2 Supported Input Formats
Images: JPG, PNG, TIFF, WebP, SVG. Text: TXT, DOCX, PDF, HTML, XML, CSV, JSON.
9.3 Automatic OCR
Arabic, English, mixed-language images, handwritten text, low-quality scans — via an OCR engine with strong Arabic support (e.g., a model pipeline covering both Arabic and Latin scripts), with per-image confidence scores surfaced to the user rather than silently trusted.
9.4 Image Analysis
9.4.1 Object detection: people, animals, objects, vehicles, buildings, food, products, logos, weapons, religious symbols, flags — via an open-vocabulary detector so new categories don't require retraining.
9.4.2 Scene recognition: office, home, street, classroom, hospital, battlefield, mosque, church, supermarket, airport, etc.
9.4.3 Facial analysis: estimated age group, gender presentation, facial expressions, emotions, eye gaze, head direction. Ships as an opt-in module, off by default (§4 Principle 9, §18) — no identity recognition or re-identification, ever.
9.4.4 Body language: posture, gestures, interaction, dominance/submission, power relations — always output as a described visual cue ("figure occupies more vertical frame space, direct frontal gaze") plus an optional, clearly-labeled interpretive gloss, not a bare "dominant" label.
9.4.5 Eye contact: direct/indirect gaze, gaze direction and intensity — core to Visual Grammar's interactive meaning.
9.4.6 Colour analysis: dominant colors, harmony, warm/cold balance, brightness, contrast, saturation, and colour symbolism (symbolism outputs must be framework/culture-relative and labeled as such — colour symbolism is not universal).
9.4.7 Composition analysis: information value (left/right, top/bottom, centre/margin), salience, framing, vectors, visual/reading paths, golden ratio, rule of thirds, visual balance — computed geometrically (saliency maps, object bounding-box centroids) wherever possible, so results are numeric and reproducible, not purely impressionistic.
9.4.8 Typography: font, size, capitalization, weight/style, spacing, alignment, hierarchy (for text embedded in images, e.g., posters/ads).
9.4.9 Logo analysis: brands, institutions, political parties, government logos, NGOs, universities.
9.4.10 Symbol detection: religious, national, cultural, political, corporate symbols.
9.5 Text Analysis
Full integration of Suite A's text engine: concordancing, frequency, collocation, keywords, discourse markers, stance, hedges, boosters, metaphor, evaluation, sentiment, framing, narrative structure, argumentation — reused, not reimplemented (§5).
9.6 Arabic Text Analysis
Root extraction, morphological analysis, dialect detection, Classical/MSA recognition, transliteration, clitic segmentation — same backbone as §8.21.
9.7 English Text Analysis
POS tagging, dependency parsing, constituency parsing, semantic role labeling, coreference resolution.
9.8 Multimodal Alignment
The flagship feature: automatically link image regions to co-occurring text spans (e.g., a caption's claim to the depicted subject). Build this as its own service (engine/multimodal/) combining region-level image embeddings with text-span embeddings, surfaced with a confidence score and the exact spans/regions linked — every alignment must be inspectable, not a black box.
9.9 Cross-modal Meaning
Detect reinforcement, complementarity, contradiction, irony, mismatch, amplification, silence, redundancy between image and text — each output labeled with which alignment (§9.8) it is based on.
9.10 Visual Grammar Module
Automatic analysis structured around Kress & van Leeuwen's three meaning-metafunctions — Representational, Interactional, Compositional — producing both a structured score/breakdown (from §9.4's numeric sub-analyses) and a natural-language explanation generated by the AI layer, explicitly citing which sub-analysis drove each claim.
9.11 Social Semiotic Analysis
Actors, processes, participants, attributes, symbolic/cultural meaning, power, ideology, identity — framework-lensed outputs per Principle 5.
9.12 Critical Discourse Analysis
Power, ideology, bias, representation, marginalization, us-vs-them framing, agency, nominalization, passivization, presupposition, evidentiality — grounded in the chosen framework (Fairclough / van Dijk / Wodak / Machin & Mayr, per §9.24), each claim tied to the specific linguistic or visual feature that triggered it.
9.13 Persuasion Analysis
Ethos, pathos, logos, fear/hope appeals, emotional triggers, scarcity, authority, urgency — grounded in Aristotle's Rhetoric and Toulmin's Argumentation Model (both already listed as supported frameworks in §9.24); this is legitimate media/propaganda-studies analysis of existing texts, not content generation.
9.14 Framing Analysis
Economic, security, health, religious, national, gender, human-rights, environmental frames — grounded in Entman's framing functions (problem definition, causal interpretation, moral evaluation, treatment recommendation) as the underlying analytic structure.
9.15 Narrative Analysis
Characters, events, conflict, resolution, chronology, plot, narrative voice — grounded in an established narrative-structure model (e.g., Labov's abstract/orientation/complicating-action/evaluation/resolution/coda) rather than an unstructured list.
9.16 Metaphor Analysis
Textual, visual, and cross-modal metaphors; conceptual metaphors — same MIP/MIPVU-inspired, human-verified pipeline as §8.17, extended to visual/cross-modal candidates.
9.17 Emotion Analysis
Image emotion, text emotion, combined emotion, timeline, intensity.
9.18 Cultural Analysis
Culture-specific symbols, religious references, national identity, traditional clothing, architecture, colour symbolism — always framework/culture-relative, never presented as universal truths.
9.19 AI Assistant (Suite B)
"Analyse this advertisement using Kress & van Leeuwen." "Analyse this political poster using Fairclough." "Identify persuasive techniques." Same grounded-AI architecture as §8.19/§11, extended with image-region citations.
9.20 Dataset Comparison
Before/after, male/female, Arabic/English, country A/B, newspapers, campaigns, politicians, brands — implemented as a generic "compare two sub-corpora/image-sets across all applicable metrics" workflow, not per-category bespoke code.
9.21 Statistical Analysis
Chi-square, log-likelihood, correlation, regression, ANOVA, mixed models, factor analysis, cluster analysis — "no external software required" achieved by embedding a proper statistics library (e.g., scipy/statsmodels/pingouin for the frequentist tests and regression/ANOVA, with mixed-effects models as a later-phase item — see §16 — given their added complexity and the value of getting the simpler tests right first).
9.22 Automatic Report Generation
Publication-ready tables, figures, APA-formatted statistics, results summaries, interpretation suggestions, figure captions — interpretation suggestions always carry the "hypothesis, framework-lensed" framing from Principle 5.
9.23 Explainability
For every image, the tool must be able to produce a plain-language description plus an explanation of why specific Kress & van Leeuwen features were flagged, in terms a peer reviewer could check.
9.24 Framework-Based Analysis
User picks a theoretical lens, and the AI Assistant's prompt templates, output schema, and citations change accordingly. Supported frameworks at launch: Kress & van Leeuwen (Visual Grammar), Halliday's SFL, Fairclough's CDA, van Dijk's Socio-Cognitive Approach, Wodak's Discourse-Historical Approach, Machin & Mayr's MCDA, Barthes' Semiotics, Peircean Semiotics, Conceptual Metaphor Theory (Lakoff & Johnson), Appraisal Theory (Martin & White), Toulmin's Argumentation Model, Aristotle's Rhetoric. See §11.3 for how each becomes a concrete prompt template.

10. Cross-Cutting Platform Features
10.1 Research Workflow (shared by both suites)
Saved searches, bookmarks, favorites, automatic screenshots/tables/figure numbering, project management, and the "Export Methods Section" feature (§8.23).
10.2 Collaboration
Share projects; per-corpus/per-image-set public/private visibility; [DECISION NEEDED] real-time co-editing vs. save-and-sync (§7.4).
10.3 Ease of Use
Ribbon-style interface, dark/light themes, search history, undo/redo, customizable workspace, keyboard shortcuts, interactive tutorials.
(+ADD) A command palette (type-to-find-any-action) as a power-user complement to the ribbon, since researchers who do become power users will want it, without taking anything away from the zero-code default experience.
(+ADD) WCAG 2.1 AA accessibility target and full RTL mirroring for Arabic (not just RTL text within an otherwise LTR-only UI) — see §13.3.

11. The AI Assistant Layer (Deep Specification)
This section operationalizes Principles 2 and 5 (§4). Build it as a distinct, reusable service (engine/ai/) used by both suites.
11.1 Architecture: retrieval + tool-calling, not free chat
The Assistant is a tool-using agent, not a chatbot with the corpus pasted into its context. On every user question:
The engine retrieves the smallest sufficient evidence — matching concordance lines, computed statistics, or image regions — via the same deterministic engine functions the UI itself calls (never a separate, unaudited path).
The LLM is given the retrieved evidence plus a strict output schema (claim, supporting evidence IDs, confidence, and — for Suite B / interpretive claims — the active theoretical framework).
The UI renders the answer with every claim clickable back to its evidence (a concordance line, a figure, an image region).
If the LLM's claim cannot be tied to retrieved evidence, the UI must visibly flag it as ungrounded rather than silently presenting it as equal-weight fact — this is the concrete, load-bearing implementation of "grounded AI, not a bare chatbot" (Principle 2), consistent with the broader finding that citation-enforced, retrieval-grounded generation is the standard mitigation for hallucination, while retrieval alone does not guarantee correctness — hence the mandatory citation-back-to-evidence UI, not just a RAG pipeline running silently.
11.2 Tool surface exposed to the model
At minimum: search_concordance, get_frequency(unit, level), compute_collocations(node, measures[], window), compute_keyness(target_corpus, ref_corpus, measures[]), get_dispersion(term, measure), run_pos_query(pattern), get_dependency_matches(pattern), describe_image_region(image_id, bbox), get_alignment(image_id), get_framework_template(name). Each tool call and its result should be logged as part of the conversation's audit trail (Principle 4/8).
11.3 Framework prompt templates (Suite B, §9.24)
Each of the twelve supported frameworks gets its own structured system-prompt template with: (a) the framework's core analytic categories, (b) the required output schema (claim / evidence / confidence / framework attribution), (c) an explicit instruction never to state ideology, bias, or power relations as settled fact. Store these as versioned, editable files (e.g., reference-data/frameworks/*.yaml), not hard-coded strings, so researchers can inspect and even propose edits to the analytic lens being applied to their data.
11.4 Model Provider abstraction
ModelProvider (interface)
 ├── OllamaProvider     → http://localhost:11434  (native + OpenAI-compatible /v1)
 ├── LMStudioProvider   → http://localhost:1234/v1 (OpenAI-compatible)
 └── CloudProvider      → user-supplied API key, opt-in, off by default
All three implement the same chat(), stream(), and embed() methods; the rest of the codebase never branches on which provider is active. On the desktop build, corpusmind-desktop supervises the sidecar lifecycle (spawn, health-check poll, log-to-file, clean shutdown) per the pitfalls noted in §3.4.

12. Statistical & Computational Reference
Implement these to the precise, named definitions below so results match what a reviewer would expect from the cited literature — do not substitute an ad hoc variant silently.
Measure
Use
Definition (O = observed joint freq., E = expected under independence, N = corpus size, R/C = marginal freqs.)
MI (Church & Hanks 1990)
Collocation
log2(O / E), E = R·C / N within the chosen span
T-score
Collocation
(O − E) / sqrt(O)
Log-likelihood / G² (Dunning 1993)
Collocation, keyness
2 · Σ Oᵢⱼ · ln(Oᵢⱼ / Eᵢⱼ) over the 2×2 contingency table
Dice coefficient
Collocation
2·f(x,y) / (f(x) + f(y))
LogDice (Rychlý 2008)
Collocation
14 + log2( 2·f(x,y) / (f(x) + f(y)) )
Chi-square
Collocation, keyness
Standard Pearson χ² on the 2×2 contingency table
Delta P (Gries 2013; Ellis 2007)
Collocation (directional)
P(y|x) − P(y|¬x), computed in both directions
Log Ratio (Hardie 2014)
Keyness effect size
log2( (f1/N1) / (f2/N2) )
%DIFF (Gabrielatos & Marchi 2012)
Keyness effect size
((norm_f1 − norm_f2) / norm_f2) × 100
Simple Maths (Kilgarriff 2009)
Keyness score
(norm_f1 + SMOOTH) / (norm_f2 + SMOOTH), SMOOTH user-configurable
Odds Ratio
Keyness effect size
(f1 · (N2−f2)) / (f2 · (N1−f1))
Juilland's D
Dispersion
1 − (CV / sqrt(n−1)) across n corpus parts; range 0–1, higher = more even
Gries' DP (2008)
Dispersion
0.5 · Σ |observed proportionᵢ − expected proportionᵢ| across parts
STTR
Lexical variation
TTR computed over fixed-size consecutive chunks and averaged, to control for the sample-size sensitivity of raw TTR

Every result screen must show which measure(s) and parameters (window size, smoothing constant, chunk size) produced the number on screen, per Principle 8.

13. Non-Functional Requirements
13.1 Performance targets (design goals — validate empirically, don't just assert)
Target smooth KWIC/frequency/collocation queries on corpora up to the hundreds-of-millions-of-tokens range on a modern consumer laptop, via the indexed storage design in §7.3; degrade gracefully (background indexing with progress feedback) rather than freezing the UI on larger corpora.
13.2 Security & privacy
Local-first by default (Principle 1); no telemetry/analytics without explicit, separate opt-in; an at-rest encryption option for project storage on shared/institutional machines; the cloud-AI indicator from §7.5/§11.4 must be unmissable whenever active.
13.3 Accessibility & internationalization
WCAG 2.1 AA; full UI RTL mirroring for Arabic (menus, ribbon, alignment — not just text direction); UI string externalization from day one so additional languages are a translation task, not a re-engineering task.
13.4 Ethical & legal guardrails
See §18 — do not skip.
13.5 Licensing compliance
Track and surface the license of every bundled model, wordlist, and reference corpus (e.g., spaCy/Stanza are permissively licensed; CAMeL Tools/SinaTools are open-source; EVP-style CEFR wordlists carry redistribution restrictions per §8.10 and must not be bundled without confirmed rights). Maintain a THIRD_PARTY_LICENSES.md and refuse, at build time, to bundle anything whose license hasn't been recorded there.
13.6 Reproducibility
Pin tokenizer/tagger/parser/embedding-model versions per project (Principle 8); every export can include the auto-drafted Methods paragraph (§8.23).

14. Suggested Tech Stack [recommendation — confirm in §19]
Layer
Recommendation
Why
Engine
Python 3.12, FastAPI, asyncio
Best NLP/CV ecosystem access (spaCy, Stanza, CAMeL Tools, OpenCV, transformers)
General NLP
spaCy + Stanza/Trankit
Broad multilingual coverage, active maintenance
Arabic NLP
CAMeL Tools, SinaTools, Farasa, Camelira, CamelParser2.0
See §3.3, §8.21
Stats
scipy, statsmodels, pingouin
Covers §12 and §9.21 without external software
Corpus index
An embedded positional/full-text index (evaluate options capable of phrase/proximity queries at scale)
KWIC/collocation speed at scale (§7.3)
Vision
OpenCV (composition/color), an open-vocabulary detector (objects/scenes), OCR with Arabic+Latin support
§9.3–9.4
Frontend
TypeScript, React or SvelteKit + Vite
Single codebase for PWA + Tauri webview
Desktop shell
Tauri 2
Small footprint, native webview, Rust-managed sidecars (§3.4, §6)
Local LLM runtimes
Ollama, LM Studio (OpenAI-compatible endpoints)
§6, §11.4
Packaging engine as sidecar
PyInstaller-built single binary
Matches the documented Tauri sidecar pattern (§3.4)

15. Repository Structure for GitHub
Use the monorepo layout in §7.1. At the repo root, include: README.md (product overview + quickstart), docs/AI_AGENT_BUILD_PROMPT.md (this file, kept in sync), docs/ARCHITECTURE.md (living diagram, updated as decisions are made), docs/METHODOLOGY.md (the exact formulas from §12, for researcher-facing transparency), THIRD_PARTY_LICENSES.md (§13.5), CONTRIBUTING.md, and a CHANGELOG.md. [DECISION NEEDED]: overall project license (e.g., MIT/Apache-2.0/AGPL) — must be chosen with the licenses of bundled NLP/vision models in mind (§13.5) before the first public commit.

16. Phased Delivery Roadmap
Do not attempt to build all of §8 and §9 at once. Suggested phasing:
Phase 0 — Foundations. Monorepo scaffold; corpusmind-engine skeleton with health-check API; corpusmind-web skeleton as an installable PWA; corpusmind-desktop Tauri 2 shell that can spawn the engine as a sidecar; ModelProvider abstraction wired to Ollama and LM Studio with a working "hello world" chat round-trip. Ship the ribbon-style shell UI and theme system early so every later feature has a home to land in.
Phase 1 — Suite A MVP. §8.1–8.7 (ingestion, corpus management, search, concordancer, frequency, collocation, keyness) plus §8.19's grounded AI Assistant for these features only, plus §8.20's core visualizations. This alone is already a usable, shippable product.
Phase 2 — Suite A completion. §8.8–8.18, §8.21–8.25 (n-grams through Arabic, bilingual tools, research workflow, collaboration, ease-of-use polish).
Phase 3 — Arabic depth pass. Dedicated hardening of §8.21 against the CAMeL Tools/SinaTools/Farasa benchmarks (§17), since Arabic quality is a stated differentiator, not an afterthought.
Phase 4 — Suite B MVP. §9.1–9.10 (ingestion through Visual Grammar module) for one framework (start with Kress & van Leeuwen, since it's the doc's primary named framework) end-to-end, including the multimodal-alignment core (§9.8) — this is the highest-risk, most novel piece; validate it thoroughly before adding more frameworks.
Phase 5 — Suite B completion. Remaining frameworks (§9.24), remaining analysis categories (§9.11–9.23), facial-analysis opt-in module (§9.4.3, §18) behind its explicit consent gate.
Phase 6 — Collaboration, self-hosting, and polish. Multi-user sync/collaboration mode (§7.4, §10.2 decision), self-hosted engine mode (§6.3) for lab deployments, accessibility/i18n hardening (§13.3), performance tuning at scale (§13.1).

17. Testing & Validation Plan
NLP pipeline accuracy: benchmark POS/dependency parsing against standard Universal Dependencies test sets per language; benchmark the Arabic module against published CAMeL Tools/MADAMIRA/SinaTools comparison numbers rather than trusting default settings.
Statistics correctness: unit-test every formula in §12 against hand-computed or published worked examples (e.g., cross-check log-likelihood/MI/logDice output against documented example calculations from the corpus-linguistics literature) — a wrong constant in a keyness formula is a silent, serious validity bug.
Metaphor/pragmatics/CDA modules: validate the LLM-assisted candidate flagging against a held-out, human-annotated sample (e.g., a MIPVU-style annotated subset) before trusting default thresholds, and report precision/recall honestly in the docs rather than assuming parity with fine-tuned detectors (§3.2).
AI Assistant grounding: adversarial-test that every claim in an Assistant answer is either tied to a real evidence ID or visibly flagged as ungrounded (§11.1) — this is a release-blocking test category, not a nice-to-have.
Cross-platform desktop: verify the sidecar lifecycle (spawn/health-check/shutdown) on all three OSes, explicitly covering the known failure modes from §3.4 (macOS quarantine attributes, orphaned processes, log-buffer hangs, target-triple binary naming).

18. Ethical & Legal Guardrails
Facial/body/demographic inference (§9.4.3–9.4.4) ships as an explicit opt-in module, off by default, with an in-app notice explaining what it does and does not do (no identity recognition, aggregate/descriptive use only), because age/gender/emotion inference from images is legally sensitive in a growing number of jurisdictions and should never be silently on.
Interpretive/ideological claims (CDA/MCDA, §9.11–9.14, §9.18) are always framework-attributed hypotheses with cited evidence, never bare assertions of fact about real people, institutions, or groups (Principle 5) — this protects both scientific validity and the researcher from overclaiming in publication.
Object/symbol categories like "weapons," "religious symbols," and "political symbols" (§9.4.1, §9.4.10) are legitimate, standard categories in media/propaganda/discourse studies (analysis of existing published media), and should be implemented as ordinary object-detection classes like any other — this is analysis of existing content, not generation of new harmful content.
No real, identifiable individuals should ever be named or re-identified by the system from an uploaded image; keep the scope to descriptive visual/compositional analysis.

19. Open Decisions — Confirm With the Project Owner Before Locking In
Final product name (this document uses "CorpusMind" as a placeholder throughout — confirm or replace before the first public commit, and then keep it consistent everywhere).
Engine language (§7.2 recommends Python; confirm before Phase 0, since it affects the sidecar packaging strategy).
Frontend framework — React vs. SvelteKit vs. another option (§14); pick one and standardize before Phase 0.
Collaboration model — real-time CRDT co-editing vs. save-and-sync (§7.4, §10.2); a significant scope difference.
Project license (MIT/Apache-2.0/AGPL/etc.) given bundled model/data licenses (§13.5, §15).
Reference corpora sourcing — which licensed or open reference corpora will actually be bundled per supported language, and under what terms.
CEFR wordlist source (§8.10) — open frequency-band approximation by default, or a licensed EVP-style list if rights can be secured.
Facial-analysis module scope (§9.4.3, §18) — confirm which sub-features (if any) ship at all in jurisdictions with stricter biometric regulation, possibly as a build-time-removable module.
Self-hosting/collaboration server — who hosts the optional shared "engine" instance for lab/team use (§6.3), and what the pricing/hosting model (if any) is.

20. Definition of Done for the MVP (End of Phase 1)
A researcher with no programming background can, without help: install the desktop app or open the PWA, create a project, upload a multi-file text corpus, watch it auto-clean/tokenize/tag, run a concordance search, generate a collocation list with at least two selectable statistical measures, generate a keyness comparison against a reference corpus showing both a significance test and an effect-size measure, export results to Excel/PDF, and ask the AI Assistant a natural-language question about the corpus and receive an answer whose claims are clickable back to real concordance lines.
The AI Assistant works fully offline against a local Ollama or LM Studio model, with no data leaving the machine unless the user has explicitly enabled a cloud provider.
The desktop build runs cleanly on Windows, Linux, and macOS with no orphaned background processes after quitting.


