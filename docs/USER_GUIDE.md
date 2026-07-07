# CorpusMind User Guide

> Version 0.1.0 | AGPL-3.0-only
>
> Authors: Dr. Waleed Mandour (Sultan Qaboos University, ORCID: 0000-0002-9262-5993)
> and Prof. Wessam Ibrahim (Princess Nourah Bint Abdulrahman University, ORCID: 0000-0003-0710-6038)

---

## Citation

If you use CorpusMind in your research, please cite it as:

> Mandour, W., & Ibrahim, W. (2026). *CorpusMind: A local-first, AI-native
> research environment for corpus linguistics and multimodal discourse
> analysis* (Version 0.1.0) [Computer software]. Zenodo.
> https://doi.org/10.5281/zenodo.21226650

---

## 1. What is CorpusMind?

CorpusMind is a research tool for corpus linguists and discourse analysts. It
lets you upload texts, run concordance searches, compute collocations and
keyness, analyze grammar and discourse features, and work with Arabic
corpora using CAMeL Tools. It also includes a Vision suite for multimodal
discourse analysis of images using Kress and van Leeuwen's Visual Grammar.

The AI Assistant answers your questions about the corpus by calling the
analysis tools and citing specific evidence (concordance line IDs, computed
statistics). Every answer is either "grounded" (backed by a tool call) or
clearly flagged as "ungrounded."

Everything runs on your own machine. No data leaves your computer unless you
explicitly choose to use a cloud AI provider.

---

## 2. Installation

You need three things:

1. **Python 3.12 or newer** from python.org
2. **Node.js 20 or newer** from nodejs.org
3. **Ollama** from ollama.com (for the AI Assistant to work locally)

After installing Ollama, open a terminal and run:

```
ollama pull llama3.2:3b
```

### Set Up the Engine

```
cd CorpusMind/engine
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m spacy download en_core_web_sm
corpusmind-engine
```

### Set Up the Web App

Open a new terminal:

```
cd CorpusMind/web
npm install
npm run dev
```

Open http://localhost:5173 in your browser.

### Optional: Arabic Support

```
pip install camel-tools pyrsistent muddler cachetools emoji future regex
camel_data -i morphology-db-msa-r13
camel_data -i dialectid-model6
```

---

## 3. Creating a Project and Uploading Texts

1. Click **Projects** in the sidebar.
2. Click **+ New** to create a project. Enter a name and select a language.
3. Click your project to select it.
4. Click **+ New** under Corpora to create a corpus.
5. Drag and drop text files into the upload area.

Supported formats: TXT, DOCX, PDF, HTML, XML, CSV, Markdown.

The engine automatically detects encoding, cleans the text, tokenizes,
tags with POS, lemmatizes, and parses dependencies using spaCy. The
pipeline recipe (model name and version) is visible and exportable for
reproducibility.

---

## 4. Concordance Search (KWIC)

1. Select a corpus.
2. Click **Concordance** in the sidebar.
3. Type a search query.
4. Choose the level: word, lemma, or POS tag.
5. Set the context window (how many words to show left and right).
6. Click **Search**.

Each result line has a stable ID (for example, `doc:0:3`) that the AI
Assistant can cite as evidence. Use `*` for wildcards.

Click **Export Excel** to download results.

---

## 5. Frequency, Collocation, Keyness, and Dispersion

**Frequency**: Click any analysis tool in the sidebar. Choose word, lemma,
or POS. The table shows frequency, per-million, and percent. STTR
(Standardized Type-Token Ratio) is displayed at the top.

**Collocation**: Type a node word, set the window size (default 5 tokens
each side), and click Compute. All 7 measures are shown: MI, T-score,
log-likelihood, Dice, LogDice, chi-square, and Delta P (both directions).

**Keyness**: Select your target corpus, then choose a reference corpus.
Results show both significance tests (log-likelihood, chi-square) and
effect-size measures (Log Ratio, %DIFF, Simple Maths, Odds Ratio) side by
side. Click **Methods PDF** to auto-draft a methodology paragraph for your
manuscript.

**Dispersion**: Type a term. Results show Juilland's D (0 to 1, higher is
more even) and Gries' DP (0 to n-1/n, lower is more even) across
documents.

---

## 6. Advanced Analysis Tools

**N-grams**: Choose n (2 to 10). Set minimum frequency and minimum range
(number of distinct documents the n-gram must appear in). This follows the
Biber et al. (1999) frequency-and-range criterion for lexical bundles.

