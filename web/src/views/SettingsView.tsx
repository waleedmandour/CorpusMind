/**
 * Settings view — a professional, card-based dashboard showing engine
 * status, model providers, Smart Troubleshooting configuration,
 * reproducibility, privacy/encryption, and accessibility.
 *
 * Each section is a card with an icon, title, and structured content.
 * Status indicators use colored badges (green = ok, red = problem,
 * amber = warning) so the user can scan the page in one glance.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useTroubleshoot } from "@/store/troubleshooting";
import { useUI } from "@/store/ui";
import { useApp } from "@/store/app";

export function SettingsView() {
  const qc = useQueryClient();
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 5_000 });
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers, refetchInterval: 5_000 });
  const version = useQuery({ queryKey: ["version"], queryFn: api.version });
  const encryption = useQuery({ queryKey: ["encryption"], queryFn: api.encryptionStatus });
  const troubleshoot = useQuery({ queryKey: ["troubleshoot-status"], queryFn: api.troubleshootStatus });

  const engineOk = health.data?.status === "ok";
  const ollamaOk = providers.data?.providers.find((p) => p.name === "ollama")?.healthy ?? false;
  const lmstudioOk = providers.data?.providers.find((p) => p.name === "lmstudio")?.healthy ?? false;
  const cloudOk = providers.data?.providers.find((p) => p.name === "cloud")?.healthy ?? false;

  const [recheckingEngine, setRecheckingEngine] = useState(false);
  const [recheckingOllama, setRecheckingOllama] = useState(false);
  const [diagMessage, setDiagMessage] = useState("");
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const [engineLogs, setEngineLogs] = useState<string>("");
  const [sidecarInfo, setSidecarInfo] = useState<string>("");

  // Check if we're running in Tauri (desktop app)
  const isTauri = typeof window !== "undefined" &&
    (typeof (window as any).__TAURI_INTERNALS__ !== "undefined" ||
     typeof (window as any).__TAURI__ !== "undefined");

  const recheckEngine = async () => {
    setRecheckingEngine(true);
    setDiagMessage("");
    try {
      if (isTauri) {
        const invoke = (window as any).__TAURI_INTERNALS__?.invoke || (window as any).__TAURI__?.core?.invoke;
        if (invoke) {
          const result = await invoke("restart_engine");
          const data = JSON.parse(result as string);
          setDiagMessage(data.message || data.diagnostics?.hint || "");
        }
      }
      qc.invalidateQueries({ queryKey: ["health"] });
      qc.invalidateQueries({ queryKey: ["providers"] });
    } catch (e: any) {
      setDiagMessage(`Recheck failed: ${e?.message || String(e)}`);
    } finally {
      setRecheckingEngine(false);
    }
  };

  const recheckOllama = async () => {
    setRecheckingOllama(true);
    setDiagMessage("");
    try {
      if (isTauri) {
        const invoke = (window as any).__TAURI_INTERNALS__?.invoke || (window as any).__TAURI__?.core?.invoke;
        if (invoke) {
          const result = await invoke("restart_ollama");
          const data = JSON.parse(result as string);
          setDiagMessage(data.message || data.hint || "");
        }
      }
      qc.invalidateQueries({ queryKey: ["providers"] });
    } catch (e: any) {
      setDiagMessage(`Recheck failed: ${e?.message || String(e)}`);
    } finally {
      setRecheckingOllama(false);
    }
  };

  const runDiagnostics = async () => {
    setShowDiagnostics(true);
    setEngineLogs("Loading...");
    setSidecarInfo("Loading...");
    if (!isTauri) {
      setEngineLogs("Diagnostics only available in the desktop app.");
      setSidecarInfo("Diagnostics only available in the desktop app.");
      return;
    }
    try {
      const invoke = (window as any).__TAURI_INTERNALS__?.invoke || (window as any).__TAURI__?.core?.invoke;
      if (invoke) {
        // Get engine logs
        const logsResult = await invoke("engine_logs");
        const logsData = JSON.parse(logsResult as string);
        const logText = [
          `stdout log: ${logsData.stdout_path || "(not found)"}`,
          "─".repeat(60),
          logsData.stdout || "(empty)",
          "",
          `stderr log: ${logsData.stderr_path || "(not found)"}`,
          "─".repeat(60),
          logsData.stderr || "(empty)",
        ].join("\n");
        setEngineLogs(logText);

        // Get sidecar verification
        const sidecarResult = await invoke("verify_sidecar");
        const sidecarData = JSON.parse(sidecarResult as string);
        const sidecarText = [
          `Sidecar found: ${sidecarData.sidecar_found ? "YES" : "NO"}`,
          `Expected name: ${sidecarData.expected_name}`,
          `Target triple: ${sidecarData.target_triple}`,
          `Resource dir: ${sidecarData.resource_dir || "(not resolved)"}`,
          `Sidecar path: ${sidecarData.sidecar_path || "(not found)"}`,
          "",
          `Resolved program: ${sidecarData.resolved_program}`,
          `Resolved args: ${sidecarData.resolved_args}`,
          `Resolved working dir: ${sidecarData.resolved_working_dir}`,
          "",
          `Message: ${sidecarData.message}`,
        ].join("\n");
        setSidecarInfo(sidecarText);
      }
    } catch (e: any) {
      setEngineLogs(`Diagnostics failed: ${e?.message || String(e)}`);
      setSidecarInfo(`Diagnostics failed: ${e?.message || String(e)}`);
    }
  };

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
          {!engineOk && (
            <div className="settings-status-row" style={{ marginTop: "var(--space-3)", flexDirection: "column", alignItems: "stretch" }}>
              <strong style={{ color: "var(--danger)" }}>Engine is offline</strong>
              <p className="settings-text-muted">
                The engine should start automatically when the app launches.
                If it didn't, click "Recheck" to try again. If it still fails,
                click "Run Diagnostics" to see the engine logs and find out why.
              </p>
              <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", flexWrap: "wrap" }}>
                <button
                  className="btn-primary"
                  onClick={recheckEngine}
                  disabled={recheckingEngine || !isTauri}
                  title={!isTauri ? "Recheck is only available in the desktop app" : ""}
                >
                  {recheckingEngine ? "Restarting..." : "Recheck Engine"}
                </button>
                <button
                  className="btn-secondary"
                  onClick={runDiagnostics}
                  disabled={!isTauri}
                  title={!isTauri ? "Diagnostics only available in the desktop app" : ""}
                >
                  Run Diagnostics
                </button>
                {!isTauri && <span className="settings-text-muted">(desktop app only)</span>}
              </div>
              {diagMessage && <p className="settings-text-muted" style={{ marginTop: "var(--space-2)" }}>{diagMessage}</p>}
            </div>
          )}
          {showDiagnostics && (
            <div style={{ marginTop: "var(--space-3)" }}>
              <h3 style={{ fontSize: "0.95em", marginBottom: "var(--space-2)" }}>Engine Logs</h3>
              <pre style={{
                background: "var(--surface-2, #1a1a1a)",
                color: "var(--text-2, #e0e0e0)",
                padding: "var(--space-2)",
                borderRadius: "6px",
                fontSize: "0.8em",
                maxHeight: "300px",
                overflow: "auto",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                fontFamily: "monospace",
              }}>{engineLogs}</pre>

              <h3 style={{ fontSize: "0.95em", marginTop: "var(--space-3)", marginBottom: "var(--space-2)" }}>Sidecar Verification</h3>
              <pre style={{
                background: "var(--surface-2, #1a1a1a)",
                color: "var(--text-2, #e0e0e0)",
                padding: "var(--space-2)",
                borderRadius: "6px",
                fontSize: "0.8em",
                maxHeight: "200px",
                overflow: "auto",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                fontFamily: "monospace",
              }}>{sidecarInfo}</pre>

              <p className="settings-text-muted" style={{ marginTop: "var(--space-2)", fontSize: "0.85em" }}>
                Copy the above text and share it with support if the engine won't start.
                The stderr log shows the exact Python error that prevented the engine from starting.
              </p>
            </div>
          )}
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

          {/* Ollama recheck button */}
          {!ollamaOk && (
            <div className="settings-status-row" style={{ marginTop: "var(--space-3)", flexDirection: "column", alignItems: "stretch" }}>
              <strong style={{ color: "var(--danger)" }}>Ollama is not detected</strong>
              <p className="settings-text-muted">
                The app should auto-start Ollama when it launches. If it didn't,
                click "Recheck" to try again. Make sure Ollama is installed from
                <a href="https://ollama.com" target="_blank" rel="noreferrer"> ollama.com</a>.
              </p>
              <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
                <button
                  className="btn-primary"
                  onClick={recheckOllama}
                  disabled={recheckingOllama || !isTauri}
                  title={!isTauri ? "Recheck is only available in the desktop app" : ""}
                >
                  {recheckingOllama ? "Restarting..." : "Recheck Ollama"}
                </button>
                {!isTauri && <span className="settings-text-muted">(desktop app only)</span>}
              </div>
              {diagMessage && <p className="settings-text-muted" style={{ marginTop: "var(--space-2)" }}>{diagMessage}</p>}
            </div>
          )}

          {/* Ollama model downloader */}
          <OllamaModelManager ollamaHealthy={ollamaOk} />
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
            {troubleshoot.data?.available ? "Enabled" : "Off by default"}
          </span>
        </div>
        <div className="settings-card-body">
          <p className="settings-text">
            When a backend error occurs during use, CorpusMind captures it and shows
            the details in the taskbar at the bottom of the window. If a Gemini API
            key is configured, the error is automatically interpreted by Google&apos;s
            Gemini model — you get a plain-language explanation, the likely cause,
            and a suggested fix.
          </p>

          {/* Gemini API key input */}
          <GeminiKeyInput
            available={troubleshoot.data?.available ?? false}
            source={troubleshoot.data?.source ?? "none"}
            model={troubleshoot.data?.model ?? "gemini-2.5-flash"}
          />

          {/* Mute toggle */}
          <MuteToggle />
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

      {/* Research + Reproducibility card */}
      <ResearchCard />
    </div>
  );
}


