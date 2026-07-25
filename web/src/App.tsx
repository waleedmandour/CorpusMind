/**
 * App shell -- top bar + sidebar + main content + status bar.
 *
 * The old ribbon + top-tab system has been replaced with a cleaner
 * left sidebar for navigation. The top bar holds the brand, active
 * corpus indicator, theme toggle, RTL toggle, and command palette button.
 */
import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { api, waitForEngine } from "@/lib/api";
import { useDownloadProgress } from "@/store/downloadProgress";
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

  // Task 1: Wait for the engine to be ready BEFORE validating the persisted
  // corpus ID. Previously, the frontend fired api.getCorpus() immediately on
  // mount, before the engine was accepting connections — causing a "UNKNOWN"
  // error and clearing the persisted corpus ID even though it still existed.
  const clearActiveCorpus = useApp((s) => s.setActiveCorpus);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      // Wait for engine to be ready (up to 15 seconds)
      const ready = await waitForEngine(30);
      if (cancelled || !ready) return;
      // Now safe to validate the persisted corpus ID
      if (activeCorpusId) {
        api.getCorpus(activeCorpusId).catch(() => {
          if (!cancelled) clearActiveCorpus(null);
        });
      }
    })();
    return () => { cancelled = true; };
  }, []); // Run only once on mount

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
        <DownloadProgressBar />
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

/** Shows a download progress bar in the status bar when a reference corpus is being downloaded. */
function DownloadProgressBar() {
  const { activeDownload, clearDownloadProgress } = useDownloadProgress();
  if (!activeDownload) return null;

  const isDone = activeDownload.status === "installed" || activeDownload.status === "failed";
  const color = activeDownload.status === "failed" ? "var(--danger)"
    : activeDownload.status === "installed" ? "var(--success)"
    : "var(--brand-500)";

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: "6px",
      padding: "0 8px", fontSize: "11px", color: "var(--text-muted)",
    }}>
      <span style={{ fontWeight: 600, color }}>{activeDownload.status === "installed" ? "✓" : activeDownload.status === "failed" ? "✗" : "⏳"}</span>
      <span>{activeDownload.displayName}</span>
      {!isDone && (
        <div style={{
          width: "80px", height: "6px",
          background: "var(--bg-subtle)", borderRadius: "3px", overflow: "hidden",
        }}>
          <div style={{
            width: `${activeDownload.progress}%`, height: "100%",
            background: color, transition: "width 0.3s ease",
          }} />
        </div>
      )}
      <span style={{ fontSize: "10px" }}>{activeDownload.message}</span>
      {isDone && (
        <button
          onClick={clearDownloadProgress}
          style={{ background: "none", border: "none", color: "var(--text-subtle)", cursor: "pointer", fontSize: "11px" }}
          title="Dismiss"
        >✕</button>
      )}
    </div>
  );
}
