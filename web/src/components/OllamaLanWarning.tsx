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
 */
import { useState } from "react";

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
  const [dismissedAddr, setDismissedAddr] = useState<string | null>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch {
      return null; // private mode / storage disabled — session-only then
    }
  });
  if (!exposed) return null;
  const currentAddr = addr ?? "LAN";
  if (dismissedAddr && dismissedAddr === currentAddr) return null;
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
    </div>
  );
}
