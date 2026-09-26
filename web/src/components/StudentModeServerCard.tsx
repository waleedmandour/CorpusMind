/**
 * StudentModeServerCard — v1.2.9 Student Mode, teacher side (Settings).
 *
 * Enable/disable the classroom server (teacher-as-server), pick the
 * connection mode (Secure HTTPS via the bundled Caddy's internal CA, or
 * Simple plain HTTP for closed classroom networks), show the QR codes +
 * URLs + student token, pick the classroom model (default llama3.2:3b —
 * deliberately separate from whatever large model the teacher uses solo),
 * tune OLLAMA_NUM_PARALLEL guidance, and display the live connected-student
 * count plus the "up to N students" capacity estimate computed from the
 * same RAM/VRAM probe the HF GGUF explorer uses.
 *
 * The Secure mode's certificate-trust step is presented as what it is — a
 * real one-time action per student device that school-managed devices may
 * block — never as an automatic zero-friction flow.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import QRCode from "qrcode";

import { api } from "@/lib/api";
import { useUI } from "@/store/ui";
import { t } from "@/lib/i18n";

function CopyBtn({ text, lang }: { text: string; lang: "en" | "ar" }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="sm-copy-btn"
      title={t(lang, "sm_copy")}
      aria-label={t(lang, "sm_copy")}
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
    >
      {copied ? "✓" : "⧉"}
    </button>
  );
}

function QrImage({ value, size = 148 }: { value: string; size?: number }) {
  const ref = useRef<HTMLImageElement | null>(null);
  useEffect(() => {
    let cancelled = false;
    QRCode.toDataURL(value, { width: size * 2, margin: 1 })
      .then((url) => {
        if (!cancelled && ref.current) ref.current.src = url;
      })
      .catch(() => {
        /* QR only fails on absurdly long URLs — the text URL is always shown too */
      });
    return () => {
      cancelled = true;
    };
  }, [value, size]);
  return <img ref={ref} width={size} height={size} alt={`QR: ${value}`} className="sm-qr-img" />;
}

