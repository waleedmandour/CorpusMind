/**
 * Engine API client.
 *
 * Talks to corpusmind-engine over HTTP. In dev, Vite proxies /api → :8765.
 * In the Tauri desktop shell, the engine runs as a sidecar on 127.0.0.1:8765.
 */

export const ENGINE_BASE =
  (import.meta.env.VITE_ENGINE_URL as string | undefined) ?? ""; // empty → same-origin (proxied in dev)

export interface HealthResponse {
  status: string;
  engine: string;
  version: string;
}

export interface ProviderInfo {
  name: "ollama" | "lmstudio" | "cloud";
  healthy: boolean;
  base_url?: string;
  default_model?: string;
  error?: string;
}

export interface ProvidersResponse {
  providers: ProviderInfo[];
}

export interface ChatRequest {
  message: string;
  provider?: "ollama" | "lmstudio" | "cloud";
  model?: string | null;
  conversation_id?: string | null;
}

export interface ChatTurnResponse {
  conversation_id: string;
  content: string;
  grounded: boolean;
  tool_calls: Array<Record<string, unknown>>;
  elapsed_ms: number;
  provider: string;
  model: string;
}

export interface ToolInfo {
  name: string;
  description: string;
}

export interface ToolsResponse {
  tools: ToolInfo[];
}

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${ENGINE_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!r.ok) {
    const body = await r.text();
    throw new Error(`HTTP ${r.status}: ${body}`);
  }
  return (await r.json()) as T;
}

export const api = {
  health: () => jsonFetch<HealthResponse>("/api/v1/health"),
  ready: () => jsonFetch<{ status: string; providers: Record<string, boolean> }>("/api/v1/health/ready"),
  version: () => jsonFetch<{ version: string; name: string }>("/api/v1/version"),
  providers: () => jsonFetch<ProvidersResponse>("/api/v1/providers"),
  listModels: (provider: string) =>
    jsonFetch<{ provider: string; models: string[] }>(`/api/v1/providers/${provider}/models`),
  listTools: () => jsonFetch<ToolsResponse>("/api/v1/ai/tools"),
  chat: (req: ChatRequest) =>
    jsonFetch<ChatTurnResponse>("/api/v1/ai/chat", {
      method: "POST",
      body: JSON.stringify(req),
    }),
};
