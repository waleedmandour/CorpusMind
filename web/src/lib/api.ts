/**
 * Engine API client.
 *
 * Talks to corpusmind-engine over HTTP.
 *
 *  - `vite dev` (localhost:5173):        relative "/api/..." paths, proxied to
 *                                        :8765 by vite.config.ts's server.proxy.
 *  - Hosted PWA (e.g. Vercel):            VITE_ENGINE_URL baked in at build time
 *                                        (see docs/BUILD_GUIDE.md).
 *  - Tauri desktop app (packaged build):  the bundled frontend is served from a
 *                                        tauri://localhost / *.localhost origin,
 *                                        NOT the Vite dev server, so relative
 *                                        "/api/..." fetches never reach the
 *                                        sidecar unless VITE_ENGINE_URL was
 *                                        baked in at build time. We self-heal:
 *                                        if no VITE_ENGINE_URL was configured
 *                                        AND we detect we're running inside
 *                                        Tauri, default to the sidecar's fixed,
 *                                        hardcoded address (see ENGINE_HOST /
 *                                        ENGINE_PORT constants in
 *                                        desktop/src-tauri/src/lib.rs — always
 *                                        127.0.0.1:8765 for the desktop shell).
 *
 * CRITICAL (Windows desktop fix, 2026-07):
 *   Inside the Tauri webview we use @tauri-apps/plugin-http's `fetch()`
 *   instead of the browser's native `fetch()`. The plugin routes the request
 *   through Rust's `reqwest`, which is NOT subject to the webview's CORS
 *   preflight, Private/Local Network Access (PNA/LNA) restrictions, or
 *   mixed-content rules. This is the Tauri team's official recommendation
 *   (tauri-apps/tauri#11260) and eliminates the "Detected (API unreachable)"
 *   amber state on Windows desktop builds where the webview origin
 *   (http://tauri.localhost) cannot reach the sidecar (http://127.0.0.1:8765)
 *   via native fetch due to these browser-security checks.
 *   In browser/PWA mode (not Tauri) we fall back to the native fetch.
 */

/**
 * Detect whether the frontend is running inside the Tauri desktop webview.
 *
 * Tauri v2 injects `window.__TAURI_INTERNALS__` (the IPC bridge) even when
 * `withGlobalTauri` is false (this project's config). `window.__TAURI__` is
 * only present when `withGlobalTauri` is true, but we check it too for
 * robustness across configs. This helper is exported so other modules
 * (HomeView, SettingsView) can reuse it instead of re-implementing the same
 * global sniff.
 */
export function isTauriRuntime(): boolean {
  if (typeof window === "undefined") return false;
  const w = window as any;
  return typeof w.__TAURI_INTERNALS__ !== "undefined" || typeof w.__TAURI__ !== "undefined";
}

const configuredEngineUrl = import.meta.env.VITE_ENGINE_URL as string | undefined;

export const ENGINE_BASE =
  configuredEngineUrl ?? (isTauriRuntime() ? "http://127.0.0.1:8765" : "");
// empty string ("") → same-origin, relies on the Vite dev proxy in `vite dev`.

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

// ----------------------------------------------------------------------- //
// Native (Rust-side) provider health — the authoritative source of truth.
//
// The `all_providers_health` Tauri command checks engine + Ollama + LM Studio
// directly from Rust (via reqwest with .no_proxy()), bypassing the webview's
// fetch path entirely. This avoids the circular dependency where Ollama/LM
// Studio health was previously read from the engine's /api/v1/providers
// endpoint — which fails when the engine itself is down, making ALL
// providers appear "not detected" even when they're running fine.
//
// The UI uses this as the PRIMARY status source; the engine's /providers
// endpoint is now only used for the model list (default_model, base_url).
// ----------------------------------------------------------------------- //

export interface NativeProviderHealth {
  healthy: boolean;
  url: string;
  error: string | null;
  path?: string;
}

export interface NativeProvidersHealth {
  engine: NativeProviderHealth;
  ollama: NativeProviderHealth;
  lmstudio: NativeProviderHealth;
}

/** Lazy-loaded Tauri invoke, cached after first call. */
let _invoke: ((cmd: string, args?: Record<string, unknown>) => Promise<unknown>) | null = null;
async function getInvoke(): Promise<typeof import("@tauri-apps/api/core").invoke> {
  if (_invoke) return _invoke as typeof import("@tauri-apps/api/core").invoke;
  const mod = await import("@tauri-apps/api/core");
  _invoke = mod.invoke;
  return mod.invoke;
}

/**
 * Query the Rust-side `all_providers_health` command for the authoritative
 * status of all three providers. Returns null when not running inside Tauri
 * (browser/PWA mode — the UI falls back to the engine's /providers endpoint).
 */
export async function nativeProvidersHealth(): Promise<NativeProvidersHealth | null> {
  if (!isTauriRuntime()) return null;
  try {
    const invoke = await getInvoke();
    const raw = (await invoke("all_providers_health")) as string;
    return JSON.parse(raw) as NativeProvidersHealth;
  } catch (e) {
    console.error("[nativeProvidersHealth] failed:", e);
    return null;
  }
}

/** Restart the engine sidecar from Rust. Returns the result message. */
export async function nativeRestartEngine(): Promise<{
  ok: boolean;
  engine_running: boolean;
  message: string;
  diagnostics?: { program: string; args: string; working_dir: string; hint: string };
}> {
  if (!isTauriRuntime()) {
    throw new Error("Engine restart is only available in the desktop app.");
  }
  const invoke = await getInvoke();
  const raw = (await invoke("restart_engine")) as string;
  return JSON.parse(raw);
}

/** Restart Ollama from Rust. Returns the result message + path. */
export async function nativeRestartOllama(): Promise<{
  ok: boolean;
  ollama_running: boolean;
  ollama_path: string;
  message: string;
  hint?: string;
}> {
  if (!isTauriRuntime()) {
    throw new Error("Ollama restart is only available in the desktop app.");
  }
  const invoke = await getInvoke();
  const raw = (await invoke("restart_ollama")) as string;
  return JSON.parse(raw);
}

/** Check LM Studio health from Rust (no auto-start — it's a GUI app). */
export async function nativeCheckLmStudio(): Promise<{
  ok: boolean;
  lmstudio_running: boolean;
  url?: string;
  message: string;
}> {
  if (!isTauriRuntime()) {
    throw new Error("LM Studio check is only available in the desktop app.");
  }
  const invoke = await getInvoke();
  const raw = (await invoke("check_lmstudio")) as string;
  return JSON.parse(raw);
}

/** Fetch engine stdout/stderr logs from Rust (for the diagnostics panel). */
export async function nativeEngineLogs(): Promise<{
  ok: boolean;
  stdout_path: string;
  stderr_path: string;
  stdout: string;
  stderr: string;
}> {
  if (!isTauriRuntime()) {
    throw new Error("Engine logs are only available in the desktop app.");
  }
  const invoke = await getInvoke();
  const raw = (await invoke("engine_logs")) as string;
  return JSON.parse(raw);
}

