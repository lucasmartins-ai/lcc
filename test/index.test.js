"use strict";

const assert = require("assert");
const { LccCompressor, LccOptimizer, compressContext, estimateTokens } = require("../index.js");

console.log("Running lcc JS unit tests...");

// Test token estimation
const tokenCount = estimateTokens("Hello world! This is a test context prompt.");
assert(tokenCount > 0, "Token count should be > 0");

// Test LccCompressor
const compressor = new LccCompressor({ model: "gpt-4.1", removeBoilerplate: true });
const rawText = `
CONFIDENTIALITY NOTICE: This email is intended for the recipient.
Sent from my iPhone

Here is the primary context paragraph.

Here is the primary context paragraph.
`;

const res = compressor.compress(rawText);
assert(res.compressedText.includes("Here is the primary context paragraph."));
assert(!res.compressedText.includes("Sent from my iPhone"));
assert(res.originalTokens >= res.compressedTokens);
assert(res.savingsPercentage >= 0);

// Test LccOptimizer alias
const optimizer = new LccOptimizer();
const res2 = optimizer.compress("Testing optimizer alias");
assert.strictEqual(res2.compressedText, "Testing optimizer alias");

// Test compressContext helper
const res3 = compressContext("Hello world");
assert.strictEqual(res3.compressedText, "Hello world");

// Test buildPrompt with Claude XML template
const xmlPrompt = compressor.buildPrompt({
  question: "Summarize architecture",
  context: "Architecture uses local-first compiler.",
  taskType: "summary",
  constraints: ["Preserve all ADRs."]
}, "claude_xml");
assert(xmlPrompt.includes("<system_instructions>"), "Should contain <system_instructions>");
assert(xmlPrompt.includes("<definition_of_done>"), "Should contain <definition_of_done>");
assert(xmlPrompt.includes("<context>"), "Should contain <context>");
assert(xmlPrompt.includes("<user_query>"), "Should contain <user_query>");
assert(xmlPrompt.includes("<rule>Preserve all ADRs.</rule>"), "Should contain constraint rule");
assert(xmlPrompt.indexOf("<system_instructions>") < xmlPrompt.indexOf("<context>") && xmlPrompt.indexOf("<context>") < xmlPrompt.indexOf("<user_query>"), "Should be ordered for prompt caching");

// Test buildPrompt with Code Agent template
const codePrompt = compressor.buildPrompt({
  question: "Implement unit test",
  context: "function add(a, b) { return a + b; }",
  taskType: "coding"
}, "code_agent");
// Test LccIntake unified workflow
const { LccIntake, parseIntake, processIntake } = require("../index.js");

const parsed = parseIntake("Maybe we should refactor something with the database, not sure");
assert.strictEqual(parsed.readiness, "NEEDS_INTAKE");
assert(parsed.questions.length > 0);

const intakePipeline = new LccIntake({ model: "claude-sonnet-5", template: "claude_xml" });
const intakeRes = intakePipeline.process(`
Sent from my iPhone
This is the database migration guide.
This is the database migration guide.
`, "Optimize query");
assert(intakeRes.formattedPrompt.includes("lcc-intake:readiness"));
assert(!intakeRes.formattedPrompt.includes("Sent from my iPhone"));
assert(intakeRes.formattedPrompt.includes("<system_instructions>"));
assert(intakeRes.compression !== null);

console.log("✓ All lcc JS unit tests passed cleanly!");
