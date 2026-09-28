/**
 * OllamaLanWarning — the ONE canonical "Ollama is reachable beyond
 * loopback" warning (v1.2.10 field fixes).
 *
 * Field report: the warning was rendered twice with divergent copy —
 * dismissible inside the Student Mode card but with NO dismiss in the
 * Model Providers card — so teachers could never fully clear it, and the
 * session-only dismissal made it return on every restart. One component,
 * one sentence, one hint; the dismissal is persisted to localStorage
 * keyed by the exposed ADDRESS, so a genuinely new exposure (different
 * interface / network) re-arms the warning while a known one stays quiet.
 *
 * v1.2.11 field fixes: a "Check again" button. The status poll caches the
 * exposure probe for 60 s, so a teacher who just fixed their Ollama
 * binding used to keep seeing a stale warning for up to a minute with no
 * way to act on it. The button hits /server-mode/recheck-ollama (drops
 * the cache, re-probes) and refreshes every query that feeds this banner.
 */
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useUI } from "@/store/ui";

const STORAGE_KEY = "cm_ollama_lan_dismissed_addr";

export function OllamaLanWarning({
  exposed,
  addr,
  style,
}: {
  exposed: boolean;
  addr: string | null;
  style?: React.CSSProperties;
}) {
  const lang = useUI((s) => s.lang);
  const qc = useQueryClient();
  const [dismissedAddr, setDismissedAddr] = useState<string | null>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch {
      return null; // private mode / storage disabled — session-only then
    }
  });
  const [checking, setChecking] = useState(false);

  if (!exposed) return null;
  const currentAddr = addr ?? "LAN";
  if (dismissedAddr && dismissedAddr === currentAddr) return null;

  const recheck = async () => {
    if (checking) return;
    setChecking(true);
    try {
      const fresh = await api.serverModeRecheckOllama();
      if (!fresh.exposed && dismissedAddr) {
        // The exposure is gone; forget the stale dismissal address so a
        // future exposure at a different address is not silently muted.
        try {
          localStorage.removeItem(STORAGE_KEY);
        } catch {
          /* storage unavailable — nothing to clean */
        }
        setDismissedAddr(null);
      }
      // Both copies of this banner (Settings + Student Mode card) read the
      // same ["server-mode-status"] query — one invalidation refreshes both.
      await qc.invalidateQueries({ queryKey: ["server-mode-status"] });
    } catch {
      // Probe endpoint unreachable — the banner simply stays as-is.
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="sm-warning sm-lan-warning" role="alert" style={style}>
      <button
        type="button"
        className="sm-warning-dismiss"
        aria-label={t(lang, "sm_dismiss")}
        onClick={() => {
          setDismissedAddr(currentAddr);
          try {
            localStorage.setItem(STORAGE_KEY, currentAddr);
          } catch {
            /* storage unavailable — dismissal is session-only then */
          }
        }}
      >
        ×
      </button>
      <p>
        {t(lang, "sm_ollama_lan_warning").replace("{addr}", currentAddr)}
      </p>
      <p className="sm-warning-hint">{t(lang, "sm_ollama_lan_hint")}</p>
      <button
        type="button"
        className="btn btn-secondary sm-warning-recheck"
        onClick={recheck}
        disabled={checking}
      >
        {checking ? t(lang, "sm_rechecking") : t(lang, "sm_recheck")}
      </button>
    </div>
  );
}
