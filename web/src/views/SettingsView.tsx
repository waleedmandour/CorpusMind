/**
 * Settings view — engine info, providers, reproducibility toggles.
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function SettingsView() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 5_000 });
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers, refetchInterval: 5_000 });
  const version = useQuery({ queryKey: ["version"], queryFn: api.version });
  const encryption = useQuery({ queryKey: ["encryption"], queryFn: api.encryptionStatus });

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
