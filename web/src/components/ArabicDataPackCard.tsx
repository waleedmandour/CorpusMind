/**
 * ArabicDataPackCard — in-app installer for the CAMeL Arabic data pack
 * (v1.2.11 follow-up).
 *
 * Used in TWO places:
 *   1. the Arabic Tools 503 error card (compact variant), and
 *   2. Settings (full card with the package preview table).
 *
 * Talks to the engine's background install job (POST /arabic/data/install,
 * GET .../status, POST .../cancel). Status is polled at 1s ONLY while a job
 * is running; idle states re-fetch on mount and after mutations. All EN+AR
 * strings come from i18n. The card never blocks anything: the engine runs
 * the download in its own worker thread and the UI just mirrors its status.
 */
import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type ArabicDataInstallStatus } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useUI } from "@/store/ui";

function fmtMB(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fill(s: string, vars: Record<string, string>): string {
  let out = s;
  for (const [k, v] of Object.entries(vars)) out = out.replaceAll(`{${k}}`, v);
  return out;
}

function stageLabel(state: string | undefined, stage: string | undefined, lang: "en" | "ar"): string {
  switch (stage) {
    case "downloading":
      return t(lang, "ar_data_stage_download");
    case "verifying":
      return t(lang, "ar_data_stage_verifying");
    case "extracting":
      return t(lang, "ar_data_stage_extracting");
    case "cancelling":
      return t(lang, "ar_data_stage_cancelling");
    case "done":
      return t(lang, "ar_data_stage_done");
    default:
      return stage ?? state ?? "";
  }
}

export function ArabicDataPackCard({ compact = false }: { compact?: boolean }) {
  const lang = useUI((s) => s.lang);
  const qc = useQueryClient();

  // Poll fast ONLY while busy; otherwise a single fetch on mount suffices
  // (refetchInterval returns false/undefined when idle).
  const status = useQuery({
    queryKey: ["arabic-data-install"],
    queryFn: ({ signal }) => api.arabicDataInstallStatus(signal),
    refetchInterval: (query) =>
      (query.state.data as ArabicDataInstallStatus | undefined)?.busy ? 1_000 : false,
  });

  const startInstall = useMutation({
    mutationFn: (includeDialectId: boolean) => api.arabicDataInstall(includeDialectId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["arabic-data-install"] }),
  });

  const cancelInstall = useMutation({
    mutationFn: () => api.arabicDataInstallCancel(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["arabic-data-install"] }),
  });

  // v1.2.11-rc1 fix: when an install finishes, refresh the Arabic backends
  // badge too. Before this, the badge kept its pre-install state ("stubbed")
  // until a full page remount, and the user had no signal that analysis was
  // usable again (engine-side, the resolver cache is dropped by the
  // installer, so analysis genuinely works right after "done").
  const installState = status.data?.state;
  useEffect(() => {
    if (installState === "done") {
      void qc.invalidateQueries({ queryKey: ["arabic-backends"] });
      void qc.invalidateQueries({ queryKey: ["arabic-data-install"] });
    }
  }, [installState, qc]);

  const s = status.data;
  const camel = s?.camel_tools;
  const installed = camel?.installed === true;
  const busy = s?.busy === true;
  const pct =
    s && s.bytes_total && s.bytes_total > 0
      ? Math.min(100, Math.round(((s.bytes_done ?? 0) / s.bytes_total) * 100))
      : 0;

  // The 503 card only needs the button + progress; Settings shows everything.
  if (compact && (installed || busy)) {
    return (
      <div className="arabic-data-compact">
        {busy && s && (
          <>
            <div className="arabic-data-progress" role="status">
              {fill(t(lang, "ar_data_installing"), {
                pct: String(pct),
                done: fmtMB(s.bytes_done ?? 0),
                total: fmtMB(s.bytes_total ?? 0),
              })}
              {" \u00b7 "}
              {stageLabel(s.state, s.stage, lang)}
            </div>
            <div className="bar-track" aria-hidden>
              <div className="bar-fill" style={{ width: `${pct}%`, background: "var(--bar-brand)" }} />
            </div>
            <button
              className="run-btn run-btn-cancel"
              type="button"
              onClick={() => cancelInstall.mutate()}
              disabled={cancelInstall.isPending}
            >
              {t(lang, "ar_data_cancel_btn")}
            </button>
          </>
        )}
        {installed && <div className="status-ok">{t(lang, "ar_data_done")}</div>}
      </div>
    );
  }

  if (compact) {
    // Idle + not installed: the 503 card shows just the install button.
    return (
      <button
        className="run-btn"
        type="button"
        onClick={() => startInstall.mutate(true)}
        disabled={startInstall.isPending}
      >
        {t(lang, "ar_data_install_btn")}
      </button>
    );
  }

  return (
    <section className="settings-card" data-testid="arabic-data-pack-card">
      <div className="settings-card-header">
        <span className="settings-card-icon" aria-hidden>{"\u0623"}</span>
        <div>
          <h2>{t(lang, "ar_data_settings_title")}</h2>
          <p className="settings-card-desc">
            {s?.offer
              ? fill(t(lang, "ar_data_settings_desc"), { dir: s.offer.target_dir })
              : t(lang, "ar_data_missing_hint")}
          </p>
        </div>
        <span className={`settings-badge ${installed ? "ok" : busy ? "warn" : "warn"}`}>
          <span className="settings-badge-dot" />
          {installed ? t(lang, "ar_data_installed_badge") : busy ? t(lang, "ar_data_stage_download") : t(lang, "ar_data_install_btn")}
        </span>
      </div>

      <div className="settings-card-body">
        {/* Pinned package preview (only offered while idle) */}
        {s?.offer && (
          <table className="data-table" style={{ marginBottom: "var(--space-3)" }}>
            <thead>
              <tr>
                <th>Package</th>
                <th>Version</th>
                <th>Size</th>
                <th>SHA256</th>
                <th>State</th>
              </tr>
            </thead>
            <tbody>
              {s.offer.packages.map((p) => (
                <tr key={p.name}>
                  <td>
                    {p.name === "morphology-db-msa-r13"
                      ? t(lang, "ar_data_pkg_msa")
                      : t(lang, "ar_data_pkg_did")}
                  </td>
                  <td><code>{p.version}</code></td>
                  <td>{fmtMB(p.size)}</td>
                  <td><code title={p.sha256}>{p.sha256.slice(0, 10)}…</code></td>
                  <td>{p.state === "installed" ? "\u2713" : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {/* Progress while running */}
        {busy && s && (
          <div style={{ marginBottom: "var(--space-3)" }}>
            <div className="arabic-data-progress" role="status">
              {fill(t(lang, "ar_data_installing"), {
                pct: String(pct),
                done: fmtMB(s.bytes_done ?? 0),
                total: fmtMB(s.bytes_total ?? 0),
              })}
              {" \u00b7 "}
              {stageLabel(s.state, s.stage, lang)}
              {s.current_package ? ` \u00b7 ${s.current_package}` : ""}
            </div>
            <div className="bar-track" aria-hidden>
              <div className="bar-fill" style={{ width: `${pct}%`, background: "var(--bar-brand)" }} />
            </div>
          </div>
        )}

        {/* Terminal states */}
        {s?.state === "done" && !busy && (
          <div className="status-ok" style={{ marginBottom: "var(--space-3)" }}>
            {t(lang, "ar_data_done")}
          </div>
        )}
        {s?.state === "cancelled" && !busy && (
          <div className="settings-text-muted" style={{ marginBottom: "var(--space-3)" }}>
            {t(lang, "ar_data_cancelled")}
          </div>
        )}
        {s?.state === "error" && !busy && (
          <div className="error" role="alert" style={{ marginBottom: "var(--space-3)" }}>
            {fill(t(lang, "ar_data_failed"), { error: s.error ?? "unknown" })}
          </div>
        )}

        {/* Actions */}
        <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap" }}>
          {!busy && (
            <button
              className="run-btn"
              type="button"
              onClick={() => startInstall.mutate(true)}
              disabled={startInstall.isPending || installed}
            >
              {installed ? t(lang, "ar_data_stage_done") : t(lang, "ar_data_install_btn")}
            </button>
          )}
          {busy && (
            <button
              className="run-btn run-btn-cancel"
              type="button"
              onClick={() => cancelInstall.mutate()}
              disabled={cancelInstall.isPending}
            >
              {t(lang, "ar_data_cancel_btn")}
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
