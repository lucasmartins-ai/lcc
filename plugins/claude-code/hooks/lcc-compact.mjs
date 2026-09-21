// Claude Code function-hook adapter for `lcc compact --mode tool-calls`.
//
// The engine hands this module a `session.compact` event: the transcript it is about to
// summarize. The module hands that transcript to the `lcc mcp` server shipped with the
// plugin (`compact_transcript`), which pairs every tool call with its result, scores the
// pairs with TypeSafe Jev, and returns the conversation minus the pairs that are spent.
//
// Nothing is rewritten: kept messages carry their original bytes, and user/assistant text
// is never touched. Every failure path calls `next(event)`, so a hook that cannot do its
// job lets Claude Code's own compaction run instead of leaving the session uncompacted.
//
// EARLY ACCESS: function hooks require Claude Code 2.1.274+ and
// CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1. See plugins/claude-code/hooks/README.md.

import {
  buildCompactArgs,
  decideReplacement,
  hasUnsupportedContent,
  parseToolResult,
  resolveOptions,
  toSessionMessages,
} from "./map.mjs";

function notify($, text) {
  $.ui.log(text);
  $.ui.toast(text, { timeoutMs: 15000 });
}

function message(error) {
  return error instanceof Error ? error.message : String(error);
}

/** @type {import('claude-code').Register} */
export const register = (on, options) => {
  const configured = resolveOptions(options);

  on("session.compact", async ($, event, next) => {
    if (event.trigger === "precompute") return next(event);

    const unsupported = hasUnsupportedContent(event.messages);
    if (unsupported) {
      notify($, `lcc: built-in summary (this session has ${unsupported})`);
      return next(event);
    }

    const args = buildCompactArgs({
      messages: event.messages ?? [],
      instructions: event.instructions,
      options: configured,
    });
    if (!args) return next(event);

    try {
      const { content, isError } = await $.mcp.call(
        configured.server,
        "compact_transcript",
        args,
      );
      if (isError) throw new Error(`compact_transcript failed on server '${configured.server}'`);

      const payload = parseToolResult(content);
      const decision = decideReplacement({
        report: payload.report,
        messages: payload.messages,
        minReductionRatio: configured.minReductionRatio,
      });
      if (!decision.replace) {
        notify($, `lcc: built-in summary (${decision.reason})`);
        return next(event);
      }
      notify($, `lcc: verbatim compaction, no summary (${decision.reason})`);
      return { messages: toSessionMessages(payload.messages) };
    } catch (error) {
      notify($, `lcc: built-in summary (${message(error)})`);
      return next(event);
    }
  });
};
