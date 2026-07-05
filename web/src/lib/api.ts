/**
 * Engine API client.
 *
 * Talks to corpusmind-engine over HTTP. In dev, Vite proxies /api → :8765.
 * In the Tauri desktop shell, the engine runs as a sidecar on 127.0.0.1:8765.
 */

export const ENGINE_BASE =
  (import.meta.env.VITE_ENGINE_URL as string | undefined) ?? ""; // empty → same-origin (proxied in dev)

// ----------------------------------------------------------------------- //
// Types
// ----------------------------------------------------------------------- //

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
  corpus_id?: string | null;
}

export interface EvidenceItem {
  kind: "concordance_line" | "stat" | "image_region" | "tool_result";
  ref: string;
  snippet: string;
}

export interface ChatTurnResponse {
  conversation_id: string;
  content: string;
  grounded: boolean;
  tool_calls: Array<Record<string, unknown>>;
  evidence: EvidenceItem[];
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

export interface Project {
  id: string;
  name: string;
  description: string;
  language: string;
  visibility: string;
  created_at: string;
  corpus_count: number;
}

export interface Corpus {
  id: string;
  project_id: string;
  name: string;
  language: string;
  pipeline_recipe: Record<string, unknown>;
  stats: Record<string, number>;
  created_at: string;
  document_count: number;
}

export interface Document {
  id: string;
  corpus_id: string;
  filename: string;
  format: string;
  encoding: string;
  detected_language: string | null;
  raw_size_bytes: number;
  meta: Record<string, unknown>;
  created_at: string;
}

export interface ConcordanceLine {
  line_id: string;
  document_id: string;
  document_filename: string;
  sentence_idx: number;
  token_idx: number;
  left: string;
  node: string;
  right: string;
  pos: string;
  lemma: string;
}

export interface ConcordanceResult {
  lines: ConcordanceLine[];
  total: number;
  query: Record<string, unknown>;
}

export interface FrequencyRow {
  item: string;
  freq: number;
  per_million: number;
  percent: number;
}

export interface FrequencyResult {
  unit: string;
  total_tokens: number;
  total_types: number;
  rows: FrequencyRow[];
  sttr: number;
}

export interface CollocationRow {
  collocate: string;
  O: number;
  fx: number;
  fy: number;
  N: number;
  mi?: number;
  t_score?: number;
  log_likelihood?: number;
  dice?: number;
  log_dice?: number;
  chi_square?: number;
  delta_p_y_given_x?: number;
  delta_p_x_given_y?: number;
}

export interface CollocationResult {
  node: string;
  window: number;
  min_freq: number;
  measures: string[];
  rows: CollocationRow[];
}

export interface KeynessRow {
  term: string;
  f1: number;
  f2: number;
  log_likelihood: number | null;
  chi_square: number | null;
  log_ratio: number | null;
  pct_diff: number | null;
  simple_maths: number | null;
  odds_ratio: number | null;
}

export interface KeynessResult {
  target_corpus_id: string;
  reference_corpus_id: string;
  measures: string[];
  positive_keywords: KeynessRow[];
  negative_keywords: KeynessRow[];
  N1: number;
  N2: number;
}

export interface DispersionResult {
  term: string;
  juillands_d: number;
  gries_dp: number;
  per_part_freqs: number[];
}

// ----------------------------------------------------------------------- //
// Fetch helper
// ----------------------------------------------------------------------- //

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

// ----------------------------------------------------------------------- //
// API surface
// ----------------------------------------------------------------------- //

export const api = {
  // --- Health & system ---
  health: () => jsonFetch<HealthResponse>("/api/v1/health"),
  ready: () => jsonFetch<{ status: string; providers: Record<string, boolean> }>("/api/v1/health/ready"),
  version: () => jsonFetch<{ version: string; name: string }>("/api/v1/version"),
  providers: () => jsonFetch<ProvidersResponse>("/api/v1/providers"),
  listModels: (provider: string) =>
    jsonFetch<{ provider: string; models: string[] }>(`/api/v1/providers/${provider}/models`),

  // --- Projects & corpora ---
  listProjects: () => jsonFetch<Project[]>("/api/v1/projects"),
  createProject: (name: string, language = "en", description = "") =>
    jsonFetch<Project>("/api/v1/projects", {
      method: "POST",
      body: JSON.stringify({ name, language, description }),
    }),
  getProject: (pid: string) => jsonFetch<Project>(`/api/v1/projects/${pid}`),
  deleteProject: (pid: string) =>
    jsonFetch<{ deleted: string }>(`/api/v1/projects/${pid}`, { method: "DELETE" }),

  listCorpora: (pid: string) => jsonFetch<Corpus[]>(`/api/v1/projects/${pid}/corpora`),
  createCorpus: (pid: string, name: string, language = "en") =>
    jsonFetch<Corpus>(`/api/v1/projects/${pid}/corpora`, {
      method: "POST",
      body: JSON.stringify({ name, language }),
    }),
  getCorpus: (cid: string) => jsonFetch<Corpus>(`/api/v1/corpora/${cid}`),
  deleteCorpus: (cid: string) =>
    jsonFetch<{ deleted: string }>(`/api/v1/corpora/${cid}`, { method: "DELETE" }),

  listDocuments: (cid: string) => jsonFetch<Document[]>(`/api/v1/corpora/${cid}/documents`),
  uploadDocuments: (cid: string, files: File[], language?: string) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    if (language) fd.append("language", language);
    return fetch(`${ENGINE_BASE}/api/v1/corpora/${cid}/documents`, { method: "POST", body: fd }).then(async (r) => {
      if (!r.ok) throw new Error(await r.text());
      return (await r.json()) as Document[];
    });
  },

