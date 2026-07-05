/**
 * App shell — ribbon + active view + command palette + status bar.
 *
 * The shell is deliberately simple in Phase 0; every later feature has a home
 * to land in without restructuring the app.
 */
import { useEffect } from "react";

import { Ribbon } from "@/components/Ribbon";
import { CommandPalette } from "@/components/CommandPalette";
import { AssistantView } from "@/views/AssistantView";
import { TextView } from "@/views/TextView";
import { VisionView } from "@/views/VisionView";
import { SettingsView } from "@/views/SettingsView";
import { applyHtmlAttrs, useUI } from "@/store/ui";

export default function App() {
  const activeTab = useUI((s) => s.activeTab);
  const theme = useUI((s) => s.theme);

  // Re-apply html attributes whenever theme/dir changes
  useEffect(() => {
    applyHtmlAttrs();
  }, [theme, useUI((s) => s.dir)]);

  return (
    <div className="app-shell">
      <header className="app-titlebar">
        <div className="app-brand">
          <span className="app-logo" aria-hidden>◆</span>
          <span className="app-name">CorpusMind</span>
          <span className="app-tagline">local-first · AI-native · research-grade</span>
        </div>
      </header>

      <Ribbon />

      <main className="app-main">
        {activeTab === "assistant" && <AssistantView />}
        {activeTab === "text" && <TextView />}
        {activeTab === "vision" && <VisionView />}
        {activeTab === "settings" && <SettingsView />}
      </main>

      <footer className="app-statusbar">
        <span>Phase 0 · Foundations</span>
        <span className="status-sep">·</span>
        <span>AGPL-3.0</span>
        <span className="status-sep">·</span>
        <span>Press Ctrl/Cmd+K for commands</span>
      </footer>

      <CommandPalette />
    </div>
  );
}
