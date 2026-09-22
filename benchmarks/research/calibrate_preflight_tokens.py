#!/usr/bin/env python3
"""Re-sonda o teto de tokens do System One para calibrar o pre-flight do Jev.

Motivo: ``JEV_CONTEXT_LIMIT_TOKENS`` (``lcc/relevance/jev.py``) recusa localmente tudo
acima da janela, mas o numero que importa e' o ``input_tokens`` que a API reporta no
payload. Se a API passasse a contar MAIS que o tiktoken, o guard deixaria passar estados
que voltariam ``400 max_tokens_exceeded`` — entao o teto precisa de re-sonda quando a
TypeSafe mudar tokenizer ou janela. Duas sondas de payload diferente dao a reta
``api = a + b * local``.

Resultados medidos (2026-09-22, resolvido ``jev-1.13.0``): 6 medicoes com
``input_tokens`` reportado + 1 recusa ao vivo (estado de 408k tokens que o proprio guard
derrubou antes da rede) = 7 tentativas em 2 rodadas. Fitas, por payload:

    fit 1  prosa-JSON (2 pontos, 1a rodada)   api = 249 + 0.98 * local  <- pior
    fit 2  codigo-JSON (1 ponto, 1a rodada)   api = 0.94 * local
    fit 3  combinado (3 pontos, 2a rodada)    api = 437 + 0.90 * local

A API nunca contou mais que o tiktoken nas duas formas, entao recusar em 32.768 tokens
LOCAIS nao deixa sair nada acima da janela; o custo e' a faixa que a gente recusa e que a
API aceitaria — 1% a 10% da janela conforme a forma do payload (pior fit, 0.90: 9,6%).
Re-rodar varia um pouco dentro dessa tolerancia — o que importa e' a pior inclinacao
observada, 0.98, que ainda projeta a API abaixo do teto no ponto em que o guard recusa.

Requer rede e chave (nao roda em CI: ``testpaths = ["tests"]`` nao coleta benchmarks).
Offline, o proprio guard e' coberto por
``tests/test_jev_failure_modes.py::test_oversized_state_refused_locally_and_small_state_still_sent``.

Run: python3 benchmarks/research/calibrate_preflight_tokens.py
"""
from __future__ import annotations

import json
import sys

from lcc.relevance.jev import JEV_CONTEXT_LIMIT_TOKENS, JevClient, _request_tokens

PROSE_PARAGRAPH = (
    "The booking funnel dropped fourteen percent after the cache change, and the server log "
    "shows the origin kept answering two hundred while the edge returned stale markup. "
    "Measured before and after, same corpus, same hour of the day. "
)
CODE_LINE = (
    '    "tool_calls": [{"id": "call_00_abc123", "tool": "bash", "input": {"cmd": "npx tsc"}}],\n'
    '    "result": {"ok": true, "exit_code": 0, "stderr": ""},\n'
)

QUESTIONS = {
    "calibration_probe": {
        "type": "noul",
        "instructions": "Is the context in the state sufficient to answer the objective?",
        "criteria": {"true": "sufficient", "false": "missing information"},
    }
}

# Alvos locais: um barato (retira o overhead fixo da API) e um perto do teto (retira a
# inclinacao). Dois pontos bastam para a reta; shapes diferentes cobrem as formas reais.
SHAPES: tuple[tuple[str, int], ...] = (("prose", 2_000), ("prose", 30_000), ("code", 27_000))


def build(shape: str, local_target: int) -> dict:
    unit = PROSE_PARAGRAPH if shape == "prose" else CODE_LINE
    per_unit, _ = _request_tokens({"s": unit})
    units = max(1, local_target // max(per_unit, 1))
    text = "\n\n".join([unit.strip()] * units) if shape == "prose" else unit * units
    return {"objective": "reconstruct the incident timeline", "context": text}


def main() -> int:
    client = JevClient.from_env(ledger_path=None, feature="jev_calibration")
    if client is None:
        print("sem TYPESAFE_API_KEY/network desligado: nada a medir (roda com a chave)")
        return 1

    pontos: list[tuple[int, int]] = []
    for shape, alvo in SHAPES:
        state = build(shape, alvo)
        payload = {"model": client.model, "state": state, "questions": QUESTIONS}
        local, method = _request_tokens(payload)
        api = client.evaluate(state, QUESTIONS).get("usage", {}).get("input_tokens")
        print(f"{shape:<6} local {local:>6} ({method}) | api {api} | state {len(json.dumps(state))} chars")
        if isinstance(api, int) and api > 0:
            pontos.append((local, api))

    if len(pontos) < 2 or pontos[0][0] == pontos[-1][0]:
        print("menos de dois pontos validos: nao da para ajustar a reta")
        return 1

    (l1, a1), (l2, a2) = pontos[0], pontos[-1]
    b = (a2 - a1) / (l2 - l1)
    a = a1 - b * l1
    print(f"\nreta medida: api = {a:.0f} + {b:.4f} * local")
    print(f"guard atual: recusa acima de {JEV_CONTEXT_LIMIT_TOKENS} locais")
    print(f"  -> projeta api {a + b * JEV_CONTEXT_LIMIT_TOKENS:.0f} no ponto de recusa")
    sobrepassa = a + b * JEV_CONTEXT_LIMIT_TOKENS > JEV_CONTEXT_LIMIT_TOKENS
    print("  FOLGADO: a API contaria acima do teto antes do guard recusar" if sobrepassa else
          "  SEGURO: no ponto de recusa a API ainda projeta abaixo do teto")
    return 2 if sobrepassa else 0


if __name__ == "__main__":
    sys.exit(main())
