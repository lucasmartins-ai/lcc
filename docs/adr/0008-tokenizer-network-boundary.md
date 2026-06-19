# ADR 0008 — Tokenizer network boundary (no indirect network via tiktoken)

**Status:** accepted

**Context.** ADR 0006 forbids network/LLM code in the deterministic core, and ADR 0005
makes token counts honestly declare `exact` vs `approximate`. `tiktoken` is our optional
exact tokenizer, but it performs a **first-use network fetch** for encoding assets that are
not already in its local cache (`tiktoken.load.read_file` calls `requests.get`). Merely not
importing `requests` ourselves is therefore insufficient: an indirect download could still
happen at runtime, breaking the local-first promise.

**Decision.**

- **No runtime network, including indirect.** lcc-owned code and the dependency calls it
  makes must not access the network during normal operation. This holds for the whole CLI:
  no `lcc` command makes an internet request by default.
- **tiktoken is exact only when assets are local.** tiktoken is allowed solely as an optional
  exact tokenizer, and only when its encoding assets can be loaded from a local cache.
  "Exact tokenization" means exact *under local cached tokenizer availability*.
- **Block, then fall back honestly.** The exact path runs inside a tightly scoped no-network
  guard (`lcc.token_budget.counters._no_network_guard`) that temporarily neutralizes the HTTP
  entry points tiktoken can use — `requests.get` / `requests.Session.request` when `requests`
  is importable, plus `socket.connect` / `socket.create_connection` as a backstop — making any
  fetch raise `TokenizerNetworkBlocked`. If the guard fires (or any other tiktoken/encoding
  error occurs), counting falls back to the heuristic estimator. The guard is never installed
  globally and is fully restored after the call.
- **Approximate is always marked.** An approximate count sets `TokenCount.method =
  "approximate"` and records a `note` whose cause is one of: tiktoken not installed; the
  model/encoding is unknown (fallback encoding used); encoding assets unavailable offline (the
  network fetch was blocked); or another tiktoken failure. The pipeline surfaces that reason in
  the report `warnings`. An approximate count is **never** presented as exact.
- **Cache preparation stays opt-in / out of core scope.** Future commands may provide explicit
  tokenizer cache-preparation instructions (for example, populating `TIKTOKEN_CACHE_DIR`), but
  any runtime network access remains opt-in or outside the deterministic core. The benchmark
  harness's exact-mode cases may therefore require cached tokenizer assets to pass as `exact`;
  without them they fall back to approximate and fail honestly (ADR 0007).

**Why.** The right claim is precise: *lcc blocks runtime network access by default and falls
back honestly when exact tokenizer assets are unavailable* — not a vague "local-ish". Token
counts drive cost estimates, so a blocked download must degrade to a clearly labelled
approximation rather than either a silent download or a count that pretends to be exact.

**Forecloses.** The deterministic core may not depend on a live download for correctness. Any
future tokenizer or model that needs network access lives behind a new, clearly separated,
opt-in boundary (consistent with ADR 0002 and 0006); it must not weaken this guard or the
exact-vs-approximate contract in ADR 0005.
