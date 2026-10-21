# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Receipt after every tool-call compaction pass.** `lcc compact --mode tool-calls` prints one
  line last: tokens before and after, what was removed, and how to recall it; `--receipt`
  prints the five largest stashed outputs with their `recall` ids and the cache effect. The
  MCP `compact_transcript` answer carries the line as `receipt`, and the Claude Code hook
  toasts it.
- **Opt-in local ledger and statusline** (Claude Code plugin). `ledger: true` (or
  `LCC_LEDGER=1`) appends one line of counts per applied compaction to
  `~/.cache/lcc/ledger.jsonl` (`LCC_LEDGER_PATH`): no text, no paths, a hashed session id,
  never sent anywhere. Off by default. `plugins/claude-code/scripts/statusline.mjs` shows the
  session's removed tokens, stashed outputs and cache-read share. See
  `docs/CLAUDE_CODE.md#receipt-ledger-and-statusline`.

### Security

- Existing Jev ledger files are tightened to `0600` before appending (#70).
- **HTTP server: tool errors no longer echo exception text** (#73). A failing tool call over
  `lcc mcp --http` shows only the handlers' own validation messages (missing `text`, a bad
  `provider`, `'threshold' must be a number`); any other error answers
  `tool call failed (<Type>)` and is logged server-side. Checks below the tool handlers
  (cache-factor and compactor argument checks) are among those that now answer with the
  type only over HTTP. stdio is unchanged.
- **HTTP server: no host-disk access.** `lcc mcp --http` now refuses `workspace_root` and
  `laya_model` (as it already refused the stash and `recall`). With `provider: rules`,
  `rules_mode: recoverable`, an anonymous caller could send a crafted transcript naming any
  file on the server and read `replace_disk_verified` / `keep_disk_mismatch` /
  `keep_disk_missing` back: a file-existence and file-content oracle on the host. A failing
  tool call over HTTP now answers `internal error` without the exception text.
- **MCP transports survive nested JSON.** A single deeply nested line (`[[[[…`) raised an
  uncaught `RecursionError` and killed the stdio server (`lcc mcp`); it now gets a `-32700`
  parse error and the server keeps serving. The HTTP server answers `400`.
- **Regex/quadratic denial of service.** The speech-cleaning filler `\s+n[eé]\?` backtracked
  quadratically on long blank runs (20 KB took 2 s; 1 MB would take over an hour); it now
  runs in linear time with identical output. Near-duplicate paragraph detection compared
  every pair with `difflib` (200 KB of similar-length paragraphs took minutes); it now
  skips pairs on exact upper bounds (`real_quick_ratio`, `quick_ratio`), builds each kept
  paragraph's index once, and stops under a deterministic work budget
  (`NEAR_DUP_CHAR_BUDGET`), keeping the remaining paragraphs and adding a report warning.
  Results below the budget are unchanged.
- **`LCC_DISABLE_NETWORK=1` is honored everywhere.** The router's cloud solver (Fireworks /
  OpenAI-compatible) and the local agent's non-loopback endpoints ignored it; both refuse now.
- **`lcc explain` escapes terminal control characters** from reports and `--source` files
  (ANSI/OSC escapes, carriage returns, 8-bit CSI), so untrusted tool output cannot recolour,
  hide or rewrite what is printed, or set the terminal title or clipboard.
- **Secrets in local logs.** Request-log redaction now covers secret names glued to longer
  identifiers (`TYPESAFE_API_KEY=…`, `client_secret: …`) and `Cookie:` headers, and caps the
  `field` value like the goal. The Jev ledger is created `0600` (was umask, usually
  world-readable) and redacts bearer tokens and the API key from stored error bodies.
- **Claude Code pin hook:** the last tool error is pinned inside a fence it cannot close and
  labelled as quoted data, so an injected tool output cannot pose as instructions to the
  built-in summarizer.
- **Supply chain:** GitHub Actions are pinned to commit SHAs (version kept in a comment), the
  CI workflow sets `permissions: contents: read`, both Docker images run as an unprivileged
  user, and `.dockerignore` excludes `.env` files and keys.

### Added

- **Continuous invariant harness** (plan items B1 + B2). `tests/invariants.py` holds seven
  invariants of the `rules` modes (idempotence, verbatim, recall round-trip, no corruption,
  stable placeholders, accounting, fail-closed). They run over hypothesis-generated transcripts
  for `LCC_FUZZ_SECONDS` (60 s in PR CI, 600 s in a nightly workflow that uploads seeds and
  shrunk failing inputs and gates nothing), over a versioned `tests/corpus/adversarial/` on
  every run, and across `PYTHONHASHSEED` values. `hypothesis` is a new dev-only dependency. A
  planted bug (stash pointer ids from `hash()`) fails the PR-budget run in about 30 s.

- **`lcc measure-session --input-map`: where a session's input tokens go.** Reads the
  provider's own usage records in a Claude Code session or Codex rollout and reports billed
  input split into uncached, cache-write and cache-read tokens, the cost-weighted split
  (read 0.1×, write 1.25×, as in `docs/CACHE_ALIGNMENT.md`), and each category's share of
  billed input: fixed overhead (system prompt, tool schemas, instructions), tool results,
  tool-call inputs, harness attachments, user and assistant text, compaction summaries. Plus
  a drill-down by tool and attachment type, re-reads and duplicate outputs. Codex rollouts
  carry the system prompt and tool schemas, so those are counted directly (`base_instructions`
  once, even when a developer message repeats it); a Codex response's own calls and their
  outputs are charged from the next request on, and a compaction rebuilds the context from its
  `replacement_history`. For Claude Code the fixed overhead is the intercept of a fit of
  billed input on transcript size. Shares assume one tokenizer ratio across categories, so
  they rank categories rather than give exact percentages, and the output says so. Counts
  only, offline, JSON or Markdown: tool names and attachment types appear, MCP tool names
  (which carry server names) are grouped as `mcp`. On a 938-request Claude Code session it
  runs in under a second. `--input-map` runs no compaction mode, so it refuses `--question` /
  `-q` (exit code 2). Before this was fixed, unreleased builds of `main` ignored the flag
  silently.

