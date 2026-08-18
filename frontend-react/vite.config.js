import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

import { productionChunk } from "./build-chunks.js";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: productionChunk,
      },
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5174,
  },
  preview: {
    host: "127.0.0.1",
    port: 5175,
  },
});
