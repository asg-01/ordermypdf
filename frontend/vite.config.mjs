import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const API_URL = process.env.VITE_API_URL || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: undefined,
      },
    },
  },
  // Copy public folder files (including sw.js) to build output
  publicDir: "public",
  server: {
    port: 5173,
    proxy: {
      "/process": {
        target: API_URL,
        changeOrigin: true,
      },
      "/download": {
        target: API_URL,
        changeOrigin: true,
      },
      "/submit": {
        target: API_URL,
        changeOrigin: true,
      },
      "/job": {
        target: API_URL,
        changeOrigin: true,
      },
      "/api": {
        target: API_URL,
        changeOrigin: true,
      },
      "/preupload": {
        target: API_URL,
        changeOrigin: true,
      },
    },
  },
});
