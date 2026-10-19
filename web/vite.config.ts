import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the UI runs on :5173 and proxies API / WebSocket calls to the
// FastAPI server on :8000 (`tradebot serve`). In production FastAPI serves dist/.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
});
