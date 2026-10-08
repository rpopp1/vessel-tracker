import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The API port can be overridden when 8000 is taken: `$env:API_PORT = 8011` (PowerShell) before `npm run dev`.
const apiPort = process.env.API_PORT ?? "8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": `http://127.0.0.1:${apiPort}`,
      "/ws": { target: `ws://127.0.0.1:${apiPort}`, ws: true },
    },
  },
  test: { environment: "node" },
});
