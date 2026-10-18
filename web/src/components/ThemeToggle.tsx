/**
 * ThemeToggle -- a compact light/dark theme switch for the titlebar.
 *
 * Shows a sun icon in dark mode (click to switch to light) and a moon icon
 * in light mode (click to switch to dark). Resolves "system" to the actual
 * mode before toggling.
 */
import { useUI } from "@/store/ui";
import { t } from "@/lib/i18n";

export function ThemeToggle() {
  const theme = useUI((s) => s.theme);
  const toggleTheme = useUI((s) => s.toggleTheme);
  // v1.2.14-7 (r7): title/aria labels follow the active UI language.
  const lang = useUI((s) => s.lang);

  const resolved = theme === "system"
    ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    : theme;

  const isDark = resolved === "dark";

  return (
    <button
      className="theme-toggle"
      onClick={toggleTheme}
      title={isDark ? t(lang, "theme_to_light") : t(lang, "theme_to_dark")}
      aria-label={isDark ? t(lang, "theme_to_light") : t(lang, "theme_to_dark")}
      role="switch"
      aria-checked={isDark}
    >
      <span className="theme-toggle-track">
        <span className={`theme-toggle-thumb ${isDark ? "dark" : "light"}`}>
          {isDark ? "\u263D" : "\u2600"}
        </span>
      </span>
    </button>
  );
}
