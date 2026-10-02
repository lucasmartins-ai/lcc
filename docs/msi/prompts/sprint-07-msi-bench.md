# SPRINT 7 — MSI-Bench (benchmark sério, sem vaidade)

## Gate
Requer: `SPRINT_6_DONE.md` = PASS. Releia `research/methodology.md` do spec repo e
`benchmarks/research/RESEARCH_STATUS.md` (separação CURRENT/EXPERIMENTAL/HISTORICAL/BENCHMARK).

## Objetivo
Responder "com quantos recursos a menos o outcome se preserva?". Hipótese: LCC+routing+
verificação domina Pareto (qualidade×custo×latência) contra full-context em ≥1 categoria,
com qualidade pareada — e onde não dominar, publicar do mesmo jeito.

## IN scope
- Categorias iniciais: coding, research, structured decision, long-context agent,
  tool-heavy agent, document reasoning (1–2 tasks congeladas por categoria basta no v0).
- Braços comparados: full-context/frontier; LCC-only; routing-only; LCC+routing;
  LCC+routing+verification; MSI closed loop.
- Métricas obrigatórias: task success, cost, latency, input/output tokens, retained,
  frontier calls, verification calls, restores, retries, escalations,
  false_deescalation, unsafe_optimization + derivadas (success/$, success/s, retained@
  matched-success, frontier-avoided@matched-success) + Pareto quality×cost/latency/context.
- `research/benchmark-methodology.md`: origem, coleta, freeze date, contaminação,
  limitações, rubrica, incerteza estatística.

## OUT scope
Nenhum headline de compressão sem qualidade pareada; nenhum sintético rotulado como
real; nenhuma categoria nova além das 6 sem fechar as 6; nenhum tuning no test set
(freeze antes de rodar).

## Tarefas
1. Congelar datasets por categoria com classificação + freeze date + rubrica.
2. Implementar o runner (`benchmarks/msi-bench/`) com seeds, versões e receipt por run.
3. Rodar a matriz braços×categorias; computar Pareto e intervalos de incerteza
   (bootstrap simples; N pequeno → intervalo largo declarado, sem vergonha).
4. Escrever o relatório com falhas junto dos sucessos.

## Testes
- Reprodutibilidade: re-run de 1 categoria → mesmos resultados (ou delta explicado).
- Validação do runner: fixture sintética trivial onde o braço full-context DEVE vencer
  (sanity contra bug de medição invertida).
- Suite completa verde.

## Docs
benchmark-methodology.md, relatório `benchmarks/msi-bench/REPORT.md`, datasets
classificados, instruções de reprodução de 1 comando.

## Benchmark
Este sprint É o benchmark. Exigir: qualidade pareada em toda comparação; Pareto
publicado; incerteza publicada; falhas publicadas.

## Correção
Métrica que esconde degradação → reescrever a métrica, não o número. Contaminação
detectada → descartar a categoria e registrar. N insuficiente → declarar PILOT, não
"resultado". 3 tentativas → BLOCKED.

## Acceptance criteria
- [ ] Matriz braços×categorias completa com qualidade pareada.
- [ ] Pareto quality×cost/latency/context publicado.
- [ ] Metodologia + proveniência + limitações + incerteza documentadas.
- [ ] Falhas publicadas ao lado dos sucessos; reprodução em 1 comando funciona.
- [ ] `SPRINT_7_DONE.md` em PASS.
