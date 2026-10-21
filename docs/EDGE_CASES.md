# Edge cases: input and compaction

What the deterministic core does with hostile or unusual input, and the test that pins each
behaviour. "Handled" means the output is defined and tested. "Rejected" means a `ValueError`
(text APIs) or `TranscriptError` (tool-call mode) with a message that names the problem. No
case may crash with another exception or change bytes without saying so.

Test files: [`test_edge_input.py`](../tests/test_edge_input.py) (I),
[`test_edge_compaction.py`](../tests/test_edge_compaction.py) (C),
[`test_edge_transcript.py`](../tests/test_edge_transcript.py) (T). The hostile corpus is
seeded and stdlib-only ([`edge_corpus.py`](../tests/edge_corpus.py)): `edge_document(seed)`
reproduces any failing document.

## Invariants

Checked as properties over the seeded corpus (about 50 documents) and every local scorer
(mechanical, specialist-v3, a hash-based stand-in for Jev that exercises the trim band and the
verifier).

| Invariant | Statement | Test |
| --- | --- | --- |
| Determinism | Same input and options give byte-identical output and report, apart from `latency_ms` and `compilation_ms`. This also holds across `PYTHONHASHSEED` values and the `C` / `C.UTF-8` locales. | C `test_compaction_is_verbatim_accounted_and_deterministic`, `test_output_is_independent_of_hash_seed_and_locale`; I `test_cleaning_and_intake_never_crash_and_are_deterministic`; T `check_all_providers` |
| Verbatim | Gaps and kept blocks are re-emitted byte-exact, in order. A trimmed block keeps a byte-exact prefix of itself; for logs it keeps a prefix, a newline and a tail slice. A note follows, and nothing else changes. Segmentation is lossless: blocks plus gaps rebuild the input. | C `assert_verbatim_and_accounting`; I `test_segmentation_is_verbatim_and_ordered` |
| Accounting | `blocks_*`, `chars_*`, `tokens_*`, `output_sha256`, `reduction_ratio`, `first_mutation_offset`, `worth_it` and the cache hit/miss counters all reconcile exactly with the decisions and the emitted text. In tool-call mode the per-kind call counters, char and token totals and `chars_after` per decision do too. | C `assert_verbatim_and_accounting`, `test_cache_hit_and_miss_counts_reconcile`; T `assert_transcript_invariants` |
| Idempotence | A second mechanical pass over the output, with the same objective, never drops a block the first pass kept for an intrinsic reason: lexical overlap, any protection, quoted speech, other-language evidence or high-risk text. It never drops a marker either. It **may** drop a block kept only for a relational reason, such as a dependency link or a sufficiency restoration, because the block it was linked to can be gone and term rarity is corpus-relative. A keep-only result is a fixed point. | C `test_second_pass_never_drops_an_intrinsically_kept_block`, `test_compacting_a_keep_only_result_is_the_identity` |
| Never-drop | These blocks are kept at every `specialist_drop_fraction` in [0, 0.99]: protected blocks (short, `keep_patterns`, protected prefix, `preserve_tail_blocks`), the latest user message when transcript segments are given, and the specialist-v3 rule floor (the best goal match and the newest error blocks). In tool-call mode the first and the newest `preserve_recent` messages are never changed. User and assistant text is never touched. | C `test_protected_blocks_survive_any_specialist_budget`, `test_latest_user_message_survives_any_specialist_budget`, `test_specialist_floor_blocks_survive_any_budget`; T `test_pins_and_latest_user_message_hold_at_every_window` |

## Continuous checks (tool-call mode)

[`tests/invariants.py`](../tests/invariants.py) holds seven invariants for the product modes
(`rules` with `lossless`, `recoverable`, `stashed`): idempotence, verbatim, recall round-trip,
no corruption, stable placeholders (also across `PYTHONHASHSEED`), accounting, and fail-closed,
which includes falling back to the keep-everything fail-safe only for a documented reason
(today: duplicate tool ids). Three things call them:

