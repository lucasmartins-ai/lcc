// Pure mapping helpers for the lcc Claude Code hook.
//
// No engine, no I/O, no imports: everything here is a function of its arguments, so it is
// testable with `node test/hook-map.test.mjs` outside Claude Code.

/** Plugin options, with the defaults the README documents. */
export const DEFAULT_OPTIONS = {
  // Claude Code names a plugin's MCP server plugin:<plugin>:<server>.
  server: "plugin:lcc:lcc",
  question: "",
  // 'auto' is the local specialist-v3 ranker; 'jev' (remote) is opt-in.
  provider: "auto",
  threshold: 0.5,
  preserveRecentMessages: 6,
  trimHeadChars: 300,
  maxStateTokens: 25000,
  maxRequestTokens: 30000,
  minReductionRatio: 0.25,
  // Empty: no rules_mode is sent and the server default applies.
  rulesMode: "",
  // Idle stash (opt-in): after a gap longer than the cache TTL, stash spent tool outputs
  // before the first request rewrites the whole cold prefix. See docs/CLAUDE_CODE.md.
  idleStash: false,
  // 1-hour cache TTL + Claude Code's 60-minute cache keepalive window (2.1.296): the cache of
  // an open session is cold only about two hours after its last turn.
  idleTtlSeconds: 7200,
  idleMinRemovableTokens: 10000,
  idleMaxPassesPerSession: 8,
  // Opt-in local ledger: the server appends one line of counts per pass that stands, for the
  // statusline (scripts/statusline.mjs). Never text or paths; never sent anywhere.
  ledger: false,
};

/** The instructions an idle-triggered `$.session.compact` carries; the compact hook keys on it. */
export const IDLE_MARKER = "lcc:idle";

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
  // The MCP tool accepts jev | laya | auto | rules | specialist-v3; anything else falls back
  // to the default rather than sending a value the tool would reject.
  if (["jev", "laya", "auto", "rules", "specialist-v3"].includes(String(options.provider))) {
    merged.provider = String(options.provider);
  }
  if (["lossless", "lossy", "recoverable", "stashed"].includes(String(options.rulesMode))) {
    merged.rulesMode = String(options.rulesMode);
  }
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
  merged.idleStash = options.idleStash === true || options.idleStash === "true";
  merged.ledger = options.ledger === true || options.ledger === "true";
  merged.idleTtlSeconds = Math.max(
    1,
    number(options.idleTtlSeconds, DEFAULT_OPTIONS.idleTtlSeconds),
  );
  merged.idleMinRemovableTokens = Math.max(
    0,
    number(options.idleMinRemovableTokens, DEFAULT_OPTIONS.idleMinRemovableTokens),
  );
  merged.idleMaxPassesPerSession = Math.max(
    0,
    Math.trunc(number(options.idleMaxPassesPerSession, DEFAULT_OPTIONS.idleMaxPassesPerSession)),
  );
  return merged;
}

/**
 * Tokens of tool output a pass could remove: every tool result outside the pinned first
 * message and the newest `preserveRecent` messages. ponytail: chars/4, an upper bound on
 * what `stashed` removes; the pass itself re-checks with real token counts.
 */
export function estimateRemovableTokens(messages, preserveRecent) {
  const list = messages ?? [];
  const end = Math.max(1, list.length - Math.max(0, preserveRecent));
  let chars = 0;
  for (let index = 1; index < end; index += 1) {
    for (const result of list[index]?.toolResults ?? []) {
      if (typeof result?.text === "string") chars += result.text.length;
    }
  }
  return Math.floor(chars / 4);
}

/** Coarse idle-gap label for toasts and the request log (never the exact time). */
export function gapBucket(seconds) {
  if (!(seconds >= 0)) return "unknown";
  if (seconds < 300) return "<5m";
  if (seconds < 3600) return "5m-1h";
  if (seconds < 7200) return "1h-2h";
  if (seconds < 28800) return "2h-8h";
  return ">8h";
}

