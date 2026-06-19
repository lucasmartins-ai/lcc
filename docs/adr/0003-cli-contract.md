# ADR 0003 — CLI command and flag contract

**Status:** accepted

**Decision.** A single command:
`lcc optimize INPUT [--question --model --max-input-tokens --max-output-tokens
--task-type --constraint (repeatable) --output --report --pricing --config --template
--no-boilerplate --no-near-dedup --allow-external-knowledge]`.
`INPUT="-"` reads from stdin. `lcc --version` prints the version.

**Why.** Scripts and CI depend on flag names; freezing the surface now prevents breaking
downstream users later.

**Forecloses.** Within v0.x, flags are additive only. Renaming or removing a flag requires
a deprecation cycle and a minor/major version bump.
