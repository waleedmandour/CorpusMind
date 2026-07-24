/**
 * ConfirmDialog — a lightweight confirmation modal that replaces window.confirm().
 *
 * Why not use window.confirm()?
 *   1. Tauri 2 blocks it with "plugin:dialog|confirm not allowed by ACL"
 *   2. It's blocking and feels janky in a desktop app
 *   3. Can't be styled to match the app theme
 *
 * Usage:
 *   const [confirmState, setConfirmState] = useState<{msg: string; onConfirm: () => void} | null>(null);
 *   ...
 *   setConfirmState({ msg: "Delete this?", onConfirm: () => doDelete() });
 *   ...
 *   <ConfirmDialog state={confirmState} onClose={() => setConfirmState(null)} />
 */
import { useUI } from "@/store/ui";

interface ConfirmState {
  msg: string;
  onConfirm: () => void;
}

export function ConfirmDialog({ state, onClose }: { state: ConfirmState | null; onClose: () => void }) {
  const theme = useUI((s) => s.theme);
  if (!state) return null;

  return (
    <div
      className="confirm-overlay"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 10000,
      }}
      onClick={onClose}
    >
      <div
        className="confirm-dialog"
        style={{
          background: theme === "dark" ? "#161a21" : "#ffffff",
          border: `1px solid ${theme === "dark" ? "#3a424c" : "#d8dad8"}`,
          borderRadius: "8px",
          padding: "20px 24px",
          maxWidth: "400px",
          boxShadow: "0 8px 24px rgba(0,0,0,0.2)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <p style={{ margin: "0 0 16px 0", fontSize: "14px", lineHeight: 1.5, color: theme === "dark" ? "#e6e9ec" : "#1c1f1d" }}>
          {state.msg}
        </p>
        <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
          <button
            className="btn-small"
            onClick={onClose}
            style={{
              background: theme === "dark" ? "#2a3038" : "#eef0ee",
              color: theme === "dark" ? "#e6e9ec" : "#1c1f1d",
              border: "none",
              padding: "6px 16px",
              borderRadius: "4px",
              fontSize: "13px",
              cursor: "pointer",
            }}
          >
            Cancel
          </button>
          <button
            className="btn-small"
            onClick={() => {
              state.onConfirm();
              onClose();
            }}
            style={{
              background: "#c0392b",
              color: "#ffffff",
              border: "none",
              padding: "6px 16px",
              borderRadius: "4px",
              fontSize: "13px",
              cursor: "pointer",
            }}
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
}
