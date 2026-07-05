/**
 * OnboardingModal -- 3-page welcome guide shown on first launch.
 *
 * Page 1: Welcome + what CorpusMind is
 * Page 2: How to get started (create project, upload, analyze)
 * Page 3: Privacy + AI Assistant explanation
 *
 * Shown when onboardingComplete is false. Can be re-opened from Settings.
 */
import { useState } from "react";
import { useUI } from "@/store/ui";
import clsx from "clsx";

export function OnboardingModal() {
  const onboardingOpen = useUI((s) => s.onboardingOpen);
  const onboardingComplete = useUI((s) => s.onboardingComplete);
  const setOnboardingOpen = useUI((s) => s.setOnboardingOpen);
  const setOnboardingComplete = useUI((s) => s.setOnboardingComplete);
  const [page, setPage] = useState(0);

  // Show if explicitly open OR if first launch (not yet completed)
  if (!onboardingOpen && onboardingComplete) return null;

  const pages = [
    {
      icon: "\u25C6",
      title: "Welcome to CorpusMind",
      subtitle: "Local-first, AI-native research environment for corpus linguistics and multimodal discourse analysis.",
      content: (
        <div className="onboarding-content">
          <p>CorpusMind lets you go from raw texts and images to publication-ready analysis without writing a line of code.</p>
          <div className="onboarding-features">
            <div className="onboarding-feature">
              <span className="feature-icon">\u2630</span>
              <div>
                <strong>Corpus Analysis</strong>
                <p>Concordance, frequency, collocation, keyness, n-grams, dispersion, and more.</p>
              </div>
            </div>
            <div className="onboarding-feature">
              <span className="feature-icon">\u2728</span>
              <div>
                <strong>Vision Suite</strong>
                <p>Image analysis, Visual Grammar (Kress and van Leeuwen), multimodal alignment.</p>
              </div>
            </div>
            <div className="onboarding-feature">
              <span className="feature-icon">\u272A</span>
              <div>
                <strong>Arabic First-Class</strong>
                <p>CAMeL Tools morphology, dialect ID, root extraction, bilingual alignment.</p>
              </div>
            </div>
            <div className="onboarding-feature">
              <span className="feature-icon">\u2691</span>
              <div>
                <strong>Grounded AI</strong>
                <p>Every AI answer cites real evidence. No hallucination passes as fact.</p>
              </div>
            </div>
          </div>
        </div>
      ),
    },
    {
      icon: "\u25B6",
      title: "Getting Started in 3 Steps",
      subtitle: "From zero to analysis in minutes.",
      content: (
        <div className="onboarding-content">
          <div className="onboarding-steps">
            <div className="onboarding-step">
              <div className="step-number">1</div>
              <div className="step-body">
                <strong>Create a Project and Upload Texts</strong>
                <p>Click the <strong>Text Suite</strong> tab, then <strong>Manage</strong>. Click "+ New" to create a project, then a corpus. Drag and drop your text files (TXT, DOCX, PDF, HTML, XML, CSV, Markdown). The engine automatically tokenizes, tags, and parses them.</p>
              </div>
            </div>
            <div className="onboarding-step">
              <div className="step-number">2</div>
              <div className="step-body">
                <strong>Run Analysis</strong>
                <p>Click <strong>Concordance</strong> to search (KWIC), or <strong>Analyze</strong> for frequency, collocation, keyness, dispersion, n-grams, POS, grammar, discourse, vocabulary, sentiment, and metaphor. Every result includes its parameters for reproducibility.</p>
              </div>
            </div>
            <div className="onboarding-step">
              <div className="step-number">3</div>
              <div className="step-body">
                <strong>Ask the AI Assistant</strong>
                <p>Click the <strong>AI Assistant</strong> tab. Ask questions in natural language. Every answer is either <span className="badge-grounded">grounded</span> (backed by a tool call with cited evidence) or <span className="badge-unground">ungrounded</span> (clearly flagged). Start Ollama locally for fully offline AI.</p>
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
      icon: "\u272A",
      title: "Privacy and Ethics by Design",
      subtitle: "Your data stays on your machine. Always.",
      content: (
        <div className="onboarding-content">
          <div className="onboarding-privacy">
            <div className="privacy-item">
              <span className="privacy-check">\u2713</span>
              <div>
                <strong>Local-first by default.</strong>
                <p>Your corpus text, images, and AI queries never leave your machine unless you explicitly opt in to a cloud provider.</p>
              </div>
            </div>
            <div className="privacy-item">
              <span className="privacy-check">\u2713</span>
              <div>
                <strong>No telemetry.</strong>
                <p>Zero analytics, zero error reporting, zero phone-home. By design.</p>
              </div>
            </div>
            <div className="privacy-item">
              <span className="privacy-check">\u2713</span>
              <div>
                <strong>Framework-lensed hypotheses.</strong>
                <p>Every interpretive claim (CDA, power, ideology) is phrased as "Under a [Framework] reading, X may indicate Y." Never as a bare assertion of fact.</p>
              </div>
            </div>
            <div className="privacy-item">
              <span className="privacy-check">\u2713</span>
              <div>
                <strong>Facial analysis is opt-in.</strong>
                <p>Off by default. Never performs identity recognition or re-identification of real individuals.</p>
              </div>
            </div>
          </div>
          <div className="onboarding-cta">
            <p>Ready to start? Create your first project and upload some texts.</p>
          </div>
        </div>
      ),
    },
  ];

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
          <span className="onboarding-icon" aria-hidden>{currentPage.icon}</span>
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
              <button className="onboarding-btn-secondary" onClick={handlePrev}>Back</button>
            )}
            <button className="onboarding-btn-skip" onClick={handleClose}>Skip</button>
            <button className="onboarding-btn-primary" onClick={handleNext}>
              {isLast ? "Get Started" : "Next"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
