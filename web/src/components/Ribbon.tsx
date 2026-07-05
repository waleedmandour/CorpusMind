/**
 * Ribbon — Office-style top navigation (§8.25, §10.3).
 *
 * Phase 0 ships the shell with File / Text / Vision / Assistant / View tabs.
 * Most tabs are placeholders that render "Coming in Phase N" — the goal of
 * the shell is to give every later feature a home to land in, not to ship
 * the features themselves yet.
 */
import { useUI } from "@/store/ui";
import clsx from "clsx";

type TabId = "file" | "text" | "vision" | "assistant" | "view";
type UIActiveTab = "text" | "vision" | "assistant" | "settings";

interface RibbonTab {
  id: TabId;
  label: string;
  /** Phase when this tab's primary features land. */
  phase: string;
  groups: RibbonGroup[];
}

interface RibbonGroup {
  label: string;
  items: RibbonItem[];
}

interface RibbonItem {
  label: string;
  hint?: string;
  /** Phase when this specific item is implemented. */
  phase: string;
  disabled?: boolean;
  onClick?: () => void;
}

const TABS: RibbonTab[] = [
  {
    id: "file",
    label: "File",
    phase: "Phase 0",
    groups: [
      {
        label: "Project",
        items: [
          { label: "New Project", phase: "Phase 1", disabled: true },
          { label: "Open…", phase: "Phase 1", disabled: true },
          { label: "Recent", phase: "Phase 1", disabled: true },
        ],
      },
      {
        label: "Export",
        items: [
          { label: "Methods Section", phase: "Phase 1", hint: "Auto-draft a methodology paragraph", disabled: true },
          { label: "Excel", phase: "Phase 1", disabled: true },
          { label: "PDF", phase: "Phase 1", disabled: true },
        ],
      },
    ],
  },
  {
    id: "text",
    label: "Text Suite",
    phase: "Phase 1",
    groups: [
      {
        label: "Ingest",
        items: [
          { label: "Upload Corpus", phase: "Phase 1", disabled: true },
          { label: "Pipeline Recipe", phase: "Phase 1", disabled: true },
        ],
      },
      {
        label: "Analyze",
        items: [
          { label: "Concordance", phase: "Phase 1", disabled: true },
          { label: "Frequency", phase: "Phase 1", disabled: true },
          { label: "Collocation", phase: "Phase 1", disabled: true },
          { label: "Keyness", phase: "Phase 1", disabled: true },
          { label: "N-grams", phase: "Phase 2", disabled: true },
          { label: "Dispersion", phase: "Phase 2", disabled: true },
        ],
      },
      {
        label: "Arabic",
        items: [
          { label: "Morphology", phase: "Phase 3", disabled: true },
          { label: "Dialect ID", phase: "Phase 3", disabled: true },
        ],
      },
    ],
  },
  {
    id: "vision",
    label: "Vision Suite",
    phase: "Phase 4",
    groups: [
      {
        label: "Image",
        items: [
          { label: "Import Image Set", phase: "Phase 4", disabled: true },
          { label: "OCR", phase: "Phase 4", disabled: true },
        ],
      },
      {
        label: "Multimodal",
        items: [
          { label: "Image–Text Alignment", phase: "Phase 4", disabled: true },
          { label: "Visual Grammar", phase: "Phase 4", disabled: true, hint: "Kress & van Leeuwen" },
        ],
      },
    ],
  },
  {
    id: "assistant",
    label: "AI Assistant",
    phase: "Phase 0",
    groups: [
      {
        label: "Chat",
        items: [{ label: "New Conversation", phase: "Phase 0", onClick: () => useUI.getState().setActiveTab("assistant") }],
      },
      {
        label: "Tools",
        items: [{ label: "Inspect Tools", phase: "Phase 0", onClick: () => useUI.getState().setActiveTab("assistant") }],
      },
    ],
  },
  {
    id: "view",
    label: "View",
    phase: "Phase 0",
    groups: [
      {
        label: "Theme",
        items: [
          { label: "Light", phase: "Phase 0", onClick: () => useUI.getState().setTheme("light") },
          { label: "Dark", phase: "Phase 0", onClick: () => useUI.getState().setTheme("dark") },
          { label: "System", phase: "Phase 0", onClick: () => useUI.getState().setTheme("system") },
        ],
      },
      {
        label: "Direction",
        items: [
          { label: "LTR", phase: "Phase 0", onClick: () => useUI.getState().setDir("ltr") },
          { label: "RTL", phase: "Phase 0", onClick: () => useUI.getState().setDir("rtl") },
        ],
      },
      {
        label: "Command Palette",
        items: [
          { label: "Open (Ctrl+K)", phase: "Phase 0", onClick: () => useUI.getState().setCommandPaletteOpen(true) },
        ],
      },
    ],
  },
];

export function Ribbon() {
  // We only render the active tab's groups; the tab strip itself is always visible.
  const activeTab = useUI().activeTab as UIActiveTab;
  const setActiveTab = useUI((s) => s.setActiveTab);

  // Map our store's activeTab (which uses 'text'/'vision'/'assistant'/'settings')
  // onto the ribbon's tab ids.
  const ribbonTab: TabId = activeTab === "settings" ? "view" : (activeTab as TabId);

  const current = TABS.find((t) => t.id === ribbonTab) ?? TABS[0];

  return (
    <div className="ribbon">
      <div className="ribbon-tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={clsx("ribbon-tab", { active: t.id === current.id })}
            onClick={() => {
              if (t.id === "assistant") setActiveTab("assistant");
              else if (t.id === "view") setActiveTab("settings");
              else if (t.id === "text") setActiveTab("text");
              else if (t.id === "vision") setActiveTab("vision");
              else setActiveTab("assistant");
            }}
            title={`${t.label} — ${t.phase}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="ribbon-groups">
        {current.groups.map((g) => (
          <div key={g.label} className="ribbon-group">
            <div className="ribbon-group-items">
              {g.items.map((item) => (
                <button
                  key={item.label}
                  className="ribbon-item"
                  disabled={item.disabled}
                  onClick={item.onClick}
                  title={item.hint ?? `${item.label} (${item.phase})`}
                >
                  <span className="ribbon-item-label">{item.label}</span>
                  <span className="ribbon-item-phase">{item.phase}</span>
                </button>
              ))}
            </div>
            <div className="ribbon-group-label">{g.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
