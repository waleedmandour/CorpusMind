/**
 * OnboardingModal -- welcome guide shown on first launch.
 *
 * Main app (v1.2.0): 4 pages — Welcome, Steps, Privacy, Companions.
 *   - Fully i18n (onb_main_* keys; the pages were hardcoded English before,
 *     which broke en/ar parity).
 *   - Companion-first: page 4 presents CorpusMind Lens (vision) and
 *     CorpusMind Voice (audio-to-corpus) with links to their pages on
 *     waleedmandour.org, reusing AboutView's external-link mechanism
 *     (plain <a href> anchors — the Tauri webview hands them to the OS).
 *   - Feature card B "Vision Suite" became "Companion Apps" (the vision
 *     workbench itself lives in the Lens companion since v1.2.0).
 *   - Step 1 stale copy fixed: it said "Click Projects in the sidebar" but
 *     no such nav item exists — now "Open Corpus and upload texts".
 * Lens shell: unchanged 3-page i18n flow (onb_lens_*).
 *
 * Shown when onboardingComplete is false. Can be re-opened from Settings.
 */
import { useState } from "react";
import { useUI } from "@/store/ui";
import { t } from "@/lib/i18n";
import clsx from "clsx";

/** Companion app links (waleedmandour.org) — opened via plain anchors,
 * the same mechanism AboutView uses for its external links. */
const LENS_URL = "https://waleedmandour.org/projects/CorpusMindLens/";
const VOICE_URL = "https://waleedmandour.org/projects/CorpusMindVoice/";