**POS Analysis**: View POS distribution or POS n-grams (bigrams, trigrams,
etc.) for stylistic analysis.

**Grammar**: Detect passive voice, modals, negation, relative clauses,
complex noun phrases, and tense from the dependency parse.

**Dependency**: Query specific relations (nsubj, obj, iobj, obl, etc.) to
find common governor-dependent pairs.

**Discourse**: Run Hyland's (2005) metadiscourse taxonomy across your
corpus: transitions, frame markers, hedges, boosters, attitude markers,
self-mentions, engagement markers, and more.

**Vocabulary**: Profile your corpus into frequency bands (K1, K2-K9, AWL,
Off-list). Identify rare words and academic words.

**Sentiment**: Per-sentence sentiment scores (-1 to +1) with a timeline
visualization.

**Metaphor**: Generates metaphor candidates (verbs with abstract subjects).
These are candidates only. The LLM triages them, and a human must verify
before any candidate counts as a confirmed metaphor.

---

## 7. Arabic Analysis

Click **Arabic Tools** in the sidebar. Available tools:

- **Morphology**: Full analysis with root (al-jizr), pattern (al-wazn),
  lemma, POS, stem, Buckwalter transliteration, number, gender, and
  broken-plural flag. Uses CAMeL Tools (calima-msa-r13).
- **Roots**: Extracts triliteral roots. For example, all words sharing the
  root k.t.b: kitab, maktaba, katib, yaktub.
- **Dialect ID**: Identifies MSA, Egyptian, Gulf, or Levantine using the
  full CAMeL DIDModel6 (6 city dialects).
- **Buckwalter**: Transliterates Arabic script to ASCII Latin.
- **Dediacritize**: Removes harakat (diacritics).
- **Normalize**: Unifies alef variants, teh marbuta, alef maksura.
- **Register**: Detects Classical, MSA, or Dialectal.
- **Translate**: Looks up Arabic-to-English translation equivalents.

---

## 8. Vision Suite (Multimodal Analysis)

Click **Vision Suite** in the sidebar.

1. Create an image set within your corpus.
2. Drag and drop images (JPG, PNG, TIFF, WebP).
3. Optionally add captions.
4. Select an image and use the tabs:

**Analyse**: Colour analysis (dominant colours, warm/cold balance,
brightness, contrast, saturation, symbolism notes), composition analysis
(information value: Given/New, Ideal/Real, centre/margin, salience,
rule of thirds, visual balance, framing), and OCR text extraction.

**Visual Grammar**: Analyses the image against Kress and van Leeuwen's
(2006) three metafunctions: Representational, Interactive, and
Compositional. Every claim is phrased as a hypothesis: "Under a Kress and
van Leeuwen reading, X may indicate Y."

**Align**: Multimodal image-text alignment. Type the co-occurring text and
click Align. The engine extracts image regions and text spans, then matches
them with confidence scores. Cross-modal relations (reinforcement,
complementarity, silence) are detected.

**Discourse**: 8 framework-lensed analyses: Social Semiotic, CDA (4
frameworks: Fairclough, van Dijk, Wodak, Machin and Mayr), Persuasion
(Aristotle + Toulmin), Framing (Entman), Narrative (Labov), Visual
Metaphor, Combined Emotion, and Cultural analysis.

---

## 9. The AI Assistant

Click **AI Assistant** in the sidebar. The Assistant is a tool-using agent,
not a chatbot. When you ask a question, it selects and calls the
appropriate analysis tool, then writes its answer based on the tool's
output.

If the Assistant calls a tool, the answer is marked **grounded** (green
badge). If no tool was called, the answer is marked **ungrounded** (orange
badge). The UI never silently presents an ungrounded answer as fact.

Example questions:
- "What are the top 10 most frequent words in this corpus?"
- "Find all occurrences of 'research' and show me their contexts."
- "What are the strongest collocates of 'dog' within 5 tokens?"
- "Compare this corpus against the reference. What are the top keywords?"
- "What hedges does this author use?"

---

## 10. Export, Collaboration, and Privacy

**Export**: Excel for concordance, frequency, collocations, and keyness.
PDF for the auto-drafted Methods Section (cites exact tools, versions, and
formulas).

**Saved Searches and Bookmarks**: Save queries with parameters for re-use.
Bookmark specific concordance lines or statistics with notes.

