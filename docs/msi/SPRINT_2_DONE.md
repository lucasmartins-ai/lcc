# Sprint 2 — DONE (PASS)

> Current recertification (2026-10-03): the two historical full-suite failures
> below are absent from the audited current code. Python 3.11 and 3.12 each
> pass 823 tests with 5 documented skips; configured-package mypy passes on
> 95 files. This does not alter the historical gate exception. See
> [audit and evidence](../../research/msi-audit-2026-10-03.md).

- Commit: working tree (no commit/push/PR per protocol anti-slop rule and user instruction; HEAD `284f11f`)
- Gate: `SPRINT_1_DONE.md` = PASS; schemas at `/Users/Master/msi-repos/minimum-sufficient-inference/spec/` readable; `src/lcc/relevance/{blocks,decisions,graph,sufficiency}.py` read before any edit.

## Acceptance

- [x] `pytest` verde no escopo do sprint + sem regressões → PASS with 1 documented pre-existing exception. `python3 -m pytest tests/ -p no:cacheprovider` → **714 passed, 6 skipped, 2 failed** (2026-10-02). The 2 failures are pre-existing and outside this diff, proven by construction: `tests/test_metadata.py` asserts installed-dist version vs `pyproject.toml` (staged 1.0.0 bump by another WIP; neither version source touched here) and `tests/test_docs.py::test_local_doc_links_resolve_to_existing_files` lists only links from `docs/msi/SPRINT_1_DONE.md` and `docs/msi/prompts/sprint-0*.md` (future-sprint refs + spec-repo-relative paths; zero entries from/to any file created or edited in this sprint — full missing-link list inspected). New: `tests/test_context_ir.py` **20/20 passed**. Previously-red `tests/test_cli_compact.py` (TypeError at baseline, see below) is green again.
- [x] ruff/mypy limpos nos arquivos tocados → PASS (with env note). `.venv/bin/ruff check` on `src/lcc/relevance/ir.py`, `compactor.py`, `cli.py`, `relevance/__init__.py`, `tests/test_context_ir.py` → clean. mypy with project config cannot run in this env for ANY file (numpy 2.x stubs need `python_version >= 3.12`, config pins 3.11; untouched `blocks.py` fails identically — evidence in Known limitations); with `--python-version 3.14 --ignore-missing-imports`, all touched files → `Success: no issues found`.
- [x] 3–5 golden IR fixtures congeladas e verificadas → PASS. 4 fixtures in `tests/fixtures/ir/` (`corpus-01..04.txt` + `ir-01..04.json`): re-emit byte-compares green, all 4 validate against `context-ir/0.1` (jsonschema 4.26.0). Corpus-04 carries QUALIFIES + SUPPORTS edges; restoration path covered by fake-Jev test (no network judge in CI).
- [x] `explain` cobre 100% dos drops nos corpora de teste → PASS. Every dropped unit in all 4 goldens has a non-empty `selection.rationale` and appears in `render_ir_explanation` output (asserted); same invariant asserted over 50 seeded property corpora.
- [x] Outputs do QUICKSTART byte-idênticos ao baseline → PASS (partial-substitution, documented). `optimize` prompt/report and `inspect` report: `cmp` identical before/after (`/tmp/msi2base/` vs `/tmp/msi2after/`). `compact`/`explain` have no pre-change baseline — the command was broken pre-change (TypeError, baseline exit 1, evidence below) — substituted with: two identical `compact` runs → `compacted.md` byte-identical (only `compilation_ms` wall-clock differs in report JSON, pre-existing timing field), and `git diff` review showing the mechanical scoring path untouched (additive seam only, gated on `emit_ir`).

## Testes

- `python3 -m pytest tests/test_context_ir.py -p no:cacheprovider` → **20 passed** (subsetness/partição, proveniência, bytes verbatim, necessity UNKNOWN, restored ⊆ original, determinismo, task_id determinístico, ausência de campos provider, negativa com campo extra rejeitada pelo schema, protected unit + propriedade 50 corpora, explain 100% drops + filtro `--only`, restauração via fake-Jev + validação no schema, `build_context_ir` sem grafo, CLI `--emit-ir`/`--ir`/`explain`, `emit_ir` default off).
- `python3 -m pytest tests/ -p no:cacheprovider` → 714 passed, 6 skipped, 2 failed (pré-existentes, acima).
- `python3 scripts/validate_examples.py` do spec repo não tocado (sprint 1 segue verde por construção; nenhum schema alterado).
- Comandos (todos offline, provider mechanical): `lcc compact --emit-ir ir.json` → exit 0, IR valida no schema; `lcc explain ir.json --only drop` → exit 0; `lcc inspect messy.txt --ir ir.json` → exit 0, tabela de resumo no stderr, JSON de inspeção inalterado.

