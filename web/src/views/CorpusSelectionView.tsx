/**
 * CorpusSelectionView — unified view for managing both the user's study
 * corpus (target) and the reference corpus (for keyness comparison).
 *
 * The target mode includes:
 *   - Project selector (create/select a project)
 *   - Corpus list (create/select a corpus within the project)
 *   - File picker (upload .txt, .docx, .pdf, .html, .xml, .csv)
 *   - Document list (shows ingested files with format/language/size)
 *   - Clean button (opens the 16-option cleaning modal)
 *
 * The reference mode includes:
 *   - Download (search HuggingFace + Wikipedia + OPUS)
 *   - Upload (file picker for reference corpus files)
 *   - Bundled (pre-built frequency lists: BE06, AmE06, etc.)
 */
import { useState, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import { api, type HubSearchResult, type CleaningOptions } from "@/lib/api";
import { useApp } from "@/store/app";

type CorpusMode = "target" | "reference";

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
              {c.language} · {c.stats?.document_count ?? 0} docs · {(c.stats?.token_count ?? 0).toLocaleString()} tokens
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
    </section>
  );
}


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

  const clean = useMutation({
    mutationFn: () => api.cleanCorpus(cid, opts),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["corpora"] });
      qc.invalidateQueries({ queryKey: ["documents", cid] });
      setOpen(false);
      const delta = data.new_token_count - data.old_token_count;
      alert(
        `Corpus cleaned.\n\n` +
        `Documents: ${data.documents_cleaned}\n` +
        `Tokens: ${data.old_token_count.toLocaleString()} -> ${data.new_token_count.toLocaleString()} (${delta >= 0 ? "+" : ""}${delta.toLocaleString()})\n` +
        `Types: ${data.old_type_count.toLocaleString()} -> ${data.new_type_count.toLocaleString()}`
      );
    },
    onError: (e: Error) => {
      alert(`Cleaning failed: ${e.message}`);
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
                <div className="clean-group-label">Case & Punctuation</div>
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
  const [query, setQuery] = useState("");
  const [language, setLanguage] = useState<"en" | "ar">("en");
  const [searchParams, setSearchParams] = useState<{ q: string; lang: string } | null>(null);

  const search = useQuery({
    queryKey: ["hub-search", searchParams],
    queryFn: () => searchParams ? api.hubSearch(searchParams.q, searchParams.lang, "all", 20) : Promise.resolve(null),
    enabled: !!searchParams,
  });

  const doSearch = () => {
    if (!query.trim()) return;
    setSearchParams({ q: query.trim(), lang: language });
  };

  const handleDownload = async (result: HubSearchResult) => {
    const url = api.hubDownloadUrl(result.hub, result.id, result.title, result.extra);
    const a = document.createElement("a");
    a.href = url;
    a.download = "";
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  return (
    <div className="reference-download">
      <p className="reference-section-desc">
        Search and download open-access reference corpora.
      </p>
      <div className="reference-search-bar">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && doSearch()}
          placeholder="Search for a reference corpus..."
          className="reference-search-input"
        />
        <select value={language} onChange={(e) => setLanguage(e.target.value as "en" | "ar")}>
          <option value="en">English</option>
          <option value="ar">Arabic</option>
        </select>
        <button className="btn-primary" onClick={doSearch} disabled={!query.trim()}>Search</button>
      </div>

      {search.data?.results.map((result) => (
        <div key={result.id} className={clsx("hub-result-card", `hub-${result.hub}`)}>
          <div className="hub-result-header">
            <span className="hub-result-hub-badge">{result.hub}</span>
            <strong className="hub-result-title">{result.title}</strong>
          </div>
          <p className="hub-result-desc">{result.description}</p>
          <div className="hub-result-meta">
            <span className="hub-tag">{result.size}</span>
            <span className="hub-tag">{result.license}</span>
          </div>
          <button className="btn-small hub-download-btn" onClick={() => handleDownload(result)}>Download</button>
        </div>
      ))}

      {search.data?.results.length === 0 && !search.isFetching && (
        <div className="corpus-empty">No results. Try a different search.</div>
      )}
    </div>
  );
}


