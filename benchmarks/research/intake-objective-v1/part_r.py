#!/usr/bin/env python3
"""Part R of intake-objective-v1: the owner's real dictations (PROTOCOL.md, Amendment 4).

    python benchmarks/research/intake-objective-v1/part_r.py collect
    python benchmarks/research/intake-objective-v1/part_r.py run [--labels PATH]

``collect`` draws the candidate pool from the owner's Claude Code transcripts and writes it, with a
local labelling page, to ``~/.lcc-private/intake-objective-v1/``. It runs no arm: the page shows the
parser's sentence split and nothing else. ``run`` scores A0, A1 and D on the dictations the owner
labelled, after checking that D is the frozen D. Texts and per-case results never leave the private
folder; the repository gets aggregate numbers only (``stats_r.json``). DJ is not here: it needs the
owner's yes and its own amendment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_arms  # noqa: E402
from run_arms import HERE, WEIGHTS, hit  # noqa: E402

from lcc.intake import parser as intake_parser  # noqa: E402
from lcc.intake import speech as intake_speech  # noqa: E402
from lcc.intake.objective import analyse, choose  # noqa: E402
from lcc.session_report import INJECTED  # noqa: E402

PRIVATE = Path.home() / ".lcc-private" / "intake-objective-v1"
TRANSCRIPTS = Path.home() / ".claude" / "projects"
SEED = 20261116
MIN_WORDS = 300
GOAL = 25  # the owner stops once this many are kept
TARGET = (20, 30)  # PROTOCOL.md, Part R: 20 to 30 dictations
Z = 1.96
#: Amendment 2 pins the sentence split every arm shares; the page must show that split.
PARSER_SHA256 = "91ed1cc255e4bd35bb3e9de5216f2f6461ef6af634977008ccb6339908834346"
SPEECH_SHA256 = "f9b2fd0ff9e295f4cea7350878be903fd00eb4f895063adae450616087a00c15"
SKIP_REASONS = ("não foi ditado", "sensível", "não tem um pedido principal")
INSTRUCTION = (
    "Esta é uma mensagem longa que você mandou para um assistente de IA. Ela mistura contexto, "
    "pedidos laterais e pensamento em voz alta com o pedido que você mais precisava que fosse "
    "feito. Clique na frase que traz esse pedido principal. Se ele aparece em mais de uma frase "
    "(repetido no fim, por exemplo), marque cada uma. Não marque os pedidos laterais."
)

# App-injected reminders may wrap a human message: only these are stripped, and only at either
# end. The trailing pattern may not cross another opening tag, so it never eats human text.
_LEADING = re.compile(r"^\s*<system-reminder>.*?</system-reminder>\s*", re.S)
_TRAILING = re.compile(
    r"\s*<system-reminder>(?:(?!<system-reminder>).)*</system-reminder>\s*$", re.S
)
# Anything else that marks pasted or generated content drops the message rather than editing it:
# the wrappers lcc already knows (session_report.INJECTED), any tag whose name has a hyphen or an
# underscore (how apps and hooks name their wrappers), and code fences.
_MARKUP = re.compile(
    "|".join(re.escape(marker) for marker in INJECTED) + r"|</?[A-Za-z]+[-_][\w-]*[\s>/]|```"
)


def _sha(data: str | bytes) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def _text(content: Any) -> str | None:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        return "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return None


def candidate(entry: dict[str, Any]) -> tuple[str | None, str]:
    """``(text, "ok")`` when one transcript entry is a long message the owner typed or dictated,
    else ``(None, why)``."""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
        return None, "not a typed message"
    if entry.get("isCompactSummary"):
        return None, "not a typed message"
    origin = entry.get("origin") if isinstance(entry.get("origin"), dict) else {}
    if entry.get("turnOrigin") != "human" and origin.get("kind") != "human":
        return None, "not a typed message"  # rows with no origin tag are left out, not guessed
    message = entry.get("message") or {}
    text = _text(message.get("content")) if message.get("role") == "user" else None
    if not text:
        return None, "not a typed message"
    while True:
        stripped = _TRAILING.sub("", _LEADING.sub("", text, count=1), count=1)
        if stripped == text:
            break
        text = stripped
    if len(text.split()) < MIN_WORDS:
        return None, "short"
    if _MARKUP.search(text):
        return None, "markup"
    return text, "ok"


def _check_parser() -> None:
    for module, sha in ((intake_parser, PARSER_SHA256), (intake_speech, SPEECH_SHA256)):
        if _sha(Path(module.__file__).read_bytes()) != sha:
            raise SystemExit(
                f"refused: {Path(module.__file__).name} is not the one Amendment 2 pins"
            )


def collect(transcripts: Path, out: Path) -> dict[str, Any]:
    """Write ``candidates.json`` and ``label.html`` to ``out`` and return the filter counts.
    Runs no arm. Refuses when a pool exists: a new pool would reorder the one being labelled."""
    if (out / "candidates.json").exists():
        raise SystemExit("refused: candidates.json exists; the pool is drawn once")
    _check_parser()
    pool: dict[str, dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    for path in sorted(transcripts.glob("*/*.jsonl")):
        with path.open(
            encoding="utf-8", errors="replace"
        ) as lines:  # line by line: files are large
            for line in lines:
                if '"human"' not in line:  # every kept entry carries an origin tagged "human"
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                text, why = candidate(entry)
                if why != "not a typed message":
                    counts[why] += 1
                if text is None:
                    continue
                sha = _sha(text)
                if sha in pool:
                    counts["duplicate"] += 1
                    continue
                spans = [item.spans[0] for item in intake_parser.parse_intake(text).extract]
                pool[sha] = {
                    "id": sha[:12],
                    "sha256": sha,
                    "session": entry.get("sessionId", ""),
                    "timestamp": entry.get("timestamp", ""),
                    "words": len(text.split()),
                    "text": text,
                    "sentences": [list(s) for s in spans],
                }
    items = sorted(pool.values(), key=lambda c: c["sha256"])
    random.Random(SEED).shuffle(items)  # the order the owner works through, top down
    counts["candidates"] = len(items)
    for folder in (out.parent, out):
        folder.mkdir(parents=True, exist_ok=True)
        os.chmod(folder, 0o700)
    meta = {
        "seed": SEED,
        "min_words": MIN_WORDS,
        "parser_sha256": PARSER_SHA256,
        "counts": dict(counts),
    }
    _write_private(
        out / "candidates.json", json.dumps({**meta, "items": items}, ensure_ascii=False, indent=1)
    )
    # The page keys its saved progress to this exact ordered pool.
    pool_id = _sha("\n".join(c["sha256"] for c in items))[:16]
    page = {"instruction": INSTRUCTION, "reasons": SKIP_REASONS, "goal": GOAL, "pool": pool_id}
    page["items"] = items
    # No "<" may reach the script block raw: message text could otherwise end or reopen it.
    payload = json.dumps(page, ensure_ascii=False).replace("<", "\\u003c")
    _write_private(out / "label.html", PAGE.replace("__DATA__", payload))
    return dict(counts)


def _write_private(path: Path, text: str, mode: int = 0o600) -> None:
    """Write ``text`` atomically: a fresh temporary file (created exclusively, owner-only)
    replaces ``path``, so a stale or planted temporary is never reused and a reader never sees
    half a file. ``mode`` widens the result only for the public aggregates."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def wilson(k: int, n: int) -> dict[str, float]:
    """Wilson score interval for k hits in n, z = 1.96."""
    p = k / n
    centre = (p + Z * Z / (2 * n)) / (1 + Z * Z / n)
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / (1 + Z * Z / n)
    return {
        "k": k,
        "n": n,
        "rate": round(p, 4),
        "lo": round(max(0.0, centre - half), 4),
        "hi": round(min(1.0, centre + half), 4),
    }


