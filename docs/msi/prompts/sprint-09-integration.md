# SPRINT 9 — Real-World Integration (lookaorchestrator como teste, não vitrine)

## Gate
Requer: `SPRINT_8_DONE.md` = PASS. Ler `docs/msi/04-repository-boundaries.md`
(testbed, sem acoplamento) antes de qualquer integração.

## Objetivo
Medir MSI em tráfego realista sem cherry-pick. Hipótese: ganhos do bench se mantêm
(± tolerância declarada) em traces de produção; falhas viram ativos de pesquisa.

## IN scope
- Coletar traces REPLAYED ou REAL-ANONYMIZED (anonimização documentada; se sem acesso
  ao repo privado, construir track REPLAYED a partir de sessões locais — declarar).
- Medir: token reduction, cost, latency, task success, restores, escalations,
  frontier calls avoided, verification failures — pareado contra baseline full-context.
- Publicar falhas: cada regressão vira caso com causa raiz (ou `UNKNOWN` declarado).
- Integração SOMENTE via interfaces versionadas; zero lógica privada no spec.

## OUT scope
Nenhum acoplamento do spec a lógica LookADev; nenhum dado real sem anonimização;
nenhum "case de sucesso" sem o N total ao lado; nenhuma mudança de threshold tunada
nos dados de integração (isso é contaminação — R2).

## Tarefas
1. Declarar a fonte de traces (classe de dataset + N + janela de coleta + anonimização).
2. Rodar MSI vs baseline nos traces; coletar todas as métricas do §11 do master prompt.
3. Investigar TODAS as regressões (target: 100% com causa raiz ou `UNKNOWN` + próximo
   experimento que a esclareceria).
4. Devolver ao bench: 3+ casos de falha viram fixtures permanentes (replayable).

## Testes
- Replay determinístico: mesmo trace 2× → mesmo receipt-hash (ou delta explicado).
- Teste de anonimização: grep de segredos/PII nos traces publicados (vazio, com evidência).
- Suite completa verde.

## Docs
`research/real-world-integration.md` (fonte, método, números, falhas, limites) +
casos de falha como fixtures documentadas.

## Benchmark
Tabela pareada MSI vs baseline em todas as métricas + Pareto atualizado; N total e
taxa de falha em destaque (não no rodapé).

## Correção
Regressão ignorada = FAIL do sprint. Acesso ao privado indisponível → track REPLAYED
local, declarado, sem fingir que é produção. Vazamento de segredo → apagar, rodar de
novo, registrar o incidente no DONE. 3 tentativas → BLOCKED.

## Acceptance criteria
- [ ] Fonte de traces declarada (classe + N + anonimização).
- [ ] Métricas pareadas completas, sem cherry-pick (falhas publicadas).
- [ ] 100% das regressões com causa raiz ou `UNKNOWN` + próximo experimento.
- [ ] ≥3 casos de falha viraram fixtures permanentes; replay determinístico provado.
- [ ] `SPRINT_9_DONE.md` em PASS.
