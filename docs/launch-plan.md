# Launch plan

Where people who lose work to `/compact` summaries, or pay for long agent sessions, already
look for tools, and how lcc gets in front of them. Checked 2026-10-23. Submission rules change;
re-read each venue's rules before posting.

## The claim every post uses

One number, with its method, re-runnable by anyone:

- One real Claude Code session, 193 messages: 57,083 to 28,807 tokens (−49.5%) with
  `rules` / `stashed` on PyPI 1.2.0, 43 of 43 user and assistant messages byte for byte.
  `lcc measure-session <session.jsonl>`, exact `o200k_base` counts.
- Across the maintainer's 299 long sessions (100+ messages, 36.3 M tokens, 2026-10-23):
  median cut 21.8%, middle half 14.5% to 31.1%, best 65.2%, 0 messages lost
  (`python benchmarks/research/long_sessions.py`). Always say these are one person's sessions,
  and re-run before quoting: the corpus grows every day.

Do not quote the older 44,128 to 13,228 stress-corpus figure or the 22.6% Laya/Jev parity;
both came from harnesses this repo has since retracted or labelled (see
`benchmarks/research/RESEARCH_STATUS.md`).

## Already done (before this plan)

| Where | State |
| --- | --- |
| Official MCP registry, `io.github.lucasmartins-ai/lcc` | published, 1.2.0 |
| Glama | listed, Dockerfile check passes |
| punkpeye/awesome-mcp-servers | PR #17069 open since 2026-10-20, Glama badge added |
| X, Threads, LinkedIn | 27 posts mentioning lcc, 2026-09-20 to 2026-10-22 (10 Threads, 9 X, 8 LinkedIn), most recently the `/compact` angle |

Nothing has run yet on Hacker News, Reddit, dev.to or any Discord, and no awesome list other
than punkpeye has an entry.

## Venues, ranked by expected reach per hour of work

