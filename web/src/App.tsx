/**
 * App shell -- top bar + sidebar + main content + status bar.
 *
 * The old ribbon + top-tab system has been replaced with a cleaner
 * left sidebar for navigation. The top bar holds the brand, active
 * corpus indicator, theme toggle, RTL toggle, and command palette button.
 */
import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Sidebar } from "@/components/Sidebar";
import { CommandPalette } from "@/components/CommandPalette";
import { ThemeToggle } from "@/components/ThemeToggle";
import { OnboardingModal } from "@/components/OnboardingModal";
import { TroubleshootingBar } from "@/components/TroubleshootingBar";
import { HomeView } from "@/views/HomeView";
import { AboutView } from "@/views/AboutView";
import { AssistantView } from "@/views/AssistantView";
import { CorpusSelectionView } from "@/views/CorpusSelectionView";
import { ConcordancerView } from "@/views/ConcordancerView";
import { AnalysisView } from "@/views/AnalysisView";
import { ArabicView } from "@/views/ArabicView";
import { VisionView } from "@/views/VisionView";
import { SettingsView } from "@/views/SettingsView";
import { UserGuideView } from "@/views/UserGuideView";
import { applyHtmlAttrs, useUI } from "@/store/ui";
import { useApp } from "@/store/app";
import { useEngineVersionDisplay } from "@/hooks/useEngineVersion";

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
  const versionDisplay = useEngineVersionDisplay();

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
          <div className="app-active-corpus" title="Corpus is loaded and ready">
            <span className="dot" /> Corpus ready
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
          {activeNav === "corpus-target" && <CorpusSelectionView mode="target" />}
          {activeNav === "corpus-reference" && <CorpusSelectionView mode="reference" />}
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
          {activeNav === "userguide" && <UserGuideView />}
          {activeNav === "about" && <AboutView />}
        </main>
      </div>

      {/* Status bar */}
      <footer className="app-statusbar" role="contentinfo">
        <QueryStatusIndicator />
        <span className="status-sep">|</span>
        <span>CorpusMind {versionDisplay}</span>
        <span className="status-sep">|</span>
        <span>AGPL-3.0</span>
        <span className="status-sep">|</span>
        <span>Press Ctrl/Cmd+K for commands</span>
        <span className="status-sep">|</span>
        <span>Local Desktop App</span>
        <div className="statusbar-spacer" />
        <TroubleshootingBar />
      </footer>

      <CommandPalette />
      <OnboardingModal />
    </div>
  );
}

/** Shows the current React Query status (loading / idle / error) in the status bar. */
function QueryStatusIndicator() {
  const qc = useQueryClient();
  const queries = qc.getQueryCache().getAll();
  const fetching = queries.filter((q) => q.state.status === "pending");
  const errors = queries.filter((q) => q.state.status === "error");

  if (errors.length > 0) {
    return (
      <span className="status-error" title={`${errors.length} error(s)`}>
        {"\u26A0"} {errors.length} error{errors.length === 1 ? "" : "s"}
      </span>
    );
  }
  if (fetching.length > 0) {
    return (
      <span className="status-loading" title={`${fetching.length} active request(s)`}>
        <span className="status-spinner" /> {fetching.length} processing...
      </span>
    );
  }
  return <span className="status-idle">Ready</span>;
}
