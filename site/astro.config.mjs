// @ts-check
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "astro/config";

// SITE_BASE: "/" for the custom domain, "/lcc" for lucasmartins-ai.github.io/lcc.
// Pages build as QUICKSTART.html etc., the paths the old Jekyll site served.
export default defineConfig({
  site: process.env.SITE_URL ?? "https://lcc.lookadev.com",
  base: process.env.SITE_BASE ?? "/",
  build: { format: "file" },
  vite: { plugins: [tailwindcss()] },
});
