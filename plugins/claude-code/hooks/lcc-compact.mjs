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
// The one exception is the opt-in idle stash (`idleStash`): a compaction it started answers
// `{ skip }` on any failure, because a built-in summary on a cold cache costs the most.
//
// EARLY ACCESS: function hooks require Claude Code 2.1.274+ and
// CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1. See plugins/claude-code/hooks/README.md.

import {
  IDLE_MARKER,
  buildCompactArgs,
  decideReplacement,
  estimateRemovableTokens,
  expandRefs,
  gapBucket,
  hasUnsupportedContent,
  idleDecision,
  parseToolResult,
  passCount,
  receiptTail,
  resolveOptions,
} from "./map.mjs";

/** UI is best effort: a headless engine without a log/toast surface must not fail a hook. */
function log($, text) {
  try {
    $.ui.log(text);
  } catch {
    // no log surface
  }
}

function notify($, text) {
  log($, text);
  try {
    $.ui.toast(text, { timeoutMs: 15000 });
  } catch {
    // no toast surface
  }
}

function message(error) {
  return error instanceof Error ? error.message : String(error);
}

/**
 * The session's working directory, which becomes `workspace_root` for rules_mode recoverable.
 * Preferred: `event.cwd` when it is absolute. Fallback: `process.cwd()` when there is a
 * `process`. Claude Code 2.1.296 runs hook modules in a worker with no `process` and puts no
 * `cwd` on `session.compact`, so there this is undefined and no workspace_root is sent.
 */
export function sessionCwd(event) {
  if (typeof event?.cwd === "string" && event.cwd.startsWith("/")) return event.cwd;
  return globalThis.process?.cwd?.();
}

/**
 * Ledger arguments for this pass. The session id always travels, because LCC_LEDGER=1 on the
 * server turns the ledger on without the plugin option; the server keeps only its hash, and
 * only when it writes. `ledger: true` is sent only when the plugin option is on. The server
 * writes the file (the hook worker has no file system).
 */
async function ledgerArgs($, configured) {
  const on = configured.ledger ? { ledger: true } : {};
  try {
    const id = await $.session.id();
    return typeof id === "string" && id ? { ...on, ledger_session: id } : on;
  } catch {
    return on;
  }
}

const IDLE_KEY_PREFIX = "idle:";
const DEFAULT_SERVER = "plugin:lcc:lcc"; // the manifest's .mcp.json key "lcc"
const IDLE_KEYS_KEPT = 64;

// Claude Code caps an MCP result (MAX_MCP_OUTPUT_TOKENS, 25,000 tokens by default on 2.1.296)
// and hands `$.mcp.call` a pointer text in place of a larger one. Asked this way, the server
// answers with refs into the transcript the hook sent: only replaced text travels back.
const COMPACT_ANSWER = { ref_unchanged: true, ref_blocks: true };

