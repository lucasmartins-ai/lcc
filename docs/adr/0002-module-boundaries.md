# ADR 0002 — Module boundaries and interfaces

**Status:** accepted

**Decision.** Four deterministic libraries — `cleaning/` (text → text + metadata),
`token_budget/` (token counting + pricing math), `prompt_builder/` (spec → string),
`reporting/` (assemble report + JSON) — orchestrated by `pipeline.py`. `cli.py` is the
only presentation/IO layer (Typer/Rich) and the only place config files are read.

**Why.** Each module owns one responsibility and has no knowledge of the others; the
pipeline wires them together; the CLI stays a thin shell so all logic is unit-testable
without Typer or Rich installed.

**Forecloses.** Modules never import each other directly (only the pipeline composes
them). A future stage attaches by adding a pipeline step, not by editing a peer module.
