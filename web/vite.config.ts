/// <reference types="vitest/config" />
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const api = process.env.KB_API_URL ?? "http://localhost:8000";
// The JSON API's top-level paths. `npm run dev` proxies them, so the page and the API share an origin as when
// the app serves the build.
const apiPaths = ["/auth", "/capture", "/items", "/search", "/taxonomy", "/thoughts", "/versions"];

export default defineConfig({
  base: "/app/",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "src") } },
  server: { proxy: Object.fromEntries(apiPaths.map((p) => [p, api])) },
  test: {
    environment: "jsdom",
    setupFiles: ["src/test/setup.ts"],
  },
});
