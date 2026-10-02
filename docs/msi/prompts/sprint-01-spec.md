# SPRINT 1 — MSI Specification (contratos antes de código)

## Gate
Requer: `docs/msi/01-current-state.md`, `02-capability-map.md`, `05-msi-spec-v0.md` lidos.
Sem dependência de código novo. Se `05-msi-spec-v0.md` não existir, PARE.

## Objetivo
Transformar a tese em contratos explícitos e validáveis. Hipótese: os 5 schemas
conseguem representar 5 workflows realistas sem assumir nenhum provider.

## IN scope (paths below relative to the spec repo, not to LCC `docs/`)
- Criar repo público `lucasmartins-ai/minimum-sufficient-inference` via `gh`
  (README, `theory.md`, `architecture.md`, `terminology.md`,
  `spec/{task-contract,context-ir,inference-plan,verification-result,inference-receipt}.schema.json`,
  `research/research-agenda.md`, `research/methodology.md`, `benchmarks/README.md`, `examples/`).
- 5 fixtures em `examples/` (coding fix, repo investigation, multi-tool task,
  research brief, structured decision) — todos válidos contra os schemas.
- Política de versionamento independente (`versioning.md`, no spec repo).

## OUT scope (não fazer)
Nenhuma implementação LCC; nenhum código de roteamento/verificação; nenhuma
dependência nova; nenhum claim de performance; nenhuma CLI nova.

## Tarefas
1. Criar o repo e a árvore mínima acima (arquivos podem começar enxutos, mas completos).
2. Transcrever os schemas de `05-msi-spec-v0.md`, adicionando `required`, `additionalProperties: false`
   e enums fechados onde houver vocabulário fixo (relationship types, actions, statuses).
3. Escrever as 5 fixtures usando APENAS campos dos schemas (toda necessidade de campo novo
   vira issue listada, não campo ad-hoc).
4. Escrever `research/methodology.md` (classes de dataset, regra de contaminação,
   exigência de reprodução) e `research/research-agenda.md` (perguntas abertas, não respostas).
5. Registrar decisões em ADRs no spec repo: existência da IR, pluggability de triage,
   protocolo-sobre-produto, split spec/implementação.

## Testes (obrigatórios)
- `python3 -c` ou script `scripts/validate_examples.py` usando `jsonschema` (se ausente,
  validar com `python -m json` + checagem manual de required — registrar limitação):
  os 5 exemplos DEVEM validar; 1 fixture negativa (campo provider-específico) DEVE falhar.
- Grep de acoplamento: nenhum schema pode conter `jev|openai|anthropic|gpt|claude`
  (case-insensitive) — evidenciar com o comando e output vazio.

## Docs
Os arquivos do repo + ADRs. Inglês técnico, sem marketing. Cada schema com `description`
por campo e exemplo mínimo.

## Benchmark
N/A para este sprint (sem medição). Validação = matriz 5 fixtures × 5 schemas, tudo verde.

## Correção
Schema inválido ou fixture que não valida → corrigir schema OU fixture com justificativa
escrita (nunca ambos silenciosamente). 3 tentativas sem fechar → BLOCKED.

## Acceptance criteria
- [ ] Repo público criado com a árvore completa.
- [ ] 5/5 fixtures validam; 1/1 fixture negativa falha pelo motivo esperado.
- [ ] Grep de provider nos schemas retorna vazio (evidência colada no DONE).
- [ ] Proveniência + restauração + escalonamento representáveis em ≥1 fixture cada.
- [ ] `SPRINT_1_DONE.md` (no repo LCC, `docs/msi/`) em PASS.
