/**
 * HomeView -- landing dashboard shown when the app starts.
 *
 * Shows quick-access cards for the most common actions, the active corpus
 * summary, and a welcome message.
 *
 * STATUS SOURCE OF TRUTH (2026-07 fix):
 *   Inside the Tauri desktop app, provider health comes from the Rust-side
 *   `all_providers_health` command (via nativeProvidersHealth()). This is
 *   the single source of truth — no more dual fetch/native logic. In
 *   browser/PWA mode, we fall back to the engine's /api/v1/providers endpoint.
 */
import { useQuery } from "@tanstack/react-query";
import { useUI } from "@/store/ui";
import { useApp } from "@/store/app";
import { api, isTauriRuntime, nativeProvidersHealth } from "@/lib/api";

export function HomeView() {
  const setActiveNav = useUI((s) => s.setActiveNav);
  const activeProjectId = useApp((s) => s.activeProjectId);
  const activeCorpusId = useApp((s) => s.activeCorpusId);

  const isTauri = isTauriRuntime();

  // Native (Rust-side) provider health — the authoritative source of truth
  // inside the Tauri desktop app. Polled every 5s.
  const nativeHealth = useQuery({
    queryKey: ["native-providers-health"],
    queryFn: nativeProvidersHealth,
    refetchInterval: 5_000,
    enabled: isTauri,
  });

  // Engine-side health + providers — used as the fallback in browser/PWA mode
  // (where nativeHealth is null) and for the version info.
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, retry: 1 });
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers, retry: 1 });

  // Final status: native health wins in Tauri; engine endpoint in browser.
  const engineOk = isTauri
    ? (nativeHealth.data?.engine.healthy ?? false)
    : (health.data?.status === "ok");
  const ollamaOk = isTauri
    ? (nativeHealth.data?.ollama.healthy ?? false)
    : (providers.data?.providers.find((p) => p.name === "ollama")?.healthy ?? false);

  const quickActions = [
    { label: "Create Project", nav: "corpus-target" as const, icon: "\u2630", desc: "Set up a new research project and upload texts" },
    { label: "Concordance Search", nav: "concordance" as const, icon: "\u2727", desc: "Search your corpus with KWIC view" },
    { label: "Frequency Analysis", nav: "frequency" as const, icon: "\u2727", desc: "Word, lemma, and POS frequency with STTR" },
    { label: "Collocation", nav: "collocation" as const, icon: "\u2727", desc: "All 7 measures: MI, T-score, LL, Dice, LogDice, chi-square, Delta P" },
    { label: "Keyness", nav: "keyness" as const, icon: "\u2727", desc: "Compare target vs reference corpus" },
    { label: "AI Assistant", nav: "assistant" as const, icon: "\u272B", desc: "Ask questions about your corpus with grounded evidence" },
    { label: "Arabic Tools", nav: "arabic" as const, icon: "\u272A", desc: "Morphology, roots, dialect ID, Buckwalter" },
    { label: "Vision Suite", nav: "vision" as const, icon: "\u2728", desc: "Image analysis, Visual Grammar, alignment" },
  ];

  return (
    <div className="home-view">
      <div className="home-header">
        <h1>Welcome to CorpusMind</h1>
        <p className="home-subtitle">Local-first, AI-native research environment for corpus linguistics and multimodal discourse analysis</p>
      </div>

      {/* Engine offline banner — prominent, actionable.
          Now uses the single native-providers-health source of truth.
          In Tauri: nativeHealth decides. In browser: engine /health decides. */}
      {!engineOk && (
        <div className="engine-offline-banner">
          <div className="engine-offline-icon">{"\u26A0"}</div>
          <div className="engine-offline-content">
            <strong>Engine is offline.</strong> The Python backend is not running.
            {!isTauri && <span> In the desktop app, the engine starts automatically. In browser mode, start it manually:</span>}
            {isTauri && <span> The engine should have started automatically. Go to <strong>Settings</strong> and click <strong>Recheck Engine</strong> to diagnose.</span>}
          </div>
          {!isTauri && (
            <div className="engine-offline-cmd">
              <code>cd engine && source .venv/bin/activate && corpusmind-engine</code>
            </div>
          )}
          {isTauri && (
            <button className="btn-primary" onClick={() => setActiveNav("settings")}>
              Go to Settings
            </button>
          )}
        </div>
      )}

      <div className="home-status-bar">
        <div className={`status-chip ${engineOk ? "ok" : "bad"}`}>
          <span className="status-dot" />
          Engine: {engineOk ? "Running" : "Offline"}
        </div>
        <div className={`status-chip ${ollamaOk ? "ok" : "bad"}`}>
          <span className="status-dot" />
          Ollama: {ollamaOk ? "Connected" : "Not detected"}
        </div>
        {activeCorpusId && (
          <div className="status-chip ok">
            <span className="status-dot" />
            Active Corpus: {activeCorpusId.slice(0, 8)}
          </div>
        )}
        <div className="status-chip info">
          v0.1.1 | AGPL-3.0
        </div>
      </div>

      <h2 className="home-section-title">Quick Actions</h2>
      <div className="home-quick-grid">
        {quickActions.map((action) => (
          <button
            key={action.nav}
            className="quick-card"
            onClick={() => setActiveNav(action.nav)}
          >
            <span className="quick-card-icon" aria-hidden>{action.icon}</span>
            <div className="quick-card-body">
              <strong>{action.label}</strong>
              <p>{action.desc}</p>
            </div>
          </button>
        ))}
      </div>

      {!activeProjectId && (
        <div className="home-callout">
          <h3>Get Started</h3>
          <p>You have not selected a project yet. Click <strong>Projects</strong> in the sidebar to create one and upload your text files.</p>
          <button className="btn-primary" onClick={() => setActiveNav("corpus-target")}>Create a Project</button>
        </div>
      )}

      <div className="home-stats">
        <div className="home-stat">
          <span className="home-stat-num">25</span>
          <span className="home-stat-label">AI Tools</span>
        </div>
        <div className="home-stat">
          <span className="home-stat-num">20</span>
          <span className="home-stat-label">Stat Formulas</span>
        </div>
        <div className="home-stat">
          <span className="home-stat-num">12</span>
          <span className="home-stat-label">Frameworks</span>
        </div>
        <div className="home-stat">
          <span className="home-stat-num">97</span>
          <span className="home-stat-label">Tests</span>
        </div>
      </div>
    </div>
  );
}
