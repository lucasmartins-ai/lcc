#!/usr/bin/env python3
"""Intake dictation v1: synthetic dictations whose cuts are known by construction.

    python benchmarks/research/intake-dictation-v1/intake_dictation_v1.py generate
    python benchmarks/research/intake-dictation-v1/intake_dictation_v1.py run --arm A0 --src DIR
    python benchmarks/research/intake-dictation-v1/intake_dictation_v1.py run --arm L1
    python benchmarks/research/intake-dictation-v1/intake_dictation_v1.py run --arm L12
    python benchmarks/research/intake-dictation-v1/intake_dictation_v1.py report

The protocol, metrics and pass criteria are in PROTOCOL.md next to this file. Every case is
a clean request (pt-BR or English) plus injected noise; each injected segment is labelled
cut or keep when it is written, so the gold is exact. Arms A0 and L1 run offline
(``LCC_DISABLE_NETWORK=1``); only L12 calls Jev, and only on this synthetic text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CASES_PATH = HERE / "cases.json"
SEED = 20261115
VERSION = "intake-dictation-v1"
MODEL = "claude-sonnet-5"

# --- clean requests ------------------------------------------------------------------------
# Each base is a fully specified request: every ask is stated, at most two asks. One sentence
# holds a correction slot [[right|wrong]]: the clean text uses ``right``; the self-correction
# family says ``wrong`` first and then corrects it. Odd-numbered bases are the dev split
# (rules may be tuned on them), even-numbered bases the test split (headline numbers).
BASES: list[dict[str, Any]] = [
    {"id": "pt01", "lang": "pt", "s": [
        ("ask", "Preciso que você corrija o teste de integração do checkout."),
        ("context", "Ele quebra [[desde ontem|desde segunda]] no CI com timeout no banco."),
        ("constraint", "Não mexa no schema das tabelas.")]},
    {"id": "pt02", "lang": "pt", "s": [
        ("ask", "Rode a migração do banco [[na segunda|na sexta]] de manhã."),
        ("context", "O time de suporte avisou os clientes sobre a janela."),
        ("ask", "Depois me mande o log completo da execução.")]},
    {"id": "pt03", "lang": "pt", "s": [
        ("context", "O relatório mensal está saindo com os valores em dólar."),
        ("ask", "Você consegue trocar a moeda padrão para [[real|euro]]?"),
        ("constraint", "Só altere a configuração, sem mexer no código.")]},
    {"id": "pt04", "lang": "pt", "s": [
        ("ask", "Queria que você revisasse o PR [[42|24]] antes do almoço."),
        ("context", "Ele muda a autenticação do painel de admin."),
        ("constraint", "Não faça merge sem os testes passarem.")]},
    {"id": "pt05", "lang": "pt", "s": [
        ("context", "A página de preços demora [[oito|dez]] segundos para carregar no celular."),
        ("ask", "Investigue o que está pesando no carregamento."),
        ("ask", "Depois me diga quais imagens dá para comprimir.")]},
    {"id": "pt06", "lang": "pt", "s": [
        ("ask", "Escreva um teste para a função de desconto do carrinho."),
        ("constraint", "Use pytest e nada de mocks do banco."),
        ("context", "A função está em [[src/cart/discount.py|src/cart/price.py]].")]},
    {"id": "pt07", "lang": "pt", "s": [
        ("context", "O deploy de ontem derrubou o worker de e-mails."),
        ("ask", "Faça o rollback para a versão [[1.8.2|1.8.3]]."),
        ("ask", "E abra uma issue explicando a causa.")]},
    {"id": "pt08", "lang": "pt", "s": [
        ("ask", "Atualize o README com o novo comando de instalação."),
        ("constraint", "Mantenha o texto em inglês."),
        ("context", "O comando mudou [[na versão 2.0|na versão 1.9]].")]},
    {"id": "pt09", "lang": "pt", "s": [
        ("context", "Os clientes do plano grátis estão vendo o botão de [[exportar|importar]]."),
        ("ask", "Esconda esse botão para quem não paga."),
        ("constraint", "Não remova a rota da API.")]},
    {"id": "pt10", "lang": "pt", "s": [
        ("ask", "Me explica por que o cache do prompt não está acertando."),
        ("context", "O prefixo muda [[a cada pedido|a cada sessão]] por causa da data no cabeçalho.")]},
    {"id": "pt11", "lang": "pt", "s": [
        ("ask", "Gere a fatura de [[outubro|setembro]] para a clínica Bristol Vet."),
        ("constraint", "Use o modelo novo com o logo atualizado."),
        ("context", "O valor já está aprovado no CRM.")]},
    {"id": "pt12", "lang": "pt", "s": [
        ("context", "O formulário de contato aceita e-mail [[sem arroba|sem ponto]]."),
        ("ask", "Adicione validação no front e no back."),
        ("constraint", "A mensagem de erro tem que ser em português.")]},
    {"id": "pt13", "lang": "pt", "s": [
        ("ask", "Compare o tempo de build do Vite com o do Webpack no projeto do site."),
        ("context", "O build atual leva [[quatro|seis]] minutos no CI.")]},
    {"id": "pt14", "lang": "pt", "s": [
        ("context", "A planilha de leads tem [[duzentas|trezentas]] linhas duplicadas."),
        ("ask", "Remova as duplicadas mantendo o registro mais recente."),
        ("constraint", "Não apague nada da aba de clientes.")]},
    {"id": "en01", "lang": "en", "s": [
        ("ask", "Fix the flaky login test in the auth service."),
        ("context", "It fails about once in [[ten|twenty]] runs on CI."),
        ("constraint", "Do not change the session timeout.")]},
    {"id": "en02", "lang": "en", "s": [
        ("ask", "Run the database migration [[on Monday|on Friday]] morning."),
        ("context", "Support already warned the customers about the window."),
        ("ask", "Then send me the full execution log.")]},
    {"id": "en03", "lang": "en", "s": [
        ("context", "The monthly report shows every amount in dollars."),
        ("ask", "Can you switch the default currency to [[pounds|euros]]?"),
        ("constraint", "Only touch the config, not the code.")]},
    {"id": "en04", "lang": "en", "s": [
        ("ask", "Please review PR [[42|24]] before lunch."),
        ("context", "It changes authentication for the admin panel."),
        ("constraint", "Never merge it before the tests pass.")]},
    {"id": "en05", "lang": "en", "s": [
        ("context", "The pricing page takes [[eight|ten]] seconds to load on mobile."),
        ("ask", "Find out what is slowing it down."),
        ("ask", "Then tell me which images we can compress.")]},
    {"id": "en06", "lang": "en", "s": [
        ("ask", "Write a unit test for the cart discount function."),
        ("constraint", "Use pytest and do not mock the database."),
        ("context", "The function lives in [[src/cart/discount.py|src/cart/price.py]].")]},
    {"id": "en07", "lang": "en", "s": [
        ("context", "Yesterday's deploy took down the email worker."),
        ("ask", "Roll back to version [[1.8.2|1.8.3]]."),
        ("ask", "And open an issue explaining the cause.")]},
    {"id": "en08", "lang": "en", "s": [
        ("ask", "Update the README with the new install command."),
        ("constraint", "Keep the text short."),
        ("context", "The command changed [[in version 2.0|in version 1.9]].")]},
    {"id": "en09", "lang": "en", "s": [
        ("context", "Free plan users can see the [[export|import]] button."),
        ("ask", "Hide that button for anyone who does not pay."),
        ("constraint", "Do not remove the API route.")]},
    {"id": "en10", "lang": "en", "s": [
        ("ask", "Explain why the prompt cache keeps missing."),
        ("context", "The prefix changes [[on every request|on every session]] because of the date in the header.")]},
    {"id": "en11", "lang": "en", "s": [
        ("ask", "Generate the [[October|September]] invoice for the Bristol vet clinic."),
        ("constraint", "Use the new template with the updated logo."),
        ("context", "The amount is already approved in the CRM.")]},
    {"id": "en12", "lang": "en", "s": [
        ("context", "The contact form accepts emails [[without an at sign|without a dot]]."),
        ("ask", "Add validation on the front end and the back end."),
        ("constraint", "The error message must be in English.")]},
    {"id": "en13", "lang": "en", "s": [
        ("ask", "Compare the build time of Vite and Webpack on the website project."),
        ("context", "The current build takes [[four|six]] minutes on CI.")]},
    {"id": "en14", "lang": "en", "s": [
        ("context", "The leads spreadsheet has [[two hundred|three hundred]] duplicate rows."),
        ("ask", "Remove the duplicates and keep the most recent record."),
        ("constraint", "Do not delete anything from the clients tab.")]},
]

# --- injected noise ------------------------------------------------------------------------
# aside_lexicon: phrases the Layer 1 lexicon is meant to catch (PROTOCOL.md, "Layer 1").
# aside_open: asides deliberately outside that lexicon (pets, TV, phone); only a judge can
# catch them. tests/test_intake_dictation_bench.py checks both properties.
ASIDE_LEXICON = {
    "pt": ["Te amo.", "Já vou, amor!", "Tô indo, amor.", "Também te amo!", "Amor, já vou."],
    "en": ["Love you!", "Coming, honey!", "Be right there, babe.", "Love you too.", "Honey, coming!"],
}
ASIDE_OPEN = {
    "pt": ["Thor, sai daí!", "Mel, larga isso!", "Desce do sofá, Bob!", "Oi, mãe, te ligo depois.",
           "Filho, desliga essa televisão.", "E agora a previsão do tempo: chuva forte em São Paulo amanhã."],
    "en": ["Max, get off the couch!", "Bella, drop it!", "Hey mom, I'll call you back.",
           "Kids, turn that TV down.", "And now the weather: heavy rain in Seattle tomorrow."],
}
# Sentences that look like asides or noise but belong to the request: gold keep.
DISTRACTORS = {
    "pt": ["Meu cachorro derrubou o roteador ontem, por isso a rede caiu.",
           "O botão \"Te amo\" do app de namoro não aparece no iPhone.",
           "Deixa eu pensar como explicar isso.",
           "Minha esposa reclamou que o site está lento no celular."],
    "en": ["My dog unplugged the router yesterday, so the network dropped.",
           "The \"Love you\" button in the dating app is hidden on iOS.",
           "Let me think how to put this.",
           "My wife says the site is slow on her phone."],
}
# Vagueness is content, never cut; it exists to make readiness ask questions (language check).
VAGUE = {
    "pt": ["Não sei se é o melhor jeito, sei lá.", "Ou alguma coisa assim, não sei bem."],
    "en": ["Not sure this is the best way, or something.", "Or something like that, I guess."],
}
FILLER_BOUNDED = {
    "pt": [", né,", ", tipo,", ", sabe,", ", entendeu,", ", cara,"],
    "en": [", you know,", ", like,", ", I mean,", ", basically,"],
}
FILLER_OPENER = {"pt": ["Tipo, ", "Então assim, ", "Cara, "], "en": ["You know, ", "Like, ", "Basically, "]}
FILLER_INTERJECTION = {"pt": ["hum, ", "ahn, "], "en": ["uh, ", "um, "]}
CORRECTION_MARKERS = {
    "pt": ["não, quer dizer,", "quer dizer,", "não,", "ou melhor,", "digo,"],
    "en": ["no, I mean,", "I mean,", "no,", "no wait,", "or rather,", "sorry,"],
}
FAMILIES = ["clean", "aside_lexicon", "aside_open", "filler", "self_correction", "repetition",
            "false_start", "distractor", "vague", "mixed"]
MIXABLE = ["aside_lexicon", "aside_open", "filler", "self_correction", "repetition",
           "false_start", "distractor"]
_SLOT = re.compile(r"\[\[([^|\]]+)\|([^\]]+)\]\]")
_WORD = re.compile(r"\w+")
_INNER_SPACE = re.compile(r"(?<=\w) (?=\w)")


def _split(base: dict[str, Any]) -> str:
    return "dev" if int(base["id"][2:]) % 2 else "test"


def _lower_first(text: str) -> str:
    word = text.split(" ", 1)[0]
    return text if len(word) > 1 and word.isupper() else text[:1].lower() + text[1:]


def _sentences(base: dict[str, Any], correction: str | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    asks = 0
    for role, text in base["s"]:
        ask_id = f"a{asks}" if role == "ask" else None
        asks += role == "ask"
        m = _SLOT.search(text)
        if m is None:
            segs = [[text, False, ""]]
        elif correction is None:
            segs = [[text[: m.start()] + m.group(1) + text[m.end():], False, ""]]
        else:
            right, wrong = m.group(1), m.group(2)
            segs = [[text[: m.start()], False, ""],
                    [f"{wrong}, {correction} ", True, "self_correction"],
                    [right + text[m.end():], False, ""]]
        out.append({"role": role, "ask": ask_id, "segs": [s for s in segs if s[0]]})
    return out


def _inject_filler(sents: list[dict[str, Any]], lang: str, rng: random.Random) -> None:
    kind = rng.choice(["bounded", "bounded", "opener", "interjection"])
    sent = rng.choice(sents)
    if kind == "opener":
        first = sent["segs"][0]
        if first[1]:  # starts with a cut segment already: fall back to a bounded filler
            kind = "bounded"
        else:
            first[0] = _lower_first(first[0])
            sent["segs"].insert(0, [rng.choice(FILLER_OPENER[lang]), True, "filler"])
            return
    keep = [i for i, s in enumerate(sent["segs"]) if not s[1] and _INNER_SPACE.search(s[0])]
    if not keep:
        return
    i = rng.choice(keep)
    text = sent["segs"][i][0]
    gap = rng.choice(list(_INNER_SPACE.finditer(text))).start()
    if kind == "interjection":
        left, cut, right = text[: gap + 1], rng.choice(FILLER_INTERJECTION[lang]), text[gap + 1:]
    else:
        left, cut, right = text[:gap], rng.choice(FILLER_BOUNDED[lang]), text[gap:]
    sent["segs"][i: i + 1] = [[left, False, ""], [cut, True, "filler"], [right, False, ""]]


def _ask_targets(sents: list[dict[str, Any]], taken: set[int]) -> list[int]:
    return [i for i, s in enumerate(sents) if s["ask"] and i not in taken and not s["segs"][0][1]]


def _inject_repetition(sents: list[dict[str, Any]], rng: random.Random, taken: set[int]) -> None:
    targets = _ask_targets(sents, taken)
    if not targets:
        return
    i = rng.choice(targets)
    taken.add(i)
    first = sents[i]["segs"][0]
    words = first[0].split(" ")
    k = rng.choice([1, 2]) if len(words) > 3 and words[1].isalpha() else 1
    sep = ", " if k == 1 else rng.choice([" ", ", "])
    copy = " ".join(words[:k])
    first[0] = _lower_first(first[0])
    sents[i]["segs"].insert(0, [copy + sep, True, "repetition"])


def _inject_false_start(sents: list[dict[str, Any]], rng: random.Random, taken: set[int]) -> None:
    targets = _ask_targets(sents, taken)
    if not targets:
        return
    i = rng.choice(targets)
    taken.add(i)
    word = re.match(r"[^\W\d_]+", sents[i]["segs"][0][0])
    if word is None:
        return
    w = word.group(0)
    sents[i]["segs"].insert(0, [w[: max(2, len(w) // 2)] + "- ", True, "false_start"])


def _insert_sentence(sents: list[dict[str, Any]], text: str, cut: bool, family: str,
                     rng: random.Random) -> None:
    sents.insert(rng.randint(0, len(sents)),
                 {"role": "aside" if cut else "context", "ask": None, "segs": [[text, cut, family]]})


def build_case(base: dict[str, Any], family: str, rng: random.Random) -> dict[str, Any]:
    lang = base["lang"]
    if family == "mixed":
        while True:
            families = sorted(rng.sample(MIXABLE, 3))
            if not {"repetition", "false_start"} <= set(families):
                break
    else:
        families = [] if family == "clean" else [family]
    correction = rng.choice(CORRECTION_MARKERS[lang]) if "self_correction" in families else None
    sents = _sentences(base, correction)
    taken: set[int] = set()
    for fam in families:
        if fam == "filler":
            _inject_filler(sents, lang, rng)
            _inject_filler(sents, lang, rng)
        elif fam == "repetition":
            _inject_repetition(sents, rng, taken)
        elif fam == "false_start":
            _inject_false_start(sents, rng, taken)
    for fam in families:
        if fam == "aside_lexicon":
            _insert_sentence(sents, rng.choice(ASIDE_LEXICON[lang]), True, fam, rng)
        elif fam == "aside_open":
            _insert_sentence(sents, rng.choice(ASIDE_OPEN[lang]), True, fam, rng)
        elif fam == "distractor":
            _insert_sentence(sents, rng.choice(DISTRACTORS[lang]), False, fam, rng)
        elif fam == "vague":
            _insert_sentence(sents, rng.choice(VAGUE[lang]), False, fam, rng)

    text, cuts, asks, asides = "", [], {}, []
    for n, sent in enumerate(sents):
        if n:
            text += " "
        start = len(text)
        for seg, cut, fam in sent["segs"]:
            s = len(text)
            text += seg
            if cut:
                cuts.append([s, len(text), fam])
            elif sent["ask"]:
                asks.setdefault(sent["ask"], []).append([s, len(text)])
        if sent["role"] == "aside":
            asides.append([start, len(text)])
    return {
        "id": f"{base['id']}-{family}",
        "base": base["id"],
        "lang": lang,
        "split": _split(base),
        "family": family,
        "families": families,
        "text": text,
        "cuts": cuts,
        "asks": [asks[k] for k in sorted(asks)],
        "asides": asides,
    }


def generate() -> dict[str, Any]:
    rng = random.Random(SEED)
    cases = [build_case(base, fam, rng) for base in BASES for fam in FAMILIES]
    return {"version": VERSION, "seed": SEED, "cases": cases}


# --- running a system ----------------------------------------------------------------------


def _code_fingerprint(src: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((src / "lcc" / "intake").glob("*.py")):
        digest.update(path.name.encode() + path.read_bytes())
    digest.update((src / "lcc" / "cleaning" / "speech.py").read_bytes())
    return digest.hexdigest()


def rebuild(cleaned: str, removals: list[tuple[int, int, str]]) -> str:
    """Raw input from the cleaned text plus the receipt (spans in raw coordinates)."""
    out, cursor_out, cursor_raw = [], 0, 0
    for start, end, text in sorted(removals):
        keep = start - cursor_raw
        out.append(cleaned[cursor_out: cursor_out + keep])
        out.append(text)
        cursor_out += keep
        cursor_raw = end
    out.append(cleaned[cursor_out:])
    return "".join(out)


def run_case(case: dict[str, Any], arm: str) -> dict[str, Any]:
    from lcc.intake import LccIntake
    from lcc.token_budget import count_tokens

    kwargs: dict[str, Any] = {"optimize_context": False}
    if arm == "L12":
        kwargs["judge_roles"] = True
    text = case["text"]
    result = LccIntake(**kwargs).process(text)
    cleaning = result.speech_cleaning
    removals = [(r.start, r.end, r.text) for r in cleaning.removals] if cleaning else []
    cleaned = cleaning.text if cleaning else text
    brief = result.parsed.brief
    asks = [a for a in getattr(brief, "asks", []) or [] if a] or [brief.objective]
    items = asks + list(brief.constraints) + ([brief.context] if brief.context else [])
    extract = getattr(result, "extract", None)
    verbatim = None
    if extract is not None:
        verbatim = all(
            "".join(text[s:e] for s, e in item.spans) == item.text for item in extract
        )
    roles = getattr(result, "roles", None)
    return {
        "id": case["id"],
        "cut": [[s, e] for s, e, _ in removals],
        "kinds": [r.kind for r in cleaning.removals] if cleaning else [],
        "asks": asks,
        "items": items,
        "questions": list(result.parsed.questions),
        "readiness": result.parsed.readiness.value,
        "detected": bool(result.dictation and result.dictation.detected),
        "tokens_before": count_tokens(text, MODEL).value,
        "tokens_after": count_tokens(cleaned, MODEL).value,
        "reconstruct_ok": rebuild(cleaned, removals) == text,
        "verbatim_ok": verbatim,
        "roles_degraded": None if roles is None else bool(roles.degraded),
        "jev_model": None if roles is None else roles.model,
    }


# --- scoring -------------------------------------------------------------------------------
_PT = {"que", "qual", "quais", "você", "os", "as", "é", "de", "do", "da", "para", "uma", "não",
       "isso", "como", "em", "ou", "cada", "pedido"}
_EN = {"the", "what", "which", "is", "are", "you", "should", "an", "of", "to", "do", "this",
       "how", "in", "or", "each", "request"}


def question_lang(text: str) -> str:
    words = [w.lower() for w in _WORD.findall(text)]
    pt, en = sum(w in _PT for w in words), sum(w in _EN for w in words)
    return "pt" if pt > en else "en" if en > pt else "unknown"


def _tokens(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _WORD.finditer(text)]


def _mask(n: int, spans: list[list[int]]) -> bytearray:
    mask = bytearray(n)
    for s, e in spans:
        mask[s:e] = b"\x01" * (e - s)
    return mask


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def _subsequence(needle: list[str], hay: list[str]) -> bool:
    it = iter(hay)
    return all(any(w == h for h in it) for w in needle)


def _contiguous(needle: list[str], hay: list[str]) -> bool:
    n = len(needle)
    return n > 0 and any(hay[i: i + n] == needle for i in range(len(hay) - n + 1))


def score(cases: list[dict[str, Any]], records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for split in ("dev", "test", "all"):
        chosen = [c for c in cases if split in ("all", c["split"])]
        tp = fp = fn = keep_tokens = 0
        fam_gold: dict[str, int] = {}
        fam_hit: dict[str, int] = {}
        asks_total = asks_survived = asks_recalled = 0
        brief_items = brief_items_matched = 0
        leaks = q_cases = q_match = needs_intake = non_vague = 0
        detected_noisy = noisy = detected_clean = clean = 0
        recon = verbatim = verbatim_n = tok_before = tok_after = 0
        for case in chosen:
            rec = records[case["id"]]
            text = case["text"]
            gold = _mask(len(text), [c[:2] for c in case["cuts"]])
            pred = _mask(len(text), rec["cut"])
            fam_of = {}
            for s, e, fam in case["cuts"]:
                for t in _tokens(text[s:e]):
                    fam_of[(s + t[0], s + t[1])] = fam
            for s, e in _tokens(text):
                g, p = all(gold[s:e]), all(pred[s:e])
                tp += g and p
                fp += p and not g
                fn += g and not p
                keep_tokens += not g
                if g:
                    fam = fam_of.get((s, e), "?")
                    fam_gold[fam] = fam_gold.get(fam, 0) + 1
                    fam_hit[fam] = fam_hit.get(fam, 0) + p
            ask_items = [_words(a) for a in rec["asks"]]
            for spans in case["asks"]:
                asks_total += 1
                offsets = [(s + a, s + b) for s, e in spans for a, b in _tokens(text[s:e])]
                asks_survived += not any(any(pred[a:b]) for a, b in offsets)
                needle = [text[a:b].lower() for a, b in offsets]
                asks_recalled += any(_subsequence(needle, item) for item in ask_items)
            gold_asks = [[text[s + a: s + b].lower() for s, e in spans
                          for a, b in _tokens(text[s:e])] for spans in case["asks"]]
            for item in ask_items:
                brief_items += 1
                brief_items_matched += any(_subsequence(g, item) for g in gold_asks if g)
            all_items = [_words(i) for i in rec["items"]]
            leaks += any(_contiguous(_words(text[s:e]), item)
                         for s, e in case["asides"] for item in all_items)
            if rec["questions"]:
                q_cases += 1
                q_match += all(question_lang(q) == case["lang"] for q in rec["questions"])
            if "vague" not in case["families"]:
                non_vague += 1
                needs_intake += rec["readiness"] == "NEEDS_INTAKE"
            if case["family"] == "clean":
                clean += 1
                detected_clean += rec["detected"]
            elif case["cuts"]:
                noisy += 1
                detected_noisy += rec["detected"]
            recon += rec["reconstruct_ok"]
            if rec["verbatim_ok"] is not None:
                verbatim_n += 1
                verbatim += rec["verbatim_ok"]
            tok_before += rec["tokens_before"]
            tok_after += rec["tokens_after"]
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        out[split] = {
            "cases": len(chosen),
            "cut_tokens_gold": tp + fn,
            "cut_precision": round(precision, 4),
            "cut_recall": round(recall, 4),
            "cut_f1": round(2 * precision * recall / (precision + recall), 4)
            if precision + recall else 0.0,
            "false_cut_rate_on_keep_tokens": round(fp / keep_tokens, 4) if keep_tokens else 0.0,
            "recall_by_family": {f: round(fam_hit.get(f, 0) / n, 4)
                                 for f, n in sorted(fam_gold.items())},
            "ask_survival": round(asks_survived / asks_total, 4),
            "asks": asks_total,
            "brief_ask_recall": round(asks_recalled / asks_total, 4),
            "brief_ask_precision": round(brief_items_matched / brief_items, 4)
            if brief_items else 0.0,
            "aside_leak_cases": leaks,
            "question_lang_match": round(q_match / q_cases, 4) if q_cases else None,
            "cases_with_questions": q_cases,
            "false_needs_intake_rate": round(needs_intake / non_vague, 4) if non_vague else 0.0,
            "detection_rate_noisy": round(detected_noisy / noisy, 4) if noisy else None,
            "detection_rate_clean": round(detected_clean / clean, 4) if clean else None,
            "reconstruct_rate": round(recon / len(chosen), 4),
            "verbatim_rate": round(verbatim / verbatim_n, 4) if verbatim_n else None,
            "tokens_before": tok_before,
            "tokens_after": tok_after,
            "token_reduction": round(1 - tok_after / tok_before, 4) if tok_before else 0.0,
        }
    return out


# --- commands ------------------------------------------------------------------------------


def cmd_generate(_: argparse.Namespace) -> int:
    data = json.dumps(generate(), ensure_ascii=False, indent=1) + "\n"
    CASES_PATH.write_text(data, encoding="utf-8")
    print(f"{CASES_PATH.name}: {len(json.loads(data)['cases'])} cases, "
          f"sha256 {hashlib.sha256(data.encode()).hexdigest()}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    src = Path(args.src).resolve() if args.src else ROOT / "src"
    sys.path.insert(0, str(src))
    if args.arm == "L12":
        os.environ.pop("LCC_DISABLE_NETWORK", None)
        private = Path.home() / ".lcc" / "bench" / VERSION
        private.mkdir(parents=True, exist_ok=True)
        # The shared fleet ledger stays untouched; this run keeps its own.
        os.environ["LCC_TS_LEDGER"] = str(private / "jev.jsonl")
    else:
        os.environ["LCC_DISABLE_NETWORK"] = "1"
    raw = CASES_PATH.read_bytes()
    cases = json.loads(raw)["cases"]
    records = {c["id"]: run_case(c, args.arm) for c in cases}
    import lcc

    result = {
        "version": VERSION,
        "arm": args.arm,
        "label": args.label,
        "cases_sha256": hashlib.sha256(raw).hexdigest(),
        "code_sha256": _code_fingerprint(src),
        "lcc_file": str(Path(lcc.__file__).resolve().relative_to(src.parent)),
        "metrics": score(cases, records),
        "per_case": records,
    }
    out = HERE / f"results-{args.arm}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"arm": args.arm, "test": result["metrics"]["test"]}, indent=1))
    return 0


_ROWS = [
    ("cut_precision", "cut precision"), ("cut_recall", "cut recall"), ("cut_f1", "cut F1"),
    ("false_cut_rate_on_keep_tokens", "false cuts / keep tokens"),
    ("ask_survival", "ask survival"), ("brief_ask_recall", "brief ask recall"),
    ("brief_ask_precision", "brief ask precision"), ("aside_leak_cases", "aside leaks (cases)"),
    ("question_lang_match", "questions in input language"),
    ("false_needs_intake_rate", "false NEEDS_INTAKE"),
    ("detection_rate_noisy", "dictation detected (noisy)"),
    ("detection_rate_clean", "dictation detected (clean)"),
    ("reconstruct_rate", "rebuilt byte for byte"), ("verbatim_rate", "brief spans verbatim"),
    ("token_reduction", "token reduction"),
]


def cmd_report(args: argparse.Namespace) -> int:
    arms = [a for a in ("A0", "L1", "L12") if (HERE / f"results-{a}.json").exists()]
    data = {a: json.loads((HERE / f"results-{a}.json").read_text("utf-8")) for a in arms}
    for split in ("test", "dev"):
        print(f"\n### {split} split\n")
        print("| metric | " + " | ".join(arms) + " |")
        print("| :--- | " + " | ".join("---:" for _ in arms) + " |")
        for key, label in _ROWS:
            cells = [data[a]["metrics"][split][key] for a in arms]
            print(f"| {label} | " + " | ".join("n/a" if c is None else str(c) for c in cells) + " |")
        fams = sorted({f for a in arms for f in data[a]["metrics"][split]["recall_by_family"]})
        for fam in fams:
            cells = [data[a]["metrics"][split]["recall_by_family"].get(fam) for a in arms]
            print(f"| recall: {fam} | " + " | ".join(str(c) for c in cells) + " |")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("generate").set_defaults(func=cmd_generate)
    run = sub.add_parser("run")
    run.add_argument("--arm", choices=["A0", "L1", "L12"], required=True)
    run.add_argument("--src", help="lcc src directory to import (default: this checkout)")
    run.add_argument("--label", default="", help="free text recorded in the result, e.g. a commit")
    run.set_defaults(func=cmd_run)
    sub.add_parser("report").set_defaults(func=cmd_report)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
