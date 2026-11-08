import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` proxies data calls to `fluxora serve` (default port 8765).
const api = "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  server: { port: 5174, proxy: { "/api": api, "/runs": api } },
});
