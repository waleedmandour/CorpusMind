/**
 * VisionView — Suite B (9.1–9.18).
 *
 * CorpusMind Lens core view. v1.2.0 Lens round: this view is now
 * fully i18n (en/ar), and gains the missing feature surface:
 *   - Discourse lenses panel (the 8 Phase-5 routes were backend-only)
 *   - Vision-model picker (capability-aware auto-pick or explicit)
 *   - Batch runner (analyse the whole set — no per-image clicking)
 *   - Set/image export + deletion
 *   - Provenance badges (heuristic vs vision-LM, model, confidence)
 *
 * Layout (top-to-bottom):
 *   1. Toolbar — image-set picker, new-set, delete-set, export set.
 *   2. Dropzone + pending upload list.
 *   3. Image grid (thumbnails, delete per image).
 *   4. Analysis drawer for the selected image (OCR / colours /
 *      composition + Vision-LM describe + Visual Grammar + Discourse
 *      lenses + alignment + facial analysis).
 *   5. Batch runner + read-only batch view.
 */
import { useState, useRef, type KeyboardEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import { api, exportWithFeedback, type ImageRecord, type ImageAnalysis, type VisualGrammarResult, type BatchAnalysisResult, type DiscourseResult, type DiscourseClaim } from "@/lib/api";
import { ExportButton } from "@/components/ExportButton";
import { useApp } from "@/store/app";
import { useUI } from "@/store/ui";
import { t, type TranslationKey } from "@/lib/i18n";
import { useTroubleshoot } from "@/store/troubleshooting";


// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/** Localize a template that contains {n}/{done}/{total} placeholders. */
function tf(lang: "en" | "ar", key: TranslationKey, vars: Record<string, string | number>): string {
  let s = t(lang, key);
  for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, String(v));
  return s;
}

/** Route an error into Smart Troubleshooting so the Fix: hint appears. */
function reportVisionError(e: unknown, endpoint: string, context: string): string {
  const msg = (e as Error)?.message || String(e);
  useTroubleshoot.getState().captureError({
    message: msg,
    endpoint,
    context,
  });
  return msg;
}

const IMAGE_ACCEPT = "image/png,image/jpeg,image/webp,image/gif";

// The 8 discourse-lens routes (Phase 5 §9.11–9.18). Labels are i18n keys.
const LENS_ROUTES: Array<{ route: string; labelKey: TranslationKey; isCda?: boolean }> = [
  { route: "social-semiotic", labelKey: "vision_lens_framework" },
  { route: "cda", labelKey: "vision_lens_framework", isCda: true },
  { route: "persuasion", labelKey: "vision_lens_framework" },
  { route: "framing", labelKey: "vision_lens_framework" },
  { route: "narrative", labelKey: "vision_lens_framework" },
  { route: "visual-metaphor", labelKey: "vision_lens_framework" },
  { route: "emotion", labelKey: "vision_lens_framework" },
  { route: "cultural", labelKey: "vision_lens_framework" },
];

// Friendly route → display names (framework names come from the engine
// response; these only back the dropdown).
const LENS_NAMES: Record<string, { en: string; ar: string }> = {
  "social-semiotic": { en: "Social semiotics", ar: "السيميائيات الاجتماعية" },
  "cda": { en: "Critical discourse analysis", ar: "التحليل النقدي للخطاب" },
  "persuasion": { en: "Persuasion strategies", ar: "استراتيجيات الإقناع" },
  "framing": { en: "Framing", ar: "ال تأطير" },
  "narrative": { en: "Narrative structure", ar: "البنية السردية" },
  "visual-metaphor": { en: "Visual metaphor", ar: "الاستعارة البصرية" },
  "emotion": { en: "Emotion appeal", ar: "مناشدة العاطفة" },
  "cultural": { en: "Cultural semiotics", ar: "السيميائيات الثقافية" },
};

const CDA_VARIANTS = ["fairclough", "van_dijk", "wodak", "machin_mayr"] as const;


// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------

