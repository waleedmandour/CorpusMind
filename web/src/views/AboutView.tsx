/**
 * AboutView -- project info, authors, license, acknowledgements.
 */
export function AboutView() {
  return (
    <div className="about-view">
      <div className="about-hero">
        <span className="about-logo" aria-hidden>{"\u25C6"}</span>
        <h1>CorpusMind</h1>
        <p className="about-version">Version 0.7.0 Pre-Release | AGPL-3.0-only</p>
        <p className="about-tagline">
          Local-first, AI-native research environment for corpus linguistics
          and multimodal discourse analysis.
        </p>
      </div>

      <section className="about-section">
        <h2>Authors</h2>
        <ul className="about-authors">
          <li>
            <strong>Dr. Waleed Mandour</strong>
            <p>Sultan Qaboos University | ORCID: <a href="https://orcid.org/0000-0002-9262-5993">0000-0002-9262-5993</a></p>
            <p>Lead architect and full-stack engineer</p>
          </li>
          <li>
            <strong>Prof. Wessam Ibrahim</strong>
            <p>ORCID: <a href="https://orcid.org/0000-0003-0710-6038">0000-0003-0710-6038</a></p>
            <p>Co-author, corpus linguistics and discourse analysis methodology</p>
          </li>
        </ul>
      </section>

      <section className="about-section">
        <h2>Citation</h2>
        <p>
          If you use CorpusMind in your research, please cite it as:
        </p>
        <div style={{ background: "var(--bg-subtle)", padding: "var(--space-3)", borderRadius: "var(--radius-md)", fontSize: "13px", lineHeight: 1.6 }}>
          Mandour, W., &amp; Ibrahim, W. (2026). <em>CorpusMind: A local-first,
          AI-native research environment for corpus linguistics and multimodal
          discourse analysis</em> (Version 0.7.0) [Computer software]. Zenodo.
          https://doi.org/10.5281/zenodo.(DOI upon registration)
        </div>
      </section>

      <section className="about-section">
        <h2>Development Acknowledgement</h2>
        <p>
          The development of CorpusMind was assisted by an AI agent (Super Z,
          built on the GLM model by Z.ai) which served as a full-stack
          engineering collaborator across all six phases of the build:
          scaffolding the monorepo, implementing the FastAPI engine, the React
          PWA, the Tauri 2 desktop shell, the grounded-AI tool surface, the
          Arabic NLP pipeline (CAMeL Tools integration), the vision suite
          (image analysis, Visual Grammar, multimodal alignment), the
          multimodal discourse analyses, and the collaboration/accessibility/
          encryption features. All AI-generated code was reviewed, tested,
          and committed by the human authors.
        </p>
      </section>

      <section className="about-section">
        <h2>Technology Stack</h2>
        <div className="about-tech-grid">
          <div className="about-tech-card">
            <h3>Engine</h3>
            <p>Python 3.12, FastAPI, SQLAlchemy 2.0 (async), spaCy, CAMeL Tools, OpenCV, Pillow, scipy, statsmodels, openpyxl, reportlab</p>
          </div>
          <div className="about-tech-card">
            <h3>Web Frontend</h3>
            <p>React 18, Vite, TypeScript, TanStack Query, Zustand, vite-plugin-pwa</p>
          </div>
          <div className="about-tech-card">
            <h3>Desktop Shell</h3>
            <p>Tauri 2 (Rust), sidecar process supervision, cross-platform: Windows, Linux, macOS</p>
          </div>
          <div className="about-tech-card">
            <h3>AI Layer</h3>
            <p>ModelProvider abstraction: Ollama, LM Studio, Cloud (opt-in). Tool-calling agent with citation-enforced output. 25 registered tools.</p>
          </div>
        </div>
      </section>

      <section className="about-section">
        <h2>Key Numbers</h2>
        <div className="about-stats">
          <div className="about-stat"><span className="num">97</span><span className="label">Tests Passing</span></div>
          <div className="about-stat"><span className="num">25</span><span className="label">Grounded-AI Tools</span></div>
          <div className="about-stat"><span className="num">85</span><span className="label">API Routes</span></div>
          <div className="about-stat"><span className="num">12</span><span className="label">Framework Templates</span></div>
          <div className="about-stat"><span className="num">20</span><span className="label">Statistical Formulas</span></div>
          <div className="about-stat"><span className="num">163</span><span className="label">Source Files</span></div>
        </div>
      </section>

      <section className="about-section">
        <h2>License</h2>
        <p>
          CorpusMind is released under the <strong>GNU Affero General Public
          License v3.0</strong> (AGPL-3.0-only). See the
          <a href="https://github.com/waleedmandour/CorpusMind/blob/main/LICENSE">LICENSE</a> file
          for the full text. Third-party licenses are documented in
          <a href="https://github.com/waleedmandour/CorpusMind/blob/main/THIRD_PARTY_LICENSES.md">THIRD_PARTY_LICENSES.md</a>.
        </p>
      </section>

      <section className="about-section">
        <h2>Acknowledgements</h2>
        <p>
          CorpusMind stands on the shoulders of a substantial open-source
          ecosystem, including (but not limited to) spaCy, Stanza, Trankit,
          CAMeL Tools, SinaTools, Farasa, Camelira, CamelParser2.0, FastAPI,
          Tauri, React, Ollama, and LM Studio. The methodology draws on the
          corpus-linguistics and multimodal-discourse literature cited inline
          throughout the specification: Kress and van Leeuwen, Halliday,
          Fairclough, van Dijk, Wodak, Machin and Mayr, Barthes, Peirce,
          Lakoff and Johnson, Martin and White, Toulmin, Aristotle, Hyland,
          Biber, Gabrielatos and Marchi, Hardie, Kilgarriff, Church and Hanks,
          Dunning, Rychly, Gries, and Juilland.
        </p>
      </section>

      <section className="about-section">
        <h2>Links</h2>
        <div className="about-links">
          <a href="https://github.com/waleedmandour/CorpusMind" className="about-link">GitHub Repository</a>
          <a href="https://corpus-mind-web.vercel.app/" className="about-link">Live PWA on Vercel</a>
          <a href="https://github.com/waleedmandour/CorpusMind/releases/tag/v0.7.0-pre" className="about-link">Pre-Release Page</a>
          <a href="https://github.com/waleedmandour/CorpusMind/blob/main/docs/USER_GUIDE.md" className="about-link">User Guide</a>
          <a href="https://github.com/waleedmandour/CorpusMind/blob/main/docs/BUILD_GUIDE.md" className="about-link">Build Guide</a>
          <a href="https://github.com/waleedmandour/CorpusMind/blob/main/docs/METHODOLOGY.md" className="about-link">Methodology Reference</a>
        </div>
      </section>
    </div>
  );
}
