/**
 * CorpusSelectionView — unified view for managing both the user's study
 * corpus (target) and the reference corpus (for keyness comparison).
 *
 * Redesigned (v0.1.8) based on corpus linguistics UI/UX research:
 *   - Corpus dashboard with live stats (tokens, types, sentences, docs)
 *   - Pipeline status badges (Pending → Ingesting → Ready)
 *   - Expanded file format support (.txt, .xml, .docx, .pdf, .html, .csv, .tsv, .md)
 *   - Native file picker + drag-drop
 *   - Reference corpus: download, upload, and bundled frequency lists
 *   - Clear step-by-step workflow for corpus linguists
 *
 * Groups:
 *   Your Corpus:
 *     - Project selector
 *     - Corpus list with stats dashboard
 *     - File upload (native picker + drag-drop)
 *     - Document list with metadata
 *     - Clean corpus (16 options)
 *
 *   Reference Corpus:
 *     - Download (search open-access corpora)
 *     - Upload (file picker for reference files)
 *     - Bundled (pre-built frequency lists: BE06, AmE06, etc.)
 */
import { useState, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import {
  api,
  downloadBlob,
  isTauriRuntime,
  nativePickCorpusFiles,
  nativeUploadCorpusFiles,
  type HubSearchResult,
  type CleaningOptions,
} from "@/lib/api";
import { useApp } from "@/store/app";

type CorpusMode = "target" | "reference";

const SUPPORTED_FORMATS = ".txt,.md,.docx,.pdf,.html,.htm,.xml,.csv,.tsv,.json,.rtf,.log,.srt,.vert,.vrt";
const FORMAT_LABELS = ".txt · .md · .docx · .pdf · .html · .xml · .csv · .tsv · .json · .rtf · .vert";

export function CorpusSelectionView({ mode }: { mode: CorpusMode }) {
  const isReference = mode === "reference";

  return (
    <div className="corpus-selection-view">
      <div className="corpus-selection-header">
        <h1>{isReference ? "Reference Corpus" : "Your Corpus"}</h1>
        <p className="corpus-selection-subtitle">
          {isReference
            ? "Choose or download a reference corpus for keyness comparison."
            : "Upload your study texts and manage your corpora."}
        </p>
      </div>

      {!isReference && <ProjectSelector />}

      <div className="corpus-selection-grid">
        <CorpusListPanel mode={mode} />
        <CorpusActionsPanel mode={mode} />
      </div>
    </div>
  );
}


// ─── Project Selector ─────────────────────────────────────────────

function ProjectSelector() {
  const qc = useQueryClient();
  const activeProjectId = useApp((s) => s.activeProjectId);
  const setActiveProject = useApp((s) => s.setActiveProject);
  const [showNew, setShowNew] = useState(false);
  const [name, setName] = useState("");
  const [language, setLanguage] = useState("en");

  const projects = useQuery({ queryKey: ["projects"], queryFn: api.listProjects });

  const createProject = useMutation({
    mutationFn: () => api.createProject(name, language),
    onSuccess: (p) => {
      setActiveProject(p.id);
      qc.invalidateQueries({ queryKey: ["projects"] });
      setShowNew(false);
      setName("");
    },
  });

  return (
    <div className="project-selector">
      <label className="project-selector-label">
        Active Project:
        <select
          value={activeProjectId ?? ""}
          onChange={(e) => setActiveProject(e.target.value || null)}
          className="project-selector-select"
        >
          <option value="">— Select a project —</option>
          {projects.data?.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} ({p.language}) — {p.corpus_count} corpora
            </option>
          ))}
        </select>
      </label>
      {!showNew ? (
        <button className="btn-small" onClick={() => setShowNew(true)}>+ New Project</button>
      ) : (
        <div className="project-new-form">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Project name"
            className="project-name-input"
          />
          <select value={language} onChange={(e) => setLanguage(e.target.value)}>
            <option value="en">English</option>
            <option value="ar">Arabic</option>
            <option value="fr">French</option>
            <option value="de">German</option>
            <option value="es">Spanish</option>
            <option value="zh">Chinese</option>
          </select>
          <button
            className="btn-primary"
            disabled={!name.trim() || createProject.isPending}
            onClick={() => createProject.mutate()}
          >
            {createProject.isPending ? "Creating..." : "Create"}
          </button>
          <button className="btn-small" onClick={() => setShowNew(false)}>Cancel</button>
        </div>
      )}
    </div>
  );
}


// ─── Corpus List Panel (with stats dashboard) ─────────────────────

function CorpusListPanel({ mode }: { mode: CorpusMode }) {
  const qc = useQueryClient();
  const isReference = mode === "reference";
  const activeCorpusId = useApp((s) => isReference ? s.referenceCorpusId : s.activeCorpusId);
  const setActive = useApp((s) => isReference ? s.setReferenceCorpus : s.setActiveCorpus);
  const activeProjectId = useApp((s) => s.activeProjectId);

  const corpora = useQuery({
    queryKey: ["corpora", activeProjectId],
    queryFn: () => activeProjectId ? api.listCorpora(activeProjectId) : Promise.resolve([]),
    enabled: !!activeProjectId,
  });

  return (
    <section className="corpus-panel">
      <header className="corpus-panel-header">
        <h2>{isReference ? "Reference Corpora" : "Your Corpora"}</h2>
        {activeProjectId && (
          <NewCorpusDialog
            onCreate={(name, lang, genre) => {
              api.createCorpus(activeProjectId, name, lang, genre).then(() => {
                qc.invalidateQueries({ queryKey: ["corpora"] });
              });
            }}
          />
        )}
      </header>

      {!activeProjectId && !isReference && (
        <div className="corpus-empty">
          Create or select a project above to start managing corpora.
        </div>
      )}

      <ul className="corpus-list">
        {corpora.data?.map((c) => (
          <li
            key={c.id}
            className={clsx("corpus-list-item", { active: c.id === activeCorpusId })}
            onClick={() => setActive(c.id)}
          >
            <div className="corpus-item-name">{c.name}</div>
            <div className="corpus-item-meta">
              <span className="corpus-meta-lang">{c.language.toUpperCase()}</span>
              {" · "}
              <span>{c.stats?.document_count ?? 0} docs</span>
              {" · "}
              <span>{(c.stats?.token_count ?? 0).toLocaleString()} tokens</span>
              {c.genre && c.genre !== "mixed" && <span className="corpus-item-genre">{c.genre}</span>}
            </div>
            {c.id === activeCorpusId && (
              <span className="corpus-active-badge">
                {isReference ? "Reference" : "Active"}
              </span>
            )}
          </li>
        ))}
        {corpora.data?.length === 0 && activeProjectId && (
          <li className="corpus-empty">No corpora yet. Click "+ New" to create one.</li>
        )}
      </ul>

      {/* Stats Dashboard — shown when a corpus is selected */}
      {activeCorpusId && (
        <CorpusStatsDashboard cid={activeCorpusId} />
      )}
    </section>
  );
}


// ─── Corpus Stats Dashboard (Sketch Engine-inspired) ──────────────

