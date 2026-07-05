/**
 * Command palette (§10.3 power-user complement to the ribbon).
 *
 * Phase 0 ships the bare scaffolding: open with Ctrl/Cmd+K, fuzzy-filter the
 * list of registered actions. Real actions get registered as features land.
 */
import { useEffect, useMemo, useState } from "react";
import { useUI } from "@/store/ui";
import clsx from "clsx";

interface Action {
  id: string;
  label: string;
  hint?: string;
  run: () => void;
}

export function CommandPalette() {
  const open = useUI((s) => s.commandPaletteOpen);
  const setOpen = useUI((s) => s.setCommandPaletteOpen);
  const ui = useUI();
  const [query, setQuery] = useState("");

  const actions = useMemo<Action[]>(() => {
    return [
      { id: "tab.assistant", label: "Go to AI Assistant", run: () => ui.setActiveTab("assistant") },
      { id: "tab.text", label: "Go to Text Suite", run: () => ui.setActiveTab("text") },
      { id: "tab.arabic", label: "Go to Arabic Analysis", run: () => ui.setActiveTab("arabic") },
      { id: "tab.vision", label: "Go to Vision Suite", run: () => ui.setActiveTab("vision") },
      { id: "tab.settings", label: "Go to Settings", run: () => ui.setActiveTab("settings") },
      { id: "theme.light", label: "Theme: Light", run: () => ui.setTheme("light") },
      { id: "theme.dark", label: "Theme: Dark", run: () => ui.setTheme("dark") },
      { id: "theme.system", label: "Theme: System", run: () => ui.setTheme("system") },
      { id: "dir.ltr", label: "Direction: LTR", run: () => ui.setDir("ltr") },
      { id: "dir.rtl", label: "Direction: RTL", run: () => ui.setDir("rtl") },
    ];
  }, [ui]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(!useUI.getState().commandPaletteOpen);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setOpen]);

  if (!open) return null;

  const filtered = actions.filter((a) => a.label.toLowerCase().includes(query.toLowerCase()));

  return (
    <div className="cmdk-backdrop" onClick={() => setOpen(false)}>
      <div className="cmdk" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Type to find any action…"
          className="cmdk-input"
        />
        <ul className="cmdk-list">
          {filtered.map((a) => (
            <li key={a.id}>
              <button
                className={clsx("cmdk-item")}
                onClick={() => {
                  a.run();
                  setOpen(false);
                }}
              >
                {a.label}
              </button>
            </li>
          ))}
          {filtered.length === 0 && <li className="cmdk-empty">No actions match.</li>}
        </ul>
      </div>
    </div>
  );
}
