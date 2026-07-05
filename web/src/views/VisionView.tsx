/**
 * VisionView — Suite B (§9.1–9.10).
 *
 * Tools:
 *  - Image set management (create, list, upload images)
 *  - Image analysis viewer (colour, composition, OCR)
 *  - Visual Grammar analysis (Kress & van Leeuwen)
 *  - Image-text alignment (flagship)
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import { api } from "@/lib/api";
import { useApp } from "@/store/app";

type Tab = "manage" | "analyse" | "grammar" | "align" | "discourse" | "facial";

export function VisionView() {
  const cid = useApp((s) => s.activeCorpusId);
  const [tab, setTab] = useState<Tab>("manage");
  const [activeImageSetId, setActiveImageSetId] = useState<string | null>(null);
  const [activeImageId, setActiveImageId] = useState<string | null>(null);

  if (!cid) return <div className="empty-state">Select a corpus to start working with images.</div>;

  return (
    <div className="vision-view">
      <div className="grounding-notice">
        <strong>§9 Vision Suite (Phase 4 + 5):</strong> Image ingestion, OCR, colour/composition
        analysis, Visual Grammar (Kress &amp; van Leeuwen), multimodal image-text alignment,
        + Phase 5: Social Semiotic, CDA (4 frameworks), Persuasion, Framing, Narrative,
        Visual Metaphor, Emotion, Cultural + facial-analysis opt-in (§18).
      </div>

      <div className="tabs">
        {(["manage", "analyse", "grammar", "align", "discourse", "facial"] as Tab[]).map((t) => (
          <button key={t} className={clsx("tab", { active: tab === t })} onClick={() => setTab(t)}>
            {t === "manage" ? "Manage" : t === "analyse" ? "Analyse" : t === "grammar" ? "Visual Grammar" :
             t === "align" ? "Align" : t === "discourse" ? "Discourse §5" : "Facial §18"}
          </button>
        ))}
      </div>

      {tab === "manage" && (
        <ImageManager cid={cid} activeImageSetId={activeImageSetId} setActiveImageSetId={setActiveImageSetId} setActiveImageId={setActiveImageId} />
      )}
      {tab === "analyse" && activeImageId && <ImageAnalyser imgId={activeImageId} />}
      {tab === "grammar" && activeImageId && <VisualGrammarView imgId={activeImageId} />}
      {tab === "align" && activeImageId && <AlignmentView imgId={activeImageId} />}
      {tab === "discourse" && activeImageId && <DiscoursePanel imgId={activeImageId} />}
      {tab === "facial" && activeImageId && <FacialPanel imgId={activeImageId} />}
      {tab !== "manage" && !activeImageId && (
        <div className="empty-state">Select an image in the Manage tab first.</div>
      )}
    </div>
  );
}


function ImageManager({ cid, activeImageSetId, setActiveImageSetId, setActiveImageId }: {
  cid: string;
  activeImageSetId: string | null;
  setActiveImageSetId: (id: string | null) => void;
  setActiveImageId: (id: string | null) => void;
}) {
  const qc = useQueryClient();
  const [newSetName, setNewSetName] = useState("");

  const imageSets = useQuery({
    queryKey: ["image-sets", cid],
    queryFn: () => api.listImageSets(cid),
  });

  const createSet = useMutation({
    mutationFn: (name: string) => api.createImageSet(cid, name),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["image-sets", cid] }),
  });

  return (
    <div className="image-manager">
      <div className="toolbar">
        <input value={newSetName} onChange={(e) => setNewSetName(e.target.value)} placeholder="New image set name" />
        <button disabled={!newSetName.trim()} onClick={() => { createSet.mutate(newSetName); setNewSetName(""); }}>
          Create image set
        </button>
      </div>

      <div className="image-sets-list">
        {imageSets.data?.map((iset) => (
          <div key={iset.id} className={clsx("image-set-item", { active: iset.id === activeImageSetId })}
               onClick={() => setActiveImageSetId(iset.id)}>
            <strong>{iset.name}</strong>
            <span>{iset.image_count} image{iset.image_count === 1 ? "" : "s"}</span>
          </div>
        ))}
        {imageSets.data?.length === 0 && <div className="empty">No image sets yet.</div>}
      </div>

      {activeImageSetId && <ImageUploader isetId={activeImageSetId} setActiveImageId={setActiveImageId} />}
      {activeImageSetId && <ImageList isetId={activeImageSetId} setActiveImageId={setActiveImageId} />}
    </div>
  );
}


function ImageUploader({ isetId, setActiveImageId }: { isetId: string; setActiveImageId: (id: string | null) => void }) {
  const qc = useQueryClient();
  const [dragging, setDragging] = useState(false);
  const [caption, setCaption] = useState("");

  const upload = useMutation({
    mutationFn: (files: File[]) => api.uploadImages(isetId, files, caption || undefined),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["images", isetId] });
      qc.invalidateQueries({ queryKey: ["image-sets"] });
      if (data.length > 0) setActiveImageId(data[0].id);
    },
  });

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) upload.mutate(files);
  };

  return (
    <div>
      <div className={clsx("dropzone", { dragging, busy: upload.isPending })}
           onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
           onDragLeave={() => setDragging(false)}
           onDrop={onDrop}>
        <input type="file" multiple accept=".jpg,.jpeg,.png,.tif,.tiff,.webp,.bmp,.gif"
               onChange={(e) => { const fs = Array.from(e.target.files ?? []); if (fs.length) upload.mutate(fs); }}
               style={{ display: "none" }} id="img-file-input" />
        <label htmlFor="img-file-input" className="dropzone-label">
          {upload.isPending ? "Uploading & analysing…" : dragging ? "Drop images here" : "Drop images or click (.jpg, .png, .tif, .webp)"}
        </label>
      </div>
      <input className="caption-input" value={caption} onChange={(e) => setCaption(e.target.value)}
             placeholder="Optional caption (one per image, newline-separated)" />
    </div>
  );
}


function ImageList({ isetId, setActiveImageId }: { isetId: string; setActiveImageId: (id: string | null) => void }) {
  const images = useQuery({
    queryKey: ["images", isetId],
    queryFn: () => api.listImages(isetId),
  });
  return (
    <div className="image-grid">
      {images.data?.map((img) => (
        <div key={img.id} className="image-thumb" onClick={() => setActiveImageId(img.id)}>
          <div className="thumb-placeholder">{img.format.toUpperCase()}</div>
          <div className="thumb-meta">
            <div>{img.filename}</div>
            <div>{img.width}×{img.height}</div>
            {img.caption && <div className="thumb-caption">{img.caption.slice(0, 40)}…</div>}
          </div>
        </div>
      ))}
      {images.data?.length === 0 && <div className="empty">No images yet.</div>}
    </div>
  );
}


function ImageAnalyser({ imgId }: { imgId: string }) {
  const analysis = useQuery({
    queryKey: ["image-analysis", imgId],
    queryFn: () => api.getImageAnalysis(imgId),
  });

  if (!analysis.data) return <div className="empty-state">Loading…</div>;
  const a = analysis.data;

  return (
    <div className="panel-content">
      <div className="result-meta">
        <strong>{a.filename}</strong> · {a.dimensions} · {a.analysis.ocr?.engine === "tesseract" ? `OCR: ${a.analysis.ocr.word_count} words` : "OCR unavailable"}
      </div>

      <h3>Colour analysis (§9.4.6)</h3>
      <div className="colour-swatches">
        {a.analysis.colours?.dominant_colours?.map((c: any, i: number) => (
          <div key={i} className="swatch">
            <div className="swatch-colour" style={{ background: c.hex }} />
            <div className="swatch-meta">
              <code>{c.hex}</code>
              <span>{c.percent}%</span>
            </div>
          </div>
        ))}
      </div>
      <div className="colour-stats">
        <span>Brightness: <strong>{a.analysis.colours?.brightness}</strong></span>
        <span>Contrast: <strong>{a.analysis.colours?.contrast}</strong></span>
        <span>Saturation: <strong>{a.analysis.colours?.saturation}</strong></span>
        <span>Warm/cold: <strong>{a.analysis.colours?.warm_cold_balance}</strong></span>
      </div>
      {a.analysis.colours?.colour_symbolism_notes?.length > 0 && (
        <div className="grounding-notice">
          <strong>Colour symbolism (culture-relative, §9.4.6):</strong>
          <ul>{a.analysis.colours.colour_symbolism_notes.map((n: string, i: number) => <li key={i}>{n}</li>)}</ul>
        </div>
      )}

      <h3>Composition analysis (§9.4.7)</h3>
      <div className="composition-info">
        <span>Information value:</span>
        <ul>
          <li>Left (Given): <strong>{a.analysis.composition?.information_value?.left}</strong></li>
          <li>Right (New): <strong>{a.analysis.composition?.information_value?.right}</strong></li>
          <li>Top (Ideal): <strong>{a.analysis.composition?.information_value?.top}</strong></li>
          <li>Bottom (Real): <strong>{a.analysis.composition?.information_value?.bottom}</strong></li>
          <li>Centre: <strong>{a.analysis.composition?.information_value?.centre}</strong></li>
        </ul>
        <span>Salience centre: ({a.analysis.composition?.salience_centre?.[0]}, {a.analysis.composition?.salience_centre?.[1]})</span>
        <span>Visual balance: <strong>{a.analysis.composition?.visual_balance}</strong></span>
      </div>

      {a.analysis.ocr?.text && (
        <>
          <h3>OCR text (§9.3)</h3>
          <div className="ocr-text">{a.analysis.ocr.text}</div>
        </>
      )}
    </div>
  );
}


function VisualGrammarView({ imgId }: { imgId: string }) {
  const vg = useQuery({
    queryKey: ["visual-grammar", imgId],
    queryFn: () => api.getVisualGrammar(imgId),
  });

  if (!vg.data) return <div className="empty-state">Loading…</div>;

  return (
    <div className="panel-content">
      <div className="result-meta">
        Framework: <strong>{vg.data.framework}</strong>
      </div>

      <div className="vg-scores">
        <div className="vg-score">
          <h4>Representational</h4>
          <span>{vg.data.scores.representational.claim_count} claims · avg conf {vg.data.scores.representational.avg_confidence}</span>
        </div>
        <div className="vg-score">
          <h4>Interactive</h4>
          <span>{vg.data.scores.interactive.claim_count} claims · avg conf {vg.data.scores.interactive.avg_confidence}</span>
        </div>
        <div className="vg-score">
          <h4>Compositional</h4>
          <span>{vg.data.scores.compositional.claim_count} claims · avg conf {vg.data.scores.compositional.avg_confidence}</span>
        </div>
      </div>

      <h3>Claims (framework-lensed hypotheses, §4 Principle 5)</h3>
      {vg.data.claims.map((c: any, i: number) => (
        <div key={i} className={clsx("vg-claim", `meta-${c.metafunction}`)}>
          <header>
            <span className="vg-metafunction">{c.metafunction}</span>
            <span className="vg-category">{c.category}</span>
            <span className="vg-confidence">conf: {c.confidence.toFixed(2)}</span>
          </header>
          <p>{c.claim}</p>
          <div className="vg-evidence">
            <strong>Evidence:</strong>
            <ul>{c.evidence.map((e: string, j: number) => <li key={j}><code>{e}</code></li>)}</ul>
          </div>
        </div>
      ))}
    </div>
  );
}


function AlignmentView({ imgId }: { imgId: string }) {
  const [text, setText] = useState("");
  const [submitted, setSubmitted] = useState<string | null>(null);
  const result = useQuery({
    queryKey: ["alignment", imgId, submitted],
    queryFn: () => api.alignImageText(imgId, submitted!),
    enabled: !!submitted,
  });

  return (
    <div className="panel-content">
      <div className="grounding-notice">
        <strong>§9.8 (flagship):</strong> Image-text alignment. Every alignment is inspectable
        (not a black box). Phase 4 uses heuristic similarity; Phase 5 swaps in CLIP-style embeddings.
      </div>

      <div className="toolbar">
        <textarea value={text} onChange={(e) => setText(e.target.value)}
                  placeholder="Co-occurring text (caption, article body)…" rows={3} />
        <button disabled={!text.trim() || result.isPending} onClick={() => setSubmitted(text)}>
          {result.isPending ? "Aligning…" : "Align"}
        </button>
      </div>

      {result.data && (
        <>
          <div className="result-meta">
            Method: <strong>{result.data.method}</strong> ·
            {result.data.alignments.length} alignments ·
            {result.data.regions.length} regions · {result.data.spans.length} text spans
          </div>

          <h3>Alignments (sorted by confidence)</h3>
          <table className="data-table">
            <thead>
              <tr><th>Region</th><th>Text span</th><th>Confidence</th><th>Match reason</th></tr>
            </thead>
            <tbody>
              {result.data.alignments.map((a: any, i: number) => (
                <tr key={i}>
                  <td><code>{a.region_id}</code></td>
                  <td><strong>"{a.span_text}"</strong></td>
                  <td>{a.confidence.toFixed(3)}</td>
                  <td className="match-reason">{a.match_reason}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3>Regions (grid-based, Phase 5 will use object detector)</h3>
          <div className="regions-grid">
            {result.data.regions.map((r: any) => (
              <div key={r.region_id} className="region-card">
                <code>{r.region_id}</code>
                <div className="region-colour" style={{ background: `rgb(${r.mean_colour.join(",")})` }} />
                <div>salience: {r.salience}</div>
                <div className="region-desc">{r.descriptor}</div>
              </div>
            ))}
          </div>

          <h3>Cross-modal relations (§9.9)</h3>
          {result.data.cross_modal_relations.map((r: any, i: number) => (
            <div key={i} className={clsx("cross-modal-relation", `type-${r.relation_type}`)}>
              <header>
                <span className="cm-type">{r.relation_type}</span>
                <span className="cm-conf">conf: {r.confidence.toFixed(2)}</span>
              </header>
              <p>{r.description}</p>
            </div>
          ))}
        </>
      )}
    </div>
  );
}


// =========================================================================
// Phase 5 — Discourse panel (§9.11–9.18)
// =========================================================================

function DiscoursePanel({ imgId }: { imgId: string }) {
  const [analysis, setAnalysis] = useState<string>("social_semiotic");
  const [cdaFramework, setCdaFramework] = useState("fairclough");
  const [submitted, setSubmitted] = useState<{ type: string; framework?: string } | null>(null);

  const frameworks = useQuery({ queryKey: ["cda-frameworks"], queryFn: api.cdaFrameworks });

  const result = useQuery({
    queryKey: ["discourse", imgId, submitted],
    queryFn: async () => {
      if (!submitted) return null;
      switch (submitted.type) {
        case "social_semiotic": return await api.socialSemiotic(imgId);
        case "cda": return await api.cda(imgId, submitted.framework);
        case "persuasion": return await api.persuasion(imgId);
        case "framing": return await api.framing(imgId);
        case "narrative": return await api.narrative(imgId);
        case "visual_metaphor": return await api.visualMetaphor(imgId);
        case "emotion": return await api.emotion(imgId);
        case "cultural": return await api.cultural(imgId);
        default: return null;
      }
    },
    enabled: !!submitted,
  });

  const onRun = () => {
    setSubmitted({ type: analysis, framework: analysis === "cda" ? cdaFramework : undefined });
  };

  return (
    <div className="panel-content">
      <div className="grounding-notice">
        <strong>§4 Principle 5 (load-bearing):</strong> Every interpretive claim below is
        framework-attributed and phrased as a hypothesis ("Under a [Framework] reading, X may
        indicate Y"). Never state ideology, bias, or power relations as settled fact.
      </div>

      <div className="toolbar">
        <label>Analysis
          <select value={analysis} onChange={(e) => setAnalysis(e.target.value)}>
            <option value="social_semiotic">§9.11 Social Semiotic</option>
            <option value="cda">§9.12 Critical Discourse (CDA)</option>
            <option value="persuasion">§9.13 Persuasion (Aristotle + Toulmin)</option>
            <option value="framing">§9.14 Framing (Entman)</option>
            <option value="narrative">§9.15 Narrative (Labov)</option>
            <option value="visual_metaphor">§9.16 Visual Metaphor (MIPVU)</option>
            <option value="emotion">§9.17 Emotion (combined)</option>
            <option value="cultural">§9.18 Cultural (culture-relative)</option>
          </select>
        </label>
        {analysis === "cda" && (
          <label>CDA framework
            <select value={cdaFramework} onChange={(e) => setCdaFramework(e.target.value)}>
              {frameworks.data && Object.entries(frameworks.data.frameworks).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </label>
        )}
        <button onClick={onRun} disabled={result.isPending}>
          {result.isPending ? "Analysing…" : "Run analysis"}
        </button>
      </div>

      {result.data && (
        <>
          <div className="result-meta">
            Framework: <strong>{result.data.framework}</strong> ·
            {result.data.claims.length} claims
          </div>
          <p className="summary">{result.data.summary}</p>
          {result.data.claims.map((c: any, i: number) => (
            <div key={i} className="vg-claim">
              <header>
                <span className="vg-metafunction">{c.category}</span>
                <span className="vg-confidence">conf: {c.confidence.toFixed(2)}</span>
              </header>
              <p>{c.claim}</p>
              {c.evidence && c.evidence.length > 0 && (
                <div className="vg-evidence">
                  <strong>Evidence:</strong>
                  <ul>{c.evidence.map((e: string, j: number) => <li key={j}><code>{e}</code></li>)}</ul>
                </div>
              )}
            </div>
          ))}
        </>
      )}
    </div>
  );
}


// =========================================================================
// Phase 5 — Facial analysis panel (§9.4.3, §18 opt-in)
// =========================================================================

function FacialPanel({ imgId }: { imgId: string }) {
  const status = useQuery({ queryKey: ["facial-status"], queryFn: api.facialAnalysisStatus });
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const onRun = async () => {
    setError(null);
    try {
      const r = await api.facialAnalysis(imgId);
      setResult(r);
    } catch (e: any) {
      setError(e.message || String(e));
    }
  };

  return (
    <div className="panel-content">
      <div className="grounding-notice" style={{ borderInlineStartColor: "var(--danger)" }}>
        <strong>§18 Ethical Guardrails (load-bearing):</strong> Facial analysis is OFF by default.
        It NEVER performs identity recognition or re-identification of real individuals.
        Outputs are descriptive visual cues only. To enable: set
        <code>CORPUSMIND_FACIAL_ANALYSIS_ENABLED=1</code>.
      </div>

      {status.data && (
        <div className="facial-status">
          Status: <strong className={status.data.enabled ? "ok" : "bad"}>
            {status.data.enabled ? "ENABLED" : "DISABLED (default)"}
          </strong>
          <p className="notice">{status.data.notice}</p>
        </div>
      )}

      <button onClick={onRun} className="run-btn">Run facial analysis</button>

      {error && <div className="error">⚠ {error}</div>}

      {result && (
        <>
          <div className="result-meta">
            Model: <strong>{result.model}</strong> ·
            Faces detected: <strong>{result.face_count}</strong> ·
            Consent verified: <strong>{result.consent_verified ? "✓" : "✗"}</strong>
          </div>
          <div className="ethics-notice">{result.ethics_notice}</div>
          {result.faces.map((f: any, i: number) => (
            <div key={i} className="face-card">
              <header>
                <span>Face {i + 1}</span>
                <span>conf: {f.confidence.toFixed(2)}</span>
              </header>
              <div className="face-cues">
                <span>Expression: <strong>{f.facial_expression}</strong></span>
                <span>Head: <strong>{f.head_direction}</strong></span>
                <span>Gaze: <strong>{f.eye_gaze}</strong></span>
                <span>Age group: <strong>{f.estimated_age_group}</strong></span>
                <span>Gender presentation: <strong>{f.gender_presentation}</strong></span>
              </div>
              <p className="gloss">{f.interpretive_gloss}</p>
              <p className="evidence-note">{f.evidence_note}</p>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
