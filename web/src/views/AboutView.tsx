/**
 * AboutView -- project info, authors, license, acknowledgements.
 *
 * v1.2.14-7 (r7): all visible strings now route through the i18n catalog,
 * so the page follows the active UI language. Author names, institutions,
 * bibliographic citations, and file/URL labels stay in their canonical form.
 */
import { useEngineVersion } from "@/hooks/useEngineVersion";
import { t } from "@/lib/i18n";
import { useUI } from "@/store/ui";

export function AboutView() {
  const version = useEngineVersion();
  const lang = useUI((s) => s.lang);
  const appName = "CorpusMind";
  return (
    <div className="about-view">
      <div className="about-hero">
        <img
          src="/icon-512.png"
          alt={appName}
          width="96"
          height="96"
          className="about-logo-img"
        />
        <h1>{appName}</h1>
        <p className="about-version">{t(lang, "about_version")} {version} | AGPL-3.0-only</p>
        <p className="about-tagline">{t(lang, "about_tagline")}</p>
      </div>

      <section className="about-section">
        <h2>{t(lang, "about_authors")}</h2>
        <ul className="about-authors">
          <li>
            <strong>Dr. Waleed Mandour</strong>
            <p>Sultan Qaboos University | ORCID: <a href="https://orcid.org/0000-0002-9262-5993">0000-0002-9262-5993</a></p>
            <p>{t(lang, "about_lead_arch")}</p>
          </li>
          <li>
            <strong>Prof. Wesam Ibrahim</strong>
            <p>Princess Nourah Bint Abdulrahman University | ORCID: <a href="https://orcid.org/0000-0003-0710-6038">0000-0003-0710-6038</a></p>
            <p>{t(lang, "about_applied")}</p>
          </li>
        </ul>
      </section>

      <section className="about-section">
        <h2>{t(lang, "about_citation")}</h2>
        <p>
          {t(lang, "about_cite_intro")}
        </p>
        <div style={{ background: "var(--bg-subtle)", padding: "var(--space-3)", borderRadius: "var(--radius-md)", fontSize: "14px", lineHeight: 1.6 }}>
          Mandour, W., &amp; Ibrahim, W. (2026). <em>CorpusMind: A local-first,
          AI-native research environment for corpus linguistics and multimodal
          discourse analysis</em> (Version {version}) [Computer software]. Zenodo.
          <a href="https://doi.org/10.5281/zenodo.21226649">https://doi.org/10.5281/zenodo.21226649</a>
        </div>
      </section>

      <section className="about-section">
        <h2>{t(lang, "about_ack")}</h2>
        <p>
          {t(lang, "about_ack_body")}
        </p>
      </section>

      <section className="about-section">
        <h2>{t(lang, "about_stack")}</h2>
        <div className="about-tech-grid">
          <div className="about-tech-card">
            <h3>{t(lang, "about_engine")}</h3>
            <p>Python 3.12, FastAPI, SQLAlchemy 2.0 (async), spaCy, CAMeL Tools, OpenCV, Pillow, scipy, openpyxl, reportlab</p>
          </div>
          <div className="about-tech-card">
            <h3>{t(lang, "about_web")}</h3>
            <p>React 18, Vite, TypeScript, TanStack Query, Zustand</p>
          </div>
          <div className="about-tech-card">
            <h3>{t(lang, "about_desktop")}</h3>
            <p>Tauri 2 (Rust), sidecar process supervision, cross-platform: Windows, Linux, macOS</p>
          </div>
          <div className="about-tech-card">
            <h3>{t(lang, "about_ai")}</h3>
            <p>ModelProvider abstraction: Ollama, LM Studio, Cloud (opt-in). Tool-calling agent with citation-enforced output. 25 registered tools.</p>
          </div>
        </div>
      </section>

      <section className="about-section">
        <h2>{t(lang, "about_key_numbers")}</h2>
        <div className="about-stats">
          <div className="about-stat"><span className="num">202</span><span className="label">{t(lang, "about_stat_tests")}</span></div>
          <div className="about-stat"><span className="num">25</span><span className="label">{t(lang, "about_stat_tools")}</span></div>
          <div className="about-stat"><span className="num">90+</span><span className="label">{t(lang, "about_stat_routes")}</span></div>
          <div className="about-stat"><span className="num">12</span><span className="label">{t(lang, "about_stat_frameworks")}</span></div>
          <div className="about-stat"><span className="num">20</span><span className="label">{t(lang, "about_stat_formulas")}</span></div>
          <div className="about-stat"><span className="num">8</span><span className="label">{t(lang, "about_stat_lenses")}</span></div>
        </div>
      </section>

      <section className="about-section">
        <h2>{t(lang, "about_license")}</h2>
        <p>
          {t(lang, "about_license_a")}{" "}
          <a href="https://github.com/waleedmandour/CorpusMind/blob/main/LICENSE">LICENSE</a>{" "}
          {t(lang, "about_license_b")}{" "}
          <a href="https://github.com/waleedmandour/CorpusMind/blob/main/THIRD_PARTY_LICENSES.md">THIRD_PARTY_LICENSES.md</a>.
        </p>
      </section>

      <section className="about-section">
        <h2>{t(lang, "about_thanks")}</h2>
        <p>
          {t(lang, "about_thanks_body")} {t(lang, "about_kwic_cite_lead")} Anthony, L. (2025). Concordancing
          with AI: Applications of word and sentence embeddings. <em>Applied
          Corpus Linguistics, 5</em>(3), 100164.
          <a href="https://doi.org/10.1016/j.acorp.2025.100164">doi.org/10.1016/j.acorp.2025.100164</a>.
        </p>
      </section>

      <section className="about-section">
        <h2>{t(lang, "about_links")}</h2>
        <div className="about-links">
          <a href="https://github.com/waleedmandour/CorpusMind" className="about-link">{t(lang, "about_link_repo")}</a>
          <a href="https://corpus-mind-web.vercel.app/" className="about-link">{t(lang, "about_link_web")}</a>
          <a href="https://github.com/waleedmandour/CorpusMind/releases" className="about-link">{t(lang, "about_link_releases")}</a>
          <a href="https://doi.org/10.5281/zenodo.21226649" className="about-link">{t(lang, "about_link_zenodo")}</a>
          <a href="https://github.com/waleedmandour/CorpusMind/blob/main/docs/USER_GUIDE.md" className="about-link">{t(lang, "about_link_guide")}</a>
          <a href="https://github.com/waleedmandour/CorpusMind/blob/main/docs/BUILD_GUIDE.md" className="about-link">{t(lang, "about_link_build")}</a>
          <a href="https://github.com/waleedmandour/CorpusMind/blob/main/docs/METHODOLOGY.md" className="about-link">{t(lang, "about_link_method")}</a>
        </div>
      </section>
    </div>
  );
}
