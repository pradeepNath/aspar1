import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite config for ASPAR frontend.
// The proxy setting forwards any /api/* request from the React dev server
// to the Flask backend on port 5000 — this means Axios calls like
// axios.post("/api/auth/login") just work without CORS issues in development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:5000",
        changeOrigin: true,
      },
    },
  },
});