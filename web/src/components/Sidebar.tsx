/**
 * Sidebar -- the primary navigation for CorpusMind.
 *
 * Modernized design (2026-07):
 *   - Collapsible to icon-only rail (toggle button in header)
 *   - Active item: left accent bar + filled background + brand-color icon
 *   - Group headers: subtle, with chevron rotation animation
 *   - Smooth width transition when collapsing/expanding
 *   - Active corpus card with language badge
 *   - Footer with license + local-first indicator
 *
 * Groups:
 *   Overview      — Home
 *   Corpora       — Your Corpus + Reference Corpus
 *   Analysis Tools — Concordance, Frequency, Collocation, Keyness, etc.
 *   Arabic        — Arabic Tools
 *   Vision        — Vision Suite
 *   AI            — AI Assistant
 *   System        — Settings, User Guide, About
 */
import clsx from "clsx";
import { useUI, type NavTarget } from "@/store/ui";
import { useApp } from "@/store/app";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useEngineVersionDisplay } from "@/hooks/useEngineVersion";
import { t, type TranslationKey } from "@/lib/i18n";

interface NavItem {
  id: NavTarget;
  labelKey: TranslationKey;
  icon: string;
}

interface NavGroup {
  id: string;
  labelKey: TranslationKey;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    id: "overview",
    labelKey: "nav_overview",
    items: [
      { id: "home", labelKey: "nav_home", icon: "\u2302" },
    ],
  },
  {
    id: "corpora",
    labelKey: "nav_file",
    items: [
      { id: "corpus-target", labelKey: "nav_corpus_target", icon: "\u25A4" },
      { id: "corpus-reference", labelKey: "nav_corpus_reference", icon: "\u25C8" },
    ],
  },
  {
    id: "analyze",
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
    id: "arabic",
    labelKey: "nav_arabic",
    items: [
      { id: "arabic", labelKey: "nav_arabic_tools", icon: "\u0639" },
    ],
  },
  {
    id: "vision",
    labelKey: "nav_vision",
    items: [
      { id: "vision", labelKey: "nav_vision_suite", icon: "\u25A3" },
    ],
  },
  {
    id: "ai",
    labelKey: "nav_ai",
    items: [
      { id: "assistant", labelKey: "nav_assistant", icon: "\u272B" },
    ],
  },
  {
    id: "system",
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
  const expandedGroups = useUI((s) => s.expandedGroups);
  const toggleGroup = useUI((s) => s.toggleGroup);
  const sidebarCollapsed = useUI((s) => s.sidebarCollapsed);
  const toggleSidebar = useUI((s) => s.toggleSidebar);
  const activeCorpusId = useApp((s) => s.activeCorpusId);
  const versionDisplay = useEngineVersionDisplay();

  const activeCorpus = useQuery({
    queryKey: ["corpus", activeCorpusId],
    queryFn: () => activeCorpusId ? api.getCorpus(activeCorpusId) : Promise.resolve(null),
    enabled: !!activeCorpusId,
  });

  return (
    <nav
      className={clsx("sidebar", { "sidebar-collapsed": sidebarCollapsed })}
      role="navigation"
      aria-label="Main navigation"
    >
      {/* Logo + collapse toggle */}
      <div className="sidebar-header">
        <div className="sidebar-logo">
          <img src="/icon-32.png" alt="CorpusMind" width="28" height="28" />
          {!sidebarCollapsed && (
            <div className="sidebar-logo-text-group">
              <span className="sidebar-logo-text">CorpusMind</span>
              <span className="sidebar-logo-version">{versionDisplay}</span>
            </div>
          )}
        </div>
        <button
          className="sidebar-collapse-btn"
          onClick={toggleSidebar}
          title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {sidebarCollapsed ? "\u25B6" : "\u25C0"}
        </button>
      </div>

      {/* Active corpus card */}
      {activeCorpus.data && !sidebarCollapsed && (
        <div className="sidebar-active-corpus">
          <div className="sidebar-active-corpus-label">Active Corpus</div>
          <div className="sidebar-active-corpus-name">{activeCorpus.data.name}</div>
          <div className="sidebar-active-corpus-meta">
            <span className="sidebar-lang-badge">{activeCorpus.data.language.toUpperCase()}</span>
            {(activeCorpus.data.stats?.token_count ?? 0).toLocaleString()} tokens
          </div>
        </div>
      )}

      {/* Navigation */}
      <div className="sidebar-nav">
        {NAV_GROUPS.map((group) => {
          const isExpanded = expandedGroups[group.id] ?? true;
          const hasActiveItem = group.items.some((item) => item.id === activeNav);

          return (
            <div key={group.id} className="sidebar-group">
              {!sidebarCollapsed && (
                <button
                  className={clsx("sidebar-group-header", { "has-active": hasActiveItem })}
                  onClick={() => toggleGroup(group.id)}
                  aria-expanded={isExpanded}
                >
                  <span className={clsx("sidebar-group-chevron", { expanded: isExpanded })}>
                    {"\u25B8"}
                  </span>
                  <span className="sidebar-group-label">{t(lang, group.labelKey)}</span>
                </button>
              )}
              {(sidebarCollapsed || isExpanded) && (
                <div className="sidebar-group-items">
                  {group.items.map((item) => (
                    <button
                      key={item.id}
                      className={clsx("sidebar-item", { active: activeNav === item.id })}
                      onClick={() => setActiveNav(item.id)}
                      title={t(lang, item.labelKey)}
                      aria-current={activeNav === item.id ? "page" : undefined}
                      aria-label={t(lang, item.labelKey)}
                    >
                      <span className="sidebar-item-icon" aria-hidden>{item.icon}</span>
                      {!sidebarCollapsed && (
                        <span className="sidebar-item-label">{t(lang, item.labelKey)}</span>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Footer */}
      {!sidebarCollapsed ? (
        <div className="sidebar-footer">
          <span className="sidebar-footer-text">AGPL-3.0</span>
          <span className="sidebar-footer-dot" />
          <span className="sidebar-footer-text">Local-first</span>
        </div>
      ) : (
        <div className="sidebar-footer sidebar-footer-collapsed" title="AGPL-3.0 · Local-first">
          <span className="sidebar-footer-dot" />
        </div>
      )}
    </nav>
  );
}
