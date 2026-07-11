/**
 * CorpusManager — project list, corpus list, document upload (drag-drop),
 * pipeline-recipe display (§8.1, §8.2), and on-demand corpus cleaning.
 */
import { useState, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import { api, type CleaningOptions } from "@/lib/api";
import { useApp } from "@/store/app";

export function CorpusManagerView() {
  const qc = useQueryClient();
  const activeProjectId = useApp((s) => s.activeProjectId);
  const activeCorpusId = useApp((s) => s.activeCorpusId);
  const setActiveProject = useApp((s) => s.setActiveProject);
  const setActiveCorpus = useApp((s) => s.setActiveCorpus);

  const projects = useQuery({ queryKey: ["projects"], queryFn: api.listProjects });
  const corpora = useQuery({
    queryKey: ["corpora", activeProjectId],
    queryFn: () => (activeProjectId ? api.listCorpora(activeProjectId) : Promise.resolve([])),
    enabled: !!activeProjectId,
  });

  const createProject = useMutation({
    mutationFn: ({ name, language }: { name: string; language: string }) =>
      api.createProject(name, language),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });

  const createCorpus = useMutation({
    mutationFn: ({ pid, name, language }: { pid: string; name: string; language: string }) =>
      api.createCorpus(pid, name, language),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["corpora"] }),
  });

  return (
    <div className="cm-grid">
      {/* Projects column */}
      <section className="panel">
        <header className="panel-header">
          <h2>Projects</h2>
          <NewProjectDialog onCreate={(name, lang) => createProject.mutate({ name, language: lang })} />
        </header>
        <ul className="item-list">
          {projects.data?.map((p) => (
            <li
              key={p.id}
              className={clsx("item", { active: p.id === activeProjectId })}
              onClick={() => setActiveProject(p.id)}
            >
              <div className="item-name">{p.name}</div>
              <div className="item-meta">
                {p.language} · {p.corpus_count} corpus{p.corpus_count === 1 ? "" : "es"} · {new Date(p.created_at).toLocaleDateString()}
              </div>
            </li>
          ))}
          {projects.data?.length === 0 && (
            <li className="empty">No projects yet — create one to get started.</li>
          )}
        </ul>
      </section>

      {/* Corpora column */}
      <section className="panel">
        <header className="panel-header">
          <h2>Corpora {activeProjectId && `· ${projects.data?.find((p) => p.id === activeProjectId)?.name}`}</h2>
          {activeProjectId && (
            <NewCorpusDialog onCreate={(name, lang) => createCorpus.mutate({ pid: activeProjectId, name, language: lang })} />
          )}
        </header>
        {!activeProjectId && <div className="empty">Select a project to see its corpora.</div>}
        <ul className="item-list">
          {corpora.data?.map((c) => (
            <li
              key={c.id}
              className={clsx("item", { active: c.id === activeCorpusId })}
              onClick={() => setActiveCorpus(c.id)}
            >
              <div className="item-name">{c.name}</div>
              <div className="item-meta">
                {c.language} · {c.stats?.document_count ?? 0} docs · {(c.stats?.token_count ?? 0).toLocaleString()} tokens
              </div>
              <div className="item-actions" onClick={(e) => e.stopPropagation()}>
                <CleanCorpusButton cid={c.id} language={c.language} />
              </div>
              {c.id === activeCorpusId && c.pipeline_recipe && (
                <PipelineRecipe recipe={c.pipeline_recipe} />
              )}
            </li>
          ))}
        </ul>
      </section>

      {/* Documents column */}
      <section className="panel">
        <header className="panel-header">
          <h2>Documents {activeCorpusId && `· ${corpora.data?.find((c) => c.id === activeCorpusId)?.name}`}</h2>
        </header>
        {!activeCorpusId && <div className="empty">Select a corpus to see its documents.</div>}
        {activeCorpusId && <DocumentUploader cid={activeCorpusId} />}
        {activeCorpusId && <DocumentList cid={activeCorpusId} />}
      </section>
    </div>
  );
}