**Project Sharing**: Mark a project as shared (public or private) with a
share token. Sync events are logged in an audit trail.

**At-Rest Encryption**: Optional AES-256-GCM encryption for image files on
disk. Enable by setting the `CORPUSMIND_ENCRYPTION_KEY` environment
variable. The key is never stored on disk.

**Accessibility**: WCAG 2.1 AA target. Visible focus indicators,
skip-to-content link, high contrast mode, reduced motion support, 44px
minimum touch targets, and full RTL mirroring for Arabic.

## 11. PWA versus Desktop Application

CorpusMind ships in two forms that share the same user interface, the same
project file format, and the same analytical engine. The two forms differ in
how the engine is delivered, where the data lives, and which platform
features are available. This section documents the differences precisely so
that researchers can choose the form that fits their workflow and their
institutional data-governance constraints.

### 11.1 What the PWA Is

The Progressive Web App (PWA) is a browser-based version of CorpusMind
hosted at https://corpus-mind-web.vercel.app/. It can be installed on
Chrome, Edge, Safari, and Firefox by clicking the install icon in the
address bar. Once installed, it runs in its own window, works offline after
the first visit, and appears in the operating system's application list.

In the PWA configuration, the analytical engine runs either as a remote
service (when the researcher has access to a self-hosted CorpusMind engine
on a lab server) or as a process the researcher starts locally with the
`corpusmind-engine` command and then connects to from the browser. The
browser itself does not run Python; it talks to the engine over HTTP on
`127.0.0.1:8765` or on a remote address the researcher configures.

### 11.2 What the Desktop Application Is

The desktop application is a Tauri 2 binary for Windows, macOS (Apple
Silicon and Intel), and Linux. It bundles the web interface, the Rust
supervisor process, and (when built with the sidecar spec) the PyInstaller-
bundled engine into a single installable package. On launch, the Rust
supervisor spawns the engine as a child process, polls its health endpoint
until it is ready, redirects its stdout and stderr to log files, and kills
it cleanly on application exit.

### 11.3 Feature Comparison Table

| Capability | PWA | Desktop Application |
|---|---|---|
| Analytical tools (concordance, collocation, keyness, etc.) | Identical | Identical |
| Vision Suite (multimodal analysis) | Identical | Identical |
| AI Assistant (local LLM via Ollama) | Requires the researcher to run Ollama locally and configure the engine URL | The supervisor can spawn Ollama automatically if it is on the system PATH |
| AI Assistant (remote LLM via OpenAI / Anthropic) | Supported, opt-in | Supported, opt-in |
| Engine delivery | Researcher starts the engine manually, or connects to a lab-server engine | Supervisor spawns and supervises the engine automatically |
| At-rest encryption (AES-256-GCM) | Supported, with the encryption key set via environment variable | Supported, with the key set via the desktop settings dialog or the environment |
| File system access | Limited to files the researcher uploads through the browser dialog; no access to arbitrary paths on disk | Full access to files the researcher opens through the desktop dialog; can read from the project's data directory |
| Offline operation | After the first visit, the PWA shell loads from cache; the engine still needs to be running locally for analysis | Fully offline after installation; no network connection required for any analytical operation |
| Process lifecycle | The researcher starts and stops the engine manually; if the browser tab is closed, the engine keeps running until killed | The supervisor starts the engine on app launch and kills it on app exit; no orphaned processes |
| Log files | Engine logs go to wherever the researcher started the engine; the PWA does not manage them | Engine stdout and stderr are redirected to `engine.stdout.log` and `engine.stderr.log` in the OS log directory |
| Cross-platform consistency | Identical on every operating system because the browser is the runtime | Identical UI, but the supervisor and sidecar binary are platform-specific (one build per OS) |
| Installation | One click (install icon in the browser) | Download and run the platform installer (.dmg, .exe, .msi, .AppImage, .deb) |
| Update mechanism | Transparent; the PWA updates on next visit when the server ships a new version | Manual; the researcher downloads the new installer or builds from source |
| Sandboxing | The browser sandbox restricts file system and network access to what the CSP allows | The Tauri shell enforces the same CSP, but the Rust supervisor has full process-control privileges |
| Institutional deployment | Easy: point the PWA at a lab-server engine URL and share the URL with the team | Each researcher installs the desktop app; a lab server is optional |
| Data residency | If the engine runs on a lab server, the corpus data lives on that server; if the engine runs locally, the data lives on the researcher's machine | The corpus data always lives on the researcher's machine; no data leaves the device unless a remote LLM provider is configured |

