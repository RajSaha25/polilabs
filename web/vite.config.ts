import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// /api and /chat proxy to the FastAPI backend (server.py) during dev.
// In production the backend serves the built web/dist directly, so the
// proxy is dev-only.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/chat": "http://localhost:8000",
    },
  },
});
