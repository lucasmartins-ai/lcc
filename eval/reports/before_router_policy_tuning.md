# LCC-Router Local Evaluation

Local development proxy only; not official AMD Track 1 accuracy.

| Metric | Value |
| --- | ---: |
| total_cases | 10 |
| remote_tokens_total | 273 |
| remote_tokens_mean | 27.3 |
| local_accept_rate | 0.7 |
| remote_escalation_rate | 0.3 |
| format_pass_rate | 1.0 |
| estimated_accuracy_proxy | 1.0 |
| lcc_compression_applied_rate | 0.2 |
| average_projected_savings | 0.2254 |

## Cases

| case | route | remote_tokens_used |
| --- | --- | ---: |
| ambiguous_context_task | LOCAL_THEN_VERIFY | 0 |
| ambiguous_task | REMOTE_DIRECT | 99 |
| calculation_total | LOCAL_THEN_VERIFY | 0 |
| long_context | COMPRESS_THEN_REMOTE | 98 |
| long_duplicated_context | COMPRESS_THEN_REMOTE | 76 |
| noisy_context | COMPRESS_THEN_LOCAL | 0 |
| simple_qa | LOCAL_THEN_VERIFY | 0 |
| strict_format | LOCAL_THEN_VERIFY | 0 |
| strict_json_output | LOCAL_THEN_VERIFY | 0 |
| very_short_simple | LOCAL_THEN_VERIFY | 0 |

## Failures

None.
