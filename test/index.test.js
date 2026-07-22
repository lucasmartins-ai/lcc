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

console.log("✓ All lcc JS unit tests passed cleanly!");
