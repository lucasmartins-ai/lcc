# ADR 0001 — Schemas use stdlib dataclasses, not Pydantic

**Status:** accepted

**Decision.** Core data structures (`OptimizationReport`, `PromptSpec`, token/cleaning/
pricing/cost metrics) are stdlib `dataclasses`, serialized to JSON by a small recursive
normalizer. Pydantic is **not** a runtime dependency in the MVP.

**Why.** It keeps the dependency surface minimal (an explicit project constraint), lets
the deterministic core import and run its tests with zero third-party packages, and the
report is output-only, so heavyweight validation buys little here.

**Forecloses.** No automatic input coercion/validation from Pydantic. If richer validation
is needed later it can be introduced at the CLI boundary via a new ADR without renaming
report fields.
