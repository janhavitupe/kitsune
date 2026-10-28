import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // In dev the backend runs on :8000; in production VITE_API_URL points at it instead.
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
