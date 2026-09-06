/**
 * LensCorporaView — v1.0.9 Lens round.
 *
 * The Lens shell's "Your Corpus" view. In the main CorpusMind app this nav
 * target renders CorpusSelectionView (text corpora); in Lens mode it renders
 * THIS view instead, because Lens is an image-corpus workbench: the visual
 * items are the corpus (cf. CLARIN's multimodal corpora resource family and
 * the CASS corpus-methods-for-multimodal-data programme).
 *
 * What it gives the researcher (the scholarly apparatus the text side has,
 * rebuilt for images):
 *   - Image sets as first-class corpus cards, with provenance/sampling notes
 *     (corpus-construction norm: document your sampling frame).
 *   - Set-level corpus statistics: formats, orientation mix, resolution
 *     range, date range, coverage (OCR / captions / vision-LM / metadata).
 *   - Per-image metadata aligned with IPTC Core descriptive fields (source,
 *     date, licence/rights, genre, language of embedded text, notes) plus
 *     read-only EXIF/XMP extracted at ingest — GPS is never extracted.
 *   - Bulk "Tag All Images" and genre filtering (subsetting).
 *   - OCR Corpus Tools: KWIC-style search over OCR text + captions, a
 *     word-frequency list with the engine's EN/AR stopword control, and
 *     set-vs-set keyness (log-likelihood) — the image-corpus analogues of
 *     concordance, word list, and keyness.
 *   - OCR corpus export (<doc>-marked txt / json) so the visual side's text
 *     can be analysed with the main app's full text tooling.
 *
 * Everything here is additive and Lens-only: the main app's corpus view is
 * untouched.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ExportButton } from "@/components/ExportButton";
import {
  api,
  exportWithFeedback,
  type ImageRecord,
  type ImageSet,
  type ImageSetStats,
  type OcrFrequencyResult,
  type OcrKeynessResult,
  type OcrSearchResult,
} from "@/lib/api";
import { useApp } from "@/store/app";
import { useUI } from "@/store/ui";
import { t, type TranslationKey } from "@/lib/i18n";
import { ProjectSelector } from "@/views/CorpusSelectionView";

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

export function LensCorporaView() {
  const lang = useUI((s) => s.lang);
  const setActiveNav = useUI((s) => s.setActiveNav);

  return (
    <div className="corpus-selection-view">
      <div className="corpus-selection-header">
        <h1>{t(lang, "lens_your_image_corpora")}</h1>
        <p className="corpus-selection-subtitle">{t(lang, "lens_corpora_subtitle")}</p>
      </div>

      <ProjectSelector />

      <div className="corpus-selection-grid">
        <CorpusListPanel />
        <ImageSetWorkspace onOpenVision={() => setActiveNav("vision")} />
      </div>
    </div>
  );
}


// ─── Corpus list (Lens flavour: corpora are containers of image sets) ─────

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

  return (
    <section className="corpus-panel">
      <header className="corpus-panel-header">
        <h2>{t(lang, "nav_file")}</h2>
      </header>

      {!activeProjectId && (
        <div className="corpus-empty">{t(lang, "lens_select_corpus_first")}</div>
      )}

      <ul className="corpus-list">
        {corpora.data?.map((c) => (
          <li
            key={c.id}
            className={clsx("corpus-list-item", { active: c.id === activeCorpusId })}
            onClick={() => setActiveCorpus(c.id)}
          >
            <div className="corpus-item-name">{c.name}</div>
            <div className="corpus-item-meta">
              <span className="corpus-meta-lang">{c.language.toUpperCase()}</span>
              {c.genre && c.genre !== "mixed" && <span className="corpus-item-genre">{c.genre}</span>}
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


// ─── Image-set workspace for the active corpus ─────────────────────────────

function ImageSetWorkspace({ onOpenVision }: { onOpenVision: () => void }) {
  const lang = useUI((s) => s.lang);
  const qc = useQueryClient();
  const cid = useApp((s) => s.activeCorpusId);
  const [selectedSetId, setSelectedSetId] = useState<string | null>(null);
  const [showNewSet, setShowNewSet] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [editingNotes, setEditingNotes] = useState(false);
  const [notesDraft, setNotesDraft] = useState("");
  const [confirm, setConfirm] = useState<{ msg: string; onConfirm: () => void } | null>(null);
  const [actionMsg, setActionMsg] = useState("");
  const [filterGenre, setFilterGenre] = useState("");

  const sets = useQuery({
    queryKey: ["image-sets", cid],
    queryFn: () => api.listImageSets(cid!),
    enabled: !!cid,
  });

  // Auto-select the first set once so the workspace is never mysteriously
  // empty (render-phase state adjustment — the official React pattern,
  // same as VisionView's set picker).
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
              setFilterGenre("");
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
          {/* Provenance / sampling notes (corpus documentation) */}
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
            <button className="btn-secondary" onClick={onOpenVision}>{t(lang, "lens_open_in_vision")}</button>
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

          <SetStatsPanel setId={activeSet.id} onGenrePick={(g) => setFilterGenre(g === filterGenre ? "" : g)} activeGenre={filterGenre} />

          <ImagesPanel setId={activeSet.id} filterGenre={filterGenre} />
          <OcrToolsPanel setId={activeSet.id} allSets={sets.data ?? []} />
        </>
      )}

      {actionMsg && <div className="uploader-status info" style={{ marginBlockStart: "var(--space-2)" }}>{actionMsg}</div>}

      <ConfirmDialog state={confirm} onClose={() => setConfirm(null)} />
    </section>
  );
}


