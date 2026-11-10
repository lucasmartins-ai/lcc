// Tests for the lcc Claude Code hook's pure mapping helpers. No framework, no engine.
//
//   node test/hook-map.test.mjs

import assert from "node:assert/strict";

import {
  buildCompactArgs,
  decideReplacement,
  deriveGoal,
  expandRefs,
  hasUnsupportedContent,
  parseToolResult,
  resolveOptions,
  toMcpMessages,
  toSessionMessages,
} from "../plugins/claude-code/hooks/map.mjs";

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

const TRANSCRIPT = [
  { role: "user", text: "Fix the failing parser test. Never edit src/generated." },
  {
    role: "assistant",
    text: "Running the suite.",
    toolUses: [{ tool_use_id: "toolu_1", tool: "Bash", input: { command: "pytest -q" }, isError: false }],
  },
  { role: "user", text: "", toolResults: [{ tool_use_id: "toolu_1", text: "1 failed, 24 passed" }] },
];

test("resolveOptions keeps the documented defaults", () => {
  const options = resolveOptions();
  assert.equal(options.server, "plugin:lcc:lcc");
  assert.equal(options.threshold, 0.5);
  assert.equal(options.preserveRecentMessages, 6);
  assert.equal(options.minReductionRatio, 0.25);
});

test("resolveOptions coerces strings and refuses nonsense", () => {
  const options = resolveOptions({
    threshold: "0.7",
    preserveRecentMessages: -4,
    maxStateTokens: 10,
    maxRequestTokens: 5,
    minReductionRatio: 12,
  });
  assert.equal(options.threshold, 0.7);
  assert.equal(options.preserveRecentMessages, 0);
  assert.equal(options.maxStateTokens, 64);
  assert.ok(options.maxRequestTokens > options.maxStateTokens);
  assert.equal(options.minReductionRatio, 1);
});

test("deriveGoal uses the newest user prompts, not the assistant's chatter", () => {
  const goal = deriveGoal(TRANSCRIPT);
  assert.equal(goal, "Fix the failing parser test. Never edit src/generated.");
});

test("deriveGoal cuts a newest prompt that is longer than the limit", () => {
  const messages = [
    { role: "user", text: "one" },
    { role: "assistant", text: "sure" },
    { role: "user", text: "two" },
    { role: "user", text: "three" },
    { role: "user", text: "x".repeat(600) },
  ];
  assert.equal(deriveGoal(messages, 50), "x".repeat(50));
});

test("deriveGoal keeps the newest prompt whole and skips tag-wrapped pseudo prompts", () => {
  const messages = [
    { role: "user", text: "old ".repeat(200) },
    { role: "user", text: "<system-reminder>not a prompt</system-reminder>" },
    { role: "user", text: "Fix the parser." },
    { role: "user", text: "<command-name>/compact</command-name>" },
  ];
  // The 800-char older prompt does not fit beside the newest one, so it is left out whole.
  assert.equal(deriveGoal(messages), "Fix the parser.");
  assert.equal(deriveGoal(messages, 1000), `${"old ".repeat(200).trim()}\nFix the parser.`);
  // A session that holds nothing else still gets an objective.
  const wrapper = "<command-name>/review</command-name>";
  assert.equal(deriveGoal([{ role: "user", text: wrapper }]), wrapper);
});

test("hasUnsupportedContent stands down on content it cannot rebuild", () => {
  assert.equal(hasUnsupportedContent(TRANSCRIPT), null);
  assert.equal(hasUnsupportedContent([{ role: "user", text: "hi", id: "m1", at: 12 }]), null);
  assert.match(
    hasUnsupportedContent([{ role: "user", text: "look", images: [{ type: "image" }] }]),
    /unsupported content in 'images'/,
  );
});

test("toMcpMessages carries the fields the MCP tool reads", () => {
  const messages = toMcpMessages(TRANSCRIPT);
  assert.deepEqual(messages[0], { role: "user", text: "Fix the failing parser test. Never edit src/generated." });
  assert.deepEqual(messages[1].toolUses, [
    { tool_use_id: "toolu_1", tool: "Bash", input: { command: "pytest -q" } },
  ]);
  assert.deepEqual(messages[2].toolResults, [{ tool_use_id: "toolu_1", text: "1 failed, 24 passed" }]);
});

test("toMcpMessages forwards a result's error flag, and only when set", () => {
  const messages = toMcpMessages([
    { role: "user", text: "", toolResults: [
      { tool_use_id: "a", text: "boom", is_error: true },
      { tool_use_id: "b", text: "fine", isError: true },
      { tool_use_id: "c", text: "ok", is_error: false },
    ] },
  ]);
  assert.deepEqual(messages[0].toolResults, [
    { tool_use_id: "a", text: "boom", is_error: true },
    { tool_use_id: "b", text: "fine", is_error: true },
    { tool_use_id: "c", text: "ok" },
  ]);
});

