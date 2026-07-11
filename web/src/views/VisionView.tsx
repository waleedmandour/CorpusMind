/**
 * VisionView — Suite B (§9.1–9.10).
 *
 * Coming Soon — the Vision Suite is under active development.
 * When complete, it will include:
 *  - Image set management (create, list, upload images)
 *  - Image analysis viewer (colour, composition, OCR)
 *  - Visual Grammar analysis (Kress & van Leeuwen)
 *  - Image-text alignment (flagship)
 *  - Multimodal discourse analysis
 *
 * For now, a "Coming Soon" placeholder is shown.
 */
export function VisionView() {
  return (
    <div className="vision-coming-soon">
      <div className="coming-soon-icon">{"\u25A3"}</div>
      <h1>Vision Suite</h1>
      <h2>Coming Soon</h2>
      <p className="coming-soon-desc">
        The Vision Suite is under active development. When complete, it will
        support multimodal discourse analysis including:
      </p>
      <ul className="coming-soon-list">
        <li>Image set management — upload and organize images</li>
        <li>Image analysis — colour, composition, OCR text extraction</li>
        <li>Visual Grammar — Kress &amp; van Leeuwen metafunction scoring</li>
        <li>Image-text alignment — cross-modal meaning analysis</li>
        <li>Multimodal discourse analysis — combining text + image evidence</li>
      </ul>
      <p className="coming-soon-note">
        The text analysis tools, Arabic NLP, AI Assistant, and all other
        features are fully functional now. Check back for the Vision Suite
        in a future release.
      </p>
    </div>
  );
}
