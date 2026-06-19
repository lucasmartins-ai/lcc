## Summary

<!-- What does this PR do, and why? One or two sentences. -->

## Scope

<!-- Which modules/files does this touch? Is this core, CLI, benchmarking, or docs? -->

- [ ] This is the **smallest safe change** for the goal (no unprompted redesign).

## Tests run

<!-- Paste or confirm the results. Never fabricate; if a check was not run, say so. -->

- [ ] `python -m pytest`
- [ ] `ruff check .`
- [ ] `ruff format --check .`
- [ ] `mypy`

## Benchmark impact

<!-- Required for any change to optimization behavior. -->

- [ ] Not applicable (no change to cleaning/dedup/token/prompt behavior), **or**
- [ ] Ran `lcc bench benchmarks/cases` and noted the mechanical impact below.

<!-- Paste relevant before/after metrics. Remember: the harness measures mechanical
     behavior, not LLM answer quality. -->

## Documentation

- [ ] Updated `README.md` / `docs/` / `CHANGELOG.md` where behavior changed, **or** no
      docs change was needed.
- [ ] **No roadmap feature is documented as implemented** (docs honesty rule).

## Boundary confirmations

- [ ] No **runtime network** calls were added to the deterministic core (network stays
      blocked by default, including indirect access via `tiktoken`).
- [ ] No **model/LLM/embedding** calls were added to the core.
- [ ] **Tokenization honesty considered:** exact counting still requires local `tiktoken`
      assets, and any approximate fallback is clearly labelled (never presented as exact).
- [ ] If the JSON report shape changed, `schema_version` was handled per
      [ADR 0004](docs/adr/0004-report-schema-versioning.md) (additive → stays `1.0`;
      breaking → bump).

## Notes / residual risk

<!-- Anything a reviewer should know: new dependencies, follow-ups, known gaps. -->
