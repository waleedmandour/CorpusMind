/**
 * Settings view — a professional, card-based dashboard showing engine
 * status, model providers, Smart Troubleshooting configuration,
 * reproducibility, privacy/encryption, and accessibility.
 *
 * Each section is a card with an icon, title, and structured content.
 * Status indicators use colored badges (green = ok, red = problem,
 * amber = warning) so the user can scan the page in one glance.
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function SettingsView() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 5_000 });
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers, refetchInterval: 5_000 });
  const version = useQuery({ queryKey: ["version"], queryFn: api.version });
  const encryption = useQuery({ queryKey: ["encryption"], queryFn: api.encryptionStatus });
  const troubleshoot = useQuery({ queryKey: ["troubleshoot-status"], queryFn: api.troubleshootStatus });

  const engineOk = health.data?.status === "ok";
  const ollamaOk = providers.data?.providers.find((p) => p.name === "ollama")?.healthy ?? false;
  const lmstudioOk = providers.data?.providers.find((p) => p.name === "lmstudio")?.healthy ?? false;
  const cloudOk = providers.data?.providers.find((p) => p.name === "cloud")?.healthy ?? false;

  return (
    <div className="settings-view">
      <div className="settings-header">
        <h1>Settings</h1>
        <p className="settings-subtitle">
          Engine status, model providers, and system configuration for CorpusMind.
        </p>
      </div>

      {/* Engine status card */}
      <section className="settings-card">
        <div className="settings-card-header">
          <span className="settings-card-icon" aria-hidden>{"\u2699"}</span>
          <div>
            <h2>Engine</h2>
            <p className="settings-card-desc">The CorpusMind FastAPI backend process.</p>
          </div>
          <span className={`settings-badge ${engineOk ? "ok" : "bad"}`}>
            <span className="settings-badge-dot" />
            {engineOk ? "Running" : "Offline"}
          </span>
        </div>
        <div className="settings-card-body">
          <dl className="settings-dl">
            <dt>Status</dt>
            <dd>{health.data?.status ?? "—"}</dd>
            <dt>Engine</dt>
            <dd><code>{health.data?.engine ?? "—"}</code></dd>
            <dt>Version</dt>
            <dd><code>{version.data?.version ?? "—"}</code></dd>
            <dt>Endpoint</dt>
            <dd><code>http://127.0.0.1:8765</code></dd>
          </dl>
        </div>
      </section>

      {/* Model providers card */}
      <section className="settings-card">
        <div className="settings-card-header">
          <span className="settings-card-icon" aria-hidden>{"\u2728"}</span>
          <div>
            <h2>Model Providers</h2>
            <p className="settings-card-desc">
              Local-first by default. Cloud is opt-in and visibly indicated whenever active.
            </p>
          </div>
        </div>
        <div className="settings-card-body">
          <div className="provider-grid">
            <ProviderCard
              name="Ollama"
              icon={"\u25CF"}
              healthy={ollamaOk}
              baseUrl="http://127.0.0.1:11434"
              defaultModel={providers.data?.providers.find((p) => p.name === "ollama")?.default_model ?? "llama3.2:3b"}
              description="Local LLM runtime. Install from ollama.com, then run `ollama serve`."
            />
            <ProviderCard
              name="LM Studio"
              icon={"\u25CF"}
              healthy={lmstudioOk}
              baseUrl="http://127.0.0.1:1234/v1"
              defaultModel={providers.data?.providers.find((p) => p.name === "lmstudio")?.default_model ?? "local-model"}
              description="Local LLM runtime with OpenAI-compatible API. Install from lmstudio.ai."
            />
            <ProviderCard
              name="Cloud"
              icon={"\u2601"}
              healthy={cloudOk}
              baseUrl="—"
              defaultModel="—"
              description="Opt-in cloud provider (Anthropic / OpenAI). Off by default for privacy."
            />
          </div>
        </div>
      </section>

      {/* Smart Troubleshooting card */}
      <section className="settings-card">
        <div className="settings-card-header">
          <span className="settings-card-icon" aria-hidden>{"\u26A0"}</span>
          <div>
            <h2>Smart Troubleshooting</h2>
            <p className="settings-card-desc">
              Automatic backend error detection with optional Gemini-powered interpretation.
            </p>
          </div>
          <span className={`settings-badge ${troubleshoot.data?.available ? "ok" : "warn"}`}>
            <span className="settings-badge-dot" />
            {troubleshoot.data?.available ? "Enabled" : "Not configured"}
          </span>
        </div>
        <div className="settings-card-body">
          <p className="settings-text">
            When a backend error occurs during use, CorpusMind captures it and shows
            the details in the taskbar at the bottom of the window. If a Gemini API
            key is configured in the engine environment, the error is automatically
            interpreted by Google&apos;s Gemini model — you get a plain-language
            explanation, the likely cause, and a suggested fix.
          </p>
          <div className="settings-status-row">
            <strong>Gemini interpretation:</strong>{" "}
            {troubleshoot.data?.available ? (
              <span className="status-ok">
                ENABLED ({troubleshoot.data.model || "gemini-2.5-flash"})
              </span>
            ) : (
              <span className="status-bad">DISABLED (no API key configured)</span>
            )}
          </div>
          {!troubleshoot.data?.available && (
            <div className="settings-setup-hint">
              <p><strong>To enable AI-powered error interpretation:</strong></p>
              <ol>
                <li>
                  Get a free API key at{" "}
                  <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">
                    aistudio.google.com/apikey
                  </a>
                </li>
                <li>
                  Set it in the engine environment:
                  <pre><code>{`export CORPUSMIND_GEMINI_API_KEY="your-key-here"`}</code></pre>
                </li>
                <li>Restart <code>corpusmind-engine</code>.</li>
              </ol>
              <p className="settings-text-muted">
                The key is stored in the engine environment and never exposed to the
                browser. Only error text (message, code, endpoint) is sent to Gemini —
                never your corpus data.
              </p>
            </div>
          )}
        </div>
      </section>

      {/* Reproducibility card */}
      <section className="settings-card">
        <div className="settings-card-header">
          <span className="settings-card-icon" aria-hidden>{"\u21BB"}</span>
          <div>
            <h2>Reproducibility</h2>
            <p className="settings-card-desc">
              Every project pins the exact tools, models, and formulas used.
            </p>
          </div>
        </div>
        <div className="settings-card-body">
          <p className="settings-text">
            Every project pins the exact tokenizer, tagger, model, and formula
            versions used. The engine stores an annotation-version UUID alongside
            every parsed corpus, and the AI Assistant&apos;s audit trail records which
            model + provider + prompt template produced each turn. The auto-drafted
            &quot;Methods Section&quot; PDF export names the exact tools and versions
            for pasting into a manuscript.
          </p>
        </div>
      </section>

      {/* Privacy + Encryption card */}
      <section className="settings-card">
        <div className="settings-card-header">
          <span className="settings-card-icon" aria-hidden>{"\u26BF"}</span>
          <div>
            <h2>Privacy &amp; Encryption</h2>
            <p className="settings-card-desc">
              No telemetry. Cloud is opt-in. At-rest encryption is available for project storage.
            </p>
          </div>
          <span className={`settings-badge ${encryption.data?.enabled ? "ok" : "warn"}`}>
            <span className="settings-badge-dot" />
            {encryption.data?.enabled ? "Encrypted" : "Not encrypted"}
          </span>
        </div>
        <div className="settings-card-body">
          <p className="settings-text">
            No telemetry or analytics without explicit, separate opt-in. The
            cloud-AI indicator is unmissable whenever active. An at-rest encryption
            option for project storage is available.
          </p>
          {encryption.data && (
            <div className="settings-status-row">
              <strong>At-rest encryption:</strong>{" "}
              <span className={encryption.data.enabled ? "status-ok" : "status-bad"}>
                {encryption.data.enabled ? "ENABLED" : "DISABLED (default)"}
              </span>
              <p className="settings-text-muted">{encryption.data.notice}</p>
            </div>
          )}
        </div>
      </section>

      {/* Accessibility card */}
      <section className="settings-card">
        <div className="settings-card-header">
          <span className="settings-card-icon" aria-hidden>{"\u267F"}</span>
          <div>
            <h2>Accessibility</h2>
            <p className="settings-card-desc">WCAG 2.1 AA target with full RTL support.</p>
          </div>
        </div>
        <div className="settings-card-body">
          <div className="settings-feature-list">
            <div className="settings-feature-item">
              <span className="settings-feature-check">{"\u2713"}</span>
              <span>Visible focus indicators</span>
            </div>
            <div className="settings-feature-item">
              <span className="settings-feature-check">{"\u2713"}</span>
              <span>Skip-to-content link</span>
            </div>
            <div className="settings-feature-item">
              <span className="settings-feature-check">{"\u2713"}</span>
              <span>Screen-reader-only text</span>
            </div>
            <div className="settings-feature-item">
              <span className="settings-feature-check">{"\u2713"}</span>
              <span>Reduced-motion support</span>
            </div>
            <div className="settings-feature-item">
              <span className="settings-feature-check">{"\u2713"}</span>
              <span>High-contrast mode</span>
            </div>
            <div className="settings-feature-item">
              <span className="settings-feature-check">{"\u2713"}</span>
              <span>44px minimum touch targets</span>
            </div>
            <div className="settings-feature-item">
              <span className="settings-feature-check">{"\u2713"}</span>
              <span>Full RTL mirroring for Arabic</span>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}


function ProviderCard({
  name,
  icon,
  healthy,
  baseUrl,
  defaultModel,
  description,
}: {
  name: string;
  icon: string;
  healthy: boolean;
  baseUrl: string;
  defaultModel: string;
  description: string;
}) {
  return (
    <div className={`provider-card ${healthy ? "healthy" : "unhealthy"}`}>
      <div className="provider-card-header">
        <span className="provider-card-icon" aria-hidden>{icon}</span>
        <strong className="provider-card-name">{name}</strong>
        <span className={`provider-card-badge ${healthy ? "ok" : "bad"}`}>
          <span className="settings-badge-dot" />
          {healthy ? "Connected" : "Not running"}
        </span>
      </div>
      <p className="provider-card-desc">{description}</p>
      <dl className="provider-card-meta">
        <dt>Base URL</dt>
        <dd><code>{baseUrl}</code></dd>
        <dt>Default model</dt>
        <dd><code>{defaultModel}</code></dd>
      </dl>
    </div>
  );
}
