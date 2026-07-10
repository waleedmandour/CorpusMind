/**
 * Settings view — engine info, providers, reproducibility toggles,
 * Smart Troubleshooting status.
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function SettingsView() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 5_000 });
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers, refetchInterval: 5_000 });
  const version = useQuery({ queryKey: ["version"], queryFn: api.version });
  const encryption = useQuery({ queryKey: ["encryption"], queryFn: api.encryptionStatus });
  const troubleshoot = useQuery({ queryKey: ["troubleshoot-status"], queryFn: api.troubleshootStatus });

  return (
    <div className="settings-view">
      <h2>Settings</h2>

      <section>
        <h3>Engine</h3>
        <dl>
          <dt>Status</dt>
          <dd>{health.data?.status ?? "—"}</dd>
          <dt>Engine</dt>
          <dd>{health.data?.engine ?? "—"}</dd>
          <dt>Version</dt>
          <dd>{version.data?.version ?? "—"}</dd>
        </dl>
      </section>

      <section>
        <h3>Model Providers</h3>
        <p className="hint">
          Local-first by default. Cloud is opt-in and visibly indicated whenever active.
        </p>
        <table>
          <thead>
            <tr>
              <th>Provider</th>
              <th>Healthy</th>
              <th>Base URL</th>
              <th>Default Model</th>
            </tr>
          </thead>
          <tbody>
            {providers.data?.providers.map((p) => (
              <tr key={p.name}>
                <td><code>{p.name}</code></td>
                <td>{p.healthy ? "✓" : "✗"}</td>
                <td>{p.base_url || "—"}</td>
                <td>{p.default_model || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h3>Smart Troubleshooting</h3>
        <p className="hint">
          When a backend error occurs during use, CorpusMind captures it and shows
          the details in the taskbar at the bottom of the window. If a Gemini API
          key is configured in the engine environment, the error is automatically
          interpreted by Google&apos;s Gemini model — you get a plain-language
          explanation, the likely cause, and a suggested fix.
        </p>
        <div className="troubleshoot-settings-status">
          <strong>Gemini interpretation:</strong>{" "}
          {troubleshoot.data?.available ? (
            <span className="ok">
              ENABLED ({troubleshoot.data.model || "gemini-2.5-flash"})
            </span>
          ) : (
            <span className="bad">DISABLED (no API key configured)</span>
          )}
        </div>
        {!troubleshoot.data?.available && (
          <div className="troubleshoot-setup-hint">
            <p>
              <strong>To enable AI-powered error interpretation:</strong>
            </p>
            <ol>
              <li>
                Get a free API key at{" "}
                <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">
                  aistudio.google.com/apikey
                </a>
              </li>
              <li>
                Set it in the engine environment:
                <pre>{`export CORPUSMIND_GEMINI_API_KEY="your-key-here"`}</pre>
              </li>
              <li>Restart <code>corpusmind-engine</code>.</li>
            </ol>
            <p className="hint">
              The key is stored in the engine environment and never exposed to the
              browser. Only error text (message, code, endpoint) is sent to Gemini —
              never your corpus data.
            </p>
          </div>
        )}
      </section>

      <section>
        <h3>Reproducibility</h3>
        <p className="hint">
          Every project pins the exact tokenizer, tagger, model, and formula
          versions used. The auto-drafted &quot;Methods Section&quot; export
          lands in Phase 1.
        </p>
      </section>

      <section>
        <h3>Privacy</h3>
        <p className="hint">
          No telemetry or analytics without explicit, separate opt-in. The
          cloud-AI indicator is unmissable whenever active. An at-rest encryption
          option for project storage is available (Phase 6).
        </p>
        {encryption.data && (
          <div className="facial-status">
            <strong>At-rest encryption (§13.2):</strong>
            <span className={encryption.data.enabled ? "ok" : "bad"}>
              {encryption.data.enabled ? "ENABLED" : "DISABLED (default)"}
            </span>
            <p className="notice">{encryption.data.notice}</p>
          </div>
        )}
      </section>

      <section>
        <h3>Accessibility (§13.3)</h3>
        <p className="hint">
          WCAG 2.1 AA target. Visible focus indicators, skip-to-content link,
          screen-reader-only text, reduced-motion support, high-contrast mode,
          44px minimum touch targets, full RTL mirroring for Arabic.
        </p>
      </section>
    </div>
  );
}
