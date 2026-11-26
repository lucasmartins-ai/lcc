"""Shared pins, private I/O, filtered Jev client and prompt variants for intake-distill-v1.

Never prints or logs message text. Every script checks Amendment 1 file pins before running.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any

from lcc.relevance.jev import (
    JEV_CONTEXT_LIMIT_TOKENS,
    JevClient,
    _request_tokens,
)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PRIV = Path.home() / ".lcc-private"
OUT = PRIV / "intake-distill-v1"
LEDGER = OUT / "jev-ledger.jsonl"

CATS = ["pedido_principal", "pedido_lateral", "contexto", "entrega", "regra", "ruido"]
KEEP = {"pedido_principal", "pedido_lateral", "entrega", "regra"}
TAU_DEFAULT = 0.5
JEV_BUDGET = 2500
MAX_Q_PER_REQ = 30
TOKEN_MARGIN = 512

PINS = {
    REPO
    / "src/lcc/intake/parser.py": "91ed1cc255e4bd35bb3e9de5216f2f6461ef6af634977008ccb6339908834346",
    REPO / "src/lcc/handoff.py": "9a5d5873eac33cff52f1409c02e14939b4cc27ee2adb0e61c6e73a91637c07b3",
    HERE / "cues.json": "f9e3f574057af27c193b4bfde28b7a7bf8993eafe7e4d259eb6af8f583a9f9de",
    HERE
    / "pilot_downstream.py": "eac48532b9233a35a53f20a45b7d021234d15610cb789bfea580c315dcce9dda",
    HERE
    / "transcribe_voice.py": "a2aa4adafa2154d5a06769ea19c5afaba4df5c87b0603e14fc7899e970569529",
    HERE / "voice_screen.py": "c73e59cfa3e5ab4bddb325072ad433aa8cb4c4f19b50adc16aa7d09da43df5bf",
}

_REFUSED_ENV = ("TYPESAFE_ENDPOINT", "TYPESAFE_MODEL", "SSL_CERT_FILE", "SSL_CERT_DIR")
_MODEL_RE = re.compile(r"jev-(?:latest|\d{1,3}(?:\.\d{1,3}){0,3})")
_INT_KEYS = ("http_status", "attempt", "latency_ms", "input_tokens", "output_tokens", "state_chars")
_ERROR_KINDS = ("pre_flight", "network", "malformed_response")

# Jev question variants (PROTOCOL.md, Amendment 2).
# v1_pilot is the pilot question (pilot_downstream.py), already cached on dev under pilot/.
VARIANTS: dict[str, dict[str, Any]] = {
    "v1_pilot": {
        "instruction_tpl": (
            "`sentences` is a message the speaker dictated to an AI coding assistant. "
            "Which category fits `sentences.{k}`, read in context?"
        ),
        "criteria": {
            "pedido_principal": "The request the speaker most needs done (or a repeat of it).",
            "pedido_lateral": "Another request, besides the main one.",
            "contexto": "Background the task needs: situation, history, why.",
            "entrega": "What should come out: format, file, place, audience.",
            "regra": "A constraint on how to do it: must, never, only, without, before.",
            "ruido": "Thinking aloud, filler, or a repeat that adds nothing new.",
        },
    },
    "v2_owner_prior_en": {
        "instruction_tpl": (
            "`sentences` is a message the speaker dictated or typed to an AI coding assistant. "
            "Classify `sentences.{k}` read in full context. Most sentences (~85%) are `contexto` "
            "(background, situation, reasoning, narrative, examples). Choose `entrega` or `regra` "
            "ONLY when an explicit deliverable/format or explicit constraint/prohibition is stated. "
            "Choose `ruido` ONLY for pure empty filler with zero task meaning."
        ),
        "criteria": {
            "pedido_principal": (
                "Directly states or directly restates the core task the speaker most wants done."
            ),
            "pedido_lateral": (
                "Directly asks for a distinct secondary task, separate from the core request."
            ),
            "contexto": (
                "Default category: background, facts, problem symptoms, history, explanations, "
                "motivations, examples, or commentary that is not itself a direct request."
            ),
            "entrega": (
                "Explicitly specifies what must be delivered: file, format, destination, or "
                "audience. Do not use for mere mentions of files or tools in background."
            ),
            "regra": (
                "Explicitly states a binding constraint or prohibition on how to work (must, "
                "never, only, without, before, do not). Do not use for ordinary facts or hopes."
            ),
            "ruido": (
                "Pure empty verbal filler with zero informational value (e.g. 'ok', 'hmm'). "
                "Never use if the sentence carries any request, constraint, or context."
            ),
        },
    },
    "v3_owner_prior_pt": {
        "instruction_tpl": (
            "`sentences` é uma mensagem que o usuário ditou ou digitou para um assistente de "
            "código. Classifique `sentences.{k}` no contexto da mensagem inteira. Quase todas as "
            "frases (~85%) são `contexto` (cenário, história, explicação, raciocínio). Só marque "
            "`entrega` ou `regra` quando houver formato/entregável ou restrição explícitos. Só "
            "marque `ruido` se for preenchimento vazio sem nenhuma informação útil."
        ),
        "criteria": {
            "pedido_principal": (
                "Frase que pede diretamente a tarefa central que o usuário mais precisa que seja "
                "feita (ou reafirma diretamente esse pedido central)."
            ),
            "pedido_lateral": (
                "Frase que pede diretamente outra tarefa distinta, além do pedido principal."
            ),
            "contexto": (
                "Categoria padrão: cenário, fatos, sintomas de bug, histórico, explicações, "
                "motivações, exemplos ou observações que não são um pedido direto."
            ),
            "entrega": (
                "Define explicitamente o entregável esperado: formato, arquivo de saída, destino "
                "ou público. Não marque só porque a frase cita um arquivo como contexto."
            ),
            "regra": (
                "Impõe explicitamente uma restrição, proibição ou regra obrigatória de como "
                "fazer (nunca, não faça, somente, sem, antes de, obrigatório)."
            ),
            "ruido": (
                "Apenas preenchimento vazio sem conteúdo útil. Se tiver qualquer contexto, "
                "pedido ou regra, não é ruído."
            ),
        },
    },
    "v4_five_class_en": {
        "instruction_tpl": (
            "`sentences` is a message dictated or typed to an AI coding assistant. Classify "
            "`sentences.{k}` in full context. Default to `contexto`: most sentences (~85%) are "
            "background, narrative, problem descriptions, thinking aloud, or repeats. Mark "
            "`pedido_principal` for sentences stating the core task (including follow-up sentences "
            "that specify that same core task). Mark `entrega` or `regra` ONLY when explicit."
        ),
        "criteria": {
            "pedido_principal": (
                "Directly states or specifies the single core task the speaker most needs done."
            ),
            "pedido_lateral": (
                "Directly asks for an independent secondary task unrelated to the core task."
            ),
            "contexto": (
                "Default: background, facts, problem symptoms, narrative, reasoning, thinking "
                "aloud, filler, or repetition. Choose this whenever unsure."
            ),
            "entrega": (
                "Explicitly specifies the output deliverable, format, file path, or audience."
            ),
            "regra": (
                "Explicitly imposes a hard rule, limit, or prohibition (must, never, only, "
                "without, do not)."
            ),
        },
    },
    "v5_five_class_pt_strict": {
        "instruction_tpl": (
            "`sentences` é uma mensagem enviada a um assistente de código. Classifique "
            "`sentences.{k}` lendo a mensagem toda. Em caso de dúvida, escolha `contexto`: a "
            "grande maioria das frases é contexto, relato de problema, explicação ou fala em voz "
            "alta. Marque `pedido_principal` só para frases que pedem diretamente o objetivo "
            "central, `pedido_lateral` só para uma segunda tarefa independente, e `entrega` ou "
            "`regra` só quando forem explícitos e inequívocos."
        ),
        "criteria": {
            "pedido_principal": (
                "Pede diretamente o objetivo central da mensagem (ou detalha diretamente o que "
                "fazer nesse pedido central)."
            ),
            "pedido_lateral": (
                "Pede diretamente uma tarefa secundária separada do objetivo central."
            ),
            "contexto": (
                "Padrão: cenário, relato, explicação, hipótese, fala em voz alta, repetição ou "
                "qualquer frase que não seja pedido direto, entrega explícita ou regra explícita."
            ),
            "entrega": (
                "Especifica explicitamente o formato, arquivo, local ou público da entrega final."
            ),
            "regra": (
                "Impõe explicitamente uma proibição ou condição obrigatória de execução (não "
                "faça, nunca, só, sem, antes de, tem que)."
            ),
        },
    },
}


def check_pins(extra: dict[Path, str] | None = None) -> None:
    """Refuse to run if any Amendment 1 pinned file (or extra pin) changed."""
    pins = dict(PINS)
    if extra:
        pins.update(extra)
    for path, want in pins.items():
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != want:
            raise SystemExit(f"refused: {path.name} differs from pinned sha256")


def ensure_private_dir(path: Path) -> Path:
    """Verify path stays inside ~/.lcc-private after symlink resolution, create 0700."""
    priv_real = PRIV.resolve()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    real = path.resolve()
    if real != priv_real and priv_real not in real.parents:
        raise SystemExit("refused: private output path resolves outside ~/.lcc-private")
    os.chmod(real, 0o700)
    return real


def write_private_json(path: Path, data: Any) -> None:
    """Atomically write JSON with 0600 permissions inside ~/.lcc-private."""
    ensure_private_dir(path.parent)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def ledger_request_count(ledger_path: Path = LEDGER) -> int:
    if not ledger_path.is_file():
        return 0
    with ledger_path.open(encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        n = float(value)
    except (ValueError, OverflowError):
        return None
    return n if math.isfinite(n) else None


def _filter_ledger_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Keep only structured metadata and safe category choices — never raw API error bodies."""
    line: dict[str, Any] = {k: entry[k] for k in ("ts", "feature") if isinstance(entry.get(k), str)}
    line["status"] = "ok" if entry.get("status") == "ok" else "error"
    for key in ("model", "resolved_model"):
        if key in entry:
            v = entry[key]
            line[key] = v if isinstance(v, str) and _MODEL_RE.fullmatch(v) else "unexpected"
    for key in _INT_KEYS:
        if type(entry.get(key)) is int:
            line[key] = entry[key]
    if "error" in entry:
        err = entry["error"] if isinstance(entry["error"], str) else ""
        line["error"] = next((k for k in _ERROR_KINDS if err.startswith(k)), "api_error")
    answers = entry.get("answers")
    if isinstance(answers, dict):
        line["n_answers"] = len(answers)
    return line


