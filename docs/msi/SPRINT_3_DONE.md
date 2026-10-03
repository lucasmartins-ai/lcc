# Sprint 3 — DONE (PASS)

- Commit: working tree (no commit/push/PR per protocol anti-slop rule and user instruction; HEAD `284f11f`)
- Gate: `SPRINT_2_DONE.md` = PASS; `src/lcc/relevance/sufficiency.py` + `verifier.py` re-read (SELECT → SAFETY → RESTORATION → VALIDATION → VERIFY opt-in single-shot, confirmed before editing)

## Acceptance

- [x] Restauração visível no report/IR com motivo por bloco → PASS. Restored decisions carry `reason` = `semantic_sufficiency_restoration` (layer 2) or `semantic_verifier_fail_restoration` (layer 3) + `relationships[]`; IR mirrors it in `selection.rationale[id]` + `restoration.restored`. Evidence: `tests/test_sufficiency.py::test_bypassed_protection_restores_with_per_block_reason` (report reason == IR rationale == restored list, 18/18 file green).
- [x] `false_drop_rate` medido por camada, publicado com N e corpus → PASS. N = 30 curated adversarial cases (53 required blocks), pressure 1, offline, 2026-10-02. Lexical path: all-on 30/30 fdr 0.000; `--no-deterministic-protection` 27/30 (fails: dependency_causal, quoted_instruction, multilingual). Judge-error path (fake Jev keeps 1 block): all-on 22/30 fdr 0.151 with 127 restores vs `--no-sufficiency` 3/30 fdr 0.660 with 0 restores. Verifier path: targeted fixture restores 2 more past the structural budget (3 ≤ 1+4), REVIEW. Tables in `docs/lcc/sufficiency.md`.
- [x] Falha injetada em cada camada → contexto preservado → PASS. Graph crash → `relationship_analysis_failed`, output produced; `verify_sufficiency` crash (first check and re-check) → typed warning + `sufficiency_failures` + IR `sufficient: false` + REVIEW via E2; verifier client crash → REVIEW (`verifier_unavailable_fail_closed`); verifier code crash → `semantic_verifier_failed` + REVIEW (new 3-line hardening). Evidence: 4 tests in `tests/test_sufficiency.py` (graph, sufficiency, verifier × 2 shapes), all green.
- [x] Matriz adversarial publicada (PASS e FAIL, sem cherry-pick) → PASS. 6/6 classes PASS (contraditório, stale, duplicado, dependência oculta, evidência única, proveniência) in `docs/lcc/sufficiency.md`; red rows published alongside (harsh-judge budget-exhaustion losses, no-det/no-suff FAILs).
- [x] `SPRINT_3_DONE.md` em PASS (this file, `docs/msi/`).

## Testes

- `python3 -m pytest tests/test_sufficiency.py -p no:cacheprovider` → **18 passed** (7 pre-existing + 11 new: severed-link, bypassed-protection+IR-audit, 4 injected-failure, 6 adversarial).
- `python3 -m pytest tests/ -p no:cacheprovider` → **725 passed, 6 skipped, 2 failed** — both failures pre-existing and outside this diff (proven as in sprint 2: `test_metadata` staged-version bump vs stale source-tree fallback; `test_docs` only `SPRINT_1_DONE.md → theory.md, terminology.md` spec-repo-relative links; zero entries from/to any file created or edited here).
- `.venv/bin/ruff check` on `compactor.py`, `cli.py`, `test_sufficiency.py` → clean. mypy (`--python-version 3.14 --ignore-missing-imports`, same workaround as sprint 2) on touched src files → `Success: no issues found`.
- CLI: `lcc compact … --verifier-max-restorations 0` → exit 0, report renders; `-1` → `Error: --verifier-max-restorations must be >= 0.`

## Benchmark

No gain claim (sprint de endurecimento; qualidade + custo juntos, nunca só compressão):

| caminho | config | pass | lost_req/53 | fdr | restored |
|---|---|---|---|---|---|
| lexical (mechanical) | all on | 30/30 | 0 | 0.000 | 0 |
| lexical | `--no-deterministic-protection` | 27/30 | 3 cases | — | 0 |
| lexical | `--no-sufficiency` | 30/30 | 0 | 0.000 | 0 |
| judge-error (fake Jev) | all on | 22/30 | 8 | 0.151 | 127 |
| judge-error | `--no-sufficiency` | 3/30 | 35 | 0.660 | 0 |

Custo: wall total do sweep lexical 170 ms (all-on) vs 85–102 ms (camadas off) em 30 corpora — mesma ordem de grandeza, sem claim. Evidência: CURRENT. Dados: CURATED (`benchmarks/research/adversarial_cases.py`, 30 cases, pressure 1). KEEP por camada: determinística remove 3 classes reais; estrutural corta fdr 0.660 → 0.151; verificador restaura além do orçamento estrutural + sinaliza REVIEW. Nenhuma camada deletada.

## Docs/ADRs

- Criados: `docs/lcc/sufficiency.md` (camadas, orçamentos, fail-closed map, ablation, matriz), `docs/lcc/restoration.md` (trilha de auditoria, orçamentos), `docs/adr/0018-sufficiency-restoration-budgets.md` + linha no `docs/adr/README.md`.
- Alterados: `src/lcc/relevance/compactor.py` (fail-closed em `verify_sufficiency` ×2 + crash do verificador → REVIEW), `src/lcc/cli.py` (`--verifier-max-restorations` 4, validação, repasse, tool-calls inapplicable), `tests/test_sufficiency.py` (+11 testes), `CHANGELOG.md` (Unreleased/Added: ADR 0018).

## Deliberately skipped

- `--task-id`/`--collected-at` flags, `transform: clean/dedupe`, scorer Nimble real: herdados do sprint 2, seguem fora de escopo.
- Loop de re-verificação: proibido pelo sprint (verifier single-shot por desenho, ADR 0018 forecloses).
- Re-check `verdict2` com restauração adicional: mesma decisão — re-check é observabilidade, nunca nova restauração (sem loop).
- Commit local: não commitado de propósito — árvore contém staged work alheio (pyproject, chatgpt bits); working tree, sem push/PR (protocolo + instrução do usuário).

## Known limitations

- Sob judge-error restam 8/53 blocos perdidos (exaustão do orçamento 8/pass, ex: cadeia VAT de 4 blocos) — todos com `needs_review`; teto documentado, não falha silenciosa.
- Com judge no caminho Jev, `--no-deterministic-protection` ≡ `--no-sufficiency` (proteção determinística só guarda scoring lexical) — documentado na ablation.
- `safety.py::decide_assessment` segue modelo standalone, não wired no compactor — sem mudança neste sprint (camadas medidas são as 3 do pipeline real).
- mypy com o config do projeto segue não-rodável neste env (stubs numpy × pin 3.11, pré-existente); limpo com flags de contorno.

## Next

Sprint 4 implementa o inference planner sobre a IR e a restauração auditável congeladas aqui.