### 11.4 Which Form to Choose

Choose the **PWA** if you want to try CorpusMind without installing
anything, if your institution already hosts a shared engine on a lab
server, or if you work across many machines and want your project state
to follow you. The PWA is also the only option on ChromeOS and on locked-
down corporate machines where you cannot install native applications.

Choose the **desktop application** if you work with sensitive or
unpublished corpora and need a strict local-only default, if you want the
engine to start and stop automatically with the application, if you want
the engine logs managed for you, or if you need the full offline
experience with no browser in the loop. The desktop application is also
the recommended form for classroom deployment where the instructor
pre-installs the application on lab machines and students do not need to
manage the engine lifecycle.

---

## 12. CorpusMind Compared with Other Corpus Tools

CorpusMind is not a replacement for every existing corpus tool. Each tool
in this section was designed for a different audience and a different
era of computing. This section compares CorpusMind with four widely used
corpus analysis tools: AntConc, Sketch Engine, #LancsBox, and Voyant
Tools. The comparison is based on the official documentation of each
tool as of 2025, and every claim is sourced to the tool's own website or
to a peer-reviewed publication about it.

### 12.1 AntConc

AntConc is a freeware corpus analysis toolkit developed by Laurence
Anthony at Waseda University and first released in 2002. It is a desktop
application written in Perl and compiled to a native binary for Windows,
macOS, and Linux. It is distributed at no cost from
https://www.laurenceanthony.net/software/antconc/.

AntConc provides a concordancer (KWIC), a cluster and n-gram tool, a
collocate tool, a word list tool, and a keyword tool. It supports
regular-expression search, user-defined tag handling, and a range of
output sort options. It does not include a lemmatiser, a POS tagger, or
a dependency parser; the researcher is expected to pre-process the
corpus with an external tool if lemmatised or POS-tagged search is
required. It does not include an AI assistant, a vision pipeline, or
multimodal analysis. Arabic support is limited because AntConc does not
bundle an Arabic morphological analyser; researchers working with Arabic
typically pre-process the corpus with a separate tool such as
Farasa or CAMeL Tools and then import the tagged text into AntConc.

