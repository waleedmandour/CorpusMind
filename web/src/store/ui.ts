/**
 * UI store -- theme, language/dir, sidebar navigation, onboarding,
 * collapsible sidebar groups.
 *
 * Theme + expandedGroups are persisted to localStorage; dir is auto-detected
 * from the user's preferred language (Arabic -> RTL, everything else -> LTR)
 * and can be flipped at runtime for bilingual workflows (section 13.3).
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";

type Theme = "light" | "dark" | "system";
type Dir = "ltr" | "rtl";
type Lang = "en" | "ar";

// v1.2.0: the parent-app "vision" tab is gone (the Lens companion owns the
// vision workbench; the engine vision endpoints stay). Added "vector-kwic"
// (semantic KWIC, bge-m3) and the three Learner Research tools.
export type NavTarget =
  | "home" | "corpus-target" | "corpus-reference" | "concordance" | "frequency" | "collocation"
  | "keyness" | "dispersion" | "ngrams" | "pos" | "grammar" | "dependency"
  | "discourse" | "vocab" | "sentiment" | "metaphor"
  | "vector-kwic"
  | "learner-caf" | "learner-compare" | "learner-errors"
  | "arabic" | "assistant" | "settings" | "about" | "userguide";

interface UIState {
  theme: Theme;
  dir: Dir;
  lang: Lang;
  commandPaletteOpen: boolean;
  /** v1.2.0: floating AI assistant drawer (Issue 7b) */
  floatingAssistantOpen: boolean;
  activeNav: NavTarget;
  onboardingComplete: boolean;
  onboardingOpen: boolean;
  /** Which sidebar groups are expanded. Persisted so the user's
   * collapse/expand preference survives app restarts. */
  expandedGroups: Record<string, boolean>;
  /** Whether the sidebar is in collapsed (icon-only) mode. Persisted. */
  sidebarCollapsed: boolean;
  /** Student mode: hides the AI Assistant until the student has done
   * their own interpretation. Prevents over-reliance while still
   * teaching the tools. Persisted to localStorage. */
  studentMode: boolean;
  setTheme: (t: Theme) => void;
  toggleTheme: () => void;
  setDir: (d: Dir) => void;
  toggleDir: () => void;
  setLang: (l: Lang) => void;
  toggleLang: () => void;
  setCommandPaletteOpen: (open: boolean) => void;
  setFloatingAssistantOpen: (open: boolean) => void;
  setActiveNav: (nav: NavTarget) => void;
  setOnboardingComplete: (done: boolean) => void;
  setOnboardingOpen: (open: boolean) => void;
  toggleGroup: (groupId: string) => void;
  setGroupExpanded: (groupId: string, expanded: boolean) => void;
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  setStudentMode: (enabled: boolean) => void;
}

/** v1.2.1: the CorpusMind Lens shell now lives in its own repository
 * (waleedmandour/CorpusMind-Lens) with its own frontend, so the
 * ?shell=lens mode, LENS_NAV_TARGETS guard, and isLensMode flag have been
 * removed from this codebase. This app is always the main CorpusMind app. */

export const useUI = create<UIState>()(
  persist(
    (set, get) => ({
      theme: "system",
      dir: "ltr",
      lang: "en",
      commandPaletteOpen: false,
      floatingAssistantOpen: false,
      activeNav: "home",
      onboardingComplete: false,
      onboardingOpen: false,
      // Default expand state: Corpora + Analyze expanded; others collapsed.
      // This follows the linguist workflow: load data first, then pick a tool.
      expandedGroups: {
        corpora: true,
        analyze: true,
        learner: true, // v1.2.0: new group — expanded so it gets discovered
        arabic: false,
        ai: false,
        system: false,
      },
      sidebarCollapsed: false,
      studentMode: false,
      setTheme: (theme) => set({ theme }),
      toggleTheme: () => {
        const current = get().theme;
        const resolved = current === "system"
          ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
          : current;
        set({ theme: resolved === "dark" ? "light" : "dark" });
      },
      setDir: (dir) => set({ dir }),
      toggleDir: () => set({ dir: get().dir === "ltr" ? "rtl" : "ltr" }),
      setLang: (lang) => set({ lang, dir: lang === "ar" ? "rtl" : "ltr" }),
      toggleLang: () => {
        const newLang = get().lang === "en" ? "ar" : "en";
        set({ lang: newLang, dir: newLang === "ar" ? "rtl" : "ltr" });
      },
      setCommandPaletteOpen: (open) => set({ commandPaletteOpen: open }),
      setFloatingAssistantOpen: (open) => set({ floatingAssistantOpen: open }),
      setActiveNav: (activeNav) => set({ activeNav }),
      setOnboardingComplete: (onboardingComplete) => set({ onboardingComplete }),
      setOnboardingOpen: (onboardingOpen) => set({ onboardingOpen }),
      toggleGroup: (groupId) =>
        set((state) => ({
          expandedGroups: {
            ...state.expandedGroups,
            [groupId]: !state.expandedGroups[groupId],
          },
        })),
      setGroupExpanded: (groupId, expanded) =>
        set((state) => ({
          expandedGroups: {
            ...state.expandedGroups,
            [groupId]: expanded,
          },
        })),
      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      setSidebarCollapsed: (sidebarCollapsed) => set({ sidebarCollapsed }),
      setStudentMode: (studentMode) => set({ studentMode }),
    }),
    {
      name: "corpusmind-ui",
      // v1.0.7 (version bump + migrate): activeNav is NEVER persisted anymore —
      // the app must open on its default view at every launch (Home for the
      // main app, Vision for Lens). Old payloads carried a persisted
      // activeNav, so the migration drops it once on first load.
      version: 1,
      migrate: (persisted, version) => {
        const p = { ...((persisted ?? {}) as Record<string, unknown>) };
        if (version < 1) delete p.activeNav;
        return p as unknown as UIState;
      },
      partialize: (state) => {
        // activeNav is never persisted — the app must open on its default
        // view (Home) at every launch (see version note above).
        const { activeNav, ...rest } = state;
        void activeNav;
        return rest;
      },
    },
  ),
);

/** Apply theme + dir + lang to <html>. Called from App. */
export function applyHtmlAttrs() {
  const { theme, dir, lang } = useUI.getState();

  const resolved =
    theme === "system"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
      : theme;

  document.documentElement.dataset.theme = resolved;
  document.documentElement.dir = dir;
  document.documentElement.lang = lang;
}
