/**
 * CorpusManager — project list, corpus list, document upload (drag-drop),
 * pipeline-recipe display (§8.1, §8.2).
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import { api } from "@/lib/api";
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
  };

  return (
    <div
      className={clsx("dropzone", { dragging, busy: upload.isPending })}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      <input
        type="file"
        multiple
        accept=".txt,.md,.docx,.pdf,.html,.htm,.xml,.csv"
        onChange={onFilePicker}
        style={{ display: "none" }}
        id="file-input"
      />
      <label htmlFor="file-input" className="dropzone-label">
        {upload.isPending
          ? "Uploading & tagging…"
          : dragging
            ? "Drop files here"
            : "Drop files here or click to choose (.txt, .md, .docx, .pdf, .html, .xml, .csv)"}
      </label>
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
