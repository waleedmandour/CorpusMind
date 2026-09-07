/**
 * VisionCorporaView — v1.1.0 "Your Vision Corpora".
 *
 * THE merged Lens tab: the former "Your Corpora" (corpus/set management,
 * provenance, IPTC metadata, OCR corpus tools — LensCorporaView) and
 * "Your Vision" (per-image vision analysis — VisionView) are now ONE
 * workspace, because in a visual corpus the images ARE the corpus and
 * the management/analysis split was a split-brain UX.
 *
 * Layout (consistent with the app's corpus workbenches):
 *   corpus-selection-grid
 *     ├─ CorpusListPanel (left: corpora of the project)
 *     └─ SetWorkspace (right)
 *          ├─ set management: picker, create, provenance notes, export, delete
 *          └─ four tabs (the researcher workflow: build → annotate → measure → interpret)
 *               1. Overview  — set-level corpus statistics + coverage
 *               2. Corpus    — upload, grid, per-image metadata + tags +
 *                              the five-dimension visual annotation editor
 *               3. Measures  — the corpus-linguistics battery over the
 *                              annotations (frequency, diversity, n-grams,
 *                              co-occurrence association, keyness,
 *                              dispersion, visual KWIC) + the OCR text tools
 *               4. Vision Analysis — VLM describe, visual grammar,
 *                              discourse lenses, alignment, facial (opt-in),
 *                              batch runner/view
 *
 * The five annotation dimensions (Visual Morphology, Attentional Framing,
 * Filmic Shot Scale, Path Structure and Transitions, Multimodal
 * Integration) are schema-driven: labels and categories come from the
 * engine's annotation-schema endpoint (single source of truth, EN + AR).
 */
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import {
  api,
  exportWithFeedback,
  type AnnotationDimension,
  type ImageRecord,
  type ImageSet,
  type ImageSetStats,
  type OcrFrequencyResult,
  type OcrKeynessResult,
  type OcrSearchResult,
  type UploadFailure,
  type VisualProfileResult,
  type VisualStatsResult,
} from "@/lib/api";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ExportButton } from "@/components/ExportButton";
import { useApp } from "@/store/app";
import { useUI } from "@/store/ui";
import { t, type TranslationKey } from "@/lib/i18n";
import { ProjectSelector } from "@/views/CorpusSelectionView";
import {
  AlignmentPanel,
  AnalysisDrawer,
  BatchRunnerPanel,
  BatchViewPanel,
  DiscourseLensesPanel,
  FacialAnalysisPanel,
  VisionGuidance,
} from "@/views/VisionView";

const IMAGE_ACCEPT = "image/png,image/jpeg,image/webp,image/gif,image/tiff,image/bmp";
const PAGE_SIZE = 24;

function formatBytes(n: number): string {
  if (!n) return "0 B";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

/** Localize a template containing {n}/{shown}/{total} placeholders. */
function tf(lang: "en" | "ar", key: TranslationKey, vars: Record<string, string | number>): string {
  let s = t(lang, key);
  for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, String(v));
  return s;
}

// The OCR language choices surfaced at upload. "auto" = engine resolves
// from the corpus language (the default — Arabic corpora OCR with ara+eng).
const OCR_LANG_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "", label: "" }, // placeholder filled with t(vc_ocr_lang_auto)
  { value: "eng", label: "English (eng)" },
  { value: "ara+eng", label: "العربية + English (ara+eng)" },
  { value: "ara", label: "العربية (ara)" },
  { value: "fra", label: "Français (fra)" },
  { value: "deu", label: "Deutsch (deu)" },
  { value: "spa", label: "Español (spa)" },
];

type WorkspaceTab = "overview" | "corpus" | "measures" | "vision";

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------

