import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@shared": path.resolve(__dirname, "../shared"),
    },
  },
  server: {
    port: 5173,
    strictPort: false,
    // Proxy API calls to the engine during local dev (production builds talk to
    // the engine directly via VITE_ENGINE_URL).
    proxy: {
      "/api": {
        target: process.env.VITE_ENGINE_URL ?? "http://127.0.0.1:8765",
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    target: "es2022",
    sourcemap: true,
    outDir: "dist",
    // v1.2.14 (P1.6): split the heavy graph stack (sigma ~600KB + graphology
    // + forceatlas2) into a network-only chunk so it lazy-loads on first
    // AnalysisView open. Cuts first paint of every other view by ~150ms.
    rollupOptions: {
      output: {
        manualChunks: {
          "graph-vendor": ["sigma", "graphology", "graphology-layout-forceatlas2"],
        },
      },
    },
  },
});