export function StudentModeServerCard() {
  const lang = useUI((s) => s.lang);
  const qc = useQueryClient();

  const status = useQuery({
    queryKey: ["server-mode-status"],
    queryFn: () => api.serverModeStatus(),
    refetchInterval: (q) => (q.state.data?.enabled ? 5000 : false),
  });

  const models = useQuery({
    queryKey: ["ollama-models-list"],
    queryFn: async () => (await api.listModels("ollama")).models,
    enabled: !!status.data,
  });

  const classroomModel = status.data?.student_model ?? "llama3.2:3b";
  const capacity = useQuery({
    queryKey: ["server-mode-capacity", classroomModel],
    queryFn: () => api.serverModeCapacity(classroomModel),
    enabled: !!status.data?.enabled,
  });

  const enable = useMutation({
    mutationFn: (req: Parameters<typeof api.serverModeEnable>[0]) => api.serverModeEnable(req),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["server-mode-status"] }),
  });
  const disable = useMutation({
    mutationFn: () => api.serverModeDisable(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["server-mode-status"] }),
  });
  const updateConfig = useMutation({
    mutationFn: (req: { student_model?: string; num_parallel?: number }) =>
      api.serverModeUpdateConfig(req),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["server-mode-status"] }),
  });

  const [mode, setMode] = useState<"secure" | "simple">("secure");
  const [httpsPort, setHttpsPort] = useState<number | null>(null);
  const [httpPort, setHttpPort] = useState<number | null>(null);

  const s = status.data;
  const enabled = !!s?.enabled;

  const studentUrl = useMemo(() => {
    if (!s?.enabled) return "";
    const base = s.urls.app;
    return `${base}/?mode=student&server=${encodeURIComponent(base)}&token=${encodeURIComponent(s.student_token ?? "")}`;
  }, [s]);

  const teacherUrl = useMemo(() => {
    if (!s?.enabled) return "";
    const base = s.urls.app;
    return `${base}/?mode=student&server=${encodeURIComponent(base)}&token=${encodeURIComponent(s.teacher_token ?? "")}`;
  }, [s]);

  if (status.isLoading) return null;

  return (
    <section className="settings-card">
      <div className="settings-card-header">
        <span className="settings-card-icon" aria-hidden>{"\u2318"}</span>
        <div>
          <h2>{t(lang, "sm_card_title")}</h2>
          <p className="settings-card-desc">{t(lang, "sm_card_desc")}</p>
        </div>
      </div>
      <div className="settings-card-body">
        {/* Prerequisite problems surface here, not as a generic failure */}
        {s && (!s.caddy_binary_found || !s.web_dist_bundled) && (
          <div className="sm-warning" role="status">
            {!s.caddy_binary_found && <p>{t(lang, "sm_err_no_caddy")}</p>}
            {!s.web_dist_bundled && <p>{t(lang, "sm_err_no_webdist")}</p>}
          </div>
        )}
        {s?.caddy_error && (
          <div className="sm-warning" role="status">
            <p>{s.caddy_error}</p>
          </div>
        )}

        {/* Connection mode choice — always visible so the trade-off is
            explained BEFORE the teacher commits. */}
        <div className="sm-mode-choice" role="radiogroup" aria-label={t(lang, "sm_mode")}>
          <label className={mode === "secure" ? "sm-mode sm-mode-active" : "sm-mode"}>
            <input
              type="radio"
              name="sm-mode"
              checked={mode === "secure"}
              onChange={() => setMode("secure")}
              disabled={enabled}
            />
            <div>
              <strong>{t(lang, "sm_mode_secure")}</strong>
              <p className="settings-text-muted">{t(lang, "sm_mode_secure_hint")}</p>
            </div>
          </label>
          <label className={mode === "simple" ? "sm-mode sm-mode-active" : "sm-mode"}>
            <input
              type="radio"
              name="sm-mode"
              checked={mode === "simple"}
              onChange={() => setMode("simple")}
              disabled={enabled}
            />
            <div>
              <strong>{t(lang, "sm_mode_simple")}</strong>
              <p className="settings-text-muted">{t(lang, "sm_mode_simple_hint")}</p>
            </div>
          </label>
        </div>

        <details className="sm-advanced">
          <summary>{t(lang, "sm_advanced")}</summary>
          <div className="sm-port-row">
            <label>
              {t(lang, "sm_https_port")}
              <input
                type="number"
                min={1024}
                max={65535}
                value={httpsPort ?? s?.https_port ?? 8483}
                onChange={(e) => setHttpsPort(Number(e.target.value))}
                disabled={enabled}
              />
            </label>
            <label>
              {t(lang, "sm_http_port")}
              <input
                type="number"
                min={1024}
                max={65535}
                value={httpPort ?? s?.http_port ?? 8484}
                onChange={(e) => setHttpPort(Number(e.target.value))}
                disabled={enabled}
              />
            </label>
          </div>
        </details>

        {/* Enable / disable */}
        <div className="sm-actions">
          {!enabled ? (
            <button
              className="btn-small sm-primary"
              disabled={enable.isPending || (!!s && (!s.caddy_binary_found || !s.web_dist_bundled))}
              onClick={() =>
                enable.mutate({
                  mode,
                  https_port: httpsPort,
                  http_port: httpPort,
                })
              }
            >
              {enable.isPending ? t(lang, "sm_starting") : t(lang, "sm_enable")}
            </button>
          ) : (
            <button className="btn-small sm-danger" disabled={disable.isPending} onClick={() => disable.mutate()}>
              {t(lang, "sm_disable")}
            </button>
          )}
          {enabled && (
            <button
              className="btn-small"
              onClick={() => enable.mutate({ mode: s!.mode, rotate: true })}
              disabled={enable.isPending}
              title={t(lang, "sm_rotate_hint")}
            >
              {t(lang, "sm_rotate")}
            </button>
          )}
        </div>
        {(enable.error || disable.error) && (
          <div className="sm-warning" role="alert">
            <p>{String((enable.error ?? disable.error))}</p>
          </div>
        )}

        {/* Live classroom panel */}
        {enabled && s && (
          <>
            <div className="sm-status-line">
              <span className={s.caddy_running ? "settings-badge ok" : "settings-badge bad"}>
                <span className="settings-badge-dot" />
                {s.caddy_running ? t(lang, "sm_running") : t(lang, "sm_not_running")}
              </span>
              {s.caddy_version ? <span className="cat-meta">{s.caddy_version}</span> : null}
              <span className="cat-meta">
                {t(lang, "sm_students_connected").replace("{n}", String(s.students_active))}
              </span>
              {s.ollama_running_models != null && (
                <span className="cat-meta">
                  {t(lang, "sm_ollama_loaded").replace("{n}", String(s.ollama_running_models))}
                </span>
              )}
            </div>

            {/* QRs + URLs */}
            <div className="sm-qr-row">
              <div className="sm-qr-box">
                <QrImage value={studentUrl} />
                <strong>{t(lang, "sm_qr_student")}</strong>
                <code className="sm-url">{studentUrl}</code>
                <CopyBtn text={studentUrl} lang={lang} />
              </div>
              {s.mode === "secure" && (
                <div className="sm-qr-box">
                  <QrImage value={s.urls.root_ca ?? ""} />
                  <strong>{t(lang, "sm_qr_cert")}</strong>
                  <code className="sm-url">{s.urls.root_ca}</code>
                  <CopyBtn text={s.urls.root_ca ?? ""} lang={lang} />
                </div>
              )}
              <div className="sm-qr-box sm-qr-text">
                <strong>{t(lang, "sm_teacher_join")}</strong>
                <p className="settings-text-muted">{t(lang, "sm_teacher_join_hint")}</p>
                <code className="sm-url">{teacherUrl}</code>
                <CopyBtn text={teacherUrl} lang={lang} />
                <details className="sm-advanced">
                  <summary>{t(lang, "sm_trust_title")}</summary>
                  <p className="settings-text-muted">{t(lang, "sm_trust_step_body")}</p>
                </details>
              </div>
            </div>

            {/* Classroom model + parallelism + capacity */}
            <div className="sm-config-row">
              <label>
                {t(lang, "sm_classroom_model")}
                <select
                  value={classroomModel}
                  onChange={(e) => updateConfig.mutate({ student_model: e.target.value })}
                >
                  {(models.data ?? []).map((m: string) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                  {(models.data ?? []).length === 0 && <option value="llama3.2:3b">llama3.2:3b</option>}
                </select>
              </label>
              <label>
                {t(lang, "sm_num_parallel")}
                <select
                  value={s.num_parallel}
                  onChange={(e) => updateConfig.mutate({ num_parallel: Number(e.target.value) })}
                >
                  {[1, 2, 3, 4, 5, 6, 8, 10].map((n) => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </select>
              </label>
            </div>
            <p className="cat-meta">{t(lang, "sm_num_parallel_hint")}</p>
            {capacity.data && (
              <div className="sm-capacity">
                <strong>
                  {capacity.data.students_max != null
                    ? t(lang, "sm_capacity_n").replace("{n}", String(capacity.data.students_max))
                    : t(lang, "sm_capacity_unknown")}
                </strong>
                <p className="cat-meta">{capacity.data.note}</p>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
