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
      { id: "nav.home", label: "Go to Home", run: () => ui.setActiveNav("home") },
      { id: "nav.corpus-target", label: "Go to Your Corpus", run: () => ui.setActiveNav("corpus-target") },
      { id: "nav.corpus-reference", label: "Go to Reference Corpus", run: () => ui.setActiveNav("corpus-reference") },
      { id: "nav.concordance", label: "Go to Concordance", run: () => ui.setActiveNav("concordance") },
      { id: "nav.frequency", label: "Go to Frequency", run: () => ui.setActiveNav("frequency") },
      { id: "nav.collocation", label: "Go to Collocation", run: () => ui.setActiveNav("collocation") },
      { id: "nav.keyness", label: "Go to Keyness", run: () => ui.setActiveNav("keyness") },
      { id: "nav.dispersion", label: "Go to Dispersion", run: () => ui.setActiveNav("dispersion") },
      { id: "nav.ngrams", label: "Go to N-grams", run: () => ui.setActiveNav("ngrams") },
      { id: "nav.pos", label: "Go to POS Analysis", run: () => ui.setActiveNav("pos") },
      { id: "nav.grammar", label: "Go to Grammar", run: () => ui.setActiveNav("grammar") },
      { id: "nav.dependency", label: "Go to Dependency", run: () => ui.setActiveNav("dependency") },
      { id: "nav.discourse", label: "Go to Discourse", run: () => ui.setActiveNav("discourse") },
      { id: "nav.vocab", label: "Go to Vocabulary", run: () => ui.setActiveNav("vocab") },
      { id: "nav.sentiment", label: "Go to Sentiment", run: () => ui.setActiveNav("sentiment") },
      { id: "nav.metaphor", label: "Go to Metaphor", run: () => ui.setActiveNav("metaphor") },
      { id: "nav.arabic", label: "Go to Arabic Tools", run: () => ui.setActiveNav("arabic") },
      { id: "nav.vision", label: "Go to Vision Suite", run: () => ui.setActiveNav("vision") },
      { id: "nav.assistant", label: "Go to AI Assistant", run: () => ui.setActiveNav("assistant") },
      { id: "nav.settings", label: "Go to Settings", run: () => ui.setActiveNav("settings") },
      { id: "nav.userguide", label: "Go to User Guide", run: () => ui.setActiveNav("userguide") },
      { id: "nav.about", label: "Go to About", run: () => ui.setActiveNav("about") },
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
