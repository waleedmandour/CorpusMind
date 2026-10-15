/**
 * EngineAttachCard — runtime engine attachment (Settings → Engine Connection).
 *
 * A static hosted build (e.g. the Vercel PWA) ships with no engine URL,
 * which previously made it a read-only showcase. This card lets any user
 * attach an engine AT RUNTIME — the desktop app's sidecar on
 * http://127.0.0.1:8765, or a self-hosted deployment (BUILD_GUIDE §5) —
 * turning the SAME hosted PWA into a full analysis client. The URL plus an
 * optional bearer token persist in localStorage (see lib/api.ts, "Runtime
 * engine attachment"); attaching or detaching reloads the page so every
 * boot-time gate (main.tsx, HomeView, Smart Troubleshooting) re-evaluates.
 *
 * Hidden inside the Tauri desktop shell: there the engine IS the sidecar,
 * auto-started and auto-attached — nothing to configure.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  api,
  clearAttachedEngine,
  getAttachedEngineToken,
  getAttachedEngineUrl,
  getStudentServer,
  isTauriRuntime,
  setAttachedEngine,
} from "@/lib/api";
import { useUI } from "@/store/ui";
import { t } from "@/lib/i18n";

type TestResult = { ok: boolean; detail: string } | null;

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "8px 10px",
  borderRadius: 8,
  border: "1px solid var(--border, #ccc)",
  background: "var(--bg, transparent)",
  color: "inherit",
  fontSize: 14,
  fontFamily: "inherit",
};

export function EngineAttachCard() {
  const lang = useUI((s) => s.lang);
  const [url, setUrl] = useState(() => getAttachedEngineUrl());
  const [token, setToken] = useState(() => getAttachedEngineToken());
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult>(null);
  const [busy, setBusy] = useState(false);

  const attached = getAttachedEngineUrl();
  const inTauri = isTauriRuntime();
  const studentSession = getStudentServer();

  // Live health of the attached engine — shares the ["health"] react-query
  // cache with the Engine card above, so both flip in sync. Never runs when
  // unattached (synthetic offline response keeps the badge honest).
  const health = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    enabled: !!attached && !inTauri,
    retry: 1,
  });

  // The desktop shell auto-attaches its sidecar engine — nothing to do here.
  if (inTauri) return null;

  const requireUrl = (): string => {
    const u = url.trim().replace(/\/+$/, "");
    if (!u) {
      setTestResult({ ok: false, detail: t(lang, "engine_attach_need_url") });
      return "";
    }
    return u;
  };

  async function runTest(): Promise<void> {
    const u = requireUrl();
    if (!u) return;
    setTesting(true);
    setTestResult(null);
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => ctrl.abort(), 8000);
    try {
      const headers: Record<string, string> = {};
      const tk = token.trim();
      if (tk) headers["Authorization"] = `Bearer ${tk}`;
      const r = await fetch(`${u}/api/v1/health`, { headers, signal: ctrl.signal });
      if (!r.ok) {
        setTestResult({ ok: false, detail: `${t(lang, "engine_attach_http_fail")} ${r.status}` });
      } else {
        const data = (await r.json()) as { status?: string; engine?: string; version?: string };
        const label = [data.engine, data.version].filter(Boolean).join(" ");
        setTestResult({
          ok: true,
          detail: label ? `${label} — ${data.status ?? "ok"}` : (data.status ?? "ok"),
        });
      }
    } catch {
      // Mixed-content blocking, CORS rejection, connection refused and
      // offline engines all surface here — one honest, actionable message.
      setTestResult({ ok: false, detail: t(lang, "engine_attach_unreachable") });
    } finally {
      window.clearTimeout(timer);
      setTesting(false);
    }
  }

  function attach(): void {
    const u = requireUrl();
    if (!u) return;
    setBusy(true);
    setAttachedEngine(u, token);
    window.location.reload();
  }

  function detach(): void {
    setBusy(true);
    clearAttachedEngine();
    window.location.reload();
  }

  return (
    <section className="settings-card">
      <div className="settings-card-header">
        <span className="settings-card-icon" aria-hidden>{"\u26A1"}</span>
        <div>
          <h2>{t(lang, "engine_attach_title")}</h2>
          <p className="settings-card-desc">{t(lang, "engine_attach_desc")}</p>
        </div>
        <span className={`settings-badge ${attached ? "ok" : "warn"}`}>
          <span className="settings-badge-dot" />
          {attached ? t(lang, "engine_attach_status_on") : t(lang, "engine_attach_status_off")}
        </span>
      </div>

      <div className="settings-card-body" style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
        {studentSession && (
          <p className="settings-text-muted" style={{ margin: 0 }}>
            {"\u26A0 "} {t(lang, "engine_attach_student_note")}
          </p>
        )}

        {attached && (
          <dl className="settings-dl">
            <dt>{t(lang, "engine_attach_url_label")}</dt>
            <dd>
              <code>{attached}</code>
            </dd>
            {health.data?.status === "ok" && (
              <>
                <dt>{t(lang, "engine_attach_version_label")}</dt>
                <dd>
                  {health.data.engine}
                  {health.data.version ? ` ${health.data.version}` : ""} — ok
                </dd>
              </>
            )}
          </dl>
        )}

        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 14 }}>
          <span>{t(lang, "engine_attach_url_label")}</span>
          <input
            style={inputStyle}
            type="text"
            value={url}
            placeholder="http://127.0.0.1:8765"
            spellCheck={false}
            autoCapitalize="off"
            autoCorrect="off"
            disabled={busy}
            onChange={(e) => setUrl(e.target.value)}
          />
        </label>

        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 14 }}>
          <span>{t(lang, "engine_attach_token_label")}</span>
          <input
            style={inputStyle}
            type="password"
            value={token}
            placeholder="CORPUSMIND_AUTH_TOKEN"
            spellCheck={false}
            autoCapitalize="off"
            autoCorrect="off"
            disabled={busy}
            onChange={(e) => setToken(e.target.value)}
          />
        </label>

        <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", alignItems: "center" }}>
          <button type="button" className="btn-secondary" onClick={() => void runTest()} disabled={testing || busy}>
            {testing ? t(lang, "engine_attach_testing") : t(lang, "engine_attach_test")}
          </button>
          <button type="button" className="btn-primary" onClick={attach} disabled={busy}>
            {t(lang, "engine_attach_attach")}
          </button>
          {attached && (
            <button type="button" className="btn-cancel" onClick={detach} disabled={busy}>
              {t(lang, "engine_attach_detach")}
            </button>
          )}
        </div>

        {testResult && (
          <p style={{ margin: 0, fontSize: 14, color: testResult.ok ? "var(--ok, #2e7d32)" : "var(--danger, #c62828)" }}>
            {testResult.ok ? "\u2713 " : "\u2717 "}
            {testResult.detail}
          </p>
        )}

        <p className="settings-text-muted" style={{ margin: 0 }}>
          {t(lang, "engine_attach_hint_local")}
        </p>
        <p className="settings-text-muted" style={{ margin: 0 }}>
          {t(lang, "engine_attach_hint_remote")}
        </p>
      </div>
    </section>
  );
}
