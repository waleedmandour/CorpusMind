/**
 * ClassroomStatusChip — live Student Mode progress in the bottom task bar
 * (v1.2.11 field fix).
 *
 * Field report: turning the classroom ON used to freeze the app for up to
 * ~20 s while the engine waited (synchronously) for Caddy, with the only
 * visible change being a black console window. The start is now phased in
 * the engine (off → starting → live / failed), and this chip renders that
 * phase in the task bar the field report asked for:
 *
 *   starting → pulsing amber  "Starting classroom server…"
 *   live     → green          "Classroom live · N students"
 *   failed   → red            "Classroom failed — details"
 *
 * It shares the ["server-mode-status"] query with the Student Mode card,
 * so there is exactly one poll no matter which surface is mounted. While
 * the classroom is off the chip renders nothing — the task bar stays clean.
 */
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useUI } from "@/store/ui";

export function ClassroomStatusChip() {
  const lang = useUI((s) => s.lang);
  const setActiveNav = useUI((s) => s.setActiveNav);

  const status = useQuery({
    queryKey: ["server-mode-status"],
    queryFn: () => api.serverModeStatus(),
    refetchInterval: (q) => {
      const d = q.state.data;
      if (d?.phase === "starting") return 1500;
      if (d?.enabled) return 5000;
      return false;
    },
  });

  const s = status.data;
  if (!s || s.phase === "off") return null;

  const cls =
    s.phase === "starting"
      ? "classroom-chip is-starting"
      : s.phase === "failed"
        ? "classroom-chip is-failed"
        : "classroom-chip is-live";

  const label =
    s.phase === "starting"
      ? t(lang, "sm_taskbar_starting")
      : s.phase === "failed"
        ? t(lang, "sm_taskbar_failed")
        : `${t(lang, "sm_taskbar_live")} · ${s.students_active}`;

  return (
    <button
      type="button"
      className={cls}
      onClick={() => setActiveNav("settings")}
      title={s.phase === "failed" && s.caddy_error ? s.caddy_error : t(lang, "sm_card_title")}
    >
      <span className="status-dot" aria-hidden />
      <span>{label}</span>
    </button>
  );
}
