/**
 * App shell — ribbon + active view + command palette + status bar.
 */
import { useEffect } from "react";

import { Ribbon } from "@/components/Ribbon";
import { CommandPalette } from "@/components/CommandPalette";
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
  const activeTab = useUI((s) => s.activeTab);
  const theme = useUI((s) => s.theme);
  const activeCorpusId = useApp((s) => s.activeCorpusId);

  useEffect(() => {
    applyHtmlAttrs();
  }, [theme, useUI((s) => s.dir)]);

  return (
    <div className="app-shell">
      <a href="#main-content" className="skip-link">Skip to main content</a>
      <header className="app-titlebar">
        <div className="app-brand">
          <span className="app-logo" aria-hidden>◆</span>
          <span className="app-name">CorpusMind</span>
          <span className="app-tagline">local-first · AI-native · research-grade</span>
        </div>
        {activeCorpusId && (
          <div className="app-active-corpus" title={activeCorpusId}>
            <span className="dot" /> {activeCorpusId.slice(0, 8)}…
          </div>
        )}
      </header>

      <Ribbon />

      <main className="app-main" id="main-content" role="main">
        {activeTab === "assistant" && <AssistantView />}
        {activeTab === "text" && <TextSuiteRouter />}
        {activeTab === "arabic" && <ArabicView />}
        {activeTab === "vision" && <VisionView />}
        {activeTab === "settings" && <SettingsView />}
      </main>

      <footer className="app-statusbar" role="contentinfo">
        <span>Phase 6 · Collaboration + Polish</span>
        <span className="status-sep">·</span>
        <span>AGPL-3.0</span>
        <span className="status-sep">·</span>
        <span>Press Ctrl/Cmd+K for commands</span>
      </footer>

      <CommandPalette />
    </div>
  );
}

/** Routes within the Text suite tab: Manage / Concordance / Analyze. */
function TextSuiteRouter() {
  // Read a query-param-like state from the URL hash for sub-tab selection.
  // Phase 1 keeps this simple — a module-level variable.
  const sub = useTextSubTab();
  return (
    <div className="text-suite">
      <nav className="sub-tabs">
        <button className={sub.tab === "manage" ? "active" : ""} onClick={() => sub.setTab("manage")}>Manage</button>
        <button className={sub.tab === "concordance" ? "active" : ""} onClick={() => sub.setTab("concordance")}>Concordance</button>
        <button className={sub.tab === "analyze" ? "active" : ""} onClick={() => sub.setTab("analyze")}>Analyze</button>
      </nav>
      <div className="sub-content">
        {sub.tab === "manage" && <CorpusManagerView />}
        {sub.tab === "concordance" && <ConcordancerView />}
        {sub.tab === "analyze" && <AnalysisView />}
      </div>
    </div>
  );
}

// Simple module-level sub-tab state. Phase 2 will move this to the URL.
import { useState } from "react";
function useTextSubTab() {
  const [tab, setTab] = useState<"manage" | "concordance" | "analyze">("manage");
  return { tab, setTab };
}