function PipelineRecipe({ recipe }: { recipe: Record<string, unknown> }) {
  return (
    <details className="recipe">
      <summary>Pipeline recipe (§8.1)</summary>
      <dl>
        <dt>Backend</dt><dd>{String(recipe.backend ?? "—")}</dd>
        <dt>Model</dt><dd>{String(recipe.model_name ?? "—")}</dd>
        <dt>Model version</dt><dd>{String(recipe.model_version ?? "—")}</dd>
        <dt>spaCy version</dt><dd>{String(recipe.spacy_version ?? "—")}</dd>
        <dt>Language</dt><dd>{String(recipe.language ?? "—")}</dd>
      </dl>
    </details>
  );
}


function DocumentUploader({ cid }: { cid: string }) {
  const qc = useQueryClient();
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const upload = useMutation({
    mutationFn: (files: File[]) => api.uploadDocuments(cid, files),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["documents", cid] });
      qc.invalidateQueries({ queryKey: ["corpora"] });
    },
  });

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) upload.mutate(files);
  };

  const onFilePicker = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (files.length > 0) upload.mutate(files);
    // Reset the input so the same file can be selected again
    e.target.value = "";
  };

  const openFilePicker = () => {
    fileInputRef.current?.click();
  };

  return (
    <div
      className={clsx("dropzone", { dragging, busy: upload.isPending })}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
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
        onChange={onFilePicker}
        style={{ position: "absolute", width: 0, height: 0, opacity: 0, pointerEvents: "none" }}
        aria-hidden="true"
      />
      <div className="dropzone-icon">{"\u2191"}</div>
      <div className="dropzone-label">
        {upload.isPending
          ? "Uploading & tagging…"
          : dragging
            ? "Drop files here"
            : "Drop files here or click to upload"}
      </div>
      <div className="dropzone-formats">
        .txt · .md · .docx · .pdf · .html · .xml · .csv
      </div>
      {upload.isError && <div className="error">{String(upload.error)}</div>}
      {upload.data && (
        <div className="success">Ingested {upload.data.length} document(s).</div>
      )}
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
    <ul className="item-list">
      {docs.data?.map((d) => (
        <li key={d.id} className="item">
          <div className="item-name">{d.filename}</div>
          <div className="item-meta">
            {d.format} · {d.detected_language ?? "?"} · {(d.raw_size_bytes / 1024).toFixed(1)} KB
          </div>
        </li>
      ))}
      {docs.data?.length === 0 && <li className="empty">No documents yet.</li>}
    </ul>
  );
}


