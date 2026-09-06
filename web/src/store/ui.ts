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

export type NavTarget =
  | "home" | "corpus-target" | "corpus-reference" | "concordance" | "frequency" | "collocation"
  | "keyness" | "dispersion" | "ngrams" | "pos" | "grammar" | "dependency"
  | "discourse" | "vocab" | "sentiment" | "metaphor"
  | "arabic" | "vision" | "assistant" | "settings" | "about" | "userguide";

interface UIState {
  theme: Theme;
  dir: Dir;
  lang: Lang;
  commandPaletteOpen: boolean;
  /** v1.2.0: floating AI assistant drawer (Issue 7b) */
  floatingAssistantOpen: boolean;
  activeNav: NavTarget;
  /** Whether we're running inside the CorpusMind Lens shell (vs the
   * main CorpusMind app). Detected from the ?shell=lens URL query param
   * that the Lens Tauri shell passes. In Lens mode, the sidebar shows
   * only vision-relevant items and the app defaults to the Vision view. */
  isLensMode: boolean;
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

/** Detect whether we're running inside the Lens Tauri shell by checking
 * the ?shell=lens URL query param. The Lens shell's tauri.conf.json sets
 * the window URL to "index.html?shell=lens" so this works in both dev
 * and production. In browser/PWA mode (no ?shell param), this returns
 * false — the full CorpusMind UI is shown. */
function detectLensMode(): boolean {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).get("shell") === "lens";
}

/** v1.0.9: navigation targets the Lens shell actually exposes. The sidebar
 * filtered these visually before, but setActiveNav still accepted any
 * target — so Home quick-action cards (and any stray call) could open the
 * full text-analysis views that Lens deliberately hides. The guard makes
 * the Lens boundary real: out-of-scope targets are redirected to vision. */
const LENS_NAV_TARGETS: ReadonlySet<NavTarget> = new Set<NavTarget>([
  "home", "corpus-target", "vision", "assistant", "settings", "userguide", "about",
]);

export const useUI = create<UIState>()(
  persist(
    (set, get) => ({
      theme: "system",
      dir: "ltr",
      lang: "en",
      commandPaletteOpen: false,
      floatingAssistantOpen: false,
      // In Lens mode, default to the Vision view instead of Home.
      activeNav: detectLensMode() ? "vision" : "home",
      isLensMode: detectLensMode(),
      onboardingComplete: false,
      onboardingOpen: false,
      // Default expand state: Corpora + Analyze expanded; others collapsed.
      // This follows the linguist workflow: load data first, then pick a tool.
      expandedGroups: {
        corpora: true,
        analyze: true,
        arabic: false,
        vision: false,
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
      setActiveNav: (activeNav) => {
        // v1.0.9: enforce the Lens navigation boundary (see LENS_NAV_TARGETS).
        if (get().isLensMode && !LENS_NAV_TARGETS.has(activeNav)) {
          set({ activeNav: "vision" });
          return;
        }
        set({ activeNav });
      },
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
        // Don't persist isLensMode — it's always re-detected from the URL
        // query param (?shell=lens) on each load. activeNav is likewise
        // never persisted (see version note above).
        const { isLensMode, activeNav, ...rest } = state;
        void isLensMode;
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
