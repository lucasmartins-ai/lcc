# Architecture Decision Records

Short records of the one-way-door decisions frozen before the MVP was written.
Each entry states the decision, the reason, and what it forecloses. These are the
public / cross-module contracts that are expensive to change after release.

| ADR | Decision |
| --- | --- |
| [0001](0001-schema-contracts.md) | Schemas use stdlib dataclasses, not Pydantic |
| [0002](0002-module-boundaries.md) | Module boundaries and interfaces |
| [0003](0003-cli-contract.md) | CLI command and flag contract |
| [0004](0004-report-schema-versioning.md) | JSON report carries `schema_version` |
| [0005](0005-tokenization-boundary.md) | Exact vs approximate token counting |
| [0006](0006-determinism-boundary.md) | Cleaning/dedup stay free of LLM and network |
| [0007](0007-deterministic-benchmark-harness.md) | Deterministic, fixture-based benchmark harness |
| [0008](0008-tokenizer-network-boundary.md) | Tokenizer network boundary (no indirect network via tiktoken) |
| [0009](0009-inspection-command-boundary.md) | `lcc inspect` is a diagnostic boundary (no prompt, no transform) |
| [0010](0010-deterministic-first-preparation-model-assistance.md) | Deterministic Phase 1.7 prepare boundary; optional model assistance is not implemented |
| [0011](0011-phase-2-opt-in-semantic-retrieval-boundary.md) | Accepted Phase 2 opt-in semantic retrieval boundary with a disabled-by-default scaffold; retrieval execution is not implemented |
| [0012](0012-semantic-retrieval-execution-boundary.md) | Future semantic retrieval execution must use a separate opt-in local-index adapter; execution is not implemented |
| [0013](0013-instant-relevance-compaction-boundary.md) | Opt-in instant relevance compaction (`lcc compact`) via narrow model judgment (Jev): fail-safe, byte-faithful, cache-aligned sticky decisions |
| [0014](0014-minimum-sufficient-context.md) | Minimum sufficient context: safety model, v1.1 cache identity, tokenizer contract, type-aware trim, context graph, sufficiency verification, confidence policy |

ADRs are append-only. To change a decision, add a new ADR that supersedes the old one.
