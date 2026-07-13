/**
 * HomeView -- landing dashboard shown when the app starts.
 *
 * Shows quick-access cards for the most common actions, the active corpus
 * summary, and a welcome message.
 */
import { useQuery } from "@tanstack/react-query";
import { invoke } from "@tauri-apps/api/core";
import { useUI } from "@/store/ui";
import { useApp } from "@/store/app";
import { api, isTauriRuntime } from "@/lib/api";

/** Shape returned by the Rust-side `system_status` Tauri command. */
interface NativeSystemStatus {
  engine_running: boolean;
  ollama_running: boolean;
  ollama_path: string;
  engine_program: string;
  engine_args: string;
  engine_working_dir: string;
}

export function HomeView() {
  const setActiveNav = useUI((s) => s.setActiveNav);
  const activeProjectId = useApp((s) => s.activeProjectId);
  const activeCorpusId = useApp((s) => s.activeCorpusId);

  const health = useQuery({ queryKey: ["health"], queryFn: api.health, retry: 1 });
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers, retry: 1 });

  // Browser-fetch-based detection (works in PWA + Tauri once ENGINE_BASE is
  // correctly resolved — see lib/api.ts).
  const fetchEngineOk = health.data?.status === "ok";
  const fetchOllamaOk = providers.data?.providers.find((p) => p.name === "ollama")?.healthy ?? false;

  // True when running inside the Tauri desktop webview. Reuses the shared
  // helper from lib/api.ts so the detection logic lives in one place.
  const isTauri = isTauriRuntime();

  // Authoritative native fallback (Tauri only). The `system_status` command
  // (desktop/src-tauri/src/lib.rs) pings the engine + Ollama from the Rust
  // side via reqwest, which bypasses the webview's fetch path entirely. If
  // the browser-fetch check fails but the native check succeeds, the process
  // IS running — it's just unreachable over HTTP from the webview (e.g. a
  // stale CORS allowlist, a transient startup race, or a broken ENGINE_BASE).
  // We surface that as a distinct "Detected natively but API unreachable"
  // state instead of a flat "Offline", so the user isn't told the engine is
  // down when it isn't. Disabled (no query) outside Tauri.
  const nativeStatus = useQuery<NativeSystemStatus | null>({
    queryKey: ["native-system-status"],
    enabled: isTauri,
    retry: 1,
    // `invoke` throws if called outside Tauri; `enabled: isTauri` above guards
    // against that, and we re-check at runtime for defense in depth.
    queryFn: async () => {
      if (!isTauriRuntime()) return null;
      const raw = await invoke<string>("system_status");
      return JSON.parse(raw) as NativeSystemStatus;
    },
  });

  const nativeEngineOk = nativeStatus.data?.engine_running ?? false;
  const nativeOllamaOk = nativeStatus.data?.ollama_running ?? false;

  // Final surfaced booleans: fetch path wins when it succeeds; otherwise fall
  // back to the native check (Tauri only) so a healthy-but-unreachable engine
  // is still reported as detected. Used to gate the "Engine is offline" banner.
  const engineOk = fetchEngineOk || nativeEngineOk;

  // Distinguish "fully offline" from "detected natively but API unreachable".
  // The latter means the fetch path failed but the Rust-side reqwest check
  // succeeded — the engine is running, the webview just can't talk to it.
  const engineUnreachableButDetected =
    !fetchEngineOk && nativeEngineOk && isTauri;
  const ollamaUnreachableButDetected =
    !fetchOllamaOk && nativeOllamaOk && isTauri;

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

      {/* Engine offline banner — prominent, actionable */}
      {/* Hidden when the engine is reachable via EITHER path (fetch or native). */}
      {/* When the native check detects it but the fetch path fails, we show a */}
      {/* distinct "Detected natively but API unreachable" banner instead.      */}
      {!engineOk && !engineUnreachableButDetected && (
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

      {/* Detected natively (Rust-side reqwest) but unreachable from the     */}
      {/* webview's fetch() — e.g. a CORS/origin mismatch or a stale ENGINE_BASE. */}
      {/* The engine IS running, so this is NOT the "offline" banner; it's a   */}
      {/* targeted diagnostic nudge.                                           */}
      {engineUnreachableButDetected && (
        <div className="engine-offline-banner" style={{ borderColor: "var(--warn, #d4a017)" }}>
          <div className="engine-offline-icon">{"\u26A0"}</div>
          <div className="engine-offline-content">
            <strong>Detected natively but API unreachable.</strong>{" "}
            The engine process is running (confirmed by the desktop shell), but the
            app couldn't reach it over HTTP. This usually means a CORS origin
            mismatch or a baked-in engine URL that doesn't match
            <code> http://127.0.0.1:8765</code>. Go to <strong>Settings</strong> and
            click <strong>Recheck Engine</strong> to re-probe, or restart the app.
          </div>
          {isTauri && (
            <button className="btn-primary" onClick={() => setActiveNav("settings")}>
              Go to Settings
            </button>
          )}
        </div>
      )}

      <div className="home-status-bar">
        <div className={`status-chip ${fetchEngineOk ? "ok" : engineUnreachableButDetected ? "warn" : "bad"}`}>
          <span className="status-dot" />
          Engine: {fetchEngineOk ? "Running" : engineUnreachableButDetected ? "Detected (API unreachable)" : "Offline"}
        </div>
        <div className={`status-chip ${fetchOllamaOk ? "ok" : ollamaUnreachableButDetected ? "warn" : "warn"}`}>
          <span className="status-dot" />
          Ollama: {fetchOllamaOk ? "Connected" : ollamaUnreachableButDetected ? "Detected (API unreachable)" : "Not detected"}
        </div>
        {activeCorpusId && (
          <div className="status-chip ok">
            <span className="status-dot" />
            Active Corpus: {activeCorpusId.slice(0, 8)}
          </div>
        )}
        <div className="status-chip info">
          v0.1.0 | AGPL-3.0
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
