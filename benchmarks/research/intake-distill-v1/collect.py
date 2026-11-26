"""intake-distill-v1 `collect` (PROTOCOL.md, Amendment 1): the training pool and T, drawn once. Prints counts only.

Writes ~/.lcc-private/intake-distill-v1/{pool.json,t.json} (0600). Refuses if either exists or any pin differs.
"""

from __future__ import annotations

import difflib
import glob
import hashlib
import json
import os
import random
import re
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path[:0] = [str(HERE.parent / "intake-objective-v1"), str(REPO / "src")]
import part_r  # noqa: E402
import part_r2  # noqa: E402

from lcc.handoff import mask  # noqa: E402
from lcc.intake import parser as intake_parser  # noqa: E402

PINS = {
    REPO
    / "src/lcc/intake/parser.py": "91ed1cc255e4bd35bb3e9de5216f2f6461ef6af634977008ccb6339908834346",
    REPO / "src/lcc/handoff.py": "9a5d5873eac33cff52f1409c02e14939b4cc27ee2adb0e61c6e73a91637c07b3",
    HERE / "cues.json": "f9e3f574057af27c193b4bfde28b7a7bf8993eafe7e4d259eb6af8f583a9f9de",
    HERE / "voice_screen.py": "c73e59cfa3e5ab4bddb325072ad433aa8cb4c4f19b50adc16aa7d09da43df5bf",
}
VOICE_LIST_SHA = "762f8ba36301296924c917338cd87727a4058b697bc5d26df2a6dfa3c034a52a"
PRIV = Path.home() / ".lcc-private"
OUT = PRIV / "intake-distill-v1"
SEED_T = 20261126
MIN_WORDS = 20
LONG = 200  # census rule for T's typed messages: one paragraph, 200+ words
CENSUS_LONG = 14
LEAK_RATIO = 0.6


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def strip_reminders(text: str) -> str:
    while True:
        s = part_r._TRAILING.sub("", part_r._LEADING.sub("", text, count=1), count=1)
        if s == text:
            return text
        text = s


def claude_code() -> Iterator[tuple[str, str]]:
    part_r2.MIN_WORDS = 1
    for path in sorted(part_r.TRANSCRIPTS.glob("*/*.jsonl")):
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"user"' not in line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(e, dict):
                    text, why, _ = part_r2.candidate(e)
                    yield (
                        ("claude_code", text)
                        if text
                        else ("claude_code", "" if why != "markup" else "\0")
                    )


def jsonl_texts(pattern: str, pick: Any) -> Iterator[str]:
    for f in sorted(glob.glob(os.path.expanduser(pattern), recursive=True)):
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(o, dict) and (t := pick(o)) is not None:
                    yield t


def _blocks(content: Any) -> str:
    return "\n".join(
        b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text"
    )


def codex() -> Iterator[tuple[str, str]]:
    def pick(o: dict[str, Any]) -> str | None:
        it = (o.get("payload") or {}).get("item") or {}
        return _blocks(it.get("content")) if it.get("type") == "UserMessage" else None

    for t in jsonl_texts("~/.codex/sessions/**/*.jsonl", pick):
        t = strip_reminders(t)
        yield "codex", ("\0" if part_r._MARKUP.search(t) else t)


def grok() -> Iterator[tuple[str, str]]:
    def pick(o: dict[str, Any]) -> str | None:
        ok = o.get("type") == "user" and "prompt_index" in o and isinstance(o.get("content"), list)
        return _blocks(o["content"]) if ok else None

    for t in jsonl_texts("~/.grok/sessions/*/*/chat_history.jsonl", pick):
        t = strip_reminders(t)
        yield "grok", ("\0" if part_r._MARKUP.search(t) else t)


def item(text: str, source: str, **extra: Any) -> dict[str, Any]:
    spans = [x.spans[0] for x in intake_parser.parse_intake(text).extract]
    h = sha(text)
    return {"id": h[:12], "sha256": h, "source": source, "words": len(text.split()), "text": text,
            "sentences": [list(s) for s in spans], **extra}  # fmt: skip


def one_paragraph(text: str) -> bool:
    return sum(1 for line in text.split("\n") if line.strip()) == 1


def leaks(text: str, others: list[list[str]]) -> bool:
    """Word-level difflib ratio; char-level on 15K-char memos takes hours."""
    a = text.lower().split()
    for o in others:
        m = difflib.SequenceMatcher(None, a, o, autojunk=False)
        if (
            m.real_quick_ratio() >= LEAK_RATIO
            and m.quick_ratio() >= LEAK_RATIO
            and m.ratio() >= LEAK_RATIO
        ):
            return True
    return False


