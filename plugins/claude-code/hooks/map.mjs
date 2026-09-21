// Pure mapping helpers for the lcc Claude Code hook.
//
// No engine, no I/O, no imports: everything here is a function of its arguments, so it is
// testable with `node test/hook-map.test.mjs` outside Claude Code.

/** Plugin options, with the defaults the README documents. */
export const DEFAULT_OPTIONS = {
  server: "lcc",
  question: "",
  threshold: 0.5,
  preserveRecentMessages: 6,
  trimHeadChars: 300,
  maxStateTokens: 25000,
  maxRequestTokens: 30000,
  minReductionRatio: 0.25,
};

/** Matches the shape `claude-code`'s SessionMessage rebuilds from. */
const KNOWN_MESSAGE_KEYS = new Set(["role", "text", "toolUses", "toolResults"]);

function number(value, fallback) {
  const parsed = typeof value === "string" ? Number(value) : value;
  return typeof parsed === "number" && Number.isFinite(parsed) ? parsed : fallback;
}

/** Merge user options over the defaults, ignoring values that make no sense. */
export function resolveOptions(options = {}) {
  const merged = { ...DEFAULT_OPTIONS };
  if (options.server) merged.server = String(options.server);
  if (options.question) merged.question = String(options.question);
  merged.threshold = number(options.threshold, DEFAULT_OPTIONS.threshold);
  merged.preserveRecentMessages = Math.max(
    0,
    Math.trunc(number(options.preserveRecentMessages, DEFAULT_OPTIONS.preserveRecentMessages)),
  );
  merged.trimHeadChars = Math.max(
    0,
    Math.trunc(number(options.trimHeadChars, DEFAULT_OPTIONS.trimHeadChars)),
  );
  merged.maxStateTokens = Math.max(
    64,
    Math.trunc(number(options.maxStateTokens, DEFAULT_OPTIONS.maxStateTokens)),
  );
  merged.maxRequestTokens = Math.max(
    merged.maxStateTokens + 1,
    Math.trunc(number(options.maxRequestTokens, DEFAULT_OPTIONS.maxRequestTokens)),
  );
  merged.minReductionRatio = Math.min(
    1,
    Math.max(0, number(options.minReductionRatio, DEFAULT_OPTIONS.minReductionRatio)),
  );
  return merged;
}

/** The objective the judge is asked about: the explicit option or the `/compact` text when
 * there is one, otherwise the newest **user** prompts (the task the session is on). */
export function deriveGoal(messages, limit = 500) {
  const texts = [];
  for (let index = messages.length - 1; index >= 0 && texts.length < 3; index -= 1) {
    if (messages[index]?.role !== "user") continue;
    const text = typeof messages[index]?.text === "string" ? messages[index].text.trim() : "";
    if (text) texts.unshift(text);
  }
  return texts.join("\n").slice(0, limit);
}

/**
 * Names a message field the hook cannot rebuild. The engine rebuilds a message without its
 * handle from `role`, `text` and tool blocks alone, so content we do not model (images,
 * attachments) would be lost by a replacement — the hook stands down instead.
 * Metadata (strings, numbers, booleans) is ignored: it survives the round trip either way.
 */
export function hasUnsupportedContent(messages) {
  for (const message of messages ?? []) {
    if (!message || typeof message !== "object") continue;
    for (const [key, value] of Object.entries(message)) {
      if (KNOWN_MESSAGE_KEYS.has(key)) continue;
      if (Array.isArray(value) && value.length > 0) return `unsupported content in '${key}'`;
      if (value && typeof value === "object" && Object.keys(value).length > 0) {
        return `unsupported content in '${key}'`;
      }
    }
  }
  return null;
}

/** The MCP arguments for `compact_transcript`; null when there is nothing to ask about. */
export function buildCompactArgs({ messages, instructions, options }) {
  const config = resolveOptions(options);
  const question = (config.question || instructions || deriveGoal(messages)).trim();
  if (!question) return null;
  return {
    messages: toMcpMessages(messages),
    question,
    provider: "jev",
    threshold: config.threshold,
    preserve_recent: config.preserveRecentMessages,
    trim_head_chars: config.trimHeadChars,
    max_state_tokens: config.maxStateTokens,
    max_request_tokens: config.maxRequestTokens,
    min_reduction: config.minReductionRatio,
  };
}

/** Session messages as the MCP tool reads them (its `toolUses` / `toolResults` shape). */
export function toMcpMessages(messages) {
  return (messages ?? []).map((message) => {
    const entry = { role: message.role, text: typeof message.text === "string" ? message.text : "" };
    if (message.toolUses?.length) {
      entry.toolUses = message.toolUses.map((tool) => ({
        tool_use_id: tool.tool_use_id,
        tool: tool.tool,
        input: tool.input ?? {},
      }));
    }
    if (message.toolResults?.length) {
      entry.toolResults = message.toolResults.map((result) => ({
        tool_use_id: result.tool_use_id,
        text: typeof result.text === "string" ? result.text : "",
      }));
    }
    return entry;
  });
}

/** The MCP tool answers with JSON in a text content block. */
export function parseToolResult(content) {
  const text = (content ?? [])
    .filter((block) => block?.type === "text" && typeof block.text === "string")
    .map((block) => block.text)
    .join("");
  if (!text.trim()) throw new Error("empty tool result");
  const payload = JSON.parse(text);
  if (!payload?.report || !Array.isArray(payload.messages)) {
    throw new Error("tool result is not a compaction payload");
  }
  return payload;
}

/**
 * Should the compaction replace the built-in summary? Only a judged pass that actually
 * removed something may. A degraded pass, an empty result or a pass below the minimum
 * reduction stands down, and the engine summarizes as it always did.
 */
export function decideReplacement({ report, messages, minReductionRatio }) {
  if (report?.degraded === true) {
    return { replace: false, reason: `judge unavailable (${report?.degradation_reason ?? "degraded"})` };
  }
  if (!Array.isArray(messages) || messages.length === 0) {
    return { replace: false, reason: "the pass returned no messages" };
  }
  const ratio = number(report?.reduction_ratio, 0);
  const minimum = number(minReductionRatio, DEFAULT_OPTIONS.minReductionRatio);
  if (ratio < minimum) {
    return {
      replace: false,
      reason: `below the ${(minimum * 100).toFixed(0)}% minimum (${(ratio * 100).toFixed(1)}%)`,
    };
  }
  const dropped = report?.tool_calls_dropped ?? 0;
  const trimmed = report?.tool_calls_trimmed ?? 0;
  return {
    replace: true,
    reason: `kept ${messages.length} messages, dropped ${dropped} tool call(s), trimmed ${trimmed}`,
  };
}

/** The compacted conversation in the shape the engine rebuilds messages from. */
export function toSessionMessages(messages) {
  return (messages ?? []).map((message) => {
    const entry = {
      role: message.role,
      text: typeof message.text === "string" ? message.text : "",
      toolUses: message.toolUses ?? [],
    };
    if (message.toolResults?.length) entry.toolResults = message.toolResults;
    return entry;
  });
}
