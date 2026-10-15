/**
 * SlowQueryNote — slow-query feedback with classroom-awareness (v1.2.14).
 *
 * v1.2.10 added the "class is busy" banner for full-classroom load.
 * v1.2.12 rc7 fixed the idle false-positive (isPending -> isLoading).
 * v1.2.13 left the classroom-specific wording firing on any solo query
 * over 3s, which was misleading: users running solo analyses with the
 * classroom server OFF still got the queue message.
 *
 * v1.2.14 fix:
 *   - Subscribe to the shared ["server-mode-status"] query (zero added
 *     engine traffic — 30s staleTime, same query the ClassroomStatusChip
 *     already uses).
 *   - Render the classroom copy ONLY when phase === "live"; otherwise
 *     render a classroom-neutral "still working" copy.
 *   - Bump default delayMs from 3000 -> 8000 so the common 3-7s analysis
 *     range doesn't trip the banner at all.
 *
 * Callers can override delayMs (e.g. AnalysisView passes 15000 for the
 * heavy collocation table; the network panel passes 5000 because the
 * network has its own progress feedback).
 */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { t, type Lang } from "@/lib/i18n";

export function SlowQueryNote({
  pending,
  lang,
  delayMs = 8000,
}: {
  pending: boolean;
  lang: Lang;
  delayMs?: number;
}) {
  const [slow, setSlow] = useState(false);

  // Subscribe to the shared classroom-status query. We pass `queryFn` so
  // React Query doesn't warn, but `enabled: false` so SlowQueryNote never
  // triggers a fetch itself — ClassroomStatusChip / StudentModeServerCard
  // elsewhere on the page own the actual polling.
  const { data: serverMode } = useQuery<{ phase?: string }>({
    queryKey: ["server-mode-status"],
    queryFn: () => api.serverModeStatus(),
    enabled: false,
    staleTime: 30_000,
  });
  const classLive = serverMode?.phase === "live";

  useEffect(() => {
    if (!pending) {
      setSlow(false);
      return;
    }
    const id = window.setTimeout(() => setSlow(true), delayMs);
    return () => window.clearTimeout(id);
  }, [pending, delayMs]);

  if (!pending || !slow) return null;
  // Pick the copy based on whether a classroom is actually live.
  const key = classLive ? "analysis_class_busy" : "analysis_slow_neutral";
  return (
    <div className="empty-state sm-busy-note" role="status">
      {t(lang, key)}
    </div>
  );
}
