// Tests for the lcc Claude Code hook's pure mapping helpers. No framework, no engine.
//
//   node test/hook-map.test.mjs

import assert from "node:assert/strict";

import {
  buildCompactArgs,
  decideReplacement,
  deriveGoal,
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
  assert.equal(options.server, "lcc");
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

test("deriveGoal joins up to three user prompts and caps the length", () => {
  const messages = [
    { role: "user", text: "one" },
    { role: "assistant", text: "sure" },
    { role: "user", text: "two" },
    { role: "user", text: "three" },
    { role: "user", text: "x".repeat(600) },
  ];
  const goal = deriveGoal(messages, 50);
  assert.equal(goal.length, 50);
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

test("buildCompactArgs prefers an explicit question, then the /compact instructions", () => {
  const explicit = buildCompactArgs({
    messages: TRANSCRIPT,
    instructions: "keep the plan",
    options: { question: "reduce mobile booking friction" },
  });
  assert.equal(explicit.question, "reduce mobile booking friction");
  assert.equal(explicit.provider, "jev");
  assert.equal(explicit.preserve_recent, 6);
  assert.equal(explicit.messages.length, 3);

  const fromInstructions = buildCompactArgs({ messages: TRANSCRIPT, instructions: "keep the plan", options: {} });
  assert.equal(fromInstructions.question, "keep the plan");

  const fromGoal = buildCompactArgs({ messages: TRANSCRIPT, options: {} });
  assert.equal(fromGoal.question, "Fix the failing parser test. Never edit src/generated.");

  assert.equal(buildCompactArgs({ messages: [{ role: "assistant", text: "hi" }], options: {} }), null);
});

test("parseToolResult reads the JSON out of the MCP content blocks", () => {
  const payload = { messages: [{ role: "user", text: "hi" }], report: { mode: "tool-calls" } };
  const parsed = parseToolResult([{ type: "text", text: JSON.stringify(payload) }]);
  assert.equal(parsed.report.mode, "tool-calls");
  assert.throws(() => parseToolResult([]), /empty tool result/);
  assert.throws(() => parseToolResult([{ type: "text", text: "not json" }]), SyntaxError);
  assert.throws(() => parseToolResult([{ type: "text", text: "{}" }]), /not a compaction payload/);
});

test("decideReplacement replaces only a judged pass that removed something", () => {
  const messages = [{ role: "user", text: "hi" }];
  assert.deepEqual(
    decideReplacement({ report: { degraded: false, reduction_ratio: 0.42, tool_calls_dropped: 3 }, messages, minReductionRatio: 0.25 }),
    { replace: true, reason: "kept 1 messages, dropped 3 tool call(s), trimmed 0" },
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

test("toSessionMessages returns exactly what the engine rebuilds from", () => {
  const rebuilt = toSessionMessages([
    { role: "user", text: "hi" },
    { role: "user", text: "", toolResults: [{ tool_use_id: "toolu_1", text: "out" }] },
  ]);
  assert.deepEqual(rebuilt[0], { role: "user", text: "hi", toolUses: [] });
  assert.deepEqual(rebuilt[1].toolResults, [{ tool_use_id: "toolu_1", text: "out" }]);
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
