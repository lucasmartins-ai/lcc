# LCC-Router Policy Tuning Comparison

Local development proxy only; not official AMD Track 1 accuracy.

| Metric | Before | After | Delta |
| --- | ---: | ---: | ---: |
| total_cases | 10 | 10 | 0 |
| remote_tokens_total | 273 | 99 | -174 |
| remote_tokens_mean | 27.3 | 9.9 | -17.4 |
| local_accept_rate | 0.7 | 0.9 | +0.2 |
| remote_escalation_rate | 0.3 | 0.1 | -0.2 |
| format_pass_rate | 1.0 | 1.0 | 0.0 |
| estimated_accuracy_proxy | 1.0 | 1.0 | 0.0 |
| lcc_compression_applied_rate | 0.2 | 0.3 | +0.1 |

Remote tokens dropped by 174 on the expanded 10-case fixture set.

## Route Changes

| case | before | after | remote tokens before | remote tokens after |
| --- | --- | --- | ---: | ---: |
| long_context | COMPRESS_THEN_REMOTE | COMPRESS_THEN_LOCAL | 98 | 0 |
| long_duplicated_context | COMPRESS_THEN_REMOTE | COMPRESS_THEN_LOCAL | 76 | 0 |

## Still Remote

| case | route | remote_tokens_used | reason |
| --- | --- | ---: | --- |
| ambiguous_task | REMOTE_DIRECT | 99 | asks for latest public status outside the provided context |