def labelled(
    candidates: dict[str, Any], labels: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """The dictations the owner kept, with their gold spans, and the skip counts, after checking
    the labelling rules: top down with no gap, a listed reason for each skip, and gold spans that
    are sentences of the pinned parser."""
    if candidates.get("parser_sha256") != PARSER_SHA256:
        raise SystemExit("refused: the candidates were split by another parser")
    items = candidates["items"]
    decided = {d["id"]: d for d in labels["items"]}
    order = [c["id"] for c in items]
    if set(decided) - set(order):
        raise SystemExit("refused: labels name candidates that are not in the pool")
    last = max((order.index(i) for i in decided), default=-1)
    if any(i not in decided for i in order[: last + 1]):
        raise SystemExit("refused: labels must cover the candidates top down, with no gap")
    kept, skips = [], Counter()
    for c in items[: last + 1]:
        d = decided[c["id"]]
        if d.get("sha256") != c["sha256"] or _sha(c["text"]) != c["sha256"]:
            raise SystemExit(f"refused: {c['id']} was labelled on another text")
        if d.get("decision") == "skip":
            if d.get("reason") not in SKIP_REASONS:
                raise SystemExit(f"refused: {c['id']} skipped without a listed reason")
            skips[d["reason"]] += 1
            continue
        gold = d.get("gold") if d.get("decision") == "use" else None
        if not gold or any(list(g) not in c["sentences"] for g in gold):
            raise SystemExit(f"refused: {c['id']} is kept without gold sentences from the page")
        kept.append({"id": c["id"], "text": c["text"], "main": [list(g) for g in gold]})
    if not TARGET[0] <= len(kept) <= TARGET[1]:
        raise SystemExit(f"refused: {len(kept)} dictations kept, the protocol asks for 20 to 30")
    return kept, dict(skips)


def score(cases: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """A0, A1 and D on the labelled dictations: per-case rows (private) and aggregates (public).
    D is scored by Amendment 2's own ``score_d``; Part R has no support labels and labels only the
    main ask, so its ask-recall and support columns are not read."""
    rows = []
    for case in cases:
        a = analyse(case["text"])
        pick = choose(a, WEIGHTS)
        a0, a1 = run_arms._baselines(a)
        d = run_arms.score_d({**case, "asks": [case["main"]], "support": []}, a, pick)
        rows.append(
            {
                "id": case["id"],
                "A0": hit(a0, case["main"]),
                "A1": hit(a1, case["main"]),
                "D": d["hit"],
                "D_hit3": d["hit3"],
                "D_fallback": d["fallback"],
                "D_rebuilds": d["rebuilds"],
                "D_brief_ratio": d["brief_ratio"],
                # Share of the gold sentences the parser marks as asks: no arm can pick the rest.
                "gold_is_ask": d["asks_labelled"],
                "D_span": list(pick.objective_span),
                "golds": len(case["main"]),
            }
        )
    n = len(rows)
    summary = {
        "n": n,
        **{arm: wilson(sum(r[arm] for r in rows), n) for arm in ("A0", "A1", "D", "D_hit3")},
        "D_fallbacks": sum(r["D_fallback"] for r in rows),
        "D_rebuilds_all": all(r["D_rebuilds"] for r in rows),
        "D_brief_ratio_mean": round(sum(r["D_brief_ratio"] for r in rows) / n, 4),
        "cases_with_gold_never_an_ask": sum(r["gold_is_ask"] == 0 for r in rows),
        "cases_with_two_or_more_golds": sum(r["golds"] > 1 for r in rows),
        "ask_recall": "not computed: Part R labels only the main ask",
    }
    return rows, summary


def cmd_collect(args: argparse.Namespace) -> int:
    print(json.dumps(collect(TRANSCRIPTS, PRIVATE)))
    print(f"label page: {PRIVATE / 'label.html'}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    out = HERE / "stats_r.json"
    if out.exists():
        print("refused: stats_r.json exists; Part R runs once")
        return 2
    if run_arms._code_sha256() != run_arms.FROZEN_OBJECTIVE_SHA256 or (
        run_arms.run("dev", WEIGHTS)["summary"]["d_sha256"] != run_arms.FROZEN_D_SHA256
    ):
        print("refused: D is not the frozen D (code or dev output differ from Amendment 2)")
        return 2
    _check_parser()
    candidates = json.loads((PRIVATE / "candidates.json").read_text(encoding="utf-8"))
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    kept, skips = labelled(candidates, labels)
    rows, summary = score(kept)
    summary = {"pool": candidates["counts"], "skipped": skips, **summary}
    _write_private(
        PRIVATE / "results_r.json", json.dumps({"rows": rows, "summary": summary}, indent=1)
    )
    _write_private(out, json.dumps(summary, indent=1, ensure_ascii=False) + "\n", mode=0o644)
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(required=True)
    sub.add_parser("collect").set_defaults(func=cmd_collect)
    run = sub.add_parser("run")
    run.add_argument("--labels", default=str(PRIVATE / "labels.json"))
    run.set_defaults(func=cmd_run)
    args = parser.parse_args(argv)
    return int(args.func(args))


# The labelling page: one file, no network, texts rendered with textContent only.
PAGE = r"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Part R: rótulos</title>
<style>
:root{--bg:#0b0f17;--card:#141b27;--ink:#e6ebf2;--mute:#8a97ab;--line:#26324a;--pick:#2f6fed;--skip:#a33b3b;--ok:#2e8b57}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.6 -apple-system,system-ui,sans-serif}
main{max-width:860px;margin:0 auto;padding:16px}
header{position:sticky;top:0;background:var(--bg);padding:12px 0;border-bottom:1px solid var(--line);z-index:1}
.meta{color:var(--mute);font-size:14px}.text{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:12px 0;white-space:pre-wrap}
.s{cursor:pointer;border-radius:4px;padding:1px 2px;border-bottom:1px dashed #3a4a6a}.s:hover{background:#1e2a40}.s.on{background:var(--pick);color:#fff}
.actions{position:sticky;bottom:0;background:var(--bg);padding:6px 0 10px;border-top:1px solid var(--line)}
button{font:inherit;font-size:16px;border:0;border-radius:10px;padding:12px 14px;margin:6px 6px 0 0;cursor:pointer;color:#fff;background:#33415c}
button.use{background:var(--ok)}button.skip{background:var(--skip)}button:disabled{opacity:.4;cursor:not-allowed}
textarea{width:100%;height:140px;background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:10px;padding:8px;font:13px monospace}
</style></head><body><main>
<header><div id="progress"></div><div class="meta" id="instruction"></div></header>
<section id="card"></section>
<section><h3>Exportar</h3><button id="copy">Copiar rótulos</button><button id="download">Baixar labels.json</button>
<p class="meta">Se copiar não funcionar, o JSON está aqui embaixo.</p><textarea id="out" readonly></textarea></section>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById("data").textContent);
const KEY = "lcc-part-r-" + D.pool;
let st = {}; try { st = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { st = {}; }
function save() { try { localStorage.setItem(KEY, JSON.stringify(st)); } catch (e) {} render(); }
function used() { return D.items.filter(c => st[c.id] && st[c.id].decision === "use").length; }
function current() { return D.items.findIndex(c => !st[c.id]); }
function exportJSON() {
  const items = D.items.filter(c => st[c.id]).map(c => Object.assign({id: c.id, sha256: c.sha256}, st[c.id]));
  return JSON.stringify({version: 1, items: items}, null, 1);
}
let sel = new Set(), shown = null;
function render() {
  document.getElementById("instruction").textContent = D.instruction;
  const i = current(), n = used();
  if (i !== shown) { shown = i; window.scrollTo(0, 0); }  // a new message starts at its top
  document.getElementById("progress").textContent =
    "Usados: " + n + " de " + D.goal + " | decididos: " + D.items.filter(c => st[c.id]).length + " de " + D.items.length;
  document.getElementById("out").value = exportJSON();
  const card = document.getElementById("card"); card.replaceChildren();
  const prev = i < 0 ? D.items.length - 1 : i - 1;
  const back = document.createElement("button"); back.textContent = "Desfazer o anterior";
  back.disabled = prev < 0 || !st[D.items[prev].id];
  back.onclick = () => { delete st[D.items[prev].id]; sel = new Set(); save(); };
  if (n >= D.goal || i < 0) {
    const p = document.createElement("p"); p.textContent = "Pronto. Baixe ou copie os rótulos abaixo.";
    card.append(p, back); return;
  }
  const c = D.items[i];
  const meta = document.createElement("div"); meta.className = "meta";
  meta.textContent = "#" + (i + 1) + " · " + String(c.timestamp).slice(0, 10) + " · " + c.words + " palavras";
  const box = document.createElement("div"); box.className = "text";
  // Spans count code points, as Python does; a JS string slices UTF-16 units.
  const cp = Array.from(c.text), cut = (s, e) => cp.slice(s, e).join("");
  let at = 0;
  c.sentences.forEach(([s, e], k) => {
    if (s > at) box.append(document.createTextNode(cut(at, s)));
    const span = document.createElement("span"); span.className = "s" + (sel.has(k) ? " on" : "");
    span.textContent = cut(s, e);
    span.onclick = () => { sel.has(k) ? sel.delete(k) : sel.add(k); render(); };
    box.append(span); at = e;
  });
  if (at < cp.length) box.append(document.createTextNode(cut(at)));
  const row = document.createElement("div"); row.className = "actions";
  const use = document.createElement("button"); use.className = "use";
  use.textContent = "Usar (frases marcadas: " + sel.size + ")"; use.disabled = sel.size === 0;
  use.onclick = () => { st[c.id] = {decision: "use", gold: [...sel].sort((a, b) => a - b).map(k => c.sentences[k])}; sel = new Set(); save(); };
  row.append(use);
  D.reasons.forEach(r => {
    const b = document.createElement("button"); b.className = "skip"; b.textContent = "Pular: " + r;
    b.onclick = () => { st[c.id] = {decision: "skip", reason: r}; sel = new Set(); save(); };
    row.append(b);
  });
  row.append(back);
  card.append(meta, box, row);
}
document.getElementById("copy").onclick = async () => {
  try { await navigator.clipboard.writeText(exportJSON()); } catch (e) { document.getElementById("out").select(); }
};
document.getElementById("download").onclick = () => {
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([exportJSON()], {type: "application/json"}));
  a.download = "labels.json"; a.click();
};
render();
</script></body></html>
"""


if __name__ == "__main__":
    sys.exit(main())
