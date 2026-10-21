// The statusline against a fixture ledger, in-process and as Claude Code runs it (stdin JSON).
//
//   node test/statusline.test.mjs

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { cacheReadShare, render, sessionKey, summarize } from "../plugins/claude-code/scripts/statusline.mjs";

const FIXTURE = fileURLToPath(new URL("./fixtures/ledger.jsonl", import.meta.url));
const SCRIPT = fileURLToPath(new URL("../plugins/claude-code/scripts/statusline.mjs", import.meta.url));
const ledger = readFileSync(FIXTURE, "utf8");

// Same key as lcc.receipt.session_key (tests/test_receipt.py pins the Python side).
assert.equal(sessionKey("fixture-session-a"), "e279159a3ffc189d");
assert.equal(sessionKey(""), null);

// Session A: two v1 passes; the corrupted line and the v2 line are skipped.
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

// As Claude Code runs it: JSON on stdin, one line on stdout; bad stdin or no ledger never throws.
const run = (stdin, path) =>
  execFileSync(process.execPath, [SCRIPT], { input: stdin, env: { ...process.env, LCC_LEDGER_PATH: path } }).toString();
assert.equal(run(JSON.stringify(input), FIXTURE), "lcc: -40.6k tokens (2 passes) · 23 stashed · cache read 92%\n");
assert.equal(run("not json", FIXTURE), "lcc: no pass this session\n");
assert.equal(run("{}", "/nonexistent/lcc/ledger.jsonl"), "lcc: ledger off\n");

console.log("statusline: ok");
