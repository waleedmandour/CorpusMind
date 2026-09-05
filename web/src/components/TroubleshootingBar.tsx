/**
 * TroubleshootingBar — a compact issue indicator that lives in the taskbar.
 *
 * Only renders when there are unresolved issues. Shows a red badge with the
 * count of active issues. Clicking it expands a panel showing the details
 * of each issue, an instant one-line fix suggestion (v1.2.0, offline rules
 * table), the Gemini interpretation (if available), and a
 * "Report to Developer" button that opens a mailto: link.
 *
 * v1.2.0: fully internationalized (en/ar) — the mute toggle previously had
 * a malformed unicode escape ("\u1F50A" parses as U+1F50 + literal "A",
 * rendering "ὐA On") and no translations at all.
 *
 * When everything is healthy, this component renders nothing.
 */
import { useState } from "react";
import { useTroubleshoot, type TroubleshootIssue } from "@/store/troubleshooting";
import { useEngineVersion } from "@/hooks/useEngineVersion";
import { t } from "@/lib/i18n";
import { useUI } from "@/store/ui";

const DEVELOPER_EMAIL = "w.abumandour@squ.edu.om";

function severityIcon(sev: string): string {
  switch (sev) {
    case "error": return "\u26A0";
    case "warning": return "\u26A0";
    default: return "\u2139";
  }
}

function severityClass(sev: string): string {
  return `severity-${sev}`;
}