export function VisionCorporaView() {
  const lang = useUI((s) => s.lang);

  return (
    <div className="corpus-selection-view">
      <div className="corpus-selection-header">
        <h1>{t(lang, "nav_vision_corpora")}</h1>
        <p className="corpus-selection-subtitle">{t(lang, "vc_subtitle")}</p>
      </div>

      <ProjectSelector />

      <div className="corpus-selection-grid">
        <CorpusListPanel />
        <SetWorkspace />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Corpus list (left panel — corpora of the active project)
// ---------------------------------------------------------------------------

function CorpusListPanel() {
  const activeCorpusId = useApp((s) => s.activeCorpusId);
  const setActiveCorpus = useApp((s) => s.setActiveCorpus);
  const activeProjectId = useApp((s) => s.activeProjectId);
  const lang = useUI((s) => s.lang);

  const corpora = useQuery({
    queryKey: ["corpora", activeProjectId],
    queryFn: () => (activeProjectId ? api.listCorpora(activeProjectId) : Promise.resolve([])),
    enabled: !!activeProjectId,
  });

  // Issue #8: corpora that already carry image sets surface first (stable
  // sort — the API's created_at-desc order is kept within each group), and
  // each row carries an image-set count badge so text-only corpora no
  // longer read the same as image-bearing ones.
  const sorted = useMemo(
    () =>
      [...(corpora.data ?? [])].sort(
        (a, b) => (b.image_set_count ?? 0) - (a.image_set_count ?? 0),
      ),
    [corpora.data],
  );

  return (
    <section className="corpus-panel">
      <header className="corpus-panel-header">
        <h2>{t(lang, "nav_file")}</h2>
      </header>

      {!activeProjectId && (
        <div className="corpus-empty">{t(lang, "lens_select_corpus_first")}</div>
      )}

      <ul className="corpus-list">
        {sorted.map((c) => (
          <li
            key={c.id}
            className={clsx("corpus-list-item", { active: c.id === activeCorpusId })}
            onClick={() => setActiveCorpus(c.id)}
          >
            <div className="corpus-item-name">{c.name}</div>
            <div className="corpus-item-meta">
              <span className="corpus-meta-lang">{c.language.toUpperCase()}</span>
              {c.genre && c.genre !== "mixed" && <span className="corpus-item-genre">{c.genre}</span>}
              {c.image_set_count > 0 && (
                <span
                  className="corpus-item-sets"
                  title={t(lang, "vc_sets_badge")}
                  aria-label={`${t(lang, "vc_sets_badge")}: ${c.image_set_count}`}
                >
                  <svg viewBox="0 0 16 16" width="10" height="10" aria-hidden="true" focusable="false">
                    <rect x="1.5" y="3" width="13" height="10" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
                    <circle cx="5.5" cy="6.5" r="1.3" fill="currentColor" />
                    <path d="M2.5 12.2 L6 8.7 L8.5 11.2 L11 8.2 L13.5 10.7" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round" />
                  </svg>
                  {c.image_set_count}
                </span>
              )}
            </div>
            {c.id === activeCorpusId && (
              <span className="corpus-active-badge">Active</span>
            )}
          </li>
        ))}
        {corpora.data?.length === 0 && activeProjectId && (
          <li className="corpus-empty">{t(lang, "lens_select_corpus_first")}</li>
        )}
      </ul>
    </section>
  );
}

// ---------------------------------------------------------------------------
// SetWorkspace — set management + the four-tab workbench
// ---------------------------------------------------------------------------

function SetWorkspace() {
  const lang = useUI((s) => s.lang);
  const qc = useQueryClient();
  const cid = useApp((s) => s.activeCorpusId);
  const [selectedSetId, setSelectedSetId] = useState<string | null>(null);
  const [tab, setTab] = useState<WorkspaceTab>("overview");
  const [selectedImageId, setSelectedImageId] = useState<string | null>(null);
  const [showNewSet, setShowNewSet] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [editingNotes, setEditingNotes] = useState(false);
  const [notesDraft, setNotesDraft] = useState("");
  const [confirm, setConfirm] = useState<{ msg: string; onConfirm: () => void } | null>(null);
  const [actionMsg, setActionMsg] = useState("");

  const sets = useQuery({
    queryKey: ["image-sets", cid],
    queryFn: () => api.listImageSets(cid!),
    enabled: !!cid,
  });

  // Auto-select the first set once so the workspace is never mysteriously
  // empty (render-phase state adjustment — the official React pattern).
  if (sets.data && sets.data.length > 0 && !selectedSetId) {
    setSelectedSetId(sets.data[0].id);
  }

  const activeSet: ImageSet | undefined = sets.data?.find((s) => s.id === selectedSetId);

  const createSet = useMutation({
    mutationFn: () => api.createImageSet(cid!, newName.trim(), newDesc.trim()),
    onSuccess: (created) => {
      setNewName("");
      setNewDesc("");
      setShowNewSet(false);
      setSelectedSetId(created.id);
      setActionMsg(t(lang, "lens_created"));
      qc.invalidateQueries({ queryKey: ["image-sets", cid] });
    },
    onError: (e: Error) => setActionMsg(`${t(lang, "lens_create_failed")}: ${e.message}`),
  });

  const updateSet = useMutation({
    mutationFn: () => api.updateImageSet(selectedSetId!, { description: notesDraft }),
    onSuccess: () => {
      setEditingNotes(false);
      setActionMsg(t(lang, "lens_meta_saved"));
      qc.invalidateQueries({ queryKey: ["image-sets", cid] });
    },
    onError: (e: Error) => setActionMsg(`${t(lang, "lens_save_failed")}: ${e.message}`),
  });

  const deleteSet = useMutation({
    mutationFn: (sid: string) => api.deleteImageSet(sid),
    onSuccess: () => {
      setSelectedSetId(null);
      setSelectedImageId(null);
      setActionMsg(t(lang, "lens_deleted"));
      qc.invalidateQueries({ queryKey: ["image-sets", cid] });
    },
    onError: (e: Error) => setActionMsg(`${t(lang, "lens_delete_failed")}: ${e.message}`),
  });

  if (!cid) {
    return (
      <section className="corpus-panel">
        <div className="corpus-empty">{t(lang, "lens_select_corpus_first")}</div>
      </section>
    );
  }

  const TABS: Array<{ id: WorkspaceTab; labelKey: TranslationKey }> = [
    { id: "overview", labelKey: "vc_tab_overview" },
    { id: "corpus", labelKey: "vc_tab_corpus" },
    { id: "measures", labelKey: "vc_tab_measures" },
    { id: "vision", labelKey: "vc_tab_vision" },
  ];

  return (
    <section className="corpus-panel">
      <header className="corpus-panel-header">
        <h2>{t(lang, "lens_image_sets")}</h2>
        <button className="btn-small" onClick={() => setShowNewSet((v) => !v)}>
          {showNewSet ? t(lang, "lens_cancel") : t(lang, "lens_new_set")}
        </button>
      </header>

      {showNewSet && (
        <div className="vision-new-set-form" style={{ flexDirection: "column", alignItems: "stretch", gap: "var(--space-2)" }}>
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder={t(lang, "lens_set_name_ph")}
            autoFocus
          />
          <textarea
            value={newDesc}
            onChange={(e) => setNewDesc(e.target.value)}
            placeholder={t(lang, "lens_set_desc_ph")}
            rows={2}
          />
          <button
            className="btn-primary"
            onClick={() => createSet.mutate()}
            disabled={!newName.trim() || createSet.isPending}
          >
            {createSet.isPending ? "…" : t(lang, "lens_create")}
          </button>
        </div>
      )}

      {sets.isLoading && <div className="hint">…</div>}
      {sets.error && (
        <div className="uploader-status error">{(sets.error as Error).message}</div>
      )}
      {sets.data && sets.data.length === 0 && !showNewSet && (
        <div className="corpus-empty">{t(lang, "lens_no_sets")}</div>
      )}

      {sets.data && sets.data.length > 0 && (
        <label className="vision-set-picker" style={{ marginBlock: "var(--space-2)" }}>
          <span className="vision-set-picker-label">{t(lang, "lens_image_sets")}</span>
          <select
            value={selectedSetId ?? ""}
            onChange={(e) => {
              setSelectedSetId(e.target.value || null);
              setSelectedImageId(null);
            }}
          >
            <option value="">{t(lang, "lens_filter_all")}</option>
            {sets.data.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.image_count})
              </option>
            ))}
          </select>
        </label>
      )}

      {activeSet && (
        <>
          {/* Provenance / sampling notes (corpus-construction documentation) */}
          {editingNotes ? (
            <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)", marginBlockEnd: "var(--space-2)" }}>
              <textarea
                value={notesDraft}
                onChange={(e) => setNotesDraft(e.target.value)}
                placeholder={t(lang, "lens_set_desc_ph")}
                rows={2}
              />
              <div style={{ display: "flex", gap: "var(--space-2)" }}>
                <button className="btn-small btn-primary" onClick={() => updateSet.mutate()} disabled={updateSet.isPending}>
                  {t(lang, "lens_save_notes")}
                </button>
                <button className="btn-small" onClick={() => setEditingNotes(false)}>{t(lang, "lens_cancel")}</button>
              </div>
            </div>
          ) : (
            <p className="hint" style={{ marginBlockEnd: "var(--space-2)" }}>
              {activeSet.description || t(lang, "lens_set_desc_ph")}{" "}
              <button
                className="btn-small"
                onClick={() => { setNotesDraft(activeSet.description ?? ""); setEditingNotes(true); }}
              >
                {t(lang, "lens_edit_notes")}
              </button>
            </p>
          )}

          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", marginBlockEnd: "var(--space-3)" }}>
            <ExportButton label={t(lang, "lens_export_ocr")} formats={["txt", "json"]}
              onExport={(fmt) => {
                const slug = activeSet.name.replace(/[^\w-]+/g, "-").slice(0, 40) || "imageset";
                void exportWithFeedback(
                  () => api.exportOcrCorpus(activeSet.id, fmt as "txt" | "json"),
                  `ocr-corpus-${slug}.${fmt}`,
                  (msg) => setActionMsg(msg),
                );
              }} />
            <ExportButton label="Export" formats={["xlsx", "csv", "tsv", "txt", "json"]}
              onExport={(fmt) => {
                const slug = activeSet.name.replace(/[^\w-]+/g, "-").slice(0, 40) || "imageset";
                void exportWithFeedback(
                  () => api.exportImageSet(activeSet.id, fmt as "xlsx"),
                  `image-set-${slug}.${fmt}`,
                  (msg) => setActionMsg(msg),
                );
              }} />
            <button
              className="btn-danger"
              onClick={() => setConfirm({
                msg: t(lang, "lens_delete_set_confirm"),
                onConfirm: () => deleteSet.mutate(activeSet.id),
              })}
            >
              {t(lang, "lens_delete_set")}
            </button>
          </div>

          {/* The merged workbench: build → annotate → measure → interpret */}
          <div className="tabs" role="tablist" aria-label="Workspace tabs">
            {TABS.map((tb) => (
              <button
                key={tb.id}
                role="tab"
                aria-selected={tab === tb.id}
                className={clsx("tab", { active: tab === tb.id })}
                onClick={() => setTab(tb.id)}
              >
                {t(lang, tb.labelKey)}
              </button>
            ))}
          </div>

          <div className="panel-content" style={{ marginBlockStart: "var(--space-2)" }}>
            {tab === "overview" && <SetStatsPanel setId={activeSet.id} />}
            {tab === "corpus" && (
              <CorpusTab
                setId={activeSet.id}
                selectedImageId={selectedImageId}
                onSelectImage={setSelectedImageId}
              />
            )}
            {tab === "measures" && <MeasuresTab setId={activeSet.id} allSets={sets.data ?? []} />}
            {tab === "vision" && (
              <VisionTab setId={activeSet.id} selectedImageId={selectedImageId} />
            )}
          </div>
        </>
      )}

      {actionMsg && <div className="uploader-status info" style={{ marginBlockStart: "var(--space-2)" }}>{actionMsg}</div>}

      <ConfirmDialog state={confirm} onClose={() => setConfirm(null)} />
    </section>
  );
}

// ---------------------------------------------------------------------------
// SetStatsPanel — set-level corpus statistics + coverage (Overview tab)
// ---------------------------------------------------------------------------