- [`test_invariants_fuzz.py`](../tests/test_invariants_fuzz.py): hypothesis-generated
  transcripts for `LCC_FUZZ_SECONDS` (one fixed-seed batch when unset; 60 s in PR CI; 600 s in
  the nightly workflow, which uploads the seeds and any shrunk failing input and gates nothing).
  `LCC_FUZZ_SEED` replays a batch;
- the versioned [adversarial corpus](../tests/corpus/adversarial/), replayed on every run;
- the transcript edge tests below (`assert_transcript_invariants`).

The first runs found five defects, each now a corpus case: lossless re-deduped its own pointers
(and stash pointers) on a second pass; a result forced back to `keep` still carried its `stash`
field; the verification fail-safe kept every call but left `note`/`kept_at`/`stash` on the
decisions; a whitespace-only user message was dropped on rebuild, which tripped the fail-safe
and stopped the whole pass; and an output too short to stash was held out of lossless dedupe,
so a second `stashed` pass changed it.

## Input

| Edge case | Expected behaviour | Test |
| --- | --- | --- |
| Empty or whitespace-only input | `optimize`: empty cleaned context and a warning. `compact`: identity, 0 blocks. An empty objective is rejected. | I `test_pipeline_empty_and_whitespace_only_input_is_handled`, `test_compaction_of_empty_input_is_identity`, `test_compaction_requires_an_objective` |
| Leading BOM | Cleaning strips it and records the step `strip_bom`. Compaction keeps it verbatim. Either way a code fence on the first line is still recognised. | I `test_normalize_strips_leading_bom_and_records_it`, `test_normalize_protects_a_code_fence_right_after_a_bom`, `test_blocks_detect_a_code_fence_right_after_a_bom`, `test_bom_is_kept_verbatim_by_compaction` |
| CRLF, CR, mixed newlines | Cleaning converts them to LF. Compaction keeps them. Line numbers count `\n`, `\r\n` and a lone `\r` as one break each; U+2028, form feed and `\x85` are characters inside a line. An oversized block is never cut between `\r` and `\n`. | I `test_cr_only_line_numbers_count_cr_as_a_line_break`, `test_mixed_newline_line_numbers`, `test_unicode_line_separators_do_not_split_lines`, `test_oversized_crlf_block_is_never_cut_between_cr_and_lf` |
| NUL and control characters | Kept as content. Input that contains the cleaner's internal placeholder text is never substituted: the placeholder prefix is chosen so it does not occur in the input. | I `test_normalize_placeholder_text_in_input_is_not_substituted`, `test_speech_cleaning_placeholder_text_in_input_is_not_substituted`, `test_control_characters_survive_cleaning` |
| Invalid UTF-8 | The CLI exits non-zero with a "UTF-8" message and no traceback. Unpaired surrogates (from `surrogateescape` decoding or a JSON `\ud800` escape) are rejected by `optimize`, `compact_context` and `parse_transcript`. | I `test_cli_rejects_invalid_utf8_with_a_clear_message`, `test_*_rejects_lone_surrogates_*`; T malformed-payload table |
| Very long single line | Split into blocks of at most `max_block_chars`, verbatim. | I `test_very_long_single_line_splits_into_bounded_verbatim_blocks` |
| NFC vs NFD duplicates | Paragraph dedup compares NFC keys, so they are exact duplicates. The first occurrence keeps its own bytes. Compaction never normalises. | I `test_nfc_and_nfd_paragraphs_are_exact_duplicates_and_first_bytes_win` |
| RTL, emoji, zero-width characters | Kept byte-exact by cleaning and compaction. | I `test_rtl_emoji_and_zero_width_characters_are_preserved` |
| Portuguese / English mix | Lexical matching is accent-insensitive (`fold_accents`), so a goal typed without accents matches accented evidence. Language detection sees accented function words, so evidence in another language than the objective is protected (`evidence_in_pt_not_en`). specialist-v3 features keep their training-time tokenization. | C `test_accent_folding_makes_lexical_matching_accent_insensitive`, `test_portuguese_objective_without_accents_keeps_the_accented_evidence`, `test_portuguese_evidence_survives_an_english_objective_under_specialist_v3`, `test_specialist_features_keep_the_training_time_tokenization` |
| Boilerplate-looking lines inside code fences | Never removed. Dedup never splits a fence or deduplicates inside it. | I `test_boilerplate_lines_inside_code_fences_are_kept`, `test_dedup_never_splits_or_dedups_inside_a_code_fence`, `test_pipeline_keeps_fenced_boilerplate_end_to_end`, `test_cleaning_never_touches_fenced_code` |
| Tables, deep nesting, indentation | Table spacing and leading indentation are kept. Dedup no longer strips the first line's indentation. | I `test_tables_keep_their_spacing_through_cleaning`, `test_deep_nesting_is_preserved`, `test_dedup_keeps_leading_indentation_of_a_paragraph` |
| More than 9,999 blocks | Ids grow to `blk_10000_…` and match `BLOCK_ID_RE`. Ties still sort in source order. | I `test_block_ids_match_the_published_pattern_past_9999_blocks`; C `test_restoration_rank_orders_numerically_past_9999_blocks` |

