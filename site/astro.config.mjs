// @ts-check
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "astro/config";

// Served at lookadev.com/lcc/ by the lcc-site Worker (wrangler.jsonc). The build lands in
// dist/<base> so the asset tree matches the URL paths the Worker receives.
const base = process.env.SITE_BASE ?? "/lcc";

export default defineConfig({
  site: process.env.SITE_URL ?? "https://lookadev.com",
  base,
  outDir: `./dist${base.replace(/\/$/, "")}`,
  build: { format: "file" },
  // Scripts ship as files so the page CSP (Base.astro) can allow only same-origin scripts.
  vite: { plugins: [tailwindcss()], build: { assetsInlineLimit: 0 } },
});
