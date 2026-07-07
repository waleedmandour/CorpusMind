import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.svg", "robots.txt", "icon-192.png", "icon-512.png"],
      manifest: {
        name: "CorpusMind",
        short_name: "CorpusMind",
        description:
          "Local-first, AI-native research environment for corpus linguistics and multimodal discourse analysis.",
        theme_color: "#0b6e4f",
        background_color: "#0e1116",
        display: "standalone",
        orientation: "any",
        start_url: "/",
        scope: "/",
        lang: "en",
        // UI mirrors document direction (LTR/RTL) — see §13.3. Manifest doesn't accept "auto",
        // so we default to "ltr" and flip the <html dir> attribute at runtime via the UI store.
        icons: [
          { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any maskable" },
          { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any maskable" },
        ],
        categories: ["education", "productivity", "science"],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,png,ico,woff,woff2}"],
        // Conservative runtime caching — never cache API responses by default,
        // because corpus data is sensitive and should always be fetched fresh
        // from the engine (§4 Principle 1).
        runtimeCaching: [
          {
            urlPattern: ({ url }) => url.pathname.startsWith("/api/"),
            handler: "NetworkOnly",
          },
          {
            urlPattern: ({ request }) => request.destination === "image",
            handler: "CacheFirst",
            options: {
              cacheName: "corpusmind-images",
              expiration: { maxEntries: 60, maxAgeSeconds: 60 * 60 * 24 * 7 },
            },
          },
        ],
      },
      devOptions: {
        enabled: true,
        type: "module",
      },
    }),
  ],
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
  },
});
