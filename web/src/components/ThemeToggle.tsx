/**
 * ThemeToggle -- a compact light/dark theme switch for the titlebar.
 *
 * Shows a sun icon in dark mode (click to switch to light) and a moon icon
 * in light mode (click to switch to dark). Resolves "system" to the actual
 * mode before toggling.
 */
import { useUI } from "@/store/ui";

export function ThemeToggle() {
  const theme = useUI((s) => s.theme);
  const toggleTheme = useUI((s) => s.toggleTheme);

  const resolved = theme === "system"
    ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    : theme;

  const isDark = resolved === "dark";

  return (
    <button
      className="theme-toggle"
      onClick={toggleTheme}
      title={isDark ? "Switch to light theme" : "Switch to dark theme"}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
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