export function VisionView() {
  const cid = useApp((s) => s.activeCorpusId);
  const lang = useUI((s) => s.lang);
  const queryClient = useQueryClient();
  const [activeSetId, setActiveSetId] = useState<string | null>(null);
  const [selectedImageId, setSelectedImageId] = useState<string | null>(null);
  const [showNewSetForm, setShowNewSetForm] = useState(false);
  const [newSetName, setNewSetName] = useState("");
  const [actionMsg, setActionMsg] = useState("");

  // List image sets for the active corpus.
  const setsQuery = useQuery({
    queryKey: ["image-sets", cid],
    queryFn: () => api.listImageSets(cid!),
    enabled: !!cid,
  });

  // Auto-select the first set when the list loads, so the user doesn't
  // see an empty grid with no explanation.
  if (setsQuery.data && setsQuery.data.length > 0 && !activeSetId) {
    setActiveSetId(setsQuery.data[0].id);
  }

  if (!cid) {
    return (
      <div className="empty-state">
        <h2>{t(lang, "vision_select_corpus_h")}</h2>
        <p className="hint">{t(lang, "vision_select_corpus_hint")}</p>
      </div>
    );
  }

  const onCreateSet = async () => {
    if (!newSetName.trim()) return;
    try {
      const created = await api.createImageSet(cid, newSetName.trim());
      setNewSetName("");
      setShowNewSetForm(false);
      setActiveSetId(created.id);
      setActionMsg("");
      // Invalidate the list so the new set appears at the top.
      queryClient.invalidateQueries({ queryKey: ["image-sets", cid] });
    } catch (e) {
      // Issue 21 fix: surface creation failures (dialog stays open) —
      // inline message + Smart Troubleshooting instead of alert().
      const msg = reportVisionError(e, `/corpora/${cid}/image-sets`, "Create image set");
      setActionMsg(`${t(lang, "vision_create_failed")}: ${msg}`);
    }
  };

  const onDeleteSet = async () => {
    if (!activeSetId) return;
    const name = setsQuery.data?.find((s) => s.id === activeSetId)?.name ?? "";
    if (!window.confirm(`${t(lang, "vision_delete_confirm_set")}\n\n${name}`)) return;
    try {
      await api.deleteImageSet(activeSetId);
      setSelectedImageId(null);
      setActiveSetId(null);
      setActionMsg(t(lang, "vision_deleted"));
      queryClient.invalidateQueries({ queryKey: ["image-sets", cid] });
    } catch (e) {
      const msg = reportVisionError(e, `/image-sets/${activeSetId}`, "Delete image set");
      setActionMsg(`${t(lang, "vision_delete_failed")}: ${msg}`);
    }
  };

  const exportSet = async (fmt: string) => {
    if (!activeSetId) return;
    const name = setsQuery.data?.find((s) => s.id === activeSetId)?.name ?? "image-set";
    const slug = name.replace(/[^\w-]+/g, "-").slice(0, 40) || "image-set";
    await exportWithFeedback(
      () => api.exportImageSet(activeSetId, fmt as "xlsx"),
      `image-set-${slug}.${fmt}`,
      (msg) => setActionMsg(msg),
    );
  };

  return (
    <div className="vision-view">
      <div className="vision-toolbar">
        <label className="vision-set-picker">
          <span className="vision-set-picker-label">{t(lang, "vision_set_label")}</span>
          <select
            value={activeSetId ?? ""}
            onChange={(e) => {
              setActiveSetId(e.target.value || null);
              setSelectedImageId(null);
            }}
          >
            <option value="">{t(lang, "vision_select")}</option>
            {setsQuery.data?.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.image_count})
              </option>
            ))}
          </select>
        </label>
        <button
          className="btn-secondary"
          onClick={() => setShowNewSetForm((v) => !v)}
        >
          {showNewSetForm ? t(lang, "vision_cancel") : t(lang, "vision_new_set")}
        </button>
        {activeSetId && (
          <>
            <ExportButtonVision onExport={exportSet} />
            <button className="btn-danger" onClick={onDeleteSet}>
              {t(lang, "vision_delete_set")}
            </button>
          </>
        )}
      </div>

      {actionMsg && <div className="hint vision-action-msg">{actionMsg}</div>}

      {showNewSetForm && (
        <div className="vision-new-set-form">
          <input
            type="text"
            value={newSetName}
            onChange={(e) => setNewSetName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onCreateSet()}
            placeholder={t(lang, "vision_set_name_placeholder")}
            autoFocus
          />
          <button className="btn-primary" onClick={onCreateSet} disabled={!newSetName.trim()}>
            {t(lang, "vision_create")}
          </button>
        </div>
      )}

      {setsQuery.isLoading && <div className="hint">{t(lang, "vision_loading_sets")}</div>}
      {setsQuery.error && (
        <div className="uploader-status error">
          {t(lang, "vision_failed_sets")}: {(setsQuery.error as Error).message}
        </div>
      )}
      {setsQuery.data && setsQuery.data.length === 0 && !showNewSetForm && (
        <div className="empty-state">
          <h2>{t(lang, "vision_no_sets_h")}</h2>
          <p className="hint">{t(lang, "vision_no_sets_hint")}</p>
        </div>
      )}

      {activeSetId && (
        <ImageSetWorkspace
          setId={activeSetId}
          selectedImageId={selectedImageId}
          onSelectImage={setSelectedImageId}
        />
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// ExportButtonVision — ExportButton wired to the image-set export endpoint
// ---------------------------------------------------------------------------

function ExportButtonVision({ onExport }: { onExport: (fmt: string) => void }) {
  return <ExportButton label="Export" onExport={(fmt) => onExport(fmt)} />;
}


// ---------------------------------------------------------------------------
// ImageSetWorkspace — owns the upload dropzone + grid + analysis drawer
// ---------------------------------------------------------------------------

function ImageSetWorkspace({
  setId,
  selectedImageId,
  onSelectImage,
}: {
  setId: string;
  selectedImageId: string | null;
  onSelectImage: (id: string | null) => void;
}) {
  const cid = useApp((s) => s.activeCorpusId)!;
  const lang = useUI((s) => s.lang);
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const imagesQuery = useQuery({
    queryKey: ["images", setId],
    queryFn: () => api.listImages(setId),
  });

  const uploadMutation = useMutation({
    mutationFn: ({ files, caption }: { files: File[]; caption: string }) =>
      api.uploadImages(setId, files, caption || undefined),
    onSuccess: () => {
      // Refresh both the image list and the image-set list (the latter
      // because image_count changes).
      queryClient.invalidateQueries({ queryKey: ["images", setId] });
      queryClient.invalidateQueries({ queryKey: ["image-sets", cid] });
    },
  });

  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [caption, setCaption] = useState("");
  const [isDragOver, setIsDragOver] = useState(false);

  const onPickFiles = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const arr = Array.from(files).filter((f) => f.type.startsWith("image/"));
    setPendingFiles((prev) => [...prev, ...arr]);
  };

  const onUpload = async () => {
    if (pendingFiles.length === 0) return;
    try {
      await uploadMutation.mutateAsync({ files: pendingFiles, caption });
      setPendingFiles([]);
      setCaption("");
    } catch (e) {
      reportVisionError(e, `/image-sets/${setId}/images`, "Image upload");
    }
  };

  const openFilePicker = () => fileInputRef.current?.click();

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    onPickFiles(e.dataTransfer.files);
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openFilePicker();
    }
  };

  return (
    <div className="vision-workspace">
      <div
        className={clsx("dropzone", { "drag-over": isDragOver, "busy": uploadMutation.isPending })}
        onClick={openFilePicker}
        onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={handleDrop}
        role="button"
        tabIndex={0}
        onKeyDown={handleKeyDown}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={IMAGE_ACCEPT}
          onChange={(e) => onPickFiles(e.target.files)}
          style={{ position: "absolute", width: 0, height: 0, opacity: 0, pointerEvents: "none" }}
          aria-hidden="true"
        />
        <div className="dropzone-icon">{"\u2191"}</div>
        <div className="dropzone-label">{t(lang, "vision_drop_label")}</div>
      </div>

      {pendingFiles.length > 0 && (
        <div className="vision-pending-upload">
          <div className="vision-pending-header">
            <strong>{pendingFiles.length} {t(lang, "vision_ready_upload")}</strong>
            <button className="btn-small" onClick={() => setPendingFiles([])}>{t(lang, "vision_clear")}</button>
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
          <button
            className="btn-primary"
            onClick={onUpload}
            disabled={uploadMutation.isPending}
          >
            {uploadMutation.isPending
              ? t(lang, "vision_uploading")
              : tf(lang, "vision_upload_btn", { n: pendingFiles.length })}
          </button>
          {uploadMutation.error && (
            <div className="uploader-status error">
              {t(lang, "vision_upload_failed")}: {(uploadMutation.error as Error).message}
            </div>
          )}
        </div>
      )}

      <h3 className="vision-section-heading">{t(lang, "vision_images_in_set")}</h3>
      {imagesQuery.isLoading && <div className="hint">{t(lang, "vision_loading_images")}</div>}
      {imagesQuery.error && (
        <div className="uploader-status error">
          {t(lang, "vision_failed_images")}: {(imagesQuery.error as Error).message}
        </div>
      )}
      {imagesQuery.data && imagesQuery.data.length === 0 && (
        <div className="hint">{t(lang, "vision_no_images")}</div>
      )}
      {imagesQuery.data && imagesQuery.data.length > 0 && (
        <div className="vision-grid" role="list">
          {imagesQuery.data.map((img) => (
            <ImageGridItem
              key={img.id}
              image={img}
              setId={setId}
              selected={img.id === selectedImageId}
              onSelect={() => onSelectImage(img.id === selectedImageId ? null : img.id)}
              onDeleted={() => onSelectImage(null)}
            />
          ))}
        </div>
      )}

      {selectedImageId && (
        <AnalysisDrawer imageId={selectedImageId} />
      )}

      {selectedImageId && (
        <DiscourseLensesPanel imageId={selectedImageId} />
      )}

      {selectedImageId && (
        <AlignmentPanel imageId={selectedImageId} />
      )}

      <BatchRunnerPanel isetId={setId} />
      <BatchViewPanel isetId={setId} />
    </div>
  );
}


