# ADR 0004 — JSON report carries `schema_version`

**Status:** accepted

**Decision.** Every JSON report includes `schema_version` (starting at `"1.0"`) and
`tool_version`. Reports are deterministic: no timestamps, no random ordering.

**Why.** Downstream consumers can branch on `schema_version`; determinism makes reports
diffable in version control and exactly assertable in tests.

**Forecloses.** Additive fields keep `schema_version` at `"1.0"`. Removing/renaming a field
or changing the meaning of one bumps the major schema version.