/** Build a mailto: link with the issue details + Gemini interpretation. */
function buildMailto(issue: TroubleshootIssue, version: string): string {
  const subject = `[CorpusMind Bug Report] ${issue.message.slice(0, 80)}`;
  const lines: string[] = [
    "Dear Dr. Mandour,",
    "",
    "I encountered the following error while using CorpusMind and would like to report it.",
    "",
    "=== ERROR DETAILS ===",
    `Timestamp: ${issue.timestamp}`,
    `Error code: ${issue.code}`,
    `Endpoint: ${issue.endpoint ?? "N/A"}`,
    `Context: ${issue.context ?? "N/A"}`,
    `Message: ${issue.message}`,
    "",
  ];

  if (issue.suggestion) {
    lines.push(`=== INSTANT SUGGESTION === ${issue.suggestion}`, "");
  }

  if (issue.stackTrace) {
    lines.push("=== STACK TRACE ===", issue.stackTrace, "");
  }

  if (issue.interpretation && issue.interpretation.available) {
    lines.push(
      "=== GEMINI INTERPRETATION ===",
      `Severity: ${issue.interpretation.severity}`,
      `Plain language: ${issue.interpretation.plain_language}`,
      `Likely cause: ${issue.interpretation.likely_cause}`,
      `Suggested fix: ${issue.interpretation.suggested_fix}`,
      `Model: ${issue.interpretation.model}`,
      "",
    );
  }

  lines.push(
    "=== ENVIRONMENT ===",
    `CorpusMind version: ${version}`,
    `Browser: ${navigator.userAgent}`,
    `URL: ${window.location.href}`,
    "",
    "Steps to reproduce:",
    "1. ",
    "2. ",
    "3. ",
    "",
    "Thank you for looking into this.",
    "",
    "Best regards,",
  );

  const body = lines.join("\n");
  return `mailto:${DEVELOPER_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

function IssueCard({ issue, version }: { issue: TroubleshootIssue; version: string }) {
  const resolveIssue = useTroubleshoot((s) => s.resolveIssue);
  const fetchInterpretation = useTroubleshoot((s) => s.fetchInterpretation);
  const lang = useUI((s) => s.lang);
  const [showFull, setShowFull] = useState(false);

  const sev = issue.interpretation?.severity ?? "error";
  const interp = issue.interpretation;

  return (
    <div className={`trouble-issue-card ${severityClass(sev)} ${issue.resolved ? "resolved" : ""}`}>
      <div className="trouble-issue-header">
        <span className="trouble-issue-icon" aria-hidden>{severityIcon(sev)}</span>
        <div className="trouble-issue-meta">
          <strong className="trouble-issue-message">
            {issue.message.length > 120 && !showFull
              ? `${issue.message.slice(0, 120)}…`
              : issue.message}
          </strong>
          {issue.message.length > 120 && (
            <button
              className="trouble-toggle-full"
              onClick={() => setShowFull(!showFull)}
            >
              {showFull ? t(lang, "trouble_show_less") : t(lang, "trouble_show_full")}
            </button>
          )}
          <div className="trouble-issue-tags">
            <span className="trouble-tag">{t(lang, "trouble_code")}: {issue.code}</span>
            {issue.endpoint && <span className="trouble-tag">{t(lang, "trouble_endpoint")}: {issue.endpoint}</span>}
            <span className="trouble-tag">{new Date(issue.timestamp).toLocaleTimeString()}</span>
            {issue.resolved && <span className="trouble-tag resolved">{t(lang, "trouble_resolved")}</span>}
          </div>
        </div>
        {!issue.resolved && (
          <button
            className="trouble-resolve-btn"
            onClick={() => resolveIssue(issue.id)}
            title={t(lang, "trouble_resolve_title")}
          >
            {"\u2713"}
          </button>
        )}
      </div>

      {/* v1.2.0: instant offline one-line suggestion — shown immediately,
          no Gemini key or network needed. */}
      {issue.suggestion && (
        <div className="trouble-interp suggestion" role="note">
          <div className="trouble-interp-row">
            <strong>{t(lang, "trouble_fix_label")}:</strong> {issue.suggestion}
          </div>
        </div>
      )}

      {/* Gemini interpretation (deeper, optional layer) */}
      {interp === null && (
        <div className="trouble-interp loading">
          <span className="trouble-spinner" aria-hidden />
          {t(lang, "trouble_asking_gemini")}
        </div>
      )}
      {interp && interp.available && (
        <div className={`trouble-interp ${severityClass(interp.severity)}`}>
          <div className="trouble-interp-row">
            <strong>{t(lang, "trouble_what_happened")}:</strong> {interp.plain_language}
          </div>
          <div className="trouble-interp-row">
            <strong>{t(lang, "trouble_likely_cause")}:</strong> {interp.likely_cause}
          </div>
          <div className="trouble-interp-row">
            <strong>{t(lang, "trouble_suggested_fix")}:</strong> {interp.suggested_fix}
          </div>
          {interp.model && (
            <div className="trouble-interp-model">{t(lang, "trouble_interpreted_by")} {interp.model}</div>
          )}
        </div>
      )}
      {interp && !interp.available && (
        <div className="trouble-interp unavailable">
          {interp.plain_language}
        </div>
      )}

      {/* Actions */}
      <div className="trouble-actions">
        {!interp || !interp.available ? (
          <button
            className="trouble-action-btn retry"
            onClick={() => fetchInterpretation(issue.id)}
          >
            {t(lang, "trouble_retry_interp")}
          </button>
        ) : null}
        <a
          className="trouble-action-btn report"
          href={buildMailto(issue, version)}
          title={`Report this issue to ${DEVELOPER_EMAIL}`}
        >
          {"\u2709"} {t(lang, "trouble_report_dev")}
        </a>
      </div>
    </div>
  );
}

export function TroubleshootingBar() {
  const issues = useTroubleshoot((s) => s.issues);
  const panelOpen = useTroubleshoot((s) => s.panelOpen);
  const setPanelOpen = useTroubleshoot((s) => s.setPanelOpen);
  const clearResolved = useTroubleshoot((s) => s.clearResolved);
  const clearAll = useTroubleshoot((s) => s.clearAll);
  const backendReachable = useTroubleshoot((s) => s.backendReachable);
  const muted = useTroubleshoot((s) => s.muted);
  const setMuted = useTroubleshoot((s) => s.setMuted);
  const version = useEngineVersion();
  const lang = useUI((s) => s.lang);

  const unresolved = issues.filter((i) => !i.resolved);

  // When muted, don't show the taskbar badge (errors are still captured
  // silently and visible if the user opens the panel from Settings).
  // Still render the container so the panel can be opened from Settings.
  const showBadge = !muted && (unresolved.length > 0 || !backendReachable);

  // Don't render anything if everything is healthy AND not muted
  if (!showBadge && !panelOpen) {
    return null;
  }

  return (
    <div className="trouble-bar-container">
      {/* The taskbar indicator — hidden when muted */}
      {showBadge && (
        <button
          className={`trouble-bar-indicator ${unresolved.length > 0 ? "has-issues" : "backend-down"}`}
          onClick={() => setPanelOpen(!panelOpen)}
          aria-expanded={panelOpen}
          aria-label={`${unresolved.length} ${unresolved.length === 1 ? t(lang, "trouble_badge_issue") : t(lang, "trouble_badge_issues")}`}
        >
          <span className="trouble-bar-dot" aria-hidden />
          {unresolved.length > 0 ? (
            <span>
              {unresolved.length}{" "}
              {unresolved.length === 1 ? t(lang, "trouble_badge_issue") : t(lang, "trouble_badge_issues")}
            </span>
          ) : (
            <span>{t(lang, "trouble_backend_offline")}</span>
          )}
          <span className="trouble-bar-chevron">{panelOpen ? "\u25BC" : "\u25C2"}</span>
        </button>
      )}

      {/* The expandable panel */}
      {panelOpen && (
        <div className="trouble-panel" role="dialog" aria-label={t(lang, "trouble_dialog_label")}>
          <div className="trouble-panel-header">
            <strong>{t(lang, "trouble_title")}</strong>
            <div className="trouble-panel-actions">
              <button
                className="trouble-panel-btn mute-toggle"
                onClick={() => setMuted(!muted)}
                title={muted ? t(lang, "trouble_mute_unmute") : t(lang, "trouble_mute_mute")}
              >
                {/* v1.2.0 bugfix: the old label used "\u1F50A", which JS
                    parses as U+1F50 + literal "A" → rendered "ὐA On".
                    Correct escapes (or literals) render the speaker emoji. */}
                {muted ? `\u23F8 ${t(lang, "trouble_muted_label")}` : `\u{1F508} ${t(lang, "trouble_on_label")}`}
              </button>
              {issues.some((i) => i.resolved) && (
                <button className="trouble-panel-btn" onClick={clearResolved}>
                  {t(lang, "trouble_clear_resolved")}
                </button>
              )}
              {issues.length > 0 && (
                <button className="trouble-panel-btn" onClick={clearAll}>
                  {t(lang, "trouble_clear_all")}
                </button>
              )}
              <button
                className="trouble-panel-btn close"
                onClick={() => setPanelOpen(false)}
                aria-label={t(lang, "trouble_close")}
              >
                {"\u2715"}
              </button>
            </div>
          </div>

          {muted && (
            <div className="trouble-muted-banner">
              {t(lang, "trouble_muted_banner")}
            </div>
          )}

          <div className="trouble-panel-body">
            {issues.length === 0 ? (
              <div className="trouble-empty">
                {t(lang, "trouble_empty")}
                {!backendReachable && (
                  <>
                    {" "}
                    {t(lang, "trouble_backend_down_pre")}
                    <code>corpusmind-engine</code>
                    {t(lang, "trouble_backend_down_post")}
                  </>
                )}
              </div>
            ) : (
              issues.map((issue) => <IssueCard key={issue.id} issue={issue} version={version} />)
            )}
          </div>
        </div>
      )}
    </div>
  );
}
