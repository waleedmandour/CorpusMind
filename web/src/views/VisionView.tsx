/**
 * VisionView — Suite B (9.1–9.10).
 *
 * CorpusMind Lens build step 2: image set manager + analysis viewer.
 *
 * This is the first real frontend for the vision subsystem. The backend
 * has been live since Phase 4 — every route this view calls already
 * exists and is tested (engine/tests/test_phase4_vision.py). This view
 * is intentionally model-free: it surfaces the cached colour /
 * composition / OCR analysis the engine produces at upload time, with
 * no LLM dependency. Vision-LM-backed routes (describe, CDA+llm, etc.)
 * are later build steps and will slot in as siblings to the panels
 * rendered here.
 *
 * Layout (top-to-bottom):
 *   1. Toolbar — image-set picker + "New set" button.
 *   2. Dropzone — drag-drop or click to upload images into the active set.
 *   3. Image grid — thumbnails of all images in the active set.
 *   4. Analysis drawer — when an image is selected, shows its cached
 *      analysis (OCR text, dominant colours, composition geometry) and
 *      a button to run Visual Grammar analysis on it.
 *
 * Accessibility:
 *   - The dropzone is a button (role + tabIndex + Enter/Space handler).
 *   - The image grid is a list of buttons, not a list of divs, so the
 *     screen reader announces them as actionable.
 *   - Every section has an <h3> heading so the page has a real outline.
 */
