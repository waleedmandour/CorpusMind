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
// Phase 3 types — Arabic (§8.21)
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

// Phase 3 polish — bilingual (§8.22)
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
// Phase 4 types — Vision (§9.1–9.10)
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

  // --- Phase 3 Arabic (§8.21) ---
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

  // --- Phase 3 polish — bilingual (§8.22) ---
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

  // --- Phase 4 Vision (§9.1–9.10) ---
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
    return fetch(`${ENGINE_BASE}/api/v1/image-sets/${isetId}/images`, {
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
