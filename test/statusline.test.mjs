// The statusline against a fixture ledger, in-process and as Claude Code runs it (stdin JSON).
//
//   node test/statusline.test.mjs

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import {
  cacheReadShare,
  contextSegment,
  render,
  sessionKey,
  suggestAt,
  summarize,
} from "../plugins/claude-code/scripts/statusline.mjs";

const FIXTURE = fileURLToPath(new URL("./fixtures/ledger.jsonl", import.meta.url));
const SCRIPT = fileURLToPath(new URL("../plugins/claude-code/scripts/statusline.mjs", import.meta.url));
const ledger = readFileSync(FIXTURE, "utf8");

// Same key as lcc.receipt.session_key (tests/test_receipt.py pins the Python side).
assert.equal(sessionKey("fixture-session-a"), "e279159a3ffc189d");
assert.equal(sessionKey(""), null);

// Session A: two v1 passes; the corrupted line, the v2 line and the recall record are skipped.
assert.deepEqual(summarize(ledger, sessionKey("fixture-session-a")), {
  passes: 2,
  saved: (148210 - 121004) + (152330 - 138911),
  stashed: 14 + 9,
});
assert.deepEqual(summarize(ledger, null), { passes: 0, saved: 0, stashed: 0 });

const usage = { input_tokens: 2000, cache_creation_input_tokens: 6000, cache_read_input_tokens: 92000 };
assert.equal(cacheReadShare({ context_window: { current_usage: usage } }), 0.92);
assert.equal(cacheReadShare({}), null);

const input = { session_id: "fixture-session-a", context_window: { current_usage: usage } };
assert.equal(render(input, ledger), "lcc: -40.6k tokens (2 passes) · 23 stashed · cache read 92%");
assert.equal(render({ session_id: "fixture-session-b" }, ledger), "lcc: -10.0k tokens (1 pass) · 5 stashed");
assert.equal(render({ session_id: "other" }, ledger), "lcc: no pass this session");
assert.equal(render(input, null), "lcc: ledger off · cache read 92%");

// Context fill: `used_percentage` floored, so the hint shows exactly when the printed % is >= the threshold.
const ctx = (used, size) => ({ context_window: { used_percentage: used, context_window_size: size } });
assert.equal(contextSegment(ctx(12.4, 200000), 30), " · ctx 12% of 200k");
assert.equal(contextSegment(ctx(29.9, 200000), 30), " · ctx 29% of 200k");
assert.equal(contextSegment(ctx(30, 200000), 30), " · ctx 30% of 200k · /compact suggested");
assert.equal(contextSegment(ctx(40, 1000000), 30), " · ctx 40% of 1M · /compact suggested");
assert.equal(contextSegment(ctx(95.2, 200000), 30), " · ctx 95% of 200k · /compact suggested");
assert.equal(contextSegment(ctx(31, undefined), 30), " · ctx 31% · /compact suggested");
assert.equal(contextSegment(ctx(31, 200000), null), " · ctx 31% of 200k");
// Early in a session and right after /compact Claude Code sends null: no segment, never "ctx 0%".
assert.equal(contextSegment(ctx(null, 200000), 30), "");
assert.equal(contextSegment(ctx(-1, 200000), 30), "");
assert.equal(contextSegment({}, 30), "");

// LCC_SUGGEST_COMPACT_AT: percent, default 30, 0 turns the hint off, junk falls back to the default.
assert.equal(suggestAt({}), 30);
assert.equal(suggestAt({ LCC_SUGGEST_COMPACT_AT: "40" }), 40);
assert.equal(suggestAt({ LCC_SUGGEST_COMPACT_AT: "0" }), null);
assert.equal(suggestAt({ LCC_SUGGEST_COMPACT_AT: "0.0" }), null);
assert.equal(suggestAt({ LCC_SUGGEST_COMPACT_AT: "  " }), 30);
assert.equal(suggestAt({ LCC_SUGGEST_COMPACT_AT: "abc" }), 30);
assert.equal(suggestAt({ LCC_SUGGEST_COMPACT_AT: "-5" }), 30);
assert.equal(suggestAt({ LCC_SUGGEST_COMPACT_AT: "" }), 30);

const full = { ...input, context_window: { ...input.context_window, used_percentage: 41, context_window_size: 200000 } };
assert.equal(
  render(full, ledger),
  "lcc: -40.6k tokens (2 passes) · 23 stashed · cache read 92% · ctx 41% of 200k · /compact suggested",
);
assert.equal(render(full, null, null), "lcc: ledger off · cache read 92% · ctx 41% of 200k");

// As Claude Code runs it: JSON on stdin, one line on stdout; bad stdin or no ledger never throws.
const run = (stdin, path, extra = {}) =>
  execFileSync(process.execPath, [SCRIPT], {
    input: stdin,
    env: { ...process.env, LCC_SUGGEST_COMPACT_AT: "", LCC_LEDGER_PATH: path, ...extra },
  }).toString();
assert.equal(run(JSON.stringify(input), FIXTURE), "lcc: -40.6k tokens (2 passes) · 23 stashed · cache read 92%\n");
assert.equal(run("not json", FIXTURE), "lcc: no pass this session\n");
assert.equal(run("{}", "/nonexistent/lcc/ledger.jsonl"), "lcc: ledger off\n");
assert.equal(
  run(JSON.stringify(full), FIXTURE, { LCC_SUGGEST_COMPACT_AT: "50" }),
  "lcc: -40.6k tokens (2 passes) · 23 stashed · cache read 92% · ctx 41% of 200k\n",
);

console.log("statusline: ok");