function NewProjectDialog({ onCreate }: { onCreate: (name: string, language: string) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [language, setLanguage] = useState("en");
  return (
    <>
      <button className="btn-small" onClick={() => setOpen(true)}>+ New</button>
      {open && (
        <div className="modal-backdrop" onClick={() => setOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>New project</h3>
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
            <div className="modal-actions">
              <button onClick={() => setOpen(false)}>Cancel</button>
              <button className="primary" disabled={!name} onClick={() => { onCreate(name, language); setOpen(false); setName(""); }}>Create</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}


function NewCorpusDialog({ onCreate }: { onCreate: (name: string, language: string) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [language, setLanguage] = useState("en");
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
            <div className="modal-actions">
              <button onClick={() => setOpen(false)}>Cancel</button>
              <button className="primary" disabled={!name} onClick={() => { onCreate(name, language); setOpen(false); setName(""); }}>Create</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}


function CleanCorpusButton({ cid, language }: { cid: string; language: string }) {
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

  const isArabic = language === "ar";
  const toggle = (key: keyof CleaningOptions, value: boolean | number) =>
    setOpts((o) => ({ ...o, [key]: value }));

  return (
    <>
      <button
        className="btn-small clean-btn"
        onClick={() => setOpen(true)}
        title="Clean this corpus (remove URLs, lowercase, strip punctuation, etc.)"
      >
        Clean
      </button>
      {open && (
        <div className="modal-backdrop" onClick={() => setOpen(false)}>
          <div className="modal clean-modal" onClick={(e) => e.stopPropagation()}>
            <h3>Clean Corpus</h3>
            <p className="clean-warning">
              Warning: This re-cleans every document in this corpus and re-runs the
              NLP pipeline. The old annotations are replaced. This cannot be undone.
            </p>

            <div className="clean-options">
              <div className="clean-group">
                <div className="clean-group-label">Structure</div>
                <label><input type="checkbox" checked={opts.collapse_whitespace ?? false} onChange={(e) => toggle("collapse_whitespace", e.target.checked)} /> Collapse whitespace</label>
                <label><input type="checkbox" checked={opts.strip_leading_trailing ?? false} onChange={(e) => toggle("strip_leading_trailing", e.target.checked)} /> Strip leading/trailing whitespace</label>
                <label><input type="checkbox" checked={opts.remove_empty_lines ?? false} onChange={(e) => toggle("remove_empty_lines", e.target.checked)} /> Remove empty lines</label>
                <label><input type="checkbox" checked={opts.remove_urls ?? false} onChange={(e) => toggle("remove_urls", e.target.checked)} /> Remove URLs</label>
                <label><input type="checkbox" checked={opts.remove_email_addresses ?? false} onChange={(e) => toggle("remove_email_addresses", e.target.checked)} /> Remove email addresses</label>
                <label><input type="checkbox" checked={opts.remove_html_entities ?? false} onChange={(e) => toggle("remove_html_entities", e.target.checked)} /> Remove HTML entities</label>
              </div>

              <div className="clean-group">
                <div className="clean-group-label">Case &amp; Punctuation</div>
                <label><input type="checkbox" checked={opts.lowercase ?? false} onChange={(e) => toggle("lowercase", e.target.checked)} /> Lowercase all text</label>
                <label><input type="checkbox" checked={opts.remove_punctuation ?? false} onChange={(e) => toggle("remove_punctuation", e.target.checked)} /> Remove punctuation</label>
                <label><input type="checkbox" checked={opts.remove_numbers ?? false} onChange={(e) => toggle("remove_numbers", e.target.checked)} /> Remove numbers</label>
                <label><input type="checkbox" checked={opts.remove_extra_symbols ?? false} onChange={(e) => toggle("remove_extra_symbols", e.target.checked)} /> Remove emoji &amp; symbols</label>
              </div>

              <div className="clean-group">
                <div className="clean-group-label">Linguistic</div>
                <label><input type="checkbox" checked={opts.remove_stopwords ?? false} onChange={(e) => toggle("remove_stopwords", e.target.checked)} /> Remove stopwords ({isArabic ? "Arabic" : "English"})</label>
                <label>
                  Min token length:
                  <input
                    type="number"
                    min={0}
                    max={20}
                    value={opts.min_token_length ?? 0}
                    onChange={(e) => toggle("min_token_length", parseInt(e.target.value, 10) || 0)}
                    style={{ inlineSize: "60px", marginInlineStart: "8px" }}
                  />
                  <span className="hint-inline">(0 = no filter)</span>
                </label>
              </div>

              {isArabic && (
                <div className="clean-group">
                  <div className="clean-group-label">Arabic-specific</div>
                  <label><input type="checkbox" checked={opts.normalize_arabic ?? false} onChange={(e) => toggle("normalize_arabic", e.target.checked)} /> Normalize alef variants</label>
                  <label><input type="checkbox" checked={opts.strip_arabic_diacritics ?? false} onChange={(e) => toggle("strip_arabic_diacritics", e.target.checked)} /> Strip diacritics (harakat)</label>
                  <label><input type="checkbox" checked={opts.remove_arabic_tatweel ?? false} onChange={(e) => toggle("remove_arabic_tatweel", e.target.checked)} /> Remove tatweel/kashida</label>
                </div>
              )}
            </div>

            <div className="modal-actions">
              <button onClick={() => setOpen(false)} disabled={clean.isPending}>Cancel</button>
              <button
                className="primary danger"
                disabled={clean.isPending}
                onClick={() => clean.mutate()}
              >
                {clean.isPending ? "Cleaning..." : "Clean Corpus"}
              </button>
            </div>
            {clean.isError && (
              <div className="error">Error: {String(clean.error)}</div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
