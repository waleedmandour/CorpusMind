/**
 * Sidebar -- the primary navigation for CorpusMind.
 *
 * Professional, icon-driven navigation with clear visual hierarchy:
 *   - Brand header with logo + app name + version
 *   - Grouped sections with subtle labels and icons
 *   - Active state with brand-colored left border + tinted background
 *   - Hover states with smooth transitions
 *
 * All labels are translated via the i18n system.
 */
import clsx from "clsx";
import { useUI, type NavTarget } from "@/store/ui";
import { t, type TranslationKey } from "@/lib/i18n";

interface NavItem {
  id: NavTarget;
  labelKey: TranslationKey;
  icon: string;
}

interface NavGroup {
  labelKey: TranslationKey;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    labelKey: "nav_overview",
    items: [
      { id: "home", labelKey: "nav_home", icon: "\u2302" },
    ],
  },
  {
    labelKey: "nav_file",
    items: [
      { id: "file", labelKey: "nav_projects", icon: "\u25A4" },
      { id: "hub", labelKey: "nav_hub", icon: "\u25C8" },
    ],
  },
  {
    labelKey: "nav_analyze",
    items: [
      { id: "concordance", labelKey: "nav_concordance", icon: "\u2727" },
      { id: "frequency", labelKey: "nav_frequency", icon: "\u2111" },
      { id: "collocation", labelKey: "nav_collocation", icon: "\u2726" },
      { id: "keyness", labelKey: "nav_keyness", icon: "\u2605" },
      { id: "dispersion", labelKey: "nav_dispersion", icon: "\u2234" },
      { id: "ngrams", labelKey: "nav_ngrams", icon: "\u224B" },
      { id: "pos", labelKey: "nav_pos", icon: "\u2135" },
      { id: "grammar", labelKey: "nav_grammar", icon: "\u2699" },
      { id: "dependency", labelKey: "nav_dependency", icon: "\u2192" },
      { id: "discourse", labelKey: "nav_discourse", icon: "\u201D" },
      { id: "vocab", labelKey: "nav_vocab", icon: "\u4E00" },
      { id: "sentiment", labelKey: "nav_sentiment", icon: "\u263A" },
      { id: "metaphor", labelKey: "nav_metaphor", icon: "\u2248" },
    ],
  },
  {
    labelKey: "nav_arabic",
    items: [
      { id: "arabic", labelKey: "nav_arabic_tools", icon: "\u0639" },
    ],
  },
  {
    labelKey: "nav_vision",
    items: [
      { id: "vision", labelKey: "nav_vision_suite", icon: "\u25A3" },
    ],
  },
  {
    labelKey: "nav_ai",
    items: [
      { id: "assistant", labelKey: "nav_assistant", icon: "\u272B" },
    ],
  },
  {
    labelKey: "nav_system",
    items: [
      { id: "settings", labelKey: "nav_settings", icon: "\u2699" },
      { id: "userguide", labelKey: "nav_userguide", icon: "\u2139" },
      { id: "about", labelKey: "nav_about", icon: "\u24D8" },
    ],
  },
];

export function Sidebar() {
  const activeNav = useUI((s) => s.activeNav);
  const setActiveNav = useUI((s) => s.setActiveNav);
  const lang = useUI((s) => s.lang);

  return (
    <nav className="sidebar" role="navigation" aria-label="Main navigation">
      <div className="sidebar-logo">
        <img src="/icon-32.png" alt="CorpusMind" width="28" height="28" />
        <div className="sidebar-logo-text-group">
          <span className="sidebar-logo-text">CorpusMind</span>
          <span className="sidebar-logo-version">v0.1.0</span>
        </div>
      </div>
      <div className="sidebar-nav">
        {NAV_GROUPS.map((group) => (
          <div key={group.labelKey} className="sidebar-group">
            <div className="sidebar-group-label">{t(lang, group.labelKey)}</div>
            {group.items.map((item) => (
              <button
                key={item.id}
                className={clsx("sidebar-item", { active: activeNav === item.id })}
                onClick={() => setActiveNav(item.id)}
                title={t(lang, item.labelKey)}
                aria-current={activeNav === item.id ? "page" : undefined}
              >
                <span className="sidebar-item-icon" aria-hidden>{item.icon}</span>
                <span className="sidebar-item-label">{t(lang, item.labelKey)}</span>
              </button>
            ))}
          </div>
        ))}
      </div>
      <div className="sidebar-footer">
        <span className="sidebar-footer-text">AGPL-3.0</span>
        <span className="sidebar-footer-dot" />
        <span className="sidebar-footer-text">Local-first</span>
      </div>
    </nav>
  );
}
