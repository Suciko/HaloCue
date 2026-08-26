import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/scene-editor/",
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      "/scene-preview": "http://127.0.0.1:8898",
      "/api/resources": "http://127.0.0.1:8898",
    },
  },
});
