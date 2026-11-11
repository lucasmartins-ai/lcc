# Handing a session to another agent

`lcc handoff` writes what the next agent needs to pick up a session, taken verbatim from its
transcript. It works across tools: Claude Code can hand to Codex, Codex to Gemini CLI, and so
on, because the packet is a Markdown file and every stashed output in it is one `lcc recall`
away in the same local stash.

```sh
lcc handoff ~/.claude/projects/<project>/<session>.jsonl
# .lcc/handoff/3f9a1c0d8e7b.md
```

Then tell the next agent: "read `.lcc/handoff/3f9a1c0d8e7b.md` and continue".

`lcc handoff --latest` finds the session for you: the most recently written Claude Code
session or Codex rollout of the current directory. Run it after you quit one agent and before
you start the next. From inside a running session the newest session is that session, so
there pass the path instead. It prints the chosen path on stderr. Codex runs nobody sat in
(`codex exec`, `codex review` and their subagents) are skipped, and so is a session of another
directory that shares the Claude Code project folder (`/r/a-b` and `/r/a_b` do).

## The next session is offered the previous one

With the `SessionStart` hook that [`lcc setup`](CLAUDE_CODE.md#one-command-lcc-setup) adds
(`lcc handoff --hook`, matcher `startup`), a new Claude Code session gets one line when the
directory has an earlier session, from Claude Code or Codex, written in the last 7 days:

```text
lcc handoff: a Codex session in this directory was last written 3 h ago. If the user wants to continue that work, run `lcc handoff <path> --stdout` for its requests, edited files, last error and stashed outputs. Otherwise ignore this line.
```

It is an offer. No packet is built and nothing else enters the context, because the new
session may be unrelated work. Resumed, cleared and compacted sessions get no line, and any
error prints nothing, so the session always starts. Codex does not load this hook: there, run
`lcc handoff --latest` first.

## What the packet holds

| Section | Source |
| --- | --- |
| User requests | the first request and the latest 5, verbatim, 500 characters each, messages sent while the agent worked included; injected context (reminders, environment, AGENTS.md) is left out |
| Files edited | Edit/Write/MultiEdit/NotebookEdit, `write_file`/`replace`/`edit`, and `apply_patch` file headers in any tool input, rename targets included; failed edits are left out |
| Files read | Read, `read_file`, `view` |
| Last tool error | the transcript's `is_error` flag when it carries one, otherwise error text or a non-zero exit code in command output, or error text in edit output; the last 1,200 characters |
| Stashed outputs | every `lcc recall <id>` in the transcript (pointers and ids up to the full sha256), newest first (30 at most), each checked against its sha256 now; ids that are missing, damaged or ambiguous are listed apart |
| Receipt | the source path, size and sha256, what was read, message and call counts, the stash directory and the lcc version |

Quoted text sits in fences it cannot close, labelled as data, not instructions; paths, tool
names and stash openings sit in inline code, so nothing in them renders as Markdown or HTML. Secrets
(API keys, tokens, passwords, bearer and cookie values) are masked with the request-log rules;
masking runs before any cut, and a cut never leaves part of a word behind. File paths are kept.

## Inputs

- Claude Code session JSONL and Codex rollout JSONL, read directly.
- Any other tool through a JSON transcript, `{"messages": [...]}` with `role`, `text`,
  `toolUses` and `toolResults`: the same shape `lcc compact --mode tool-calls` takes.

A JSONL session over 17 MB is read as its first 1 MB and its last 16 MB; the receipt says so.
A JSON transcript is always read whole.

## Output

The packet goes to `.lcc/handoff/<sha12>.md`, named by its own hash and owner-only (0600). The
directory gets a `.gitignore`, so packets are never committed. `--out DIR` changes the directory
and `--stdout` prints the packet instead. There is no clock in the packet: the same transcript
and stash give the same file.

## Limits

- The next agent must use the same stash (`~/.cache/lcc/stash`, or `LCC_STASH_DIR`) to recall.
- Files read through shell commands (`cat`, `sed -n`) are not listed.
- In a long session, files touched only in the unread middle are not listed.
- A digit-free secret over 32 characters with no known prefix is not masked.