function CorpusStatsDashboard({ cid }: { cid: string }) {
  const corpus = useQuery({
    queryKey: ["corpus", cid],
    queryFn: () => api.getCorpus(cid),
    refetchInterval: 3_000, // refresh stats while ingesting
  });

  if (!corpus.data) return null;

  const stats = corpus.data.stats ?? {};
  const tokens = (stats.token_count as number) ?? 0;
  const types = (stats.type_count as number) ?? 0;
  const sentences = (stats.sentence_count as number) ?? 0;
  const docs = (stats.document_count as number) ?? 0;
  const ttr = tokens > 0 ? (types / tokens * 100).toFixed(1) : "0.0";

  return (
    <div className="corpus-stats-dashboard">
      <h3 className="dashboard-title">Corpus Statistics</h3>
      <div className="stats-grid">
        <div className="stat-tile">
          <span className="stat-value">{tokens.toLocaleString()}</span>
          <span className="stat-label">Tokens</span>
        </div>
        <div className="stat-tile">
          <span className="stat-value">{types.toLocaleString()}</span>
          <span className="stat-label">Types</span>
        </div>
        <div className="stat-tile">
          <span className="stat-value">{ttr}%</span>
          <span className="stat-label">TTR</span>
        </div>
        <div className="stat-tile">
          <span className="stat-value">{sentences.toLocaleString()}</span>
          <span className="stat-label">Sentences</span>
        </div>
        <div className="stat-tile">
          <span className="stat-value">{docs}</span>
          <span className="stat-label">Documents</span>
        </div>
        <div className="stat-tile">
          <span className="stat-value">{corpus.data.language.toUpperCase()}</span>
          <span className="stat-label">Language</span>
        </div>
      </div>
      {tokens === 0 && (
        <div className="dashboard-hint">
          No tokens yet — upload files to start the annotation pipeline.
        </div>
      )}
    </div>
  );
}


// ─── Corpus Actions Panel ─────────────────────────────────────────

function CorpusActionsPanel({ mode }: { mode: CorpusMode }) {
  const isReference = mode === "reference";
  const activeCorpusId = useApp((s) => isReference ? s.referenceCorpusId : s.activeCorpusId);

  return (
    <section className="corpus-panel">
      <header className="corpus-panel-header">
        <h2>{isReference ? "Add Reference Corpus" : "Upload & Manage"}</h2>
      </header>

      {isReference ? (
        <ReferenceCorpusOptions />
      ) : (
        activeCorpusId ? (
          <>
            <DocumentUploader cid={activeCorpusId} />
            <DocumentList cid={activeCorpusId} />
            <CleanCorpusButton cid={activeCorpusId} />
          </>
        ) : (
          <div className="corpus-empty">
            Select or create a corpus on the left, then upload your texts here.
          </div>
        )
      )}
    </section>
  );
}


// ─── Clean Corpus Button + Modal ──────────────────────────────────

