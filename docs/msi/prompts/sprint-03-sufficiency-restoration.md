# SPRINT 3 — Sufficiency + Restoration Loop (além de relevância)

## Gate
Requer: `SPRINT_2_DONE.md` = PASS + emissão IR funcionando.
Releia `src/lcc/relevance/sufficiency.py` e `verifier.py` (já existe o pipeline
SELECT → SAFETY → RESTORATION → VALIDATION → VERIFY opt-in; este sprint o mede e endurece).

## Objetivo
Provar que o loop select→check→restore→recheck preserva outcome. Hipótese: cada camada
(determinística, dependência, juiz leve) remove uma classe distinta de false drops;
restauração fica visível no receipt e falha default preserva informação.

## IN scope
- Endurecer o loop existente: orçamentos explícitos por camada, contadores
  (`blocks_restored`, `sufficiency_checks`, `sufficiency_failures`) já no report.
- Experimento separado por camada: desligar cada uma e medir (ablation de mecanismo,
  não de conteúdo — a de conteúdo é o sprint 6).
- `docs/lcc/sufficiency.md` + `docs/lcc/restoration.md` + ADR.

## OUT scope
Nenhum verificador novo obrigatório; nenhum LLM em camada determinística;
nenhuma mudança de threshold sem evidência; nenhum loop de re-verificação
(verifier continua single-shot — sem loop, por desenho).

## Tarefas
1. Auditar o caminho atual contra adversarial: contraditório, stale, duplicado,
   dependência oculta, evidência única, proveniência malformada. Registrar cada classe
   como PASS/FAIL em matriz (`docs/lcc/sufficiency.md`).
2. Medir por camada (on/off) nos corpora `benchmarks/research/`: recall por categoria,
   `false_drop_rate`, `restoration_rate`, `blocks_restored`.
3. Fail-closed: forçar falha de cada camada (exceção injetada) e provar que o resultado
   preserva contexto (`degraded` + keep), nunca drop silencioso.
4. Tornar restauração auditável: cada restore com motivo + origem no report/IR.

## Testes
- `tests/test_sufficiency.py` (novos): severed-link → `sufficient=False`; proteção
  burlada → restore; falha injetada → keep (fail-closed).
- Adversariais: 1 teste por classe da matriz acima (mínimo 5).
- Suite completa verde + ruff/mypy.

## Docs
`sufficiency.md`, `restoration.md`, ADR (orçamento por camada, single-shot rationale),
matriz adversarial com resultados reais (verdes e vermelhos publicados).

## Benchmark
Tabela por camada: recall/categoria, false drops, restores, `compilation_ms`.
Critério de KEEP de cada camada: remove ≥1 classe real de false drop OU é deletada
(resultado negativo = deletar, documentado — sem apego).

## Correção
Camada que não prova valor → remover, não "melhorar no escuro". Falha fail-closed →
bug crítico, corrige antes de qualquer outra coisa. 3 tentativas → BLOCKED.

## Acceptance criteria
- [ ] Restauração visível no report/IR com motivo por bloco.
- [ ] `false_drop_rate` medido por camada, publicado com N e corpus.
- [ ] Falha injetada em cada camada → contexto preservado (teste prova).
- [ ] Matriz adversarial publicada (PASS e FAIL, sem cherry-pick).
- [ ] `SPRINT_3_DONE.md` em PASS.
