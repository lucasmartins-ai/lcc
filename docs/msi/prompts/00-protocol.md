# Protocolo de execução — ler antes de QUALQUER sprint

Este arquivo rege todos os prompts `sprint-*.md` deste diretório.

## Como o usuário opera

O usuário dirá apenas: **"vá para o próximo sprint"** (ou "execute o sprint N").
Você descobre N = (maior sprint com `SPRINT_N_DONE.md` presente) + 1. Sprint 0 já está pronto
(docs em `docs/msi/01–07`). Comece pelo sprint 1.

## Ordem obrigatória de cada sprint

1. Leia este protocolo + `docs/msi/00-repo-map.md` + `docs/msi/prompts/sprint-N-*.md` por inteiro.
2. Leia os pré-requisitos listados no gate do sprint. Se qualquer artefato do gate
   estiver ausente ou o `SPRINT_{N-1}_DONE.md` anterior registrar FAIL, **PARE** e reporte.
   Nunca inicie um sprint com o gate anterior vermelho.
3. Execute as tarefas em ordem. Não pule etapas de teste/correção.
4. Rode o loop de correção até tudo passar OU até 3 tentativas sem progresso —
   então pare, registre o bloqueio em `SPRINT_N_DONE.md` (status BLOCKED) e reporte.
5. Só escreva `SPRINT_N_DONE.md` com status PASS quando **todos** os acceptance
   criteria estiverem verificados com evidência (comando + output, não afirmação).
6. Nunca avance para o sprint seguinte sem o DONE do atual em PASS.

## Regras anti-slop (valem para todos os sprints)

- Proibido: linguagem de marketing, superlativos, claims sem medição, percentuais sem
  N/dataset/config, "SOTA", "novel" sem prior-art, código morto, abstração de uso único,
  dependência nova sem justificativa escrita, comando CLI sem workflow real.
- Toda afirmação empírica carrega: dataset + N + config + commit + comando de reprodução.
  Classifique evidência: CURRENT / EXPERIMENTAL / HISTORICAL / BENCHMARK.
  Classifique dados: REAL / REAL-ANONYMIZED / REPLAYED / CURATED / SYNTHETIC / HYBRID.
  Sintético jamais é descrito como produção.
- YAGNI + ponytail full: menor diff que responde à hipótese; o que for cortado vai para
  `SPRINT_N_DONE.md` em "Deliberately skipped".
- Padrão de tese: redução sem qualidade pareada = falha. Sempre reporte qualidade +
  custo juntos; nunca apenas compressão.
- Fail-closed: incerteza → preserva; falha de verificação → restaura/retry/escala.
  Nada é silenciosamente descartado.
- Não faça push, não crie PR, não arquive repositório, não publique nada externo.
  Mudanças ficam no working tree; reporte ao final.

## `SPRINT_N_DONE.md` (obrigatório ao final de cada sprint)

```markdown
# Sprint N — DONE (PASS | FAIL | BLOCKED)
- Commit: <sha>
- Acceptance: cada critério → PASS/FAIL + evidência (comando/output/arquivo:linha)
- Testes: <comando> → <resultado, ex: 312 passed>
- Benchmark: tabela de métricas ou "N/A (sprint sem medição, justificativa)"
- Docs/ADRs: arquivos criados/alterados
- Deliberately skipped: o que foi cortado e por quê
- Known limitations: o que continua aberto
- Next: frase única de handoff para o sprint N+1
```
