# SPRINT 4 — Inference Planner (rotear sem acoplar a provider)

## Gate
Requer: `SPRINT_3_DONE.md` = PASS. Releia `src/lcc/router/{policy,features,schemas}.py`
e a gate do triage-benchmark (`scripts/integrate_agy_results.py:150-175`).

## Objetivo
Roteamento auditável e plugável a partir de (Task Contract, Context IR, budget, risco).
Hipótese: uma política determinística baseline já roteia corretamente os casos de
baixo risco; motores auxiliares só entram se provarem ganho pareado.

## IN scope
- Interface de engine plugável: `deterministic | jev-adapter | rules` (small-local-model
  como stub documentado, não implementado — YAGNI até haver evidência).
- Baseline determinístico portando a semântica de `choose_route` + gate de triage
  `(decision, confidence, escalate_risk)` como adapter Jev (limiares herdados como
  default, não como verdade).
- Decisão auditável: cada plano carrega motivos + política versionada.
- `docs/msi/inference-planning.md` (no spec repo ou LCC — escolher 1, sem duplicar) + ADR.

## OUT scope
Nenhuma chamada real a provider dentro do planner (planeja, não executa); nenhum
acoplamento LCC↔Jev/OpenAI; nenhuma "otimização" de limiar sem experimento;
nenhum engine novo além dos 3 citados.

## Tarefas
1. Definir o tipo `InferencePlan` em código a partir do schema v0.1 (um módulo, ex:
   `src/lcc/router/plan.py`), com `fallbacks` e `escalation_policy` explícitos.
2. Implementar baseline determinístico + adapter Jev atrás da mesma interface.
3. Golden decisions: congelar 10–15 (features → plano) cobrindo cada rota e cada fallback.
4. Documentar quando NÃO rotear para barato (risco alto/unknown → fail-closed).

## Testes
- `tests/test_inference_plan.py`: goldens, policy-version no output, engine trocável
  (mock engine com mesma interface passa nos mesmos goldens de contrato).
- Invariante: plano barato nunca emitido com `risk_level high|unknown` sem escalonamento.
- Suite completa verde + ruff/mypy.

## Docs
Planning doc + ADR (por que determinístico primeiro; alternativas consideradas;
reversibilidade) + exemplos de plano por perfil de risco.

## Benchmark
Distribuição de rotas + economia projetada nos fixtures do sprint 1 (N=5, rotulado
PILOT — sem generalização). Comparar motores SOMENTE baseline-vs-Jev-adapter, mesma
métrica, mesmo N. Tabela pareada ou nada.

## Correção
Adapter que não supera o baseline em qualidade pareada → fica como adapter opcional,
nunca default. Divergência de goldens → investigar, não atualizar golden sem causa raiz
escrita. 3 tentativas → BLOCKED.

## Acceptance criteria
- [ ] Engine plugável com baseline determinístico + 1 adapter real.
- [ ] 10–15 golden decisions verdes e estáveis.
- [ ] Invariante fail-closed (risco alto→nunca barato silencioso) testada.
- [ ] Decisão 100% auditável (motivo + policy version no output).
- [ ] `SPRINT_4_DONE.md` em PASS.