CorpusMind differs from AntConc in four respects. First, CorpusMind
bundles spaCy and CAMeL Tools, so tokenisation, lemmatisation, POS
tagging, dependency parsing, and Arabic morphology are available without
any pre-processing step. Second, CorpusMind implements all seven
collocation measures documented in the methodology literature (MI,
T-score, log-likelihood, Dice, LogDice, chi-square, Delta P) and both
keyness measures (log-likelihood ratio and Burrows's Zeta) in a single
interface, whereas AntConc's collocate tool reports a single statistic
selected by the user. Third, CorpusMind includes a Vision Suite for
multimodal discourse analysis and an AI assistant with a citation-
enforced contract, neither of which AntConc provides. Fourth, CorpusMind
emits a YAML provenance record for every analytical operation, whereas
AntConc does not record the pipeline configuration or the software
version with the output. AntConc remains an excellent choice for
teaching corpus linguistics at the introductory level, for quick
concordance searches on pre-processed corpora, and for researchers who
prefer a single-purpose desktop tool without network dependencies.

### 12.2 Sketch Engine

Sketch Engine is a commercial corpus management and analysis platform
developed by Lexical Computing Limited and first released in 2003. It is
a web-based service available at https://www.sketchengine.eu/. It
requires a paid subscription; academic personal accounts start at
approximately 7.09 EUR per month, and institutional licences are priced
per user. A free tier called SKELL is available for language learners
but does not include the full analysis toolset.

Sketch Engine's signature feature is the Word Sketch: a one-page,
automatically generated grammatical collocation profile of a word, built
by parsing the corpus with a language-specific sketch grammar and
grouping collocates by grammatical relation (subject-of, object-of,
modifier-of, etc.). It also offers a distributional thesaurus,
concordance, word list, keyword, n-grams, and term extraction. Sketch
Engine hosts a large collection of ready-made corpora (British National
Corpus, English Web Corpus 2021, enTenTen, and many others) and allows
researchers to upload their own corpora up to a size limit determined by
the subscription tier. It supports over 100 languages, with language-
specific taggers and sketch grammars for most of them.

CorpusMind differs from Sketch Engine in three respects. First,
CorpusMind is local-first and free (AGPL-3.0-only); the researcher's
corpus never leaves their machine unless they explicitly configure a
remote LLM provider. Sketch Engine is a cloud service; the corpus is
uploaded to the Sketch Engine servers for processing. This makes Sketch
Engine unsuitable for unpublished or confidential corpora unless the
researcher has an institutional licence with a data-processing
agreement. Second, CorpusMind does not currently implement the Word
Sketch grammatical collocation profile; this is a feature on the roadmap
for a later release. Sketch Engine's Word Sketch remains the reference
implementation for grammatical collocation summarisation, and
researchers who need it should use Sketch Engine. Third, CorpusMind
includes a Vision Suite for multimodal discourse analysis and an AI
assistant with a citation-enforced contract; Sketch Engine does not
offer either. Sketch Engine is the better choice for researchers who
need ready-made large reference corpora, for lexicographers who rely on
Word Sketches, and for teams that prefer a managed cloud service over a
local installation.

### 12.3 #LancsBox

#LancsBox is a free corpus analysis toolbox developed at Lancaster
University by Vaclav Brezina and colleagues and first released in 2015.
The current version, #LancsBox X, is available at
https://lancsbox.lancs.ac.uk/. It is a desktop application for Windows,
macOS, and Linux and is distributed at no cost for non-commercial
academic use.

#LancsBox provides concordancing, collocation analysis, frequency
lists, keyword analysis, dispersion plots, and a distinctive "Graph
Coll" visualisation that shows collocational relationships as a network
graph with the node word at the centre. It includes built-in support
for BNC and BNC64 reference corpora and allows researchers to upload
their own corpora. It supports multiple languages for tokenisation but
does not bundle language-specific POS taggers or morphological analysers
beyond English.

CorpusMind differs from #LancsBox in three respects. First, CorpusMind
implements the full seven-measure collocation suite and the four-measure
dispersion suite (Juilland's D, Gries's DP, average reduced frequency,
and average wait time) with provenance records, whereas #LancsBox
focuses on a smaller set of measures with richer visualisation. Second,
CorpusMind includes the Vision Suite and the AI assistant; #LancsBox
does not. Third, CorpusMind bundles CAMeL Tools for Arabic morphology,
dialect identification, and named-entity recognition, whereas #LancsBox
treats Arabic as a plain-text corpus without morphological analysis.
#LancsBox is the better choice for researchers who value the Graph Coll
network visualisation, for classroom use where the visual immediacy of
the tool supports teaching, and for researchers working primarily with
English reference corpora.

### 12.4 Voyant Tools

Voyant Tools is a free, web-based text analysis environment developed
by Stéfan Sinclair and Geoffrey Rockwell and first released in 2012. It
is available at https://voyant-tools.org/. It is open source and can be
self-hosted, but most researchers use the public hosted instance.

Voyant Tools provides a multi-panel interface with a reader, a word
cloud, a trends graph, a contexts tool, a collocates tool, a
correlations tool, a scatterplot, and a dreamcatcher visualisation. It
is designed for digital-humanities work on small to medium corpora and
emphasises visual exploration over statistical rigour. It does not
bundle a POS tagger, a lemmatiser, or a dependency parser; it works on
raw token frequency. It does not implement the standard collocation
measures (MI, t-score, log-likelihood, etc.) and does not emit a
provenance record. It does not support Arabic morphology.

CorpusMind differs from Voyant Tools in four respects. First, CorpusMind
implements the full statistical suite (seven collocation measures, four
dispersion measures, two keyness measures) with formal definitions and
primary-literature citations, whereas Voyant Tools focuses on visual
exploration. Second, CorpusMind bundles spaCy and CAMeL Tools for
linguistic annotation, whereas Voyant Tools works on raw tokens. Third,
CorpusMind includes the Vision Suite and the AI assistant; Voyant Tools
does not. Fourth, CorpusMind emits a YAML provenance record for every
operation; Voyant Tools does not. Voyant Tools is the better choice for
digital-humanities researchers who want a quick visual overview of a
text, for teaching introductory text analysis, and for researchers who
do not need linguistic annotation or statistical rigour.

### 12.5 Summary Comparison Table

| Feature | CorpusMind | AntConc | Sketch Engine | #LancsBox | Voyant Tools |
|---|---|---|---|---|---|
| Licence | AGPL-3.0-only (free, open source) | Freeware (closed source) | Commercial (subscription) | Free for academic use (closed source) | Open source (GPL) |
| Price | Free | Free | From 7.09 EUR/month (academic) | Free | Free |
| Deployment | Local-first desktop + PWA | Desktop only | Cloud only | Desktop only | Web only |
| Concordance (KWIC) | Yes | Yes | Yes | Yes | Yes (Contexts) |
| Collocation measures | 7 (MI, t-score, LL, Dice, LogDice, chi-square, Delta P) | 1 (user-selected) | Multiple (Word Sketch grammar-based) | Several | 1 (raw co-occurrence) |
| Keyness | Yes (LL, chi-square, Log Ratio, %DIFF, Simple Maths, Odds Ratio) | Yes (LL, chi-square) | Yes | Yes | No |
| Dispersion | Yes (Juilland's D, Gries's DP, ARF, AWT) | No | Yes | Yes (visual) | No |
| POS tagging | Yes (spaCy) | No (pre-process externally) | Yes (language-specific) | Limited | No |
| Lemmatisation | Yes (spaCy, CAMeL Tools) | No | Yes | Limited | No |
| Dependency parsing | Yes (spaCy) | No | No | No | No |
| Arabic morphology | Yes (CAMeL Tools: root, pattern, lemma, dialect ID) | No | Yes (Arabic sketch grammar) | No | No |
| Multimodal / Vision analysis | Yes (Kress and van Leeuwen Visual Grammar, OCR, object detection) | No | No | No | No |
| AI assistant | Yes (grounded, citation-enforced, local LLM via Ollama) | No | No | No | No |
| Provenance records (YAML) | Yes (every operation) | No | No | No | No |
| At-rest encryption | Yes (AES-256-GCM) | No | No (cloud-hosted) | No | No (cloud-hosted) |
| Ready-made reference corpora | No (researcher supplies corpus) | No | Yes (BNC, enTenTen, 100+ languages) | Yes (BNC, BNC64) | No |
| Word Sketch (grammatical collocation profile) | No (on roadmap) | No | Yes (reference implementation) | No | No |
| Network collocation visualisation | No (table-based) | No | No | Yes (Graph Coll) | No |
| Word cloud | No | No | No | No | Yes |
| Offline operation | Yes (desktop) / partial (PWA) | Yes | No (cloud) | Yes | No (web) |
| Data residency | Local by default | Local | Cloud (uploaded) | Local | Cloud (uploaded, or self-host) |
| Reproducibility for peer review | Yes (YAML provenance + methods.pdf export) | Manual | Limited | Manual | Manual |

### 12.6 When to Use Which Tool

Use **CorpusMind** when you need local-first, reproducible, framework-
grounded analysis of English or Arabic corpora, when you need multimodal
discourse analysis of images alongside text, or when you need an AI
assistant that grounds its claims in corpus evidence.

Use **AntConc** when you need a quick concordance on a pre-processed
corpus in a classroom or workshop setting, when you do not need
lemmatisation or POS tagging, or when you are on a machine where you
cannot install Python.

Use **Sketch Engine** when you need ready-made large reference corpora,
when you need the Word Sketch grammatical collocation profile, or when
your team prefers a managed cloud service and your data-governance
policy permits uploading the corpus to a third-party server.

Use **#LancsBox** when you value the Graph Coll network visualisation,
when you are teaching corpus linguistics and want a visually intuitive
tool, or when you work primarily with the BNC or BNC64.

Use **Voyant Tools** when you want a quick visual overview of a text in
a digital-humanities context, when you do not need linguistic annotation
or statistical rigour, or when you are working in a browser-only
environment.

These tools are complementary, not mutually exclusive. Many researchers
will use more than one: for example, Voyant Tools for an initial visual
overview, CorpusMind for the rigorous statistical and multimodal
analysis, and Sketch Engine for the Word Sketch when a grammatical
collocation profile is required.

---

## Getting Help

- GitHub: https://github.com/waleedmandour/CorpusMind/issues
- Live PWA: https://corpus-mind-web.vercel.app/
- Build Guide: docs/BUILD_GUIDE.md
- Methodology Reference: docs/METHODOLOGY.md
- Zenodo DOI: https://doi.org/10.5281/zenodo.21226650