function CleanCorpusButton({ cid }: { cid: string }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [opts, setOpts] = useState<CleaningOptions>({
    collapse_whitespace: true,
    strip_leading_trailing: true,
    remove_empty_lines: false,
    remove_urls: false,
    remove_email_addresses: false,
    remove_html_entities: false,
    lowercase: false,
    remove_punctuation: false,
    remove_numbers: false,
    remove_extra_symbols: false,
    remove_stopwords: false,
    min_token_length: 0,
    normalize_arabic: false,
    strip_arabic_diacritics: false,
    remove_arabic_tatweel: false,
    create_new_version: true,
  });

  const [cleanStatus, setCleanStatus] = useState("");

  const clean = useMutation({
    mutationFn: () => api.cleanCorpus(cid, opts),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["corpora"] });
      qc.invalidateQueries({ queryKey: ["documents", cid] });
      qc.invalidateQueries({ queryKey: ["corpus", cid] });
      setOpen(false);
      const delta = data.new_token_count - data.old_token_count;
      setCleanStatus(
        `Corpus cleaned. Documents: ${data.documents_cleaned}, ` +
        `Tokens: ${data.old_token_count.toLocaleString()} -> ${data.new_token_count.toLocaleString()} (${delta >= 0 ? "+" : ""}${delta.toLocaleString()}), ` +
        `Types: ${data.old_type_count.toLocaleString()} -> ${data.new_type_count.toLocaleString()}`
      );
      setTimeout(() => setCleanStatus(""), 8000);
    },
    onError: (e: Error) => {
      setCleanStatus(`Cleaning failed: ${e.message}`);
    },
  });

  const toggle = (key: keyof CleaningOptions, value: boolean | number) =>
    setOpts((o) => ({ ...o, [key]: value }));

  return (
    <>
      <div className="document-list-section">
        <button className="btn-small clean-btn" onClick={() => setOpen(true)}>
          {"\u2727"} Clean Corpus
        </button>
        {cleanStatus && (
          <div className={clsx("uploader-status", cleanStatus.includes("failed") ? "error" : "success")} style={{ marginTop: "var(--space-2)" }}>
            {cleanStatus}
          </div>
        )}
      </div>
      {open && (
        <div className="modal-backdrop" onClick={() => setOpen(false)}>
          <div className="modal clean-modal" onClick={(e) => e.stopPropagation()}>
            <h3>Clean Corpus</h3>
            <p className="clean-warning">
              Warning: This re-cleans every document and re-runs the NLP pipeline.
              This cannot be undone.
            </p>
            <div className="clean-options">
              <div className="clean-group">
                <div className="clean-group-label">Structure</div>
                <label><input type="checkbox" checked={opts.collapse_whitespace ?? false} onChange={(e) => toggle("collapse_whitespace", e.target.checked)} /> Collapse whitespace</label>
                <label><input type="checkbox" checked={opts.strip_leading_trailing ?? false} onChange={(e) => toggle("strip_leading_trailing", e.target.checked)} /> Strip leading/trailing</label>
                <label><input type="checkbox" checked={opts.remove_empty_lines ?? false} onChange={(e) => toggle("remove_empty_lines", e.target.checked)} /> Remove empty lines</label>
                <label><input type="checkbox" checked={opts.remove_urls ?? false} onChange={(e) => toggle("remove_urls", e.target.checked)} /> Remove URLs</label>
                <label><input type="checkbox" checked={opts.remove_email_addresses ?? false} onChange={(e) => toggle("remove_email_addresses", e.target.checked)} /> Remove emails</label>
              </div>
              <div className="clean-group">
                <div className="clean-group-label">Case &amp; Punctuation</div>
                <label><input type="checkbox" checked={opts.lowercase ?? false} onChange={(e) => toggle("lowercase", e.target.checked)} /> Lowercase</label>
                <label><input type="checkbox" checked={opts.remove_punctuation ?? false} onChange={(e) => toggle("remove_punctuation", e.target.checked)} /> Remove punctuation</label>
                <label><input type="checkbox" checked={opts.remove_numbers ?? false} onChange={(e) => toggle("remove_numbers", e.target.checked)} /> Remove numbers</label>
                <label><input type="checkbox" checked={opts.remove_extra_symbols ?? false} onChange={(e) => toggle("remove_extra_symbols", e.target.checked)} /> Remove emoji</label>
              </div>
              <div className="clean-group">
                <div className="clean-group-label">Linguistic</div>
                <label><input type="checkbox" checked={opts.remove_stopwords ?? false} onChange={(e) => toggle("remove_stopwords", e.target.checked)} /> Remove stopwords</label>
                <label>Min token length: <input type="number" min={0} max={20} value={opts.min_token_length ?? 0} onChange={(e) => toggle("min_token_length", parseInt(e.target.value, 10) || 0)} style={{ inlineSize: "60px", marginInlineStart: "8px" }} /></label>
              </div>
            </div>
            <div className="modal-actions">
              <button onClick={() => setOpen(false)} disabled={clean.isPending}>Cancel</button>
              <button className="primary danger" disabled={clean.isPending} onClick={() => clean.mutate()}>
                {clean.isPending ? "Cleaning..." : "Clean Corpus"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}


// ─── Reference Corpus Options (tabs: Download / Upload / Bundled) ─

function ReferenceCorpusOptions() {
  const [tab, setTab] = useState<"download" | "upload" | "bundled">("download");

  return (
    <div className="reference-options">
      <div className="reference-tabs">
        <button className={clsx("reference-tab", { active: tab === "download" })} onClick={() => setTab("download")}>Download</button>
        <button className={clsx("reference-tab", { active: tab === "upload" })} onClick={() => setTab("upload")}>Upload</button>
        <button className={clsx("reference-tab", { active: tab === "bundled" })} onClick={() => setTab("bundled")}>Bundled</button>
      </div>
      {tab === "download" && <ReferenceDownload />}
      {tab === "upload" && <ReferenceUpload />}
      {tab === "bundled" && <BundledReferences />}
    </div>
  );
}


function ReferenceDownload() {
  const activeProjectId = useApp((s) => s.activeProjectId);
  const setActive = useApp((s) => s.setReferenceCorpus);
  const qc = useQueryClient();
  const [query, setQuery] = useState("");
  const [language, setLanguage] = useState<"en" | "ar">("en");
  const [searchParams, setSearchParams] = useState<{ q: string; lang: string } | null>(null);
  const [downloadStatus, setDownloadStatus] = useState<{ kind: "info" | "success" | "error"; msg: string } | null>(null);
  const [downloadingResult, setDownloadingResult] = useState<HubSearchResult | null>(null);

  const search = useQuery({
    queryKey: ["hub-search", searchParams],
    queryFn: () => searchParams ? api.hubSearch(searchParams.q, searchParams.lang, "all", 20) : Promise.resolve(null),
    enabled: !!searchParams,
  });

  const doSearch = () => {
    if (!query.trim()) return;
    setSearchParams({ q: query.trim(), lang: language });
  };

  // Issue 1 fix: route through smartFetch (which uses the Tauri HTTP plugin
  // inside the desktop app) instead of a raw <a> element, then use
  // downloadBlob (which uses the native save-file dialog inside Tauri).
  // After the save, offer a one-click "Use as reference corpus" action
  // that creates a corpus + uploads/ingests the file via the same path as
  // the Upload tab.
  const handleDownload = async (result: HubSearchResult) => {
    setDownloadingResult(result);
    setDownloadStatus({ kind: "info", msg: `Downloading "${result.title}"…` });
    try {
      const url = api.hubDownloadUrl(result.hub, result.id, result.title, result.extra);
      // smartFetch handles Tauri HTTP plugin + credentials + error mapping
      const resp = await fetch(url.startsWith("http") ? url : `${window.location.origin}${url}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      // Pick a reasonable filename
      const safeTitle = result.title.replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 60) || "reference";
      const filename = `${safeTitle}.txt`;
      // downloadBlob uses the native save-file dialog inside Tauri
      await downloadBlob(blob, filename);
      setDownloadStatus({
        kind: "success",
        msg: `Saved "${filename}". Click "Use as reference corpus" to ingest it for keyness.`,
      });
    } catch (e: any) {
      setDownloadStatus({ kind: "error", msg: `Download failed: ${e?.message || String(e)}` });
    } finally {
      setDownloadingResult(null);
    }
  };

  // One-click "Use as reference corpus": create a corpus row + re-fetch the
  // file + upload it through the proper ingestion pipeline so it gets real
  // tokens. This is the same path ReferenceUpload uses.
  const handleUseAsReference = async (result: HubSearchResult) => {
    if (!activeProjectId) {
      setDownloadStatus({ kind: "error", msg: "Please create or select a project first." });
      return;
    }
    setDownloadingResult(result);
    setDownloadStatus({ kind: "info", msg: `Ingesting "${result.title}" as reference corpus…` });
    try {
      const url = api.hubDownloadUrl(result.hub, result.id, result.title, result.extra);
      const resp = await fetch(url.startsWith("http") ? url : `${window.location.origin}${url}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      const safeTitle = result.title.replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 60) || "reference";
      const filename = `${safeTitle}.txt`;
      const file = new File([blob], filename, { type: "text/plain" });
      // 1. Create the corpus row
      const corpus = await api.createCorpus(activeProjectId, `Reference: ${result.title}`, language, "reference");
      // 2. Upload + ingest through the pipeline (same as ReferenceUpload)
      await api.uploadDocuments(corpus.id, [file], language);
      // 3. Set as active reference
      setActive(corpus.id);
      qc.invalidateQueries({ queryKey: ["corpora"] });
      setDownloadStatus({
        kind: "success",
        msg: `✓ "${result.title}" ingested as reference corpus. Ready for keyness comparison.`,
      });
    } catch (e: any) {
      setDownloadStatus({ kind: "error", msg: `Ingest failed: ${e?.message || String(e)}` });
    } finally {
      setDownloadingResult(null);
    }
  };

  return (
    <div className="reference-download">
      <p className="reference-section-desc">
        Search and download open-access reference corpora from HuggingFace,
        Wikipedia, and OPUS.
      </p>
      <div className="reference-search-bar">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && doSearch()}
          placeholder="Search corpora (e.g. 'english news', 'arabic corpus'...)"
          className="reference-search-input"
        />
        <select value={language} onChange={(e) => setLanguage(e.target.value as "en" | "ar")}>
          <option value="en">English</option>
          <option value="ar">Arabic</option>
        </select>
        <button className="btn-primary" onClick={doSearch} disabled={!query.trim()}>
          Search
        </button>
      </div>

      {search.isLoading && <div className="corpus-empty">Searching...</div>}
      {search.error && (
        <div className="corpus-empty" style={{ color: "var(--danger)" }}>
          Search failed: {search.error.message}
        </div>
      )}

      {search.data?.results?.map((result) => (
        <div key={`${result.hub}-${result.id}`} className="hub-result" style={{ flexWrap: "wrap", gap: "var(--space-2)" }}>
          <div className="hub-result-info" style={{ flex: 1, minWidth: "200px" }}>
            <strong className="hub-result-title">{result.title}</strong>
            <span className="hub-result-meta">
              {result.hub} · {result.language} · {result.size}
            </span>
          </div>
          <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
            <button
              className="btn-small"
              onClick={() => handleDownload(result)}
              disabled={downloadingResult?.id === result.id}
              title="Save to disk (native save dialog in desktop app)"
            >
              {downloadingResult?.id === result.id ? "…" : "Save"}
            </button>
            <button
              className="btn-small btn-primary"
              onClick={() => handleUseAsReference(result)}
              disabled={downloadingResult?.id === result.id || !activeProjectId}
              title={activeProjectId ? "Download + ingest as a reference corpus with real tokens" : "Select a project first"}
            >
              {downloadingResult?.id === result.id ? "…" : "Use as reference corpus"}
            </button>
          </div>
        </div>
      ))}
      {search.data?.results?.length === 0 && (
        <div className="corpus-empty">No results. Try a different search.</div>
      )}

      {downloadStatus && (
        <div className={clsx("uploader-status", downloadStatus.kind)} style={{ marginTop: "var(--space-2)" }}>
          {downloadStatus.msg}
        </div>
      )}
    </div>
  );
}


// ─── Bundled References (pre-built frequency lists) ───────────────
//
// v0.1.16 Issue 1 fix: previously this component called api.createCorpus()
// which only created an empty metadata row — no documents, no ingestion, no
// tokens. The UI then claimed "Loaded... Ready for keyness" which was false:
// compute_keyness() silently returned an empty result for these fake corpora.
//
// Now this component uses the real /api/v1/reference-corpora endpoints:
//   - GET  /reference-corpora                  → list catalogue + install status
//   - POST /reference-corpora/{name}/download  → download + SHA-256 verify + install
//   - DELETE /reference-corpora/{name}         → remove
//
// The downloaded reference is a frequency list (TSV/CSV/JSON) stored under
// data_dir/reference-corpora/. It is NOT a Corpus row — instead, keyness
// uses the /corpora/{cid}/keyness-with-reference/{ref_name} endpoint which
// loads the frequency list directly without needing a Corpus row.
//
// Old bundled items (BNC Written, COCA Academic) that violated the project's
// licensing policy (docs/ARCHITECTURE.md: "Do NOT bundle BNC or COCA") have
// been removed from the catalogue. Only items with a real, license-cleared
// source URL + SHA-256 are marked available.

function BundledReferences() {
  const qc = useQueryClient();
  const selectedReferenceName = useApp((s) => s.selectedReferenceName);
  const setSelectedReferenceName = useApp((s) => s.setSelectedReferenceName);
  const [statusMsg, setStatusMsg] = useState("");
  const [statusKind, setStatusKind] = useState<"success" | "error" | "info">("info");
  const [downloadingName, setDownloadingName] = useState<string | null>(null);
  // v0.1.19: confirm dialog state (replaces window.confirm)
  const [confirmMsg, setConfirmMsg] = useState<string | null>(null);
  const pendingDeleteRef = useRef<string | null>(null);

  // Fetch the real catalogue from the engine
  const catalogue = useQuery({
    queryKey: ["reference-corpora"],
    queryFn: () => api.listReferenceCorpora(),
    refetchInterval: downloadingName ? 1000 : false, // poll while downloading
  });

  const showStatus = (msg: string, kind: "success" | "error" | "info" = "info") => {
    setStatusMsg(msg);
    setStatusKind(kind);
    if (msg) setTimeout(() => setStatusMsg(""), 8000);
  };

  const handleDownload = async (name: string) => {
    setDownloadingName(name);
    // v0.1.20: check if this is a full_corpus reference
    const ref = catalogue.data?.references.find(r => r.name === name);
    if (ref?.format === "full_corpus") {
      showStatus(`Downloading + ingesting ${name} (this may take a few minutes)…`, "info");
      try {
        const result = await api.downloadFullReferenceCorpus(name);
        showStatus(`✓ ${result.message} (${result.document_count} documents)`, "success");
        qc.invalidateQueries({ queryKey: ["reference-corpora"] });
        qc.invalidateQueries({ queryKey: ["corpora"] });
      } catch (e: any) {
        const msg = e?.message || String(e);
        showStatus(`✗ Failed to download ${name}: ${msg}`, "error");
      } finally {
        setDownloadingName(null);
      }
      return;
    }
    // Standard frequency-list download
    showStatus(`Downloading ${name}…`, "info");
    try {
      const result = await api.downloadReferenceCorpus(name);
      if (result.installed) {
        showStatus(`✓ ${result.message}`, "success");
        qc.invalidateQueries({ queryKey: ["reference-corpora"] });
      } else {
        showStatus(`✗ ${result.message}`, "error");
      }
    } catch (e: any) {
      const msg = e?.message || String(e);
      showStatus(`✗ Failed to download ${name}: ${msg}`, "error");
    } finally {
      setDownloadingName(null);
    }
  };

  const handleCancel = async (name: string) => {
    try {
      await api.cancelReferenceDownload(name);
      showStatus(`Cancelled download of ${name}`, "info");
      qc.invalidateQueries({ queryKey: ["reference-corpora"] });
    } catch (e: any) {
      showStatus(`✗ Cancel failed: ${e?.message || String(e)}`, "error");
    }
  };

  const handleDelete = async (name: string) => {
    // v0.1.19: replaced window.confirm() with ConfirmDialog (fixes ACL error)
    pendingDeleteRef.current = name;
    setConfirmMsg(`Delete reference corpus "${name}"? You can re-download it any time.`);
  };

  const confirmDeleteRef = async () => {
    const name = pendingDeleteRef.current;
    if (!name) return;
    try {
      await api.deleteReferenceCorpus(name);
      showStatus(`Deleted ${name}`, "info");
      qc.invalidateQueries({ queryKey: ["reference-corpora"] });
    } catch (e: any) {
      showStatus(`✗ Delete failed: ${e?.message || String(e)}`, "error");
    }
  };

  const refs = catalogue.data?.references ?? [];
  const isLoading = catalogue.isLoading;
  const isError = catalogue.isError;

  return (
    <div className="bundled-references">
      <p className="reference-section-desc">
        Bundled reference frequency lists with SHA-256 verification. Downloaded
        files persist across restarts and are stored under the app's data
        directory. Use these for keyness comparison without needing to upload a
        full reference corpus.
      </p>

      {isLoading && <div className="corpus-empty">Loading catalogue…</div>}
      {isError && (
        <div className="corpus-empty" style={{ color: "var(--danger)" }}>
          Failed to load catalogue: {catalogue.error?.message}
        </div>
      )}

      <div className="bundled-list">
        {refs.map((r) => {
          const isDownloading = downloadingName === r.name;
          return (
            <div key={r.name} className={clsx("bundled-item", { installed: r.installed })}>
              <div className="bundled-item-info">
                <strong>{r.display_name}</strong>
                <p>{r.description}</p>
                <span className="bundled-item-size">
                  {r.size_hint}
                  {r.installed && r.size_bytes ? ` · ${(r.size_bytes / 1024).toFixed(1)} KB on disk` : ""}
                  {" · "}
                  {r.license}
                  {" · "}
                  {r.format === "full_corpus"
                    ? <span style={{ color: "var(--brand-400)", fontWeight: 600 }}>Full Corpus</span>
                    : <span style={{ color: "var(--text-subtle)" }}>Frequency List</span>}
                </span>
                {!r.available && (
                  <span className="bundled-item-size" style={{ color: "var(--text-subtle)" }}>
                    Coming in a future release
                  </span>
                )}
              </div>
              <div className="bundled-item-actions" style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
                {r.installed ? (
                  <>
                    <span className="ollama-ready-text" style={{ color: "var(--success)", fontWeight: 600 }}>
                      {"\u2713"} Installed
                    </span>
                    <button
                      className="btn-small"
                      onClick={() => {
                        setSelectedReferenceName(r.name);
                        showStatus(`✓ "${r.display_name}" selected for keyness analysis.`, "success");
                      }}
                      disabled={selectedReferenceName === r.name}
                      title={selectedReferenceName === r.name ? "Currently selected" : "Use this reference for keyness analysis across the platform"}
                      style={selectedReferenceName === r.name ? { background: "var(--success)" } : {}}
                    >
                      {selectedReferenceName === r.name ? "✓ Selected" : "Select"}
                    </button>
                    <button
                      className="btn-small"
                      onClick={() => handleDelete(r.name)}
                      title="Delete this reference corpus"
                      style={{ background: "var(--danger)" }}
                    >
                      Delete
                    </button>
                  </>
                ) : isDownloading ? (
                  <>
                    <span className="status-spinner" />
                    <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>Downloading…</span>
                    <button
                      className="btn-small"
                      onClick={() => handleCancel(r.name)}
                      title="Cancel download"
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <button
                    className="btn-small"
                    onClick={() => handleDownload(r.name)}
                    disabled={!r.downloadable || downloadingName !== null}
                  >
                    {r.downloadable ? "Download" : "Coming Soon"}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {refs.length === 0 && !isLoading && !isError && (
        <div className="corpus-empty">
          No bundled reference corpora available. Check back in a future release.
        </div>
      )}

      {statusMsg && (
        <div className={clsx("uploader-status", statusKind)} style={{ marginTop: "var(--space-2)" }}>
          {statusMsg}
        </div>
      )}

      <ConfirmDialog
        state={confirmMsg ? { msg: confirmMsg, onConfirm: confirmDeleteRef } : null}
        onClose={() => { setConfirmMsg(null); pendingDeleteRef.current = null; }}
      />
    </div>
  );
}


// ─── Document Uploader (native picker + drag-drop) ────────────────

function DocumentUploader({ cid }: { cid: string }) {
  const qc = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const isTauri = isTauriRuntime();
  const [language, setLanguage] = useState<string>("auto");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [nativePaths, setNativePaths] = useState<string[]>([]);
  const [uploadStatus, setUploadStatus] = useState<string>("");

  const upload = useMutation({
    mutationFn: async () => {
      const lang = language === "auto" ? undefined : language;
      if (isTauri && nativePaths.length > 0) {
        return await nativeUploadCorpusFiles(cid, nativePaths, lang);
      } else {
        return await api.uploadDocuments(cid, selectedFiles, lang);
      }
    },
    onSuccess: (docs) => {
      qc.invalidateQueries({ queryKey: ["documents", cid] });
      qc.invalidateQueries({ queryKey: ["corpora"] });
      qc.invalidateQueries({ queryKey: ["corpus", cid] });
      setUploadStatus(`✓ ${docs.length} document(s) ingested, cleaned, tagged, and parsed`);
      setSelectedFiles([]);
      setNativePaths([]);
      setTimeout(() => setUploadStatus(""), 6000);
    },
    onError: (e: Error) => {
      setUploadStatus(`✗ Upload failed: ${e.message}`);
    },
  });

  const openFilePicker = () => fileInputRef.current?.click();

  const browseNative = async () => {
    try {
      const result = await nativePickCorpusFiles();
      if (result.ok && result.paths.length > 0) {
        setNativePaths(result.paths);
        setSelectedFiles([]);
        setUploadStatus(`${result.paths.length} file(s) selected. Click "Upload & Tag" to ingest.`);
      }
    } catch (e: any) {
      setUploadStatus(`File picker failed: ${e?.message || String(e)}`);
    }
  };

  const onInputChange = (files: FileList | null) => {
    const arr = Array.from(files ?? []);
    if (arr.length > 0) {
      setSelectedFiles(arr);
      setNativePaths([]);
      setUploadStatus(`${arr.length} file(s) selected. Click "Upload & Tag" to ingest.`);
    }
  };

  const doUpload = () => {
    if (selectedFiles.length === 0 && nativePaths.length === 0) return;
    upload.mutate();
  };

  const hasFiles = selectedFiles.length > 0 || nativePaths.length > 0;
  const fileCount = Math.max(selectedFiles.length, nativePaths.length);

  return (
    <div className="document-uploader">
      <div className="uploader-header">
        <h3 className="uploader-title">Upload Corpus Files</h3>
        <div className="uploader-lang-select">
          <label className="uploader-lang-label">Language:</label>
          <select value={language} onChange={(e) => setLanguage(e.target.value)} className="uploader-lang-dropdown">
            <option value="auto">Auto-detect</option>
            <option value="en">English</option>
            <option value="ar">Arabic</option>
            <option value="fr">French</option>
            <option value="de">German</option>
            <option value="es">Spanish</option>
            <option value="zh">Chinese</option>
          </select>
        </div>
      </div>

      <div
        className="dropzone"
        onClick={openFilePicker}
        onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add("drag-over"); }}
        onDragLeave={(e) => e.currentTarget.classList.remove("drag-over")}
        onDrop={(e) => {
          e.preventDefault();
          e.currentTarget.classList.remove("drag-over");
          onInputChange(e.dataTransfer.files);
        }}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openFilePicker(); } }}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={SUPPORTED_FORMATS}
          onChange={(e) => onInputChange(e.target.files)}
          style={{ position: "absolute", width: 0, height: 0, opacity: 0, pointerEvents: "none" }}
          aria-hidden="true"
        />
        <div className="dropzone-icon">{"\u2191"}</div>
        <div className="dropzone-label">Drop files here or click to upload</div>
        <div className="dropzone-formats">{FORMAT_LABELS}</div>
      </div>

      {isTauri && (
        <div className="uploader-native-picker">
          <button className="btn-secondary uploader-browse-btn" onClick={browseNative}>
            {"\u25CF"} Browse files... (native picker)
          </button>
        </div>
      )}

      {hasFiles && (
        <div className="uploader-file-list">
          <div className="uploader-file-list-header">
            <strong>{fileCount} file(s) selected</strong>
            <button className="btn-small" onClick={() => { setSelectedFiles([]); setNativePaths([]); }}>Clear</button>
          </div>
          <ul className="uploader-file-items">
            {selectedFiles.slice(0, 10).map((f, i) => (
              <li key={i} className="uploader-file-item">
                <span className="uploader-file-name">{f.name}</span>
                <span className="uploader-file-size">{(f.size / 1024).toFixed(1)} KB</span>
              </li>
            ))}
            {nativePaths.slice(0, 10).map((p, i) => (
              <li key={`np-${i}`} className="uploader-file-item">
                <span className="uploader-file-name">{p.split(/[/\\]/).pop() ?? p}</span>
                <span className="uploader-file-size">native</span>
              </li>
            ))}
            {fileCount > 10 && (
              <li className="uploader-file-item uploader-file-more">
                ...and {fileCount - 10} more
              </li>
            )}
          </ul>
          <div className="uploader-actions">
            <button
              className="btn-primary"
              onClick={doUpload}
              disabled={upload.isPending}
            >
              {upload.isPending ? "Uploading & processing..." : "Upload & Tag"}
            </button>
          </div>
        </div>
      )}

      {uploadStatus && (
        <div className={clsx("uploader-status", upload.isError ? "error" : upload.isSuccess ? "success" : "info")}>
          {uploadStatus}
        </div>
      )}

      <div className="uploader-pipeline-info">
        <strong>Auto-pipeline:</strong> Upload → Format detection → Encoding detection →
        Text cleaning (whitespace + BOM + zero-width) → Tokenization →
        POS tagging → Lemmatization → Dependency parsing → Sentence segmentation
      </div>
    </div>
  );
}


// ─── Document List ────────────────────────────────────────────────

function DocumentList({ cid }: { cid: string }) {
  const qc = useQueryClient();
  const docs = useQuery({
    queryKey: ["documents", cid],
    queryFn: () => api.listDocuments(cid),
    refetchInterval: 3_000,
  });
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [recompiling, setRecompiling] = useState(false);
  const [status, setStatus] = useState<{ kind: "success" | "error" | "info"; msg: string } | null>(null);
  // v0.1.19: confirm dialog state (replaces window.confirm)
  const [confirmState, setConfirmState] = useState<{ msg: string; onConfirm: () => void } | null>(null);
  const pendingDelete = useRef<{ did: string; filename: string } | null>(null);
  // v0.1.19: metadata editing state
  const [editingMetaId, setEditingMetaId] = useState<string | null>(null);
  const [metaForm, setMetaForm] = useState<{ genre: string; register: string; year: string }>({ genre: "", register: "", year: "" });
  // v0.1.19: subcorpus state
  const [showSubcorpusForm, setShowSubcorpusForm] = useState(false);
  const [subcorpusForm, setSubcorpusForm] = useState({ name: "", description: "", genre: "", register: "", yearMin: "", yearMax: "" });
  const subcorpora = useQuery({
    queryKey: ["subcorpora", cid],
    queryFn: () => api.listSubcorpora(cid),
  });

  const showStatus = (msg: string, kind: "success" | "error" | "info" = "info") => {
    setStatus({ kind, msg });
    if (msg) setTimeout(() => setStatus(null), 6000);
  };

  const handleDelete = (did: string, filename: string) => {
    // v0.1.19: replaced window.confirm() with ConfirmDialog (fixes ACL error)
    pendingDelete.current = { did, filename };
    setConfirmState({
      msg: `Delete "${filename}"? This removes it from the corpus and recomputes stats.`,
      onConfirm: async () => {
        const pending = pendingDelete.current;
        if (!pending) return;
        setDeletingId(pending.did);
        try {
          const result = await api.deleteDocument(cid, pending.did);
          showStatus(`✓ Deleted "${pending.filename}". ${result.remaining_documents} document(s) remaining.`, "success");
          qc.invalidateQueries({ queryKey: ["documents", cid] });
          qc.invalidateQueries({ queryKey: ["corpora"] });
          qc.invalidateQueries({ queryKey: ["corpus", cid] });
        } catch (e: any) {
          showStatus(`✗ Delete failed: ${e?.message || String(e)}`, "error");
        } finally {
          setDeletingId(null);
          pendingDelete.current = null;
        }
      },
    });
  };

  const handleRecompile = async () => {
    setRecompiling(true);
    showStatus("Recompiling corpus (re-running NLP pipeline)...", "info");
    try {
      const result = await api.recompileCorpus(cid);
      showStatus(`✓ Recompiled ${result.recompiled}/${result.total_documents} documents. ${result.token_count} tokens, ${result.type_count} types.`, "success");
      qc.invalidateQueries({ queryKey: ["corpora"] });
      qc.invalidateQueries({ queryKey: ["corpus", cid] });
    } catch (e: any) {
      showStatus(`✗ Recompile failed: ${e?.message || String(e)}`, "error");
    } finally {
      setRecompiling(false);
    }
  };

  // v0.1.19: metadata editing
  const handleEditMeta = (doc: any) => {
    setEditingMetaId(doc.id);
    setMetaForm({
      genre: doc.meta?.genre || "",
      register: doc.meta?.register || "",
      year: doc.meta?.year || "",
    });
  };

  const handleSaveMeta = async (did: string) => {
    try {
      const meta: Record<string, string> = {};
      if (metaForm.genre) meta.genre = metaForm.genre;
      if (metaForm.register) meta.register = metaForm.register;
      if (metaForm.year) meta.year = metaForm.year;
      await api.updateDocumentMeta(cid, did, meta);
      showStatus("✓ Metadata updated.", "success");
      qc.invalidateQueries({ queryKey: ["documents", cid] });
      setEditingMetaId(null);
    } catch (e: any) {
      showStatus(`✗ Failed: ${e?.message || String(e)}`, "error");
    }
  };

  // v0.1.19: subcorpus creation
  const handleCreateSubcorpus = async () => {
    const filter: Record<string, unknown> = {};
    if (subcorpusForm.genre) filter.genre = subcorpusForm.genre;
    if (subcorpusForm.register) filter.register = subcorpusForm.register;
    if (subcorpusForm.yearMin) filter.year_min = parseInt(subcorpusForm.yearMin);
    if (subcorpusForm.yearMax) filter.year_max = parseInt(subcorpusForm.yearMax);
    try {
      await api.createSubcorpus(cid, subcorpusForm.name, filter, subcorpusForm.description);
      showStatus(`✓ Subcorpus "${subcorpusForm.name}" created.`, "success");
      qc.invalidateQueries({ queryKey: ["subcorpora", cid] });
      setShowSubcorpusForm(false);
      setSubcorpusForm({ name: "", description: "", genre: "", register: "", yearMin: "", yearMax: "" });
    } catch (e: any) {
      showStatus(`✗ Failed: ${e?.message || String(e)}`, "error");
    }
  };

  const handleDeleteSubcorpus = async (sid: string, name: string) => {
    setConfirmState({
      msg: `Delete subcorpus "${name}"? This does NOT delete the documents.`,
      onConfirm: async () => {
        try {
          await api.deleteSubcorpus(cid, sid);
          showStatus(`✓ Deleted subcorpus "${name}".`, "info");
          qc.invalidateQueries({ queryKey: ["subcorpora", cid] });
        } catch (e: any) {
          showStatus(`✗ Failed: ${e?.message || String(e)}`, "error");
        }
      },
    });
  };

  return (
    <div className="document-list-section">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "var(--space-2)" }}>
        <h3 className="document-list-title">Documents ({docs.data?.length ?? 0})</h3>
        <div style={{ display: "flex", gap: "var(--space-2)" }}>
          {docs.data && docs.data.length > 0 && (
            <button
              className="btn-small"
              onClick={() => setShowSubcorpusForm(!showSubcorpusForm)}
              title="Create a subcorpus (saved filter) for register-matched analysis"
            >
              + Subcorpus
            </button>
          )}
          {docs.data && docs.data.length > 0 && (
            <button
              className="btn-small"
              onClick={handleRecompile}
              disabled={recompiling}
              title="Re-run the full NLP pipeline on all documents"
            >
              {recompiling ? "Compiling…" : "↻ Recompile"}
            </button>
          )}
        </div>
      </div>

      {status && (
        <div className={clsx("uploader-status", status.kind)} style={{ marginBottom: "var(--space-2)" }}>
          {status.msg}
        </div>
      )}

      {/* v0.1.19: Subcorpus list */}
      {subcorpora.data && subcorpora.data.length > 0 && (
        <div style={{ marginBottom: "var(--space-2)", display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
          <span style={{ fontSize: "11px", color: "var(--text-muted)", alignSelf: "center" }}>Subcorpora:</span>
          {subcorpora.data.map((sc) => (
            <span key={sc.id} style={{
              display: "inline-flex", alignItems: "center", gap: "4px",
              background: "var(--bg-subtle)", border: "1px solid var(--border)",
              borderRadius: "12px", padding: "2px 8px", fontSize: "11px",
            }}>
              {sc.name}
              <button
                onClick={() => handleDeleteSubcorpus(sc.id, sc.name)}
                style={{ background: "none", border: "none", color: "var(--danger)", cursor: "pointer", fontSize: "11px", padding: "0" }}
                title="Delete subcorpus"
              >✕</button>
            </span>
          ))}
        </div>
      )}

      {/* v0.1.19: Subcorpus creation form */}
      {showSubcorpusForm && (
        <div style={{
          marginBottom: "var(--space-2)", padding: "var(--space-3)",
          background: "var(--bg-subtle)", borderRadius: "var(--radius-sm)",
          border: "1px solid var(--border)", fontSize: "12px",
        }}>
          <strong>Create Subcorpus</strong>
          <p style={{ fontSize: "11px", color: "var(--text-muted)", margin: "4px 0 8px" }}>
            A subcorpus is a saved filter over document metadata. Only documents matching the filter will be included in analyses that use this subcorpus.
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: "var(--space-2)", marginBottom: "var(--space-2)" }}>
            <input placeholder="Name (e.g. News only)" value={subcorpusForm.name} onChange={(e) => setSubcorpusForm({...subcorpusForm, name: e.target.value})} style={{ fontSize: "12px" }} />
            <input placeholder="Genre (e.g. news)" value={subcorpusForm.genre} onChange={(e) => setSubcorpusForm({...subcorpusForm, genre: e.target.value})} style={{ fontSize: "12px" }} />
            <input placeholder="Register (e.g. academic)" value={subcorpusForm.register} onChange={(e) => setSubcorpusForm({...subcorpusForm, register: e.target.value})} style={{ fontSize: "12px" }} />
            <input placeholder="Year range (e.g. 2010-2020)" value={subcorpusForm.yearMin} onChange={(e) => setSubcorpusForm({...subcorpusForm, yearMin: e.target.value})} style={{ fontSize: "12px" }} />
          </div>
          <div style={{ display: "flex", gap: "var(--space-2)" }}>
            <button className="btn-small btn-primary" onClick={handleCreateSubcorpus} disabled={!subcorpusForm.name.trim()}>Create</button>
            <button className="btn-small" onClick={() => setShowSubcorpusForm(false)}>Cancel</button>
          </div>
        </div>
      )}

      {docs.data && docs.data.length > 0 ? (
        <table className="document-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid var(--border)" }}>
              <th style={{ padding: "var(--space-2)", fontWeight: 600 }}>Filename</th>
              <th style={{ padding: "var(--space-2)", fontWeight: 600 }}>Format</th>
              <th style={{ padding: "var(--space-2)", fontWeight: 600 }}>Genre</th>
              <th style={{ padding: "var(--space-2)", fontWeight: 600 }}>Register</th>
              <th style={{ padding: "var(--space-2)", fontWeight: 600 }}>Size</th>
              <th style={{ padding: "var(--space-2)", fontWeight: 600 }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {docs.data.map((d) => (
              <tr key={d.id} style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: "var(--space-2)", fontWeight: 500 }}>{d.filename}</td>
                <td style={{ padding: "var(--space-2)", color: "var(--text-muted)" }}>{d.format}</td>
                {editingMetaId === d.id ? (
                  <>
                    <td style={{ padding: "var(--space-2)" }}>
                      <input value={metaForm.genre} onChange={(e) => setMetaForm({...metaForm, genre: e.target.value})} placeholder="genre" style={{ fontSize: "11px", width: "80px", padding: "2px 4px" }} />
                    </td>
                    <td style={{ padding: "var(--space-2)" }}>
                      <input value={metaForm.register} onChange={(e) => setMetaForm({...metaForm, register: e.target.value})} placeholder="register" style={{ fontSize: "11px", width: "80px", padding: "2px 4px" }} />
                    </td>
                  </>
                ) : (
                  <>
                    <td style={{ padding: "var(--space-2)", color: "var(--text-muted)" }}>{(d.meta as any)?.genre || "—"}</td>
                    <td style={{ padding: "var(--space-2)", color: "var(--text-muted)" }}>{(d.meta as any)?.register || "—"}</td>
                  </>
                )}
                <td style={{ padding: "var(--space-2)", color: "var(--text-muted)" }}>{(d.raw_size_bytes / 1024).toFixed(1)} KB</td>
                <td style={{ padding: "var(--space-2)" }}>
                  <div style={{ display: "flex", gap: "4px" }}>
                    {editingMetaId === d.id ? (
                      <>
                        <button className="btn-small" onClick={() => handleSaveMeta(d.id)} style={{ fontSize: "11px", padding: "2px 6px" }}>Save</button>
                        <button className="btn-small" onClick={() => setEditingMetaId(null)} style={{ fontSize: "11px", padding: "2px 6px" }}>Cancel</button>
                      </>
                    ) : (
                      <>
                        <button className="btn-small" onClick={() => handleEditMeta(d)} style={{ fontSize: "11px", padding: "2px 6px" }} title="Edit metadata (genre, register, year)">✎ Tag</button>
                        <button
                          className="btn-small"
                          onClick={() => handleDelete(d.id, d.filename)}
                          disabled={deletingId === d.id}
                          style={{ background: "var(--danger)", fontSize: "11px", padding: "2px 6px" }}
                          title="Remove this file from the corpus"
                        >
                          {deletingId === d.id ? "…" : "✕"}
                        </button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="corpus-empty">No documents yet. Upload files to start the annotation pipeline.</div>
      )}

      <ConfirmDialog
        state={confirmState}
        onClose={() => { setConfirmState(null); pendingDelete.current = null; }}
      />
    </div>
  );
}


// ─── Reference Upload ─────────────────────────────────────────────

function ReferenceUpload() {
  const setActive = useApp((s) => s.setReferenceCorpus);
  const activeProjectId = useApp((s) => s.activeProjectId);
  const activeReferenceId = useApp((s) => s.referenceCorpusId);
  const qc = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const isTauri = isTauriRuntime();
  const [showNewCorpus, setShowNewCorpus] = useState(false);
  const [newCorpusName, setNewCorpusName] = useState("");
  const [newCorpusLang, setNewCorpusLang] = useState("en");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [nativePaths, setNativePaths] = useState<string[]>([]);
  const [statusMsg, setStatusMsg] = useState("");

  const ACCEPT = SUPPORTED_FORMATS;

  const corpora = useQuery({
    queryKey: ["corpora", activeProjectId],
    queryFn: () => activeProjectId ? api.listCorpora(activeProjectId) : Promise.resolve([]),
    enabled: !!activeProjectId,
  });

  const createAndUpload = useMutation({
    mutationFn: async ({ name, lang }: { name: string; lang: string }) => {
      if (!activeProjectId) throw new Error("No active project");
      const corpus = await api.createCorpus(activeProjectId, name, lang);
      if (nativePaths.length > 0) {
        await nativeUploadCorpusFiles(corpus.id, nativePaths, lang);
      } else if (selectedFiles.length > 0) {
        await api.uploadDocuments(corpus.id, selectedFiles, lang);
      }
      return corpus;
    },
    onSuccess: (corpus) => {
      setActive(corpus.id);
      qc.invalidateQueries({ queryKey: ["corpora"] });
      setShowNewCorpus(false);
      setNewCorpusName("");
      setSelectedFiles([]);
      setNativePaths([]);
      setStatusMsg(`Created "${corpus.name}" and uploaded successfully`);
      setTimeout(() => setStatusMsg(""), 5000);
    },
    onError: (e: Error) => setStatusMsg(`Upload failed: ${e.message}`),
  });

  const uploadToSelected = useMutation({
    mutationFn: async ({ cid }: { cid: string }) => {
      if (nativePaths.length > 0) {
        await nativeUploadCorpusFiles(cid, nativePaths);
      } else if (selectedFiles.length > 0) {
        await api.uploadDocuments(cid, selectedFiles);
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["corpora"] });
      setSelectedFiles([]);
      setNativePaths([]);
      setStatusMsg("Uploaded successfully");
      setTimeout(() => setStatusMsg(""), 5000);
    },
    onError: (e: Error) => setStatusMsg(`Upload failed: ${e.message}`),
  });

  const onUploadFiles = (files: File[]) => {
    if (files.length === 0) return;
    setSelectedFiles(files);
    setNativePaths([]);
    setStatusMsg(`${files.length} file(s) ready. Click "Upload & Tag" to ingest.`);
  };

  const doUpload = () => {
    if (selectedFiles.length === 0 && nativePaths.length === 0) return;
    if (activeReferenceId) {
      uploadToSelected.mutate({ cid: activeReferenceId });
    } else if (showNewCorpus && newCorpusName.trim() && activeProjectId) {
      createAndUpload.mutate({ name: newCorpusName.trim(), lang: newCorpusLang });
    }
  };

  const browseNative = async () => {
    try {
      const result = await nativePickCorpusFiles();
      if (result.ok && result.paths.length > 0) {
        setNativePaths(result.paths);
        setSelectedFiles([]);
        setStatusMsg(`${result.paths.length} file(s) selected. Click "Upload & Tag" to ingest.`);
      }
    } catch (e: any) {
      setStatusMsg(`File picker failed: ${e?.message || String(e)}`);
    }
  };

  const hasFiles = selectedFiles.length > 0 || nativePaths.length > 0;
  const fileCount = Math.max(selectedFiles.length, nativePaths.length);

  return (
    <div className="reference-upload">
      <p className="reference-section-desc">
        Upload your own reference corpus files, or select an existing corpus.
      </p>

      <div className="reference-upload-section">
        <strong>Option 1: Use an existing corpus</strong>
        <select
          value={activeReferenceId ?? ""}
          onChange={(e) => setActive(e.target.value || null)}
          className="reference-select"
        >
          <option value="">— Select a corpus —</option>
          {corpora.data?.map((c) => (
            <option key={c.id} value={c.id}>{c.name} ({c.language}) — {c.stats?.document_count ?? 0} docs</option>
          ))}
        </select>
      </div>

      <div className="reference-upload-section">
        <strong>Option 2: Upload reference files</strong>
        {!showNewCorpus ? (
          <>
            {activeReferenceId ? (
              <>
                <div className="dropzone" onClick={() => fileInputRef.current?.click()} role="button" tabIndex={0}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInputRef.current?.click(); } }}
                  onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add("drag-over"); }}
                  onDragLeave={(e) => e.currentTarget.classList.remove("drag-over")}
                  onDrop={(e) => { e.preventDefault(); e.currentTarget.classList.remove("drag-over"); onUploadFiles(Array.from(e.dataTransfer.files)); }}>
                  <input ref={fileInputRef} type="file" multiple accept={ACCEPT}
                    onChange={(e) => { const files = Array.from(e.target.files ?? []); if (files.length > 0) onUploadFiles(files); e.target.value = ""; }}
                    style={{ position: "absolute", width: 0, height: 0, opacity: 0, pointerEvents: "none" }} aria-hidden="true" />
                  <div className="dropzone-icon">{"\u2191"}</div>
                  <div className="dropzone-label">{uploadToSelected.isPending ? "Uploading..." : "Drop reference files here or click to upload"}</div>
                  <div className="dropzone-formats">{FORMAT_LABELS}</div>
                </div>
                {isTauri && (
                  <button className="btn-secondary" onClick={browseNative} style={{ marginTop: "var(--space-2)" }}>
                    {"\u25CF"} Browse files... (native picker)
                  </button>
                )}
              </>
            ) : (
              <button className="btn-primary" onClick={() => setShowNewCorpus(true)}>+ Create a new reference corpus</button>
            )}
          </>
        ) : (
          <div className="reference-new-corpus">
            <input type="text" value={newCorpusName} onChange={(e) => setNewCorpusName(e.target.value)}
              placeholder="Reference corpus name" className="reference-name-input" />
            <select value={newCorpusLang} onChange={(e) => setNewCorpusLang(e.target.value)}>
              <option value="en">English</option>
              <option value="ar">Arabic</option>
            </select>
            <div className="dropzone" onClick={() => newCorpusName.trim() && fileInputRef.current?.click()} role="button" tabIndex={0}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); if (newCorpusName.trim()) fileInputRef.current?.click(); } }}
              onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add("drag-over"); }}
              onDragLeave={(e) => e.currentTarget.classList.remove("drag-over")}
              onDrop={(e) => { e.preventDefault(); e.currentTarget.classList.remove("drag-over"); onUploadFiles(Array.from(e.dataTransfer.files)); }}
              style={{ opacity: newCorpusName.trim() ? 1 : 0.5 }}>
              <input ref={fileInputRef} type="file" multiple accept={ACCEPT}
                onChange={(e) => { const files = Array.from(e.target.files ?? []); if (files.length > 0) onUploadFiles(files); e.target.value = ""; }}
                style={{ position: "absolute", width: 0, height: 0, opacity: 0, pointerEvents: "none" }} aria-hidden="true" />
              <div className="dropzone-icon">{"\u2191"}</div>
              <div className="dropzone-label">{createAndUpload.isPending ? "Creating + uploading..." : "Drop reference files here or click to upload"}</div>
              <div className="dropzone-formats">{FORMAT_LABELS}</div>
            </div>
            {isTauri && (
              <button className="btn-secondary" onClick={browseNative} disabled={!newCorpusName.trim()} style={{ marginTop: "var(--space-2)" }}>
                {"\u25CF"} Browse files... (native picker)
              </button>
            )}
            <button className="btn-small" onClick={() => setShowNewCorpus(false)}>Cancel</button>
          </div>
        )}
      </div>

      {hasFiles && (
        <div className="uploader-file-list">
          <div className="uploader-file-list-header">
            <strong>{fileCount} file(s) selected</strong>
            <button className="btn-small" onClick={() => { setSelectedFiles([]); setNativePaths([]); }}>Clear</button>
          </div>
          <ul className="uploader-file-items">
            {selectedFiles.slice(0, 10).map((f, i) => (
              <li key={i} className="uploader-file-item">
                <span className="uploader-file-name">{f.name}</span>
                <span className="uploader-file-size">{(f.size / 1024).toFixed(1)} KB</span>
              </li>
            ))}
            {nativePaths.slice(0, 10).map((p, i) => (
              <li key={`np-${i}`} className="uploader-file-item">
                <span className="uploader-file-name">{p.split(/[/\\]/).pop() ?? p}</span>
                <span className="uploader-file-size">native</span>
              </li>
            ))}
            {fileCount > 10 && (
              <li className="uploader-file-item uploader-file-more">...and {fileCount - 10} more</li>
            )}
          </ul>
          <div className="uploader-actions">
            <button className="btn-primary" onClick={doUpload} disabled={createAndUpload.isPending || uploadToSelected.isPending}>
              {(createAndUpload.isPending || uploadToSelected.isPending) ? "Uploading..." : "Upload & Tag"}
            </button>
          </div>
        </div>
      )}

      {statusMsg && (
        <div className={clsx("uploader-status", statusMsg.includes("successfully") || statusMsg.includes("ready") ? "success" : statusMsg.includes("failed") ? "error" : "info")}>
          {statusMsg}
        </div>
      )}
    </div>
  );
}


