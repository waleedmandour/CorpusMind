/**
 * Shared types between corpusmind-web and corpusmind-desktop.
 *
 * The canonical API schema is the engine's OpenAPI document at
 * http://127.0.0.1:8765/openapi.json — generate `api-schema.ts` from it via
 *   cd shared && npm run generate
 * (requires the engine to be running locally).
 *
 * The hand-written types below cover the Phase 0 surface; Phase 1+ should
 * switch to the generated `api-schema.ts` and use `paths`/`components`
 * directly.
 */

// -----------------------------------------------------------------------
// Health & system
// -----------------------------------------------------------------------

export interface HealthResponse {
  status: string;
  engine: string;
  version: string;
}

export interface ReadyResponse {
  status: string;
  providers: Record<string, boolean>;
}

export type ProviderName = "ollama" | "lmstudio" | "cloud";

export interface ProviderInfo {
  name: ProviderName;
  healthy: boolean;
  base_url?: string;
  default_model?: string;
  error?: string;
}

export interface ProvidersResponse {
  providers: ProviderInfo[];
}

export interface PublicSettings {
  cloud_provider: ProviderName | "none";
  cloud_disabled_hard: boolean;
  ollama_base_url: string;
  lmstudio_base_url: string;
  data_dir: string;
}

// -----------------------------------------------------------------------
// AI Assistant (§11)
// -----------------------------------------------------------------------

export interface ChatRequest {
  message: string;
  provider?: ProviderName;
  model?: string | null;
  conversation_id?: string | null;
}

export interface ChatTurnResponse {
  conversation_id: string;
  content: string;
  /** true iff at least one tool was invoked during this turn — the load-bearing
   * flag the UI uses to render the "grounded" vs "unground" badge (§11.1). */
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

/** Audit-trail export of a full conversation (§4.8). */
export interface ConversationExport {
  id: string;
  provider: string;
  model: string;
  messages: Array<{ role: string; content: string; name?: string }>;
  turns: Array<{
    role: "assistant";
    content: string;
    grounded: boolean;
    evidence: Array<{
      kind: "concordance_line" | "stat" | "image_region" | "tool_result";
      ref: string;
      snippet: string;
    }>;
    tool_calls: Array<Record<string, unknown>>;
    elapsed_ms: number;
  }>;
}

// -----------------------------------------------------------------------
// Stats (§12) — exported so the desktop + web share the same enum
// -----------------------------------------------------------------------

export const COLLOCATION_MEASURES = [
  "mi",
  "t_score",
  "log_likelihood",
  "dice",
  "log_dice",
  "chi_square",
  "delta_p",
] as const;

export const KEYNESS_MEASURES = [
  "log_likelihood",
  "chi_square",
  "log_ratio",
  "pct_diff",
  "simple_maths",
  "odds_ratio",
] as const;

export const DISPERSION_MEASURES = ["juillands_d", "gries_dp"] as const;

export type CollocationMeasure = (typeof COLLOCATION_MEASURES)[number];
export type KeynessMeasure = (typeof KEYNESS_MEASURES)[number];
export type DispersionMeasure = (typeof DISPERSION_MEASURES)[number];
