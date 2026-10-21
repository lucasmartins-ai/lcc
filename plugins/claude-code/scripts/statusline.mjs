#!/usr/bin/env node
// Claude Code statusline for lcc: tokens this session's lcc passes removed, outputs stashed,
// and the cache-read share of the last request.
//
// Reads the opt-in local ledger (`ledger: true` in the plugin options, or LCC_LEDGER=1; file
// ~/.cache/lcc/ledger.jsonl or LCC_LEDGER_PATH) and the JSON Claude Code pipes to a statusline
// command on stdin. Reads only; writes nothing, sends nothing. Wire it in settings.json:
//
//   "statusLine": { "type": "command", "command": "node /path/to/plugins/claude-code/scripts/statusline.mjs" }
//
// Any failure prints a short line instead of throwing: a statusline must never break the UI.

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

export function ledgerPath(env = process.env) {
  return env.LCC_LEDGER_PATH || join(homedir(), ".cache", "lcc", "ledger.jsonl");
}

/** Same key the server stores (`lcc.receipt.session_key`): truncated SHA-256 of the id. */
export function sessionKey(id) {
  return typeof id === "string" && id ? createHash("sha256").update(id, "utf8").digest("hex").slice(0, 16) : null;
}

const count = (value) => (Number.isFinite(value) && value > 0 ? Math.trunc(value) : 0);

/** Totals of one session's ledger lines. Unparseable or foreign lines are skipped. */
export function summarize(text, key) {
  const total = { passes: 0, saved: 0, stashed: 0 };
  if (!key) return total;
  // ponytail: reads the whole file on every refresh; fine to a few MB (~10k passes). Read
  // only the tail if a ledger ever grows past that.
  for (const line of text.split("\n")) {
    let record;
    try {
      record = JSON.parse(line);
    } catch {
      continue;
    }
    if (record?.v !== 1 || record.session !== key) continue;
    total.passes += 1;
    total.saved += Math.max(0, count(record.tokens_before) - count(record.tokens_after));
    total.stashed += count(record.stashed);
  }
  return total;
}

/** Cache-read share of the last request, from Claude Code's `context_window.current_usage`. */
export function cacheReadShare(input) {
  const usage = input?.context_window?.current_usage;
  if (!usage || typeof usage !== "object") return null;
  const read = count(usage.cache_read_input_tokens);
  const all = count(usage.input_tokens) + count(usage.cache_creation_input_tokens) + read;
  return all > 0 ? read / all : null;
}

function short(n) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

/** The statusline text. `ledger` is the file's text, or null when there is no ledger. */
export function render(input, ledger) {
  const share = cacheReadShare(input);
  const cache = share === null ? "" : ` · cache read ${Math.round(share * 100)}%`;
  if (ledger === null) return `lcc: ledger off${cache}`;
  const total = summarize(ledger, sessionKey(input?.session_id));
  if (total.passes === 0) return `lcc: no pass this session${cache}`;
  const passes = total.passes === 1 ? "1 pass" : `${total.passes} passes`;
  const stashed = total.stashed ? ` · ${total.stashed} stashed` : "";
  return `lcc: -${short(total.saved)} tokens (${passes})${stashed}${cache}`;
}

function main() {
  let input = {};
  try {
    input = JSON.parse(readFileSync(0, "utf8") || "{}");
  } catch {
    // no or bad stdin: render without session or cache data
  }
  let ledger = null;
  try {
    ledger = readFileSync(ledgerPath(), "utf8");
  } catch {
    // no ledger: it is opt-in
  }
  let line;
  try {
    line = render(input, ledger);
  } catch {
    line = "lcc";
  }
  process.stdout.write(`${line}\n`);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main();
