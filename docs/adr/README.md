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

ADRs are append-only. To change a decision, add a new ADR that supersedes the old one.