function ReferenceUpload() {
  const setActive = useApp((s) => s.setReferenceCorpus);
  const activeProjectId = useApp((s) => s.activeProjectId);
  const activeReferenceId = useApp((s) => s.referenceCorpusId);
  const qc = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [showNewCorpus, setShowNewCorpus] = useState(false);
  const [newCorpusName, setNewCorpusName] = useState("");
  const [newCorpusLang, setNewCorpusLang] = useState("en");

  const corpora = useQuery({
    queryKey: ["corpora", activeProjectId],
    queryFn: () => activeProjectId ? api.listCorpora(activeProjectId) : Promise.resolve([]),
    enabled: !!activeProjectId,
  });

  const createAndUpload = useMutation({
    mutationFn: async ({ name, lang, files }: { name: string; lang: string; files: File[] }) => {
      if (!activeProjectId) throw new Error("No active project");
      const corpus = await api.createCorpus(activeProjectId, name, lang);
      await api.uploadDocuments(corpus.id, files);
      return corpus;
    },
    onSuccess: (corpus) => {
      setActive(corpus.id);
      qc.invalidateQueries({ queryKey: ["corpora"] });
      setShowNewCorpus(false);
      setNewCorpusName("");
    },
  });

  const uploadToSelected = useMutation({
    mutationFn: ({ cid, files }: { cid: string; files: File[] }) => api.uploadDocuments(cid, files),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["corpora"] }),
  });

  const onUploadFiles = (files: File[]) => {
    if (files.length === 0) return;
    if (activeReferenceId) {
      uploadToSelected.mutate({ cid: activeReferenceId, files });
    } else if (showNewCorpus && newCorpusName.trim() && activeProjectId) {
      createAndUpload.mutate({ name: newCorpusName.trim(), lang: newCorpusLang, files });
    }
  };

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
              <div className="dropzone" onClick={() => fileInputRef.current?.click()} role="button" tabIndex={0}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInputRef.current?.click(); } }}>
                <input ref={fileInputRef} type="file" multiple accept=".txt,.md,.docx,.pdf,.html,.htm,.xml,.csv"
                  onChange={(e) => { const files = Array.from(e.target.files ?? []); if (files.length > 0) onUploadFiles(files); e.target.value = ""; }}
                  style={{ position: "absolute", width: 0, height: 0, opacity: 0, pointerEvents: "none" }} aria-hidden="true" />
                <div className="dropzone-icon">{"\u2191"}</div>
                <div className="dropzone-label">{uploadToSelected.isPending ? "Uploading..." : "Drop reference files here or click to upload"}</div>
                <div className="dropzone-formats">.txt · .md · .docx · .pdf · .html · .xml · .csv</div>
              </div>
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
              style={{ opacity: newCorpusName.trim() ? 1 : 0.5 }}>
              <input ref={fileInputRef} type="file" multiple accept=".txt,.md,.docx,.pdf,.html,.htm,.xml,.csv"
                onChange={(e) => { const files = Array.from(e.target.files ?? []); if (files.length > 0) onUploadFiles(files); e.target.value = ""; }}
                style={{ position: "absolute", width: 0, height: 0, opacity: 0, pointerEvents: "none" }} aria-hidden="true" />
              <div className="dropzone-icon">{"\u2191"}</div>
              <div className="dropzone-label">{createAndUpload.isPending ? "Creating + uploading..." : "Drop reference files here or click to upload"}</div>
              <div className="dropzone-formats">.txt · .md · .docx · .pdf · .html · .xml · .csv</div>
            </div>
            <button className="btn-small" onClick={() => setShowNewCorpus(false)}>Cancel</button>
          </div>
        )}
      </div>
    </div>
  );
}


