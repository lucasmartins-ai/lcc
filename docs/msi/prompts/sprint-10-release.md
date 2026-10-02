# SPRINT 10 — Public Research Release (impecável ou nada)

## Gate
Requer: `SPRINT_9_DONE.md` = PASS + todos os DONE anteriores presentes.
Este sprint não cria capacidade nova — consolida e publica. Qualquer gate vermelho
nos sprints 1–9 bloqueia o release (corrigir lá, não aqui).

## Objetivo
Release público que sustenta a tese com evidência e limitações honestas.
Hipótese nula permanente: sem prior-art review, sem claim de novidade.

## IN scope
- Spec congelada e versionada; architecture paper (título candidato no master §10;
  manter SOMENTE se o conteúdo o sustenta).
- MSI-Bench + resultados + limitações + agenda de pesquisa publicados.
- Prior-art review escrito (o que já existe, o que é incremental, o que é novo —
  cada claim de novidade com citação ou removida).
- Checklist de release: full suite verde, links verificados, `test_docs.py` verde,
  instalação limpa, licenças/atribuições (Laya NOTICE precedent).

## OUT scope
Nenhuma feature nova; nenhum benchmark novo; nenhum número novo (só consolidação);
nenhum SaaS/cloud/infra; nenhum rebranding do LCC.

## Tarefas
1. Auditoria de claims: grepar docs/paper por "novel|SOTA|first|best|guarantee" —
   cada ocorrência ou ganha citação/medição ou é reescrita.
2. Congelar versões (IR, Contract, Plan, Receipt, dataset, evaluator, policy) e
   carimbar nos artefatos.
3. Verificar reprodução end-to-end de um terceiro: checkout limpo → quickstart →
   1 categoria do bench (log completo anexado).
4. Escrever `limitations.md` (tudo que não funciona / não foi testado / pode estar
   errado) e agenda de pesquisa (próximas 5 perguntas, não promessas).

## Testes
- Full `pytest` + node + docs tests verdes no commit do release.
- Link-check em docs publicadas (script ou grep de 404 — evidência anexada).
- Instalação limpa + quickstart refeitos no commit final.

## Docs
Paper, limitations, metodologia consolidada, ADRs finais, CHANGELOG de release.

## Benchmark
Nenhum número novo. Consolidação: tabela-mestre de todos os resultados com
proveniência (sprint, dataset, N, commit) por linha.

## Correção
Claim sem evidência → corta, sem exceção (reputação > headline). Link quebrado,
teste vermelho ou reprodução falhada → release BLOQUEADO até verde.
Este é o único sprint onde FAIL Jade é preferível a PASS com ressalva escondida.

## Acceptance criteria
- [ ] Zero claims de novidade/superioridade sem citação ou medição pareada.
- [ ] `limitations.md` + agenda publicados; versões congeladas e carimbadas.
- [ ] Reprodução third-party simulada com log completo verde.
- [ ] Full suite + docs tests + links + install limpa verdes no commit final.
- [ ] `SPRINT_10_DONE.md` em PASS — ou FAIL explícito com o que falta.
