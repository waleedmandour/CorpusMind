/**
 * Placeholder view for Suite A (Text) — populated in Phase 1+.
 */
export function TextView() {
  return (
    <div className="placeholder-view">
      <h2>CorpusMind Text</h2>
      <p>
        The corpus-analysis workbench lands in <strong>Phase 1</strong>:
        ingestion, corpus management, advanced search, concordancer, frequency,
        collocation, and keyness analysis — with the grounded AI Assistant for
        these features and the core visualizations.
      </p>
      <p>
        The statistics engine backing these features is already implemented and
        unit-tested in <code>engine/stats/measures.py</code> (MI, T-score,
        log-likelihood, Dice, LogDice, chi-square, Delta P, Log Ratio, %DIFF,
        Simple Maths, Odds Ratio, Juilland&apos;s D, Gries&apos; DP, STTR).
      </p>
    </div>
  );
}
