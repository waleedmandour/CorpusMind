import { useEffect, useState } from "react";
import { t, type Lang } from "@/lib/i18n";

/**
 * v1.2.10 (soak follow-up): queued-query feedback for heavy analysis.
 *
 * The Student Mode soak showed collocation/concordance requests queueing
 * for tens of seconds under full classroom load while the UI sat on a
 * silent spinner. This note stays invisible for normal queries and appears
 * only after `delayMs` of pending time, so a solo user on a fast corpus
 * never sees it. The wording covers both the queued and the merely-slow
 * case honestly.
 */
export function SlowQueryNote({
  pending,
  lang,
  delayMs = 3000,
}: {
  pending: boolean;
  lang: Lang;
  delayMs?: number;
}) {
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    if (!pending) {
      setSlow(false);
      return;
    }
    const id = window.setTimeout(() => setSlow(true), delayMs);
    return () => window.clearTimeout(id);
  }, [pending, delayMs]);

  if (!pending || !slow) return null;
  return (
    <div className="empty-state sm-busy-note" role="status">
      {t(lang, "analysis_class_busy")}
    </div>
  );
}