- `lcc measure-session --question/-q` passes a specific question or objective to every
  compaction mode, retaining the previous default when omitted (#61).

- **`lcc measure-session` reads Codex CLI rollouts** (#67, thanks @dailyun). The format is
  detected from the first `session_meta` record; messages and paired tool calls/results,
  including native web search, map into the existing report shape.
- **`lcc measure-session` says why a count is approximate.** The report gains
  `token_count_note`, and the table and `--markdown` output print it, so a shared result
  cannot pass an estimate off as exact (for example when the `o200k_base` file is not
  cached and lcc blocks the download).
- **Edge-case suite for the deterministic core.** These are property tests over a seeded,
  stdlib-only hostile corpus (`tests/edge_corpus.py`) and every local scorer. They cover
  determinism (also across `PYTHONHASHSEED` and locale), verbatim kept bytes, exact report
  accounting, an honestly stated idempotence property, and never-drop protections at any drop
  budget. Input, transcript and compaction edge cases are pinned too. Each case, its expected
  behaviour and its test are listed in `docs/EDGE_CASES.md`.
- **Judge benchmark: five input/compaction edge cases** (`extra_edge_cases`): an accent-less
  Portuguese goal, re-reads of different ranges, an error fixed later, parallel tool calls, a
  CRLF table. They are reported in their own section, so the nine original cases stay
  comparable. `--check` now also requires rules-lossless to keep their needles and v3-blocks
  to keep `pt_en_mixed`. `benchmarks/results/judge_bench.*` were not regenerated here.

- **Cache contract as code (`lcc.relevance.cache_contract`).** The prompt-cache invariants of a
  compaction pass are now defined and tested (`docs/CACHE_ALIGNMENT.md`, "Invariants and
  tests"): I1 prefix stability within an epoch, I2 deterministic placeholders, I3 no
  non-deterministic fields in emitted text, I4 append never rewrites earlier output unless an
  epoch is reported. Pure helpers: `common_prefix_chars`, `prefix_stability`,
  `cache_state_from_idle` (exact TTL is cold, negative gap is clock skew and counts as warm,
  missing timestamps are unknown), `estimate_cache_effect`.
- **`cache_effect` in the `relevance-compaction` and `transcript-compaction` reports**
  (additive field; ADR 0004, so neither `schema_version` changes): stable prefix,
  `invalidated_prefix_tokens`, `rewritten_tokens`, `removed_tokens`, the relative cost of the
  pass vs no pass under configurable read/write/input multipliers (defaults 0.10x/1.25x/1x, no
  prices), `recommended`, `epoch_opened` and `sticky_flips`. `unknown` cache state is priced as
  warm. New request fields / CLI flags (block mode): `--cache-state`, `--expected-reuses`,
  `--previous-output` (measure against what the provider actually caches),
  `--cache-read-factor`, `--cache-write-factor`; MCP `compact_transcript` takes `cache_state`,
  and the idle stash sends `cold` (`unknown` for a manual `/compact lcc:idle`).
  `break_even_reuses` now uses the configured factors (same figure at the defaults).
- **`benchmarks/cache/run_prefix_stability.py`** (`--check`, CI step): grows seeded synthetic
  sessions turn by turn with a pass in between and reports the byte-identical prefix share.
  Defaults (12 seeds): block compaction append-only on 96.2% of passes (mean stable share
  0.975), every break a reported sticky flip; the old merged-marker behaviour scores 82.6%
  with 18 unexplained breaks. Stashed transcript passes: 0 idempotence violations, 0
  placeholder rewrites.
- `test/hook-cache.test.mjs`: idle stash TTL boundaries, `idleMinRemovableTokens` boundary,
  pass cap, every fail-safe path, idempotent placeholders.

- **`lcc share-stats`: anonymous "share your numbers" summary for beta testers.** Reads local
  `lcc compact -r` reports and the opt-in request log (`LCC_REQUEST_LOG=1`) and prints Markdown
  (default) or `--json` (`lcc-share-stats-1.0`) to paste into a "Share your numbers" issue (`results.yml`):
  pass and provider/mode counts, degraded/fallback passes, passes under the 25% gate, token
  totals rounded to the nearest 100, p10/median/p90 reduction ratio, idle-stash passes. No
  text, paths, ids, hashes or times finer than a day; labels outside fixed allowlists become
  `other`. Corrupt or old files are skipped and counted, never echoed. `--since YYYY-MM-DD`
  filters the request log. Sends nothing; CLI only, not exposed over MCP.
  See `docs/SHARE_STATS.md`.

### Changed

- **`auto` stays local for plain text.** `compact` / `lcc compact` / intake relevance with
  `provider: auto` used to send context blocks to the TypeSafe API whenever a key resolved
  (environment, `~/.config/lcc/typesafe.key`, a sibling `.env`, or the macOS Keychain), with
  no explicit opt-in. It now scores with the local `mechanical` provider (report unchanged
  from the no-key case: `degraded: true`, `jev_unavailable_mechanical_fallback`, plus an
  `auto_local_only` warning). Escape hatch: name `--provider jev`, or set `LCC_AUTO_REMOTE=1`
  to restore the old `auto` behaviour. Transcripts under `auto` were already local
  (`specialist-v3`).

- **Drop markers and trim notes keep the replaced block's line ending.** Before, a marker
  merged with the next paragraph. When no blank line followed (a code fence right after a
  paragraph, or a split oversized block), it was glued onto that block's first line and broke
  the fence. Output bytes after the first mutation change: one line ending per marker or trim.
- **Mechanical matching is accent-insensitive** (`fold_accents`: NFKD, combining marks
  dropped). Accented words were split by the ASCII word pattern (`não` became `n` + `o`).
  Language detection now reads Unicode words and recognises accented Portuguese function
  words, so Portuguese evidence under an English objective is protected
  (`evidence_in_pt_not_en`). v3-blocks now keeps the judge-bench `pt_en_mixed` needle (8/9 to
  9/9 must-keep), with unchanged reduction. specialist-v3 features keep the training-time
  tokenization (`fold=False`).
- **specialist-v3 hard floors.** The rule-floor blocks (best goal match, newest error blocks)
  are never drop candidates (`specialist_floor`). With transcript segments, the latest user
  message is protected (`latest_user_message`). New `SpecialistJudge.score_and_floor`.
- **Tool-call mode refuses content it cannot rebuild** and names the field. This covers text
  under `content`, any non-empty list/object field (images, attachments, content blocks), tool
  results with `content` blocks, a non-object call `input`, and unpaired surrogates. Before,
  these parsed as empty and were silently lost from the output.
- `PROTECTION_VERSION` is `protection-1.2` and `RELATIONSHIP_VERSION` is `relationships-1.1`.
  The protection and relationship policies changed for non-ASCII text, so sticky decisions
  start a new cache epoch.

- **With `--decisions-cache`, every dropped block gets its own marker** (format unchanged:
  `[lcc-compact: dropped 1 block (N chars)]`). A merged run marker counted the whole run, so a
  run at the tail that grew on the next pass rewrote `dropped 1 block` as `dropped 2 blocks`
  inside the cached prefix. One-shot passes (no decisions cache) still merge runs;
  `RelevanceCompactionRequest.merge_dropped_runs` overrides either way. Existing sticky caches
  re-emit their markers once in the new form (one cache epoch on upgrade).
- **Sticky ratchet for restorations.** A sufficiency or verifier restoration that keeps a block
  the decisions cache holds as drop/trim is persisted (`provider: "ratchet"`), so it cannot flip
  back with the restoration budget on a later pass. When it flips a decision *reused* this pass,
  the report says so (`cache_effect.sticky_flips`, `cache_epoch_opened` warning); a ratcheted
  restoration still counts in `blocks_restored`.

- `pyproject.toml`: `Source` URL and the keywords `claude-code`, `mcp`, `agents`,
  `context-compaction`.

### Fixed

- **`measure-session --input-map` and compactions.** Claude Code: the messages a compaction
  keeps (`compactMetadata.preservedMessages` / `preservedSegment`) stay in the replayed context
  instead of vanishing at the boundary. Codex: the compaction call, billed only through
  `token_usage_record` / `latest_token_usage_record`, is now counted (once per response id; on
  one local rollout with two compactions that added 653,505 billed tokens, matching the usage
  records exactly), and an encrypted compaction summary is shown as
  `unattributed (opaque summary)`, sized from the next request's billed input, with a warning.
  The report also warns when Claude Code's fixed overhead cannot be separated, instead of
  silently spreading it over the other categories. `session_report.codex_message` is public.
- **Found by the invariant harness** (each is a corpus case): lossless no longer re-dedupes an
  earlier pass's pointers (its own or stash/recoverable ones) into pointers to pointers; a
  decision turned back into `keep` (pinned result, verification fail-safe) no longer carries
  `note`, `kept_at` or `stash`; a whitespace-only user message is kept instead of being dropped
  on rebuild, which had tripped the fail-safe and stopped the whole pass; and an output too
  short to stash stays available to lossless dedupe, so `stashed` is a fixed point. A stashed
  result that is too short now reports `not_stash_eligible` instead of
  `short_result_kept_whole`.
  Claude Code `<synthetic>` messages (local API errors, zero usage) are not requests; a split
  response without `requestId` is keyed by `message.id`; `preservedSegment` is followed as a
  `parentUuid` chain, so a rewound branch between head and tail is not counted; and tool
  results a compaction keeps stay in the re-read and duplicate indexes.
- Preserve CRLF separators when joining trimmed log lines (#71); `TRIM_POLICY_VERSION` is now `trim-1.3`, changing prompt-cache identity. Historical `trim-1.2` benchmark results are unchanged.
- **`lcc explain` left out `replace` and `dedupe` decisions.** On a `provider: rules` report
  the outputs that were stashed, re-read pointers or deduped were not listed at all, so the
  receipt missed exactly the cuts. They now get `REPLACED` / `DEDUPED` groups (only when a
  report has them; block reports render as before), a count in `Decisions`, the pointer that
  replaced each output (`now: ...`), plain-language reasons for the rules codes, and
  `--only replace|dedupe`. Tool-call rows show the message and tool instead of `lines ?-?`,
  and the meaningless `Thresholds` row is dropped for `rules`.
- `mypy` passes with and without `tiktoken` installed (no unused `type: ignore`).
- Reject non-finite or out-of-range `min_reduction` values before invoking the MCP compactor (#77); valid values are between 0 and 1 inclusive.

- Boilerplate removal deleted `----`, `Page 3 of 10`, `On … wrote:` and similar lines inside
  fenced code blocks.
- Paragraph dedup split fenced code on blank lines, deduplicated inside it, and stripped the
  leading indentation of every paragraph. NFC and NFD spellings of one paragraph are now
  exact duplicates, and the first keeps its own bytes.
- Cleaning replaced input text that happened to contain its internal NUL placeholder with a
  protected block.
- A leading BOM hid a first-line code fence from cleaning (the code was whitespace-collapsed)
  and from block segmentation (fence pairing flipped). Cleaning strips the BOM (`strip_bom`);
  compaction keeps it.
- Block line numbers ignored a lone CR, and U+2028 or a form feed counted as a line break. An
  oversized block could be cut between CR and LF. `BLOCK_ID_RE` rejected ids past block 9999,
  and restoration ties sorted `blk_10000` before `blk_9999`.
- Trimmed CRLF markdown tables and logs came back with LF line endings, so the head was no
  longer the block's own bytes.
- `semantic_cache_misses` subtracted cache hits twice and went negative on warm runs.
- Unpaired surrogates crashed `optimize` and `compact_context` deep in hashing. They now raise
  a `ValueError` that names the offset.
- Tool-call mode with lossy rules, specialist-v3 or Jev: a drop decided for one call also
  removed every call sharing its id, even in a pinned message. A call just outside the recent
  window could be dropped together with its result inside the window. Both are now kept
  (`duplicate_tool_use_id`, `pinned_recent_result`), as the lossless and recoverable modes
  already did.

- **`rules_mode: stashed` re-stashed its own placeholders.** A second pass over stashed history
  (a second idle stash) replaced `[removed: 693 tokens · lcc recall <id>]` with a pointer to the
  pointer (`[removed: 11 tokens · ...]`) whenever the new note was shorter, rewriting early
  history for ~0 tokens and making `recall` return the pointer. Existing pointers are now kept
  (`already_stashed`); a stash pass over its own output is a no-op.
- **Claude Code plugin: a headless engine whose `$.ui.log`/`$.ui.toast` throws** made the idle
  stash's own error handler throw into `session.start` / `turn.complete`. UI calls are now best
  effort.
- **Claude Code plugin: idle pass count from a corrupted store** (`passes: "abc"`) concatenated
  to a string on `+= 1` and never reached `idleMaxPassesPerSession`; a non-object store record
  was spread into the new one. Both are sanitised. A negative idle gap (clock skew) now reports
  `clock skew` instead of `cache warm` (still never fires).

### Documentation

- **`results` issue form** (`.github/ISSUE_TEMPLATE/results.yml`) for anonymous counts:
  version, provider and mode, agent, tokens before and after, `recall` calls, whether the
  agent lost something. Session text is never asked for. `config.yml` links Discussions and
  the security policy; `.github/FUNDING.yml` added.
- Draft GitHub Release notes in `docs/release-notes/1.2.0.md`, and five starter issues in
  `docs/contributing/good-first-issues.md`.

## [1.2.0] - 2026-10-20

### Added

- **`lcc measure-session <session.jsonl>`**: runs `rules:lossless`, `rules:stashed` and `auto`
  on one Claude Code session, offline, and prints counts only (messages, tool calls, tokens
  before/after, texts kept, time). `--markdown` is ready to paste into an issue, `--json` is
  `lcc-session-report/1`. It never writes to the real stash.
- **`lcc compact --mode tool-calls --rules-mode <mode>`** (with `--provider rules`): the CLI can
  now select `stashed`, `recoverable` or `lossy`; before, only MCP and Python could.
- **`lcc compact --mode tool-calls` reads a Claude Code session file (JSONL) directly.**
- **`server.json`** for the official MCP registry (`io.github.lucasmartins-ai/lcc`), and a
  `local-context-compiler` console script (same entry point as `lcc`), so
  `uvx local-context-compiler mcp` starts the server.
- `demos/stash.gif` and `demos/make_session.py` (a synthetic 91-message session), and
  [docs/EVIDENCE.md](docs/EVIDENCE.md): the aggregates of the private studies behind the
  README numbers.
- **Claude Code plugin: idle stash (opt-in, off by default).** With `idleStash: true`, a
  session resumed after `idleTtlSeconds` of idle has its spent tool outputs stashed
  (`provider: rules`, `rulesMode: stashed`) at `session.start`, before the first request
  re-writes a prompt cache that has already expired. Every failure answers `{ skip }`, and the
  classic `PreCompact` hook blocks Claude Code's own summary for an idle compaction, so it never
  becomes the built-in summary. `idleTtlSeconds` defaults to 7200, not 3600: Claude Code 2.1.296
  keeps the cache warm for 60 minutes after a turn (cache keepalive), so with a 1-hour TTL it is
  cold about two hours after the last turn. Resumed interactive sessions only: on 2.1.296
  `$.session.compact` is refused from `prompt.submit` and in `-p`/SDK sessions, and a timer's
  call skips the plugin's own hooks (all observed in a disposable session). Other knobs:
  `idleMinRemovableTokens` (10000), `idleMaxPassesPerSession` (8). The request log
  (`LCC_REQUEST_LOG=1`) gains `trigger`, `gap_bucket` and `removed_tokens` on idle passes.
  Evidence (INFERIDO) and limits: `docs/CLAUDE_CODE.md#idle-stash-opt-in`.
- **`compact_transcript`: `ref_unchanged: true`.** Returns each message the pass left unchanged
  as `{"ref": <input index>}` and leaves per-call decisions out. Claude Code caps an MCP
  result (`MAX_MCP_OUTPUT_TOKENS`) and hands a plugin's `$.mcp.call` an error text in place of
  a larger one; a 12-message session with four 10 KB reads already crossed it (49 KB answer).
  The idle stash uses it; the `/compact` path is unchanged.

### Changed

- README: leads with `/compact` vs lcc on a real session, the plugin install with
  `rulesMode=stashed`, and how to send numbers.

### Fixed

- **Claude Code plugin: `/compact` on a long session always fell back to the built-in summary.**
  The `session.compact` hook asked `compact_transcript` for the whole compacted conversation.
  Claude Code caps an MCP result (`MAX_MCP_OUTPUT_TOKENS`, 25,000 tokens by default on 2.1.296)
  and hands a plugin's `$.mcp.call` a pointer text in place of a larger one, so on any session
  worth compacting the answer was not JSON and the hook stood down. The hook now asks for
  `ref_blocks: true` (below) and rebuilds the conversation from the session's own messages; the
  idle stash uses it too. A capped answer now toasts `built-in summary (tool result is not JSON
  (N chars; over Claude Code's MCP output cap?))` instead of a JSON parse error.
- **`compact_transcript`: `ref_blocks: true`.** `ref_unchanged` down to the block: a changed
  message comes back as `{"ref": i, "toolUses": [kept indices], "toolResults": [kept index |
  {"ref", "tool_use_id", "text", "head"?, "tail"?}]}`, a replaced result being the original's
  first `head` and last `tail` UTF-16 units around `text`. Only placeholders and trim notes
  travel. On a synthetic 40-output, 1 MB transcript (`rules_mode: lossy`) the whole answer is
  1.5 MB, `ref_unchanged` 10.6 KB and `ref_blocks` 2.1 KB; `ref_unchanged` grows with every
  trimmed result it sends whole (86 KB for 21 trims on another shape, against 6.3 KB).
- **`recoverable` / `stashed` disk check vs Claude Code's Read format.** Claude Code 2.1.296
  numbers the empty line after a file's final newline (`480\t` for a 479-line file), so every
  whole-file read of a newline-terminated file failed the disk check (`keep_disk_mismatch`)
  and was never replaced or stashed. That empty trailing row is now ignored; a non-empty one
  still fails.

## [1.1.0] - 2026-10-19

### Added

- **Claude Code plugin: `rulesMode: "stashed"`.** The plugin accepted only `lossless`,
  `recoverable` and `lossy`, so the stashed mode could not be picked from Claude Code. Docs now
  recommend `stashed` with the `recall` tool, with the one measured run (INFERIDO) in
  `docs/TOOL_CALLS.md`.

- **`rules_mode: "stashed"` and `lcc recall`.** Tool-call compaction can now remove what
  `lossy` drops or trims and what `recoverable` replaces without losing it: the exact bytes go
  to a local content-addressed stash (`~/.cache/lcc/stash`, `0700`/`0600`, `LCC_STASH_DIR`)
  and the result becomes `[removed: N tokens · lcc recall <sha12>]`. `lcc recall` and the MCP
  tool `recall` re-hash on read. stdio only; `lcc mcp --http` refuses it. `lossless` stays
  the default. Measured offline on 847 real-session dossiers (owner-attested, private
  receipts): 30.1% pooled token reduction, 0 verification violations. Agent-in-the-loop eval on
  172 items (INFERIDO): non-inferior to full context on artifact recall with 36.6% fewer tokens,
  and the model recalled the right blob on 90% of probes about stashed content.
- **`provider="specialist-v3"`: a local block ranker for agent transcripts.** A frozen
  LR + boosted-tree model (183 KB, plain Python, no new dependency) ranks blocks and drops the
  lowest-ranked until `specialist_drop_fraction` (default 0.3) of candidate characters is gone.
  LCC's protection rules run first, and deterministic-protection and high-risk blocks are never
  dropped. Block metadata (message index, role, kind, tool) comes from trusted
  `segments` (`render_transcript`), never from text. `auto` uses it whenever segments are
  given (see Changed); plain text keeps the Jev/mechanical path.
  The model's sha256 is checked at load, and a mismatch falls back to mechanical. Held-out results and
  limits: [docs/SPECIALIST.md](docs/SPECIALIST.md).

### Changed

- **Behaviour change: `auto` is now specialist-v3 whenever structured transcript blocks are
  present**, ahead of Jev and Laya. That covers block compaction with `segments` and every
  tool-call path (Claude Code hook, MCP `compact_transcript`, `lcc compact --mode
  tool-calls`), which always have them. Jev runs only when named (`provider: jev`, the
  plugin's `provider` setting, `--provider jev`); a key alone no longer selects it. Plain-text
  `auto` is unchanged (Jev, else mechanical). The plugin and MCP `compact_transcript` default
  changes from `jev` to `auto`. To restore the old behaviour set `provider` to `jev`.
  Evidence (INFERIDO): held-out, v3 ties Opus on recall and beats Gemini Flash on all-kept;
  dev (43 sessions, optimistic) v3 0.886 vs Jev 0.818 recall AUC; Jev was not run on the
  held-out set. See [docs/SPECIALIST.md](docs/SPECIALIST.md).
- **Tool-call mode with specialist-v3:** the transcript is rendered with trusted segments,
  block compaction runs unchanged, and a call is dropped only when every block of its call
  and result was dropped (trimmed when only the result was). Text is never touched. Any
  ranker error keeps every call (`specialist_v3_failed_fail_safe`). `rules`
  (`lossless` default) is unchanged.
- The request log records `provider` and `degradation_reason` (labels only) for tool-call
  compaction, and `lcc request-log` counts entries by provider.

### Deprecated

- **Laya (`provider: laya`).** No automatic or fallback path selects it (none did for block
  mode; it is now stated). It still runs when named. Removal is planned for a later release.

### Security

- **The TypeSafe bearer key could leave over plain HTTP or follow a redirect.**
  `TYPESAFE_ENDPOINT` must now be `https://` (plain `http://` is accepted only for
  loopback). If it is not, Jev is reported as unavailable, with a note on stderr.
  Redirects are refused, because urllib re-sends `Authorization` to whatever host a
  `301`/`302`/`303` names.
- **The request log was world-readable under the default umask.** The log directory is
  now created `0700`, and `requests.jsonl` (including the rewrite done on deletion) is
  `0600`. The goals are redacted, but they are still users' text.

- **`lcc mcp --http` let anonymous callers choose paid or heavy providers.** Any client
  that reached the server could send `provider: "jev"` and spend the operator's TypeSafe
  key, or `provider: "laya"` and load model weights on the host. Without the new
  `LCC_HTTP_TOKEN` env var, HTTP callers are now limited to `mechanical`. With it set,
  `POST /mcp` requires `Authorization: Bearer <token>` and any provider is allowed. Each
  request also gets a 30 s socket timeout, so a stalled body no longer holds a thread.
- **The npm package would have published the whole checkout.** `package.json` had no
  `files` field, so `npm pack` took 1054 files (45.8 MB), including
  `.claude/settings.local.json` and session worktrees. It now ships `index.js`,
  `index.d.ts`, `README.md`, `LICENSE` and `NOTICE`.

### Fixed

- **Anonymous HTTP callers could not use `compact_transcript` at all.** The provider gate
  allowed only `mechanical`, and `compact_transcript` refuses that. The offline `rules`
  provider is now allowed too.
- **`lcc route` from a pip install ran with risk detection off.** `configs/` is not in
  the wheel, and with no YAML in the working directory every risk keyword list was
  empty. The built-in defaults now match `configs/router_policy.yaml`.
- **A failed neighbourhood fingerprint was silent.** The decision cache then fell back to
  content-only keys without saying so. It now adds a `neighbourhood_fingerprint_failed`
  warning to the report.

### Changed

- `benchmarks/research/results/matrix.jsonl` (16.9 MB) is now committed as
  `matrix.jsonl.gz` (227 KB). The file decompresses to the same bytes, `run_matrix.py`
  writes it with `mtime=0` so identical rows produce identical bytes, and
  `show_losses.py` reads it. The old file stays in git history.
- Package metadata names the author: Lucas Martins <lucas@lookadev.com>.
- New `Dependency audit` workflow: `pip-audit` runs weekly and on demand. It is not run on
  PRs, so an advisory published against a dependency does not block unrelated merges.

- Removed `act2_router/`, which held 17 star re-exports of `lcc.router` and `lcc.agents`
  and was never in the wheel. The 7 tests that still used it now import the real modules.
- The supersession cue list is defined once in `graph.SUPERSESSION_CUES`, and the graph
  adds its two extra cues explicitly. Matching is unchanged.
- `fast-jev-compaction` is a dev dependency, because only the benchmark arm uses it. CI
  now tests Python 3.11–3.14 (the classifiers already claimed 3.13 and 3.14), runs
  `ruff check .` on the whole repo, and builds both dists and runs `twine check --strict`
  on every PR.

- **Text containing `<|endoftext|>` was never counted exactly.** tiktoken rejects
  special-token strings by default, and the counter silently fell back to the heuristic.
  Pasted chat logs then ran `--require-exact-tokens` and cache economics on estimates.
  These strings are now counted as plain text.
- **A malformed `200` from TypeSafe aborted compaction instead of falling back.** A
  non-JSON body raised `JSONDecodeError`, and a non-object answer raised `AttributeError`.
  Both escaped the `JevError` fail-safe. They now raise `JevMalformedResponseError`, are
  written to the ledger, and degrade to mechanical scoring.
- **One malformed line ended the `lcc mcp` stdio session.** A parse error now gets a
  `-32700` reply and the server keeps reading. A JSON array gets `-32600`. Non-object
  `params` or `arguments` get `-32602` on both transports, instead of an internal error
  (stdio) or a dropped connection (HTTP).

- **`lcc mcp` never completed the MCP handshake with real clients.** The stdio server only
  read LSP-style `Content-Length` frames, while the MCP stdio transport (Claude Code, Codex,
  Cursor) sends one JSON message per line, so `initialize` hung until the client timed out.
  In Claude Code this left the plugin's `lcc` server disconnected and every `/compact` fell
  back to the built-in summary (`no connected MCP tool "compact_transcript"`). The server now
  reads newline-delimited JSON and still accepts `Content-Length` frames, replying in the
  framing of each request.

## [1.0.0] - 2026-10-07

First stable release. The library API, the CLI surface, and the MCP tool set are now
covered by the compatibility promise.

This release also publishes everything merged since 0.5.0: the MSI research release
(sprints 1–10), tool-call compaction judged locally by Laya, the hosted MCP endpoint and the
ChatGPT plugin.

### Sprint 10 — Research release and audit resolution

- **Audit findings R1–R3 resolved:**
  - **R1 (All-attempt cost accounting):** `benchmarks/msi-bench/bench.py::run_arm`
    now instruments context tokens and model classes for every executed attempt and
    retry (decision-01 under verify arm records 3 attempts and 3 frontier calls at
    $3.2160, updating verify arm total cost to $4.3600);
  - **R2 (Paired bootstrap):** `bench.py::bootstrap_ci` draws task indices once per
    resample across all arms, establishing true paired resampling;
  - **R3 (Full-payload drift check):** `benchmarks/msi-bench/run.py` strengthens `--check`
    with `check_payload`, verifying full stable payload equality and rejecting any
    aggregate or receipt drift.
- **Architecture paper and prior art review:** published `research/paper.md` ("Minimum
  Sufficient Inference: Closed-Loop Context Compaction with Bounded Verification")
  and `research/prior-art.md` with taxonomic positioning against LLMLingua, FrugalGPT,
  RouteLLM, and Reflexion, plus a complete zero-superlative claims audit.
- **Limitations and research agenda:** published `research/limitations.md` documenting
  all structural constraints, oracle vs. mechanical compiler distinctions, and five
  falsifiable research questions.
- **Frozen version manifest and master results:** published `research/versions.json`
  pinning all schemas (`context-ir/0.1`, `planner-contract/0.1`, `inference-plan/0.1`,
  `inference-receipt/0.1`, `verify-1.0`, `planner-1.0`) and `research/results-master.md`
  cataloging all empirical results with per-row provenance.
- **ADR 0022:** accepted `docs/adr/0022-research-release-freeze.md`.

### Audit corrections (Sprint 9 / PR #34)

- Fully protected mechanical passes now report `semantic_guarantee: none`;
  regression coverage proves that zero scoring calls cannot imply judgment.
- CI now blocks lint/type failures, runs configured-package mypy and includes
  Node hook tests. A transcript loop-variable type conflict is corrected.
- Packaged license files include the existing NOTICE attribution.
- README and quickstart describe current MSI behavior, pending sprint 10,
  reproducible offline usability measurements and explicit benchmark limits.
- Sprint-7 historical reports now carry an audit notice for final-attempt
  costs, unpaired bootstrap sampling and incomplete reproducibility checks.

### Added

- **Laya judges tool-call compaction.** `--mode tool-calls --provider laya` retires spent
  tool calls locally and offline, so this mode no longer requires `TYPESAFE_API_KEY`.
  Measured on 9 real tool calls with `laya-typed-decisions`: 56.2% reduction,
  `semantic_guarantee: judged`, no warnings, 2.7s over 9 calls. It dropped the
  reconnaissance and kept `edit_file` (0.75) and `pytest` (0.56). See
  [docs/LAYA.md](docs/LAYA.md) § 2.
- Versioned Context IR emission (`context-ir/0.1`, ADR 0017): `lcc compact --emit-ir ir.json`
  writes a provider-independent envelope (verbatim units + provenance, typed relationships,
  selection + rationale, sufficiency, restoration); `lcc explain` reads IR files and
  `lcc inspect --ir` summarizes them. Opt-in: default outputs are byte-identical.
  Mapping, guarantees and limits: `docs/lcc/context-ir.md`.
- Sufficiency/restoration hardening, MSI sprint 3 (ADR 0018): per-layer restoration budgets,
  both CLI-explicit (`--max-restorations` 8 structural, `--verifier-max-restorations` 4
  verifier-side, independent); every restore carries motive + origin layer in the report
  (`decisions[].reason`/`relationships`) and the IR (`selection.rationale`,
  `restoration.restored`); any layer crashing fails closed (typed warning + REVIEW,
  never a silent drop). Measured: structural cuts false-drop rate 0.660 → 0.151 under
  judge error (30 curated adversarial cases). Docs: `docs/lcc/sufficiency.md` (ablation +
  adversarial matrix), `docs/lcc/restoration.md` (audit trail).
- Causal necessity harness, MSI sprint 6 (ADR 0021, research-only):
  `src/lcc/router/ablate.py` (`run_pilot`, harness `ablate-1.0`) removes each unit
  (and passing pairs) from a frozen offline baseline, replays sprint-5 verification,
  and labels by observed delta (NECESSARY / CONDITIONALLY_NECESSARY / REDUNDANT /
  UNNECESSARY / PROTECTED / UNKNOWN, unstable labels fail closed to UNKNOWN). Pilot
  N=8 (`benchmarks/ablation/pilot.py`, digest-pinned results): single-removal splits
  2 NECESSARY from 5 passing units; pair ablation + token-coverage split the rest
  (2 conditional, 2 redundant, 1 noise). 35 experiments, <1 ms wall, 0 model calls.
  Labels are not consumed by any production path. Docs: `research/causal-necessity.md`.
- MSI-Bench pilot, MSI sprint 7 (PILOT N=12, offline, deterministic, no live models):
  `benchmarks/msi-bench/` runs 6 arms (full-context, LCC-only, routing-only,
  LCC+routing, +verification, MSI closed loop) over 12 frozen CURATED tasks in 6
  categories, all scored under the paired `verify-1.0`/`standard` rubric with an
  `inference-receipt/0.1` receipt per run (72 runs, digest-pinned results, 1-command
  repro via `run.py --check`). PILOT outcome: MSI closed loop is the only 12/12 arm
  at 0.11x modeled cost and 0.52x context of full-context; routing alone matches
  full-context quality (11/12, identical cells) at 0.14x modeled cost; lexical-only
  filtering loses 5/12 with named failure modes, and full-context itself FAILs the
  injection task. Pareto frontier: lcc, lcc+routing+verification, msi. Costs are
  modeled (illustrative prices), latency is deterministic overhead only, bootstrap
  95% CIs overlap nearly everywhere -- distributions only, no generalization claim.
  Docs: `benchmarks/msi-bench/REPORT.md`, `research/benchmark-methodology.md`.
- MSI DX, sprint 8: one-call offline Python API `lcc.msi.compile(task, context)`
  (deterministic planner + mechanical compaction + bounded sufficiency; returns
  context + spec-valid receipt + sufficiency; demo `examples/msi_quickstart.py`,
  reference `docs/lcc/msi-api.md`); new offline `lcc diff LEFT RIGHT` (sizes,
  token deltas, unified diff; workflow: compact then diff before sending to a
  model); actionable CLI errors (every common failure names the next step);
  QUICKSTART extended with the MSI path, a `diff` section, and an offline x
  command matrix (single quickstart location, no second file).
- MSI sprint 9 integration: replay 10 anonymous local pytest-result windows
  through `msi-api-1.0` (20 paired runs), with summary preservation 10/10 in
  both arms and 174 -> 122 estimated tokens; no model calls or API spend.
  Keep 10 authored regression probes separately labeled CURATED (60 runs,
  25 failures investigated; four permanent fixtures). Replay checks cover
  receipt audit fields and aggregate drift; modeled probe cost counts every
  executed attempt. See `research/real-world-integration.md` for sources,
  commands, quality/cost tables and limits.

### Changed

- README leads with measured results, the demo GIFs and a three-line quick start; the
  research and audit material follows it. Demo GIFs regenerated against this release
  (`demos/make_gifs.py` now finds a monospace font on Linux). Package metadata moves to
  `Development Status :: 4 - Beta` and links the docs site and changelog.
- Development installs now include JSON Schema validation, and contract tests
  use pinned in-repo schema fixtures rather than machine-specific clone paths.
  CLI error tests use pytest filesystem fixtures for current Typer versions.
  Network-guard fallback errors name the requested attribute consistently.

- The transcript mode accepts `laya` alongside `jev`, in the CLI, the MCP tool, and the
  library API. The default stays `jev`; `--provider laya` is opt-in.

### Fixed

- An unavailable Laya now degrades with one typed `laya_unavailable` warning naming the
  cause, instead of one `laya_batch_N_failed` warning per batch that read like a flaky
  judge.
- The transcript summary no longer labels local Laya calls as "Jev calls".
- `laya_confidence_missing` warnings are gone. Confidence never gates a decision and Laya
  returns none, so the warning added noise without changing a keep or a drop.

### Hosted MCP and ChatGPT plugin

#### Added

- **ChatGPT plugin.** `lcc` is served over streamable HTTP at
  `https://lcc.lookadev.com/mcp` and submitted to the ChatGPT plugin directory as
  *Context Compiler*. Six read-only tools, each declaring `readOnlyHint`,
  `destructiveHint`, and `openWorldHint`, plus the `trim-long-context` skill.
  See [docs/CHATGPT_PLUGIN.md](docs/CHATGPT_PLUGIN.md).
- **Domain-verification endpoint.** `GET /.well-known/openai-apps-challenge` returns the
  configured token as plain text, byte for byte. Unset means 404 rather than a
  placeholder.
- **Published privacy policy** at
  <https://lucasmartins-ai.github.io/lcc/PRIVACY_POLICY>.

#### Changed

- README restructured: rationale, install, and a first-command example now precede the
  reference material.
- `lcc mcp --http` serves the same tools over streamable HTTP, bound to `$HOST`/`$PORT`.
  An unexpanded `$PORT` is resolved from the environment instead of failing validation.

#### Fixed

- `robots.txt` and `favicon.ico` answer 200/204. Plugin scanners probe both before
  `/mcp`, and a 404 read as a broken host stalled tool discovery.
- HTTP transport negotiates protocol revision `2025-06-18`; the stdio server keeps
  `2024-11-05`.

#### Security

- The hosted deployment sets no `TYPESAFE_API_KEY`, so `compact` runs the offline
  `mechanical` provider and submitted text never leaves the process.

### Laya specialisation

#### Added

- Laya specialisation harness, and the measurement it produced. `benchmarks/research/laya_finetune_items.py`
  turns the corpus factory into supervised items — de-labelled first, because the corpora's literal
  `GROUND TRUTH`/`(not evidence, ignore)` markers would be learned as label vocabulary, and with six
  objectives per corpus so the same evidence block is a keep for the objective it answers and a drop
  for the four it does not. `laya_finetune_train.py` runs the vendor's RLCD recipe on one device with
  the encoder frozen and fits the calibration temperature on a held-out slice (4 epochs, MPS, ~35 min,
  held-out separation 0.895 at 4 epochs). `laya_real_context_test.py` measures a real Hermes or Claude
  Code transcript against a real objective, scoring survival of the user turns byte-for-byte.
  `run_laya_comparison.py` and `run_judge_ablation.py` gained `--laya-model`, `--batch-size` and `--out`.
  Results, including the two failures that matter, are in `docs/LAYA.md` §8 and the canonical rows in
  `benchmarks/research/RESEARCH_STATUS.md`.
- `lcc.relevance.compactor.keep_question`: the typed keep question now lives in one place, shared by the
  Jev and Laya paths and by the fine-tuning harness, so training text cannot drift from inference text.

#### Changed

- `lcc compact --provider laya` documents `--batch-size 1` as the configuration that works. Measured
  2026-09-23 on the same blocks: with several blocks in one state both the shipped and a specialised
  checkpoint answer "keep" to everything (0.88–0.94 regardless of relevance); with one block per state
  they separate (specialised noise 0.003–0.016, shipped checkpoint drops the evidence instead). The flag
  already existed; the measurement that turns it into a requirement did not.

## [0.5.0] - 2026-09-21

**Release focus: Jev first, and enough of it shipped to prove it.** The Jev provider is now the
headline path in the documentation (`docs/JEV.md`), the compiler learned a message-level mode
(`lcc compact --mode tool-calls`) that drops spent tool calls and results from an agent
transcript without ever summarizing, and a Claude Code plugin replaces that editor's built-in
compaction summary with the same pass. A head-to-head study against `fast-jev-compaction` 0.4.0
on the same transcripts with live Jev is published in `benchmarks/research/TRANSCRIPT_AB.md`:
this mode removed 13.3 / 39.2 / 55.7% of the transcript at fact recall 1.00 / 1.00 / 1.00, where
that library removed 70.5 / 78.9 / 83.4% at recall 0.00. Two defects the study found in the new
mode are fixed below.

### Added

- Tool-call compaction study: `benchmarks/research/TRANSCRIPT_AB.md` measures `lcc compact --mode tool-calls` against `fast-jev-compaction` 0.4.0 on the same three deterministic transcripts with matching options and live Jev. Our mode removed 13.3 / 39.2 / 55.7% of the transcript at fact recall 1.00 / 1.00 / 1.00; the npm arm removed 70.5 / 78.9 / 83.4% at recall 0.00 (every evidence pair dropped, reproducibly). New harness: `make_transcripts.py` (ground-truth corpus with a self-check), `run_transcript_ab.py` (both arms measured by the same ruler, per-pair outcomes derived from the emitted messages, arm selection in the artifact filename), `fast_jev_arm.mjs`; artifacts under `benchmarks/research/results/`. Canonical row in `benchmarks/research/RESEARCH_STATUS.md`.

### Fixed

- Tool-call compaction, state budget honesty: the mode scored the conversation with the stdlib heuristic, which undercounts JSON-heavy transcripts by roughly a third. On a then-497-message snapshot of a real session it judged a 22 936-token state inside its 25 000 budget, sent 38 batches, and had every one refused by the API (`400 max_tokens_exceeded`, 123 741 characters ≈ 31 000 real tokens) before degrading to keep-everything. `_budget_tokens` now counts with the real tokenizer when the environment has one and otherwise inflates the heuristic by the measured factor, so a session that cannot fit fails closed in ~50 ms with a typed error and zero requests spent. Regression tests: `test_the_budget_is_never_optimistic`, `test_fitting_uses_the_budget_function`.
- Tool-call compaction: a `drop` decision reported `chars_after` equal to `chars_before`, so the report's `tool_reduction_ratio` read 0.0 while the transcript had shrunk by more than half. A result shorter than `--trim-head-chars` was also "trimmed" into a *longer* transcript, because the audit note outweighed the characters it removed; such a pair is now kept whole with reason `short_result_kept_whole`. Both were found by the new A/B study and both have regression tests.
- Tool-call compaction, real sessions: `benchmarks/research/REAL_SESSIONS.md` adds the measurement the release was missing. A real Claude Code session in this repository (192 messages, 75 tool calls), in the exact shape the hook receives, goes from 55 411 to 18 761 tokens (**−66.1%**) with all 42 user/assistant texts preserved byte for byte; this release's own 337-message Hermes session (187 tool calls) goes from 199 717 to 36 645 tokens (**−81.7%**) with all 58 texts preserved. New harness: `measure_session.py` (Claude Code JSONL or the Hermes store → the session shape → the shipping code path).

- Claude Code plugin (`plugins/claude-code`, `.claude-plugin/marketplace.json`): replaces the built-in compaction summary with verbatim tool-call compaction. The `session.compact` hook is a thin ESM adapter (no build step, no dependencies) that hands the transcript to the plugin's own `lcc mcp` server and maps the result back; it stands down to Claude Code's own summary on any failure, on a below-`minReductionRatio` pass, or when a message carries content it cannot rebuild. Install and limits: `docs/CLAUDE_CODE.md`; operator guide: `plugins/claude-code/hooks/README.md`. Verified by `claude plugin validate` plus `test/hook-map.test.mjs` (10 cases, run by `npm test`); a live head-to-head against the built-in summary is still pending.
- Tool-call compaction: `lcc compact --mode tool-calls` (and the MCP tool `compact_transcript`) compacts a session transcript instead of a document. Each `tool_use` is paired with its `tool_result` by id; the first and newest `--preserve-recent` messages are pinned; every other pair gets two typed Jev questions (does the call still matter, does its result still need to be there verbatim) and is kept, trimmed to `--trim-head-chars` plus a note, or dropped whole. User and assistant text is never scored, trimmed or rewritten, results stay in the message they arrived in, and a history that cannot be shown inside `--max-state-tokens` fails closed instead of being judged blind. `mechanical`/`laya` are refused with exit 2 rather than pretending to judge semantics. The report is `transcript-compaction-1.0` and reads through `lcc explain` unchanged. New: `src/lcc/relevance/transcript.py`, `docs/TOOL_CALLS.md`.
- Jev path documentation: new `docs/JEV.md` (typed-decision contract, key resolution order, honest fallback table, measured behaviour and its limits), a Jev-first section at the top of `README.md` with a five-line `--provider jev` example and a TypeSafe badge, a Jev path in `docs/QUICKSTART.md`, and `tests/test_docs.py` assertions that keep the document linked from both entry points and pinned to the tested phrases.

### Changed

- README positioning: the compaction claim now leads with "Jev-powered relevance compaction that never summarizes", and the provider table's note points to `docs/JEV.md`. No behaviour change; the offline default path (`mechanical`/`laya`, no key, no network) is unchanged.

## [0.4.0] - 2026-09-21

### Added

- Laya live validation (2026-09-21): the real backend runs end-to-end (verified offline, in-budget, `judged`, no fallback) and the pre-validation "Laya = Jev, −22.6% on XL" claims are corrected — measured with real weights the default checkpoint keeps essentially every block (0.0% reduction at small/medium/large, −0.5% at XL; Jev −52% / mechanical −70% at XL, all at 100% category recall). `run_comparative_stress_test.py` and `run_laya_comparison.py` run real backends by default (`--mock` opts into the labelled harness) and every result row now carries `harness: real|mock`. New `run_laya_context_cases.py` (budget cases A/B/C, offline) and gated live test `tests/test_laya_integration.py` (`LCC_LAYA_INTEGRATION=1`). Pre-validation mock archives preserved and labelled. Full rows: `benchmarks/research/RESEARCH_STATUS.md`.
- Laya opt-in local semantic backend for `lcc compact` (ADR 0016, `local-context-compiler[laya]` extra): `LayaClient` judges typed `noul`/`choice`/`score` questions on-device with zero network and zero remote tokens. Strict context budgeting (`laya` 512 / `laya-multilingual` / `laya-typed-decisions` 1024, `HEAD_RESERVATION_TOKENS = 192` → 319/831 state tokens, `--laya-context-limit` override); oversized blocks are kept whole with `laya_context_limit_exceeded`, never sliced. Temperature calibration (`calibrate_noul`, `--laya-temperature`, default 1.0) is pure stdlib and part of the decision-cache identity. New CLI flags `--laya-model`, `--laya-device`, `--laya-context-limit`, `--laya-temperature`; Python API `LayaClient` + `provider="laya"`. Missing extra or failed batch falls back honestly to mechanical (`laya+mechanical_fallback`, `degraded: true`, typed reason) — never a fake `judged`. Operator guide: `docs/LAYA.md`.
- Laya maturity: report schema `relevance-compaction-1.2` (additive; new `context_budget_used`, `laya_temperature` alongside `laya_model_requested`/`resolved`, `laya_context_limit`, `latency_ms`), `lcc compact --help` provider decision guidance (mechanical vs laya vs jev vs auto), and fallback/observability tests including the missing-dependency path.
- Discoverability: `docs/QUICKSTART.md` (5-minute offline tour), runnable `examples/compact_providers.py` (mechanical vs laya vs honest jev-skip on one dossier) and `examples/long_session_cache.py` (decisions-cache + prefix-marker + append-only session), both covered by `tests/test_examples.py`.
- Deterministic boundary hardening: `tests/test_deterministic_boundary.py` fails any network/LLM/embedding capability import in `cleaning`, `token_budget`, `inspection`, `pipeline`, `lexical_selection`, `benchmarking` (sole exceptions: the fail-closed download guard and `*_VERSION` identity constants), fails any opt-in layer import into core, and proves core outputs are byte-identical with the network disabled. ADR 0010 clarified (decision unchanged): Laya, sufficiency, verifier, agents, and router are opt-in outside the core.
- MCP server MVP (`lcc mcp`, `src/lcc/mcp_server.py`, `docs/MCP.md`): stdio JSON-RPC tools `compact` (defaults to offline `mechanical`), `inspect`, `prepare`, `explain`, `intake`. Stdlib only — zero new dependencies; covered by `tests/test_mcp_server.py` including a real framed-subprocess session.
- Minimum-sufficient-context compilation (ADR 0014): `lcc compact` now answers two questions — "is this block relevant?" and "after these drops, can the objective still be solved from what remains?". New modules `lcc.relevance.safety` (independent relevance/necessity/dependency-risk/semantic-risk/redundancy axes), `lcc.relevance.graph` (typed SUPPORTS/QUALIFIES/CONTRADICTS/SUPERSEDES/DEPENDS_ON/DUPLICATES/DERIVED_FROM edges), `lcc.relevance.sufficiency` (verify-then-restore with `--sufficiency/--no-sufficiency`, `--max-restorations`), `lcc.relevance.trim` (type-aware TRIM: valid-syntax JSON/YAML/XML, row-aware tables, line-bound code, head+tail logs, TRIM→KEEP for high-stakes content), and `lcc.benchmarking.metadata` (reproducible benchmark identity). Decision cache keys bind the full policy identity (v1.1); reports add tokenizer identity, `jev_model_resolved`, sufficiency/relationship/marker accounting, per-decision confidence/relationships/policy/content-type, and `compilation_ms`. New CLI flags `--sufficiency/--no-sufficiency`, `--max-restorations`, `--confidence-threshold`. Adversarial suite grows 20→26 cases (scope quantifiers, coreference, paraphrase duplicates, set-level VAT chain, HTML/log injection); new `benchmarks/research/run_answer_eval.py` gates answer-level regressions (26/26 pass, 0 regressions mechanical). Node engine gains `tokenizerIdentity()`/`estimateTokensWithMeta()` with a documented parity boundary.
- Relevance compaction v1.1 (2026-09-18 review of `tamaratran/fast-jev-compaction`, adapted to this boundary): three-way decisions — **keep / trim / drop** — where borderline blocks keep a bounded head plus an audit note (`--trim-threshold`, `--trim-head-chars 0` restores strict keep/drop); `--preserve-tail N` pins the newest blocks untouched for live append-only contexts; scoring batches run concurrently (`--max-workers`, up to 8); reduction accounting (`reduction_ratio`, `worth_it`, `--min-reduction`) flags passes that save too little to justify a cache epoch. Report schema is `relevance-compaction-1.1` (additive; `decisions[].chars_after` for trims). A failed scoring batch no longer aborts the remaining ones — missing blocks fall back mechanically, as before.
- `lcc compact` (ADR 0013): opt-in instant relevance compaction. Drops context blocks that are irrelevant to an objective using narrow model judgment (TypeSafe System One / Jev) in batched calls, with a fully local mechanical fallback (zero-lexical-overlap blocks only) when no API key is configured. Fail-safe: provider failures keep content, never drop it.
- Cache-aligned compaction: sticky decisions (`--decisions-cache`) pin `(objective, block)` outcomes so unchanged history keeps byte-identical output; `--protect-prefix` / `--prefix-marker` make early-prefix mutation impossible; reports expose `first_mutation_offset`, `prefix_sha256`, and `output_sha256` for automated cache accounting (`docs/CACHE_ALIGNMENT.md`).
- `lcc intake --enable-relevance` (with `--relevance-threshold`, `--relevance-provider`): runs relevance compaction on raw input before intake compilation; results appear in the intake report JSON and summary.
- Deterministic relevance block segmentation (`lcc.relevance.blocks`) with content-addressed ids (`blk_0001_<12 hex>`), fenced-code-aware spans, and byte-exact reconstruction; shared-ledger audit trail for every scoring call (`lcc_compact` feature tag, matching the LookADev fleet ledger schema).
- `lcc agent` local agent subsystem (`lcc.agents`) with native support for **Gemma 4 e4b** (turn formatting `<start_of_turn>user...`) and **Qwen3.5-4B** (ChatML `<|im_start|>...`), Ollama, llama.cpp / GGUF (e4b 4-bit), vLLM, MLX, and mock backends with health checks and zero remote token usage.
- `lcc route` hybrid local/cloud routing subsystem (`lcc.router`) with conservative verification gates (`RuleBasedVerifier`, `LocalLLMVerifier`) and selective escalation to Fireworks AI.
- `lcc intake` intelligent prompt intake engine (`lcc.intake`) with automated readiness triage (`READY_TO_EXECUTE`, `NEEDS_LIGHT_REFINEMENT`, `NEEDS_INTAKE`, `BLOCKED`), intent/assumptions extraction, and clarifying questions generation.
- `lcc speech` and transcript cleaning (`lcc.cleaning.speech`) with deterministic speech disfluency stripping (English & Portuguese fillers), Whisper audio tag elimination (`[Music]`, `[Applause]`, etc.), hallucinated subtitle/video outro removal, and speaker-turn collapsing.
- Code-block and Markdown-table safe normalization in `lcc.cleaning.normalize` protecting fenced code blocks (``` and ~~~) and Markdown tables against destructive inner-space collapsing and indentation disruption.
- Fixed `REMOTE_DIRECT` router token leak in `lcc.router` so direct cloud model escalation always receives safe deterministic cleaning (normalization, boilerplate removal, and exact paragraph deduplication).
- Universal TypeScript & Node.js client package exports (`LccCompressor`, `LccIntake`, `processIntake`).
- `lcc prepare` deterministic inspect-first workflow. It runs inspection, skips prompt

  generation for `skip`/`manual_review` recommendations, and runs deterministic lexical
  selection plus the existing safe optimization path for `optimize_safe`/`optimize_with_flags`,
  with input-file overwrite protection for output and report paths.
- Machine-readable inspection recommendation scoring signals with deterministic scores,
  thresholds, evidence values, and reason codes for duplication pressure, projected savings,
  token budget pressure, missing pricing, approximate token counting, and manual-review risk.
- Additive `chunk_inventory` data in inspection reports, with deterministic chunk IDs,
  character offsets, line spans, paragraph counts, token counts and methods, structural
  labels, literal heading text, and exact duplicate markers.
- Deterministic question-aware lexical chunk selection for `lcc prepare` optimize decisions,
  using keyword overlap, heading matches, rare-term matches, heading proximity, and exact
  duplicate markers from `chunk_inventory`; prepare reports explain selected chunks and nested
  optimization output.
- Deterministic benchmark coverage for `workflow: prepare` cases, including bundled
  selection-applied and selection-not-applied fixtures with required evidence markers,
  forbidden irrelevant/duplicate markers, and prepare selection report assertions.
- Phase 1.7 roadmap status for the implemented deterministic `prepare` and recommendation
  scoring slices, chunk-inventory slice, lexical-selection slice, and prepare benchmark slice.
- ADR 0010 documenting the deterministic-first preparation and optional model-assistance
  boundary. Optional future model assistance is not implemented; model, embedding, network
  client, runtime-download, and local/remote model-call code cannot enter the deterministic
  core, inspection, or benchmarking boundary.
- ADR 0011 as the accepted Phase 2 opt-in semantic retrieval boundary, plus a
  disabled-by-default `lcc.semantic_retrieval` / `lcc semantic-retrieval` scaffold that reports
  disabled or blocked status only. Retrieval execution, embeddings, RAG, model calls, network
  access, and local-model behavior are still not implemented.
- Visitor-facing project presentation (added during this cycle, since removed as hackathon-specific; pitch content folded into README).

### Changed

- **Behavior change:** `--provider laya` without the `[laya]` extra (or with an unloadable model) now falls back honestly to mechanical scoring (`provider_used: laya+mechanical_fallback`, `degraded: true`, `degradation_reason: laya_unavailable_mechanical_fallback`) instead of keeping every block silently. Rationale: a keep-all pass disguised the missing dependency and hid that no semantic judgment ran; the fallback is labeled, warned, and `semantic_guarantee: none`.
- `semantic_guarantee` is now exact about mixed runs: `partial` only when at least one block was actually judged before the failure; a total provider failure (every decision lexical) reports `none`. Same rule for Jev and Laya fallbacks.
- Report schema `relevance-compaction-1.1` → `relevance-compaction-1.2` (additive only: `context_budget_used`, `laya_temperature`; all 1.1 consumers keep working, e.g. `lcc explain` reads both).
- Reworked the README into a clearer first-visit guide with a tighter project summary, the offline-first path, direct links to the five-minute QUICKSTART and MCP Server guide, a command guide, an architecture map, and explicit scope boundaries.
- Tightened CLI-facing and visitor-facing docs around the deterministic Phase 1.7 prepare
  boundary, diagnostic-only inspection, and mechanical-only benchmark claims.
- The inline drop marker no longer carries scorer values, so repeated `lcc compact` runs emit
  byte-identical output without extra flags; `--marker-scores` restores the previous verbose
  form. Per-block scores remain in the report. Measured over five identical runs, this took the
  output from five distinct hashes to one.
- `--provider auto` reports a mechanical fallback honestly: `degraded` is now true with a
  `degradation_reason` and `semantic_guarantee: none`, instead of claiming success while a
  lexical scorer replaced the semantic judge.
- `lcc compact` exits 3 under `--require-exact-tokens` when token counting degrades to the
  heuristic estimator, and always warns (`approximate_token_count`) that every token figure in
  the report is an estimate.
- Passing `--trim-head-chars 0` now warns (`strict_keep_drop`) that the trim middle gear is
  disabled and borderline blocks are dropped outright instead of keeping a bounded head.
- `lcc compact --help` and the README document `--provider jev` as the recommended explicit
  choice, and describe the trim band as the safety net rather than an optional extra.
- `docs/CACHE_ALIGNMENT.md` corrects the byte-stability claim (scorer values in the marker and
  uncached threshold drift were two distinct causes) and documents the new report fields.

### Added

- `lcc compact --append-to <session>`: compacts the payload and appends it in one step, never
  rewriting the bytes already in the file. This makes the placement the measurements favour — a
  per-payload pass instead of a whole-session rewrite — a first-class operation rather than shell
  plumbing, and it is what keeps a session's prefix byte-stable so its prompt cache survives.
- The Jev scorer is documented as optional everywhere it is mentioned. `--provider mechanical`
  needs no key and no network and the measurements show it keeps every item of every information
  category on every corpus size tested, so the README now answers "does it work without a model
  API key?" directly, and `lcc compact --help` says which path needs what.
- `benchmarks/research/run_cache_patterns.py`: measures where compaction is placed, which turns
  out to matter more than how much it removes. Per-payload compaction (the tool result, before it
  is appended) saved 42.4% of context cost against 7.9% for a single whole-session pass, and spent
  fewer scorer tokens, because a whole-session drop pays to rewrite everything it invalidates.
  `docs/CACHE_ALIGNMENT.md` now carries the placement guidance and the recommended order.
- An audit guide in `benchmarks/research/README.md`: what each script proves, how to re-run every
  number, and the two habits that keep the benchmark honest (report recall per information
  category, and check that the objective actually requires the ground truth before blaming a
  component).
- Supersession rule in the deterministic safety net: a block that revises or corrects a value
  carried by a kept block is kept too, even when it shares only one distinctive term with it. It
  closes the last category the local scorer was losing (`temporal`, at 0.00 on every scale) for
  between one and two points of reduction. The rule is a separate pass rather than a transitive
  closure, because making the closure transitive cost 27 points of reduction on the medium corpus.
- `lcc explain`: reads a report written by `lcc compact -r` and prints why every block was kept,
  trimmed or dropped, in plain language, with the original text behind each decision when
  `--source` is given. `--only` filters to one decision kind and `--limit` caps the trail. It
  never re-runs compaction and never touches the network, so a pass stays auditable after the
  fact.
- Recall by information category in the research benchmark. The corpora now carry categorized
  ground truth (critical facts, a constraint, a negative constraint, an exception, a dated
  revision and a contradictory measurement) and `run_matrix.py` reports recall per category
  instead of one flat count.
- `benchmarks/research/stress_edges.py`: a stress and edge-case suite. The `xl` corpus is roughly
  four times `large` (1 492 blocks, 44 128 tokens) and confirms that category recall, reduction
  and cache byte-stability hold at that scale; eight edge cases cover empty input, whitespace, a
  single oversized block, CRLF, unicode, 400 sub-floor blocks and a 40 kB line.
- Deterministic safety net for locally scored blocks (`--deterministic-protection`, on by
  default). When `lcc compact` falls back to the lexical scorer, three classes of evidence now
  survive it: quoted third-party speech, evidence written in another language than the
  objective, and blocks sharing two or more distinctive terms with a block that is being kept.
  Measured against the adversarial suite in `benchmarks/research/`, this takes the deterministic
  path from 17/20 cases passing to 20/20, and on the main corpora from 3/5 ground-truth facts
  retained to 5/5, at a cost of 10 to 23 points of reduction. The Jev path is unaffected.
- `invalidated_tokens` and `break_even_reuses` in the relevance compaction report, plus a
  `cache_epoch_risk` warning when a pass mutates a warm prefix earlier than the reuse count can
  pay for. Measured break-even sits between 11.8 and 20.3 reuses across three corpus sizes.
- `degradation_reason` and `semantic_guarantee` (`judged` / `partial` / `none`) in the relevance
  compaction report so callers can decide whether a pass is trustworthy without parsing prose.
- `--marker-scores` and `--require-exact-tokens` CLI flags for `lcc compact`.
- `benchmarks/research/`: a measured study of compaction effectiveness, evidence retention and
  prompt-cache safety, with reproducible corpora, a 39-run transform matrix, a cache-safety
  suite, and a real 9-agent A/B against a no-LCC baseline.

### Fixed

- Identical blocks are now decided once per run. The decisions cache is content-addressed, so a
  run that scored two copies of the same block independently could disagree with the single
  cached score a warm run reuses, changing the emitted bytes between runs.

## [0.2.0] - 2026-06-22

### Added

- `lcc inspect` diagnostic command — analyzes a text input (from a file or stdin) and reports
  its token, structure, duplication, cleanup, and cost profile, plus a clearly-labelled
  projection of what `lcc optimize`'s safe cleaning would remove. It is diagnostic, not
  transformative: it builds **no** prompt, makes no network or model call, and never modifies
  the input. The JSON report goes to `--report` (or stdout); a human-readable summary and
  warnings go to stderr.
- Deterministic inspection reports (`lcc.inspection`, `schema_version` 1.0): identical input
  produces a byte-identical report — no timestamps, random values, absolute paths, or
  machine-specific values. Token counts preserve the exact-vs-approximate honesty of ADR 0005
  and ADR 0008.
- ADR 0009 — `lcc inspect` is a diagnostic boundary (no prompt, no transform).
- PyPI Trusted Publishing workflow for tag-triggered releases via GitHub Actions OIDC,
  without long-lived PyPI tokens.
- Explicit source distribution manifest covering docs, examples, benchmark fixtures, config
  examples, and tests.
- PEP 561 typing marker (`py.typed`) in the wheel.

### Changed

- Documented published-package installation with `pipx install local-context-compiler` and
  `python -m pip install local-context-compiler`.
- Updated the release checklist for building distributions, checking them with `twine`,
  installing the wheel in a clean virtual environment, and publishing through PyPI Trusted
  Publishing.

## [0.1.0] - 2026-06-19

First public release: the deterministic, local-first context-optimization MVP plus a
deterministic benchmark harness. No RAG, embeddings, vector databases, local or remote LLM
calls, API server, voice/audio, transcript ingestion, semantic scoring, model routing, or
response verification — those remain roadmap items (see `docs/roadmap.md`).

### Added

- Initial deterministic MVP — identical input produces identical output.
- Deterministic cleaning: `normalize_text`, `remove_common_boilerplate`,
  `deduplicate_paragraphs` (exact + conservative near-duplicate).
- Token budget and cost estimation: token counting via `tiktoken` with an honest
  approximate fallback (the method `exact` / `approximate` is surfaced in every report),
  plus configurable, editable model pricing and input-cost estimates.
- Tokenizer network guard: exact token counting runs inside a tightly scoped no-network
  guard. `lcc` blocks runtime network access by default — including the first-use encoding
  download `tiktoken` would otherwise perform — and no CLI command makes an internet request
  by default. If exact tokenizer assets are not available locally, counting falls back to a
  clearly labelled approximate count whose warning explains the specific reason (tiktoken not
  installed, model/encoding unknown, encoding unavailable offline, or another tiktoken
  failure). Exact counting therefore requires the encoding assets to be cached locally. See
  [ADR 0008](docs/adr/0008-tokenizer-network-boundary.md).
- Evidence-aware prompt builder with an extensible template registry.
- `OptimizationReport` (deterministic JSON, `schema_version` 1.0) with before/after
  characters, tokens, compression ratio, savings percentage, cost before/after, cleaning
  steps, dedup metrics, and warnings.
- `lcc optimize` CLI (file or stdin), with `--version` and graceful, non-zero-exit errors.
- `lcc bench` CLI and the deterministic benchmark harness (`lcc.benchmarking`): runs the
  optimization pipeline over committed fixtures in `benchmarks/cases/` and reports mechanical
  metrics (token savings, compression ratio, character reduction, exact/approximate token
  mode, literal marker preservation, warnings) with explicit per-case thresholds and a
  versioned (`schema_version` 1.0), deterministic JSON/Markdown report. See ADR 0007. It does
  **not** measure LLM answer quality.
- Benchmark fixtures in `benchmarks/cases/` (basic redundancy, boilerplate cleanup, evidence
  preservation, approximate-token fallback).
- Architecture Decision Records 0001–0008 capturing the frozen, one-way-door design
  decisions.
- CI workflow (`.github/workflows/ci.yml`) running ruff, mypy, and pytest on Python 3.11,
  3.12, and 3.13.
- Open-source project docs: `README.md`, `CONTRIBUTING.md`, `SECURITY.md`,
  `CODE_OF_CONDUCT.md`, the `docs/` set (architecture, evaluation, roadmap, release, ADRs),
  examples, and agent guidance (`CLAUDE.md`, `AGENTS.md`).

[Unreleased]: https://github.com/lucasmartins-ai/lcc/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/lucasmartins-ai/lcc/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/lucasmartins-ai/lcc/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/lucasmartins-ai/lcc/compare/v0.5.0...v1.0.0
[0.5.0]: https://github.com/lucasmartins-ai/lcc/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/lucasmartins-ai/lcc/compare/v0.2.0...v0.4.0
[0.2.0]: https://github.com/lucasmartins-ai/lcc/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/lucasmartins-ai/lcc/releases/tag/v0.1.0
