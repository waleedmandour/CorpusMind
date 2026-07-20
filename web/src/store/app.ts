/**
 * Active corpus / project state. Persists to localStorage so a refresh
 * doesn't lose your place.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface AppState {
  activeProjectId: string | null;
  activeCorpusId: string | null;
  /** The corpus chosen as "reference" for keyness comparisons. */
  referenceCorpusId: string | null;
  /** The Ollama model selected via the "Load" button in Settings. */
  selectedOllamaModel: string | null;
  setActiveProject: (pid: string | null) => void;
  setActiveCorpus: (cid: string | null) => void;
  setReferenceCorpus: (cid: string | null) => void;
  setSelectedOllamaModel: (model: string | null) => void;
}

export const useApp = create<AppState>()(
  persist(
    (set) => ({
      activeProjectId: null,
      activeCorpusId: null,
      referenceCorpusId: null,
      selectedOllamaModel: null,
      setActiveProject: (activeProjectId) => set({ activeProjectId, activeCorpusId: null }),
      setActiveCorpus: (activeCorpusId) => set({ activeCorpusId }),
      setReferenceCorpus: (referenceCorpusId) => set({ referenceCorpusId }),
      setSelectedOllamaModel: (selectedOllamaModel) => set({ selectedOllamaModel }),
    }),
    { name: "corpusmind-app" },
  ),
);