// ─── New Corpus Dialog ────────────────────────────────────────────

function NewCorpusDialog({ onCreate }: { onCreate: (name: string, language: string, genre: string) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [language, setLanguage] = useState("en");
  const [genre, setGenre] = useState("mixed");

  return (
    <>
      <button className="btn-small" onClick={() => setOpen(true)}>+ New</button>
      {open && (
        <div className="modal-backdrop" onClick={() => setOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Create New Corpus</h3>
            <label>
              Name:
              <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="My Corpus" />
            </label>
            <label>
              Language:
              <select value={language} onChange={(e) => setLanguage(e.target.value)}>
                <option value="en">English</option>
                <option value="ar">Arabic</option>
                <option value="fr">French</option>
                <option value="de">German</option>
                <option value="es">Spanish</option>
                <option value="zh">Chinese</option>
              </select>
            </label>
            <label>
              Genre:
              <select value={genre} onChange={(e) => setGenre(e.target.value)}>
                <option value="mixed">Mixed</option>
                <option value="academic">Academic</option>
                <option value="news">News</option>
                <option value="fiction">Fiction</option>
                <option value="spoken">Spoken</option>
                <option value="blog">Blog</option>
                <option value="legal">Legal</option>
                <option value="medical">Medical</option>
              </select>
            </label>
            <div className="modal-actions">
              <button onClick={() => setOpen(false)}>Cancel</button>
              <button className="primary" disabled={!name.trim()} onClick={() => {
                onCreate(name, language, genre);
                setOpen(false);
                setName("");
              }}>Create</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
