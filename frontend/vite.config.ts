import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The in-app guides are the Markdown files in ../docs/guides (bundled at build time).
const repoRoot = fileURLToPath(new URL("..", import.meta.url));

// The API runs on 8420 by default; the dev server proxies /api and /ws to it.
const target = process.env.PATHSCOPE_API_URL || "http://127.0.0.1:8420";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false,
    fs: { allow: [repoRoot] },
    proxy: {
      "/api": { target, changeOrigin: true },
      "/ws": { target: target.replace(/^http/, "ws"), ws: true, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 1500,
  },
  test: {
    environment: "node",
  },
});