| # | Venue | How to submit | Rules that matter | Angle |
| ---: | --- | --- | --- | --- |
| 1 | [Show HN](https://news.ycombinator.com/showhn.html) | Title `Show HN: lcc – compact Claude Code sessions without summarizing them`, link to the repo | Must be runnable without signup; the author stays in the thread to answer; no vote asking | The `/compact` vs lcc table and "run it on your own session in 30 seconds" |
| 2 | [hesreallyhim/awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code) | Issue form `recommend-resource.yml`, web UI only (PRs and `gh` submissions are refused) | 14+ days old with active commits; one neutral line, no emoji; leave the last checklist box unchecked | Category "Memory & Context Persistence": replaces the `/compact` summary with recallable verbatim context |
| 3 | [r/ClaudeAI](https://www.reddit.com/r/ClaudeAI) | Post, showcase flair | Showcase posts need about 50 karma (mod post, 2026-04); otherwise the "Built with Claude" megathread | What `/compact` loses, measured on a real session |
| 4 | [Anthropic plugin directory](https://github.com/anthropics/claude-plugins-official) | Third-party submission form linked from the README | Quality and security review; process not documented | The plugin that hands back compacted messages instead of a summary |
| 5 | [r/LocalLLaMA](https://www.reddit.com/r/LocalLLaMA) | Post | Self-promotion about 1 in 10 of your activity; karma minimums (unverified, check live rules) | Offline, no API key, plain-Python rules; works on Codex CLI rollouts too |
| 6 | [pleasedodisturb/awesome-llm-token-optimization](https://github.com/pleasedodisturb/awesome-llm-token-optimization) | PR, Prompt Compression → Tools | `- [Name](URL) - One sentence.` plus star badge; CI: 30+ days old, 2+ contributors or 50+ stars; disclose self-submission | Token cut without summarizing, with a re-runnable number |
| 7 | [yzfly/awesome-context-engineering](https://github.com/yzfly/awesome-context-engineering) | PR to `README.md` and `README_CN.md`, Memory & Compression | Same line in both languages; existing order | Verbatim compaction with recall, next to other compaction tools |
| 8 | [mcpservers.org](https://mcpservers.org/submit) | Web form (wong2 list takes no PRs) | Free review "within 2 weeks"; paid fast lane exists, not needed | Memory category |
| 9 | [cline/mcp-marketplace](https://github.com/cline/mcp-marketplace) | Issue template `mcp-server-submission.yml` | 400×400 PNG logo; Cline must be able to install from the README | The MCP server: `compact`, `recall` for any stdio client |
| 10 | [dev.to](https://dev.to) | Article, tags `claude`, `ai`, `python`, `opensource` | Self-written posts fine; canonical link if cross-posted | "What /compact throws away": a walkthrough with `lcc recall` |
| 11 | r/mcp, r/ChatGPTCoding, r/ClaudeCode | Post | Rules not verified; read the sidebar first | MCP server for r/mcp, Codex rollouts for r/ChatGPTCoding |
| 12 | [ai-for-developers/awesome-ai-coding-tools](https://github.com/ai-for-developers/awesome-ai-coding-tools) | PR, "MCP Servers and Directories", append at the end | Needs a free tier (MIT qualifies) | MCP server for coding agents |
| 13 | [Jenqyang/Awesome-AI-Agents](https://github.com/Jenqyang/Awesome-AI-Agents) | PR, Tools | Open-source licence; wording must not read like an ad | Context tooling for agents |
| 14 | [milisp/awesome-codex-cli](https://github.com/milisp/awesome-codex-cli) | Issue "Submit a resource" | Needs a documented Codex setup (`codex mcp add` or a `config.toml` block) first | Codex CLI rollout support |
| 15 | [hashgraph-online/awesome-codex-plugins](https://github.com/hashgraph-online/awesome-codex-plugins) | PR | Lists Codex plugins; lcc needs a Codex plugin bundle first | Later |
| 16 | [tensorchord/Awesome-LLMOps](https://github.com/tensorchord/Awesome-LLMOps) | PR, one per suggestion, alphabetical | Weak fit | Skip unless the others land |
| 17 | Discords: Claude Developers, MCP | Showcase channels only | Not verified | The plugin for Claude Developers, the MCP server for MCP |
| 18 | [Meirtz/Awesome-Context-Engineering](https://github.com/Meirtz/Awesome-Context-Engineering) | PR | Last merge 2026-05, 56 open PRs | Low odds |

Rejected: appcypher/awesome-mcp-servers (archived), wong2/awesome-mcp-servers PRs (closed to
PRs), e2b-dev/awesome-ai-agents (stalled, and lcc is not an agent), skills and subagent lists
(lcc is not a skill), Smithery (hosted servers; lcc is stdio and offline), Lobste.rs (invite
only), awesome-python (bar too high for the project's age).

## Submitted 2026-10-23

| Venue | Link | State |
| --- | --- | --- |
| yzfly/awesome-context-engineering | [PR #103](https://github.com/yzfly/awesome-context-engineering/pull/103) | open |
| pleasedodisturb/awesome-llm-token-optimization | [PR #68](https://github.com/pleasedodisturb/awesome-llm-token-optimization/pull/68) | open, CI checks the inclusion bar |
| ai-for-developers/awesome-ai-coding-tools | [PR #1073](https://github.com/ai-for-developers/awesome-ai-coding-tools/pull/1073) | open |
| Jenqyang/Awesome-AI-Agents | [PR #656](https://github.com/Jenqyang/Awesome-AI-Agents/pull/656) | open |
| Show HN | [item 50213585](https://news.ycombinator.com/item?id=50213585) | live; the author's first comment was auto-killed (new account, karma 1), moderators emailed |
| r/ClaudeAI | [showcase megathread comment](https://www.reddit.com/r/ClaudeAI/comments/1sly3jm/built_with_claude_project_showcase_megathread/19rjqaqf7sc02/) | live; feed posts need 50-100 karma, the account has 19 |
| r/LocalLLaMA | not posted | lcc was already posted there on 2026-09-04, and the account's history is mostly self-promotion (rule 4: about 1 in 10); the rules also ban primarily LLM-written posts. Wait until the account has real participation, then the maintainer writes the post himself |

Venues 2, 4, 8, 9 and 10 need the maintainer: they post under his name or
go through a web form.

## Order

1. GitHub-only list PRs (6, 7, 12, 13). They need no new account and add backlinks that stay.
2. Forms that a person submits: awesome-claude-code (2), Anthropic plugin directory (4),
   mcpservers.org (8), Cline (9).
3. Show HN on a weekday morning US Eastern, with the maintainer free for the next three hours
   to answer. r/ClaudeAI the day after, r/LocalLLaMA two days later, each with its own text.
4. dev.to article once HN feedback shows which question people ask first.

## Rules for every post

- Every number comes from a command in this repo and says how it was counted.
- Different text per venue; same claim.
- No emoji, no exclamation marks, no superlatives. End on a question people can answer by
  running `lcc measure-session` on their own session.
- Point results to [Discussions → Results](https://github.com/lucasmartins-ai/lcc/discussions/categories/results).
