// Reference arm: `fast-jev-compaction` (npm) over the same transcripts, so the study compares
// two real backends rather than a backend against a description of one.
//
// Copied into a scratch directory that has the package installed, then run as:
//   node fast_jev_arm.mjs <input.json> <output.json>
// The output is the library's result verbatim: {messages, stats, reductionRatio}.

import { readFileSync, writeFileSync } from "node:fs";

import { compactMessages, reductionRatio } from "fast-jev-compaction";

const [, , inputPath, outputPath] = process.argv;
if (!inputPath || !outputPath) {
  console.error("usage: node fast_jev_arm.mjs <input.json> <output.json>");
  process.exit(2);
}

const job = JSON.parse(readFileSync(inputPath, "utf8"));
const started = Date.now();

try {
  const result = await compactMessages(job.messages, {
    preserveRecentMessages: job.options.preserveRecentMessages,
    keepThreshold: job.options.threshold,
    truncateHeadChars: job.options.trimHeadChars,
    maxStateTokens: job.options.maxStateTokens,
    maxRequestTokens: job.options.maxRequestTokens,
    goal: job.options.question,
    model: job.options.jevModel,
  });
  writeFileSync(
    outputPath,
    JSON.stringify(
      {
        ok: true,
        latency_ms: Date.now() - started,
        reduction_ratio: reductionRatio(result),
        stats: result.stats,
        messages: result.messages,
      },
      null,
      2,
    ),
  );
} catch (error) {
  writeFileSync(
    outputPath,
    JSON.stringify(
      {
        ok: false,
        latency_ms: Date.now() - started,
        error: error instanceof Error ? error.message : String(error),
      },
      null,
      2,
    ),
  );
  process.exitCode = 1;
}
