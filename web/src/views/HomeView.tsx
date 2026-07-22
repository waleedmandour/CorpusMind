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
import { useEngineVersionDisplay } from "@/hooks/useEngineVersion";
import { t } from "@/lib/i18n";

export function HomeView() {
  const setActiveNav = useUI((s) => s.setActiveNav);
  const lang = useUI((s) => s.lang);
  const versionDisplay = useEngineVersionDisplay();
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
        <h1>{t(lang, "home_welcome")}</h1>
        <p className="home-subtitle">{t(lang, "home_subtitle")}</p>
      </div>

      {/* Engine offline banner — prominent, actionable.
          Now uses the single native-providers-health source of truth.
          In Tauri: nativeHealth decides. In browser: engine /health decides. */}
      {!engineOk && (
        <div className="engine-offline-banner">
          <div className="engine-offline-icon">{"\u26A0"}</div>
          <div className="engine-offline-content">
            <strong>{lang === "ar" ? "المحرك متوقف." : "Engine is offline."}</strong>{" "}
            {lang === "ar"
              ? "الواجهة الخلفية بلغة Python لا تعمل."
              : "The Python backend is not running."}
            {!isTauri && <span> {lang === "ar" ? "في تطبيق سطح المكتب، يبدأ المحرك تلقائياً. في وضع المتصفح، ابدأه يدوياً:" : "In the desktop app, the engine starts automatically. In browser mode, start it manually:"}</span>}
            {isTauri && <span> {lang === "ar" ? "كان من المفترض أن يبدأ المحرك تلقائياً. اذهب إلى " : "The engine should have started automatically. Go to "}<strong>{lang === "ar" ? "الإعدادات" : "Settings"}</strong>{lang === "ar" ? " وانقر " : " and click "}<strong>{lang === "ar" ? "إعادة فحص المحرك" : "Recheck Engine"}</strong>{lang === "ar" ? " للتشخيص." : " to diagnose."}</span>}
          </div>
          {!isTauri && (
            <div className="engine-offline-cmd">
              <code>cd engine && source .venv/bin/activate && corpusmind-engine</code>
            </div>
          )}
          {isTauri && (
            <button className="btn-primary" onClick={() => setActiveNav("settings")}>
              {lang === "ar" ? "اذهب إلى الإعدادات" : "Go to Settings"}
            </button>
          )}
        </div>
      )}

      <div className="home-status-bar">
        <div className={`status-chip ${engineOk ? "ok" : "bad"}`}>
          <span className="status-dot" />
          {t(lang, "home_engine")}: {engineOk ? t(lang, "home_running") : t(lang, "home_offline")}
        </div>
        <div className={`status-chip ${ollamaOk ? "ok" : "bad"}`}>
          <span className="status-dot" />
          {t(lang, "home_ollama")}: {ollamaOk ? t(lang, "home_connected") : t(lang, "home_not_running")}
        </div>
        {activeCorpusId && (
          <div className="status-chip ok">
            <span className="status-dot" />
            {t(lang, "home_active_corpus")}
          </div>
        )}
        <div className="status-chip info">
          {versionDisplay} | AGPL-3.0
        </div>
      </div>

      <h2 className="home-section-title">{t(lang, "home_quick_actions")}</h2>
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
          <h3>{t(lang, "home_get_started")}</h3>
          <p>{t(lang, "home_no_project")}</p>
          <button className="btn-primary" onClick={() => setActiveNav("corpus-target")}>{t(lang, "home_create_project")}</button>
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
