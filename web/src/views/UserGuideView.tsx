/**
 * UserGuideView — an in-app, professional user guide.
 *
 * Content is organized into expandable sections covering installation,
 * corpus management, analysis tools, Arabic NLP, the Vision suite, the
 * AI Assistant, privacy, and troubleshooting. Mirrors docs/USER_GUIDE.md
 * but reformatted as an interactive in-app page.
 */
import { useState } from "react";

interface GuideSection {
  id: string;
  title: string;
  icon: string;
  body: React.ReactNode;
}

const sections: GuideSection[] = [
  {
    id: "getting-started",
    title: "Getting Started",
    icon: "\u25B6",
    body: (
      <>
        <p>
          CorpusMind is a research tool for corpus linguists and discourse analysts. It lets you
          upload texts, run concordance searches, compute collocations and keyness, analyze
          grammar and discourse features, and work with Arabic corpora using CAMeL Tools. It also
          includes a Vision suite for multimodal discourse analysis of images using Kress and van
          Leeuwen's Visual Grammar.
        </p>
        <h4>Prerequisites</h4>
        <ul>
          <li><strong>Python 3.12 or newer</strong> from python.org</li>
          <li><strong>Node.js 20 or newer</strong> from nodejs.org</li>
          <li><strong>Ollama</strong> from ollama.com (for the AI Assistant to work locally)</li>
        </ul>
        <h4>Start the Engine</h4>
        <pre>{`cd CorpusMind/engine
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\\Scripts\\activate
pip install -e ".[dev]"
python -m spacy download en_core_web_sm
corpusmind-engine`}</pre>
        <h4>Start the Web App</h4>
        <pre>{`cd CorpusMind/web
npm install
npm run dev`}</pre>
        <p>Open <code>http://localhost:5173</code> in your browser. The engine runs on port 8765.</p>
        <h4>Optional: Arabic Support</h4>
        <pre>{`pip install camel-tools pyrsistent muddler cachetools emoji future regex
camel_data -i morphology-db-msa-r13`}</pre>
      </>
    ),
  },
  {
    id: "projects",
    title: "Projects and Corpora",
    icon: "\u25B6",
    body: (
      <>
        <p>
          A <strong>project</strong> is a container for one or more <strong>corpora</strong>. A corpus
          is a collection of documents (TXT, DOCX, PDF, HTML, XML, CSV, Markdown) that you analyze
          together. Projects let you organize research by topic, course, or paper.
        </p>
        <ol>
          <li>Click <strong>Projects</strong> in the sidebar.</li>
          <li>Click <strong>+ New Project</strong>, give it a name and optional description.</li>
          <li>Inside the project, click <strong>+ New Corpus</strong> and pick a language (en/ar).</li>
          <li>Drag and drop your text files into the corpus, or click <strong>Upload</strong>.</li>
          <li>The engine automatically detects encoding, parses the format, tokenizes, tags, and
          lemmatizes each document. You can watch progress in real time.</li>
        </ol>
        <p>
          Once documents are ingested, the corpus is ready for analysis. You can switch between
          corpora at any time using the corpus selector at the top of each analysis view.
        </p>
      </>
    ),
  },
  {
    id: "concordance",
    title: "Concordance (KWIC)",
    icon: "\u25B6",
    body: (
      <>
        <p>
          The <strong>Concordance</strong> view (KWIC — Key Word In Context) is the workhorse of
          corpus linguistics. It shows every occurrence of a search term with a window of context
          on either side, sorted and filterable.
        </p>
        <ul>
          <li><strong>Search term:</strong> a word, lemma, or phrase. Use <code>*</code> as a wildcard.</li>
          <li><strong>Case-sensitive:</strong> toggle to match exact case.</li>
          <li><strong>Context window:</strong> how many words to show left and right (default 5).</li>
          <li><strong>Sort:</strong> by left context, right context, or word position.</li>
          <li><strong>Filter by POS:</strong> show only nouns, verbs, adjectives, etc.</li>
        </ul>
        <p>
          Every concordance line has a stable evidence ID you can cite. Click <strong>Export Excel</strong>
          to download the full results as a spreadsheet for offline analysis or inclusion in a
          manuscript supplement.
        </p>
      </>
    ),
  },
  {
    id: "frequency",
    title: "Frequency and STTR",
    icon: "\u25B6",
    body: (
      <>
        <p>
          The <strong>Frequency</strong> view shows word, lemma, and POS frequency counts. For
          each type you get: raw count, per-million-normalized frequency, and percentage of the
          corpus.
        </p>
        <h4>Standardized Type-Token Ratio (STTR)</h4>
        <p>
          STTR measures lexical diversity. It computes the average type-token ratio over
          fixed-size segments (default 1,000 tokens) and averages them, which makes it
          comparable across corpora of different sizes. A higher STTR means more lexical variety.
        </p>
        <p>
          Use STTR to compare registers (e.g. academic vs. spoken), genres, or learner
          proficiency levels. A typical academic prose STTR is around 0.40–0.45; spoken
          conversation is usually lower (0.30–0.35).
        </p>
      </>
    ),
  },
  {
    id: "collocation",
    title: "Collocation",
    icon: "\u25B6",
    body: (
      <>
        <p>
          The <strong>Collocation</strong> view computes all seven standard association measures
          for words that co-occur with a node word within a window:
        </p>
        <ul>
          <li><strong>MI</strong> (Mutual Information) — sensitive to low-frequency, tightly-bound pairs.</li>
          <li><strong>T-score</strong> — favors high-frequency pairs; more stable on small corpora.</li>
          <li><strong>Log-Likelihood (LL)</strong> — the most widely used; good balance.</li>
          <li><strong>Dice</strong> and <strong>LogDice</strong> — normalized co-occurrence.</li>
          <li><strong>Chi-square</strong> — classic significance test.</li>
          <li><strong>Delta P</strong> — directional; shows which word predicts the other.</li>
        </ul>
        <p>
          The window size defaults to 5 words left and right. Use MI &gt; 3 and T-score &gt; 2 as
          rough thresholds for "significant" collocations, but always report your parameters.
        </p>
      </>
    ),
  },
  {
    id: "keyness",
    title: "Keyness",
    icon: "\u25B6",
    body: (
      <>
        <p>
          <strong>Keyness</strong> compares a target corpus against a reference corpus to find
          words that are significantly more (or less) frequent in the target. This is the
          standard technique for "what makes this corpus distinctive?"
        </p>
        <p>
          CorpusMind computes three keyness statistics side by side:
        </p>
        <ul>
          <li><strong>Log-Likelihood (LL)</strong> — the most widely reported.</li>
          <li><strong>Log Ratio</strong> — an effect-size measure (LL alone can flag trivially
            small differences as "significant" on large corpora).</li>
          <li><strong>%DIFF</strong> — percentage difference in relative frequency.</li>
        </ul>
        <p>
          To run keyness: select your target corpus (the one you're studying), then pick a
          reference corpus (the one to compare against — often a large reference corpus like a
          general-language sample). The result is a sortable table of keywords with their
          statistics. A positive keyness means the word is <em>more</em> frequent in the target;
          a negative keyness means <em>less</em> frequent.
        </p>
      </>
    ),
  },
  {
    id: "ngrams",
    title: "N-grams and Phraseology",
    icon: "\u25B6",
    body: (
      <>
        <p>
          The <strong>N-grams</strong> view extracts recurring multi-word sequences. You can
          search by length (2-gram, 3-gram, etc.), minimum frequency, and minimum range (the
          number of distinct documents the n-gram must appear in — this filters out one-off
          repetitions).
        </p>
        <p>
          Use n-grams to identify:
        </p>
        <ul>
          <li><strong>Lexical bundles</strong> — frequent multi-word units that characterize a
            register (e.g. "on the other hand" in academic prose).</li>
          <li><strong>Formulaic language</strong> — idioms and fixed phrases.</li>
          <li><strong>Collostructions</strong> — patterns like "X is Y" or "the N of the N".</li>
        </ul>
      </>
    ),
  },
  {
    id: "pos-grammar",
    title: "POS, Grammar, and Dependency",
    icon: "\u25B6",
    body: (
      <>
        <h4>POS Analysis</h4>
        <p>
          Shows the distribution of parts of speech (noun, verb, adjective, etc.) across the
          corpus, plus the most frequent POS n-grams (e.g. "DET NOUN" is usually the most common
          2-gram in English).
        </p>
        <h4>Grammar Patterns</h4>
        <p>
          Detects and counts structural patterns:
        </p>
        <ul>
          <li><strong>Passive voice</strong> — "was written", "is being done", etc.</li>
          <li><strong>Modals</strong> — can, could, may, might, must, shall, should, will, would.</li>
          <li><strong>Negation</strong> — not, never, no, n't, and their scope.</li>
        </ul>
        <h4>Dependency Patterns</h4>
        <p>
          Queries the Universal Dependencies parse. You can search for specific relations
          (nsubj, dobj, amod, etc.) between a governor and a dependent. This is the most
          fine-grained syntactic analysis CorpusMind offers.
        </p>
      </>
    ),
  },
  {
    id: "discourse",
    title: "Discourse and Stance",
    icon: "\u25B6",
    body: (
      <>
        <p>
          The <strong>Discourse</strong> view applies Hyland's metadiscourse taxonomy and Martin
          &amp; White's appraisal framework to identify how writers position themselves and their
          readers.
        </p>
        <h4>Metadiscourse (Hyland 2005)</h4>
        <ul>
          <li><strong>Interactive markers:</strong> transitions, frame markers, endophoric
            markers, evidentials, code glosses.</li>
          <li><strong>Interactional markers:</strong> hedges, boosters, attitude markers,
            self-mentions, engagement markers.</li>
        </ul>
        <h4>Appraisal (Martin &amp; White 2005)</h4>
        <ul>
          <li><strong>Affect</strong> — emotional responses.</li>
          <li><strong>Judgment</strong> — moral evaluations of behavior.</li>
          <li><strong>Appreciation</strong> — aesthetic evaluations.</li>
        </ul>
      </>
    ),
  },
  {
    id: "vocab-sentiment",
    title: "Vocabulary and Sentiment",
    icon: "\u25B6",
    body: (
      <>
        <h4>Vocabulary Profile</h4>
        <p>
          Classifies each token into frequency bands (K1, K2, K3-K5, K6-K9, K10+, off-list) based
          on a reference frequency list. Also flags academic words (from the Academic Word List)
          and rare words. Useful for assessing text difficulty, learner proficiency, or comparing
          registers.
        </p>
        <h4>Sentiment</h4>
        <p>
          A lexicon-based sentiment analysis (positive, negative, neutral) with a per-sentence
          timeline. The lexicon is opt-in and configurable; no machine-learning model is used, so
          the results are fully transparent and reproducible.
        </p>
        <h4>Metaphor Candidates</h4>
        <p>
          Applies the MIP (Metaphor Identification Procedure) — flags words whose contextual
          meaning differs from their basic meaning. These are <em>candidates</em> for metaphor,
          not confirmed metaphors; a human analyst must verify each one.
        </p>
      </>
    ),
  },
  {
    id: "arabic",
    title: "Arabic Tools",
    icon: "\u25B6",
    body: (
      <>
        <p>
          CorpusMind treats Arabic as a first-class language. The Arabic tools are built on
          <strong> CAMeL Tools</strong> (the standard NLP toolkit for Modern Standard Arabic),
          with optional Farasa and SinaTools backends.
        </p>
        <h4>Morphology</h4>
        <p>
          Full morphological analysis: lemma, root (جذر), pattern (وزن), POS, stem, Buckwalter
          transliteration, and dediacritized form. Useful for semantic-field analysis (all words
          sharing a root are semantically related) and for matching across spelling variants.
        </p>
        <h4>Dialect Identification</h4>
        <p>
          Returns a probability distribution over {`{MSA, Egyptian, Gulf, Levantine}`}. Useful
          for filtering parallel corpora or studying dialectal variation.
        </p>
        <h4>Root extraction</h4>
        <p>
          Extracts the triliteral root for each token (e.g. <code>المكتبة → ك.ت.ب</code>). This is
          essential for Arabic corpus linguistics, where surface forms are highly inflected.
        </p>
        <h4>Bilingual alignment</h4>
        <p>
          Aligns Arabic and English sentence pairs in a parallel corpus, then runs parallel
          concordance searches across both sides.
        </p>
        <p className="hint">
          Arabic support requires the optional <code>camel-tools</code> package. Run
          <code> pip install -e ".[arabic]"</code> in the engine directory, then
          <code> camel_data -i morphology-db-msa-r13</code> to download the morphology database.
        </p>
      </>
    ),
  },
  {
    id: "vision",
    title: "Vision Suite",
    icon: "\u25B6",
    body: (
      <>
        <p>
          The <strong>Vision Suite</strong> supports multimodal discourse analysis — analyzing
          images alongside text using Kress and van Leeuwen's Visual Grammar framework.
        </p>
        <h4>Image analysis</h4>
        <ul>
          <li><strong>OCR</strong> — extract text embedded in images.</li>
          <li><strong>Object and scene detection</strong> — identify what's in the image.</li>
          <li><strong>Composition and color</strong> — color palette, brightness, contrast,
            rule-of-thirds analysis.</li>
        </ul>
        <h4>Visual Grammar (Kress &amp; van Leeuwen 2006)</h4>
        <p>
          Scores each image on the four metafunctions:
        </p>
        <ul>
          <li><strong>Representational</strong> — narrative vs. conceptual processes.</li>
          <li><strong>Interactive</strong> — gaze, angle, social distance (power and involvement).</li>
          <li><strong>Compositional</strong> — information value, framing, salience.</li>
          <li><strong>Modal</strong> — modality cues (color saturation, focus, illumination).</li>
        </ul>
        <h4>Multimodal alignment</h4>
        <p>
          Aligns image regions with text spans to study cross-modal meaning-making. Useful for
          analyzing how images reinforce, contradict, or extend the verbal text.
        </p>
        <p className="hint">
          Vision features require the optional <code>[vision]</code> extra:
          <code> pip install -e ".[vision]"</code>.
        </p>
      </>
    ),
  },
  {
    id: "ai-assistant",
    title: "The AI Assistant",
    icon: "\u25B6",
    body: (
      <>
        <p>
          The <strong>AI Assistant</strong> is a tool-using agent, not a chatbot. When you ask a
          question, it:
        </p>
        <ol>
          <li>Retrieves the smallest sufficient evidence from your corpus (concordance lines,
            computed statistics, image regions) using the same deterministic engine functions the
            UI itself calls.</li>
          <li>Sends the retrieved evidence to the LLM with a strict output schema
            (<code>claim</code>, <code>evidence_ids</code>, <code>confidence</code>,
            <code>framework</code>).</li>
          <li>Renders the answer with every claim clickable back to its evidence.</li>
          <li>If a claim cannot be tied to retrieved evidence, visibly flags it as
            <strong> UNGROUNDED</strong> rather than silently presenting it as fact.</li>
        </ol>
        <h4>Providers</h4>
        <ul>
          <li><strong>Ollama</strong> (default, local) — runs on 127.0.0.1:11434. Start it with
            <code> ollama serve</code> after installing from ollama.com.</li>
          <li><strong>LM Studio</strong> (local) — runs on 127.0.0.1:1234.</li>
          <li><strong>Cloud</strong> (opt-in) — Anthropic or OpenAI. Off by default; activating
            it requires explicit user action, and an unmissable indicator shows whenever a cloud
            request is in flight.</li>
        </ul>
        <h4>Grounded vs. Ungrounded</h4>
        <p>
          A <strong>grounded</strong> answer has every claim backed by a cited tool call with a
          stable evidence ID. An <strong>ungrounded</strong> answer is the LLM's opinion without
          corpus evidence — it is clearly flagged so you never mistake it for a finding.
        </p>
      </>
    ),
  },
  {
    id: "privacy",
    title: "Privacy and Ethics",
    icon: "\u25B6",
    body: (
      <>
        <h4>Local-first by default</h4>
        <p>
          Your corpus text, images, and AI queries never leave your machine unless you explicitly
          opt in to a cloud provider. The engine runs on localhost; the AI Assistant calls local
          Ollama/LM Studio by default.
        </p>
        <h4>Cloud is opt-in and visibly indicated</h4>
        <p>
          The CloudProvider is off by default. Activating it requires explicit user action in
          Settings. Whenever a cloud request is in flight, an unmissable indicator appears in the
          top bar. Self-hosted lab deployments can hard-disable cloud entirely with
          <code> CORPUSMIND_CLOUD_DISABLED_HARD=true</code>.
        </p>
        <h4>No telemetry or analytics</h4>
        <p>
          Zero analytics, zero error reporting, zero phone-home. By design. The Smart
          Troubleshooting feature only sends error text to Google Gemini if you explicitly
          configure a Gemini API key in the engine environment — and even then, only the error
          text is sent, never your corpus data.
        </p>
        <h4>Framework-lensed hypotheses</h4>
        <p>
          Every interpretive claim (CDA, power, ideology) is phrased as "Under a [Framework]
          reading, X may indicate Y." Never as a bare assertion of fact. This keeps the AI
          Assistant honest about the difference between evidence and interpretation.
        </p>
        <h4>Facial analysis is opt-in</h4>
        <p>
          Off by default. Never performs identity recognition or re-identification of real
          individuals.
        </p>
      </>
    ),
  },
  {
    id: "troubleshooting",
    title: "Smart Troubleshooting",
    icon: "\u25B6",
    body: (
      <>
        <p>
          CorpusMind includes a <strong>Smart Troubleshooting</strong> system that watches for
          backend errors during normal use. It only fires when something actually goes wrong —
          you won't see it when everything is working.
        </p>
        <h4>How it works</h4>
        <ol>
          <li>When a backend request fails (a 4xx/5xx response or a network error), the error is
            captured automatically. Duplicate errors within a 5-second window are suppressed so
            you're not spammed.</li>
          <li>The error appears in the <strong>taskbar</strong> at the bottom of the window. Click
            it to see the full details.</li>
          <li>If you've configured a <strong>Gemini API key</strong> in the engine environment
            (via <code>CORPUSMIND_GEMINI_API_KEY</code>), the error is sent to Google's Gemini
            model for interpretation. Gemini returns a plain-language explanation of what went
            wrong, the likely cause, and a suggested fix.</li>
          <li>If the error looks like a real bug, a <strong>Report to Developer</strong> button
            appears. Clicking it opens your email client with a pre-filled message to
            <code> w.abumandour@squ.edu.om</code> containing the error details and Gemini's
            interpretation.</li>
        </ol>
        <h4>Configuring Gemini interpretation (optional)</h4>
        <pre>{`# In the engine environment (e.g. engine/.env or your shell):
export CORPUSMIND_GEMINI_API_KEY="your-key-from-aistudio.google.com/apikey"
export CORPUSMIND_GEMINI_MODEL="gemini-2.5-flash"  # optional, this is the default

# Then restart the engine:
corpusmind-engine`}</pre>
        <p className="hint">
          Get a free API key at <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">aistudio.google.com/apikey</a>.
          The free tier is sufficient for troubleshooting use. The key is stored in the engine
          environment and never exposed to the browser.
        </p>
        <h4>Privacy note</h4>
        <p>
          Only the error text (message, HTTP code, endpoint, and what you were doing) is sent to
          Gemini. Your <strong>corpus data is never sent</strong>. If you don't configure a
          Gemini key, the feature still captures errors and shows them in the taskbar — you just
          don't get the AI interpretation.
        </p>
      </>
    ),
  },
  {
    id: "exporting",
    title: "Exporting Results",
    icon: "\u25B6",
    body: (
      <>
        <p>
          Every analysis result in CorpusMind can be exported in multiple formats.
          Click the <strong>Export</strong> dropdown button in any analysis view
          (Concordance, Frequency, Collocation, Keyness) and pick a format.
        </p>
        <h4>Tabular formats (concordance, frequency, collocation, keyness)</h4>
        <table className="guide-shortcut-table">
          <thead>
            <tr><th>Format</th><th>Use case</th></tr>
          </thead>
          <tbody>
            <tr><td><strong>Excel (.xlsx)</strong></td><td>Styled spreadsheet — opens in Excel or Google Sheets. Good for sharing with collaborators.</td></tr>
            <tr><td><strong>CSV (.csv)</strong></td><td>Universal comma-separated — opens in any tool (R, Python, Excel, SPSS).</td></tr>
            <tr><td><strong>TSV (.tsv)</strong></td><td>Tab-separated — paste directly into Excel or Google Sheets.</td></tr>
            <tr><td><strong>Plain text (.txt)</strong></td><td>Fixed-width table — for emails, quick inspection, or plain-text notes.</td></tr>
            <tr><td><strong>JSON (.json)</strong></td><td>Structured — for programmatic use, re-import into scripts, or feeding into another pipeline.</td></tr>
          </tbody>
        </table>
        <h4>Diagram export (collocations)</h4>
        <p>
          The Collocation view has a separate <strong>Export diagram</strong> dropdown
          that produces a collocation network diagram:
        </p>
        <ul>
          <li><strong>SVG (.svg)</strong> — vector graphics. Scales to any size
            without quality loss. Open in a browser, Inkscape, or Adobe Illustrator.
            Best for papers, posters, and slides.</li>
          <li><strong>PNG (.png)</strong> — raster image at 1600×1200. Best for
            Word documents, social media, or anywhere SVG isn&apos;t supported.
            Requires the optional <code>cairosvg</code> package (<code>pip install -e &quot;.[export]&quot;</code>).</li>
        </ul>
        <p>
          In the diagram, the node word sits in the center with each collocate
          placed in a circle around it. Edge thickness is proportional to the
          association strength; node radius is proportional to raw frequency.
        </p>
        <h4>Methods PDF</h4>
        <p>
          The Keyness view has a <strong>Methods PDF</strong> button that auto-drafts
          a methodology paragraph naming the exact tools, model versions, and formulas
          used for your corpus. You can paste this directly into a manuscript&apos;s
          Methods section so peer reviewers can verify your workflow.
        </p>
      </>
    ),
  },
  {
    id: "corpus-hub",
    title: "Corpus Hub (download corpora)",
    icon: "\u25B6",
    body: (
      <>
        <p>
          The <strong>Corpus Hub</strong> (sidebar: File → Corpus Hub) lets you
          search and download open-access corpora in Arabic and English from
          three hubs:
        </p>
        <ul>
          <li><strong>HuggingFace Datasets</strong> — Wikipedia (Arabic + English),
            OSCAR, CC-100, Arabic Pile. Full-text search inside Wikipedia.</li>
          <li><strong>Wikipedia (live)</strong> — fetch fresh articles directly
            from Arabic or English Wikipedia. CC-BY-SA 3.0.</li>
          <li><strong>OPUS</strong> — 1,200+ parallel corpora (Arabic ↔ English
            translation pairs). Per-corpus licensing.</li>
        </ul>
        <h4>How to use it</h4>
        <ol>
          <li>Go to <strong>File → Corpus Hub</strong> in the sidebar.</li>
          <li>Type a search query (keyword or topic).</li>
          <li>Pick a language: English, Arabic, or Arabic-English (parallel).</li>
          <li>Optionally filter to a specific hub.</li>
          <li>Click <strong>Search</strong>.</li>
          <li>Review the results — each shows the hub, title, description,
            language, size, license, and format.</li>
          <li>Click <strong>Download</strong> on the result you want.</li>
          <li>The file downloads to your browser&apos;s default location.</li>
          <li>Go to <strong>Projects</strong>, create or open a corpus, and upload
            the downloaded file.</li>
        </ol>
        <p className="hint">
          Always check the license of each corpus before redistributing. Wikipedia
          is CC-BY-SA 3.0 (attribution required); OPUS corpora vary per source.
        </p>
        <h4>Privacy</h4>
        <p>
          Searches and downloads are proxied through the CorpusMind engine on your
          machine. Your existing corpus data is never sent to any hub — only search
          queries and the IDs of corpora you choose to download.
        </p>
      </>
    ),
  },
  {
    id: "reproducibility",
    title: "Reproducibility & Research Features",
    icon: "\u25B6",
    body: (
      <>
        <p>
          Every project pins the exact tokenizer, tagger, model, and formula versions used. The
          engine stores an annotation-version UUID alongside every parsed corpus, and the AI
          Assistant's audit trail records which model + provider + prompt template produced each
          turn.
        </p>
        <h4>Methods PDF export</h4>
        <p>
          The <strong>Export Methods PDF</strong> feature auto-drafts a methodology paragraph
          naming the exact tools, versions, and formulas used for a given analysis — including
          AI usage disclosure and human verification sections. You can paste this directly into
          a manuscript's Methods section so peer reviewers can verify your workflow.
        </p>
        <h4>Multi-format export</h4>
        <p>
          Every analysis view has an <strong>Export</strong> dropdown with five formats: Excel,
          CSV, TSV, Plain text, and JSON. The Collocation view also has an <strong>Export
          diagram</strong> dropdown for SVG (vector) and PNG (raster) collocation network
          diagrams.
        </p>
        <h4>Pre-publication check</h4>
        <p>
          In Settings, the Research &amp; Reproducibility card includes a pre-publication check
          that audits your corpus for: annotation version pinned, AI non-determinism flagged,
          pipeline recipe complete, and document count.
        </p>
        <h4>AI usage disclosure</h4>
        <p>
          The Research &amp; Reproducibility card generates a disclosure paragraph summarizing
          all AI usage for your project: providers, models, total turns, grounded/ungrounded
          counts, verified/rejected counts, and tools called. Include this in your Methods
          section for transparency.
        </p>
        <h4>Frequency list import/export</h4>
        <p>
          Export a frequency list as a portable <code>.lst</code> file (tab-separated) that can
          be shared even when the corpus can&apos;t be (copyright). Import a <code>.lst</code>
          file to use as a reference frequency list for keyness comparison.
        </p>
        <h4>Side-by-side concordance comparison</h4>
        <p>
          Run the same concordance query against two corpora (target + reference) and see the
          results side by side. Useful for contrastive analysis.
        </p>
        <h4>Student mode</h4>
        <p>
          Toggle Student Mode in Settings to hide the AI&apos;s interpretation until the student
          writes their own. The student then clicks &quot;Reveal AI answer&quot; to compare
          their interpretation with the AI&apos;s for learning.
        </p>
      </>
    ),
  },
  {
    id: "shortcuts",
    title: "Keyboard Shortcuts",
    icon: "\u25B6",
    body: (
      <>
        <table className="guide-shortcut-table">
          <thead>
            <tr><th>Shortcut</th><th>Action</th></tr>
          </thead>
          <tbody>
            <tr><td><kbd>Ctrl</kbd> / <kbd>Cmd</kbd> + <kbd>K</kbd></td><td>Open the Command Palette</td></tr>
            <tr><td><kbd>Esc</kbd></td><td>Close the Command Palette / any modal</td></tr>
            <tr><td><kbd>Tab</kbd></td><td>Navigate between focusable elements</td></tr>
            <tr><td><kbd>Enter</kbd> / <kbd>Space</kbd></td><td>Activate the focused button</td></tr>
          </tbody>
        </table>
        <p className="hint">
          The Command Palette is the fastest way to jump between views: press <kbd>Ctrl</kbd>+
          <kbd>K</kbd> and start typing the name of the view you want.
        </p>
      </>
    ),
  },
  {
    id: "citation",
    title: "Citation and License",
    icon: "\u25B6",
    body: (
      <>
        <h4>Citation</h4>
        <p>If you use CorpusMind in your research, please cite it as:</p>
        <pre>{`Mandour, W., & Ibrahim, W. (2026). CorpusMind: A local-first,
AI-native research environment for corpus linguistics and
multimodal discourse analysis (Version 0.1.10) [Computer
software]. Zenodo. https://doi.org/10.5281/zenodo.21226650`}</pre>
        <h4>License</h4>
        <p>
          CorpusMind is released under the <strong>GNU Affero General Public License v3.0</strong>
          (AGPL-3.0-only). See the <a href="https://github.com/waleedmandour/CorpusMind/blob/main/LICENSE">LICENSE</a> file
          for the full text. Third-party licenses are documented in
          <a href="https://github.com/waleedmandour/CorpusMind/blob/main/THIRD_PARTY_LICENSES.md">THIRD_PARTY_LICENSES.md</a>.
        </p>
        <h4>Links</h4>
        <ul>
          <li><a href="https://github.com/waleedmandour/CorpusMind">GitHub Repository</a></li>
          <li><a href="https://corpus-mind-web.vercel.app/">Live PWA on Vercel</a></li>
          <li><a href="https://github.com/waleedmandour/CorpusMind/releases">Releases</a></li>
          <li><a href="https://doi.org/10.5281/zenodo.21226650">Zenodo DOI</a></li>
        </ul>
      </>
    ),
  },
];

export function UserGuideView() {
  const [openId, setOpenId] = useState<string | null>("getting-started");

  return (
    <div className="userguide-view">
      <div className="userguide-header">
        <h1>User Guide</h1>
        <p className="userguide-subtitle">
          Everything you need to go from raw texts to publication-ready analysis.
        </p>
      </div>

      <div className="userguide-search-hint">
        Looking for something specific? Use <kbd>Ctrl</kbd>/<kbd>Cmd</kbd> + <kbd>K</kbd> to open
        the Command Palette, or expand a section below.
      </div>

      <div className="userguide-sections">
        {sections.map((section) => {
          const isOpen = openId === section.id;
          return (
            <section key={section.id} className={`guide-section ${isOpen ? "open" : ""}`}>
              <button
                className="guide-section-header"
                onClick={() => setOpenId(isOpen ? null : section.id)}
                aria-expanded={isOpen}
              >
                <span className="guide-section-icon" aria-hidden>{section.icon}</span>
                <span className="guide-section-title">{section.title}</span>
              </button>
              {isOpen && (
                <div className="guide-section-body">{section.body}</div>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
