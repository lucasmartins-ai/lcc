# SPRINT 5 — Verification + Escalation (fechar o loop)

## Gate
Requer: `SPRINT_4_DONE.md` = PASS. Releia `services/agent-api/.../evals/checks.py`,
`ci_gate.py` (agenttrace) e `src/lcc/relevance/verifier.py` (tri-state + single-shot).

## Objetivo
Cadeia execute→verify→restore→retry→escalate onde falha jamais é silenciosa.
Hipótese: verificação em camadas (schema/assertions/citação/testes/semântica/política)
detecta classes complementares de falha, cada escalonamento carrega motivo, retries
são limitados e o receipt contém a cadeia inteira.

## IN scope
- Extrair o *protocolo* AgentTrace (shape dos checks, gate de thresholds, taxonomia de
  motivos) para um módulo LCC próprio — sem dependência do produto.
- Camadas: schema assertions, task assertions, citation checks, test results,
  semantic (opt-in, single-shot, herdando `verifier.py`), policy checks.
- Ações limitadas: `PASS RESTORE_CONTEXT RETRY INCREASE_REASONING SWITCH_MODEL
  ADD_TOOL ESCALATE ABORT`, retries/escalonamentos limitados e contados.
- `verification.md` + `escalation.md` (em `docs/msi/`, a criar neste sprint) + ADR + Receipt v0 emitido.

## OUT scope
Nenhuma dependência de AgentTrace instalado; nenhum juiz LLM obrigatório no caminho
default; nenhum retry ilimitado; nenhum auto-reparo silencioso de conteúdo.

## Tarefas
1. Implementar o runner de verificação em camadas com resultado tri-state
   (PASS/REVIEW/FAIL) e `recommended_action` por falha.
2. Implementar a máquina de escalonamento: restore (orçamento próprio) → retry
   (≤max_retries) → troca de plano → ESCALATE/ABORT, cada transição com evento de
   decisão (WHY) registrado no receipt.
3. Injeção de falhas: para cada camada, provar que a falha correspondente é capturada
   e que a ação correta é emitida (teste por camada).
4. Emitir Inference Receipt v0 por execução (campos do spec; versões de tudo).

## Testes
- 1 teste de injeção por camada (mínimo 6) + teste de limite (retry além do máximo → ESCALATE).
- Golden receipts: 3 execuções (PASS direto, PASS-via-restore, ESCALATE) congeladas.
- Suite completa verde + ruff/mypy.

## Docs
verification.md, escalation.md, ADR, exemplo de receipt comentado.

## Benchmark
Distribuição PASS/REVIEW/FAIL + contadores (restore/retry/escalate) nos corpora de
pesquisa; latência adicionada pela verificação (overhead explícito, não escondido).

## Correção
Camada que gera REVIEW em >50% sem FAIL correspondente → recalibrar ou rebaixar para
advisory (com evidência). Transição sem motivo registrado = bug bloqueante.
3 tentativas → BLOCKED.

## Acceptance criteria
- [ ] Falha de verificação jamais silenciosa (teste por camada prova).
- [ ] Todo escalonamento tem motivo; retries limitados e contados.
- [ ] Receipt contém a cadeia de decisão completa (goldens congelados).
- [ ] Overhead de verificação publicado.
- [ ] `SPRINT_5_DONE.md` em PASS.
