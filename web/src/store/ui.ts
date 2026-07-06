/**
 * UI store -- theme, language/dir, sidebar navigation, onboarding.
 *
 * Theme is persisted to localStorage; dir is auto-detected from the user's
 * preferred language (Arabic -> RTL, everything else -> LTR) and can be
 * flipped at runtime for bilingual workflows (section 13.3).
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";

type Theme = "light" | "dark" | "system";
type Dir = "ltr" | "rtl";
type Lang = "en" | "ar";

export type NavTarget =
  | "home" | "file" | "concordance" | "frequency" | "collocation"
  | "keyness" | "dispersion" | "ngrams" | "pos" | "grammar" | "dependency"
  | "discourse" | "vocab" | "sentiment" | "metaphor"
  | "arabic" | "vision" | "assistant" | "settings" | "about";

interface UIState {
  theme: Theme;
  dir: Dir;
  lang: Lang;
  commandPaletteOpen: boolean;
  activeNav: NavTarget;
  onboardingComplete: boolean;
  onboardingOpen: boolean;
  setTheme: (t: Theme) => void;
  toggleTheme: () => void;
  setDir: (d: Dir) => void;
  toggleDir: () => void;
  setLang: (l: Lang) => void;
  toggleLang: () => void;
  setCommandPaletteOpen: (open: boolean) => void;
  setActiveNav: (nav: NavTarget) => void;
  setOnboardingComplete: (done: boolean) => void;
  setOnboardingOpen: (open: boolean) => void;
}

export const useUI = create<UIState>()(
  persist(
    (set, get) => ({
      theme: "system",
      dir: "ltr",
      lang: "en",
      commandPaletteOpen: false,
      activeNav: "home",
      onboardingComplete: false,
      onboardingOpen: false,
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
      setActiveNav: (activeNav) => set({ activeNav }),
      setOnboardingComplete: (onboardingComplete) => set({ onboardingComplete }),
      setOnboardingOpen: (onboardingOpen) => set({ onboardingOpen }),
    }),
    { name: "corpusmind-ui" },
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