/** A stored idle record, or `{}` for anything that is not a plain object (corrupted store). */
function idleState(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

/** Per-session idle state in the plugin's store: `{ end, passes }`, `end` in clock ms. */
async function remember($, key, value) {
  await $.store.set(key, value);
  const keys = (await $.store.keys()).filter((name) => name.startsWith(IDLE_KEY_PREFIX));
  if (keys.length <= IDLE_KEYS_KEPT) return;
  // ponytail: O(n) reads past the cap only; the store is the plugin's own small JSON file.
  const ends = await Promise.all(keys.map(async (name) => [name, (await $.store.get(name))?.end ?? 0]));
  ends.sort((a, b) => a[1] - b[1]);
  for (const [name] of ends.slice(0, ends.length - IDLE_KEYS_KEPT)) await $.store.delete(name);
}

/**
 * The idle pass itself: provider rules, rulesMode stashed over `messages`. Resolves
 * `{ messages, removed, stashed }` or `{ skip: reason }`; never throws, never toasts.
 */
export async function stashIdle($, messages, configured, gap = "unknown", cwd) {
  try {
    const unsupported = hasUnsupportedContent(messages);
    if (unsupported) return { skip: `this session has ${unsupported}` };
    const options = { ...configured, provider: "rules", rulesMode: "stashed", minReductionRatio: 0 };
    // The session directory lets `stashed` also take file reads the disk still holds.
    const root = typeof cwd === "string" && cwd.startsWith("/") ? { workspace_root: cwd } : {};
    const args = buildCompactArgs({
      messages: messages ?? [],
      options,
      // An automatic pass only fires past the TTL, so the provider cache is cold; a pass typed
      // by hand (`/compact lcc:idle`) knows nothing about the cache.
      extra: {
        trigger: "idle",
        idle_gap_bucket: gap,
        cache_state: gap === "manual" ? "unknown" : "cold",
        ...COMPACT_ANSWER,
        ...root,
      },
    });
    if (!args) return { skip: "no objective to judge against" };
    const { content, isError } = await $.mcp.call(configured.server, "compact_transcript", args);
    if (isError) return { skip: `compact_transcript failed on server '${configured.server}'` };
    const payload = parseToolResult(content);
    const decision = decideReplacement({ report: payload.report, messages: payload.messages, minReductionRatio: 0 });
    if (!decision.replace) return { skip: decision.reason };
    const removed = Number(payload.report.tokens_before) - Number(payload.report.tokens_after);
    if (!(removed >= configured.idleMinRemovableTokens)) {
      return { skip: `removed ${Number.isFinite(removed) ? removed : "?"} tokens, under ${configured.idleMinRemovableTokens}` };
    }
    return {
      messages: expandRefs(payload.messages, messages),
      removed,
      stashed: payload.report.tool_calls_stashed ?? 0,
      receipt: receiptTail(payload),
    };
  } catch (error) {
    return { skip: message(error) };
  }
}

const stood = (result, gap) =>
  `lcc: idle stash (removed ${result.removed} tokens, ${result.stashed} output(s) stashed, idle ${gap}; recall brings any back)` +
  (result.receipt ? ` · ${result.receipt}` : "");

/**
 * One idle check and, when due, the idle compaction. The pass is computed here, before
 * `$.session.compact`; the `session.compact` hook (or, on re-entry, its `.catch`) hands it
 * in. If neither does, the classic PreCompact hook blocks Claude Code's own summary.
 */
async function idlePass($, configured, idle, when) {
  const key = IDLE_KEY_PREFIX + (await $.session.id());
  const saved = idleState(await $.store.get(key));
  const base = {
    options: configured,
    lastEnd: saved.end,
    passedEnd: saved.passedEnd,
    now: await $.clock.now(),
    passes: saved.passes,
  };
  let decision = idleDecision(base);
  let messages = [];
  if (decision.fire) {
    messages = await $.session.messages();
    decision = idleDecision({ ...base, removable: estimateRemovableTokens(messages, configured.preserveRecentMessages) });
  }
  if (decision.notify) notify($, `lcc: idle stash skipped (${decision.reason})`);
  if (!decision.fire) return;
  const gap = gapBucket(decision.gapSeconds);
  log($, `lcc: idle stash starting (${when}, idle ${gap})`);
  // At session.start the plugin's own server may not be connected yet.
  if (configured.server === DEFAULT_SERVER) await $.mcp.connect("lcc").catch(() => undefined);
  const result = await stashIdle($, messages, configured, gap, await $.session.cwd());
  let passes = passCount(saved.passes);
  if (result.skip) {
    notify($, `lcc: idle stash skipped (${result.skip})`);
  } else {
    idle.prepared = { count: messages.length, messages: result.messages };
    try {
      const outcome = await $.session.compact({ instructions: IDLE_MARKER });
      if (outcome?.skip) notify($, `lcc: idle stash skipped (${outcome.skip})`);
      else if (!idle.prepared?.used) {
        // Claude Code compacted without handing the call to this plugin's hook.
        notify($, "lcc: idle stash did not stand (Claude Code compacted on its own)");
      } else {
        passes += 1;
        notify($, stood(result, gap));
      }
    } finally {
      idle.prepared = null;
    }
  }
  // Never twice over the same history, whatever the outcome.
  await remember($, key, { ...saved, passedEnd: saved.end, passes });
}

/** Fail-safe wrapper: an idle pass never throws into the engine. */
function safely($, configured, idle, when) {
  return idlePass($, configured, idle, when).catch((error) => {
    notify($, `lcc: idle stash skipped (${message(error)})`);
  });
}

/** @type {import('claude-code').Register} */
export const register = (on, options) => {
  const configured = resolveOptions(options);

  // The pass prepared for the plugin's own session.compact call.
  const idle = { prepared: null };

  on("session.compact", async ($, event, next) => {
    if (event.trigger === "precompute") return next(event);
    // `/compact lcc:idle` typed by hand: the same pass, and `{ skip }` on any failure.
    if (event.instructions === IDLE_MARKER) {
      if (event.agentId !== undefined) return { skip: "lcc idle stash: subagent" };
      const ready = idle.prepared;
      if (ready && event.messages?.length === ready.count) {
        ready.used = true;
        return { messages: ready.messages };
      }
      const result = await stashIdle($, event.messages, configured, "manual", sessionCwd(event));
      if (result.skip) {
        notify($, `lcc: idle stash skipped (${result.skip})`);
        return { skip: `lcc idle stash: ${result.skip}` };
      }
      notify($, stood(result, "manual"));
      return { messages: result.messages };
    }

    const unsupported = hasUnsupportedContent(event.messages);
    if (unsupported) {
      notify($, `lcc: built-in summary (this session has ${unsupported})`);
      return next(event);
    }

    const args = buildCompactArgs({
      messages: event.messages ?? [],
      instructions: event.instructions,
      options: configured,
      cwd: sessionCwd(event),
      extra: { ...COMPACT_ANSWER, ...(await ledgerArgs($, configured)) },
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
      const via = payload.report?.provider_used ?? configured.provider;
      // The server's one-line receipt (tokens before -> after, what went, how to recall it).
      const receipt = receiptTail(payload);
      notify($, `lcc: verbatim compaction via ${via}, no summary (${receipt || decision.reason})`);
      return { messages: expandRefs(payload.messages, event.messages) };
    } catch (error) {
      notify($, `lcc: built-in summary (${message(error)})`);
      return next(event);
    }
  }).catch(($, event, next) => {
    // Re-entry, as documented: the handler answers in the hook's place without `$`. It hands
    // in the prepared idle pass or vetoes. Claude Code 2.1.296 skipped this handler too for
    // a timer's call; the classic PreCompact hook is the backstop that held there.
    if (event.instructions !== IDLE_MARKER) return next(event);
    const ready = idle.prepared;
    if (ready && event.agentId === undefined && event.messages?.length === ready.count) {
      ready.used = true;
      return { messages: ready.messages };
    }
    return { skip: "lcc idle stash: no prepared pass for this transcript" };
  });

  // Idle stash, opt-in. Off: these hooks are never registered, so nothing changes.
  //
  // Where it can run on Claude Code 2.1.296 (observed live, docs/CLAUDE_CODE.md):
  // - `prompt.submit`: refused ("it would compact under the turn this hook is holding");
  // - a `$.clock.after` timer: the call is the plugin's own code, so Claude Code skips all of
  //   this plugin's hooks (re-entry) and runs its own summary, which PreCompact then blocks;
  // - `session.start` of a resumed session: works; this hook answers the compaction.
  // So the pass runs when a session is resumed after the gap, before its first request.
  if (!configured.idleStash) return;

  on("session.start", async ($, event, next) => {
    const result = await next(event);
    await safely($, configured, idle, "resume");
    return result;
  });

  on("turn.complete", async ($, event, next) => {
    const result = await next(event);
    if (event.agentId !== undefined) return result; // subagents: 5-minute TTL, no idle
    try {
      const key = IDLE_KEY_PREFIX + (await $.session.id());
      const saved = idleState(await $.store.get(key));
      await remember($, key, { ...saved, end: await $.clock.now() });
    } catch (error) {
      log($, `lcc: idle stash bookkeeping failed (${message(error)})`);
    }
    return result;
  });
};