function BundledReferences() {
  const bundled = [
    { name: "BE06", desc: "1M words, British English written (Baker 2009)", size: "~5 MB", available: true },
    { name: "AmE06", desc: "1M words, American English written (Baker 2009)", size: "~5 MB", available: true },
    { name: "BNC Baby", desc: "4M words, British National Corpus sample", size: "~12 MB", available: false },
    { name: "Brown", desc: "1M words, American English (1961)", size: "~5 MB", available: false },
  ];

  return (
    <div className="bundled-references">
      <p className="reference-section-desc">
        Pre-built reference frequency lists, bundled with CorpusMind.
      </p>
      <div className="bundled-grid">
        {bundled.map((b) => (
          <div key={b.name} className={clsx("bundled-card", { unavailable: !b.available })}>
            <div className="bundled-header">
              <strong>{b.name}</strong>
              <span className="bundled-size">{b.size}</span>
            </div>
            <p className="bundled-desc">{b.desc}</p>
            <button className="btn-small" disabled={!b.available} title={b.available ? "Use as reference" : "Coming soon"}>
              {b.available ? "Use" : "N/A"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}


function DocumentUploader({ cid }: { cid: string }) {
  const qc = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const upload = useMutation({
    mutationFn: (files: File[]) => api.uploadDocuments(cid, files),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["documents", cid] });
      qc.invalidateQueries({ queryKey: ["corpora"] });
    },
  });

  const openFilePicker = () => fileInputRef.current?.click();

  return (
    <div
      className="dropzone"
      onClick={openFilePicker}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openFilePicker(); } }}
    >
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".txt,.md,.docx,.pdf,.html,.htm,.xml,.csv"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length > 0) upload.mutate(files);
          e.target.value = "";
        }}
        style={{ position: "absolute", width: 0, height: 0, opacity: 0, pointerEvents: "none" }}
        aria-hidden="true"
      />
      <div className="dropzone-icon">{"\u2191"}</div>
      <div className="dropzone-label">
        {upload.isPending ? "Uploading & tagging..." : "Drop files here or click to upload"}
      </div>
      <div className="dropzone-formats">.txt · .md · .docx · .pdf · .html · .xml · .csv</div>
      {upload.isError && <div className="error">{String(upload.error)}</div>}
      {upload.data && <div className="success">Ingested {upload.data.length} document(s).</div>}
    </div>
  );
}


function DocumentList({ cid }: { cid: string }) {
  const docs = useQuery({
    queryKey: ["documents", cid],
    queryFn: () => api.listDocuments(cid),
    refetchInterval: 3_000,
  });

  return (
    <div className="document-list-section">
      <h3 className="document-list-title">Documents</h3>
      <ul className="corpus-list">
        {docs.data?.map((d) => (
          <li key={d.id} className="corpus-list-item">
            <div className="corpus-item-name">{d.filename}</div>
            <div className="corpus-item-meta">
              {d.format} · {d.detected_language ?? "?"} · {(d.raw_size_bytes / 1024).toFixed(1)} KB
            </div>
          </li>
        ))}
        {docs.data?.length === 0 && <li className="corpus-empty">No documents yet.</li>}
      </ul>
    </div>
  );
}


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
            <h3>New corpus</h3>
            <label>Name<input value={name} onChange={(e) => setName(e.target.value)} /></label>
            <label>Language
              <select value={language} onChange={(e) => setLanguage(e.target.value)}>
                <option value="en">English</option>
                <option value="ar">Arabic</option>
                <option value="fr">French</option>
                <option value="de">German</option>
                <option value="es">Spanish</option>
              </select>
            </label>
            <label>Genre / Register
              <select value={genre} onChange={(e) => setGenre(e.target.value)}>
                <option value="mixed">Mixed (default)</option>
                <option value="academic">Academic</option>
                <option value="news">News</option>
                <option value="spoken">Spoken</option>
                <option value="fiction">Fiction</option>
                <option value="blog">Blog / Social media</option>
                <option value="legal">Legal</option>
                <option value="medical">Medical</option>
                <option value="business">Business</option>
                <option value="religious">Religious</option>
                <option value="other">Other</option>
              </select>
            </label>
            <div className="modal-actions">
              <button onClick={() => setOpen(false)}>Cancel</button>
              <button className="primary" disabled={!name} onClick={() => { onCreate(name, language, genre); setOpen(false); setName(""); }}>Create</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
