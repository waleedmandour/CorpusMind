/**
 * ErrorBoundary — v1.2.12.
 *
 * Without a boundary, ANY exception thrown while React renders unmounts the
 * whole tree and the desktop window turns white until the user reloads it
 * (field report: toggling the Student Mode classroom server). The boundary
 * keeps the shell alive, records the error in Smart Troubleshooting, and
 * offers "Try again" (re-mount the subtree, no page reload, so pending
 * Tauri IPC callbacks are not orphaned) and "Reload app" as a last resort.
 */
import { Component, type ErrorInfo, type ReactNode } from "react";

import { useTroubleshoot } from "@/store/troubleshooting";
import { useUI } from "@/store/ui";
import { t } from "@/lib/i18n";

interface Props {
  children: ReactNode;
}
interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    try {
      useTroubleshoot.getState().captureError({
        message: error.message || String(error),
        context: "UI render error",
        stackTrace: [error.stack, info.componentStack].filter(Boolean).join("\n"),
      });
    } catch {
      /* never let error reporting throw inside the boundary */
    }
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  private retry = () => this.setState({ error: null });
  private reload = () => window.location.reload();

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    const lang = useUI.getState().lang;
    return (
      <div
        role="alert"
        style={{
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "12px",
          padding: "24px",
          textAlign: "center",
          background: "var(--bg, #0e1116)",
          color: "var(--text, #e6edf3)",
        }}
      >
        <h2 style={{ margin: 0 }}>{t(lang, "err_boundary_title")}</h2>
        <p style={{ maxWidth: 520, margin: 0 }}>{t(lang, "err_boundary_body")}</p>
        <code style={{ maxWidth: 640, overflowWrap: "anywhere", opacity: 0.8 }}>
          {error.message}
        </code>
        <div style={{ display: "flex", gap: "8px" }}>
          <button className="btn-small" onClick={this.retry}>
            {t(lang, "err_boundary_retry")}
          </button>
          <button className="btn-small" onClick={this.reload}>
            {t(lang, "err_boundary_reload")}
          </button>
        </div>
      </div>
    );
  }
}
