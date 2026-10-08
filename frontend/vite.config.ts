import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the API is proxied to a local node (override with SYNAPSE_API=http://host:port).
const api = process.env.SYNAPSE_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": { target: api, changeOrigin: true } },
  },
  build: {
    chunkSizeWarningLimit: 900,
  },
});