class BudgetedPrivateJev(JevClient):
    """JevClient with 1 attempt, filtered private ledger, and hard total-request budget."""

    def __init__(self, *args: Any, budget: int = JEV_BUDGET, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.budget = budget
        self._count = ledger_request_count(self.ledger_path) if self.ledger_path else 0

    def _ledger_append(self, entry: dict[str, Any]) -> None:
        self._count += 1
        try:
            line = _filter_ledger_entry(entry)
        except Exception:  # noqa: BLE001
            line = {"status": "error" if "error" in entry else "ok", "ledger_filter": "failed"}
        super()._ledger_append(line)

    def evaluate(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
        if self._count >= self.budget:
            raise RuntimeError(f"refused: Jev budget exhausted ({self._count}/{self.budget})")
        return super().evaluate(state, questions)


def make_jev_client(feature: str, *, budget: int = JEV_BUDGET) -> BudgetedPrivateJev:
    """Create a 1-attempt private-ledger Jev client, refusing env endpoint/cert overrides."""
    bad = [k for k in _REFUSED_ENV if os.environ.get(k)]
    if bad:
        raise SystemExit(f"refused: unset {', '.join(bad)} before calling Jev")
    ensure_private_dir(OUT)
    client = BudgetedPrivateJev.from_env(
        ledger_path=LEDGER,
        feature=feature,
        attempts=1,
        timeout=60.0,
        budget=budget,
    )
    if client is None:
        raise SystemExit("refused: no TypeSafe API key or network disabled")
    return client


def _build_questions(variant: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    tpl = variant["instruction_tpl"]
    criteria = variant["criteria"]
    return {
        k: {
            "type": "choice",
            "instructions": tpl.format(k=k),
            "criteria": criteria,
        }
        for k in keys
    }


def plan_chunks(
    model: str,
    sents: dict[str, str],
    variant: dict[str, Any],
    *,
    max_q: int = MAX_Q_PER_REQ,
    limit: int = JEV_CONTEXT_LIMIT_TOKENS - TOKEN_MARGIN,
) -> list[list[str]]:
    """Split sentence keys into chunks that fit within Jev's context limit."""
    keys = list(sents)
    chunks: list[list[str]] = []
    i = 0
    while i < len(keys):
        # Greedy pack up to max_q while verifying exact payload token upper bound.
        hi = min(len(keys), i + max_q)
        while hi > i:
            batch = keys[i:hi]
            payload = {
                "model": model,
                "state": {"sentences": sents},
                "questions": _build_questions(variant, batch),
            }
            toks, _ = _request_tokens(payload)
            if toks <= limit:
                chunks.append(batch)
                i = hi
                break
            # Halve excess quickly for very long messages.
            step = max(1, (hi - i) // 2)
            hi -= step
        else:
            raise RuntimeError("message exceeds System One context limit even with 1 question")
    return chunks


def label_message_jev(
    client: BudgetedPrivateJev,
    item: dict[str, Any],
    variant_name: str,
    *,
    max_q: int = MAX_Q_PER_REQ,
) -> dict[str, Any]:
    """Label every sentence of one message with Jev; returns full 6-class probability rows."""
    variant = VARIANTS[variant_name]
    allowed = set(variant["criteria"])
    text = item["text"]
    spans = item["sentences"] if "sentences" in item else item["spans"]
    sents = {f"s{i:03d}": text[a:b] for i, (a, b) in enumerate(spans)}
    chunks = plan_chunks(client.model, sents, variant, max_q=max_q)

    answers: dict[str, Any] = {}
    resolved_models: set[str] = set()
    for batch in chunks:
        qs = _build_questions(variant, batch)
        resp = client.evaluate({"sentences": sents}, qs)
        resolved_models.add(client.last_resolved_model)
        ans = resp.get("answers")
        if not isinstance(ans, dict):
            raise RuntimeError(f"malformed response on {item['id']}")
        for k in batch:
            if k not in ans:
                raise RuntimeError(f"missing key {k} on {item['id']}")
            answers[k] = ans[k]

    rows: list[dict[str, Any]] = []
    for i in range(len(spans)):
        k = f"s{i:03d}"
        a = answers[k]
        choice = a.get("choice")
        raw_probs = a.get("probabilities")
        if not isinstance(choice, str) or choice not in allowed or not isinstance(raw_probs, dict):
            raise RuntimeError(f"invalid answer schema on {item['id']} at {k}")
        probs: dict[str, float] = {}
        for c in CATS:
            if c in allowed:
                v = _finite(raw_probs.get(c))
                if v is None or not 0.0 <= v <= 1.0:
                    raise RuntimeError(f"invalid probability on {item['id']} at {k}")
                probs[c] = round(v, 6)
            else:
                probs[c] = 0.0
        rows.append({"cat": choice, "p": round(probs[choice], 4), "probs": probs})

    return {
        "id": item["id"],
        "variant": variant_name,
        "requests": len(chunks),
        "resolved_models": sorted(resolved_models),
        "labels": rows,
    }


def cohen_kappa(gold: list[str], pred: list[str], cats: list[str] = CATS) -> float:
    n = len(gold)
    if n == 0:
        return 0.0
    po = sum(g == p for g, p in zip(gold, pred, strict=True)) / n
    pe = sum((gold.count(c) / n) * (pred.count(c) / n) for c in cats)
    return 0.0 if abs(1.0 - pe) < 1e-12 else (po - pe) / (1.0 - pe)


def per_class_f1(
    gold: list[str], pred: list[str], cats: list[str] = CATS
) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for c in cats:
        tp = sum(g == c and p == c for g, p in zip(gold, pred, strict=True))
        g, p = gold.count(c), pred.count(c)
        out[c] = None if g == 0 and p == 0 else (2 * tp / (g + p))
    return out
