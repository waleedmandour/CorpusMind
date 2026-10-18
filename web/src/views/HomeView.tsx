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
import { api, engineAttached, isTauriRuntime, nativeProvidersHealth } from "@/lib/api";
import { useEngineVersionDisplay } from "@/hooks/useEngineVersion";
import { t } from "@/lib/i18n";

export function HomeView() {
  const setActiveNav = useUI((s) => s.setActiveNav);
  const lang = useUI((s) => s.lang);
  const versionDisplay = useEngineVersionDisplay();
  const activeProjectId = useApp((s) => s.activeProjectId);
  const activeCorpusId = useApp((s) => s.activeCorpusId);

  const isTauri = isTauriRuntime();
  // v1.2.14-2 (PWA hotfix): static hosted builds with no VITE_ENGINE_URL
  // have no engine attached at all — the red banner must explain that
  // instead of telling users to run a local command that cannot help.
  const attached = engineAttached();

  // v1.2.14-2 (PWA): Safari/WebKit (including every iOS browser) refuses
  // page-to-localhost connections outright, so even a running local engine is
  // unreachable from this PWA. Detect the WebKit-only signature (no Chrome /
  // Chromium / Firefox tokens) so the AI notice can point Safari users at a
  // browser that works instead of leaving them with a generic failure.
  const isWebKitLike =
    typeof navigator !== "undefined" &&
    /^((?!chrome|chromium|crios|fxios|android).)*safari/i.test(navigator.userAgent);

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
  // v1.2.14-2 (PWA): true only after the health query has actually settled
  // (isFetched) so the notice never flashes during the initial load, and
  // never renders inside the desktop shell (isTauri), where the sidecar
  // engine + native provider health make the whole question moot.
  const pwaEngineOffline = !isTauri && health.isFetched && !engineOk;
  // v1.2.14-8 (r8, P0-3b): the ENGINE is the single source of truth for
  // provider detection (it probes the configured URLs) — the native probe
  // is only the pre-engine fallback in the desktop shell.
  const ollamaOk = (providers.data?.providers.find((p) => p.name === "ollama")?.healthy)
    ?? (isTauri ? (nativeHealth.data?.ollama.healthy ?? false) : false);
  // v1.2.10: LM Studio sits next to Ollama on the home page — same
  // detection source (the engine's /providers list, native fallback before
  // the engine is up), same chip treatment.
  const lmstudioOk = (providers.data?.providers.find((p) => p.name === "lmstudio")?.healthy)
    ?? (isTauri ? (nativeHealth.data?.lmstudio.healthy ?? false) : false);

  // v1.2.1: the Lens-specific quick-action list is gone (Lens lives in its
  // own repository) — this is always the main-app card list.
  const quickActions = [
    { label: "Create Project", nav: "corpus-target" as const, icon: "\u2630", desc: "Set up a new research project and upload texts" },
    { label: "Concordance Search", nav: "concordance" as const, icon: "\u2727", desc: "Search your corpus with KWIC view" },
    { label: "Frequency Analysis", nav: "frequency" as const, icon: "\u2727", desc: "Word, lemma, and POS frequency with STTR" },
    { label: "Collocation", nav: "collocation" as const, icon: "\u2727", desc: "All 7 measures: MI, T-score, LL, Dice, LogDice, chi-square, Delta P" },
    { label: "Keyness", nav: "keyness" as const, icon: "\u2727", desc: "Compare target vs reference corpus" },
    { label: "AI Assistant", nav: "assistant" as const, icon: "\u272B", desc: "Ask questions about your corpus with grounded evidence" },
    { label: "Arabic Tools", nav: "arabic" as const, icon: "\u272A", desc: "Morphology, roots, dialect ID, Buckwalter" },
    { label: "Learner Research", nav: "learner-caf" as const, icon: "\u03A3", desc: "CAF battery, Contrastive Interlanguage Analysis, error patterns" },
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
            {!isTauri && attached && <span> {lang === "ar" ? "في تطبيق سطح المكتب، يبدأ المحرك تلقائياً. في وضع المتصفح، ابدأه يدوياً:" : "In the desktop app, the engine starts automatically. In browser mode, start it manually:"}</span>}
            {!isTauri && !attached && <span> {t(lang, "engine_not_attached_body")}</span>}
            {isTauri && <span> {lang === "ar" ? "كان من المفترض أن يبدأ المحرك تلقائياً. اذهب إلى " : "The engine should have started automatically. Go to "}<strong>{lang === "ar" ? "الإعدادات" : "Settings"}</strong>{lang === "ar" ? " وانقر " : " and click "}<strong>{lang === "ar" ? "إعادة فحص المحرك" : "Recheck Engine"}</strong>{lang === "ar" ? " للتشخيص." : " to diagnose."}</span>}
          </div>
          {!isTauri && attached && (
            <div className="engine-offline-cmd">
              <code>cd engine && source .venv/bin/activate && corpusmind-engine</code>
            </div>
          )}
          {isTauri && (
            <button className="btn-primary" onClick={() => setActiveNav("settings")}>
              {lang === "ar" ? "اذهب إلى الإعدادات" : "Go to Settings"}
            </button>
          )}
          {/* v1.2.15 (PWA): hosted build with no engine — the fix is one
              click away, not a rebuild: attach any engine at runtime. */}
          {!isTauri && !attached && (
            <button className="btn-primary" onClick={() => setActiveNav("settings")}>
              {t(lang, "engine_attach_open_settings")}
            </button>
          )}
        </div>
      )}

      {/* v1.2.14-2 (PWA): local-AI availability notice. Ollama and LM Studio
          are machine-local runtimes; browser security (mixed content, local
          network access permissions, WebKit loopback blocking) means this
          PWA can only use them THROUGH the engine. With the engine offline
          no AI model can run — say so here, on the main page, instead of
          leaving three grey chips and a silent Assistant to guess at.
          Desktop builds (Tauri) bundle the engine, so the notice never
          renders there. */}
      {pwaEngineOffline && (
        <div className="pwa-ai-notice" role="note" aria-live="polite">
          <div className="pwa-ai-notice-icon" aria-hidden>{"\u2728"}</div>
          <div className="pwa-ai-notice-content">
            <strong>{t(lang, "pwa_ai_title")}</strong>
            <p>{t(lang, "pwa_ai_body")}</p>
            {attached && (
              <>
                <p>{t(lang, "pwa_ai_fix")}</p>
                <div className="engine-offline-cmd">
                  <code>cd engine && source .venv/bin/activate && corpusmind-engine</code>
                </div>
              </>
            )}
            {!attached && <p>{t(lang, "pwa_ai_fix_hosted")}</p>}
            {isWebKitLike && (
              <p className="pwa-ai-notice-safari">{t(lang, "pwa_ai_safari_note")}</p>
            )}
          </div>
        </div>
      )}

      <div className="home-status-bar">
        <div className={`status-chip ${engineOk ? "ok" : "bad"}`}>
          <span className="status-dot" />
          {t(lang, "home_engine")}: {engineOk ? t(lang, "home_running") : t(lang, "home_offline")}
        </div>
        <div className={`status-chip ${ollamaOk ? "ok" : "bad"}`}>
          <span className="status-dot" />
          {/* v1.2.14-2 (PWA): with the engine down in browser mode the Ollama
              chip cannot know whether the runtime is installed — relabel from
              "Not detected" to the honest "Unavailable — engine offline". */}
          {t(lang, "home_ollama")}: {ollamaOk
            ? t(lang, "home_connected")
            : (pwaEngineOffline ? t(lang, "home_provider_engine_offline") : t(lang, "home_not_running"))}
        </div>
        {/* v1.2.10: LM Studio detected / not detected — right next to Ollama. */}
        <div className={`status-chip ${lmstudioOk ? "ok" : "bad"}`}>
          <span className="status-dot" />
          {t(lang, "home_lmstudio")}: {lmstudioOk
            ? t(lang, "home_connected")
            : (pwaEngineOffline ? t(lang, "home_provider_engine_offline") : t(lang, "home_not_running"))}
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
          <span className="home-stat-num">28</span>
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