/**
 * A pass count read back from the plugin store. Anything that is not a non-negative finite
 * number (a hand-edited or corrupted store) counts as 0 rather than turning `passes += 1`
 * into string concatenation that never reaches `idleMaxPassesPerSession`.
 */
export function passCount(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.trunc(value) : 0;
}

/**
 * Should an idle stash run now? `fire: false` carries a `reason`; `notify` marks the ones
 * worth a toast (the gap is past the TTL, so the user would expect a pass).
 *
 * Cache contract edges (mirrored by `lcc.relevance.cache_contract.cache_state_from_idle`):
 * a gap exactly at `idleTtlSeconds` is cold; a negative gap (clock skew) or a missing /
 * non-finite timestamp never counts as cold, because a wrong "cold" rewrites a warm prefix.
 */
export function idleDecision({ options, lastEnd, passedEnd, now, passes, removable }) {
  const config = resolveOptions(options);
  if (!config.idleStash) return { fire: false, reason: "off" };
  if (!Number.isFinite(lastEnd) || !Number.isFinite(now)) {
    return { fire: false, reason: "no previous request" };
  }
  // Never twice over the same history: a pass needs a new request after the last one.
  if (passedEnd === lastEnd) return { fire: false, reason: "already stashed since the last request" };
  const gapSeconds = (now - lastEnd) / 1000;
  if (gapSeconds < 0) return { fire: false, reason: "clock skew (last request is in the future)", gapSeconds };
  if (!(gapSeconds >= config.idleTtlSeconds)) return { fire: false, reason: "cache warm", gapSeconds };
  if (passCount(passes) >= config.idleMaxPassesPerSession) {
    return { fire: false, notify: true, gapSeconds, reason: `${config.idleMaxPassesPerSession} passes already this session` };
  }
  if (typeof removable === "number" && removable < config.idleMinRemovableTokens) {
    return { fire: false, notify: true, gapSeconds, reason: `about ${removable} removable tokens, under ${config.idleMinRemovableTokens}` };
  }
  return { fire: true, gapSeconds };
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

/**
 * The MCP arguments for `compact_transcript`; null when there is nothing to ask about.
 * `cwd` is the session's working directory: with rules_mode recoverable it becomes the
 * workspace_root, so the server checks each removed file read against the disk.
 */
export function buildCompactArgs({ messages, instructions, options, cwd, extra }) {
  const config = resolveOptions(options);
  const question = (config.question || instructions || deriveGoal(messages)).trim();
  if (!question) return null;
  const rules = {};
  if (config.rulesMode) rules.rules_mode = config.rulesMode;
  if (config.rulesMode === "recoverable" && typeof cwd === "string" && cwd.startsWith("/")) {
    rules.workspace_root = cwd;
  }
  return {
    messages: toMcpMessages(messages),
    question,
    provider: config.provider,
    threshold: config.threshold,
    preserve_recent: config.preserveRecentMessages,
    trim_head_chars: config.trimHeadChars,
    max_state_tokens: config.maxStateTokens,
    max_request_tokens: config.maxRequestTokens,
    min_reduction: config.minReductionRatio,
    ...rules,
    ...extra,
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
        // The rules policy keeps the latest failed call; forward the flag when present.
        ...(result.is_error === true || result.isError === true ? { is_error: true } : {}),
      }));
    }
    return entry;
  });
}

/** The tail of the server's one-line receipt (`lcc: ` dropped), or "" when it sent none. */
export function receiptTail(payload) {
  return typeof payload?.receipt === "string" ? payload.receipt.replace(/^lcc: /, "") : "";
}

