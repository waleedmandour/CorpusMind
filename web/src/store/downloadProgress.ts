/**
 * Download progress store — global state for tracking reference corpus
 * downloads in the status bar.
 *
 * Any component can call setDownloadProgress() to update the progress,
 * and the status bar reads it to show a progress bar.
 */
import { create } from "zustand";

export interface DownloadProgress {
  name: string;
  displayName: string;
  status: "downloading" | "extracting" | "ingesting" | "installed" | "failed";
  message: string;
  progress: number; // 0-100
}

interface DownloadState {
  activeDownload: DownloadProgress | null;
  setDownloadProgress: (progress: DownloadProgress | null) => void;
  clearDownloadProgress: () => void;
}

export const useDownloadProgress = create<DownloadState>((set) => ({
  activeDownload: null,
  setDownloadProgress: (activeDownload) => set({ activeDownload }),
  clearDownloadProgress: () => set({ activeDownload: null }),
}));