test("the judge is configurable and defaults to auto (specialist-v3)", () => {
  // The local judge is opt-in; an unknown value must not reach the MCP tool.
  assert.equal(resolveOptions({}).provider, "auto");
  assert.equal(resolveOptions({ provider: "laya" }).provider, "laya");
  assert.equal(resolveOptions({ provider: "auto" }).provider, "auto");
  assert.equal(resolveOptions({ provider: "rules" }).provider, "rules");
  assert.equal(resolveOptions({ provider: "nonsense" }).provider, "auto");
  assert.equal(resolveOptions({ provider: "jev" }).provider, "jev");

  const args = buildCompactArgs({
    messages: TRANSCRIPT,
    instructions: "keep the plan",
    options: { provider: "laya" },
  });
  assert.equal(args.provider, "laya");
});

test("buildCompactArgs prefers an explicit question, then the /compact instructions", () => {
  const explicit = buildCompactArgs({
    messages: TRANSCRIPT,
    instructions: "keep the plan",
    options: { question: "reduce mobile booking friction" },
  });
  assert.equal(explicit.question, "reduce mobile booking friction");
  assert.equal(explicit.provider, "auto");
  assert.equal(explicit.preserve_recent, 6);
  assert.equal(explicit.messages.length, 3);

  const fromInstructions = buildCompactArgs({ messages: TRANSCRIPT, instructions: "keep the plan", options: {} });
  assert.equal(fromInstructions.question, "keep the plan");

  const fromGoal = buildCompactArgs({ messages: TRANSCRIPT, options: {} });
  assert.equal(fromGoal.question, "Fix the failing parser test. Never edit src/generated.");

  assert.equal(buildCompactArgs({ messages: [{ role: "assistant", text: "hi" }], options: {} }), null);
});

test("buildCompactArgs sends no rules_mode unless the user opts in", () => {
  const args = buildCompactArgs({ messages: TRANSCRIPT, options: {}, cwd: "/repo" });
  assert.equal("rules_mode" in args, false);
  assert.equal("workspace_root" in args, false);
  const lossless = buildCompactArgs({ messages: TRANSCRIPT, options: { provider: "rules", rulesMode: "lossless" }, cwd: "/repo" });
  assert.equal(lossless.rules_mode, "lossless");
  assert.equal("workspace_root" in lossless, false);
  const bogus = buildCompactArgs({ messages: TRANSCRIPT, options: { rulesMode: "yolo" }, cwd: "/repo" });
  assert.equal("rules_mode" in bogus, false);
});

test("buildCompactArgs passes rules_mode stashed through, without workspace_root", () => {
  const args = buildCompactArgs({ messages: TRANSCRIPT, options: { provider: "rules", rulesMode: "stashed" }, cwd: "/repo" });
  assert.equal(args.rules_mode, "stashed");
  assert.equal("workspace_root" in args, false);
});

test("buildCompactArgs passes the session cwd as workspace_root for rules_mode recoverable", () => {
  const options = { provider: "rules", rulesMode: "recoverable" };
  const args = buildCompactArgs({ messages: TRANSCRIPT, options, cwd: "/repo" });
  assert.equal(args.provider, "rules");
  assert.equal(args.rules_mode, "recoverable");
  assert.equal(args.workspace_root, "/repo");
  // No absolute cwd: no workspace_root (the server then falls back to the transcript proxy).
  assert.equal("workspace_root" in buildCompactArgs({ messages: TRANSCRIPT, options, cwd: "rel" }), false);
  assert.equal("workspace_root" in buildCompactArgs({ messages: TRANSCRIPT, options }), false);
});

test("parseToolResult reads the JSON out of the MCP content blocks", () => {
  const payload = { messages: [{ role: "user", text: "hi" }], report: { mode: "tool-calls" } };
  const parsed = parseToolResult([{ type: "text", text: JSON.stringify(payload) }]);
  assert.equal(parsed.report.mode, "tool-calls");
  assert.throws(() => parseToolResult([]), /empty tool result/);
  // What Claude Code hands back for an answer over its MCP output cap is not JSON.
  assert.throws(() => parseToolResult([{ type: "text", text: "Error: result exceeds" }]), /not JSON .*MCP output cap/);
  assert.throws(() => parseToolResult([{ type: "text", text: "{}" }]), /not a compaction payload/);
});

