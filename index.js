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
 * Tokenizer contract for the Node engine.
 *
 * The Node engine ships no tokenizer model: every count is a heuristic estimate.
 * This function states that honestly so callers never mistake it for a measurement
 * and never compare it 1:1 with Python's exact tiktoken counts. Python remains the
 * reference for billable token decisions; Node estimates are for local budgeting only.
 */
function tokenizerIdentity(model = "gpt-4.1") {
  return {
    tokenizer: "heuristic",
    tokenizer_id: "heuristic-bpe-v1",
    tokenizer_version: null,
    exact: false,
    model: model || "gpt-4.1",
    note: "Node estimate only; not equivalent to Python tiktoken exact counts."
  };
}

/**
 * Token estimate with its honesty metadata attached.
 */
function estimateTokensWithMeta(text, model = "gpt-4.1") {
  return {
    value: estimateTokens(text, model),
    method: "approximate",
    counter: "heuristic",
    encoding: null,
    isEstimate: true,
    tokenizer: tokenizerIdentity(model)
  };
}

/**
 * Normalizes text line endings, repeated spaces, and excessive newlines.
 *
 * Parity note (ADR 0014): intentionally simpler than Python's `normalize_text`,
 * which protects fenced code and tables. On plain prose both agree; on
 * code/tables Python is the reference.
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

/**
 * Renders an XML-tagged contract prompt optimized for Claude (Sonnet 5/Opus 5/3.7), Gemini 3.6, and KV-Cache.
 */
function renderClaudeXml(spec = {}) {
  const role = "You are a frontier technical assistant. Base your answers on the provided context.";
  const taskType = spec.taskType || "general";
  const constraints = spec.constraints || [];
  const reqs = [
    "Direct answer to the question with zero fluff.",
    "Key evidence drawn from the provided context.",
    "Limitations or uncertainties, stated explicitly when evidence is insufficient."
  ];
  if (spec.formatRequirements) {
    reqs.push(...spec.formatRequirements);
  }

  const constraintsXml = constraints.map(c => `    <rule>${c}</rule>`).join("\n");
  const reqsXml = reqs.map(r => `    <criterion>${r}</criterion>`).join("\n");

  const sections = [
    `<system_instructions>\n  <role>${role}</role>\n  <task_type>${taskType}</task_type>\n  <constraints>\n${constraintsXml}\n  </constraints>\n  <definition_of_done>\n${reqsXml}\n  </definition_of_done>\n</system_instructions>`,
    `<context>\n${(spec.context || "").trim() || "(no context provided)"}\n</context>`,
    `<user_query>\n${(spec.question || "").trim() || "(no question provided)"}\n</user_query>`
  ];

  return sections.join("\n\n") + "\n";
}

/**
 * Renders an agentic contract prompt optimized for AI IDEs (Cursor, Antigravity, Codex, Claude Code).
 */
function renderCodeAgent(spec = {}) {
  const taskType = spec.taskType || "coding";
  const constraints = [
    "Preserve existing codebase architecture, formatting, and conventions.",
    "Write production-grade, type-safe, runnable code without placeholders.",
    "Minimize conversational filler; deliver exact code diffs or implementations.",
    "Never delete environment configurations, lockfiles, or unrelated modules.",
    ...(spec.constraints || [])
  ];

  const sections = [
    "# System: AI Coding Agent Instructions & Operational Contract",
    `**Task Type:** \`${taskType}\``,
    "### Operational Boundaries & Negative Constraints:\n" + constraints.map(c => `- ${c}`).join("\n"),
    "### Reference Context & Codebase Memory:\n```\n" + ((spec.context || "").trim() || "(no context provided)") + "\n```",
    "### User Task / Objective:\n" + ((spec.question || "").trim() || "(no question provided)")
  ];

  return sections.join("\n\n") + "\n";
}

/**
 * Renders a structured markdown prompt.
 */
function renderStructuredMarkdown(spec = {}) {
  const taskType = spec.taskType || "general";
  const constraints = spec.constraints || [];

  const sections = [
    `## Role & Instructions\nYou are a careful technical assistant.\n\n**Task Type:** ${taskType}`,
    "## Constraints\n" + (constraints.length ? constraints.map(c => `- ${c}`).join("\n") : "- None specified"),
    "## Context\n" + ((spec.context || "").trim() || "(no context provided)"),
    "## Task\n" + ((spec.question || "").trim() || "(no question provided)")
  ];

  return sections.join("\n\n") + "\n";
}

/**
 * Renders default prompt.
 */
function renderDefault(spec = {}) {
  const sections = [
    "You are a careful technical assistant.",
    `Task type: ${spec.taskType || "general"}`,
    "User question:\n" + ((spec.question || "").trim() || "(no question provided)"),
    "Constraints:\n" + (spec.constraints && spec.constraints.length ? spec.constraints.map(c => `- ${c}`).join("\n") : "- None"),
    "Context:\n" + ((spec.context || "").trim() || "(no context provided)")
  ];

  return sections.join("\n\n") + "\n";
}