export function OnboardingModal() {
  const onboardingOpen = useUI((s) => s.onboardingOpen);
  const onboardingComplete = useUI((s) => s.onboardingComplete);
  const setOnboardingOpen = useUI((s) => s.setOnboardingOpen);
  const setOnboardingComplete = useUI((s) => s.setOnboardingComplete);
  const isLensMode = useUI((s) => s.isLensMode);
  const lang = useUI((s) => s.lang);
  const [page, setPage] = useState(0);

  if (!onboardingOpen && onboardingComplete) return null;

  // v1.2.0: main-app pages are i18n-driven (onb_main_*) and companion-first.
  const mainAppPages = [
    {
      title: t(lang, "onb_main_w_title"),
      subtitle: t(lang, "onb_main_w_sub"),
      content: (
        <div className="onboarding-content">
          <p>{t(lang, "onb_main_w_intro")}</p>
          <div className="onboarding-features">
            <div className="onboarding-feature">
              <div className="feature-badge">A</div>
              <div>
                <strong>{t(lang, "onb_main_f1_t")}</strong>
                <p>{t(lang, "onb_main_f1_d")}</p>
              </div>
            </div>
            <div className="onboarding-feature">
              <div className="feature-badge">B</div>
              <div>
                <strong>{t(lang, "onb_main_f2_t")}</strong>
                <p>{t(lang, "onb_main_f2_d")}</p>
              </div>
            </div>
            <div className="onboarding-feature">
              <div className="feature-badge">C</div>
              <div>
                <strong>{t(lang, "onb_main_f3_t")}</strong>
                <p>{t(lang, "onb_main_f3_d")}</p>
              </div>
            </div>
            <div className="onboarding-feature">
              <div className="feature-badge">D</div>
              <div>
                <strong>{t(lang, "onb_main_f4_t")}</strong>
                <p>{t(lang, "onb_main_f4_d")}</p>
              </div>
            </div>
          </div>
        </div>
      ),
    },
    {
      title: t(lang, "onb_main_s_title"),
      subtitle: t(lang, "onb_main_s_sub"),
      content: (
        <div className="onboarding-content">
          <div className="onboarding-steps">
            <div className="onboarding-step">
              <div className="step-number">1</div>
              <div className="step-body">
                <strong>{t(lang, "onb_main_s1_t")}</strong>
                <p>{t(lang, "onb_main_s1_d")}</p>
              </div>
            </div>
            <div className="onboarding-step">
              <div className="step-number">2</div>
              <div className="step-body">
                <strong>{t(lang, "onb_main_s2_t")}</strong>
                <p>{t(lang, "onb_main_s2_d")}</p>
              </div>
            </div>
            <div className="onboarding-step">
              <div className="step-number">3</div>
              <div className="step-body">
                <strong>{t(lang, "onb_main_s3_t")}</strong>
                <p>{t(lang, "onb_main_s3_d")}</p>
              </div>
            </div>
          </div>
          <div className="onboarding-tip">
            <strong>Tip:</strong> Press <kbd>Ctrl</kbd>+<kbd>K</kbd> (or <kbd>Cmd</kbd>+<kbd>K</kbd>) to open the command palette and jump to any action.
          </div>
        </div>
      ),
    },
    {
      title: t(lang, "onb_main_p_title"),
      subtitle: t(lang, "onb_main_p_sub"),
      content: (
        <div className="onboarding-content">
          <div className="onboarding-privacy">
            <div className="privacy-item">
              <div className="privacy-check-mark">Yes</div>
              <div>
                <strong>{t(lang, "onb_main_p1_t")}</strong>
                <p>{t(lang, "onb_main_p1_d")}</p>
              </div>
            </div>
            <div className="privacy-item">
              <div className="privacy-check-mark">Yes</div>
              <div>
                <strong>{t(lang, "onb_main_p2_t")}</strong>
                <p>{t(lang, "onb_main_p2_d")}</p>
              </div>
            </div>
            <div className="privacy-item">
              <div className="privacy-check-mark">Yes</div>
              <div>
                <strong>{t(lang, "onb_main_p3_t")}</strong>
                <p>{t(lang, "onb_main_p3_d")}</p>
              </div>
            </div>
            <div className="privacy-item">
              <div className="privacy-check-mark">Yes</div>
              <div>
                <strong>{t(lang, "onb_main_p4_t")}</strong>
                <p>{t(lang, "onb_main_p4_d")}</p>
              </div>
            </div>
          </div>
          <div className="onboarding-cta">
            <p>{t(lang, "onb_main_cta") ?? "Ready to start? Create your first project and upload some texts."}</p>
          </div>
        </div>
      ),
    },
    {
      // v1.2.0: the companion-first page — Lens + Voice, opened in the
      // system browser (AboutView's plain-anchor mechanism).
      title: t(lang, "onb_main_c4_title"),
      subtitle: t(lang, "onb_main_c4_sub"),
      content: (
        <div className="onboarding-content">
          <div className="onboarding-features">
            <div className="onboarding-feature">
              <div className="feature-badge">1</div>
              <div>
                <strong>{t(lang, "onb_main_comp1_t")}</strong>
                <p>{t(lang, "onb_main_comp1_d")}</p>
                <a href={LENS_URL} className="about-link onboarding-companion-link">
                  {t(lang, "onb_main_comp1_open")} ↗
                </a>
              </div>
            </div>
            <div className="onboarding-feature">
              <div className="feature-badge">2</div>
              <div>
                <strong>{t(lang, "onb_main_comp2_t")}</strong>
                <p>{t(lang, "onb_main_comp2_d")}</p>
                <a href={VOICE_URL} className="about-link onboarding-companion-link">
                  {t(lang, "onb_main_comp2_open")} ↗
                </a>
              </div>
            </div>
          </div>
          <p className="hint onboarding-companions-hint">{t(lang, "onb_main_companions_hint")}</p>
        </div>
      ),
    },
  ];

  // v1.2.0 — CorpusMind Lens onboarding: mirrors what the Lens sidebar
  // actually contains (no Projects / analysis-tool steps).
  // v1.0.9: the Lens pages were previously hardcoded English — the only
  // Lens surface that broke the app's en/ar parity. All strings now come
  // from i18n (onb_lens_* keys) and describe the v1.0.9 Image Corpora
  // workflow.
  const lensPages = [
    {
      title: t(lang, "onb_lens_w_title"),
      subtitle: t(lang, "onb_lens_w_sub"),
      content: (
        <div className="onboarding-content">
          <p>{t(lang, "onb_lens_w_intro")}</p>
          <div className="onboarding-features">
            <div className="onboarding-feature">
              <div className="feature-badge">1</div>
              <div>
                <strong>{t(lang, "onb_lens_f1_t")}</strong>
                <p>{t(lang, "onb_lens_f1_d")}</p>
              </div>
            </div>
            <div className="onboarding-feature">
              <div className="feature-badge">2</div>
              <div>
                <strong>{t(lang, "onb_lens_f2_t")}</strong>
                <p>{t(lang, "onb_lens_f2_d")}</p>
              </div>
            </div>
            <div className="onboarding-feature">
              <div className="feature-badge">3</div>
              <div>
                <strong>{t(lang, "onb_lens_f3_t")}</strong>
                <p>{t(lang, "onb_lens_f3_d")}</p>
              </div>
            </div>
          </div>
        </div>
      ),
    },
    {
      title: t(lang, "onb_lens_s_title"),
      subtitle: t(lang, "onb_lens_s_sub"),
      content: (
        <div className="onboarding-content">
          <div className="onboarding-steps">
            <div className="onboarding-step">
              <div className="step-number">1</div>
              <div className="step-body">
                <strong>{t(lang, "onb_lens_s1_t")}</strong>
                <p>{t(lang, "onb_lens_s1_d")}</p>
              </div>
            </div>
            <div className="onboarding-step">
              <div className="step-number">2</div>
              <div className="step-body">
                <strong>{t(lang, "onb_lens_s2_t")}</strong>
                <p>{t(lang, "onb_lens_s2_d")}</p>
              </div>
            </div>
            <div className="onboarding-step">
              <div className="step-number">3</div>
              <div className="step-body">
                <strong>{t(lang, "onb_lens_s3_t")}</strong>
                <p>{t(lang, "onb_lens_s3_d")}</p>
              </div>
            </div>
          </div>
          <div className="onboarding-tip">
            <strong>{t(lang, "onb_lens_tip")}</strong>
          </div>
        </div>
      ),
    },
    {
      title: t(lang, "onb_lens_p_title"),
      subtitle: t(lang, "onb_lens_p_sub"),
      content: (
        <div className="onboarding-content">
          <div className="onboarding-privacy">
            <div className="privacy-item">
              <div className="privacy-check-mark">Yes</div>
              <div>
                <strong>{t(lang, "onb_lens_p1_t")}</strong>
                <p>{t(lang, "onb_lens_p1_d")}</p>
              </div>
            </div>
            <div className="privacy-item">
              <div className="privacy-check-mark">Yes</div>
              <div>
                <strong>{t(lang, "onb_lens_p2_t")}</strong>
                <p>{t(lang, "onb_lens_p2_d")}</p>
              </div>
            </div>
            <div className="privacy-item">
              <div className="privacy-check-mark">Yes</div>
              <div>
                <strong>{t(lang, "onb_lens_p3_t")}</strong>
                <p>{t(lang, "onb_lens_p3_d")}</p>
              </div>
            </div>
            <div className="privacy-item">
              <div className="privacy-check-mark">Yes</div>
              <div>
                <strong>{t(lang, "onb_lens_p4_t")}</strong>
                <p>{t(lang, "onb_lens_p4_d")}</p>
              </div>
            </div>
          </div>
          <div className="onboarding-cta">
            <p>{t(lang, "onb_lens_cta")}</p>
          </div>
        </div>
      ),
    },
  ];

  const pages = isLensMode ? lensPages : mainAppPages;

  const currentPage = pages[page];
  const isLast = page === pages.length - 1;

  const handleClose = () => {
    setOnboardingComplete(true);
    setOnboardingOpen(false);
  };

  const handleNext = () => {
    if (isLast) {
      handleClose();
    } else {
      setPage(page + 1);
    }
  };

  const handlePrev = () => {
    if (page > 0) setPage(page - 1);
  };

  return (
    <div className="onboarding-backdrop" onClick={handleClose}>
      <div className="onboarding-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="onboarding-title">
        <div className="onboarding-header">
          <div>
            <h2 id="onboarding-title">{currentPage.title}</h2>
            <p className="onboarding-subtitle">{currentPage.subtitle}</p>
          </div>
        </div>
        <div className="onboarding-body">
          {currentPage.content}
        </div>
        <div className="onboarding-footer">
          <div className="onboarding-dots">
            {pages.map((_, i) => (
              <span key={i} className={clsx("onboarding-dot", { active: i === page })} />
            ))}
          </div>
          <div className="onboarding-actions">
            {page > 0 && (
              <button className="onboarding-btn-secondary" onClick={handlePrev}>{t(lang, "onb_back")}</button>
            )}
            <button className="onboarding-btn-skip" onClick={handleClose}>{t(lang, "onb_skip")}</button>
            <button className="onboarding-btn-primary" onClick={handleNext}>
              {isLast ? t(lang, "onb_start") : t(lang, "onb_next")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