import { useState, useRef, type KeyboardEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import { api, type ImageRecord, type ImageAnalysis, type VisualGrammarResult, type BatchAnalysisResult } from "@/lib/api";
import { useApp } from "@/store/app";


// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

const IMAGE_ACCEPT = "image/png,image/jpeg,image/webp,image/gif";

// Note on thumbnails: the backend stores raw image bytes on disk under
// data_dir/images/{id}.{ext} but does NOT expose a public HTTP route to
// fetch them (the engine intentionally serves only analysis results, not
// raw files). For v1 we render a placeholder card per image with the
// metadata we DO have (filename, dimensions, size, caption). The actual
// pixel preview is a later enhancement — either a /images/{id}/thumbnail
// route or rendering the local File object URL during upload.


// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------

export function VisionView() {
  const cid = useApp((s) => s.activeCorpusId);
  const queryClient = useQueryClient();
  const [activeSetId, setActiveSetId] = useState<string | null>(null);
  const [selectedImageId, setSelectedImageId] = useState<string | null>(null);
  const [showNewSetForm, setShowNewSetForm] = useState(false);
  const [newSetName, setNewSetName] = useState("");

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
        <h2>Select a corpus</h2>
        <p className="hint">
          Image sets live inside a corpus. Pick one from <strong>Your Corpus</strong> in the sidebar.
        </p>
      </div>
    );
  }

  const onCreateSet = async () => {
    if (!newSetName.trim()) return;
    const created = await api.createImageSet(cid, newSetName.trim());
    setNewSetName("");
    setShowNewSetForm(false);
    setActiveSetId(created.id);
    // Invalidate the list so the new set appears at the top.
    queryClient.invalidateQueries({ queryKey: ["image-sets", cid] });
  };

  return (
    <div className="vision-view">
      <div className="vision-toolbar">
        <label className="vision-set-picker">
          <span className="vision-set-picker-label">Image set</span>
          <select
            value={activeSetId ?? ""}
            onChange={(e) => {
              setActiveSetId(e.target.value || null);
              setSelectedImageId(null);
            }}
          >
            <option value="">- Select -</option>
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
          {showNewSetForm ? "Cancel" : "+ New set"}
        </button>
      </div>

      {showNewSetForm && (
        <div className="vision-new-set-form">
          <input
            type="text"
            value={newSetName}
            onChange={(e) => setNewSetName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onCreateSet()}
            placeholder="Set name (e.g. 'News front pages, July 2026')"
            autoFocus
          />
          <button className="btn-primary" onClick={onCreateSet} disabled={!newSetName.trim()}>
            Create
          </button>
        </div>
      )}

      {setsQuery.isLoading && <div className="hint">Loading image sets…</div>}
      {setsQuery.error && (
        <div className="uploader-status error">
          Failed to load image sets: {(setsQuery.error as Error).message}
        </div>
      )}
      {setsQuery.data && setsQuery.data.length === 0 && !showNewSetForm && (
        <div className="empty-state">
          <h2>No image sets yet</h2>
          <p className="hint">
            Create one with <strong>+ New set</strong> above, then drag images in.
          </p>
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
    await uploadMutation.mutateAsync({ files: pendingFiles, caption });
    setPendingFiles([]);
    setCaption("");
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
        <div className="dropzone-label">
          Drop images here or click to upload (PNG, JPEG, WebP, GIF)
        </div>
      </div>

      {pendingFiles.length > 0 && (
        <div className="vision-pending-upload">
          <div className="vision-pending-header">
            <strong>{pendingFiles.length} image(s) ready to upload</strong>
            <button className="btn-small" onClick={() => setPendingFiles([])}>Clear</button>
          </div>
          <ul className="vision-pending-list">
            {pendingFiles.slice(0, 8).map((f, i) => (
              <li key={i}>
                <span>{f.name}</span>
                <span className="vision-pending-size">{formatBytes(f.size)}</span>
              </li>
            ))}
            {pendingFiles.length > 8 && (
              <li className="vision-pending-more">…and {pendingFiles.length - 8} more</li>
            )}
          </ul>
          <label className="vision-caption-input">
            <span>Caption (optional, applies to all images in this upload)</span>
            <input
              type="text"
              value={caption}
              onChange={(e) => setCaption(e.target.value)}
              placeholder="e.g. Front page of Al-Ahram, 27 July 2026"
            />
          </label>
          <button
            className="btn-primary"
            onClick={onUpload}
            disabled={uploadMutation.isPending}
          >
            {uploadMutation.isPending ? "Uploading…" : `Upload ${pendingFiles.length} image(s)`}
          </button>
          {uploadMutation.error && (
            <div className="uploader-status error">
              Upload failed: {(uploadMutation.error as Error).message}
            </div>
          )}
        </div>
      )}

      <h3 className="vision-section-heading">Images in this set</h3>
      {imagesQuery.isLoading && <div className="hint">Loading images…</div>}
      {imagesQuery.error && (
        <div className="uploader-status error">
          Failed to load images: {(imagesQuery.error as Error).message}
        </div>
      )}
      {imagesQuery.data && imagesQuery.data.length === 0 && (
        <div className="hint">No images yet. Drag some in above.</div>
      )}
      {imagesQuery.data && imagesQuery.data.length > 0 && (
        <div className="vision-grid" role="list">
          {imagesQuery.data.map((img) => (
            <ImageGridItem
              key={img.id}
              image={img}
              selected={img.id === selectedImageId}
              onSelect={() => onSelectImage(img.id === selectedImageId ? null : img.id)}
            />
          ))}
        </div>
      )}

      {selectedImageId && (
        <AnalysisDrawer imageId={selectedImageId} />
      )}

      {selectedImageId && (
        <AlignmentPanel imageId={selectedImageId} />
      )}

      <BatchViewPanel isetId={setId} />
    </div>
  );
}


// ---------------------------------------------------------------------------
// ImageGridItem — one card in the thumbnail grid
// ---------------------------------------------------------------------------

function ImageGridItem({
  image,
  selected,
  onSelect,
}: {
  image: ImageRecord;
  selected: boolean;
  onSelect: () => void;
}) {
  // No thumbnail route exists yet; show a placeholder card with the
  // metadata we DO have. This is enough for the user to identify which
  // image is which (filename + dimensions + size), and the actual pixel
  // preview is a later enhancement (either a thumbnail route or a
  // File-object-URL rendered at upload time).
  return (
    <button
      className={clsx("vision-grid-item", { selected })}
      onClick={onSelect}
      role="listitem"
      aria-pressed={selected}
      title={image.filename}
    >
      <div className="vision-grid-thumb" aria-hidden="true">
        <span className="vision-grid-thumb-icon">{"\u25A3"}</span>
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
  );
}


// ---------------------------------------------------------------------------
// AnalysisDrawer — cached analysis for the selected image
// ---------------------------------------------------------------------------

function AnalysisDrawer({ imageId }: { imageId: string }) {
  const analysisQuery = useQuery({
    queryKey: ["image-analysis", imageId],
    queryFn: () => api.getImageAnalysis(imageId),
  });

  // Visual Grammar is a separate POST that runs on demand (it's not
  // cached at upload time). Lazy-load it only when the user clicks.
  const [showVisualGrammar, setShowVisualGrammar] = useState(false);
  const vgQuery = useQuery({
    queryKey: ["visual-grammar", imageId],
    queryFn: () => api.getVisualGrammar(imageId),
    enabled: showVisualGrammar,
  });

  if (analysisQuery.isLoading) return <div className="hint">Loading analysis…</div>;
  if (analysisQuery.error) {
    return (
      <div className="uploader-status error">
        Failed to load analysis: {(analysisQuery.error as Error).message}
      </div>
    );
  }

  const a: ImageAnalysis = analysisQuery.data!;

  return (
    <div className="vision-analysis-drawer">
      <h3 className="vision-section-heading">
        Analysis: <code>{a.filename}</code>
      </h3>
      <div className="result-meta">
        Dimensions: <strong>{a.dimensions}</strong>
        {a.caption && <> · Caption: <strong>{a.caption}</strong></>}
      </div>

      <div className="vision-analysis-cols">
        <AnalysisCol title="OCR text">
          {a.analysis.ocr.text ? (
            <>
              <pre className="vision-ocr-text">{a.analysis.ocr.text}</pre>
              <div className="hint">
                Engine: <code>{a.analysis.ocr.engine}</code> ·
                Confidence: {(a.analysis.ocr.confidence * 100).toFixed(0)}% ·
                Words: {a.analysis.ocr.word_count} ·
                Language: <code>{a.analysis.ocr.language}</code>
              </div>
            </>
          ) : (
            <div className="hint">No text detected.</div>
          )}
        </AnalysisCol>

        <AnalysisCol title="Dominant colours">
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
            Brightness: {a.analysis.colours.brightness.toFixed(2)} ·
            Contrast: {a.analysis.colours.contrast.toFixed(2)} ·
            Saturation: {a.analysis.colours.saturation.toFixed(2)} ·
            Warm/cold: {a.analysis.colours.warm_cold_balance.toFixed(2)}
          </div>
          {a.analysis.colours.colour_symbolism_notes.length > 0 && (
            <ul className="vision-symbolism-notes">
              {a.analysis.colours.colour_symbolism_notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          )}
        </AnalysisCol>

        <AnalysisCol title="Composition">
          <div className="hint">
            Visual balance: <strong>{a.analysis.composition.visual_balance.toFixed(2)}</strong> ·
            Framing balance: <strong>{a.analysis.composition.framing_balance.toFixed(2)}</strong>
          </div>
          <div className="hint">
            Salience centre: ({a.analysis.composition.salience_centre[0].toFixed(2)}, {a.analysis.composition.salience_centre[1].toFixed(2)})
          </div>
          {Object.entries(a.analysis.composition.information_value).length > 0 && (
            <div className="vision-info-value">
              <strong>Information value:</strong>
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
          {showVisualGrammar ? "Hide Visual Grammar analysis" : "Run Visual Grammar analysis (Kress & van Leeuwen)"}
        </button>
        {showVisualGrammar && (
          <>
            {vgQuery.isLoading && <div className="hint">Analysing…</div>}
            {vgQuery.error && (
              <div className="uploader-status error">
                Visual Grammar failed: {(vgQuery.error as Error).message}
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
  return (
    <div className="vision-vg-panel">
      <div className="result-meta">
        Framework: <strong>{data.framework}</strong>
      </div>
      <div className="vision-vg-scores">
        <span>Representational: <strong>{data.scores.representational.claim_count} claims</strong> (avg conf {data.scores.representational.avg_confidence.toFixed(2)})</span>
        <span>Interactive: <strong>{data.scores.interactive.claim_count} claims</strong> (avg conf {data.scores.interactive.avg_confidence.toFixed(2)})</span>
        <span>Compositional: <strong>{data.scores.compositional.claim_count} claims</strong> (avg conf {data.scores.compositional.avg_confidence.toFixed(2)})</span>
      </div>
      {data.claims.length === 0 ? (
        <div className="hint">No claims produced. This is unusual — the image may be too uniform for the heuristic to find features.</div>
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
// AlignmentPanel — image-text alignment inspector (build step 6)
//
// Frontend for the /images/{img_id}/align route. Lets the user enter
// co-occurring text, choose heuristic/llm/both mode, and see the
// alignments side by side. The "both" mode shows heuristic and LLM
// alignments together so the user can compare which mode produced
// what — honest about which path produced the output.
// ---------------------------------------------------------------------------

type AlignMode = "heuristic" | "llm" | "both";

function AlignmentPanel({ imageId }: { imageId: string }) {
  const [text, setText] = useState("");
  const [mode, setMode] = useState<AlignMode>("heuristic");
  const [submitted, setSubmitted] = useState<{ text: string; mode: AlignMode } | null>(null);

  // Heuristic alignment query
  const heuristicQuery = useQuery({
    queryKey: ["align", imageId, submitted?.text, "heuristic"],
    queryFn: () => api.alignImageText(imageId, submitted!.text, "heuristic"),
    enabled: !!submitted && (submitted.mode === "heuristic" || submitted.mode === "both"),
  });

  // LLM alignment query
  const llmQuery = useQuery({
    queryKey: ["align", imageId, submitted?.text, "llm"],
    queryFn: () => api.alignImageText(imageId, submitted!.text, "llm", "moondream"),
    enabled: !!submitted && (submitted.mode === "llm" || submitted.mode === "both"),
  });

  const onAlign = () => {
    if (!text.trim()) return;
    setSubmitted({ text: text.trim(), mode });
  };

  return (
    <div className="vision-alignment-panel">
      <h3 className="vision-section-heading">Image-text alignment</h3>
      <div className="vision-alignment-input">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) onAlign();
          }}
          placeholder="Enter the co-occurring text (caption, article body, etc.) to align with this image..."
          rows={3}
        />
        <div className="vision-alignment-controls">
          <label className="vision-align-mode">
            <span>Mode</span>
            <select value={mode} onChange={(e) => setMode(e.target.value as AlignMode)}>
              <option value="heuristic">Heuristic (colour/positional)</option>
              <option value="llm">Vision-LM (looks at image)</option>
              <option value="both">Both (side by side)</option>
            </select>
          </label>
          <button
            className="btn-primary"
            onClick={onAlign}
            disabled={!text.trim() || heuristicQuery.isFetching || llmQuery.isFetching}
          >
            {(heuristicQuery.isFetching || llmQuery.isFetching) ? "Aligning..." : "Align"}
          </button>
        </div>
        <div className="hint">Ctrl+Enter to align</div>
      </div>

      {submitted && submitted.mode === "heuristic" && (
        <AlignmentResultView
          title="Heuristic alignment"
          query={heuristicQuery}
        />
      )}

      {submitted && submitted.mode === "llm" && (
        <AlignmentResultView
          title="Vision-LM alignment"
          query={llmQuery}
        />
      )}

      {submitted && submitted.mode === "both" && (
        <div className="vision-alignment-both">
          <AlignmentResultView
            title="Heuristic alignment"
            query={heuristicQuery}
          />
          <AlignmentResultView
            title="Vision-LM alignment"
            query={llmQuery}
          />
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
  if (query.isLoading) return <div className="hint">Running {title.toLowerCase()}...</div>;
  if (query.error) {
    return (
      <div className="uploader-status error">
        {title} failed: {(query.error as Error).message}
      </div>
    );
  }
  if (!query.data) return null;

  const data = query.data;
  return (
    <div className="vision-alignment-result">
      <h4 className="vision-align-result-heading">{title}</h4>
      <div className="result-meta">
        Method: <strong>{data.method}</strong>
        {data.provenance && (
          <> · Mode: <strong>{data.provenance.mode}</strong>
          {data.provenance.model && <> · Model: <strong>{data.provenance.model}</strong></>}
          </>
        )}
        {data.fallback_reason && (
          <div className="hint vision-align-fallback">{data.fallback_reason}</div>
        )}
        {data.person_descriptive_redacted && (
          <div className="hint vision-align-redacted">
            Person-descriptive content was redacted (enable facial analysis in Settings to view).
          </div>
        )}
      </div>

      {data.alignments.length === 0 ? (
        <div className="hint">No alignments found.</div>
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
                <strong>Region:</strong> {a.region_descriptor}
              </div>
              <div className="vision-align-reason">
                <strong>Reason:</strong> {a.match_reason}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// BatchViewPanel — recurring themes + OCR frequency across an image set
// (build step 7)
//
// Surfaces cached vision-LM analysis across all images in the set:
//   1. Recurring framework themes (grouped by framework, counted by category)
//   2. OCR-derived frequency list (Python-side Counter over OCR text)
//   3. Vision-LM description summary (one per image that has a cached desc)
//
// This is a READ-ONLY view — it doesn't call any model, just aggregates
// what's already cached.
// ---------------------------------------------------------------------------

function BatchViewPanel({ isetId }: { isetId: string }) {
  const [enabled, setEnabled] = useState(false);

  const batchQuery = useQuery({
    queryKey: ["batch-analysis", isetId],
    queryFn: () => api.getBatchAnalysis(isetId),
    enabled,
  });

  return (
    <div className="vision-batch-panel">
      <div className="vision-batch-header">
        <h3 className="vision-section-heading">Batch view</h3>
        <button
          className="btn-secondary"
          onClick={() => setEnabled((v) => !v)}
          aria-expanded={enabled}
        >
          {enabled ? "Hide" : "Show"} batch analysis
        </button>
      </div>

      {enabled && batchQuery.isLoading && <div className="hint">Loading batch analysis…</div>}
      {enabled && batchQuery.error && (
        <div className="uploader-status error">
          Failed to load batch analysis: {(batchQuery.error as Error).message}
        </div>
      )}
      {enabled && batchQuery.data && <BatchViewContent data={batchQuery.data} />}
    </div>
  );
}


function BatchViewContent({ data }: { data: BatchAnalysisResult }) {
  return (
    <div className="vision-batch-content">
      <div className="result-meta">
        {data.image_count} images · {data.images_with_vlm} with VLM descriptions ·{" "}
        {data.images_with_discourse} with discourse analysis
      </div>

      {data.note && <div className="hint vision-batch-note">{data.note}</div>}

      <div className="vision-batch-cols">
        {/* Recurring themes */}
        <div className="vision-batch-col">
          <h4 className="vision-col-heading">Recurring framework themes</h4>
          {data.recurring_themes.length === 0 ? (
            <div className="hint">No discourse analysis cached yet.</div>
          ) : (
            data.recurring_themes.map((t) => (
              <div key={t.framework} className="vision-batch-theme">
                <div className="vision-batch-theme-header">
                  <span className="vision-batch-framework">{t.framework}</span>
                  <span className="vision-batch-total">{t.total_claims} claims</span>
                </div>
                <ul className="vision-batch-categories">
                  {t.categories.map((c) => (
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
          <h4 className="vision-col-heading">OCR word frequency</h4>
          {data.ocr_frequency.length === 0 ? (
            <div className="hint">No OCR text found in any image.</div>
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
          <h4 className="vision-col-heading">Vision-LM descriptions</h4>
          {data.descriptions.length === 0 ? (
            <div className="hint">No VLM descriptions cached yet.</div>
          ) : (
            <ul className="vision-batch-desc-list">
              {data.descriptions.map((d) => (
                <li key={d.image_id} className="vision-batch-desc-item">
                  <div className="vision-batch-desc-filename">{d.filename}</div>
                  <p className="vision-batch-desc-text">{d.description}</p>
                  <div className="hint">Model: {d.model}</div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