/** Verify the bundled sidecar binary exists (for the diagnostics panel). */
export async function nativeVerifySidecar(): Promise<{
  ok: boolean;
  sidecar_found: boolean;
  sidecar_path: string;
  resource_dir: string;
  layout: string;
  target_triple: string;
  expected_name?: string;
  resolved_program: string;
  resolved_args: string;
  resolved_working_dir: string;
  message: string;
}> {
  if (!isTauriRuntime()) {
    throw new Error("Sidecar verification is only available in the desktop app.");
  }
  const invoke = await getInvoke();
  const raw = (await invoke("verify_sidecar")) as string;
  return JSON.parse(raw);
}

/**
 * Open a native file picker dialog to select a local model file (.gguf).
 * Returns the selected file path, or throws if the user cancelled.
 * Used by the Ollama "Import from file" flow so the user doesn't have to
 * type the full path manually.
 */
export async function nativePickModelFile(): Promise<{
  ok: boolean;
  path: string | null;
  message: string;
}> {
  if (!isTauriRuntime()) {
    throw new Error("File picker is only available in the desktop app.");
  }
  const invoke = await getInvoke();
  const raw = (await invoke("pick_model_file")) as string;
  return JSON.parse(raw);
}

/**
 * Open a native file picker dialog to select multiple corpus text files.
 * Returns the selected file paths (array), or empty array if cancelled.
 * Used by the "Your Corpus" and "Reference Corpus" upload flows.
 */
export async function nativePickCorpusFiles(): Promise<{
  ok: boolean;
  paths: string[];
  count: number;
  message: string;
}> {
  if (!isTauriRuntime()) {
    throw new Error("File picker is only available in the desktop app.");
  }
  const invoke = await getInvoke();
  const raw = (await invoke("pick_corpus_files")) as string;
  return JSON.parse(raw);
}

/**
 * Read a local file (by path) into a File object. Used to convert
 * native-picked file paths into File objects for upload via FormData.
 * Inside Tauri, the file is read via the fs plugin; in browser mode,
 * this throws (the caller should use the <input type="file"> path instead).
 */
export async function nativeReadFile(path: string): Promise<File> {
  if (!isTauriRuntime()) {
    throw new Error("File reading is only available in the desktop app.");
  }
  // Use the Tauri fs plugin to read the file as binary
  const fs = await import("@tauri-apps/plugin-fs");
  const data = await fs.readFile(path);
  const filename = path.split(/[/\\]/).pop() ?? "file";
  return new File([data], filename);
}

/**
 * Upload corpus files directly via Rust (bypasses the webview's FormData
 * limitation). Reads files from disk by path and POSTs them to the engine
 * via reqwest multipart. This is the reliable upload path inside Tauri.
 *
 * Returns the parsed Document[] list from the engine, or throws on error.
 */
export async function nativeUploadCorpusFiles(
  cid: string,
  paths: string[],
  language?: string,
): Promise<Document[]> {
  if (!isTauriRuntime()) {
    throw new Error("Direct upload is only available in the desktop app.");
  }
  const invoke = await getInvoke();
  const raw = (await invoke("upload_corpus_files", {
    cid,
    paths,
    language: language ?? null,
  })) as string;
  const result = JSON.parse(raw) as {
    ok: boolean;
    status?: number;
    body?: string;
    error?: string;
    files_uploaded?: number;
    errors?: string[];
  };
  if (!result.ok) {
    const errMsg = result.error || result.errors?.join("; ") || "Upload failed";
    throw new Error(errMsg);
  }
  // The engine returns a JSON array of Document objects in result.body
  try {
    return JSON.parse(result.body || "[]") as Document[];
  } catch {
    return [];
  }
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
  confidence: number;
  confidence_reasoning: string;
  needs_validation: boolean;
  mcqs: MCQ[];
}

