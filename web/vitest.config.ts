import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// v1.2.12-rc7: UI regression tests (npm run test:ui).
//
// Separate from vite.config.ts on purpose: the production build config wires
// the PWA plugin and dev-server proxy, none of which a jsdom test run should
// touch. Only the JSX transform and the same "@"/"@shared" aliases as the
// app build are mirrored here.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@shared": path.resolve(__dirname, "../shared"),
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
