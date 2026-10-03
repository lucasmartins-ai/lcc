# Frozen MSI schema fixtures

Test-only copies of MSI v0.1 contracts from the local
`minimum-sufficient-inference/spec/` reference repository, captured 2026-10-03.
No reference repository was modified. The bytes and hashes below pin the
contract used by the sprints; they are not a second runtime implementation.

Tests load these files relative to this checkout so GitHub runners do not
need a developer-specific path or a separate private/local clone. The
`jsonschema` validator is a development extra, not a runtime dependency:
without it pytest skips entire contract-test modules and can conceal invalid
receipts. `pip install -e ".[dev,tiktoken]"` enables those checks in CI.
Update these snapshots only with an explicit contract version change.

| File | Source SHA-256 |
|---|---|
| `context-ir.schema.json` | `ce9435553bdaa9dcc56a2149d061f1213f5ff827d74b1af296c650b97d9eb9f0` |
| `inference-plan.schema.json` | `204ced04a815f94b61af08e6f42bec6277924e720ba183e156ad55b90d308b73` |
| `verification-result.schema.json` | `6d74783862b224181ba0e70815da1eadc3153ba400dadf1257ef73f78f935061` |
| `inference-receipt.schema.json` | `b59f051ffe44f66385489a3986d42b9c7626c6458a8053e894227e5eb48d7785` |
