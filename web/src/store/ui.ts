/**
 * UI store -- theme, language/dir, ribbon state, onboarding.
 *
 * Theme is persisted to localStorage; dir is auto-detected from the user's
 * preferred language (Arabic -> RTL, everything else -> LTR) and can be
 * flipped at runtime for bilingual workflows (section 13.3).
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";

type Theme = "light" | "dark" | "system";
type Dir = "ltr" | "rtl";

interface UIState {
  theme: Theme;
  dir: Dir;
  commandPaletteOpen: boolean;
  activeTab: "text" | "vision" | "assistant" | "settings" | "arabic";
  onboardingComplete: boolean;
  onboardingOpen: boolean;
  setTheme: (t: Theme) => void;
  toggleTheme: () => void;
  setDir: (d: Dir) => void;
  toggleDir: () => void;
  setCommandPaletteOpen: (open: boolean) => void;
  setActiveTab: (tab: UIState["activeTab"]) => void;
  setOnboardingComplete: (done: boolean) => void;
  setOnboardingOpen: (open: boolean) => void;
}

export const useUI = create<UIState>()(
  persist(
    (set, get) => ({
      theme: "system",
      dir: "ltr",
      commandPaletteOpen: false,
      activeTab: "assistant",
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
      setCommandPaletteOpen: (open) => set({ commandPaletteOpen: open }),
      setActiveTab: (activeTab) => set({ activeTab }),
      setOnboardingComplete: (onboardingComplete) => set({ onboardingComplete }),
      setOnboardingOpen: (onboardingOpen) => set({ onboardingOpen }),
    }),
    { name: "corpusmind-ui" },
  ),
);

/** Apply theme + dir to <html>. Called from App. */
export function applyHtmlAttrs() {
  const { theme, dir } = useUI.getState();

  const resolved =
    theme === "system"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
      : theme;

  document.documentElement.dataset.theme = resolved;
  document.documentElement.dir = dir;
  document.documentElement.lang = dir === "rtl" ? "ar" : "en";
}
