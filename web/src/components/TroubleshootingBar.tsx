/**
 * TroubleshootingBar — a compact issue indicator that lives in the taskbar.
 *
 * Only renders when there are unresolved issues. Shows a red badge with the
 * count of active issues. Clicking it expands a panel showing the details
 * of each issue, the Gemini interpretation (if available), and a
 * "Report to Developer" button that opens a mailto: link.
 *
 * When everything is healthy, this component renders nothing.
 */
import { useState } from "react";
import { useTroubleshoot, type TroubleshootIssue } from "@/store/troubleshooting";

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
function buildMailto(issue: TroubleshootIssue): string {
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
    `CorpusMind version: 0.1.3`,
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

function IssueCard({ issue }: { issue: TroubleshootIssue }) {
  const resolveIssue = useTroubleshoot((s) => s.resolveIssue);
  const fetchInterpretation = useTroubleshoot((s) => s.fetchInterpretation);
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
              {showFull ? "Show less" : "Show full"}
            </button>
          )}
          <div className="trouble-issue-tags">
            <span className="trouble-tag">Code: {issue.code}</span>
            {issue.endpoint && <span className="trouble-tag">Endpoint: {issue.endpoint}</span>}
            <span className="trouble-tag">{new Date(issue.timestamp).toLocaleTimeString()}</span>
            {issue.resolved && <span className="trouble-tag resolved">Resolved</span>}
          </div>
        </div>
        {!issue.resolved && (
          <button
            className="trouble-resolve-btn"
            onClick={() => resolveIssue(issue.id)}
            title="Mark as resolved"
          >
            {"\u2713"}
          </button>
        )}
      </div>

      {/* Gemini interpretation */}
      {interp === null && (
        <div className="trouble-interp loading">
          <span className="trouble-spinner" aria-hidden />
          Asking Gemini to interpret this error…
        </div>
      )}
      {interp && interp.available && (
        <div className={`trouble-interp ${severityClass(interp.severity)}`}>
          <div className="trouble-interp-row">
            <strong>What happened:</strong> {interp.plain_language}
          </div>
          <div className="trouble-interp-row">
            <strong>Likely cause:</strong> {interp.likely_cause}
          </div>
          <div className="trouble-interp-row">
            <strong>Suggested fix:</strong> {interp.suggested_fix}
          </div>
          {interp.model && (
            <div className="trouble-interp-model">Interpreted by {interp.model}</div>
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
            Retry interpretation
          </button>
        ) : null}
        <a
          className="trouble-action-btn report"
          href={buildMailto(issue)}
          title={`Report this issue to ${DEVELOPER_EMAIL}`}
        >
          {"\u2709"} Report to developer
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
          aria-label={`${unresolved.length} unresolved issue${unresolved.length === 1 ? "" : "s"}`}
        >
          <span className="trouble-bar-dot" aria-hidden />
          {unresolved.length > 0 ? (
            <span>
              {unresolved.length} issue{unresolved.length === 1 ? "" : "s"} detected
            </span>
          ) : (
            <span>Backend offline</span>
          )}
          <span className="trouble-bar-chevron">{panelOpen ? "\u25BC" : "\u25C2"}</span>
        </button>
      )}

      {/* The expandable panel */}
      {panelOpen && (
        <div className="trouble-panel" role="dialog" aria-label="Troubleshooting details">
          <div className="trouble-panel-header">
            <strong>Smart Troubleshooting</strong>
            <div className="trouble-panel-actions">
              <button
                className="trouble-panel-btn mute-toggle"
                onClick={() => setMuted(!muted)}
                title={muted ? "Unmute notifications" : "Mute notifications"}
              >
                {muted ? "\u23F8 Muted" : "\u1F50A On"}
              </button>
              {issues.some((i) => i.resolved) && (
                <button className="trouble-panel-btn" onClick={clearResolved}>
                  Clear resolved
                </button>
              )}
              {issues.length > 0 && (
                <button className="trouble-panel-btn" onClick={clearAll}>
                  Clear all
                </button>
              )}
              <button
                className="trouble-panel-btn close"
                onClick={() => setPanelOpen(false)}
                aria-label="Close troubleshooting panel"
              >
                {"\u2715"}
              </button>
            </div>
          </div>

          {muted && (
            <div className="trouble-muted-banner">
              Notifications are muted. Errors are still being captured
              silently — you can review them here anytime.
            </div>
          )}

          <div className="trouble-panel-body">
            {issues.length === 0 ? (
              <div className="trouble-empty">
                No issues recorded. {muted && "Muted — the badge will not appear even if errors occur."}
                {!backendReachable && " The backend is currently unreachable — check that "}
                {!backendReachable && <code>corpusmind-engine</code>}
                {!backendReachable && " is running on port 8765."}
              </div>
            ) : (
              issues.map((issue) => <IssueCard key={issue.id} issue={issue} />)
            )}
          </div>
        </div>
      )}
    </div>
  );
}
