import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api/v1": {
        target: process.env.HUB_API_PROXY_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: false,
      },
    },
  },
});