test("decideReplacement replaces only a judged pass that removed something", () => {
  const messages = [{ role: "user", text: "hi" }];
  assert.deepEqual(
    decideReplacement({ report: { degraded: false, reduction_ratio: 0.42, tool_calls_dropped: 3 }, messages, minReductionRatio: 0.25 }),
    { replace: true, reason: "kept 1 messages, dropped 3 tool call(s), trimmed 0, deduped 0, replaced 0" },
  );
  // Lossless dedupes and recoverable replacements count as removals.
  assert.deepEqual(
    decideReplacement({
      report: { degraded: false, reduction_ratio: 0.4, tool_calls_deduped: 2, tool_calls_replaced: 5 },
      messages,
      minReductionRatio: 0.25,
    }),
    { replace: true, reason: "kept 1 messages, dropped 0 tool call(s), trimmed 0, deduped 2, replaced 5" },
  );
  // A ratio with nothing removed (e.g. only whitespace changed) is not a compaction.
  assert.equal(
    decideReplacement({ report: { degraded: false, reduction_ratio: 0.5 }, messages, minReductionRatio: 0.25 }).replace,
    false,
  );
  assert.equal(
    decideReplacement({ report: { degraded: false, reduction_ratio: 0.05 }, messages, minReductionRatio: 0.25 }).replace,
    false,
  );
  assert.equal(
    decideReplacement({
      report: { degraded: true, degradation_reason: "jev_unavailable_fail_safe", reduction_ratio: 0.9 },
      messages,
      minReductionRatio: 0.25,
    }).replace,
    false,
  );
  assert.equal(
    decideReplacement({ report: { degraded: false, reduction_ratio: 0.9 }, messages: [], minReductionRatio: 0.25 }).replace,
    false,
  );
});

test("specialist-v3 is selectable", () => {
  assert.equal(resolveOptions({ provider: "specialist-v3" }).provider, "specialist-v3");
});

test("toSessionMessages returns exactly what the engine rebuilds from", () => {
  const rebuilt = toSessionMessages([
    { role: "user", text: "hi" },
    { role: "user", text: "", toolResults: [{ tool_use_id: "toolu_1", text: "out" }] },
  ]);
  assert.deepEqual(rebuilt[0], { role: "user", text: "hi", toolUses: [] });
  assert.deepEqual(rebuilt[1].toolResults, [{ tool_use_id: "toolu_1", text: "out" }]);
});

test("toSessionMessages keeps a failed tool result failed", () => {
  // Observed on Claude Code 2.1.296: an `is_error` result came back as a success.
  const [message] = toSessionMessages([
    { role: "user", text: "", toolResults: [{ tool_use_id: "t", text: "boom", is_error: true }] },
  ]);
  assert.deepEqual(message.toolResults, [{ tool_use_id: "t", text: "boom", isError: true }]);
});

test("expandRefs rebuilds a ref_blocks patch from the caller's own blocks", () => {
  const read = { tool_use_id: "r", tool: "Read", input: { file_path: "a.py" } };
  const grep = { tool_use_id: "g", tool: "Grep", input: { pattern: "x" } };
  const body = "head 😀 line\n".repeat(50);
  const source = [
    { role: "user", text: "go", handle: "h0" },
    { role: "assistant", text: "two calls", toolUses: [read, grep], handle: "h1" },
    {
      role: "user", text: "", handle: "h2",
      toolResults: [{ tool_use_id: "r", text: body }, { tool_use_id: "g", text: "hit", isError: true }],
    },
  ];
  const answer = [
    { ref: 0 },
    { ref: 1, toolUses: [1], toolResults: [] },
    // UTF-16 units: the emoji is two, as in the server's head count.
    { ref: 2, toolUses: [], toolResults: [{ ref: 0, tool_use_id: "r", head: 7, text: "\n[cut]" }, 1] },
  ];
  const [first, second, third] = expandRefs(answer, source);
  assert.equal(first, source[0], "an unchanged message is the caller's own object");
  assert.deepEqual(second, { role: "assistant", text: "two calls", toolUses: [grep] });
  assert.deepEqual(third, {
    role: "user", text: "", toolUses: [],
    toolResults: [{ tool_use_id: "r", text: "head 😀\n[cut]" }, source[2].toolResults[1]],
  });
  const tail = expandRefs([{ ref: 2, toolResults: [{ ref: 0, tool_use_id: "r", text: "[x]", tail: 5 }] }], source);
  assert.equal(tail[0].toolResults[0].text, "[x]line\n");
});

test("expandRefs refuses a patch that does not fit the transcript", () => {
  const source = [{ role: "user", text: "", toolResults: [{ tool_use_id: "r", text: "abc" }] }];
  assert.throws(() => expandRefs([{ ref: 1 }], source), /outside the transcript/);
  assert.throws(() => expandRefs([{ ref: 0, toolUses: [0] }], source), /tool use ref 0/);
  assert.throws(() => expandRefs([{ ref: 0, toolResults: [3] }], source), /tool result ref 3/);
  const patch = (over) => [{ ref: 0, toolResults: [{ ref: 0, tool_use_id: "r", text: "", ...over }] }];
  assert.throws(() => expandRefs(patch({ tool_use_id: "other" }), source), /does not fit/);
  assert.throws(() => expandRefs(patch({ head: 2, tail: 2 }), source), /does not fit/);
  assert.throws(() => expandRefs(patch({ head: -1 }), source), /does not fit/);
});

let failed = 0;
for (const [name, fn] of tests) {
  try {
    await fn();
    console.log(`ok   ${name}`);
  } catch (error) {
    failed += 1;
    console.error(`FAIL ${name}\n     ${error.message}`);
  }
}
if (failed > 0) {
  console.error(`\n${failed} of ${tests.length} hook-mapping tests failed`);
  process.exit(1);
}
console.log(`\nAll ${tests.length} hook-mapping tests passed.`);
