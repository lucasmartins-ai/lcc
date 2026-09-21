# Benchmark report

- Schema version: `1.0`
- Total cases: 6
- Passed: 6
- Failed: 0
- Average token savings: 58.93%
- Average compression ratio: 0.4107

> Mechanical optimization and prepare-selection metrics only: token/character reduction, literal marker checks, exact-vs-approximate token mode, prepare action, and selection state. This does **not** measure final LLM answer quality and does not perform semantic selection, embeddings, network access, model calls, summarization, rewriting, or paraphrasing (ADR 0007, ADR 0010).

| Case | Status | Token savings % | Compression | Char reduction % | Token mode | Marker recall | Forbidden kept | Prepare action | Selection |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| approximate_token_fallback | PASS | 53.16 | 0.4684 | 49.46 | approximate | 1.00 | 0 | - | - |
| basic_redundancy | PASS | 62.07 | 0.3793 | 62.55 | exact | 1.00 | 0 | - | - |
| boilerplate_cleanup | PASS | 35.06 | 0.6494 | 45.28 | exact | 1.00 | 0 | - | - |
| evidence_preservation | PASS | 52.29 | 0.4771 | 52.42 | exact | 1.00 | 0 | - | - |
| prepare_lexical_selection | PASS | 78.57 | 0.2143 | 78.60 | approximate | 1.00 | 0 | optimize_with_flags | applied: lexical_matches |
| prepare_no_selection | PASS | 72.41 | 0.2759 | 74.97 | approximate | 1.00 | 0 | optimize_with_flags | not applied: no_lexical_matches |
