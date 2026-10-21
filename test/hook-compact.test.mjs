// Direct test of the hook module's cwd plumbing: the session cwd reaches workspace_root.
//
//   node test/hook-compact.test.mjs

import assert from "node:assert/strict";

import { register, sessionCwd } from "../plugins/claude-code/hooks/lcc-compact.mjs";

const TRANSCRIPT = [
  { role: "user", text: "Fix the failing parser test." },
  {
    role: "assistant",
    text: "Reading.",
    toolUses: [{ tool_use_id: "toolu_1", tool: "Read", input: { file_path: "/repo/p.py" } }],
  },
  { role: "user", text: "", toolResults: [{ tool_use_id: "toolu_1", text: "1\tx" }] },
];

async function argsSent(event, options) {
  let handler;
  register((name, fn) => { if (name === "session.compact") handler = fn; return { catch() {} }; }, options);
  let sent = null;
  const $ = {
    ui: { log() {}, toast() {} },
    mcp: { call: async (_server, _tool, args) => { sent = args; throw new Error("stop"); } },
  };
  let fellBack = false;
  await handler($, { trigger: "manual", messages: TRANSCRIPT, ...event }, () => { fellBack = true; });
  assert.equal(fellBack, true, "a failed MCP call falls back to next(event)");
  return sent;
}

const RECOVERABLE = { provider: "rules", rulesMode: "recoverable" };

assert.equal((await argsSent({ cwd: "/session/repo" }, RECOVERABLE)).workspace_root, "/session/repo");
// No cwd on the event, or a relative one: the hook process's own cwd.
assert.equal((await argsSent({}, RECOVERABLE)).workspace_root, process.cwd());
assert.equal((await argsSent({ cwd: "rel" }, RECOVERABLE)).workspace_root, process.cwd());
assert.equal(sessionCwd({ cwd: "/x" }), "/x");
assert.equal(sessionCwd(undefined), process.cwd());
// Claude Code's hook worker has no `process`: no throw, no workspace root.
const realProcess = globalThis.process;
globalThis.process = undefined;
try {
  assert.equal(sessionCwd({}), undefined);
} finally {
  globalThis.process = realProcess;
}
// Lossless and the default mode never send a workspace root.
assert.equal("workspace_root" in (await argsSent({ cwd: "/s" }, { provider: "rules", rulesMode: "lossless" })), false);
assert.equal("workspace_root" in (await argsSent({ cwd: "/s" }, {})), false);

// The /compact path asks for a ref_blocks answer and rebuilds the session from it: Claude Code
// caps an MCP result (25,000 tokens by default), so the transcript must not travel back whole.
async function compactWith(answer, options = {}) {
  let handler;
  register((name, fn) => { if (name === "session.compact") handler = fn; return { catch() {} }; }, options);
  const toasts = [];
  let sent = null;
  const $ = {
    ui: { log() {}, toast(text) { toasts.push(text); } },
    session: { id: async () => "sess-1" },
    mcp: { call: async (_server, _tool, args) => { sent = args; return { content: [{ type: "text", text: answer }] }; } },
  };
  const result = await handler($, { trigger: "manual", messages: TRANSCRIPT }, () => "builtin");
  return { result, sent, toasts };
}
const report = { degraded: false, reduction_ratio: 0.5, tool_calls_trimmed: 1, provider_used: "rules" };
const patched = await compactWith(JSON.stringify({
  report,
  messages: [{ ref: 0 }, { ref: 1 }, { ref: 2, toolUses: [], toolResults: [{ ref: 0, tool_use_id: "toolu_1", head: 1, text: "[cut]" }] }],
}));
assert.equal(patched.sent.ref_unchanged, true);
assert.equal(patched.sent.ref_blocks, true);
assert.equal(patched.result.messages[0], TRANSCRIPT[0], "unchanged messages are the session's own");
assert.deepEqual(patched.result.messages[2].toolResults, [{ tool_use_id: "toolu_1", text: "1[cut]" }]);
assert.match(patched.toasts[0], /^lcc: verbatim compaction via rules/);
// An answer over the cap comes back as Claude Code's pointer text: the built-in summary runs.
const capped = await compactWith("Error: result (120,000 characters) exceeds maximum allowed tokens.");
assert.equal(capped.result, "builtin");
assert.match(capped.toasts[0], /built-in summary \(tool result is not JSON .*MCP output cap/);
// A ref the transcript does not have never reaches the session.
const stray = await compactWith(JSON.stringify({ report, messages: [{ ref: 9 }] }));
assert.equal(stray.result, "builtin");
// The ledger is opt-in: `ledger` is asked for only with the option on. The session id
// always travels, so LCC_LEDGER=1 on the server alone still keys records by session.
assert.equal("ledger" in patched.sent, false);
assert.equal(patched.sent.ledger_session, "sess-1");
const answer = JSON.stringify({
  report,
  messages: [{ ref: 0 }, { ref: 1 }, { ref: 2 }],
  receipt: "lcc: 1,044 -> 1,009 tokens (-35, -3.4%) · 2 stashed · recall: lcc recall a88ace3b32aa",
});
const ledgered = await compactWith(answer, { ledger: true });
assert.equal(ledgered.sent.ledger, true);
assert.equal(ledgered.sent.ledger_session, "sess-1");
// The server's one-line receipt is the toast.
assert.equal(
  ledgered.toasts[0],
  "lcc: verbatim compaction via rules, no summary (1,044 -> 1,009 tokens (-35, -3.4%) · 2 stashed · recall: lcc recall a88ace3b32aa)",
);
console.log("hook-compact: ok");
