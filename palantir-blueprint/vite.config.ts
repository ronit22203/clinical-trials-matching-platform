import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy table: routes API calls through the Vite server so the browser never
// needs a direct connection to :8000/:8001.
// On RunPod, the pod proxy only exposes one port at a time; Vite (or the
// preview server) on :5173 forwards all /api/ingest* → ingestion API (:8001)
// and all other /api* → reasoning API (:8000), both reachable at localhost.
// Order matters — the more specific /api/ingest rule must come first.
const apiProxy = {
  "/api/ingest": {
    target: "http://localhost:8001",
    changeOrigin: true,
  },
  "/api": {
    target: "http://localhost:8000",
    changeOrigin: true,
  },
};

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",   // bind to all interfaces so RunPod proxy can reach it
    port: 5173,
    proxy: apiProxy,
  },
  preview: {
    host: "0.0.0.0",
    port: 4173,
    proxy: apiProxy,
  },
});
