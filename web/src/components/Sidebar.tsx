/**
 * Sidebar -- the primary navigation for CorpusMind.
 *
 * Replaces the old ribbon + top-tab system with a clean left sidebar
 * organized into logical groups. Each item has an icon + label.
 *
 * Groups:
 *   - Overview: Home
 *   - File: Projects, Corpora, Documents (the CorpusManagerView)
 *   - Analyze: Concordance, Frequency, Collocation, Keyness, Dispersion,
 *     N-grams, POS, Grammar, Dependency, Discourse, Vocabulary,
 *     Sentiment, Metaphor
 *   - Arabic: Morphology, Dialect, Roots, etc. (ArabicView)
 *   - Vision: Image Analysis, Visual Grammar, Alignment, Discourse
 *   - AI: Assistant
 *   - System: Settings, About
 */
import clsx from "clsx";
import { useUI, type NavTarget } from "@/store/ui";

interface NavItem {
  id: NavTarget;
  label: string;
  icon: string;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    label: "Overview",
    items: [
      { id: "home", label: "Home", icon: "\u25C6" },
    ],
  },
  {
    label: "File",
    items: [
      { id: "file", label: "Projects", icon: "\u2630" },
    ],
  },
  {
    label: "Analyze",
    items: [
      { id: "concordance", label: "Concordance", icon: "\u2727" },
      { id: "frequency", label: "Frequency", icon: "\u2727" },
      { id: "collocation", label: "Collocation", icon: "\u2727" },
      { id: "keyness", label: "Keyness", icon: "\u2727" },
      { id: "dispersion", label: "Dispersion", icon: "\u2727" },
      { id: "ngrams", label: "N-grams", icon: "\u2727" },
      { id: "pos", label: "POS Analysis", icon: "\u2727" },
      { id: "grammar", label: "Grammar", icon: "\u2727" },
      { id: "dependency", label: "Dependency", icon: "\u2727" },
      { id: "discourse", label: "Discourse", icon: "\u2727" },
      { id: "vocab", label: "Vocabulary", icon: "\u2727" },
      { id: "sentiment", label: "Sentiment", icon: "\u2727" },
      { id: "metaphor", label: "Metaphor", icon: "\u2727" },
    ],
  },
  {
    label: "Arabic",
    items: [
      { id: "arabic", label: "Arabic Tools", icon: "\u272A" },
    ],
  },
  {
    label: "Vision",
    items: [
      { id: "vision", label: "Vision Suite", icon: "\u2728" },
    ],
  },
  {
    label: "AI",
    items: [
      { id: "assistant", label: "AI Assistant", icon: "\u272B" },
    ],
  },
  {
    label: "System",
    items: [
      { id: "settings", label: "Settings", icon: "\u2699" },
      { id: "about", label: "About", icon: "\u2139" },
    ],
  },
];

export function Sidebar() {
  const activeNav = useUI((s) => s.activeNav);
  const setActiveNav = useUI((s) => s.setActiveNav);

  return (
    <nav className="sidebar" role="navigation" aria-label="Main navigation">
      {NAV_GROUPS.map((group) => (
        <div key={group.label} className="sidebar-group">
          <div className="sidebar-group-label">{group.label}</div>
          {group.items.map((item) => (
            <button
              key={item.id}
              className={clsx("sidebar-item", { active: activeNav === item.id })}
              onClick={() => setActiveNav(item.id)}
              title={item.label}
              aria-current={activeNav === item.id ? "page" : undefined}
            >
              <span className="sidebar-item-icon" aria-hidden>{item.icon}</span>
              <span className="sidebar-item-label">{item.label}</span>
            </button>
          ))}
        </div>
      ))}
    </nav>
  );
}