## Benchmark

N/A para ganho (sprint de infra; sem claim). Custo medido, 1 corpus (`tests/fixtures/ir/corpus-01.txt`), N=20, provider mechanical, offline:

| métrica | sem IR | com IR |
|---|---|---|
| wall p50 (20 runs) | 2.2 ms | 2.0 ms (delta −0.1 ms, ruído) |
| wall min–max | 2.0–60.5 ms | 2.0–2.7 ms (outlier = init do tokenizador) |
| `compilation_ms` (report) | 1 | 1 |
| bytes: report vs IR | 5259 B | 4879 B (0.93x) |

Overhead da emissão indistinguível do ruído neste porte; IR 0.93x do report. Comando reprodutor: script inline em `/tmp` (não commitado) que alterna `emit_ir` False/True sobre o mesmo corpus — ver seção Testes para o corpus.

## Docs/ADRs

- Criados: `docs/lcc/context-ir.md` (emissão, leitura, garantias, tabela report-1.2 → IR v0.1, limites), `docs/adr/0017-context-ir-emission.md` + linha no `docs/adr/README.md`.
- Alterados: `CHANGELOG.md` (Added: emissão IR; Fixed: reparo Nimble abaixo), `src/lcc/cli.py`, `src/lcc/relevance/compactor.py`, `src/lcc/relevance/__init__.py`.
- Criados (código/testes): `src/lcc/relevance/ir.py`, `tests/test_context_ir.py`, `tests/fixtures/ir/` (8 arquivos).
- Todos os links `docs/*.md` adicionados resolvem (checados contra o padrão de `tests/test_docs.py`).

## Deliberately skipped

- `--task-id` / `--collected-at` flags na CLI: `task_id` deriva deterministicamente do objetivo e `collected_at` tem default fixo; flags reais entram quando um consumidor (planner, sprint 4) precisar linkar IR ↔ Task Contract.
- `transform: clean/dedupe` na proveniência: emissão lê o texto bruto de entrada, não a saída do pipeline; sempre `none`, documentado como limite.
- Docs `NIMBLE.md` + scorer Nimble real: o reparo abaixo entrega só o fallback honesto documentado; scorer é trabalho do dono do WIP.
- Commit local: não commitado de propósito — a árvore contém staged work alheio (`pyproject.toml`, `README.md`, chatgpt bits); commitar varreria trabalho de outro WIP. Working tree, sem push/PR (protocolo + instrução do usuário).

## Known limitations

- 2 testes vermelhos pré-existentes e fora de escopo (`test_metadata` version bump staged; `test_docs` links das docs dos sprints 0/1) — sem regressão deste sprint, evidência acima.
- mypy com o config do projeto não roda neste env para nenhum arquivo (stubs numpy × pin 3.11); limpo com flags de contorno nos arquivos tocados.
- `provider="nimble"` cai para mechanical (`nimble+mechanical_fallback`, degraded) até o scorer existir — reparo de um WIP alheio que quebrava 100% das invocações `lcc compact` (baseline: `TypeError: ... unexpected keyword argument 'nimble_model'`, `tests/test_cli_compact.py` vermelho antes de qualquer edição minha; verde depois). Mudança mínima, comportamento dos providers existentes inalterado.
- Restauração end-to-end com juiz real não exercitada em CI (sem rede); coberta via fake-Jev + mapeamento estrutural; goldens mostram `budget: 8` com `restored: []`.
- `compilation_ms`/`latency_ms` continuam wall-clock (não-determinísticos); IR não carrega timing — determinismo do IR bytes não é afetado.

## Next

Sprint 3 implementa sufficiency/restoration como estágio de primeira classe sobre a IR congelada aqui.