## Transcripts (tool-call mode)

| Edge case | Expected behaviour | Test |
| --- | --- | --- |
| Not a list, non-object message, missing or empty `role`, non-string `text`, tool block without id | Rejected | T `test_malformed_payloads_are_rejected_with_a_clear_error` |
| Missing or `null` `text` | Treated as empty. | T `test_missing_text_and_null_text_are_empty` |
| `content` (string or blocks), `images`, `attachments`, or any other non-empty list/object field | Rejected and the field is named. Before, the message parsed as empty and the output lost it. This mirrors the hook's `hasUnsupportedContent`. | T malformed-payload table |
| Tool result with content blocks (an image) | Rejected | T malformed-payload table |
| Tool call `input` that is not an object | Rejected. Before, it became `{}`. | T malformed-payload table |
| Non-string result `text` (object, number) | Serialized to JSON text deterministically. | T `test_non_string_result_text_is_serialized_deterministically` |
| Unknown roles (`system`, `tool`, ...) | Carried through. specialist-v3 renders `tool` as `user`. | T `test_unknown_roles_are_carried_through` |
| Scalar metadata, out-of-order timestamps | Ignored. Order is always the array order. | T `test_scalar_metadata_and_timestamps_are_ignored_and_order_is_array_order` |
| `tool_use` without a result, result without a call | Never a candidate. Both are kept byte-exact. | T `test_tool_use_without_result_and_orphan_result_are_untouched` |
| Duplicate tool ids | Kept by every provider (`duplicate_tool_use_id`). Before, a drop decided for one call also removed its namesake, even in a pinned message. | T `test_duplicate_ids_never_drop_the_pinned_namesake` |
| Call outside the recent window, result inside it | Kept whole by every provider (`pinned_recent_result`). | T `test_pins_and_latest_user_message_hold_at_every_window` |
| Interleaved parallel tool calls | Paired by id. Each result stays in its own message, in its original order. | T `test_interleaved_parallel_tool_calls_pair_by_id` |
| Huge tool output (2 MB) | Handled. A trim keeps a byte-exact head; the stashed mode replaces it with a `lcc recall` pointer. | T `test_huge_tool_output_is_handled_in_bounded_time` |
| Codex rollout items (no `role`) | Rejected (`has no string 'role'`). Codex sessions converted to the hook shape are supported by the rules policy. | T malformed-payload table |
| Empty transcript, window covering everything | Identity, with `no_candidates`. | T `test_empty_transcript_is_handled`, `test_preserve_recent_covering_everything_means_no_candidates` |

## Compaction