/** The MCP tool answers with JSON in a text content block. */
export function parseToolResult(content) {
  const text = (content ?? [])
    .filter((block) => block?.type === "text" && typeof block.text === "string")
    .map((block) => block.text)
    .join("");
  if (!text.trim()) throw new Error("empty tool result");
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    // What Claude Code hands back for an answer over its MCP result cap.
    throw new Error(`tool result is not JSON (${text.length} chars; over Claude Code's MCP output cap?)`);
  }
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
  const dropped = number(report?.tool_calls_dropped, 0);
  const trimmed = number(report?.tool_calls_trimmed, 0);
  // rules_mode lossless/recoverable remove by pointer: dedupes and recovery replacements.
  const deduped = number(report?.tool_calls_deduped, 0);
  const replaced = number(report?.tool_calls_replaced, 0);
  if (dropped + trimmed + deduped + replaced === 0) {
    return { replace: false, reason: "the pass removed no tool output" };
  }
  return {
    replace: true,
    reason: `kept ${messages.length} messages, dropped ${dropped} tool call(s), trimmed ${trimmed}, deduped ${deduped}, replaced ${replaced}`,
  };
}

/**
 * Expands a `ref_unchanged` / `ref_blocks` answer against `source`, the transcript the hook
 * sent. `{ ref: i }` is `source[i]`, the caller's own message (with its engine `handle`, when
 * it had one). `{ ref: i, toolUses, toolResults }` is `source[i]` rebuilt from the kept blocks:
 * a number is a block of `source[i]`, `{ ref, tool_use_id, text, head?, tail? }` a replaced
 * result, `source text[:head] + text + source text[-tail:]` (UTF-16 units, JavaScript's own).
 * Anything else is a whole message. Throws on any ref that does not fit `source`, so a
 * mismatched answer never reaches the session.
 */
export function expandRefs(messages, source) {
  const at = (list, index, what) => {
    if (!Number.isInteger(index) || index < 0 || index >= (list?.length ?? 0)) {
      throw new Error(`${what} ref ${index} outside the transcript`);
    }
    return list[index];
  };
  return (messages ?? []).map((message) => {
    if (typeof message?.ref !== "number") return toSessionMessages([message])[0];
    const original = at(source, message.ref, "message");
    if (!("toolUses" in message) && !("toolResults" in message)) return original;
    const toolResults = (message.toolResults ?? []).map((block) => {
      if (typeof block === "number") return at(original.toolResults, block, "tool result");
      const before = at(original.toolResults, block?.ref, "tool result");
      const text = before?.text;
      const head = block.head ?? 0;
      const tail = block.tail ?? 0;
      if (
        typeof text !== "string" || typeof block.text !== "string" ||
        before.tool_use_id !== block.tool_use_id ||
        !Number.isInteger(head) || !Number.isInteger(tail) || head < 0 || tail < 0 ||
        head + tail > text.length
      ) {
        throw new Error(`tool result patch does not fit message ${message.ref}`);
      }
      return {
        tool_use_id: before.tool_use_id,
        text: text.slice(0, head) + block.text + (tail ? text.slice(text.length - tail) : ""),
        ...(before.isError === true || before.is_error === true ? { isError: true } : {}),
      };
    });
    const entry = {
      role: original.role,
      text: original.text,
      toolUses: (message.toolUses ?? []).map((index) => at(original.toolUses, index, "tool use")),
    };
    if (toolResults.length) entry.toolResults = toolResults;
    return entry;
  });
}

/** The compacted conversation in the shape the engine rebuilds messages from. */
export function toSessionMessages(messages) {
  return (messages ?? []).map((message) => {
    const entry = {
      role: message.role,
      text: typeof message.text === "string" ? message.text : "",
      toolUses: message.toolUses ?? [],
    };
    if (message.toolResults?.length) {
      // The engine rebuilds `is_error` from `isError` only; the MCP payload says `is_error`.
      entry.toolResults = message.toolResults.map((result) => ({
        tool_use_id: result.tool_use_id,
        text: typeof result.text === "string" ? result.text : "",
        ...(result.is_error === true || result.isError === true ? { isError: true } : {}),
      }));
    }
    return entry;
  });
}
