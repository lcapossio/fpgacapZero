import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

// `npm run build` emits straight into the Python package's static dir, so
// `fcapz-web` serves the built app (and it ships in the wheel as package data).
// `npm run dev` proxies /api (REST + WebSocket) to the backend on :8000.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: fileURLToPath(new URL("../../host/fcapz/web/static", import.meta.url)),
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
