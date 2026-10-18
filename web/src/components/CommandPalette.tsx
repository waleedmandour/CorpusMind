/**
 * Command palette (10.3 power-user complement to the ribbon).
 *
 * Phase 0 ships the bare scaffolding: open with Ctrl/Cmd+K, fuzzy-filter the
 * list of registered actions. Real actions get registered as features land.
 */
import { useEffect, useMemo, useState } from "react";
import { useUI } from "@/store/ui";
import { useTroubleshoot } from "@/store/troubleshooting";
import { t } from "@/lib/i18n";
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
  // v1.2.14-7 (r7): action labels were hardcoded English; they now reuse the
  // sidebar's translated nav keys behind a translated "Go to" prefix.
  const lang = useUI((s) => s.lang);
  const go = (nav: string) => `${t(lang, "cp_go")} ${nav}`;

  const actions = useMemo<Action[]>(() => {
    // v1.2.1: the Lens-mode nav filter is gone (Lens lives in its own repo).
    // v1.2.9 Student Mode: the Settings action mirrors the Sidebar's student
    // filter — the classroom client never offers teacher-only surfaces.
    const student = ui.studentClient;
    return [
      { id: "nav.home", label: go(t(lang, "nav_home")), run: () => ui.setActiveNav("home") },
      { id: "nav.corpus-target", label: go(t(lang, "nav_corpus_target")), run: () => ui.setActiveNav("corpus-target") },
      { id: "nav.corpus-reference", label: go(t(lang, "nav_corpus_reference")), run: () => ui.setActiveNav("corpus-reference") },
      { id: "nav.concordance", label: go(t(lang, "nav_concordance")), run: () => ui.setActiveNav("concordance" as any) },
      { id: "nav.frequency", label: go(t(lang, "nav_frequency")), run: () => ui.setActiveNav("frequency" as any) },
      { id: "nav.collocation", label: go(t(lang, "nav_collocation")), run: () => ui.setActiveNav("collocation" as any) },
      { id: "nav.keyness", label: go(t(lang, "nav_keyness")), run: () => ui.setActiveNav("keyness" as any) },
      { id: "nav.dispersion", label: go(t(lang, "nav_dispersion")), run: () => ui.setActiveNav("dispersion" as any) },
      { id: "nav.ngrams", label: go(t(lang, "nav_ngrams")), run: () => ui.setActiveNav("ngrams" as any) },
      { id: "nav.pos", label: go(t(lang, "nav_pos")), run: () => ui.setActiveNav("pos" as any) },
      { id: "nav.grammar", label: go(t(lang, "nav_grammar")), run: () => ui.setActiveNav("grammar" as any) },
      { id: "nav.dependency", label: go(t(lang, "nav_dependency")), run: () => ui.setActiveNav("dependency" as any) },
      { id: "nav.discourse", label: go(t(lang, "nav_discourse")), run: () => ui.setActiveNav("discourse" as any) },
      { id: "nav.vocab", label: go(t(lang, "nav_vocab")), run: () => ui.setActiveNav("vocab" as any) },
      { id: "nav.sentiment", label: go(t(lang, "nav_sentiment")), run: () => ui.setActiveNav("sentiment" as any) },
      { id: "nav.metaphor", label: go(t(lang, "nav_metaphor")), run: () => ui.setActiveNav("metaphor" as any) },
      { id: "nav.vector-kwic", label: go(t(lang, "nav_vector_kwic")), run: () => ui.setActiveNav("vector-kwic" as any) },
      { id: "nav.learner-caf", label: go(t(lang, "nav_learner_caf")), run: () => ui.setActiveNav("learner-caf" as any) },
      { id: "nav.learner-compare", label: go(t(lang, "nav_learner_compare")), run: () => ui.setActiveNav("learner-compare" as any) },
      { id: "nav.learner-errors", label: go(t(lang, "nav_learner_errors")), run: () => ui.setActiveNav("learner-errors" as any) },
      { id: "nav.arabic", label: go(t(lang, "nav_arabic_tools")), run: () => ui.setActiveNav("arabic" as any) },
      { id: "nav.assistant", label: go(t(lang, "nav_assistant")), run: () => ui.setActiveNav("assistant") },
      ...(student ? [] : [{ id: "nav.settings", label: go(t(lang, "nav_settings")), run: () => ui.setActiveNav("settings") }]),
      { id: "nav.userguide", label: go(t(lang, "nav_userguide")), run: () => ui.setActiveNav("userguide") },
      { id: "nav.about", label: go(t(lang, "nav_about")), run: () => ui.setActiveNav("about") },
      { id: "theme.light", label: t(lang, "cp_theme_light"), run: () => ui.setTheme("light") },
      { id: "theme.dark", label: t(lang, "cp_theme_dark"), run: () => ui.setTheme("dark") },
      { id: "theme.system", label: t(lang, "cp_theme_system"), run: () => ui.setTheme("system") },
      { id: "dir.ltr", label: t(lang, "cp_dir_ltr"), run: () => ui.setDir("ltr") },
      { id: "dir.rtl", label: t(lang, "cp_dir_rtl"), run: () => ui.setDir("rtl") },
      // v1.2.3: Smart Troubleshooting was Settings-only while muted — surface
      // it here too (open the panel and flip notifications in one action).
      {
        id: "troubleshoot.panel",
        label: t(lang, "cp_st_open"),
        run: () => useTroubleshoot.getState().setPanelOpen(true),
      },
      {
        id: "troubleshoot.mute",
        label: useTroubleshoot.getState().muted
          ? t(lang, "cp_st_unmute")
          : t(lang, "cp_st_mute"),
        run: () => {
          const ts = useTroubleshoot.getState();
          ts.setMuted(!ts.muted);
          if (ts.muted) ts.setPanelOpen(true); // unmuting → reveal the panel
        },
      },
    ];
  }, [ui, lang, go]);

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
          placeholder={t(lang, "cp_placeholder")}
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
          {filtered.length === 0 && <li className="cmdk-empty">{t(lang, "cp_no_match")}</li>}
        </ul>
      </div>
    </div>
  );
}
