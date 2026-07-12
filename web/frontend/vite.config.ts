import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

// `npm run build` emits straight into the Python package's static dir, so
// `fcapz-web` serves the built app (and it ships in the wheel as package data).
// `npm run dev` proxies /api (REST + WebSocket) to the backend on :7373.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: fileURLToPath(new URL("../../host/fcapz/web/static", import.meta.url)),
    emptyOutDir: true,
    // Stable, non-hashed filenames so a rebuild overwrites the same files
    // (clean `M assets/index.js` in git instead of hash-rename churn). Served
    // locally with ETag revalidation, so cache-busting hashes aren't needed.
    rollupOptions: {
      output: {
        entryFileNames: "assets/[name].js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/[name][extname]",
      },
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:7373",
        changeOrigin: true,
        ws: true,
      },
      // The Surfer viewer iframe (/surfer/index.html) is mounted by the
      // backend, not built by Vite — without this the Viewer tab is blank in dev.
      "/surfer": {
        target: "http://127.0.0.1:7373",
        changeOrigin: true,
      },
    },
  },
});
