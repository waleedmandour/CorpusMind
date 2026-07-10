/**
 * Sidebar -- the primary navigation for CorpusMind.
 *
 * Shows the app icon at the top, followed by grouped navigation items.
 * All labels are translated via the i18n system.
 */
import clsx from "clsx";
import { useUI, type NavTarget } from "@/store/ui";
import { t, type TranslationKey } from "@/lib/i18n";

interface NavItem {
  id: NavTarget;
  labelKey: TranslationKey;
}

interface NavGroup {
  labelKey: TranslationKey;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    labelKey: "nav_overview",
    items: [{ id: "home", labelKey: "nav_home" }],
  },
  {
    labelKey: "nav_file",
    items: [{ id: "file", labelKey: "nav_projects" }],
  },
  {
    labelKey: "nav_analyze",
    items: [
      { id: "concordance", labelKey: "nav_concordance" },
      { id: "frequency", labelKey: "nav_frequency" },
      { id: "collocation", labelKey: "nav_collocation" },
      { id: "keyness", labelKey: "nav_keyness" },
      { id: "dispersion", labelKey: "nav_dispersion" },
      { id: "ngrams", labelKey: "nav_ngrams" },
      { id: "pos", labelKey: "nav_pos" },
      { id: "grammar", labelKey: "nav_grammar" },
      { id: "dependency", labelKey: "nav_dependency" },
      { id: "discourse", labelKey: "nav_discourse" },
      { id: "vocab", labelKey: "nav_vocab" },
      { id: "sentiment", labelKey: "nav_sentiment" },
      { id: "metaphor", labelKey: "nav_metaphor" },
    ],
  },
  {
    labelKey: "nav_arabic",
    items: [{ id: "arabic", labelKey: "nav_arabic_tools" }],
  },
  {
    labelKey: "nav_vision",
    items: [{ id: "vision", labelKey: "nav_vision_suite" }],
  },
  {
    labelKey: "nav_ai",
    items: [{ id: "assistant", labelKey: "nav_assistant" }],
  },
  {
    labelKey: "nav_system",
    items: [
      { id: "settings", labelKey: "nav_settings" },
      { id: "userguide", labelKey: "nav_userguide" },
      { id: "about", labelKey: "nav_about" },
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
        <img src="/icon-32.png" alt="CorpusMind" width="32" height="32" />
        <span className="sidebar-logo-text">CorpusMind</span>
      </div>
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
              <span className="sidebar-item-label">{t(lang, item.labelKey)}</span>
            </button>
          ))}
        </div>
      ))}
    </nav>
  );
}