// ---------------------------------------------------------------------------
// ImageGridItem — one card in the thumbnail grid
// ---------------------------------------------------------------------------

function ImageGridItem({
  image,
  setId,
  selected,
  onSelect,
  onDeleted,
}: {
  image: ImageRecord;
  setId: string;
  selected: boolean;
  onSelect: () => void;
  onDeleted: () => void;
}) {
  const lang = useUI((s) => s.lang);
  const cid = useApp((s) => s.activeCorpusId)!;
  const queryClient = useQueryClient();
  const thumbQuery = useQuery({
    queryKey: ["image-thumbnail", image.id],
    queryFn: () => api.fetchImageThumbnailUrl(image.id),
    staleTime: Infinity,
    retry: false,
  });

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteImage(image.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["images", setId] });
      queryClient.invalidateQueries({ queryKey: ["image-sets", cid] });
      onDeleted();
    },
  });

  const onDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!window.confirm(t(lang, "vision_delete_confirm_image"))) return;
    deleteMutation.mutate();
  };

  return (
    <div className={clsx("vision-grid-item-wrap", { selected })}>
      <button
        className={clsx("vision-grid-item", { selected })}
        onClick={onSelect}
        role="listitem"
        aria-pressed={selected}
        title={image.filename}
      >
        <div className="vision-grid-thumb" aria-hidden="true">
          {thumbQuery.data ? (
            <img
              src={thumbQuery.data}
              alt=""
              className="vision-grid-thumb-img"
              style={{ width: "100%", height: "100%", objectFit: "cover" }}
            />
          ) : (
            <span className="vision-grid-thumb-icon">{"\u25A3"}</span>
          )}
        </div>
        <div className="vision-grid-meta">
          <div className="vision-grid-filename" title={image.filename}>{image.filename}</div>
          <div className="vision-grid-dims">
            {image.width}×{image.height} · {formatBytes(image.size_bytes)}
          </div>
          {image.caption && (
            <div className="vision-grid-caption" title={image.caption}>{image.caption}</div>
          )}
        </div>
      </button>
      <button
        className="vision-grid-delete"
        onClick={onDelete}
        disabled={deleteMutation.isPending}
        title={t(lang, "vision_delete_image")}
        aria-label={t(lang, "vision_delete_image")}
      >
        ×
      </button>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Vision model picker — capability-aware auto pick or explicit model
// ---------------------------------------------------------------------------

function VisionModelSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const lang = useUI((s) => s.lang);
  const modelsQuery = useQuery({
    queryKey: ["vision-models"],
    queryFn: () => api.listModels("ollama"),
    staleTime: 30_000,
    retry: false,
  });
  const models = modelsQuery.data?.models ?? [];
  return (
    <label className="vision-model-select">
      <span>{t(lang, "vision_vlm_model_label")}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{t(lang, "vision_vlm_auto")}</option>
        {models.map((m) => (
          <option key={m} value={m}>{m}</option>
        ))}
      </select>
    </label>
  );
}


