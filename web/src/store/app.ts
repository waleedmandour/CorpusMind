/**
 * Active corpus / project state. Persists to localStorage so a refresh
 * doesn't lose your place.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface AppState {
  activeProjectId: string | null;
  activeCorpusId: string | null;
  /** The corpus chosen as "reference" for keyness comparisons (uploaded corpus). */
  referenceCorpusId: string | null;
  /** v0.1.17: The name of an installed bundled reference frequency list
   *  (e.g. "be06-top1000"). Used for keyness via /keyness-with-reference/
   *  endpoint. This is separate from referenceCorpusId because bundled
   *  references are frequency lists, not Corpus rows in the DB. */
  selectedReferenceName: string | null;
  /** The Ollama model selected via the "Load" button in Settings. */
  selectedOllamaModel: string | null;
  setActiveProject: (pid: string | null) => void;
  setActiveCorpus: (cid: string | null) => void;
  setReferenceCorpus: (cid: string | null) => void;
  setSelectedReferenceName: (name: string | null) => void;
  setSelectedOllamaModel: (model: string | null) => void;
}

export const useApp = create<AppState>()(
  persist(
    (set) => ({
      activeProjectId: null,
      activeCorpusId: null,
      referenceCorpusId: null,
      selectedReferenceName: null,
      selectedOllamaModel: null,
      setActiveProject: (activeProjectId) => set({ activeProjectId, activeCorpusId: null }),
      setActiveCorpus: (activeCorpusId) => set({ activeCorpusId }),
      setReferenceCorpus: (referenceCorpusId) => set({ referenceCorpusId }),
      setSelectedReferenceName: (selectedReferenceName) => set({ selectedReferenceName }),
      setSelectedOllamaModel: (selectedOllamaModel) => set({ selectedOllamaModel }),
    }),
    { name: "corpusmind-app" },
  ),
);
