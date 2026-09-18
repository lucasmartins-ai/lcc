# Verificação com chave real (Jev) — prompt para o agente orquestrador

Cole o bloco abaixo no orquestrador. Ele executa a bateria com `TYPESAFE_API_KEY`
real e devolve a tabela de resultados. Nada aqui commita, pusha ou altera código:
só roda benchmarks e escreve em `benchmarks/research/results/`.

---

## Prompt (colar no orquestrador)

Você está em `/Users/Master/LCC` (branch atual, sem trocar de branch, sem
commitar, sem pushar). Execute a bateria de verificação Jev com chave real e
devolva a tabela de resultados.

**Setup (não vazar a chave em logs):**

```bash
export TYPESAFE_API_KEY="$TYPESAFE_API_KEY"   # já deve existir no ambiente; se ausente, PARE e reporte
export TIKTOKEN_CACHE_DIR="$HOME/.cache/tiktoken"
python3 -c "from lcc.relevance.jev import resolve_typesafe_key; print('key:', 'OK' if resolve_typesafe_key() else 'MISSING')"
```

Se `MISSING`, pare e responda apenas: `BLOQUEADO — sem chave Jev`.

**Bateria (nesta ordem, do barato ao caro):**

1. E0 mecânico (baseline offline, ~1 min):
   `python3 benchmarks/research/run_answer_eval.py --provider mechanical`
   Gate: `30 cases, 0 regressions`.
2. E0 Jev (30 casos, ~187 calls no XL; observe o custo):
   `python3 benchmarks/research/run_adversarial.py jev`
   Gate: 30/30 PASS. Anote `reduction_pct` médio e qualquer FAIL com `lost=` / `checks=`.
3. E1 piloto com Jev (amostra pequena primeiro — custo!):
   `python3 benchmarks/research/run_multiagent_ab.py --tasks 5 --provider jev`
   Se 0 regressões E1, expanda: `--tasks 20 --provider jev`.
   Gate: `E1_regressions=0`, `E0_regressions=0`. Anote `mean_reduction` e `reviews`.
4. Verifier independente (amostra de 3 casos, 1 call extra por pass):
   Para `qualifier_truncation`, `contradiction_same_metric`, `dependency_causal` em
   `benchmarks/research/adversarial/<id>.md`, rode:
   `lcc compact <arquivo> -q "<question do index.json>" --provider jev --semantic-verify -r /tmp/v_<id>.json`
   (questions em `benchmarks/research/adversarial/index.json`).
   Gate: `semantic_verifier_sufficient` e `needs_review` presentes no JSON;
   `jev_model_resolved` diferente de `jev-latest` puro (versão resolvida registrada).
5. Estabilidade warm (byte-stability, sem custo Jev na 2ª run):
   `lcc compact dossier.md -q "..." --provider jev --decisions-cache /tmp/dec.jsonl -o /tmp/c1.md`
   rode 2x e compare `sha256sum /tmp/c1.md /tmp/c2.md` + `output_sha256` nos reports.
   Gate: bytes idênticos, `calls: 0` na 2ª run.
6. Property B (offline, grátis):
   `python3 benchmarks/research/run_injection_e2e.py`
   Gate: `3/3 Property-B cases pass`.

**Devolva EXATAMENTE esta tabela preenchida (mais nada além de observações de custo):**

| check | comando | resultado | gate | pass? |
|---|---|---|---|---|
| E0 mechanical | run_answer_eval | x/30, y regressions | 0 regressions | |
| E0 jev | run_adversarial jev | x/30 | 30/30 | |
| E1 pilot jev | run_multiagent_ab --tasks 20 | E1_reg=x E0_reg=y mean_red=z% reviews=w | E1_reg=0 | |
| verifier | compact --semantic-verify (3 casos) | sufficient=x/3 reviews=y/3 resolved=<modelo> | campos presentes | |
| warm stability | 2x compact + sha256 | identical? calls2=x | identical, calls 0 | |
| Property B | run_injection_e2e | x/3 | 3/3 | |

Mais: nº aproximado de Jev calls total, tempo total, e os `FAILED` (id + `lost=`/`checks=`)
se houver. Se qualquer gate falhar, marque a linha como FAIL e cole o trecho do log.
