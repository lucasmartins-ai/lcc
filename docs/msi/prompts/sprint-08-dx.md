# SPRINT 8 — Developer Experience (usável em 5 minutos)

## Gate
Requer: `SPRINT_7_DONE.md` = PASS. O sistema precisa existir antes de ser polido —
se APIs mudaram desde o sprint 2, congelar primeiro, polir depois.

## Objetivo
`pip install` → primeira compilação bem-sucedida em 5 minutos, sem entender os
internos. Hipótese: defaults sensatos + 1 quickstart funcional eliminam 80% do
atrito sem esconder poder dos avançados (opcionais).

## IN scope
- Polir: CLI (mensagens de erro acionáveis), Python API mínima
  (`compile(task, context) → context/receipt/sufficiency`), `inspect/explain/diff/bench`,
  exemplos executáveis, quickstart, logging sensato.
- Garantia: núcleo determinístico sem serviço externo oculto (teste prova offline).
- Teste de instalação limpa (venv fresh) + quickstart cronometrado.

## OUT scope
Nenhum comando novo "atraente" sem workflow real; nenhum breaking change sem
CHANGELOG + migração de 3 linhas; nenhum wizard interativo; nenhuma telemetria.

## Tarefas
1. Auditar cada comando: roda sem key? erro sem key é acionável? documentar a matriz.
2. Escrever `docs/QUICKSTART_MSI.md` (ou estender o existente — 1 lugar) e TESTÁ-LO
   de verdade num venv limpo, cronometrando.
3. Exemplos em `examples/` que rodam via `pytest --examples` ou 1 script (todos verdes).
4. Erros: cada falha comum (sem key, arquivo ausente, IR inválida) com mensagem que
   diz o próximo passo.

## Testes
- Instalação limpa: `pip install -e .` em venv fresh + quickstart end-to-end verde.
- Offline: núcleo determinístico com rede bloqueada (reuso de
  `tests/test_deterministic_boundary.py`, estendido ao novo código).
- Exemplos: todos executados em CI-local (script único), 100% verdes.
- Suite completa verde + ruff/mypy.

## Docs
Quickstart, matriz offline×comando, API reference mínima, CHANGELOG.

## Benchmark
Tempo até primeira compilação (cronometrado, N=1 honesto — é DX, não estatística);
tabela de comandos × offline/online/key.

## Correção
Exemplo quebrado → corrigir ou deletar (exemplo quebrado em repo público = slop).
Erro confuso → reescrever a mensagem, não a doc. Quickstart >5min → cortar escopo,
não acelerar o relóggio. 3 tentativas → BLOCKED.

## Acceptance criteria
- [ ] Fresh-venv install + quickstart verde em ≤5 min (evidência: log com timestamps).
- [ ] 100% dos exemplos executáveis e verdes.
- [ ] Núcleo determinístico prova offline (teste com rede bloqueada).
- [ ] Zero comandos sem workflow real documentado.
- [ ] `SPRINT_8_DONE.md` em PASS.