// ---------------------------------------------------------------------------
// AnalysisDrawer — cached analysis for the selected image
// ---------------------------------------------------------------------------

function AnalysisDrawer({ imageId }: { imageId: string }) {
  const lang = useUI((s) => s.lang);
  const queryClient = useQueryClient();
  const analysisQuery = useQuery({
    queryKey: ["image-analysis", imageId],
    queryFn: () => api.getImageAnalysis(imageId),
  });

  const [describeMsg, setDescribeMsg] = useState("");
  const [visionModel, setVisionModel] = useState("");
  const describeMutation = useMutation({
    mutationFn: () => api.describeImage(imageId, visionModel || undefined),
    onSuccess: (data) => {
      setDescribeMsg(data.cached ? t(lang, "vision_cached_desc") : t(lang, "vision_desc_generated"));
      queryClient.invalidateQueries({ queryKey: ["image-analysis", imageId] });
      queryClient.invalidateQueries({ queryKey: ["batch-analysis"] });
    },
    onError: (e: Error) => {
      const msg = reportVisionError(e, `/images/${imageId}/describe`, "Vision-LM describe");
      setDescribeMsg(`${t(lang, "vision_failed")}: ${msg}`);
    },
  });

  const [showVisualGrammar, setShowVisualGrammar] = useState(false);
  const vgQuery = useQuery({
    queryKey: ["visual-grammar", imageId],
    queryFn: () => api.getVisualGrammar(imageId),
    enabled: showVisualGrammar,
  });

  if (analysisQuery.isLoading) return <div className="hint">{t(lang, "vision_analysing")}</div>;
  if (analysisQuery.error) {
    return (
      <div className="uploader-status error">
        {(analysisQuery.error as Error).message}
      </div>
    );
  }

  const a: ImageAnalysis = analysisQuery.data!;

  return (
    <div className="vision-analysis-drawer">
      <h3 className="vision-section-heading">
        {t(lang, "vision_analysis_of")} <code>{a.filename}</code>
      </h3>
      <div className="result-meta">
        {t(lang, "vision_dimensions")}: <strong>{a.dimensions}</strong>
        {a.caption && <> · {t(lang, "vision_caption")}: <strong>{a.caption}</strong></>}
      </div>

      <div className="vision-describe-row">
        <VisionModelSelect value={visionModel} onChange={setVisionModel} />
        <button
          className="btn-secondary"
          onClick={() => describeMutation.mutate()}
          disabled={describeMutation.isPending}
        >
          {describeMutation.isPending ? t(lang, "vision_describing") : t(lang, "vision_describe_btn")}
        </button>
        {describeMsg && <span className="hint">{describeMsg}</span>}
      </div>

      <div className="vision-analysis-cols">
        <AnalysisCol title={t(lang, "vision_col_ocr")}>
          {a.analysis.ocr.text ? (
            <>
              <pre className="vision-ocr-text">{a.analysis.ocr.text}</pre>
              <div className="hint">
                {t(lang, "vision_engine")}: <code>{a.analysis.ocr.engine}</code> ·{" "}
                {t(lang, "vision_confidence")}: {(a.analysis.ocr.confidence * 100).toFixed(0)}% ·{" "}
                {t(lang, "vision_words")}: {a.analysis.ocr.word_count} ·{" "}
                {t(lang, "vision_language")}: <code>{a.analysis.ocr.language}</code>
              </div>
            </>
          ) : (
            <div className="hint">{t(lang, "vision_no_text")}</div>
          )}
        </AnalysisCol>

        <AnalysisCol title={t(lang, "vision_col_colours")}>
          <div className="vision-colour-swatches">
            {a.analysis.colours.dominant_colours.slice(0, 8).map((c, i) => (
              <div
                key={i}
                className="vision-colour-swatch"
                style={{ backgroundColor: c.hex }}
                title={`${c.hex} · ${(c.percent * 100).toFixed(1)}%`}
              >
                <span className="vision-colour-pct">{(c.percent * 100).toFixed(0)}%</span>
              </div>
            ))}
          </div>
          <div className="hint">
            {t(lang, "vision_brightness")}: {a.analysis.colours.brightness.toFixed(2)} ·{" "}
            {t(lang, "vision_contrast")}: {a.analysis.colours.contrast.toFixed(2)} ·{" "}
            {t(lang, "vision_saturation")}: {a.analysis.colours.saturation.toFixed(2)} ·{" "}
            {t(lang, "vision_warm_cold")}: {a.analysis.colours.warm_cold_balance.toFixed(2)}
          </div>
          {a.analysis.colours.colour_symbolism_notes.length > 0 && (
            <ul className="vision-symbolism-notes">
              {a.analysis.colours.colour_symbolism_notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          )}
        </AnalysisCol>

        <AnalysisCol title={t(lang, "vision_col_composition")}>
          <div className="hint">
            {t(lang, "vision_visual_balance")}: <strong>{a.analysis.composition.visual_balance.toFixed(2)}</strong> ·{" "}
            {t(lang, "vision_framing_balance")}: <strong>{a.analysis.composition.framing_balance.toFixed(2)}</strong>
          </div>
          <div className="hint">
            {t(lang, "vision_salience")}: ({a.analysis.composition.salience_centre[0].toFixed(2)}, {a.analysis.composition.salience_centre[1].toFixed(2)})
          </div>
          {Object.entries(a.analysis.composition.information_value).length > 0 && (
            <div className="vision-info-value">
              <strong>{t(lang, "vision_info_value")}:</strong>
              <ul>
                {Object.entries(a.analysis.composition.information_value).map(([k, v]) => (
                  <li key={k}><code>{k}</code>: {(v * 100).toFixed(0)}%</li>
                ))}
              </ul>
            </div>
          )}
        </AnalysisCol>
      </div>

      <div className="vision-vg-section">
        <button
          className="btn-secondary"
          onClick={() => setShowVisualGrammar((v) => !v)}
          aria-expanded={showVisualGrammar}
        >
          {showVisualGrammar ? t(lang, "vision_vg_hide") : t(lang, "vision_vg_run")}
        </button>
        {showVisualGrammar && (
          <>
            {vgQuery.isLoading && <div className="hint">{t(lang, "vision_analysing")}</div>}
            {vgQuery.error && (
              <div className="uploader-status error">
                {t(lang, "vision_vg_failed")}: {(vgQuery.error as Error).message}
              </div>
            )}
            {vgQuery.data && (
              <VisualGrammarPanel data={vgQuery.data} />
            )}
          </>
        )}
      </div>
    </div>
  );
}


function AnalysisCol({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="vision-analysis-col">
      <h4 className="vision-col-heading">{title}</h4>
      {children}
    </div>
  );
}


// ---------------------------------------------------------------------------
// VisualGrammarPanel — renders the result of /images/{img_id}/visual-grammar
// ---------------------------------------------------------------------------

function VisualGrammarPanel({ data }: { data: VisualGrammarResult }) {
  const lang = useUI((s) => s.lang);
  return (
    <div className="vision-vg-panel">
      <div className="result-meta">
        {t(lang, "vision_framework")}: <strong>{data.framework}</strong>
      </div>
      <div className="vision-vg-scores">
        <span>{t(lang, "vision_representational")}: <strong>{data.scores.representational.claim_count} {t(lang, "vision_claims")}</strong> ({t(lang, "vision_avg_conf")} {data.scores.representational.avg_confidence.toFixed(2)})</span>
        <span>{t(lang, "vision_interactive")}: <strong>{data.scores.interactive.claim_count} {t(lang, "vision_claims")}</strong> ({t(lang, "vision_avg_conf")} {data.scores.interactive.avg_confidence.toFixed(2)})</span>
        <span>{t(lang, "vision_compositional")}: <strong>{data.scores.compositional.claim_count} {t(lang, "vision_claims")}</strong> ({t(lang, "vision_avg_conf")} {data.scores.compositional.avg_confidence.toFixed(2)})</span>
      </div>
      {data.claims.length === 0 ? (
        <div className="hint">{t(lang, "vision_vg_no_claims")}</div>
      ) : (
        <ul className="vision-vg-claims">
          {data.claims.map((c, i) => (
            <li key={i} className="vision-vg-claim">
              <div className="vision-vg-claim-meta">
                <span className="vision-vg-metafunction">{c.metafunction}</span>
                <span className="vision-vg-category">{c.category}</span>
                <span className="vision-vg-confidence">{(c.confidence * 100).toFixed(0)}%</span>
              </div>
              <p className="vision-vg-claim-text">{c.claim}</p>
              {c.evidence.length > 0 && (
                <ul className="vision-vg-evidence">
                  {c.evidence.map((e, j) => <li key={j}><code>{e}</code></li>)}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// DiscourseLensesPanel — the 8 Phase-5 discourse routes, reachable at last
// (v1.2.0). Heuristic or vision-LM mode, framework dropdown fed by the
// engine's /frameworks catalogue, provenance badges on every claim.
// ---------------------------------------------------------------------------

function DiscourseLensesPanel({ imageId }: { imageId: string }) {
  const lang = useUI((s) => s.lang);
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [route, setRoute] = useState<string>("social-semiotic");
  const [cdaVariant, setCdaVariant] = useState<string>("fairclough");
  const [mode, setMode] = useState<"heuristic" | "llm">("heuristic");
  const [visionModel, setVisionModel] = useState("");
  const [result, setResult] = useState<DiscourseResult | null>(null);
  const [running, setRunning] = useState(false);
  const [errMsg, setErrMsg] = useState("");

  const run = async () => {
    setRunning(true);
    setErrMsg("");
    try {
      const r = await api.runDiscourseLens(imageId, route, {
        mode,
        model: visionModel || null,
        cdaFramework: cdaVariant,
      });
      setResult(r);
      queryClient.invalidateQueries({ queryKey: ["batch-analysis"] });
    } catch (e) {
      const msg = reportVisionError(e, `/images/${imageId}/${route}`, `Discourse lens: ${route}`);
      setErrMsg(`${t(lang, "vision_lens_failed")}: ${msg}`);
      setResult(null);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="vision-lenses-panel">
      <div className="vision-batch-header">
        <h3 className="vision-section-heading">{t(lang, "vision_lenses_h")}</h3>
        <button className="btn-secondary" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          {open ? t(lang, "vision_hide_batch") : t(lang, "vision_lens_run")}
        </button>
      </div>
      {open && (
        <>
          <p className="hint">{t(lang, "vision_lenses_intro")}</p>
          <div className="vision-lenses-controls">
            <label className="vision-align-mode">
              <span>{t(lang, "vision_lens_framework")}</span>
              <select value={route} onChange={(e) => setRoute(e.target.value)}>
                {LENS_ROUTES.map((l) => (
                  <option key={l.route} value={l.route}>
                    {LENS_NAMES[l.route]?.[lang] ?? l.route}
                  </option>
                ))}
              </select>
            </label>
            {route === "cda" && (
              <label className="vision-align-mode">
                <span>{t(lang, "vision_lens_cda_variant")}</span>
                <select value={cdaVariant} onChange={(e) => setCdaVariant(e.target.value)}>
                  {CDA_VARIANTS.map((v) => <option key={v} value={v}>{v}</option>)}
                </select>
              </label>
            )}
            <label className="vision-align-mode">
              <span>{t(lang, "vision_align_mode")}</span>
              <select value={mode} onChange={(e) => setMode(e.target.value as "heuristic" | "llm")}>
                <option value="heuristic">{t(lang, "vision_mode_heuristic")}</option>
                <option value="llm">{t(lang, "vision_mode_llm")}</option>
              </select>
            </label>
            {mode === "llm" && <VisionModelSelect value={visionModel} onChange={setVisionModel} />}
            <button className="btn-primary" onClick={run} disabled={running}>
              {running ? t(lang, "vision_lens_running") : t(lang, "vision_lens_run")}
            </button>
          </div>

          {errMsg && <div className="uploader-status error">{errMsg}</div>}
          {result && <LensResult result={result} />}
          {!result && !running && !errMsg && (
            <div className="hint">{t(lang, "vision_lenses_disabled")}</div>
          )}
        </>
      )}
    </div>
  );
}


function LensResult({ result }: { result: DiscourseResult }) {
  const lang = useUI((s) => s.lang);
  const mode = result.provenance?.mode ?? "heuristic";
  const isLlm = mode === "llm";
  return (
    <div className="vision-lens-result">
      <div className="result-meta">
        <span className={clsx("vision-mode-badge", isLlm ? "llm" : "heuristic")}>
          {isLlm ? t(lang, "vision_lens_llm_badge") : t(lang, "vision_lens_heuristic_badge")}
        </span>
        {" · "}
        {t(lang, "vision_framework")}: <strong>{result.framework}</strong>
        {result.provenance?.model && (
          <> · {t(lang, "vision_model")}: <strong>{result.provenance.model}</strong></>
        )}
      </div>
      {result.fallback_reason && (
        <div className="hint vision-align-fallback">{t(lang, "vision_lens_fallback")}</div>
      )}
      {result.person_descriptive_redacted && (
        <div className="hint vision-align-redacted">{t(lang, "vision_redacted")}</div>
      )}
      {result.summary && <p className="vision-lens-summary">{result.summary}</p>}
      {(result.claims?.length ?? 0) === 0 ? (
        <div className="hint">{t(lang, "vision_lens_no_claims")}</div>
      ) : (
        <ul className="vision-vg-claims">
          {result.claims.map((c: DiscourseClaim, i: number) => (
            <li key={i} className="vision-vg-claim">
              <div className="vision-vg-claim-meta">
                <span className="vision-vg-category">{c.category}</span>
                <span className="vision-vg-confidence">{(c.confidence * 100).toFixed(0)}%</span>
              </div>
              <p className="vision-vg-claim-text">{c.claim}</p>
              {c.evidence.length > 0 && (
                <ul className="vision-vg-evidence">
                  {c.evidence.map((e, j) => <li key={j}><code>{e}</code></li>)}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// AlignmentPanel — image-text alignment inspector (with model picker)
// ---------------------------------------------------------------------------

type AlignMode = "heuristic" | "llm" | "both";

function AlignmentPanel({ imageId }: { imageId: string }) {
  const lang = useUI((s) => s.lang);
  const [text, setText] = useState("");
  const [mode, setMode] = useState<AlignMode>("heuristic");
  const [visionModel, setVisionModel] = useState("");
  const [submitted, setSubmitted] = useState<{ text: string; mode: AlignMode } | null>(null);

  const heuristicQuery = useQuery({
    queryKey: ["align", imageId, submitted?.text, "heuristic"],
    queryFn: () => api.alignImageText(imageId, submitted!.text, "heuristic"),
    enabled: !!submitted && (submitted.mode === "heuristic" || submitted.mode === "both"),
  });

  // v1.2.0: no hardcoded moondream — empty model = engine-side
  // capability-aware auto-pick.
  const llmQuery = useQuery({
    queryKey: ["align", imageId, submitted?.text, "llm", visionModel],
    queryFn: () => api.alignImageText(imageId, submitted!.text, "llm", visionModel || undefined),
    enabled: !!submitted && (submitted.mode === "llm" || submitted.mode === "both"),
  });

  const onAlign = () => {
    if (!text.trim()) return;
    setSubmitted({ text: text.trim(), mode });
  };

  return (
    <div className="vision-alignment-panel">
      <h3 className="vision-section-heading">{t(lang, "vision_alignment_h")}</h3>
      <div className="vision-alignment-input">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) onAlign();
          }}
          placeholder={t(lang, "vision_align_placeholder")}
          rows={3}
        />
        <div className="vision-alignment-controls">
          <label className="vision-align-mode">
            <span>{t(lang, "vision_align_mode")}</span>
            <select value={mode} onChange={(e) => setMode(e.target.value as AlignMode)}>
              <option value="heuristic">{t(lang, "vision_mode_heuristic")}</option>
              <option value="llm">{t(lang, "vision_mode_llm")}</option>
              <option value="both">{t(lang, "vision_mode_both")}</option>
            </select>
          </label>
          {mode !== "heuristic" && (
            <VisionModelSelect value={visionModel} onChange={setVisionModel} />
          )}
          <button
            className="btn-primary"
            onClick={onAlign}
            disabled={!text.trim() || heuristicQuery.isFetching || llmQuery.isFetching}
          >
            {(heuristicQuery.isFetching || llmQuery.isFetching) ? t(lang, "vision_aligning") : t(lang, "vision_align_btn")}
          </button>
        </div>
        <div className="hint">{t(lang, "vision_align_hint")}</div>
      </div>

      {submitted && submitted.mode === "heuristic" && (
        <AlignmentResultView title={t(lang, "vision_heuristic_result")} query={heuristicQuery} />
      )}

      {submitted && submitted.mode === "llm" && (
        <AlignmentResultView title={t(lang, "vision_llm_result")} query={llmQuery} />
      )}

      {submitted && submitted.mode === "both" && (
        <div className="vision-alignment-both">
          <AlignmentResultView title={t(lang, "vision_heuristic_result")} query={heuristicQuery} />
          <AlignmentResultView title={t(lang, "vision_llm_result")} query={llmQuery} />
        </div>
      )}
    </div>
  );
}


function AlignmentResultView({
  title,
  query,
}: {
  title: string;
  query: ReturnType<typeof useQuery<any>>;
}) {
  const lang = useUI((s) => s.lang);
  if (query.isLoading) return <div className="hint">{t(lang, "vision_running")} {title.toLowerCase()}…</div>;
  if (query.error) {
    return (
      <div className="uploader-status error">
        {title} {t(lang, "vision_failed")}: {(query.error as Error).message}
      </div>
    );
  }
  if (!query.data) return null;

  const data = query.data;
  return (
    <div className="vision-alignment-result">
      <h4 className="vision-align-result-heading">{title}</h4>
      <div className="result-meta">
        {t(lang, "vision_method")}: <strong>{data.method}</strong>
        {data.provenance && (
          <> · {t(lang, "vision_align_mode")}: <strong>{data.provenance.mode}</strong>
          {data.provenance.model && <> · {t(lang, "vision_model")}: <strong>{data.provenance.model}</strong></>}
          </>
        )}
        {data.fallback_reason && (
          <div className="hint vision-align-fallback">{data.fallback_reason}</div>
        )}
        {data.person_descriptive_redacted && (
          <div className="hint vision-align-redacted">{t(lang, "vision_redacted")}</div>
        )}
      </div>

      {data.alignments.length === 0 ? (
        <div className="hint">{t(lang, "vision_no_alignments")}</div>
      ) : (
        <ul className="vision-align-list">
          {data.alignments.map((a: any, i: number) => (
            <li key={i} className="vision-align-item">
              <div className="vision-align-item-header">
                <span className="vision-align-span">"{a.span_text}"</span>
                <span className="vision-align-confidence">
                  {(a.confidence * 100).toFixed(0)}%
                </span>
              </div>
              <div className="vision-align-region">
                <strong>{t(lang, "vision_region")}:</strong> {a.region_descriptor}
              </div>
              <div className="vision-align-reason">
                <strong>{t(lang, "vision_reason")}:</strong> {a.match_reason}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// BatchRunnerPanel — analyse the whole set server-side (v1.2.0)
// ---------------------------------------------------------------------------

function BatchRunnerPanel({ isetId }: { isetId: string }) {
  const lang = useUI((s) => s.lang);
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [action, setAction] = useState<"describe" | "all">("describe");
  const [visionModel, setVisionModel] = useState("");
  const [startErr, setStartErr] = useState("");

  const statusQuery = useQuery({
    queryKey: ["batch-run", isetId],
    queryFn: () => api.getBatchStatus(isetId),
    enabled: open,
    refetchInterval: (query: any) => (query?.state?.data?.running ? 1000 : false),
  });

  const startMutation = useMutation({
    mutationFn: () =>
      api.runBatch(isetId, { action, model: visionModel || null }),
    onSuccess: () => {
      setStartErr("");
      queryClient.invalidateQueries({ queryKey: ["batch-run", isetId] });
    },
    onError: (e: Error) => {
      const msg = reportVisionError(e, `/image-sets/${isetId}/run-batch`, "Batch runner");
      setStartErr(msg);
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => api.cancelBatch(isetId),
  });

  const st = statusQuery.data;
  const finished = st && !st.running;

  const onOpen = (v: boolean) => {
    setOpen(v);
    if (!v) {
      // Refresh aggregated views when leaving the runner.
      queryClient.invalidateQueries({ queryKey: ["batch-analysis", isetId] });
      queryClient.invalidateQueries({ queryKey: ["image-analysis"] });
    }
  };

  return (
    <div className="vision-batchrun-panel">
      <div className="vision-batch-header">
        <h3 className="vision-section-heading">{t(lang, "vision_batchrun_h")}</h3>
        <button className="btn-secondary" onClick={() => onOpen(!open)} aria-expanded={open}>
          {open ? t(lang, "vision_hide_batch") : t(lang, "vision_batchrun_start")}
        </button>
      </div>
      {open && (
        <>
          <p className="hint">{t(lang, "vision_batchrun_intro")}</p>
          <div className="vision-lenses-controls">
            <label className="vision-align-mode">
              <span>{t(lang, "vision_batchrun_action")}</span>
              <select value={action} onChange={(e) => setAction(e.target.value as "describe" | "all")}>
                <option value="describe">{t(lang, "vision_batchrun_describe")}</option>
                <option value="all">{t(lang, "vision_batchrun_all")}</option>
              </select>
            </label>
            <VisionModelSelect value={visionModel} onChange={setVisionModel} />
            <button
              className="btn-primary"
              onClick={() => startMutation.mutate()}
              disabled={startMutation.isPending || !!st?.running}
            >
              {t(lang, "vision_batchrun_start")}
            </button>
            {st?.running && (
              <button className="btn-secondary" onClick={() => cancelMutation.mutate()}>
                {t(lang, "vision_batchrun_cancel")}
              </button>
            )}
          </div>

          {startErr && <div className="uploader-status error">{startErr}</div>}
          {statusQuery.isLoading && <div className="hint">{t(lang, "vision_batchrun_progressing")}</div>}

          {st && (
            <div className="vision-batchrun-status">
              {st.running ? (
                <div className="hint">
                  {tf(lang, "vision_batchrun_running", { done: st.done, total: st.total })}
                </div>
              ) : st.status === "done" ? (
                <div className="hint">
                  {tf(lang, "vision_batchrun_done", { done: st.done, total: st.total })}
                </div>
              ) : st.status === "cancelled" ? (
                <div className="hint">
                  {tf(lang, "vision_batchrun_cancelled", { done: st.done, total: st.total })}
                </div>
              ) : st.status === "error" ? (
                <div className="uploader-status error">{String((st as any).error ?? "")}</div>
              ) : null}
              {finished && st.errors.length > 0 && (
                <div className="uploader-status error">
                  {tf(lang, "vision_batchrun_errors", { n: st.errors.length })}
                  <ul>
                    {st.errors.slice(0, 8).map((e: any, i: number) => (
                      <li key={i}><code>{e.image}</code> ({e.action}): {e.error}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// BatchViewPanel — recurring themes + OCR frequency across an image set
// (read-only aggregation of cached analysis)
// ---------------------------------------------------------------------------

function BatchViewPanel({ isetId }: { isetId: string }) {
  const lang = useUI((s) => s.lang);
  const [enabled, setEnabled] = useState(false);

  const batchQuery = useQuery({
    queryKey: ["batch-analysis", isetId],
    queryFn: () => api.getBatchAnalysis(isetId),
    enabled,
  });

  return (
    <div className="vision-batch-panel">
      <div className="vision-batch-header">
        <h3 className="vision-section-heading">{t(lang, "vision_batch_h")}</h3>
        <button
          className="btn-secondary"
          onClick={() => setEnabled((v) => !v)}
          aria-expanded={enabled}
        >
          {enabled ? t(lang, "vision_hide_batch") : t(lang, "vision_show_batch")}
        </button>
      </div>

      {enabled && batchQuery.isLoading && <div className="hint">{t(lang, "vision_loading_batch")}</div>}
      {enabled && batchQuery.error && (
        <div className="uploader-status error">
          {t(lang, "vision_failed_batch")}: {(batchQuery.error as Error).message}
        </div>
      )}
      {enabled && batchQuery.data && <BatchViewContent data={batchQuery.data} />}
    </div>
  );
}


function BatchViewContent({ data }: { data: BatchAnalysisResult }) {
  const lang = useUI((s) => s.lang);
  return (
    <div className="vision-batch-content">
      <div className="result-meta">
        {data.image_count} {t(lang, "vision_batch_images")} · {data.images_with_vlm}{" "}
        {t(lang, "vision_batch_with_vlm")} · {data.images_with_discourse}{" "}
        {t(lang, "vision_batch_with_discourse")}
      </div>

      {data.note && <div className="hint vision-batch-note">{data.note}</div>}

      <div className="vision-batch-cols">
        {/* Recurring themes */}
        <div className="vision-batch-col">
          <h4 className="vision-col-heading">{t(lang, "vision_themes_h")}</h4>
          {data.recurring_themes.length === 0 ? (
            <div className="hint">{t(lang, "vision_no_themes")}</div>
          ) : (
            data.recurring_themes.map((th) => (
              <div key={th.framework} className="vision-batch-theme">
                <div className="vision-batch-theme-header">
                  <span className="vision-batch-framework">{th.framework}</span>
                  <span className="vision-batch-total">{th.total_claims} {t(lang, "vision_claims")}</span>
                </div>
                <ul className="vision-batch-categories">
                  {th.categories.map((c) => (
                    <li key={c.category} className="vision-batch-category">
                      <span className="vision-batch-cat-name">{c.category}</span>
                      <span className="vision-batch-cat-count">{c.count}</span>
                      {c.example_claim && (
                        <div className="vision-batch-cat-example">{c.example_claim}</div>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))
          )}
        </div>

        {/* OCR frequency */}
        <div className="vision-batch-col">
          <h4 className="vision-col-heading">{t(lang, "vision_ocr_freq_h")}</h4>
          {data.ocr_frequency.length === 0 ? (
            <div className="hint">{t(lang, "vision_no_ocr")}</div>
          ) : (
            <div className="vision-batch-freq-list">
              {data.ocr_frequency.slice(0, 30).map((f) => (
                <div key={f.word} className="vision-batch-freq-item">
                  <span className="vision-batch-freq-word">{f.word}</span>
                  <span className="vision-batch-freq-count">{f.count}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* VLM descriptions */}
        <div className="vision-batch-col">
          <h4 className="vision-col-heading">{t(lang, "vision_desc_h")}</h4>
          {data.descriptions.length === 0 ? (
            <div className="hint">{t(lang, "vision_no_descs")}</div>
          ) : (
            <ul className="vision-batch-desc-list">
              {data.descriptions.map((d) => (
                <li key={d.image_id} className="vision-batch-desc-item">
                  <div className="vision-batch-desc-filename">{d.filename}</div>
                  <p className="vision-batch-desc-text">{d.description}</p>
                  <div className="hint">{t(lang, "vision_model")}: {d.model}</div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