// ─── SetStatsPanel — set-level corpus statistics + coverage ───────────────

function SetStatsPanel({ setId, onGenrePick, activeGenre }: {
  setId: string;
  onGenrePick: (genre: string) => void;
  activeGenre: string;
}) {
  const lang = useUI((s) => s.lang);
  const stats = useQuery({
    queryKey: ["image-set-stats", setId],
    queryFn: () => api.imageSetStats(setId),
    refetchInterval: 15_000,
  });

  if (!stats.data) return null;
  const s: ImageSetStats = stats.data;
  const cov = s.coverage;
  const n = s.image_count || 1;
  const res = s.resolution;

  return (
    <div className="corpus-stats-dashboard" style={{ marginBlockEnd: "var(--space-3)" }}>
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
      </div>

      {/* Coverage bars — documentation completeness at a glance */}
      <div className="hint" style={{ marginBlock: "var(--space-2)" }}>
        <div>{t(lang, "lens_coverage")}: {t(lang, "lens_cov_ocr")} {cov.with_ocr}/{s.image_count} · {t(lang, "lens_cov_caption")} {cov.with_caption}/{s.image_count} · {t(lang, "lens_cov_vlm")} {cov.with_vlm}/{s.image_count} · {t(lang, "lens_cov_meta")} {cov.with_user_meta}/{s.image_count}</div>
      </div>

      {(Object.keys(s.genres).length > 0 || Object.keys(s.sources).length > 0) && (
        <div className="hint" style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-2)" }}>
          {Object.entries(s.genres).map(([g, c]) => (
            <button
              key={g}
              className={clsx("btn-small", activeGenre === g && "btn-primary")}
              onClick={() => onGenrePick(g)}
              title={`${t(lang, "lens_filter_genre")}: ${g}`}
            >
              {g} ({c}) · {Math.round((c / n) * 100)}%
            </button>
          ))}
          {Object.entries(s.sources).slice(0, 6).map(([src, c]) => (
            <span key={src} className="corpus-item-genre">{src} ({c})</span>
          ))}
        </div>
      )}
    </div>
  );
}


// ─── ImagesPanel — upload + paginated grid + metadata editor + bulk tag ───

