# CorpusMind User Guide

> Version 0.1.0 | AGPL-3.0-only
>
> Authors: Dr. Waleed Mandour (Sultan Qaboos University, ORCID: 0000-0002-9262-5993)
> and Prof. Wessam Ibrahim (ORCID: 0000-0003-0710-6038)

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

---

## Getting Help

- GitHub: https://github.com/waleedmandour/CorpusMind/issues
- Live PWA: https://corpus-mind-web.vercel.app/
- Build Guide: docs/BUILD_GUIDE.md
- Methodology Reference: docs/METHODOLOGY.md
