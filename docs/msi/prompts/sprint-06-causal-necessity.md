# SPRINT 6 — Causal Context Necessity (o possível moat técnico)

## Gate
Requer: `SPRINT_5_DONE.md` = PASS. Este sprint é pesquisa: código mínimo, rigor máximo.

## Objetivo
Responder "este bloco afetou o outcome?" em vez de "parece relevante?".
Hipótese: `P(degradação | remover unidade)` separa NECESSARY de REDUNDANT onde
relevância semântica não separa.

## IN scope
- Harness de replay + ablação: baseline congelado → remove `c_i` (e pares
  selecionados) → replay → delta de outcome por invariantes (testes passam, rubrica,
  decisão estruturada, citações resolvem, fatos presentes, trajetória válida,
  safety, equivalência semântica).
- Labels: `NECESSARY UNNECESSARY CONDITIONALLY_NECESSARY REDUNDANT PROTECTED UNKNOWN`.
- Registro por experimento: seed, baseline hash, modelo/versão, avaliador, delta.
- `research/causal-necessity.md` + ADR.

## OUT scope
Nenhum treino de modelo; nenhum label usado em produção sem validação (labels são
pesquisa até o sprint 7 dizer o contrário); nenhum N grande sem piloto primeiro
(custo!) — piloto N≤30, rotulado PILOT.

## Tarefas
1. Congelar 1 baseline pequeno e determinístico (fixture replayable, sem rede).
2. Implementar o harness (`benchmarks/ablation/` ou `research/` — 1 lugar, sem duplicar
   `benchmarks/research/`): remove → replay → avalia → persiste delta.
3. Rodar o piloto: cada unidade × baseline, registrar label + invariante que decidiu.
4. Publicar distribuição de labels + 3 exemplos comentados (1 NECESSARY, 1 REDUNDANT,
   1 CONDITIONALLY_NECESSARY com a condição nomeada).

## Testes
- Self-tests do harness: fixture trivial onde a unidade gold é NECESSARY e o ruído é
  UNNECESSARY (se o harness não acerta o trivial, nada mais vale).
- Reprodutibilidade: 2 runs do piloto → mesmos labels (hashes comparados).
- Suite completa verde.

## Docs
`research/causal-necessity.md` (método, invariantes, limites, custo por experimento),
ADR, exemplos comentados.

## Benchmark
O piloto É o benchmark: tabela unidade → delta por invariante → label; custo total
(tokens/tempo) publicado — ablação custa caro, dizer quanto custou.

## Correção
Harness não-reprodutível → bug bloqueante (seed/versão faltando). Label instável entre
runs → `UNKNOWN`, nunca forçar categoria. Resultado negativo (relevância ≈ necessidade
no piloto) é publicável como tal — sem HARKing. 3 tentativas → BLOCKED.

## Acceptance criteria
- [ ] Baseline congelado + hash registrado.
- [ ] Self-test trivial verde; piloto N≤30 com 2 runs idênticas.
- [ ] Labels com invariante-decisora registrada por unidade.
- [ ] Custo do piloto publicado; limitações escritas.
- [ ] `SPRINT_6_DONE.md` em PASS.