  // --- Analysis ---
  concordance: (cid: string, query: string, level: "word" | "lemma" | "pos" = "word",
                window = 5, limit = 100, offset = 0, case_sensitive = false) =>
    jsonFetch<ConcordanceResult>(`/api/v1/corpora/${cid}/concordance`, {
      method: "POST",
      body: JSON.stringify({ query, level, window, limit, offset, case_sensitive }),
    }),

  frequency: (cid: string, unit: "word" | "lemma" | "pos" = "word",
              min_freq = 1, limit = 1000, include_punct = false) =>
    jsonFetch<FrequencyResult>(`/api/v1/corpora/${cid}/frequency`, {
      method: "POST",
      body: JSON.stringify({ unit, min_freq, limit, include_punct }),
    }),

  collocations: (cid: string, node: string, level: "word" | "lemma" = "word",
                 window = 5, min_freq = 3, measures?: string[], limit = 100) =>
    jsonFetch<CollocationResult>(`/api/v1/corpora/${cid}/collocations`, {
      method: "POST",
      body: JSON.stringify({ node, level, window, min_freq, measures, limit }),
    }),

  keyness: (cid: string, reference_corpus_id: string, min_freq = 5, limit = 100) =>
    jsonFetch<KeynessResult>(`/api/v1/corpora/${cid}/keyness`, {
      method: "POST",
      body: JSON.stringify({ reference_corpus_id, min_freq, limit }),
    }),

  dispersion: (cid: string, term: string, level: "word" | "lemma" = "word") =>
    jsonFetch<DispersionResult>(`/api/v1/corpora/${cid}/dispersion`, {
      method: "POST",
      body: JSON.stringify({ term, level }),
    }),

  // --- Export ---
  exportConcordanceXlsx: (cid: string, query: string, level = "word", window = 5, limit = 1000) =>
    fetch(`${ENGINE_BASE}/api/v1/corpora/${cid}/export/concordance.xlsx`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, level, window, limit }),
    }).then((r) => r.blob()),

  exportFrequencyXlsx: (cid: string, unit = "word", limit = 1000) =>
    fetch(`${ENGINE_BASE}/api/v1/corpora/${cid}/export/frequency.xlsx`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ unit, limit }),
    }).then((r) => r.blob()),

  exportCollocationsXlsx: (cid: string, node: string, level = "word", window = 5, min_freq = 3) =>
    fetch(`${ENGINE_BASE}/api/v1/corpora/${cid}/export/collocations.xlsx`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ node, level, window, min_freq }),
    }).then((r) => r.blob()),

  exportKeynessXlsx: (cid: string, reference_corpus_id: string) =>
    fetch(`${ENGINE_BASE}/api/v1/corpora/${cid}/export/keyness.xlsx`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reference_corpus_id }),
    }).then((r) => r.blob()),

  exportMethodsPdf: (cid: string) =>
    fetch(`${ENGINE_BASE}/api/v1/corpora/${cid}/methods.pdf`).then((r) => r.blob()),

  // --- AI ---
  listTools: () => jsonFetch<ToolsResponse>("/api/v1/ai/tools"),
  chat: (req: ChatRequest) =>
    jsonFetch<ChatTurnResponse>("/api/v1/ai/chat", {
      method: "POST",
      body: JSON.stringify(req),
    }),
  listConversations: () => jsonFetch<Array<Record<string, unknown>>>("/api/v1/ai/conversations"),
  getConversation: (cid: string) => jsonFetch<Record<string, unknown>>(`/api/v1/ai/conversations/${cid}`),
};

/** Helper: trigger a browser download for a Blob. */
export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