export interface MCQ {
  question: string;
  options: string[];
  correct_answer: number;
  evidence_ref: string;
  explanation: string;
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
  genre: string;
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
// Phase 2 types
// ----------------------------------------------------------------------- //

export interface NGramRow {
  ngram: string;
  freq: number;
  per_million: number;
  range: number;
  range_percent: number;
}

export interface NGramResult {
  n: number;
  total_tokens: number;
  rows: NGramRow[];
  min_freq: number;
  min_range: number;
}

export interface POSDistributionRow {
  pos: string;
  freq: number;
  percent: number;
}

export interface POSNGramRow {
  pattern: string;
  freq: number;
}

export interface POSAnalysisResult {
  total_tokens: number;
  distribution: POSDistributionRow[];
  pos_ngrams: POSNGramRow[];
  n: number;
}

export interface GrammarMatch {
  pattern: string;
  doc: string;
  sent: number;
  evidence_id: string;
  [key: string]: unknown;
}

export interface GrammarResult {
  patterns: Record<string, GrammarMatch[]>;
  counts: Record<string, number>;
}

export interface DependencyRow {
  governor: string;
  dependent: string;
  relation: string;
  freq: number;
  examples: string[];
}

export interface DependencyResult {
  relation: string;
  rows: DependencyRow[];
}

export interface DiscourseCategory {
  freq: number;
  per_million: number;
  examples: Array<{ cue: string; evidence_id: string; sentence_preview: string }>;
}

export interface DiscourseResult {
  categories: Record<string, DiscourseCategory>;
  total_tokens: number;
  taxonomy: string;
}

export interface VocabBand {
  band: string;
  freq: number;
  percent: number;
}

export interface VocabProfileResult {
  total_tokens: number;
  total_types: number;
  bands: VocabBand[];
  rare_words: Array<{ word: string; freq: number }>;
  academic_words: Array<{ word: string; freq: number }>;
}

export interface SentimentResult {
  total_sentences: number;
  positive: number;
  negative: number;
  neutral: number;
  avg_score: number;
  timeline: Array<{ doc: string; sent: number; score: number; pos_hits: number; neg_hits: number }>;
}

export interface MetaphorCandidate {
  word: string;
  lemma: string;
  pos: string;
  subject: string;
  subject_lemma: string;
  sentence: string;
  evidence_id: string;
  reason: string;
}

export interface MetaphorResult {
  candidates: MetaphorCandidate[];
  pipeline: string;
  verified_count: number;
}

// ----------------------------------------------------------------------- //
// Phase 3 types — Arabic (8.21)
// ----------------------------------------------------------------------- //

export interface ArabicToken {
  text: string;
  lemma: string;
  root: string;
  pattern: string;
  pos: string;
  stem: string;
  buckwalter: string;
  dediacritized: string;
}

export interface ArabicAnalysisResult {
  text: string;
  backend: string;
  detected_dialect: string;
  token_count: number;
  tokens: ArabicToken[];
}

export interface ArabicRootRow {
  token: string;
  root: string;
  pattern: string;
  lemma: string;
  pos: string;
  buckwalter: string;
}

export interface ArabicBackendInfo {
  name: string;
  available: boolean;
  version?: string;
  model?: string;
  dialects_supported?: string[];
}

// Phase 3 polish — bilingual (8.22)
export interface AlignedPair {
  ar_sentence: string;
  en_sentence: string;
  ar_sent_idx: number;
  en_sent_idx: number;
  confidence: number;
  pair_type: string;
}

export interface AlignmentResult {
  method: string;
  ar_doc_count: number;
  en_doc_count: number;
  pair_count: number;
  pairs: AlignedPair[];
}

export interface ParallelConcordancePair {
  ar_line_id: string;
  ar_left: string;
  ar_node: string;
  ar_right: string;
  ar_sentence: string;
  en_sentence: string;
  en_line_id: string;
  confidence: number;
}

export interface ParallelConcordanceResult {
  query: string;
  total: number;
  pairs: ParallelConcordancePair[];
}

export interface TranslationResult {
  word: string;
  direction: string;
  equivalents: string[];
  source: string;
}

// ----------------------------------------------------------------------- //
// Phase 4 types — Vision (9.1–9.10)
// ----------------------------------------------------------------------- //

export interface ImageSet {
  id: string;
  corpus_id: string;
  name: string;
  image_count: number;
  created_at: string;
}

export interface ImageRecord {
  id: string;
  image_set_id: string;
  filename: string;
  format: string;
  width: number;
  height: number;
  size_bytes: number;
  caption: string;
  created_at: string;
}

export interface ImageAnalysis {
  image_id: string;
  filename: string;
  dimensions: string;
  analysis: {
    ocr: { text: string; confidence: number; word_count: number; engine: string; language: string };
    colours: {
      dominant_colours: Array<{ hex: string; rgb: number[]; percent: number }>;
      warm_cold_balance: number;
      brightness: number;
      contrast: number;
      saturation: number;
      colour_symbolism_notes: string[];
    };
    composition: {
      information_value: Record<string, number>;
      rule_of_thirds_intersections: Array<{ x: number; y: number; salience: number }>;
      salience_centre: [number, number];
      visual_balance: number;
      framing_balance: number;
      vectors: any[];
    };
  };
  caption: string;
}

export interface VisualGrammarClaim {
  metafunction: string;
  category: string;
  claim: string;
  evidence: string[];
  confidence: number;
}

export interface VisualGrammarResult {
  image_id: string;
  framework: string;
  claims: VisualGrammarClaim[];
  scores: {
    representational: { claim_count: number; avg_confidence: number };
    interactive: { claim_count: number; avg_confidence: number };
    compositional: { claim_count: number; avg_confidence: number };
  };
}

export interface ImageRegion {
  region_id: string;
  bbox: [number, number, number, number];
  centroid: [number, number];
  mean_colour: [number, number, number];
  salience: number;
  descriptor: string;
}

export interface Alignment {
  region_id: string;
  span_id: string;
  confidence: number;
  match_reason: string;
  region_descriptor: string;
  span_text: string;
}

export interface CrossModalRelation {
  relation_type: string;
  alignment_refs: string[];
  description: string;
  confidence: number;
}

export interface AlignmentResult {
  image_id: string;
  text: string;
  method: string;
  note: string;
  regions: ImageRegion[];
  spans: Array<{ span_id: string; text: string; start: number; end: number; pos_hint: string }>;
  alignments: Alignment[];
  cross_modal_relations: CrossModalRelation[];
}

// Phase 5 — multimodal discourse (9.11–9.18)
export interface DiscourseClaim {
  framework: string;
  category: string;
  claim: string;
  evidence: string[];
  confidence: number;
}

export interface DiscourseResult {
  analysis_type: string;
  framework: string;
  claims: DiscourseClaim[];
  summary: string;
}

// ----------------------------------------------------------------------- //
// Fetch helper
//
// Inside the Tauri desktop webview, we use @tauri-apps/plugin-http's `fetch()`
// which executes on the Rust side (reqwest) and is immune to CORS / PNA / LNA.
// In browser/PWA mode we use the native `fetch()` (same-origin via Vite proxy
// or cross-origin with proper CORS headers on the engine).
//
// The plugin is lazy-loaded so the PWA build doesn't bundle Tauri APIs.
// ----------------------------------------------------------------------- //

/** Lazy-loaded Tauri HTTP plugin fetch. Cached after first call. */
let _tauriFetch: ((input: string, init?: RequestInit) => Promise<Response>) | null = null;
async function getTauriFetch(): Promise<(input: string, init?: RequestInit) => Promise<Response>> {
  if (_tauriFetch) return _tauriFetch;
  const mod = await import("@tauri-apps/plugin-http");
  // The plugin's fetch has the same signature as the native fetch but executes
  // on the Rust side (reqwest). We cast to our narrower type for TS compatibility.
  _tauriFetch = mod.fetch as unknown as (input: string, init?: RequestInit) => Promise<Response>;
  return _tauriFetch;
}

/**
 * Unified fetch that picks the Tauri plugin inside the desktop webview and
 * the native fetch everywhere else. The Tauri plugin requires an absolute
 * URL, so we always pass the full `${ENGINE_BASE}${path}` (in Tauri mode
 * ENGINE_BASE is "http://127.0.0.1:8765").
 */
async function smartFetch(path: string, init?: RequestInit): Promise<Response> {
  const url = `${ENGINE_BASE}${path}`;
  if (isTauriRuntime()) {
    const tFetch = await getTauriFetch();
    return tFetch(url, init);
  }
  return fetch(url, init);
}

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await smartFetch(path, {
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
  createCorpus: (pid: string, name: string, language = "en", genre = "mixed") =>
    jsonFetch<Corpus>(`/api/v1/projects/${pid}/corpora`, {
      method: "POST",
      body: JSON.stringify({ name, language, genre }),
    }),
  getCorpus: (cid: string) => jsonFetch<Corpus>(`/api/v1/corpora/${cid}`),
  deleteCorpus: (cid: string) =>
    jsonFetch<{ deleted: string }>(`/api/v1/corpora/${cid}`, { method: "DELETE" }),

  listDocuments: (cid: string) => jsonFetch<Document[]>(`/api/v1/corpora/${cid}/documents`),
  // v0.1.17: delete a single document from a corpus
  deleteDocument: (cid: string, did: string) =>
    jsonFetch<{ deleted: string; filename: string; remaining_documents: number }>(
      `/api/v1/corpora/${cid}/documents/${did}`, { method: "DELETE" }
    ),
  // v0.1.17: recompile (re-run NLP pipeline) on all documents in a corpus
  recompileCorpus: (cid: string) =>
    jsonFetch<{ recompiled: number; total_documents: number; token_count: number; type_count: number }>(
      `/api/v1/corpora/${cid}/recompile`, { method: "POST" }
    ),
  uploadDocuments: (cid: string, files: File[], language?: string) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    if (language) fd.append("language", language);
    // Use smartFetch (Tauri plugin-http inside Tauri, native fetch in browser)
    // so file uploads bypass CORS/PNA restrictions inside the desktop webview.
    // NOTE: Do NOT set Content-Type — the browser sets it automatically with
    // the correct multipart boundary for FormData.
    return smartFetch(`/api/v1/corpora/${cid}/documents`, { method: "POST", body: fd }).then(async (r) => {
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

  // --- Phase 2 analysis ---
  ngrams: (cid: string, n = 2, min_freq = 5, min_range = 1, limit = 200) =>
    jsonFetch<NGramResult>(`/api/v1/corpora/${cid}/ngrams`, {
      method: "POST",
      body: JSON.stringify({ n, min_freq, min_range, limit }),
    }),

  posAnalysis: (cid: string, n = 2, min_freq = 2, limit = 100) =>
    jsonFetch<POSAnalysisResult>(`/api/v1/corpora/${cid}/pos-analysis`, {
      method: "POST",
      body: JSON.stringify({ n, min_freq, limit }),
    }),

  grammar: (cid: string, patterns?: string[], limit = 50) =>
    jsonFetch<GrammarResult>(`/api/v1/corpora/${cid}/grammar`, {
      method: "POST",
      body: JSON.stringify({ patterns, limit }),
    }),

  dependencies: (cid: string, relation = "nsubj", limit = 100) =>
    jsonFetch<DependencyResult>(`/api/v1/corpora/${cid}/dependencies`, {
      method: "POST",
      body: JSON.stringify({ relation, limit }),
    }),

  discourse: (cid: string) =>
    jsonFetch<DiscourseResult>(`/api/v1/corpora/${cid}/discourse`, { method: "POST" }),

  vocabProfile: (cid: string, rare_threshold = 1, limit = 100) =>
    jsonFetch<VocabProfileResult>(`/api/v1/corpora/${cid}/vocab-profile`, {
      method: "POST",
      body: JSON.stringify({ rare_threshold, limit }),
    }),

  sentiment: (cid: string) =>
    jsonFetch<SentimentResult>(`/api/v1/corpora/${cid}/sentiment`, { method: "POST" }),

  metaphorCandidates: (cid: string, limit = 50) =>
    jsonFetch<MetaphorResult>(`/api/v1/corpora/${cid}/metaphor-candidates`, {
      method: "POST",
      body: JSON.stringify({ limit }),
    }),

  // --- Phase 3 Arabic (8.21) ---
  arabicAnalyze: (text: string, dialect = "msa") =>
    jsonFetch<ArabicAnalysisResult>(`/api/v1/arabic/analyze`, {
      method: "POST",
      body: JSON.stringify({ text, dialect }),
    }),

  arabicRoots: (text: string) =>
    jsonFetch<{ roots: ArabicRootRow[] }>(`/api/v1/arabic/roots`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  arabicClitics: (text: string) =>
    jsonFetch<{ segments: Array<{ surface: string; stem: string; pos: string }> }>(`/api/v1/arabic/clitics`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  arabicBuckwalter: (text: string) =>
    jsonFetch<{ buckwalter: string; original: string }>(`/api/v1/arabic/buckwalter`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  arabicDediacritize: (text: string) =>
    jsonFetch<{ dediacritized: string; original: string }>(`/api/v1/arabic/dediacritize`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  arabicNormalize: (text: string) =>
    jsonFetch<{ normalized: string; original: string }>(`/api/v1/arabic/normalize`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  arabicDialect: (text: string) =>
    jsonFetch<{ dialect_distribution: Record<string, number> }>(`/api/v1/arabic/dialect`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  arabicRegister: (text: string) =>
    jsonFetch<{ register_distribution: Record<string, number> }>(`/api/v1/arabic/register`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  arabicBackends: () =>
    jsonFetch<{ backends: ArabicBackendInfo[] }>(`/api/v1/arabic/backends`),

  // --- Phase 3 polish — bilingual (8.22) ---
  bilingualAlign: (ar_corpus_id: string, en_corpus_id: string) =>
    jsonFetch<AlignmentResult>(`/api/v1/bilingual/align`, {
      method: "POST",
      body: JSON.stringify({ ar_corpus_id, en_corpus_id }),
    }),

  parallelConcordance: (ar_corpus_id: string, en_corpus_id: string, query: string,
                        level = "lemma", window = 5, limit = 50) =>
    jsonFetch<ParallelConcordanceResult>(`/api/v1/bilingual/parallel-concordance`, {
      method: "POST",
      body: JSON.stringify({ ar_corpus_id, en_corpus_id, query, level, window, limit }),
    }),

  translate: (word: string, direction = "ar-en") =>
    jsonFetch<TranslationResult>(`/api/v1/bilingual/translate`, {
      method: "POST",
      body: JSON.stringify({ word, direction }),
    }),

  // --- Phase 4 Vision (9.1–9.10) ---
  createImageSet: (cid: string, name: string) =>
    jsonFetch<ImageSet>(`/api/v1/corpora/${cid}/image-sets`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),

  listImageSets: (cid: string) =>
    jsonFetch<ImageSet[]>(`/api/v1/corpora/${cid}/image-sets`),

  uploadImages: (isetId: string, files: File[], caption?: string) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    if (caption) fd.append("captions", caption);
    return smartFetch(`/api/v1/image-sets/${isetId}/images`, {
      method: "POST",
      body: fd,
    }).then(async (r) => {
      if (!r.ok) throw new Error(await r.text());
      return (await r.json()) as ImageRecord[];
    });
  },

  listImages: (isetId: string) =>
    jsonFetch<ImageRecord[]>(`/api/v1/image-sets/${isetId}/images`),

  getImageAnalysis: (imgId: string) =>
    jsonFetch<ImageAnalysis>(`/api/v1/images/${imgId}/analysis`),

  getVisualGrammar: (imgId: string) =>
    jsonFetch<VisualGrammarResult>(`/api/v1/images/${imgId}/visual-grammar`, { method: "POST" }),

  alignImageText: (imgId: string, text: string) =>
    jsonFetch<AlignmentResult>(`/api/v1/images/${imgId}/align`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  // --- Phase 5 multimodal discourse (9.11–9.18) ---
  socialSemiotic: (imgId: string) =>
    jsonFetch<DiscourseResult>(`/api/v1/images/${imgId}/social-semiotic`, { method: "POST" }),

  cda: (imgId: string, framework = "fairclough") =>
    jsonFetch<DiscourseResult>(`/api/v1/images/${imgId}/cda`, {
      method: "POST",
      body: JSON.stringify({ framework }),
    }),

  persuasion: (imgId: string) =>
    jsonFetch<DiscourseResult>(`/api/v1/images/${imgId}/persuasion`, { method: "POST" }),

  framing: (imgId: string) =>
    jsonFetch<DiscourseResult>(`/api/v1/images/${imgId}/framing`, { method: "POST" }),

  narrative: (imgId: string) =>
    jsonFetch<DiscourseResult>(`/api/v1/images/${imgId}/narrative`, { method: "POST" }),

  visualMetaphor: (imgId: string) =>
    jsonFetch<DiscourseResult>(`/api/v1/images/${imgId}/visual-metaphor`, { method: "POST" }),

  emotion: (imgId: string) =>
    jsonFetch<DiscourseResult>(`/api/v1/images/${imgId}/emotion`, { method: "POST" }),

  cultural: (imgId: string) =>
    jsonFetch<DiscourseResult>(`/api/v1/images/${imgId}/cultural`, { method: "POST" }),

  facialAnalysis: (imgId: string) =>
    jsonFetch<{ image_id: string; face_count: number; model: string; consent_verified: boolean; ethics_notice: string; faces: any[] }>(`/api/v1/images/${imgId}/facial-analysis`, { method: "POST" }),

  facialAnalysisStatus: () =>
    jsonFetch<{ enabled: boolean; notice: string }>(`/api/v1/facial-analysis/status`),

  cdaFrameworks: () =>
    jsonFetch<{ frameworks: Record<string, string> }>(`/api/v1/cda-frameworks`),

  // --- Phase 6 research workflow (8.23) + collaboration (10.2) ---
  savedSearches: {
    list: (pid: string) =>
      jsonFetch<any[]>(`/api/v1/projects/${pid}/saved-searches`),
    create: (pid: string, name: string, query: string, searchType = "concordance",
             corpusId?: string, parameters?: Record<string, unknown>) =>
      jsonFetch<any>(`/api/v1/projects/${pid}/saved-searches`, {
        method: "POST",
        body: JSON.stringify({ name, query, search_type: searchType, corpus_id: corpusId, parameters }),
      }),
    delete: (sid: string) =>
      jsonFetch<{ deleted: string }>(`/api/v1/saved-searches/${sid}`, { method: "DELETE" }),
  },
  bookmarks: {
    list: (pid: string) =>
      jsonFetch<any[]>(`/api/v1/projects/${pid}/bookmarks`),
    create: (pid: string, corpusId: string, refType: string, refId: string,
             label = "", note = "") =>
      jsonFetch<any>(`/api/v1/projects/${pid}/bookmarks`, {
        method: "POST",
        body: JSON.stringify({ corpus_id: corpusId, reference_type: refType, reference_id: refId, label, note }),
      }),
    delete: (bid: string) =>
      jsonFetch<{ deleted: string }>(`/api/v1/bookmarks/${bid}`, { method: "DELETE" }),
  },
  favorites: {
    list: (pid: string) =>
      jsonFetch<any[]>(`/api/v1/projects/${pid}/favorites`),
    create: (pid: string, itemType: string, itemId: string) =>
      jsonFetch<any>(`/api/v1/projects/${pid}/favorites`, {
        method: "POST",
        body: JSON.stringify({ item_type: itemType, item_id: itemId }),
      }),
    delete: (fid: string) =>
      jsonFetch<{ deleted: string }>(`/api/v1/favorites/${fid}`, { method: "DELETE" }),
  },
  sharing: {
    share: (pid: string, visibility = "private") =>
      jsonFetch<any>(`/api/v1/projects/${pid}/share`, {
        method: "POST",
        body: JSON.stringify({ visibility }),
      }),
    get: (pid: string) =>
      jsonFetch<any>(`/api/v1/projects/${pid}/share`),
    unshare: (pid: string) =>
      jsonFetch<{ unshared: string }>(`/api/v1/projects/${pid}/share`, { method: "DELETE" }),
    sync: (pid: string, eventType = "push", summary = "") =>
      jsonFetch<any>(`/api/v1/projects/${pid}/sync`, {
        method: "POST",
        body: JSON.stringify({ event_type: eventType, summary }),
      }),
    syncEvents: (pid: string) =>
      jsonFetch<any[]>(`/api/v1/projects/${pid}/sync-events`),
  },
  encryptionStatus: () =>
    jsonFetch<{ enabled: boolean; method: string; notice: string; key_present: boolean }>(`/api/v1/encryption/status`),

  // --- Export ---
  // Multi-format export: xlsx, csv, tsv, txt, json. The old .xlsx-only
  // endpoints are kept for backwards compatibility but the frontend now
  // uses these format-parameterized versions.
  exportConcordance: (cid: string, query: string, fmt: ExportFormat = "xlsx", level = "word", window = 5, limit = 1000) =>
    smartFetch(`/api/v1/corpora/${cid}/export/concordance?fmt=${fmt}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, level, window, limit }),
    }).then((r) => r.blob()),

  exportFrequency: (cid: string, unit = "word", fmt: ExportFormat = "xlsx", limit = 1000) =>
    smartFetch(`/api/v1/corpora/${cid}/export/frequency?fmt=${fmt}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ unit, limit }),
    }).then((r) => r.blob()),

  exportCollocations: (cid: string, node: string, fmt: ExportFormat = "xlsx", level = "word", window = 5, min_freq = 3) =>
    smartFetch(`/api/v1/corpora/${cid}/export/collocations?fmt=${fmt}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ node, level, window, min_freq }),
    }).then((r) => r.blob()),

  exportKeyness: (cid: string, reference_corpus_id: string, fmt: ExportFormat = "xlsx") =>
    smartFetch(`/api/v1/corpora/${cid}/export/keyness?fmt=${fmt}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reference_corpus_id }),
    }).then((r) => r.blob()),

  // Collocation network diagram export (SVG vector + PNG raster)
  exportCollocationNetworkSvg: (cid: string, node: string, level = "word", window = 5, min_freq = 3) =>
    smartFetch(`/api/v1/corpora/${cid}/export/collocations.network.svg`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ node, level, window, min_freq }),
    }).then((r) => r.blob()),

  exportCollocationNetworkPng: (cid: string, node: string, level = "word", window = 5, min_freq = 3) =>
    smartFetch(`/api/v1/corpora/${cid}/export/collocations.network.png`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ node, level, window, min_freq }),
    }).then((r) => r.blob()),

  // Backwards-compatible xlsx-only shortcuts (delegate to the multi-format versions)
  exportConcordanceXlsx: (cid: string, query: string, level = "word", window = 5, limit = 1000) =>
    api.exportConcordance(cid, query, "xlsx", level, window, limit),
  exportFrequencyXlsx: (cid: string, unit = "word", limit = 1000) =>
    api.exportFrequency(cid, unit, "xlsx", limit),
  exportCollocationsXlsx: (cid: string, node: string, level = "word", window = 5, min_freq = 3) =>
    api.exportCollocations(cid, node, "xlsx", level, window, min_freq),
  exportKeynessXlsx: (cid: string, reference_corpus_id: string) =>
    api.exportKeyness(cid, reference_corpus_id, "xlsx"),

  exportMethodsPdf: (cid: string) =>
    smartFetch(`/api/v1/corpora/${cid}/methods.pdf`).then((r) => r.blob()),

  // --- AI ---
  listTools: () => jsonFetch<ToolsResponse>("/api/v1/ai/tools"),
  chat: (req: ChatRequest) =>
    jsonFetch<ChatTurnResponse>("/api/v1/ai/chat", {
      method: "POST",
      body: JSON.stringify(req),
    }),
  listConversations: () => jsonFetch<Array<Record<string, unknown>>>("/api/v1/ai/conversations"),
  getConversation: (cid: string) => jsonFetch<Record<string, unknown>>(`/api/v1/ai/conversations/${cid}`),
  // v0.1.16 Issue 2: pre-fabricated + dynamic query suggestions
  getQuerySuggestions: (language: string = "en", corpusId: string | null = null) =>
    jsonFetch<QuerySuggestionsResponse>(`/api/v1/ai/query-suggestions?language=${encodeURIComponent(language)}${corpusId ? `&corpus_id=${encodeURIComponent(corpusId)}` : ""}`),
  getDynamicSuggestions: (req: { provider: string; model: string | null; corpus_id: string | null; language: string; recent_analysis?: Record<string, unknown> }) =>
    jsonFetch<QuerySuggestionsResponse>("/api/v1/ai/query-suggestions/dynamic", {
      method: "POST",
      body: JSON.stringify(req),
    }),

  // --- Smart Troubleshooting ---
  troubleshootStatus: () =>
    jsonFetch<{ available: boolean; model: string; source: string }>("/api/v1/troubleshoot/status"),
  interpretError: (req: InterpretErrorRequest) =>
    jsonFetch<InterpretErrorResponse>("/api/v1/troubleshoot/interpret", {
      method: "POST",
      body: JSON.stringify(req),
    }),
  setGeminiKey: (apiKey: string) =>
    jsonFetch<{ ok: boolean; available: boolean; source: string }>("/api/v1/troubleshoot/gemini-key", {
      method: "POST",
      body: JSON.stringify({ api_key: apiKey }),
    }),
  clearGeminiKey: () =>
    jsonFetch<{ ok: boolean; available: boolean; source: string }>("/api/v1/troubleshoot/gemini-key", {
      method: "DELETE",
    }),

  // --- Cloud AI provider config (opt-in) ---
  getCloudConfig: () =>
    jsonFetch<{ configured: boolean; provider: string; model: string; source: string; hard_disabled: boolean }>("/api/v1/ai/cloud-config"),
  setCloudConfig: (req: { provider: "anthropic" | "openai"; api_key: string; model?: string; base_url?: string; acknowledge_data_leaves_device: boolean }) =>
    jsonFetch<{ configured: boolean; provider: string; model: string }>("/api/v1/ai/cloud-config", {
      method: "POST",
      body: JSON.stringify(req),
    }),
  clearCloudConfig: () =>
    jsonFetch<{ configured: boolean }>("/api/v1/ai/cloud-config", {
      method: "DELETE",
    }),

  // --- Ollama model catalogue + pull ---
  ollamaCatalogue: () =>
    jsonFetch<{ models: OllamaModel[] }>("/api/v1/ollama/catalogue"),
  ollamaPull: (model: string) =>
    jsonFetch<{ ok: boolean; model: string; message: string }>("/api/v1/ollama/pull", {
      method: "POST",
      body: JSON.stringify({ model }),
    }),
  ollamaImport: (modelName: string, filePath: string) =>
    jsonFetch<{ ok: boolean; model: string; message: string }>("/api/v1/ollama/import", {
      method: "POST",
      body: JSON.stringify({ model_name: modelName, file_path: filePath }),
    }),
  ollamaPullStatus: (model: string) =>
    jsonFetch<OllamaPullStatus>(`/api/v1/ollama/pull/status?model=${encodeURIComponent(model)}`),

  // --- Research-grade features ---
  prepublicationCheck: (cid: string) =>
    jsonFetch<PreCheckResponse>(`/api/v1/research/precheck/${cid}`),
  aiDisclosure: (pid: string) =>
    jsonFetch<AIDisclosureResponse>(`/api/v1/research/ai-disclosure/${pid}`),
  verifyTurn: (turnId: number, verified: "accepted" | "rejected" | "edited", notes: string = "") =>
    jsonFetch<{ ok: boolean; turn_id: number; verified: string }>(`/api/v1/research/verify-turn/${turnId}`, {
      method: "POST",
      body: JSON.stringify({ verified, notes }),
    }),
  exportFrequencyList: (cid: string, unit: string = "word", minFreq: number = 1, limit: number = 10000) =>
    smartFetch(`/api/v1/research/frequency-list/export/${cid}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ unit, min_freq: minFreq, limit }),
    }).then((r) => r.blob()),
  importFrequencyList: (content: string) =>
    jsonFetch<{ items: Array<{ word: string; freq: number }>; total_tokens: number; total_types: number }>(
      "/api/v1/research/frequency-list/import",
      { method: "POST", body: JSON.stringify({ content }) },
    ),
  compareConcordance: (targetCid: string, refCid: string, query: string, level: string = "word", window: number = 5, limit: number = 20) =>
    jsonFetch<CompareConcordanceResponse>("/api/v1/research/compare-concordance", {
      method: "POST",
      body: JSON.stringify({
        target_corpus_id: targetCid,
        reference_corpus_id: refCid,
        query, level, window, limit,
      }),
    }),
  listBundledReferences: () =>
    jsonFetch<{ references: Array<{ name: string; desc: string; size: string; available: boolean }> }>("/api/v1/research/bundled-references"),
  getBundledReference: (name: string) =>
    jsonFetch<{ name: string; items: Array<{ word: string; freq: number }>; total_tokens: number; total_types: number }>(`/api/v1/research/bundled-references/${name}`),

  // --- v0.1.16 reference-corpus subsystem (Issue 1) ---
  // Real download + verify + install + keyness-with-reference endpoints.
  // Replaces the fake "Bundled → Load" flow that only created an empty corpus row.
  listReferenceCorpora: () =>
    jsonFetch<{ references: Array<ReferenceCorpusEntry> }>("/api/v1/reference-corpora"),
  getReferenceStatus: (name: string) =>
    jsonFetch<ReferenceCorpusStatus>(`/api/v1/reference-corpora/${name}/status`),
  downloadReferenceCorpus: (name: string) =>
    jsonFetch<{ name: string; status: string; installed: boolean; message: string }>(`/api/v1/reference-corpora/${name}/download`, {
      method: "POST",
    }),
  cancelReferenceDownload: (name: string) =>
    jsonFetch<{ name: string; cancel_requested: boolean }>(`/api/v1/reference-corpora/${name}/cancel`, {
      method: "POST",
    }),
  deleteReferenceCorpus: (name: string) =>
    jsonFetch<{ name: string; deleted: boolean }>(`/api/v1/reference-corpora/${name}`, {
      method: "DELETE",
    }),
  keynessWithReference: (cid: string, refName: string, minFreq: number = 5, limit: number = 500) =>
    jsonFetch<KeynessWithReferenceResponse>(`/api/v1/corpora/${cid}/keyness-with-reference/${refName}`, {
      method: "POST",
      body: JSON.stringify({ reference_name: refName, min_freq: minFreq, limit }),
    }),

  // --- Open-access academic corpus download (API-key-based) ---
  oaSources: () =>
    jsonFetch<{ sources: OASource[] }>("/api/v1/open-access/sources"),
  oaSetKey: (source: string, apiKey: string) =>
    jsonFetch<{ ok: boolean; source: string; has_key: boolean }>("/api/v1/open-access/api-key", {
      method: "POST",
      body: JSON.stringify({ source, api_key: apiKey }),
    }),
  oaDeleteKey: (source: string) =>
    jsonFetch<{ ok: boolean; source: string; has_key: boolean }>(`/api/v1/open-access/api-key/${source}`, {
      method: "DELETE",
    }),
  oaSearch: (source: string, query: string, limit: number = 20, language?: string) =>
    jsonFetch<OASearchResponse>("/api/v1/open-access/search", {
      method: "POST",
      body: JSON.stringify({ source, query, limit, language }),
    }),
  oaDownload: (source: string, itemId: string, title: string = "") =>
    jsonFetch<OADownloadResponse>("/api/v1/open-access/download", {
      method: "POST",
      body: JSON.stringify({ source, item_id: itemId, title }),
    }),

  // --- Corpus Cleaning ---
  cleanCorpus: (cid: string, options: CleaningOptions) =>
    jsonFetch<CleaningResponse>(`/api/v1/corpora/${cid}/clean`, {
      method: "POST",
      body: JSON.stringify(options),
    }),

  // --- Corpus Hub (search + download open-access corpora) ---
  hubCatalogue: () =>
    jsonFetch<HubCatalogue>("/api/v1/hub/catalogue"),
  hubSearch: (q: string, language: string, hub: string = "all", limit: number = 20) =>
    jsonFetch<HubSearchResponse>(
      `/api/v1/hub/search?q=${encodeURIComponent(q)}&language=${language}&hub=${hub}&limit=${limit}`,
    ),
  hubDownloadUrl: (hub: string, corpusId: string, title: string, extra: Record<string, unknown>) =>
    `${ENGINE_BASE}/api/v1/hub/download?hub=${encodeURIComponent(hub)}&corpus_id=${encodeURIComponent(corpusId)}&title=${encodeURIComponent(title)}&extra=${encodeURIComponent(JSON.stringify(extra))}`,
};

// ----------------------------------------------------------------------- //
// Export types
// ----------------------------------------------------------------------- //

export type ExportFormat = "xlsx" | "csv" | "tsv" | "txt" | "json";

// ----------------------------------------------------------------------- //
// Ollama model catalogue + pull types
// ----------------------------------------------------------------------- //

export interface OllamaModel {
  name: string;
  size: string;
  params: string;
  ram: string;
  description: string;
  languages: string[];
  recommended: boolean;
}

export interface OllamaPullStatus {
  model: string;
  status: "starting" | "pulling" | "success" | "error" | "not_started" | string;
  completed: number;
  total: number;
  error: string | null;
}

// ----------------------------------------------------------------------- //
// Smart Troubleshooting types
// ----------------------------------------------------------------------- //

export interface InterpretErrorRequest {
  error_message: string;
  error_code?: string | number | null;
  endpoint?: string | null;
  context?: string | null;
  stack_trace?: string | null;
}

export interface InterpretErrorResponse {
  available: boolean;
  severity: "info" | "warning" | "error" | string;
  plain_language: string;
  likely_cause: string;
  suggested_fix: string;
  should_report: boolean;
  raw_error: string;
  model: string;
}

// ----------------------------------------------------------------------- //
// Corpus Cleaning types
// ----------------------------------------------------------------------- //

export interface CleaningOptions {
  collapse_whitespace?: boolean;
  strip_leading_trailing?: boolean;
  remove_empty_lines?: boolean;
  remove_urls?: boolean;
  remove_email_addresses?: boolean;
  remove_html_entities?: boolean;
  lowercase?: boolean;
  remove_punctuation?: boolean;
  remove_numbers?: boolean;
  remove_extra_symbols?: boolean;
  remove_stopwords?: boolean;
  min_token_length?: number;
  normalize_arabic?: boolean;
  strip_arabic_diacritics?: boolean;
  remove_arabic_tatweel?: boolean;
  create_new_version?: boolean;
}

export interface CleaningResponse {
  corpus_id: string;
  documents_cleaned: number;
  old_token_count: number;
  new_token_count: number;
  old_type_count: number;
  new_type_count: number;
  new_version_id: string | null;
  options_applied: Record<string, boolean | number>;
}

// ----------------------------------------------------------------------- //
// Corpus Hub types
// ----------------------------------------------------------------------- //

export interface HubInfo {
  id: string;
  name: string;
  description: string;
  requires_key: boolean;
  languages: string[];
}

export interface HubFeaturedItem {
  hub: string;
  id: string;
  title: string;
  language: string;
  size: string;
  license: string;
}

export interface HubCatalogue {
  hubs: HubInfo[];
  featured: HubFeaturedItem[];
}

export interface HubSearchResult {
  hub: string;
  id: string;
  title: string;
  description: string;
  language: string;
  size: string;
  license: string;
  download_url: string | null;
  download_format: string;
  extra: Record<string, unknown>;
}

export interface HubSearchResponse {
  query: string;
  language: string;
  hub: string;
  total: number;
  results: HubSearchResult[];
}

/** Helper: trigger a browser download for a Blob. */
/**
 * Download a blob to disk. Inside Tauri, uses the native OS save-file dialog
 * (via the save_file_to_disk Rust command) for a proper file-save experience.
 * In browser mode, falls back to the standard <a download> approach.
 *
 * Issue 5 fix:
 *   1. Replaced the JSON-array-of-numbers transfer (which inflated payload
 *      size several-fold and was slow for large exports) with a direct
 *      Uint8Array — Tauri 2 supports raw byte arrays over IPC without
 *      the Array.from() conversion.
 *   2. Returns a structured result so callers can surface user-visible
 *      success/error feedback instead of just console.error.
 */
export type DownloadResult =
  | { ok: true; path: string; message: string }
  | { ok: false; path: string | null; message: string; cancelled: boolean };

export async function downloadBlob(blob: Blob, filename: string): Promise<DownloadResult> {
  if (isTauriRuntime()) {
    // Inside Tauri: use native save dialog
    try {
      const invoke = await getInvoke();
      const arrayBuffer = await blob.arrayBuffer();
      // Issue 5 fix: pass the Uint8Array directly. Tauri 2's IPC supports
      // raw byte arrays — the previous Array.from(new Uint8Array(...))
      // converted every byte to a JS number, inflating the payload ~4x and
      // making large exports (≥10k concordance rows) appear to hang.
      const data = new Uint8Array(arrayBuffer);
      const result = await invoke<string>("save_file_to_disk", { filename, data });
      const parsed = JSON.parse(result) as { ok: boolean; path: string | null; message: string };
      if (parsed.ok) {
        return { ok: true, path: parsed.path!, message: parsed.message };
      }
      // Distinguish "user cancelled" (path is null) from real write failures
      const cancelled = parsed.path === null;
      return { ok: false, path: parsed.path, message: parsed.message, cancelled };
    } catch (e: any) {
      // Native save threw — fall back to browser download but report the error
      console.error("Native save failed, falling back to browser download:", e);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      return { ok: false, path: null, message: `Native save failed (fell back to browser): ${e?.message || String(e)}`, cancelled: false };
    }
  } else {
    // Browser mode: standard download
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    return { ok: true, path: filename, message: `Downloaded ${filename}` };
  }
}

/**
 * Issue 5 helper: wraps the common export pattern (fetch blob from API →
 * save to disk → show user-visible feedback) with proper error handling.
 *
 * Usage:
 *   const result = await exportWithFeedback(
 *     () => api.exportConcordance(cid, query, fmt, level, window, 1000),
 *     `concordance_${query}.${fmt}`,
 *     setExportStatus,  // (msg: string, kind: "success"|"error"|"info") => void
 *   );
 *
 * - Catches both backend errors (engine offline, 500, 422) and save-dialog
 *   errors (user cancelled, disk full, permissions) and routes them into
 *   the same visible-feedback path.
 * - Returns the structured DownloadResult so the caller can do additional
 *   handling if needed.
 */
export async function exportWithFeedback(
  fetchBlob: () => Promise<Blob>,
  filename: string,
  setStatus: (msg: string, kind: "success" | "error" | "info") => void,
): Promise<DownloadResult> {
  setStatus(`Exporting ${filename}…`, "info");
  let blob: Blob;
  try {
    blob = await fetchBlob();
  } catch (e: any) {
    // Backend error: engine offline, 500, 422 (e.g. Issue 1's "no ingested
    // version"), or network failure. Surface the specific message.
    const msg = e?.message || String(e);
    setStatus(`✗ Export failed: ${msg}`, "error");
    return { ok: false, path: null, message: msg, cancelled: false };
  }
  let result: DownloadResult;
  try {
    result = await downloadBlob(blob, filename);
  } catch (e: any) {
    const msg = e?.message || String(e);
    setStatus(`✗ Save failed: ${msg}`, "error");
    return { ok: false, path: null, message: msg, cancelled: false };
  }
  if (result.ok) {
    setStatus(`✓ Saved to ${result.path}`, "success");
  } else if (result.cancelled) {
    // User cancelled the save dialog — not an error, just clear the status.
    setStatus("", "info");
  } else {
    setStatus(`✗ ${result.message}`, "error");
  }
  return result;
}

// ----------------------------------------------------------------------- //
// Research-grade feature types
// ----------------------------------------------------------------------- //

export interface PreCheckResult {
  id: string;
  label: string;
  status: "pass" | "warn" | "fail";
  detail: string;
}

export interface PreCheckResponse {
  corpus_id: string;
  corpus_name: string;
  overall: "pass" | "warn" | "fail";
  checks: PreCheckResult[];
  timestamp: string;
}

export interface AIDisclosureResponse {
  project_id: string;
  project_name: string;
  ai_used: boolean;
  providers: string[];
  models: string[];
  frameworks: string[];
  total_ai_turns: number;
  grounded_turns: number;
  ungrounded_turns: number;
  verified_accepted: number;
  verified_rejected: number;
  unverified: number;
  tools_called: string[];
  disclosure_text: string;
}

export interface CompareConcordanceSide {
  corpus_id: string;
  total: number;
  lines: Array<{
    line_id: string;
    document: string;
    left: string;
    node: string;
    right: string;
    pos: string;
    lemma: string;
  }>;
}

export interface CompareConcordanceResponse {
  query: string;
  target: CompareConcordanceSide;
  reference: CompareConcordanceSide;
}

// ----------------------------------------------------------------------- //
// Open-access academic corpus types
// ----------------------------------------------------------------------- //

export interface OASource {
  id: string;
  name: string;
  description: string;
  registration_url: string | null;
  registration_note: string;
  has_key: boolean;
  needs_key: boolean;
}

export interface OASearchResult {
  id: string;
  title: string;
  authors: string[];
  year: number | string | null;
  has_full_text: boolean;
  source: string;
  download_url: string | null;
  size?: string;
  files?: Array<{ name: string; size: number }>;
}

export interface OASearchResponse {
  results: OASearchResult[];
  total: number;
  error?: string;
}

export interface OADownloadResponse {
  type: "text" | "url";
  filename?: string;
  content?: string;
  url?: string;
  size?: number;
  title?: string;
}

// ─── v0.1.16 reference-corpus subsystem (Issue 1) ────────────────────
export interface ReferenceCorpusEntry {
  name: string;
  display_name: string;
  language: "en" | "ar";
  description: string;
  format: "tsv_freq" | "csv_freq" | "json_freq";
  size_hint: string;
  license: string;
  citation: string;
  genre: string;
  min_corpus_tokens: number;
  tags: string[];
  available: boolean;
  installed: boolean;
  downloadable: boolean;
  // present when installed:
  installed_at?: string;
  size_bytes?: number;
  sha256?: string;
  catalogue_version?: string;
}

export interface ReferenceDownloadProgress {
  name: string;
  status: "pending" | "downloading" | "verifying" | "installed" | "failed" | "cancelled";
  downloaded_bytes: number;
  total_bytes: number;
  percent: number;
  error: string;
  retries: number;
}

export interface ReferenceCorpusStatus {
  name: string;
  display_name: string;
  installed: boolean;
  progress: ReferenceDownloadProgress | null;
  installed_at?: string;
  size_bytes?: number;
}

export interface KeynessWithReferenceResponse {
  target_corpus_id: string;
  reference_name: string;
  reference_corpus_id: string;
  measures: string[];
  positive_keywords: Array<Record<string, unknown>>;
  negative_keywords: Array<Record<string, unknown>>;
  N1: number;
  N2: number;
}

// ─── v0.1.16 AI query suggestions (Issue 2) ──────────────────────────
export interface QuerySuggestion {
  id: string;
  category: string;
  label: string;
  query: string;
  requires_corpus: boolean;
  requires_reference: boolean;
  available: boolean;
  unavailable_reason?: string;
  description?: string;
  source: "prefabricated" | "dynamic";
  rationale?: string;
}

export interface QuerySuggestionsResponse {
  suggestions: QuerySuggestion[];
  has_corpus: boolean;
  ref_available: boolean;
  dynamic_count?: number;
  provider_requested?: string;
  model_used?: string;
}
