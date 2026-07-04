# Routing Policy

The router is policy-driven and auditable. It does not learn a route model yet.

Default thresholds live in `configs/router_policy.yaml`:

```yaml
router:
  local_first_max_tokens: 2500
  compress_if_projected_savings_above: 0.15
  remote_direct_if_input_tokens_above: 16000
  escalate_if_manual_review: true
  local_accept_confidence: 0.78
  strict_format_requires_verification: true
  compress_before_remote: true
```

Route rules:

- simple and short tasks start as `LOCAL_THEN_VERIFY`;
- long/noisy contexts with projected LCC savings use `COMPRESS_THEN_LOCAL` or
  `COMPRESS_THEN_REMOTE`;
- strict output formats require verification before local acceptance;
- external-knowledge, conflicting, or highly ambiguous tasks escalate;
- verifier rejection escalates to Fireworks;
- local acceptance records zero remote tokens;
- remote calls count provider usage or conservative estimates.

The route trace is returned in `FinalAnswer.metadata.trace`.