function ResearchCard() {
  const studentMode = useUI((s) => s.studentMode);
  const setStudentMode = useUI((s) => s.setStudentMode);
  const activeCorpusId = useApp((s) => s.activeCorpusId);
  const activeProjectId = useApp((s) => s.activeProjectId);

  const precheck = useQuery({
    queryKey: ["precheck", activeCorpusId],
    queryFn: () => activeCorpusId ? api.prepublicationCheck(activeCorpusId) : Promise.resolve(null),
    enabled: !!activeCorpusId,
  });

  const disclosure = useQuery({
    queryKey: ["ai-disclosure", activeProjectId],
    queryFn: () => activeProjectId ? api.aiDisclosure(activeProjectId) : Promise.resolve(null),
    enabled: !!activeProjectId,
  });

  const [showDisclosure, setShowDisclosure] = useState(false);

  return (
    <section className="settings-card">
        <div className="settings-card-header">
          <span className="settings-card-icon" aria-hidden>{"\u2139"}</span>
          <div>
            <h2>Research &amp; Reproducibility</h2>
            <p className="settings-card-desc">
              Pre-publication checks, AI usage disclosure, and student mode.
            </p>
          </div>
        </div>
        <div className="settings-card-body">
          {/* Student mode toggle */}
          <div className="student-mode-row">
            <div>
              <strong>Student Mode</strong>
              <p className="settings-text-muted">
                When ON, the AI Assistant hides its interpretation until the
                student writes their own. Prevents over-reliance while still
                teaching the tools. The student can then compare their
                interpretation with the AI&apos;s for learning.
              </p>
            </div>
            <label className="toggle-switch">
              <input
                type="checkbox"
                checked={studentMode}
                onChange={(e) => setStudentMode(e.target.checked)}
              />
              <span className="toggle-slider" />
            </label>
          </div>

          {/* Pre-publication check */}
          {activeCorpusId && (
            <div className="settings-status-row" style={{ flexDirection: "column", alignItems: "stretch", marginTop: "var(--space-3)" }}>
              <strong>Pre-publication Check</strong>
              <p className="settings-text-muted">
                Audits your corpus for reproducibility before you publish.
                Checks annotation version, AI non-determinism, pipeline
                recipe, and document count.
              </p>
              {precheck.data && (
                <div className="precheck-result" style={{ marginTop: "var(--space-2)" }}>
                  <div className={`settings-badge ${precheck.data.overall === "pass" ? "ok" : precheck.data.overall === "warn" ? "warn" : "bad"}`}>
                    <span className="settings-badge-dot" />
                    Overall: {precheck.data.overall.toUpperCase()}
                  </div>
                  {precheck.data.checks.map((c) => (
                    <div key={c.id} className={`precheck-item ${c.status}`}>
                      <span className="precheck-status">
                        {c.status === "pass" ? "\u2713" : c.status === "warn" ? "\u26A0" : "\u2717"}
                      </span>
                      <div>
                        <div className="precheck-label">{c.label}</div>
                        <div className="precheck-detail">{c.detail}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* AI usage disclosure */}
          {activeProjectId && disclosure.data && (
            <div className="settings-status-row" style={{ flexDirection: "column", alignItems: "stretch", marginTop: "var(--space-3)" }}>
              <strong>AI Usage Disclosure</strong>
              <p className="settings-text-muted">
                Summary of AI usage for this project. Include this in your
                manuscript&apos;s Methods section for transparency.
              </p>
              <button className="btn-small" onClick={() => setShowDisclosure(!showDisclosure)}>
                {showDisclosure ? "Hide" : "Show"} disclosure text
              </button>
              {showDisclosure && (
                <div className="ai-disclosure-text">
                  {disclosure.data.disclosure_text}
                </div>
              )}
            </div>
          )}
        </div>
      </section>
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


function GeminiKeyInput({
  available,
  source,
  model,
}: {
  available: boolean;
  source: string;
  model: string;
}) {
  const qc = useQueryClient();
  const [key, setKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [savedMsg, setSavedMsg] = useState("");

  const saveMutation = useMutation({
    mutationFn: (k: string) => api.setGeminiKey(k),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["troubleshoot-status"] });
      setKey("");
      setSavedMsg(data.available ? "Key saved. Smart Troubleshooting is now ON." : "Key saved but not active.");
      setTimeout(() => setSavedMsg(""), 4000);
    },
    onError: (e: Error) => {
      setSavedMsg(`Error: ${e.message}`);
      setTimeout(() => setSavedMsg(""), 4000);
    },
  });

  const clearMutation = useMutation({
    mutationFn: () => api.clearGeminiKey(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["troubleshoot-status"] });
      setSavedMsg("Key cleared.");
      setTimeout(() => setSavedMsg(""), 4000);
    },
  });

  return (
    <div className="gemini-key-section">
      <div className="gemini-key-status">
        <strong>Gemini interpretation:</strong>{" "}
        {available ? (
          <span className="status-ok">
            ENABLED ({model}) via {source === "ui" ? "UI key" : "env var"}
          </span>
        ) : (
          <span className="status-bad">OFF (no key configured)</span>
        )}
      </div>

      {available && source === "ui" && (
        <button
          className="btn-small danger gemini-clear-btn"
          onClick={() => clearMutation.mutate()}
          disabled={clearMutation.isPending}
        >
          {clearMutation.isPending ? "Clearing..." : "Clear saved key"}
        </button>
      )}

      {!available || source !== "ui" ? (
        <>
          <p className="settings-text-muted">
            Enter your Gemini API key to enable AI-powered error interpretation.
            Get a free key at{" "}
            <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">
              aistudio.google.com/apikey
            </a>.
            The key is stored in-memory in the engine (never written to disk)
            and never sent back to the browser.
          </p>
          <div className="gemini-key-input-row">
            <input
              type={showKey ? "text" : "password"}
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="Paste your Gemini API key here..."
              className="gemini-key-input"
              autoComplete="off"
            />
            <button
              className="btn-small"
              onClick={() => setShowKey(!showKey)}
              title={showKey ? "Hide key" : "Show key"}
            >
              {showKey ? "Hide" : "Show"}
            </button>
            <button
              className="btn-primary gemini-save-btn"
              onClick={() => key.trim() && saveMutation.mutate(key.trim())}
              disabled={!key.trim() || saveMutation.isPending}
            >
              {saveMutation.isPending ? "Saving..." : "Save"}
            </button>
          </div>
          {savedMsg && <div className="gemini-saved-msg">{savedMsg}</div>}
        </>
      ) : (
        savedMsg && <div className="gemini-saved-msg">{savedMsg}</div>
      )}
    </div>
  );
}


function MuteToggle() {
  const muted = useTroubleshoot((s) => s.muted);
  const setMuted = useTroubleshoot((s) => s.setMuted);

  return (
    <div className="mute-toggle-row">
      <div>
        <strong>Notifications:</strong>
        <p className="settings-text-muted">
          When ON, a red badge appears in the taskbar when errors occur and the
          panel auto-opens. When OFF (muted), errors are still captured silently
          and can be reviewed here anytime.
        </p>
      </div>
      <label className="toggle-switch">
        <input
          type="checkbox"
          checked={!muted}
          onChange={(e) => setMuted(!e.target.checked)}
        />
        <span className="toggle-slider" />
      </label>
    </div>
  );
}


function OllamaModelManager({ ollamaHealthy }: { ollamaHealthy: boolean }) {
  const qc = useQueryClient();
  const catalogue = useQuery({ queryKey: ["ollama-catalogue"], queryFn: api.ollamaCatalogue });
  const installedModels = useQuery({
    queryKey: ["ollama-models"],
    queryFn: () => api.listModels("ollama"),
    enabled: ollamaHealthy,
    refetchInterval: 10_000,
  });
  const [pullingModel, setPullingModel] = useState<string | null>(null);
  const [pullStatus, setPullStatus] = useState<{ completed: number; total: number; status: string } | null>(null);
  const [showImport, setShowImport] = useState(false);
  const [importName, setImportName] = useState("");
  const [importPath, setImportPath] = useState("");

  const importMutation = useMutation({
    mutationFn: ({ name, path }: { name: string; path: string }) => api.ollamaImport(name, path),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ollama-models"] });
      setShowImport(false);
      setImportName("");
      setImportPath("");
      alert("Model imported successfully! It now appears in your Ollama model list.");
    },
    onError: (e: Error) => {
      alert(`Import failed: ${e.message}`);
    },
  });

  const installedSet = new Set(installedModels.data?.models ?? []);

  const pullModel = async (modelName: string) => {
    if (!ollamaHealthy) {
      alert("Ollama is not running. Start it with `ollama serve` first.");
      return;
    }
    setPullingModel(modelName);
    setPullStatus({ completed: 0, total: 0, status: "starting" });
    try {
      await api.ollamaPull(modelName);
      // Poll for progress
      const poll = setInterval(async () => {
        try {
          const status = await api.ollamaPullStatus(modelName);
          setPullStatus({
            completed: status.completed,
            total: status.total,
            status: status.status,
          });
          if (status.status === "success" || status.status === "error") {
            clearInterval(poll);
            setPullingModel(null);
            qc.invalidateQueries({ queryKey: ["ollama-models"] });
            if (status.status === "error") {
              alert(`Pull failed: ${status.error}`);
            }
          }
        } catch {
          clearInterval(poll);
          setPullingModel(null);
        }
      }, 2000);
    } catch (e) {
      setPullingModel(null);
      alert(`Pull failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  if (!ollamaHealthy) {
    return (
      <div className="ollama-model-manager">
        <p className="settings-text-muted">
          Ollama is not running. Start it with{" "}
          <code>ollama serve</code> to download and manage models.
        </p>
      </div>
    );
  }

  return (
    <div className="ollama-model-manager">
      <div className="ollama-model-section-title">
        Download models
        {installedModels.data && (
          <span className="ollama-installed-count">
            {installedModels.data.models.length} installed
          </span>
        )}
      </div>

      {/* Import from file (.gguf) */}
      <div className="ollama-import-section">
        {!showImport ? (
          <button className="btn-small ollama-import-btn" onClick={() => setShowImport(true)}>
            + Import from file (.gguf)
          </button>
        ) : (
          <div className="ollama-import-form">
            <p className="settings-text-muted">
              Import a local .gguf model file (e.g. downloaded from HuggingFace).
              The engine calls <code>ollama create</code> to register it.
            </p>
            <input
              type="text"
              value={importName}
              onChange={(e) => setImportName(e.target.value)}
              placeholder="Model name (e.g. 'my-gemma-4b')"
              className="ollama-import-input"
            />
            <input
              type="text"
              value={importPath}
              onChange={(e) => setImportPath(e.target.value)}
              placeholder="Full path to .gguf file (e.g. C:\Users\...\gemma-4b.gguf)"
              className="ollama-import-input"
            />
            <div className="ollama-import-actions">
              <button
                className="btn-primary"
                disabled={!importName.trim() || !importPath.trim() || importMutation.isPending}
                onClick={() => importMutation.mutate({ name: importName.trim(), path: importPath.trim() })}
              >
                {importMutation.isPending ? "Importing..." : "Import model"}
              </button>
              <button className="btn-small" onClick={() => setShowImport(false)}>Cancel</button>
            </div>
          </div>
        )}
      </div>

      <div className="ollama-model-grid">
        {catalogue.data?.models.map((m) => {
          const isInstalled = installedSet.has(m.name);
          const isPulling = pullingModel === m.name;
          const pct = pullStatus && pullStatus.total > 0
            ? Math.round((pullStatus.completed / pullStatus.total) * 100)
            : 0;
          return (
            <div key={m.name} className={`ollama-model-card ${m.recommended ? "recommended" : ""}`}>
              <div className="ollama-model-header">
                <strong className="ollama-model-name">{m.name}</strong>
                {m.recommended && <span className="ollama-recommended-badge">Recommended</span>}
                {isInstalled && <span className="ollama-installed-badge">Installed</span>}
              </div>
              <p className="ollama-model-desc">{m.description}</p>
              <div className="ollama-model-meta">
                <span className="ollama-meta-tag">{m.size}</span>
                <span className="ollama-meta-tag">{m.params} params</span>
                <span className="ollama-meta-tag">{m.ram} RAM</span>
                {m.languages.includes("ar") && <span className="ollama-meta-tag ar">Arabic</span>}
              </div>
              {isPulling && (
                <div className="ollama-pull-progress">
                  <div className="ollama-progress-bar" style={{ width: `${pct}%` }} />
                  <span className="ollama-progress-text">
                    {pullStatus?.status === "starting" ? "Starting..." : `${pct}%`}
                  </span>
                </div>
              )}
              {!isInstalled && !isPulling && (
                <button
                  className="btn-small ollama-pull-btn"
                  onClick={() => pullModel(m.name)}
                  disabled={!!pullingModel}
                >
                  Download
                </button>
              )}
              {isInstalled && !isPulling && (
                <span className="ollama-ready-text">Ready to use</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
