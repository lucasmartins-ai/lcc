// The plugin is read by two hosts. Claude Code takes hooks/hooks.json as is (its top-level `modules`
// registers the function hook). Codex parses every hooks file it loads with a strict schema
// (`description` and `hooks` only, openai/codex codex-rs/config/src/hook_config.rs) and skips the
// whole file on any other key. .codex-plugin/plugin.json overrides Codex's default hooks/hooks.json
// discovery, so Codex never reads the Claude file.
//
//   node test/plugin-manifests.test.mjs

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("../plugins/claude-code/", import.meta.url));
const json = (...parts) => JSON.parse(readFileSync(join(ROOT, ...parts), "utf8"));

// Claude Code: the function hook and the classic hooks stay registered.
const claude = json("hooks", "hooks.json");
assert.deepEqual(claude.modules, ["./lcc-compact.mjs"]);
assert.ok(existsSync(resolve(ROOT, "hooks", claude.modules[0])), "modules entry exists");
assert.deepEqual(Object.keys(claude.hooks).sort(), ["PreCompact", "SessionStart"]);

// Codex: every hooks file it would load passes its strict schema.
const codex = json(".codex-plugin", "plugin.json");
// Codex only honours a path, a non-empty list of paths, or an inline object. An absent, empty or
// invalid `hooks` (`[]`, `false`) falls back to hooks/hooks.json, which it rejects for `modules`.
const entries = Array.isArray(codex.hooks) ? codex.hooks : [codex.hooks];
assert.ok(
  entries.length > 0 && entries.every((e) => typeof e === "string" || (e && typeof e === "object" && !Array.isArray(e))),
  "manifest `hooks` must be a path, a non-empty path list or an inline object",
);
const hooksFiles = entries.map((entry) => {
  if (typeof entry !== "string") return entry; // inline object
  assert.match(entry, /^\.\//, "manifest hooks paths start with ./");
  return JSON.parse(readFileSync(resolve(ROOT, entry), "utf8"));
});
for (const file of hooksFiles) {
  const extra = Object.keys(file).filter((key) => key !== "description" && key !== "hooks");
  assert.deepEqual(extra, [], `Codex rejects hooks keys: ${extra}`);
}

// Both manifests describe the same release.
const claudeManifest = json(".claude-plugin", "plugin.json");
assert.equal(codex.name, claudeManifest.name);
assert.equal(codex.version, claudeManifest.version, "bump .codex-plugin/plugin.json with .claude-plugin/plugin.json");
const marketplace = JSON.parse(readFileSync(join(dirname(ROOT), "..", ".claude-plugin", "marketplace.json"), "utf8"));
assert.equal(marketplace.plugins.find((p) => p.name === codex.name)?.version, codex.version);
console.log("plugin-manifests: ok");