function ImagesPanel({ setId, filterGenre }: { setId: string; filterGenre: string }) {
  const lang = useUI((s) => s.lang);
  const qc = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [selectedImageId, setSelectedImageId] = useState<string | null>(null);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const [showBulk, setShowBulk] = useState(false);
  const [bulk, setBulk] = useState({ source: "", date: "", license: "", genre: "", language: "" });
  const [confirm, setConfirm] = useState<{ msg: string; onConfirm: () => void } | null>(null);
  const [statusMsg, setStatusMsg] = useState("");

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["lens-images", setId] });
    qc.invalidateQueries({ queryKey: ["image-set-stats", setId] });
    qc.invalidateQueries({ queryKey: ["image-sets"] });
  };

  const images = useQuery({
    queryKey: ["lens-images", setId, limit],
    queryFn: () => api.listImagesPaged(setId, limit, 0),
  });

  const upload = useMutation({
    mutationFn: () => api.uploadImages(setId, pendingFiles),
    onSuccess: (_data) => {
      setStatusMsg(tf(lang, "lens_upload_done", { n: pendingFiles.length }));
      setPendingFiles([]);
      invalidate();
      setTimeout(() => setStatusMsg(""), 6000);
    },
    onError: (e: Error) => setStatusMsg(`${t(lang, "lens_upload_failed")}: ${e.message}`),
  });

  const bulkTag = useMutation({
    mutationFn: () => api.bulkImageMeta(setId, Object.fromEntries(Object.entries(bulk).filter(([, v]) => v.trim())) as Record<string, string>),
    onSuccess: (res) => {
      setStatusMsg(tf(lang, "lens_bulk_done", { n: res.updated }));
      setShowBulk(false);
      setBulk({ source: "", date: "", license: "", genre: "", language: "" });
      invalidate();
      setTimeout(() => setStatusMsg(""), 6000);
    },
    onError: (e: Error) => setStatusMsg(`${t(lang, "lens_save_failed")}: ${e.message}`),
  });

  const deleteImage = useMutation({
    mutationFn: (imgId: string) => api.deleteImage(imgId),
    onSuccess: () => {
      setSelectedImageId(null);
      invalidate();
    },
    onError: (e: Error) => setStatusMsg(`${t(lang, "lens_delete_failed")}: ${e.message}`),
  });

  // Client-side genre filter (metadata lives on the returned records).
  const items = useMemo(() => {
    const arr = images.data?.items ?? [];
    if (!filterGenre) return arr;
    return arr.filter((img) => img.meta?.user?.genre === filterGenre);
  }, [images.data, filterGenre]);

  const total = images.data?.total ?? 0;
  const hasMore = images.data ? items.length < total && !filterGenre : false;

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
          const arr = Array.from(e.dataTransfer.files).filter((f) => f.type.startsWith("image/"));
          setPendingFiles((prev) => [...prev, ...arr]);
        }}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInputRef.current?.click(); } }}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={IMAGE_ACCEPT}
          onChange={(e) => {
            const arr = Array.from(e.target.files ?? []).filter((f) => f.type.startsWith("image/"));
            if (arr.length) setPendingFiles((prev) => [...prev, ...arr]);
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
          <button className="btn-primary" onClick={() => upload.mutate()} disabled={upload.isPending}>
            {upload.isPending ? "…" : tf(lang, "lens_uploading", { n: pendingFiles.length })}
          </button>
        </div>
      )}

      {/* Grid toolbar: bulk tagging + genre filter indicator */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "var(--space-2)", marginBlock: "var(--space-2)", flexWrap: "wrap" }}>
        <h3 className="vision-section-heading" style={{ margin: 0 }}>{t(lang, "lens_images")}{filterGenre ? ` — ${filterGenre}` : ""}</h3>
        <div style={{ display: "flex", gap: "var(--space-2)" }}>
          {filterGenre && (
            <button className="btn-small" onClick={() => {}}>{t(lang, "lens_filter_genre")}: {filterGenre} ✕{/* click handled via stats chips */}</button>
          )}
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
            <LensImageCard
              key={img.id}
              image={img}
              selected={img.id === selectedImageId}
              onSelect={() => setSelectedImageId(img.id === selectedImageId ? null : img.id)}
            />
          ))}
        </div>
      )}

      {images.data && (
        <div className="hint" style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", marginBlock: "var(--space-2)" }}>
          <span>{tf(lang, "lens_showing_of", { shown: items.length, total })}</span>
          {hasMore && (
            <button className="btn-small" onClick={() => setLimit((l) => l + PAGE_SIZE)}>
              {t(lang, "lens_load_more")}
            </button>
          )}
        </div>
      )}

      {selectedImageId && (
        <ImageMetaEditor
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


// ─── LensImageCard — grid thumbnail with metadata badge ───────────────────

function LensImageCard({ image, selected, onSelect }: {
  image: ImageRecord;
  selected: boolean;
  onSelect: () => void;
}) {
  const thumbQuery = useQuery({
    queryKey: ["image-thumbnail", image.id],
    queryFn: () => api.fetchImageThumbnailUrl(image.id),
    staleTime: Infinity,
    retry: false,
  });

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
        {image.meta?.user?.genre && <div className="vision-grid-caption">{image.meta.user.genre}</div>}
        {image.caption && <div className="vision-grid-caption" title={image.caption}>{image.caption}</div>}
      </div>
    </button>
  );
}


// ─── ImageMetaEditor — IPTC-Core-aligned per-image metadata ───────────────

function ImageMetaEditor({ imgId, onSaved, onDeleted }: {
  imgId: string;
  onSaved: () => void;
  onDeleted: () => void;
}) {
  const lang = useUI((s) => s.lang);
  const qc = useQueryClient();
  const image = useQuery({
    queryKey: ["lens-image", imgId],
    queryFn: () => api.listImagesPaged("", 1, 0).then(() => null).catch(() => null), // placeholder no-op
    enabled: false,
  });
  void image;

  // The images list already carries meta — find it via a direct fetch.
  const metaQuery = useQuery({
    queryKey: ["lens-image-meta", imgId],
    queryFn: async (): Promise<ImageRecord> => {
      // Minimal fetch of one record: the engine does not expose GET /images/{id},
      // so read from the parent list cache when available, else refetch paged.
      const cached = qc.getQueriesData({ queryKey: ["lens-images"] });
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
  const [msg, setMsg] = useState("");

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
    }
  }, [rec?.id, rec]);

  const save = useMutation({
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

  if (!rec) return null;
  const exifEntries = Object.entries(rec.meta?.exif ?? {});
  const xmpEntries = Object.entries(rec.meta?.xmp ?? {}).filter(([, v]) => typeof v === "string" || typeof v === "number");

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
        {" · "}
        {t(lang, "vision_dimensions")}: {rec.width}×{rec.height}
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

      <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", marginBlockEnd: "var(--space-3)" }}>
        <button className="btn-primary" onClick={() => save.mutate()} disabled={save.isPending}>
          {save.isPending ? "…" : t(lang, "lens_meta_save")}
        </button>
        <button className="btn-danger" onClick={onDeleted}>{t(lang, "lens_delete_set")}</button>
        {msg && <span className="hint">{msg}</span>}
      </div>

      {/* Machine-extracted provenance — read-only by design */}
      <div className="hint">
        <strong>{t(lang, "lens_exif_h")}</strong>
        {exifEntries.length === 0 && xmpEntries.length === 0 ? (
          <div>{t(lang, "lens_exif_none")}</div>
        ) : (
          <ul style={{ margin: "4px 0" }}>
            {exifEntries.map(([k, v]) => <li key={k}><code>EXIF {k}</code>: {String(v)}</li>)}
            {xmpEntries.map(([k, v]) => <li key={k}><code>XMP {k}</code>: {String(v)}</li>)}
          </ul>
        )}
        <div>{t(lang, "lens_exif_gps_note")}</div>
      </div>
    </div>
  );
}


// ─── OcrToolsPanel — search / frequency / keyness over the set's text ─────

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
    <div className="vision-batch-panel">
      <div className="vision-batch-header">
        <h3 className="vision-section-heading">{t(lang, "lens_ocr_tools_h")}</h3>
      </div>
      <p className="hint">{t(lang, "lens_ocr_tools_intro")}</p>

      <div className="vision-lenses-controls">
        <label className="vision-align-mode">
          <span> </span>
          <select value={tab} onChange={(e) => setTab(e.target.value as typeof tab)}>
            <option value="search">{t(lang, "lens_search_run")}</option>
            <option value="freq">{t(lang, "lens_freq_run")}</option>
            <option value="keyness">{t(lang, "lens_keyness_run")}</option>
          </select>
        </label>

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
        <SearchResult result={search.data} loading={search.isLoading} error={search.error as Error | null} />
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
        <KeynessTable result={keyness.data} />
      )}
    </div>
  );
}


function SearchResult({ result, loading, error }: {
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


function KeynessTable({ result }: { result: OcrKeynessResult }) {
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
            <th>{t(lang, "lens_stat_images") === "Images" ? "f(target)" : "f"}</th>
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