def write_private(path: Path, data: Any) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def main() -> None:
    for p, want in PINS.items():
        if hashlib.sha256(p.read_bytes()).hexdigest() != want:
            raise SystemExit(f"refused: {p.name} differs from Amendment 1")
    if (OUT / "pool.json").exists() or (OUT / "t.json").exists():
        raise SystemExit("refused: pool.json or t.json exists; collect runs once")
    c: Counter[str] = Counter()

    # Earlier study pools: dev (Part R, used), R3 (T), and the leftovers that join the training pool.
    dev_c = json.loads((PRIV / "intake-objective-v1/candidates.json").read_text())["items"]
    labels = {
        x["id"]: x["decision"]
        for x in json.loads((PRIV / "intake-objective-v1/labels.json").read_text())["items"]
    }
    dev = [x for x in dev_c if labels.get(x["id"]) == "use"]
    r_skipped = [x for x in dev_c if labels.get(x["id"]) != "use"]
    r3 = json.loads((PRIV / "intake-objective-v1-r3/candidates.json").read_text())["items"]
    r2 = json.loads((PRIV / "intake-objective-v1-r2/candidates.json").read_text())["items"]
    if len(dev) != 22 or len(r3) != 24:
        raise SystemExit(f"refused: dev {len(dev)} r3 {len(r3)}, expected 22 and 24")
    eval_shas = {x["sha256"] for x in dev + r3}
    all_prior = {
        x["sha256"]
        for p in PRIV.glob("intake-objective-v1*/**/candidates.json")
        for x in json.loads(p.read_text())["items"]
    }

    # Typed messages from the three tools.
    typed: dict[str, dict[str, Any]] = {}
    census_long: list[dict[str, Any]] = []
    for gen in (claude_code, codex, grok):
        for src, text in gen():
            if text == "\0":
                c["markup"] += 1
                continue
            if len(text.split()) < MIN_WORDS:
                continue
            try:
                h = sha(text)
            except UnicodeEncodeError:
                c["unencodable"] += 1
                continue
            if h in typed:
                c["duplicate"] += 1
                continue
            if mask(text) != text:
                c["secret"] += 1
                typed[h] = {}  # seen, never used
                continue
            if h in all_prior:
                c["in_prior_pool"] += 1
                typed[h] = {}
                continue
            typed[h] = item(text, src, multi_line=not one_paragraph(text))
            if one_paragraph(text) and len(text.split()) >= LONG:
                census_long.append(typed[h])
    if len(census_long) != CENSUS_LONG:
        raise SystemExit(
            f"refused: {len(census_long)} long one-paragraph messages, census had {CENSUS_LONG}"
        )

    # Voice memos, as screened and pinned.
    voice = PRIV / "intake-distill-v1/voice"
    manifest = json.loads((voice / "manifest.json").read_text())
    line = re.compile(r"^- \[(.)\] `([0-9a-f]{64})`")
    keys = sorted(
        m[2] for ln in (voice / "screen.md").read_text().splitlines()
        if (m := line.match(ln)) and m[1] != " " and 100 <= manifest[m[2]]["words"] <= 3000
    )  # fmt: skip
    if hashlib.sha256("\n".join(keys).encode()).hexdigest() != VOICE_LIST_SHA:
        raise SystemExit("refused: the marked voice memos differ from Amendment 1")
    memos = [
        item((voice / f"{k}.txt").read_text(encoding="utf-8"), "voice", audio_sha256=k,
             stratum="longo" if manifest[k]["words"] > 1500 else "base")
        for k in keys
    ]  # fmt: skip

    # Training pool: typed messages outside T, plus R2 leftovers and Part R's skipped ones.
    t_shas = eval_shas | {x["sha256"] for x in census_long}
    pool = [x for h, x in typed.items() if x and h not in t_shas]
    pool += [
        item(x["text"], "r2_leftover", multi_line=not one_paragraph(x["text"]))
        for x in r2 + r_skipped
        if sha(x["text"]) not in t_shas
        and mask(x["text"]) == x["text"]  # same secret rule as the logs
    ]
    pool = list({x["sha256"]: x for x in pool}.values())

    # Leakage: a memo that matches a dev, R3 or training message is dropped.
    others = [x["text"].lower().split() for x in dev + r3 + pool]
    kept = [m for m in memos if not leaks(m["text"], others)]
    c["voice_secret"] = sum(
        mask(m["text"]) != m["text"] for m in kept
    )  # reported; the owner decides
    c["voice_leak_dropped"] = len(memos) - len(kept)

    t = [{**x, "origin": "r3", "stratum": "base"} for x in r3]
    t += [{**x, "origin": "census", "stratum": "base"} for x in census_long]
    t += [{**x, "origin": "voice"} for x in kept]
    t = [
        {k: x[k] for k in ("id", "sha256", "origin", "stratum", "words", "text", "sentences")}
        for x in t
    ]
    t.sort(key=lambda x: x["sha256"])
    random.Random(SEED_T).shuffle(t)

    OUT.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Both land or neither: written as .tmp, published by link, which also refuses an existing file.
    for name, data in (("pool.json", {"items": pool}), ("t.json", {"seed": SEED_T, "items": t})):
        (OUT / f"{name}.tmp").unlink(missing_ok=True)
        write_private(OUT / f"{name}.tmp", data)
    for name in ("pool.json", "t.json"):
        os.link(OUT / f"{name}.tmp", OUT / name)
        (OUT / f"{name}.tmp").unlink()
    c["pool_messages"] = len(pool)
    c["pool_multi_line"] = sum(x["multi_line"] for x in pool)
    c["pool_sentences"] = sum(len(x["sentences"]) for x in pool)
    c["t"] = len(t)
    for k, v in Counter((x["origin"], x["stratum"]) for x in t).items():
        c[f"t_{k[0]}_{k[1]}"] = v
    print(json.dumps(dict(sorted(c.items())), indent=1))


if __name__ == "__main__":
    main()
