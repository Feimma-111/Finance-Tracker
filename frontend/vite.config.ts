import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` serves the site on :5173 with instant reload, and forwards any
// /api request to the Python server on :8000 (`python main.py --web`).
// `npm run build` writes the finished site to dist/, which the Python server
// then serves itself -- so day to day you only run one thing.
export default defineConfig({
  plugins: [react()],
  // The charting library makes the bundle ~560 kB. That only matters for sites
  // loaded over the internet; this one is served from your own computer.
  build: { chunkSizeWarningLimit: 800 },
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