const TEMPLATES = {
  default: renderDefault,
  claude_xml: renderClaudeXml,
  xml: renderClaudeXml,
  claude: renderClaudeXml,
  code_agent: renderCodeAgent,
  cursor: renderCodeAgent,
  codex: renderCodeAgent,
  structured_markdown: renderStructuredMarkdown,
  markdown: renderStructuredMarkdown
};

function buildPrompt(spec, templateName = "default") {
  const fn = TEMPLATES[templateName] || TEMPLATES.default;
  return fn(spec);
}

class LccCompressor {
  constructor(options = {}) {
    this.model = options.model || "gpt-4.1";
    this.strategy = options.strategy || "local-first";
    this.maxTokens = options.maxTokens || null;
    this.removeBoilerplate = options.removeBoilerplate !== false;
    this.removeNearDuplicates = options.removeNearDuplicates !== false;
    this.template = options.template || "default";
  }

  estimateTokens(text) {
    return estimateTokens(text, this.model);
  }

  buildPrompt(spec, templateName) {
    return buildPrompt(spec, templateName || this.template);
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

/**
 * Classifies raw intake prompt into protocol readiness state.
 */
function parseIntake(rawInput) {
  const text = (rawInput || "").trim();
  if (!text) {
    return {
      intent: "Empty request",
      readiness: "BLOCKED",
      readinessScore: 0,
      ambiguityScore: 100,
      questions: ["Please provide a valid prompt or context."],
      assumptions: []
    };
  }

  const words = text.split(/\s+/);
  const wordCount = words.length;
  const hasQuestion = text.includes("?");
  const lowered = text.toLowerCase();

  let readiness = "READY_TO_EXECUTE";
  let questions = [];
  let assumptions = [];
  let readinessScore = 90;
  let ambiguityScore = 10;

  if (lowered.includes("maybe") || lowered.includes("something with") || lowered.includes("not sure") || lowered.includes("talvez")) {
    readiness = "NEEDS_INTAKE";
    readinessScore = 40;
    ambiguityScore = 60;
    questions.push("What is the primary objective and required deliverable format?");
    questions.append ? questions.push("Are there specific architectural constraints?") : null;
  } else if (wordCount < 5 && !hasQuestion) {
    readiness = "NEEDS_LIGHT_REFINEMENT";
    readinessScore = 70;
    ambiguityScore = 30;
    assumptions.push(`Interpreted '${text}' as a request to process or implement.`);
  }

  return {
    intent: text.slice(0, 80) + (text.length > 80 ? "..." : ""),
    readiness,
    readinessScore,
    ambiguityScore,
    questions,
    assumptions
  };
}

class LccIntake {
  constructor(options = {}) {
    this.model = options.model || "claude-sonnet-5";
    this.template = options.template || "claude_xml";
    this.optimizeContext = options.optimizeContext !== false;
    this.maxTokens = options.maxTokens || null;
    this.compressor = new LccCompressor({
      model: this.model,
      template: this.template,
      maxTokens: this.maxTokens
    });
  }

  parse(rawInput) {
    return parseIntake(rawInput);
  }

  process(rawInput, question = "") {
    const parsed = parseIntake(rawInput);
    let compression = null;
    let context = rawInput;

    if (this.optimizeContext && parsed.readiness !== "BLOCKED") {
      compression = this.compressor.compress(rawInput, question);
      context = compression.compressedText;
    }

    const prompt = buildPrompt({
      question: question || parsed.intent,
      context,
      taskType: "intake-refinement"
    }, this.template);

    const formattedPrompt = [
      `<!-- lcc-intake:readiness status="${parsed.readiness}" score="${parsed.readinessScore}" -->`,
      parsed.assumptions.length ? `<!-- assumptions: ${parsed.assumptions.join("; ")} -->` : "",
      prompt
    ].filter(Boolean).join("\n\n");

    return {
      rawInput,
      parsed,
      compression,
      formattedPrompt
    };
  }
}

class LccOptimizer extends LccCompressor {}

function compressContext(text, options) {
  const compressor = new LccCompressor(options);
  return compressor.compress(text);
}

function processIntake(rawInput, options) {
  const intake = new LccIntake(options);
  return intake.process(rawInput);
}

module.exports = {
  LccCompressor,
  LccOptimizer,
  LccIntake,
  compressContext,
  estimateTokens,
  estimateTokensWithMeta,
  tokenizerIdentity,
  buildPrompt,
  parseIntake,
  parseInput: parseIntake,
  processIntake,
  processIngestion: processIntake,
  TEMPLATES
};
