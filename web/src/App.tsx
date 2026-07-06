/**
 * App shell -- top bar + sidebar + main content + status bar.
 *
 * The old ribbon + top-tab system has been replaced with a cleaner
 * left sidebar for navigation. The top bar holds the brand, active
 * corpus indicator, theme toggle, RTL toggle, and command palette button.
 */
import { useEffect } from "react";

import { Sidebar } from "@/components/Sidebar";
import { CommandPalette } from "@/components/CommandPalette";
import { ThemeToggle } from "@/components/ThemeToggle";
import { OnboardingModal } from "@/components/OnboardingModal";
import { HomeView } from "@/views/HomeView";
import { AboutView } from "@/views/AboutView";
import { AssistantView } from "@/views/AssistantView";
import { CorpusManagerView } from "@/views/CorpusManagerView";
import { ConcordancerView } from "@/views/ConcordancerView";
import { AnalysisView } from "@/views/AnalysisView";
import { ArabicView } from "@/views/ArabicView";
import { VisionView } from "@/views/VisionView";
import { SettingsView } from "@/views/SettingsView";
import { applyHtmlAttrs, useUI } from "@/store/ui";
import { useApp } from "@/store/app";

export default function App() {
  const activeNav = useUI((s) => s.activeNav);
  const theme = useUI((s) => s.theme);
  const lang = useUI((s) => s.lang);
  const dir = useUI((s) => s.dir);
  const toggleLang = useUI((s) => s.toggleLang);
  const setCommandPaletteOpen = useUI((s) => s.setCommandPaletteOpen);
  const onboardingComplete = useUI((s) => s.onboardingComplete);
  const setOnboardingOpen = useUI((s) => s.setOnboardingOpen);
  const activeCorpusId = useApp((s) => s.activeCorpusId);

  useEffect(() => {
    applyHtmlAttrs();
  }, [theme, dir, lang]);

  useEffect(() => {
    if (!onboardingComplete) {
      setOnboardingOpen(true);
    }
  }, [onboardingComplete, setOnboardingOpen]);

  return (
    <div className="app-shell">
      <a href="#main-content" className="skip-link">Skip to main content</a>

      <header className="app-topbar" role="banner">
        <div className="app-brand">
          <img src="/icon-32.png" alt="CorpusMind" width="28" height="28" className="app-brand-icon" />
          <span className="app-name">CorpusMind</span>
        </div>
        {activeCorpusId && (
          <div className="app-active-corpus" title={activeCorpusId}>
            <span className="dot" /> Corpus: {activeCorpusId.slice(0, 8)}
          </div>
        )}
        <div className="app-topbar-actions">
          <button
            className="topbar-btn lang-btn"
            onClick={toggleLang}
            title={lang === "en" ? "التبديل إلى العربية" : "Switch to English"}
            aria-label="Switch language"
          >
            {lang === "en" ? "ع" : "EN"}
          </button>
          <button
            className="topbar-btn"
            onClick={() => setCommandPaletteOpen(true)}
            title="Command Palette (Ctrl/Cmd+K)"
            aria-label="Open command palette"
          >
            {"\u2318"}
          </button>
          <ThemeToggle />
        </div>
      </header>

      {/* Sidebar + main content */}
      <div className="app-body">
        <Sidebar />
        <main className="app-main" id="main-content" role="main">
          {activeNav === "home" && <HomeView />}
          {activeNav === "file" && <CorpusManagerView />}
          {activeNav === "concordance" && <ConcordancerView />}
          {activeNav === "frequency" && <AnalysisView />}
          {activeNav === "collocation" && <AnalysisView />}
          {activeNav === "keyness" && <AnalysisView />}
          {activeNav === "dispersion" && <AnalysisView />}
          {activeNav === "ngrams" && <AnalysisView />}
          {activeNav === "pos" && <AnalysisView />}
          {activeNav === "grammar" && <AnalysisView />}
          {activeNav === "dependency" && <AnalysisView />}
          {activeNav === "discourse" && <AnalysisView />}
          {activeNav === "vocab" && <AnalysisView />}
          {activeNav === "sentiment" && <AnalysisView />}
          {activeNav === "metaphor" && <AnalysisView />}
          {activeNav === "arabic" && <ArabicView />}
          {activeNav === "vision" && <VisionView />}
          {activeNav === "assistant" && <AssistantView />}
          {activeNav === "settings" && <SettingsView />}
          {activeNav === "about" && <AboutView />}
        </main>
      </div>

      {/* Status bar */}
      <footer className="app-statusbar" role="contentinfo">
        <span>CorpusMind v0.7.0</span>
        <span className="status-sep">|</span>
        <span>AGPL-3.0</span>
        <span className="status-sep">|</span>
        <span>Press Ctrl/Cmd+K for commands</span>
        <span className="status-sep">|</span>
        <a href="https://corpus-mind-web.vercel.app/" style={{ color: "inherit" }}>Live PWA</a>
      </footer>

      <CommandPalette />
      <OnboardingModal />
    </div>
  );
}
