/**
 * StudentConnectView — v1.2.9 Student Mode (classroom client).
 *
 * The gate a student sees when the PWA is opened with ?mode=student on
 * the teacher's classroom server. Connects to the configured server URL
 * with the shared student token (usually prefilled from the QR link),
 * then hands over to the scoped student app (Sidebar filters out every
 * teacher-only surface).
 *
 * AGPL-3.0 §13: this view is rendered over a NETWORK connection from the
 * teacher's machine, so it carries a prominent Source Code link — the
 * exact clause the license's network-use provision exists for.
 */
import { useState } from "react";
import { useUI } from "@/store/ui";
import { t } from "@/lib/i18n";
import {
  clearStudentSession,
  getStudentServer,
  getStudentToken,
  setStudentSession,
} from "@/lib/api";

export function StudentConnectView() {
  const lang = useUI((s) => s.lang);
  const setStudentConnected = useUI((s) => s.setStudentConnected);
  const [server, setServer] = useState(getStudentServer());
  const [token, setToken] = useState(getStudentToken());
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const connect = async () => {
    setError("");
    const url = server.trim().replace(/\/+$/, "");
    if (!url) {
      setError(t(lang, "student_err_server"));
      return;
    }
    setBusy(true);
    try {
      // Probe with the candidate credentials before committing the session.
      const base = url;
      const r = await fetch(`${base}/api/v1/health`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!r.ok) {
        setError(`${t(lang, "student_err_connect")} (HTTP ${r.status})`);
        return;
      }
      const versioned = await fetch(`${base}/api/v1/version`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!versioned.ok && versioned.status === 401) {
        setError(t(lang, "student_err_token"));
        return;
      }
      setStudentSession(url, token.trim());
      setStudentConnected(true);
    } catch (e: unknown) {
      setError(`${t(lang, "student_err_connect")}: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const disconnect = () => {
    clearStudentSession();
    useUI.getState().setStudentClient(false);
    setStudentConnected(false);
  };

  return (
    <div className="student-connect-wrap">
      <div className="student-connect-card" role="form" aria-label={t(lang, "student_connect_title")}>
        <div className="student-connect-logo">
          <img src="/icon-32.png" alt="CorpusMind" width="40" height="40" />
          <h1>{t(lang, "student_connect_title")}</h1>
          <p className="cat-meta">{t(lang, "student_connect_hint")}</p>
        </div>

        <label className="student-connect-field">
          {t(lang, "student_server_url")}
          <input
            type="url"
            inputMode="url"
            autoCapitalize="none"
            autoCorrect="off"
            placeholder="https://192.168.1.10:8483"
            value={server}
            onChange={(e) => setServer(e.target.value)}
          />
        </label>
        <label className="student-connect-field">
          {t(lang, "student_access_token")}
          <input
            type="text"
            autoCapitalize="none"
            autoCorrect="off"
            placeholder="cm_study_…"
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
        </label>

        {error && (
          <div className="student-connect-error" role="alert">
            {error}
          </div>
        )}

        <button className="student-connect-btn" onClick={connect} disabled={busy}>
          {busy ? t(lang, "student_connecting") : t(lang, "student_connect_btn")}
        </button>

        <button type="button" className="student-connect-exit" onClick={disconnect}>
          {t(lang, "student_exit")}
        </button>

        <div className="student-connect-footer">
          <span>
            {t(lang, "student_agpl_label")}{" "}
            <a
              href="https://github.com/waleedmandour/CorpusMind"
              target="_blank"
              rel="noreferrer"
            >
              {t(lang, "student_source_link")}
            </a>
          </span>
        </div>
      </div>
    </div>
  );
}
