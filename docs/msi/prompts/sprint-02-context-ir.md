# SPRINT 2 — LCC Context IR (compilar de verdade, sem quebrar o CLI)

## Gate
Requer: `SPRINT_1_DONE.md` = PASS + schemas do spec repo acessíveis.
Leia `src/lcc/relevance/{blocks,decisions,graph,sufficiency}.py` antes de tocar qualquer código.

## Objetivo
LCC passa a emitir Context IR versionada e determinística. Hipótese: toda decisão atual
(score/seleção/restauração) é expressável como IR sem mudar comportamento do CLI.

## IN scope
- Novo módulo de emissão IR (ex: `src/lcc/relevance/ir.py` — um arquivo; reuse `graph.py`,
  `decisions.py`, `sufficiency.py`, não os duplique).
- Serialização determinística (chaves ordenadas, sem timestamps não-semeados no corpo).
- `lcc inspect` exibe resumo IR; `lcc explain` lê IR.
- `docs/lcc/context-ir.md` + ADR (mapeamento report-1.2 → IR v0.1, o que mudou e por quê).

## OUT scope
Nenhuma mudança de scoring/threshold; nenhum planner; nenhuma verificação semântica nova;
nenhuma quebra de CLI (flags e outputs existentes intactos).

## Tarefas
1. Implementar emissão IR: units (id, bytes verbatim, source, provenance), relationships
   (reuso de `graph.py`), selection (kept/trimmed/dropped + policy id), sufficiency,
   restoration. `necessity` default `UNKNOWN`.
2. Garantir: toda unidade selecionada carrega provenance; toda unidade descartada é
   explicável (`lcc explain` cobre 100% dos drops de 3 corpora de teste).
3. Proteção: conteúdo `protected` jamais some silenciosamente — teste dedicado.
4. Congelar 3–5 reports existentes como fixtures IR douradas (`tests/fixtures/ir/`).

## Testes
- Novos: `tests/test_context_ir.py` — subsetness (seleção ⊆ original), provenance
  sobrevive, restaurado ∈ original, mesmo input determinístico → mesmo bytes.
- Proteção: `protected never silently dropped` (unit + property).
- Regressão: suite completa `pytest` verde + `ruff` + `mypy` nos arquivos tocados.
- Compat: rodar os comandos do QUICKSTART antes/depois; diff de outputs deve ser vazio
  (anexar evidência).

## Docs
`docs/lcc/context-ir.md` (schema, garantias, limites) + ADR + CHANGELOG entry.

## Benchmark
Medir overhead: `compilation_ms` com/sem IR em `benchmarks/research/` (1 corpus, N=20);
tamanho do IR vs report. Tabela no DONE. Sem claim de ganho — é custo de infraestrutura.

## Correção
Teste vermelho → corrija o código, nunca o teste (salvo teste errado, com justificativa
escrita de 1 linha). Quebra de CLI = revert da mudança, não ajuste do teste. 3 tentativas → BLOCKED.

## Acceptance criteria
- [ ] `pytest` 100% verde (novo + existente), ruff/mypy limpos.
- [ ] 3–5 golden IR fixtures congeladas e verificadas.
- [ ] `explain` cobre 100% dos drops nos corpora de teste.
- [ ] Outputs do QUICKSTART byte-idênticos ao baseline.
- [ ] `SPRINT_2_DONE.md` em PASS.