function SetStatsPanel({ setId }: { setId: string }) {
  const lang = useUI((s) => s.lang);
  const stats = useQuery({
    queryKey: ["image-set-stats", setId],
    queryFn: () => api.imageSetStats(setId),
    refetchInterval: 15_000,
  });
  // v1.1.0: annotation coverage rides alongside the ingest coverage.
  const visualStats = useQuery({
    queryKey: ["visual-stats", setId],
    queryFn: () => api.visualStats(setId),
  });

  if (!stats.data) return null;
  const s: ImageSetStats = stats.data;
  const cov = s.coverage;
  const res = s.resolution;
  const anno = visualStats.data;

  return (
    <div className="corpus-stats-dashboard">
      <h3 className="dashboard-title">{t(lang, "lens_set_stats")}</h3>
      <div className="stats-grid">
        <div className="stat-tile">
          <span className="stat-value">{s.image_count}</span>
          <span className="stat-label">{t(lang, "lens_stat_images")}</span>
        </div>
        <div className="stat-tile">
          <span className="stat-value">{formatBytes(s.total_bytes)}</span>
          <span className="stat-label">{t(lang, "lens_stat_size")}</span>
        </div>
        <div className="stat-tile">
          <span className="stat-value">{s.ocr_word_total.toLocaleString()}</span>
          <span className="stat-label">{t(lang, "lens_stat_ocr_words")}</span>
        </div>
        <div className="stat-tile">
          <span className="stat-value">{Object.entries(s.formats).map(([f, c]) => `${f}:${c}`).join(" ") || "—"}</span>
          <span className="stat-label">{t(lang, "lens_stat_formats")}</span>
        </div>
        <div className="stat-tile">
          <span className="stat-value">{Object.entries(s.orientations).map(([o, c]) => `${o}:${c}`).join(" ") || "—"}</span>
          <span className="stat-label">{t(lang, "lens_stat_orientation")}</span>
        </div>
        <div className="stat-tile">
          <span className="stat-value">{res.max_width ? `${res.min_width}–${res.max_width} × ${res.min_height}–${res.max_height}` : "—"}</span>
          <span className="stat-label">{t(lang, "lens_stat_resolution")}</span>
        </div>
        {(s.date_min || s.date_max) && (
          <div className="stat-tile">
            <span className="stat-value" style={{ fontSize: "0.85em" }}>{s.date_min || "…"} → {s.date_max || "…"}</span>
            <span className="stat-label">{t(lang, "lens_stat_dates")}</span>
          </div>
        )}
        {anno && (
          <div className="stat-tile">
            <span className="stat-value">{tf(lang, "vc_annotated_images", { n: anno.images_annotated, total: anno.image_count })}</span>
            <span className="stat-label">{t(lang, "vc_annotation_h")}</span>
          </div>
        )}
      </div>

      {/* Coverage bars — documentation completeness at a glance */}
      <div className="hint" style={{ marginBlock: "var(--space-2)" }}>
        <div>
          {t(lang, "lens_coverage")}: {t(lang, "lens_cov_ocr")} {cov.with_ocr}/{s.image_count} · {t(lang, "lens_cov_caption")} {cov.with_caption}/{s.image_count} · {t(lang, "lens_cov_vlm")} {cov.with_vlm}/{s.image_count} · {t(lang, "lens_cov_meta")} {cov.with_user_meta}/{s.image_count}
          {anno ? ` · ${t(lang, "vc_annotation_h")} ${anno.images_annotated}/${anno.image_count}` : ""}
        </div>
      </div>

      {(Object.keys(s.genres).length > 0 || Object.keys(s.sources).length > 0) && (
        <div className="hint" style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-2)" }}>
          {Object.entries(s.genres).map(([g, c]) => (
            <span key={g} className="corpus-item-genre">{g} ({c})</span>
          ))}
          {Object.entries(s.sources).slice(0, 6).map(([src, c]) => (
            <span key={src} className="corpus-item-genre">{src} ({c})</span>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// CorpusTab — upload, grid, bulk tagging (build + annotate)
// ---------------------------------------------------------------------------

function CorpusTab({ setId, selectedImageId, onSelectImage }: {
  setId: string;
  selectedImageId: string | null;
  onSelectImage: (id: string | null) => void;
}) {
  const lang = useUI((s) => s.lang);
  const qc = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [caption, setCaption] = useState("");
  const [ocrLang, setOcrLang] = useState("");
  const [isDragOver, setIsDragOver] = useState(false);
  const [showBulk, setShowBulk] = useState(false);
  const [bulk, setBulk] = useState({ source: "", date: "", license: "", genre: "", language: "", tags: "" });
  const [confirm, setConfirm] = useState<{ msg: string; onConfirm: () => void } | null>(null);
  const [statusMsg, setStatusMsg] = useState("");
  const [uploadFailures, setUploadFailures] = useState<UploadFailure[]>([]);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["vc-images", setId] });
    qc.invalidateQueries({ queryKey: ["image-set-stats", setId] });
    qc.invalidateQueries({ queryKey: ["image-sets"] });
    qc.invalidateQueries({ queryKey: ["visual-stats", setId] });
  };

  const images = useQuery({
    queryKey: ["vc-images", setId, limit],
    queryFn: () => api.listImagesPaged(setId, limit, 0),
  });

  const items = useMemo(() => images.data?.items ?? [], [images.data]);

  const upload = useMutation({
    mutationFn: () => api.uploadImages(setId, pendingFiles, caption || undefined, ocrLang || undefined),
    onSuccess: (res) => {
      setStatusMsg(tf(lang, "lens_upload_done", { n: res.uploaded.length }));
      // v1.1.0: per-file isolation — surface what failed, keep what succeeded.
      setUploadFailures(res.failed);
      setPendingFiles([]);
      setCaption("");
      invalidate();
      setTimeout(() => setStatusMsg(""), 6000);
    },
    onError: (e: Error) => setStatusMsg(`${t(lang, "lens_upload_failed")}: ${e.message}`),
  });

  const bulkTag = useMutation({
    mutationFn: async () => {
      const meta = Object.fromEntries(
        Object.entries({ source: bulk.source, date: bulk.date, license: bulk.license, genre: bulk.genre, language: bulk.language })
          .filter(([, v]) => v.trim()),
      ) as Record<string, string>;
      const tagList = bulk.tags.split(",").map((s) => s.trim()).filter(Boolean);
      if (Object.keys(meta).length > 0) {
        await api.bulkImageMeta(setId, meta);
      }
      if (tagList.length > 0) {
        await api.bulkAnnotations(setId, { tags: tagList, tag_mode: "add" });
      }
      return tagList.length + Object.keys(meta).length;
    },
    onSuccess: (applied) => {
      setStatusMsg(tf(lang, "lens_bulk_done", { n: applied }));
      setShowBulk(false);
      setBulk({ source: "", date: "", license: "", genre: "", language: "", tags: "" });
      invalidate();
      setTimeout(() => setStatusMsg(""), 6000);
    },
    onError: (e: Error) => setStatusMsg(`${t(lang, "lens_save_failed")}: ${e.message}`),
  });

  const deleteImage = useMutation({
    mutationFn: (imgId: string) => api.deleteImage(imgId),
    onSuccess: () => {
      onSelectImage(null);
      invalidate();
    },
    onError: (e: Error) => setStatusMsg(`${t(lang, "lens_delete_failed")}: ${e.message}`),
  });

  const onPickFiles = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const arr = Array.from(files).filter((f) => f.type.startsWith("image/"));
    setPendingFiles((prev) => [...prev, ...arr]);
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInputRef.current?.click();
    }
  };

  const total = images.data?.total ?? 0;

  return (
    <div className="vision-workspace">
      {/* Upload dropzone — limits surfaced per the engine's hard caps */}
      <div
        className={clsx("dropzone", { "drag-over": isDragOver, busy: upload.isPending })}
        onClick={() => fileInputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragOver(false);
          onPickFiles(e.dataTransfer.files);
        }}
        role="button"
        tabIndex={0}
        onKeyDown={handleKeyDown}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={IMAGE_ACCEPT}
          onChange={(e) => {
            onPickFiles(e.target.files);
            e.target.value = "";
          }}
          style={{ position: "absolute", width: 0, height: 0, opacity: 0, pointerEvents: "none" }}
          aria-hidden="true"
        />
        <div className="dropzone-icon">{"\u2191"}</div>
        <div className="dropzone-label">{t(lang, "lens_images")}</div>
        <div className="dropzone-formats">{t(lang, "lens_upload_hint")}</div>
      </div>

      {pendingFiles.length > 0 && (
        <div className="vision-pending-upload">
          <div className="vision-pending-header">
            <strong>{tf(lang, "lens_uploading", { n: pendingFiles.length })}</strong>
            <button className="btn-small" onClick={() => setPendingFiles([])}>{t(lang, "lens_cancel")}</button>
          </div>
          <ul className="vision-pending-list">
            {pendingFiles.slice(0, 8).map((f, i) => (
              <li key={i}>
                <span>{f.name}</span>
                <span className="vision-pending-size">{formatBytes(f.size)}</span>
              </li>
            ))}
            {pendingFiles.length > 8 && (
              <li className="vision-pending-more">{tf(lang, "vision_and_more", { n: pendingFiles.length - 8 })}</li>
            )}
          </ul>
          <label className="vision-caption-input">
            <span>{t(lang, "vision_caption_label")}</span>
            <input
              type="text"
              value={caption}
              onChange={(e) => setCaption(e.target.value)}
              placeholder={t(lang, "vision_caption_placeholder")}
            />
          </label>
          {/* v1.1.0: OCR language follows the corpus language by default —
              override here for mixed-language material. */}
          <label className="vision-caption-input">
            <span>{t(lang, "vc_ocr_lang_label")}</span>
            <select value={ocrLang} onChange={(e) => setOcrLang(e.target.value)}>
              <option value="">{t(lang, "vc_ocr_lang_auto")}</option>
              {OCR_LANG_OPTIONS.slice(1).map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
          <button
            className="btn-primary"
            onClick={() => upload.mutate()}
            disabled={upload.isPending}
          >
            {upload.isPending ? "…" : tf(lang, "lens_uploading", { n: pendingFiles.length })}
          </button>
        </div>
      )}

      {/* Per-file ingestion failures (v1.1.0 isolation contract) */}
      {uploadFailures.length > 0 && (
        <div className="uploader-status error" style={{ marginBlockEnd: "var(--space-2)" }}>
          <strong>{tf(lang, "vc_upload_failures", { n: uploadFailures.length })}</strong>
          <ul style={{ margin: "4px 0 0 1em" }}>
            {uploadFailures.map((f, i) => (
              <li key={i}><code>{f.filename}</code>: {f.error}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Grid toolbar: bulk tagging */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "var(--space-2)", marginBlock: "var(--space-2)", flexWrap: "wrap" }}>
        <h3 className="vision-section-heading" style={{ margin: 0 }}>{t(lang, "lens_images")}</h3>
        <div style={{ display: "flex", gap: "var(--space-2)" }}>
          {total > 0 && (
            <button className="btn-small" onClick={() => setShowBulk((v) => !v)}>{t(lang, "lens_tag_all")}</button>
          )}
        </div>
      </div>

      {showBulk && (
        <div style={{ marginBlockEnd: "var(--space-2)", padding: "var(--space-3)", background: "var(--bg-subtle)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", fontSize: "12px" }}>
          <strong>{t(lang, "lens_bulk_tag_title")}</strong>
          <p style={{ fontSize: "11px", color: "var(--text-muted)", margin: "4px 0 8px" }}>{t(lang, "lens_bulk_tag_hint")}</p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "var(--space-2)", marginBlockEnd: "var(--space-2)" }}>
            <input placeholder={t(lang, "lens_meta_source")} value={bulk.source} onChange={(e) => setBulk({ ...bulk, source: e.target.value })} />
            <input placeholder={t(lang, "lens_meta_date")} value={bulk.date} onChange={(e) => setBulk({ ...bulk, date: e.target.value })} />
            <input placeholder={t(lang, "lens_meta_license")} value={bulk.license} onChange={(e) => setBulk({ ...bulk, license: e.target.value })} />
            <input placeholder={t(lang, "lens_meta_genre")} value={bulk.genre} onChange={(e) => setBulk({ ...bulk, genre: e.target.value })} />
            <input placeholder={t(lang, "lens_meta_language")} value={bulk.language} onChange={(e) => setBulk({ ...bulk, language: e.target.value })} />
            <input placeholder={t(lang, "vc_tags_ph")} value={bulk.tags} onChange={(e) => setBulk({ ...bulk, tags: e.target.value })} />
          </div>
          <button className="btn-small btn-primary" onClick={() => bulkTag.mutate()} disabled={bulkTag.isPending}>
            {bulkTag.isPending ? "…" : t(lang, "lens_tag_all")}
          </button>
        </div>
      )}

      {statusMsg && <div className="uploader-status info" style={{ marginBlockEnd: "var(--space-2)" }}>{statusMsg}</div>}

      {images.isLoading && <div className="hint">…</div>}
      {images.error && <div className="uploader-status error">{(images.error as Error).message}</div>}
      {items.length === 0 && !images.isLoading && (
        <div className="hint">{t(lang, "lens_no_sets")}</div>
      )}

      {items.length > 0 && (
        <div className="vision-grid" role="list">
          {items.map((img) => (
            <ImageCard
              key={img.id}
              image={img}
              selected={img.id === selectedImageId}
              onSelect={() => onSelectImage(img.id === selectedImageId ? null : img.id)}
            />
          ))}
        </div>
      )}

      {images.data && (
        <div className="hint" style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", marginBlock: "var(--space-2)" }}>
          <span>{tf(lang, "lens_showing_of", { shown: items.length, total })}</span>
          {items.length < total && (
            <button className="btn-small" onClick={() => setLimit((l) => l + PAGE_SIZE)}>
              {t(lang, "lens_load_more")}
            </button>
          )}
        </div>
      )}

      {selectedImageId && (
        <SelectedImagePanel
          imgId={selectedImageId}
          onSaved={invalidate}
          onDeleted={() => setConfirm({
            msg: t(lang, "lens_delete_image_confirm"),
            onConfirm: () => deleteImage.mutate(selectedImageId),
          })}
        />
      )}

      <ConfirmDialog state={confirm} onClose={() => setConfirm(null)} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// ImageCard — grid thumbnail with tag/annotation badges
// ---------------------------------------------------------------------------

function ImageCard({ image, selected, onSelect }: {
  image: ImageRecord;
  selected: boolean;
  onSelect: () => void;
}) {
  const lang = useUI((s) => s.lang);
  const thumbQuery = useQuery({
    queryKey: ["image-thumbnail", image.id],
    queryFn: () => api.fetchImageThumbnailUrl(image.id),
    staleTime: Infinity,
    retry: false,
  });

  const nTagged = image.meta?.tags?.length ?? 0;
  const nDims = Object.values(image.meta?.annotations ?? {}).filter(
    (b) => (b?.values?.length ?? 0) > 0,
  ).length;

  return (
    <button
      className={clsx("vision-grid-item", { selected })}
      onClick={onSelect}
      role="listitem"
      aria-pressed={selected}
      title={image.filename}
    >
      <div className="vision-grid-thumb" aria-hidden="true">
        {thumbQuery.data ? (
          <img src={thumbQuery.data} alt="" className="vision-grid-thumb-img"
               style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        ) : (
          <span className="vision-grid-thumb-icon">{"\u25A3"}</span>
        )}
      </div>
      <div className="vision-grid-meta">
        <div className="vision-grid-filename" title={image.filename}>{image.filename}</div>
        <div className="vision-grid-dims">
          {image.width}×{image.height} · {formatBytes(image.size_bytes)}
        </div>
        {(nTagged > 0 || nDims > 0) && (
          <div className="vision-grid-caption" title={t(lang, "vc_annotation_h")}>
            {nTagged > 0 && <span className="corpus-item-genre">{"\u25B8"} {nTagged}</span>}
            {" "}
            {nDims > 0 && <span className="corpus-item-genre">{"\u2B24"} {nDims}/5</span>}
          </div>
        )}
        {image.meta?.user?.genre && <div className="vision-grid-caption">{image.meta.user.genre}</div>}
        {image.caption && <div className="vision-grid-caption" title={image.caption}>{image.caption}</div>}
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// SelectedImagePanel — metadata + tags + the five-dimension annotation editor
// (the per-image drawer of the Corpus tab: document, tag, annotate, re-analyse)
// ---------------------------------------------------------------------------

type DimensionDraft = { values: string[]; note: string };

function SelectedImagePanel({ imgId, onSaved, onDeleted }: {
  imgId: string;
  onSaved: () => void;
  onDeleted: () => void;
}) {
  const lang = useUI((s) => s.lang);
  const qc = useQueryClient();

  // The images list already carries meta — read the record from the list
  // cache (the engine exposes no GET /images/{id}).
  const metaQuery = useQuery({
    queryKey: ["vc-image", imgId],
    queryFn: async (): Promise<ImageRecord> => {
      const cached = qc.getQueriesData({ queryKey: ["vc-images"] });
      for (const [, data] of cached) {
        const d = data as { items: ImageRecord[] } | undefined;
        const hit = d?.items?.find((i) => i.id === imgId);
        if (hit) return hit;
      }
      throw new Error("image not in cache");
    },
    staleTime: 0,
  });

  const rec = metaQuery.data;
  const [form, setForm] = useState<Record<string, string>>({});
  const [caption, setCaption] = useState<string | null>(null);
  const [tags, setTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");
  const [draft, setDraft] = useState<Record<string, DimensionDraft>>({});
  const [msg, setMsg] = useState("");
  const [showExif, setShowExif] = useState(false);

  // Schema-driven dimensions (EN+AR labels straight from the engine).
  const schemaQuery = useQuery({
    queryKey: ["annotation-schema", rec?.image_set_id],
    queryFn: () => api.getAnnotationSchema(rec!.image_set_id),
    enabled: !!rec,
  });
  const dimensions: AnnotationDimension[] = schemaQuery.data?.dimensions ?? [];

  useEffect(() => {
    if (rec) {
      setForm({
        source: rec.meta?.user?.source ?? "",
        date: rec.meta?.user?.date ?? "",
        license: rec.meta?.user?.license ?? "",
        genre: rec.meta?.user?.genre ?? "",
        language: rec.meta?.user?.language ?? "",
        notes: rec.meta?.user?.notes ?? "",
      });
      setCaption(rec.caption ?? "");
      setTags(rec.meta?.tags ?? []);
      const d: Record<string, DimensionDraft> = {};
      for (const dim of dimensions) {
        const block = rec.meta?.annotations?.[dim.id];
        d[dim.id] = { values: block?.values ?? [], note: block?.note ?? "" };
      }
      setDraft(d);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rec?.id, schemaQuery.data]);

  const saveMeta = useMutation({
    mutationFn: () => api.updateImageMeta(imgId, {
      caption: caption ?? undefined,
      meta: Object.fromEntries(Object.entries(form).filter(([, v]) => v.trim())),
    }),
    onSuccess: () => {
      setMsg(t(lang, "lens_meta_saved"));
      onSaved();
      setTimeout(() => setMsg(""), 4000);
    },
    onError: (e: Error) => setMsg(`${t(lang, "lens_save_failed")}: ${e.message}`),
  });

  const saveAnnotations = useMutation({
    mutationFn: () => api.saveImageAnnotations(imgId, {
      tags,
      dimensions: Object.fromEntries(
        Object.entries(draft).map(([dim, d]) => [dim, { values: d.values, note: d.note }]),
      ),
    }),
    onSuccess: () => {
      setMsg(t(lang, "vc_annotations_saved"));
      onSaved();
      setTimeout(() => setMsg(""), 4000);
    },
    onError: (e: Error) => setMsg(`${t(lang, "lens_save_failed")}: ${e.message}`),
  });

  const reanalyse = useMutation({
    mutationFn: () => api.reanalyseImage(imgId),
    onSuccess: () => {
      setMsg(t(lang, "vc_reanalysed"));
      qc.invalidateQueries({ queryKey: ["image-analysis", imgId] });
      qc.invalidateQueries({ queryKey: ["batch-analysis"] });
      setTimeout(() => setMsg(""), 5000);
    },
    onError: (e: Error) => setMsg(`${t(lang, "lens_save_failed")}: ${e.message}`),
  });

  const addTag = () => {
    const v = tagInput.trim();
    if (!v) return;
    if (!tags.some((t2) => t2.toLowerCase() === v.toLowerCase())) setTags([...tags, v]);
    setTagInput("");
  };

  const toggleCategory = (dimId: string, catId: string) => {
    setDraft((prev) => {
      const d = prev[dimId] ?? { values: [], note: "" };
      const values = d.values.includes(catId)
        ? d.values.filter((v) => v !== catId)
        : [...d.values, catId];
      return { ...prev, [dimId]: { ...d, values } };
    });
  };

  if (!rec) return null;

  const field = (key: TranslationKey, k: string) => (
    <label style={{ display: "flex", flexDirection: "column", gap: 2, fontSize: "12px" }}>
      <span style={{ color: "var(--text-muted)" }}>{t(lang, key)}</span>
      <input value={form[k] ?? ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
    </label>
  );

  return (
    <div className="vision-analysis-drawer">
      <h3 className="vision-section-heading">
        {t(lang, "lens_meta_h")}: <code>{rec.filename}</code>
      </h3>
      <div className="result-meta">
        {rec.width}×{rec.height} · {rec.format.toUpperCase()} · {formatBytes(rec.size_bytes)}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "var(--space-2)", marginBlock: "var(--space-3)" }}>
        {field("lens_meta_source", "source")}
        {field("lens_meta_date", "date")}
        {field("lens_meta_license", "license")}
        {field("lens_meta_genre", "genre")}
        {field("lens_meta_language", "language")}
        {field("lens_meta_notes", "notes")}
      </div>

      <label style={{ display: "flex", flexDirection: "column", gap: 2, fontSize: "12px", marginBlockEnd: "var(--space-2)" }}>
        <span style={{ color: "var(--text-muted)" }}>{t(lang, "lens_meta_caption")}</span>
        <textarea value={caption ?? ""} onChange={(e) => setCaption(e.target.value)} rows={2} />
      </label>

      {/* Free multi-value tags */}
      <div style={{ marginBlockEnd: "var(--space-3)" }}>
        <div className="result-meta" style={{ marginBlockEnd: "var(--space-1)" }}>
          <strong>{t(lang, "vc_tags_label")}</strong>
          <span style={{ color: "var(--text-muted)", fontSize: "11px" }}> — {t(lang, "vc_tags_hint")}</span>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-1)", marginBlockEnd: "var(--space-1)" }}>
          {tags.map((tag) => (
            <span key={tag} className="corpus-item-genre" style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
              {tag}
              <button
                onClick={() => setTags(tags.filter((t2) => t2 !== tag))}
                aria-label={`${t(lang, "lens_delete_set")}: ${tag}`}
                style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", padding: 0, fontSize: "11px" }}
              >✕</button>
            </span>
          ))}
        </div>
        <input
          value={tagInput}
          onChange={(e) => setTagInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addTag(); } }}
          placeholder={t(lang, "vc_tags_ph")}
          style={{ maxWidth: 280 }}
        />
      </div>

      {/* The five-dimension annotation editor (schema-driven) */}
      <div style={{ marginBlockEnd: "var(--space-3)" }}>
        <div className="result-meta" style={{ marginBlockEnd: "var(--space-1)" }}>
          <strong>{t(lang, "vc_annotation_h")}</strong>
          <span style={{ color: "var(--text-muted)", fontSize: "11px" }}> — {t(lang, "vc_annotation_intro")}</span>
        </div>
        {schemaQuery.isLoading && <div className="hint">…</div>}
        {schemaQuery.error && (
          <div className="uploader-status error">{(schemaQuery.error as Error).message}</div>
        )}
        {dimensions.map((dim) => {
          const d = draft[dim.id] ?? { values: [], note: "" };
          return (
            <div key={dim.id} style={{ marginBlock: "var(--space-2)", padding: "var(--space-2)", background: "var(--bg-subtle)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: "var(--space-2)", flexWrap: "wrap" }}>
                <strong style={{ fontSize: "13px" }}>{lang === "ar" ? dim.label_ar : dim.label_en}</strong>
                <span className="hint" style={{ fontSize: "10px" }}>{dim.framework}</span>
                {d.values.length > 0 && (
                  <span className="corpus-item-genre">{d.values.length}</span>
                )}
              </div>
              <p className="hint" style={{ fontSize: "11px", margin: "2px 0 var(--space-2)" }}>
                {lang === "ar" ? dim.description_ar : dim.description_en}
              </p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {dim.categories.map((cat) => {
                  const on = d.values.includes(cat.id);
                  return (
                    <button
                      key={cat.id}
                      className={clsx("btn-small", on && "btn-primary")}
                      title={lang === "ar" ? cat.description_ar : cat.description_en}
                      aria-pressed={on}
                      onClick={() => toggleCategory(dim.id, cat.id)}
                    >
                      {lang === "ar" ? cat.label_ar : cat.label_en}
                    </button>
                  );
                })}
              </div>
              <textarea
                value={d.note}
                onChange={(e) => setDraft((prev) => ({ ...prev, [dim.id]: { ...d, note: e.target.value } }))}
                placeholder={t(lang, "vc_notes_ph")}
                rows={1}
                style={{ marginBlockStart: "var(--space-2)", fontSize: "12px", width: "100%" }}
              />
            </div>
          );
        })}
      </div>

      <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", flexWrap: "wrap", marginBlockEnd: "var(--space-3)" }}>
        <button className="btn-primary" onClick={() => saveAnnotations.mutate()} disabled={saveAnnotations.isPending}>
          {saveAnnotations.isPending ? "…" : t(lang, "vc_save_annotations")}
        </button>
        <button className="btn-secondary" onClick={() => saveMeta.mutate()} disabled={saveMeta.isPending}>
          {saveMeta.isPending ? "…" : t(lang, "lens_meta_save")}
        </button>
        {/* v1.1.0: re-run OCR/colour/composition (e.g. Tesseract was missing
            at ingest, or a language pack was installed later). */}
        <button className="btn-secondary" onClick={() => reanalyse.mutate()} disabled={reanalyse.isPending}>
          {reanalyse.isPending ? t(lang, "vc_reanalysing") : t(lang, "vc_reanalyse")}
        </button>
        <button className="btn-danger" onClick={onDeleted}>{t(lang, "lens_delete_set")}</button>
        {msg && <span className="hint">{msg}</span>}
      </div>

      {/* Machine-extracted provenance — read-only by design */}
      <div className="hint">
        <button className="btn-small" onClick={() => setShowExif((v) => !v)}>
          {showExif ? t(lang, "vision_hide_batch") : t(lang, "lens_exif_h")}
        </button>
        {showExif && (
          <>
            {Object.keys(rec.meta?.exif ?? {}).length === 0 && Object.keys(rec.meta?.xmp ?? {}).length === 0 ? (
              <div>{t(lang, "lens_exif_none")}</div>
            ) : (
              <ul style={{ margin: "4px 0" }}>
                {Object.entries(rec.meta?.exif ?? {}).map(([k, v]) => <li key={k}><code>EXIF {k}</code>: {String(v)}</li>)}
                {Object.entries(rec.meta?.xmp ?? {}).filter(([, v]) => typeof v === "string" || typeof v === "number").map(([k, v]) => <li key={k}><code>XMP {k}</code>: {String(v)}</li>)}
              </ul>
            )}
            <div>{t(lang, "lens_exif_gps_note")}</div>
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// MeasuresTab — the corpus-linguistics battery over the annotations
// ---------------------------------------------------------------------------

type MeasureTool = "ngrams" | "collocations" | "keyness" | "dispersion" | "kwic";

function MeasuresTab({ setId, allSets }: { setId: string; allSets: ImageSet[] }) {
  const lang = useUI((s) => s.lang);

  const statsQuery = useQuery({
    queryKey: ["visual-stats", setId],
    queryFn: () => api.visualStats(setId),
  });
  const profileQuery = useQuery({
    queryKey: ["visual-profile", setId],
    queryFn: () => api.visualProfile(setId),
  });
  const schemaQuery = useQuery({
    queryKey: ["annotation-schema", setId],
    queryFn: () => api.getAnnotationSchema(setId),
  });
  const dimensions: AnnotationDimension[] = schemaQuery.data?.dimensions ?? [];
  const stats: VisualStatsResult | undefined = statsQuery.data;
  const profile: VisualProfileResult | undefined = profileQuery.data;
  const anyAnnotated = (stats?.images_annotated ?? 0) > 0;

  const [tool, setTool] = useState<MeasureTool>("ngrams");

  return (
    <div className="vision-batch-panel">
      {/* 1. Frequency profile — the visual word-list, always in view */}
      <h3 className="vision-section-heading">{t(lang, "vc_frequency_h")}</h3>
      {!stats && <div className="hint">…</div>}
      {stats && !anyAnnotated && (
        <div className="hint">{t(lang, "vc_no_annotations")}</div>
      )}
      {stats && anyAnnotated && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "var(--space-2)", marginBlock: "var(--space-2)" }}>
          {dimensions.map((dim) => {
            const ds = stats.dimensions[dim.id];
            if (!ds || ds.total_values === 0) return null;
            const label = lang === "ar" ? dim.label_ar : dim.label_en;
            const maxCount = Math.max(...ds.frequency.map((f) => f.count), 1);
            return (
              <div key={dim.id} style={{ padding: "var(--space-2)", background: "var(--bg-subtle)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: "var(--space-2)" }}>
                  <strong style={{ fontSize: "12px" }}>{label}</strong>
                  <span className="hint" style={{ fontSize: "10px" }}>{ds.coverage}% · {ds.total_values}×</span>
                </div>
                {ds.frequency.map((f) => (
                  <div key={f.category} title={`${f.category}: ${f.count}`} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: "11px", marginBlock: 2 }}>
                    <span style={{ minWidth: 90, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.label_en}</span>
                    <span style={{ flex: 1, height: 8, background: "var(--bg-elevated)", borderRadius: 4, overflow: "hidden" }}>
                      <span style={{ display: "block", height: "100%", width: `${(f.count / maxCount) * 100}%`, background: "var(--brand-500)" }} />
                    </span>
                    <span style={{ minWidth: 28, textAlign: "end", color: "var(--text-muted)" }}>{f.count}</span>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      )}

      {/* 2. Diversity battery */}
      {profile && anyAnnotated && (
        <>
          <h3 className="vision-section-heading">{t(lang, "vc_diversity_h")}</h3>
          <table className="vision-vg-claims" style={{ width: "100%", fontSize: "11px", borderCollapse: "collapse", marginBlockEnd: "var(--space-3)" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "start" }}>{t(lang, "vc_annotation_h")}</th>
                <th>tokens</th><th>types</th><th>TTR</th><th>Guiraud</th><th>MATTR</th><th>STTR</th>
              </tr>
            </thead>
            <tbody>
              {dimensions.map((dim) => {
                const p = profile.dimensions[dim.id];
                if (!p || p.tokens === 0) return null;
                return (
                  <tr key={dim.id}>
                    <td>{lang === "ar" ? dim.label_ar : dim.label_en}</td>
                    <td style={{ textAlign: "center" }}>{p.tokens}</td>
                    <td style={{ textAlign: "center" }}>{p.types}</td>
                    <td style={{ textAlign: "center" }}>{p.ttr.toFixed(3)}</td>
                    <td style={{ textAlign: "center" }}>{p.guiraud.toFixed(3)}</td>
                    <td style={{ textAlign: "center" }}>{p.mattr_w10.toFixed(3)}</td>
                    <td style={{ textAlign: "center" }}>{p.sttr_c20.toFixed(3)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}

      {/* 3–7. The interactive tools */}
      <div className="sub-tabs" style={{ marginBlockStart: "var(--space-2)" }}>
        {([
          ["ngrams", "vc_ngrams_h"],
          ["collocations", "vc_collocations_h"],
          ["keyness", "vc_keyness_h"],
          ["dispersion", "vc_dispersion_h"],
          ["kwic", "vc_kwic_h"],
        ] as Array<[MeasureTool, TranslationKey]>).map(([id, key]) => (
          <button key={id} className={clsx({ active: tool === id })} onClick={() => setTool(id)}>
            {t(lang, key)}
          </button>
        ))}
      </div>

      {tool === "ngrams" && <NgramsTool setId={setId} dimensions={dimensions} />}
      {tool === "collocations" && <CollocationsTool setId={setId} dimensions={dimensions} />}
      {tool === "keyness" && <VisualKeynessTool setId={setId} dimensions={dimensions} allSets={allSets} />}
      {tool === "dispersion" && <DispersionTool setId={setId} dimensions={dimensions} />}
      {tool === "kwic" && <VisualKwicTool setId={setId} dimensions={dimensions} />}

      {/* OCR text tools (the set's embedded text as a corpus) */}
      <OcrToolsPanel setId={setId} allSets={allSets} />
    </div>
  );
}

function dimLabel(dim: AnnotationDimension, lang: "en" | "ar"): string {
  return lang === "ar" ? dim.label_ar : dim.label_en;
}

function DimensionSelect({ dimensions, value, onChange, label }: {
  dimensions: AnnotationDimension[];
  value: string;
  onChange: (v: string) => void;
  label: string;
}) {
  const lang = useUI((s) => s.lang);
  return (
    <label className="vision-align-mode">
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {dimensions.map((d) => (
          <option key={d.id} value={d.id}>{dimLabel(d, lang)}</option>
        ))}
      </select>
    </label>
  );
}

function NgramsTool({ setId, dimensions }: { setId: string; dimensions: AnnotationDimension[] }) {
  const lang = useUI((s) => s.lang);
  const [dim, setDim] = useState(dimensions[0]?.id ?? "shot_scale");
  const [n, setN] = useState(3);
  const [includeGaps, setIncludeGaps] = useState(false);
  const [enabled, setEnabled] = useState(false);

  const q = useQuery({
    queryKey: ["visual-ngrams", setId, dim, n, includeGaps],
    queryFn: () => api.visualNgrams(setId, dim, { n, includeGaps }),
    enabled: enabled,
  });

  return (
    <div className="vision-lenses-controls" style={{ marginBlock: "var(--space-2)" }}>
      <DimensionSelect dimensions={dimensions} value={dim} onChange={(v) => { setDim(v); setEnabled(false); }} label={t(lang, "vc_annotation_h")} />
      <label className="vision-align-mode">
        <span>N</span>
        <select value={n} onChange={(e) => { setN(parseInt(e.target.value, 10)); setEnabled(false); }}>
          {[2, 3, 4, 5].map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
      </label>
      <label className="vision-align-mode" style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
        <input type="checkbox" checked={includeGaps} onChange={(e) => { setIncludeGaps(e.target.checked); setEnabled(false); }} />
        <span>include gaps (&lt;gap&gt;)</span>
      </label>
      <button className="btn-primary" onClick={() => setEnabled(true)}>{t(lang, "vc_tool_run")}</button>

      {q.data && q.data.ngram_total > 0 && (
        <div className="vision-batch-freq-list" style={{ marginBlockStart: "var(--space-2)", maxHeight: 300, overflowY: "auto", width: "100%" }}>
          <div className="result-meta">
            {q.data.ngram_total} {q.data.n}-grams · stream {q.data.stream_length}
          </div>
          {q.data.ngrams.map((g, i) => (
            <div key={i} className="vision-batch-freq-item">
              <span className="vision-batch-freq-word">{g.ngram_labels.join(" → ")}</span>
              <span className="vision-batch-freq-count">{g.count} · {g.percent}%</span>
            </div>
          ))}
        </div>
      )}
      {q.data && q.data.ngram_total === 0 && (
        <div className="hint" style={{ width: "100%" }}>{t(lang, "vc_no_annotations")}</div>
      )}
    </div>
  );
}

function CollocationsTool({ setId, dimensions }: { setId: string; dimensions: AnnotationDimension[] }) {
  const lang = useUI((s) => s.lang);
  const [dimA, setDimA] = useState(dimensions[0]?.id ?? "shot_scale");
  const [dimB, setDimB] = useState(dimensions[1]?.id ?? "multimodal_integration");
  const [sort, setSort] = useState<"log_dice" | "mi" | "t_score" | "dice" | "ll">("log_dice");
  const [enabled, setEnabled] = useState(false);

  const q = useQuery({
    queryKey: ["visual-collocations", setId, dimA, dimB, sort],
    queryFn: () => api.visualCollocations(setId, dimA, dimB, { sort }),
    enabled: enabled,
  });

  return (
    <div className="vision-lenses-controls" style={{ marginBlock: "var(--space-2)" }}>
      <DimensionSelect dimensions={dimensions} value={dimA} onChange={(v) => { setDimA(v); setEnabled(false); }} label="A" />
      <DimensionSelect dimensions={dimensions} value={dimB} onChange={(v) => { setDimB(v); setEnabled(false); }} label="B" />
      <label className="vision-align-mode">
        <span>sort</span>
        <select value={sort} onChange={(e) => { setSort(e.target.value as typeof sort); setEnabled(false); }}>
          <option value="log_dice">logDice</option>
          <option value="mi">MI</option>
          <option value="t_score">t-score</option>
          <option value="dice">Dice</option>
          <option value="ll">G²</option>
        </select>
      </label>
      <button className="btn-primary" onClick={() => setEnabled(true)}>{t(lang, "vc_tool_run")}</button>

      {q.data?.note && <div className="hint" style={{ width: "100%" }}>{q.data.note}</div>}
      {q.data && q.data.rows.length > 0 && (
        <div style={{ marginBlockStart: "var(--space-2)", maxHeight: 360, overflowY: "auto", width: "100%" }}>
          <div className="result-meta">{q.data.frames} frames</div>
          <table className="vision-vg-claims" style={{ width: "100%", fontSize: "11px", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "start" }}>A</th>
                <th style={{ textAlign: "start" }}>B</th>
                <th>joint</th>
                <th>MI</th>
                <th>t</th>
                <th>logDice</th>
                <th>ΔP</th>
              </tr>
            </thead>
            <tbody>
              {q.data.rows.map((r, i) => (
                <tr key={i}>
                  <td>{r.label_a}</td>
                  <td>{r.label_b}</td>
                  <td style={{ textAlign: "center" }}>{r.joint}</td>
                  <td style={{ textAlign: "center" }}>{r.mi.toFixed(2)}</td>
                  <td style={{ textAlign: "center" }}>{r.t_score.toFixed(2)}</td>
                  <td style={{ textAlign: "center" }}>{r.log_dice.toFixed(2)}</td>
                  <td style={{ textAlign: "center" }}>{r.delta_p_b_given_a.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function VisualKeynessTool({ setId, dimensions, allSets }: {
  setId: string;
  dimensions: AnnotationDimension[];
  allSets: ImageSet[];
}) {
  const lang = useUI((s) => s.lang);
  const [dim, setDim] = useState("shot_scale");
  const [otherSet, setOtherSet] = useState("");
  const [enabled, setEnabled] = useState(false);

  const q = useQuery({
    queryKey: ["visual-keyness", setId, dim, otherSet],
    queryFn: () => api.visualKeyness(setId, otherSet, dim),
    enabled: enabled && !!otherSet,
  });

  return (
    <div className="vision-lenses-controls" style={{ marginBlock: "var(--space-2)" }}>
      <DimensionSelect dimensions={dimensions} value={dim} onChange={(v) => { setDim(v); setEnabled(false); }} label={t(lang, "vc_annotation_h")} />
      <label className="vision-align-mode">
        <span>{t(lang, "lens_keyness_vs")}</span>
        <select value={otherSet} onChange={(e) => { setOtherSet(e.target.value); setEnabled(false); }}>
          <option value="">—</option>
          {allSets.filter((s) => s.id !== setId).map((s) => (
            <option key={s.id} value={s.id}>{s.name} ({s.image_count})</option>
          ))}
        </select>
      </label>
      <button className="btn-primary" onClick={() => { if (otherSet) setEnabled(true); }} disabled={!otherSet}>
        {t(lang, "lens_keyness_run")}
      </button>

      {q.data?.note && <div className="hint" style={{ width: "100%" }}>{q.data.note}</div>}
      {q.data && q.data.rows.length > 0 && (
        <div style={{ marginBlockStart: "var(--space-2)", maxHeight: 360, overflowY: "auto", width: "100%" }}>
          <div className="result-meta">
            {q.data.target.name} ({q.data.target.values}) vs {q.data.reference.name} ({q.data.reference.values})
          </div>
          <table className="vision-vg-claims" style={{ width: "100%", fontSize: "11px", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "start" }}>category</th>
                <th>f(target)</th>
                <th>f(ref)</th>
                <th>{t(lang, "lens_keyness_ll")}</th>
                <th>{t(lang, "lens_keyness_logratio")}</th>
              </tr>
            </thead>
            <tbody>
              {q.data.rows.map((r) => (
                <tr key={r.category}>
                  <td>{r.label_en}</td>
                  <td style={{ textAlign: "center" }}>{r.f_target}</td>
                  <td style={{ textAlign: "center" }}>{r.f_reference}</td>
                  <td style={{ textAlign: "center" }}>{r.log_likelihood.toFixed(1)}</td>
                  <td style={{ textAlign: "center" }}>{r.log_ratio.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function DispersionTool({ setId, dimensions }: { setId: string; dimensions: AnnotationDimension[] }) {
  const lang = useUI((s) => s.lang);
  const [dim, setDim] = useState("shot_scale");
  const [bins, setBins] = useState(10);
  const [enabled, setEnabled] = useState(false);

  const q = useQuery({
    queryKey: ["visual-dispersion", setId, dim, bins],
    queryFn: () => api.visualDispersion(setId, dim, { bins }),
    enabled: enabled,
  });

  return (
    <div className="vision-lenses-controls" style={{ marginBlock: "var(--space-2)" }}>
      <DimensionSelect dimensions={dimensions} value={dim} onChange={(v) => { setDim(v); setEnabled(false); }} label={t(lang, "vc_annotation_h")} />
      <label className="vision-align-mode">
        <span>bins</span>
        <input type="number" min={2} max={50} value={bins}
               onChange={(e) => { setBins(Math.max(2, Math.min(50, parseInt(e.target.value, 10) || 10))); setEnabled(false); }}
               style={{ width: 64 }} />
      </label>
      <button className="btn-primary" onClick={() => setEnabled(true)}>{t(lang, "vc_tool_run")}</button>

      {q.data && q.data.categories.length > 0 && (
        <div style={{ marginBlockStart: "var(--space-2)", width: "100%", maxHeight: 360, overflowY: "auto" }}>
          <div className="result-meta">stream {q.data.stream_length} · {q.data.bins} bins</div>
          <table className="vision-vg-claims" style={{ width: "100%", fontSize: "11px", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "start" }}>category</th>
                <th>total</th>
                <th>range</th>
                <th>Juilland D</th>
                <th>DP</th>
                <th style={{ textAlign: "start" }}>distribution</th>
              </tr>
            </thead>
            <tbody>
              {q.data.categories.map((c) => {
                const maxBin = Math.max(...c.per_bin, 1);
                return (
                  <tr key={c.category}>
                    <td>{c.label_en}</td>
                    <td style={{ textAlign: "center" }}>{c.total}</td>
                    <td style={{ textAlign: "center" }}>{(c.range * 100).toFixed(0)}%</td>
                    <td style={{ textAlign: "center" }}>{c.juillands_d.toFixed(2)}</td>
                    <td style={{ textAlign: "center" }}>{c.dp.toFixed(3)}</td>
                    <td>
                      <span style={{ display: "inline-flex", gap: 1 }}>
                        {c.per_bin.map((b, i) => (
                          <span key={i} title={`bin ${i + 1}: ${b}`}
                                style={{ display: "inline-block", width: 8, height: 10, background: b ? "var(--brand-500)" : "var(--bg-elevated)", opacity: b ? 0.35 + 0.65 * (b / maxBin) : 1, borderRadius: 1 }} />
                        ))}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function VisualKwicTool({ setId, dimensions }: { setId: string; dimensions: AnnotationDimension[] }) {
  const lang = useUI((s) => s.lang);
  const [dim, setDim] = useState("shot_scale");
  const [category, setCategory] = useState("");
  const [enabled, setEnabled] = useState(false);

  const dimObj = dimensions.find((d) => d.id === dim);
  const q = useQuery({
    queryKey: ["visual-kwic", setId, dim, category],
    queryFn: () => api.visualKwic(setId, dim, category),
    enabled: enabled && !!category,
  });

  return (
    <div className="vision-lenses-controls" style={{ marginBlock: "var(--space-2)" }}>
      <DimensionSelect dimensions={dimensions} value={dim} onChange={(v) => { setDim(v); setCategory(""); setEnabled(false); }} label={t(lang, "vc_annotation_h")} />
      <label className="vision-align-mode">
        <span>category</span>
        <select value={category} onChange={(e) => { setCategory(e.target.value); setEnabled(false); }}>
          <option value="">—</option>
          {(dimObj?.categories ?? []).map((c) => (
            <option key={c.id} value={c.id}>{lang === "ar" ? c.label_ar : c.label_en}</option>
          ))}
        </select>
      </label>
      <button className="btn-primary" onClick={() => { if (category) setEnabled(true); }} disabled={!category}>
        {t(lang, "vc_tool_run")}
      </button>

      {q.data && (
        <div style={{ marginBlockStart: "var(--space-2)", width: "100%", maxHeight: 360, overflowY: "auto" }}>
          <div className="result-meta">{q.data.hit_count} hit(s) · stream {q.data.stream_length}</div>
          {q.data.hits.length === 0 && <div className="hint">{t(lang, "lens_search_no_hits")}</div>}
          <ul className="vision-align-list">
            {q.data.hits.map((h) => (
              <li key={h.image_id} className="vision-align-item">
                <div className="vision-align-item-header">
                  <span className="vision-align-span" dir="auto">
                    {h.left.map((c, i) => <span key={i} style={{ color: "var(--text-muted)" }}>{c.label_en} </span>)}
                    <strong>{h.node.label_en}</strong>
                    {h.right.map((c, i) => <span key={i} style={{ color: "var(--text-muted)" }}> {c.label_en}</span>)}
                  </span>
                  <span className="vision-align-confidence">#{h.position}</span>
                </div>
                <div className="vision-align-reason"><code>{h.filename}</code></div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// OcrToolsPanel — search / frequency / keyness over the set's OCR text
// (moved from LensCorporaView — the text side of the visual corpus)
// ---------------------------------------------------------------------------

function OcrToolsPanel({ setId, allSets }: { setId: string; allSets: ImageSet[] }) {
  const lang = useUI((s) => s.lang);
  const [tab, setTab] = useState<"search" | "freq" | "keyness">("search");
  const [q, setQ] = useState("");
  const [regex, setRegex] = useState(false);
  const [searchQ, setSearchQ] = useState<{ q: string; regex: boolean } | null>(null);
  const [stopwords, setStopwords] = useState(true);
  const [minLen, setMinLen] = useState(2);
  const [freqEnabled, setFreqEnabled] = useState(false);
  const [otherSet, setOtherSet] = useState("");
  const [keyEnabled, setKeyEnabled] = useState(false);

  const others = allSets.filter((s) => s.id !== setId);

  const search = useQuery({
    queryKey: ["lens-ocr-search", setId, searchQ?.q, searchQ?.regex],
    queryFn: () => api.ocrSearch(setId, searchQ!.q, searchQ!.regex),
    enabled: !!searchQ,
  });

  const freq = useQuery({
    queryKey: ["lens-ocr-freq", setId, stopwords, minLen],
    queryFn: () => api.ocrFrequency(setId, { stopwords, minLen, limit: 100 }),
    enabled: freqEnabled,
  });

  const keyness = useQuery({
    queryKey: ["lens-ocr-keyness", setId, otherSet, stopwords],
    queryFn: () => api.ocrKeyness(setId, otherSet, { stopwords, minFreq: 2 }),
    enabled: keyEnabled && !!otherSet,
  });

  return (
    <div style={{ marginBlockStart: "var(--space-3)" }}>
      <div className="vision-batch-header">
        <h3 className="vision-section-heading">{t(lang, "lens_ocr_tools_h")}</h3>
      </div>
      <p className="hint">{t(lang, "lens_ocr_tools_intro")}</p>

      <div className="sub-tabs">
        <button className={clsx({ active: tab === "search" })} onClick={() => setTab("search")}>{t(lang, "lens_search_run")}</button>
        <button className={clsx({ active: tab === "freq" })} onClick={() => setTab("freq")}>{t(lang, "lens_freq_run")}</button>
        <button className={clsx({ active: tab === "keyness" })} onClick={() => setTab("keyness")}>{t(lang, "lens_keyness_run")}</button>
      </div>

      <div className="vision-lenses-controls">
        {tab === "search" && (
          <>
            <input
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && q.trim()) setSearchQ({ q: q.trim(), regex }); }}
              placeholder={t(lang, "lens_search_ph")}
              style={{ flex: 1, minWidth: 180 }}
            />
            <label className="vision-align-mode" style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <input type="checkbox" checked={regex} onChange={(e) => setRegex(e.target.checked)} />
              <span>{t(lang, "lens_search_regex")}</span>
            </label>
            <button className="btn-primary" onClick={() => setSearchQ(q.trim() ? { q: q.trim(), regex } : null)}>
              {t(lang, "lens_search_run")}
            </button>
          </>
        )}

        {tab === "freq" && (
          <>
            <label className="vision-align-mode" style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <input type="checkbox" checked={stopwords} onChange={(e) => setStopwords(e.target.checked)} />
              <span>{t(lang, "lens_freq_stopwords")}</span>
            </label>
            <label className="vision-align-mode">
              <span>{t(lang, "lens_min_len")}</span>
              <input type="number" min={1} max={8} value={minLen} onChange={(e) => setMinLen(Math.max(1, parseInt(e.target.value) || 1))} style={{ width: 64 }} />
            </label>
            <button className="btn-primary" onClick={() => setFreqEnabled(true)}>{t(lang, "lens_freq_run")}</button>
          </>
        )}

        {tab === "keyness" && (
          <>
            <label className="vision-align-mode">
              <span>{t(lang, "lens_keyness_vs")}</span>
              <select value={otherSet} onChange={(e) => { setOtherSet(e.target.value); setKeyEnabled(false); }}>
                <option value="">—</option>
                {others.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.image_count})</option>)}
              </select>
            </label>
            <label className="vision-align-mode" style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <input type="checkbox" checked={stopwords} onChange={(e) => setStopwords(e.target.checked)} />
              <span>{t(lang, "lens_freq_stopwords")}</span>
            </label>
            <button
              className="btn-primary"
              onClick={() => { if (otherSet) setKeyEnabled(true); }}
              disabled={!otherSet}
            >
              {t(lang, "lens_keyness_run")}
            </button>
          </>
        )}
      </div>

      {tab === "search" && searchQ && (
        <OcrSearchResult result={search.data} loading={search.isLoading} error={search.error as Error | null} />
      )}

      {tab === "freq" && freqEnabled && freq.data && (
        <div className="vision-batch-freq-list" style={{ maxHeight: 320, overflowY: "auto" }}>
          <div className="result-meta">
            {freq.data.total_tokens.toLocaleString()} tokens · {freq.data.types} types
          </div>
          {freq.data.frequency.map((row: OcrFrequencyResult["frequency"][number]) => (
            <div key={row.word} className="vision-batch-freq-item">
              <span className="vision-batch-freq-word">{row.word}</span>
              <span className="vision-batch-freq-count">{row.count} · {row.percent}%</span>
            </div>
          ))}
          {freq.data.frequency.length === 0 && <div className="hint">{t(lang, "lens_search_no_hits")}</div>}
        </div>
      )}

      {tab === "keyness" && keyEnabled && keyness.data && (
        <OcrKeynessTable result={keyness.data} />
      )}
    </div>
  );
}

function OcrSearchResult({ result, loading, error }: {
  result: OcrSearchResult | undefined;
  loading: boolean;
  error: Error | null;
}) {
  const lang = useUI((s) => s.lang);
  if (loading) return <div className="hint">…</div>;
  if (error) return <div className="uploader-status error">{error.message}</div>;
  if (!result) return null;
  if (result.hit_count === 0) return <div className="hint">{t(lang, "lens_search_no_hits")}</div>;
  return (
    <div style={{ marginBlockStart: "var(--space-2)" }}>
      <div className="result-meta">{result.hit_count} hit(s) · {result.images_searched} image(s)</div>
      <ul className="vision-align-list">
        {result.hits.map((h, i) => (
          <li key={`${h.image_id}-${i}`} className="vision-align-item">
            <div className="vision-align-item-header">
              <span className="vision-align-span" dir="auto">
                {h.left}<strong>{h.match}</strong>{h.right}
              </span>
              <span className="vision-align-confidence">×{h.match_count}</span>
            </div>
            <div className="vision-align-reason">
              <code>{h.filename}</code> ({h.field})
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function OcrKeynessTable({ result }: { result: OcrKeynessResult }) {
  const lang = useUI((s) => s.lang);
  if (result.note) return <div className="hint">{result.note}</div>;
  return (
    <div style={{ marginBlockStart: "var(--space-2)", maxHeight: 360, overflowY: "auto" }}>
      <div className="result-meta">
        {result.target.name} ({result.target.tokens.toLocaleString()}) vs {result.reference.name} ({result.reference.tokens.toLocaleString()})
      </div>
      <table className="vision-vg-claims" style={{ width: "100%", fontSize: "12px", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={{ textAlign: "start" }}>term</th>
            <th>f(target)</th>
            <th>f(ref)</th>
            <th>{t(lang, "lens_keyness_ll")}</th>
            <th>{t(lang, "lens_keyness_logratio")}</th>
          </tr>
        </thead>
        <tbody>
          {result.rows.map((r) => (
            <tr key={r.term}>
              <td dir="auto">{r.term}</td>
              <td style={{ textAlign: "center" }}>{r.f_target}</td>
              <td style={{ textAlign: "center" }}>{r.f_reference}</td>
              <td style={{ textAlign: "center" }}>{r.log_likelihood.toFixed(1)}</td>
              <td style={{ textAlign: "center" }}>{r.log_ratio.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// VisionTab — the interpretive layer (reuses VisionView's panels)
// ---------------------------------------------------------------------------

function VisionTab({ setId, selectedImageId }: { setId: string; selectedImageId: string | null }) {
  const lang = useUI((s) => s.lang);
  return (
    <div className="vision-workspace">
      <VisionGuidance lang={lang} />
      {selectedImageId ? (
        <>
          <AnalysisDrawer imageId={selectedImageId} />
          <DiscourseLensesPanel imageId={selectedImageId} />
          <AlignmentPanel imageId={selectedImageId} />
          <FacialAnalysisPanel imageId={selectedImageId} />
        </>
      ) : (
        <div className="hint">{t(lang, "vc_select_image_hint")}</div>
      )}
      <BatchRunnerPanel isetId={setId} />
      <BatchViewPanel isetId={setId} />
    </div>
  );
}