| Edge case | Expected behaviour | Test |
| --- | --- | --- |
| Supersession | A later successful whole-file Read/Write supersedes earlier views of the file. A later partial read, a failed read, or a re-read of a different range supersedes nothing. An identical rerun supersedes; a rerun whose output changed does not. | T `test_later_whole_read_supersedes_an_earlier_read`, `test_partial_later_read_does_not_supersede_a_whole_read_after_an_edit`, `test_re_reads_of_different_ranges_do_not_supersede_each_other`, `test_a_failed_later_read_supersedes_nothing`, `test_identical_rerun_is_superseded` |
| Error fixed later (old root cause) | The failing run stays: the passing rerun has different output. | T `test_an_error_fixed_later_is_not_superseded_by_the_passing_rerun` |
| Supersession / contradiction edges in the graph | The block that carries the cue is the edge source. | C `test_supersession_and_contradiction_edges_carry_the_cue_block_as_source` |
| Reduction below the 25% gate | `worth_it: false` and a `low_reduction` warning. The gate labels the pass and never changes the bytes. The boundary is inclusive (`ratio == min_reduction` is worth it). When nothing is mutated, block mode reports `worth_it: true`; tool-call mode compares the ratio, so 0 is below the gate. | C `test_reduction_gate_boundary_is_inclusive`; T `test_reduction_gate_below_25_percent_is_reported_not_enforced` |
| Ties in scores | specialist-v3: equal scores drop the older block first. Restoration: equal risk restores in source order (numeric block index, then id). | C `test_specialist_ties_drop_older_blocks_first`, `test_restoration_rank_ties_break_by_block_order` |
| Graph cycles | Closure keeps a seen set, so it terminates on any cycle at any hop count. | C `test_graph_closure_terminates_on_cycles` |
| Restoration budgets (ADR 0018) | Structural restorations are at most `max_restorations` (0 allowed). Verifier restorations are at most `verifier_max_restorations`, and only on FAIL. | C `test_structural_restorations_never_exceed_their_budget`, `test_verifier_boundaries_and_restoration_budget` |
| Verifier boundaries | PASS needs sufficiency ≥ 0.5 and confidence ≥ 0.5. Sufficiency < 0.5 gives FAIL at confidence ≥ 0.7 and REVIEW below that. Contradiction ≥ 0.7 gives REVIEW. | C `test_verifier_boundaries_and_restoration_budget` |
| Trim budgets | `trim_head_chars` 0, or a block within 200 chars of the head, keeps the block whole. Otherwise the head is a byte-exact prefix no longer than the budget. CRLF tables and logs keep their own line endings. | C `test_trim_budget_edges`, `test_trimmed_crlf_table_keeps_its_bytes`, `test_trimmed_crlf_logs_keep_their_bytes` |
| Block bigger than `max_block_chars` | Split at line boundaries, never lost. | C `test_single_block_bigger_than_the_block_budget_is_split_not_lost` |
| `preserve_tail_blocks` / `protect_prefix_chars` larger than the input | Everything kept. | C `test_preserve_tail_and_prefix_larger_than_the_input_keep_everything` |
| `specialist_drop_fraction` 0, or out of [0, 1) | 0 drops nothing. Out of range is rejected. | C `test_protected_blocks_survive_any_specialist_budget`, `test_drop_fraction_bounds_are_validated` |
| Marker or trim note followed by a block with no gap (a fence right after a paragraph) | The replacement keeps the replaced block's own line ending, so the next block starts on its own line and paragraph boundaries survive. | C `test_marker_never_glues_onto_a_following_code_fence`, `test_trim_note_never_glues_onto_a_following_code_fence` |

The synthetic judge benchmark carries five of these as transcript cases
(`extra_edge_cases` in [`run_judge_bench.py`](../benchmarks/run_judge_bench.py)), reported in
their own section; `--check` requires rules-lossless to keep all of them and v3-blocks to keep
the `pt_en_mixed` needle.
