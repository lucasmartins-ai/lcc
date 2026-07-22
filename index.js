"use strict";

/**
 * Local Context Compiler (lcc) - Node.js / TypeScript Engine
 * Deterministic, 100% local context reduction and token estimation.
 */

// Common email signatures and header boilerplate regexes
const BOILERPLATE_PATTERNS = [
  /Sent from my (iPhone|iPad|Android|Galaxy|mobile device)/gi,
  /CONFIDENTIALITY NOTICE:[\s\S]*?intended recipient\./gi,
  /This email and any files transmitted with it are confidential[\s\S]*?prohibited\./gi,
  /Get Outlook for (iOS|Android)/gi,
  /Disclaimer:[\s\S]*?error, please notify the sender/gi
];

/**
 * Deterministic local token estimator based on BPE word/punctuation heuristics (approx cl100k_base / o200k_base).
 */
function estimateTokens(text, model = "gpt-4.1") {
  if (!text || typeof text !== "string") return 0;
  const trimmed = text.trim();
  if (!trimmed) return 0;

  // Split into words, whitespace, and punctuation tokens
  const words = trimmed.match(/[\w']+|[^\w\s]|\s+/g) || [];
  let count = 0;

  for (let i = 0; i < words.length; i++) {
    const token = words[i];
    if (/^\s+$/.test(token)) {
      count += Math.ceil(token.length / 4);
    } else if (token.length <= 4) {
      count += 1;
    } else {
      count += Math.ceil(token.length / 3.5);
    }
  }

  return Math.max(1, Math.round(count));
}

/**
 * Normalizes text line endings, repeated spaces, and excessive newlines.
 */
function normalizeText(text) {
  if (!text) return { text: "", removedChars: 0 };
  const originalLen = text.length;
  let normalized = text
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

  return {
    text: normalized,
    removedChars: Math.max(0, originalLen - normalized.length)
  };
}

/**
 * Removes boilerplate and signatures.
 */
function removeBoilerplate(text) {
  let cleaned = text;
  let removedChars = 0;

  for (const pattern of BOILERPLATE_PATTERNS) {
    const before = cleaned.length;
    cleaned = cleaned.replace(pattern, "");
    removedChars += (before - cleaned.length);
  }

  cleaned = cleaned.replace(/\n{3,}/g, "\n\n").trim();
  return { text: cleaned, removedChars };
}

/**
 * Deduplicates paragraphs deterministically.
 */
function deduplicateParagraphs(text) {
  const paragraphs = text.split(/\n\s*\n/);
  const seen = new Set();
  const result = [];
  let originalLen = text.length;

  for (const p of paragraphs) {
    const key = p.trim().toLowerCase();
    if (!key) continue;
    if (!seen.has(key)) {
      seen.add(key);
      result.push(p.trim());
    }
  }

  const cleaned = result.join("\n\n");
  return {
    text: cleaned,
    removedChars: Math.max(0, originalLen - cleaned.length)
  };
}

class LccCompressor {
  constructor(options = {}) {
    this.model = options.model || "gpt-4.1";
    this.strategy = options.strategy || "local-first";
    this.maxTokens = options.maxTokens || null;
    this.removeBoilerplate = options.removeBoilerplate !== false;
    this.removeNearDuplicates = options.removeNearDuplicates !== false;
  }

  estimateTokens(text) {
    return estimateTokens(text, this.model);
  }

  compress(rawText, question = "") {
    const steps = [];
    let current = rawText || "";

    const norm = normalizeText(current);
    if (norm.removedChars > 0) {
      steps.push({ name: "normalize_text", removedChars: norm.removedChars });
      current = norm.text;
    }

    if (this.removeBoilerplate) {
      const boil = removeBoilerplate(current);
      if (boil.removedChars > 0) {
        steps.push({ name: "remove_boilerplate", removedChars: boil.removedChars });
        current = boil.text;
      }
    }

    if (this.removeNearDuplicates) {
      const dedup = deduplicateParagraphs(current);
      if (dedup.removedChars > 0) {
        steps.push({ name: "deduplicate_paragraphs", removedChars: dedup.removedChars });
        current = dedup.text;
      }
    }

    const origTokens = estimateTokens(rawText, this.model);
    let compTokens = estimateTokens(current, this.model);

    // Apply maxTokens truncation guardrail if requested and exceeding budget
    if (this.maxTokens && compTokens > this.maxTokens) {
      const words = current.split(/\s+/);
      const ratio = this.maxTokens / compTokens;
      const targetWordCount = Math.floor(words.length * ratio);
      current = words.slice(0, targetWordCount).join(" ") + "\n...[truncated by lcc maxTokens guardrail]";
      const newTokens = estimateTokens(current, this.model);
      steps.push({
        name: "max_tokens_guardrail",
        removedChars: 0,
        details: `Truncated from ${compTokens} to ${newTokens} tokens (max: ${this.maxTokens})`
      });
      compTokens = newTokens;
    }

    const savedTokens = Math.max(0, origTokens - compTokens);
    const savingsPercentage = origTokens > 0 ? Number(((savedTokens / origTokens) * 100).toFixed(2)) : 0;

    return {
      rawText: rawText || "",
      compressedText: current,
      originalTokens: origTokens,
      compressedTokens: compTokens,
      savedTokens,
      savingsPercentage,
      steps
    };
  }
}

class LccOptimizer extends LccCompressor {}

function compressContext(text, options) {
  const compressor = new LccCompressor(options);
  return compressor.compress(text);
}

module.exports = {
  LccCompressor,
  LccOptimizer,
  compressContext,
  estimateTokens
};
