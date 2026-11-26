"""Private screening list for the owner: mark `[x]` on memos that are prompts. Prints counts only.

usage: python voice_screen.py write   -> voice/screen.md (0600, owner reads and edits it)
       python voice_screen.py count   -> counts of marked memos by bounds and flags (no text)
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

VOICE = Path.home() / ".lcc-private" / "intake-distill-v1" / "voice"
SCREEN = VOICE / "screen.md"
LINE = re.compile(r"^- \[([ xX])\] `([0-9a-f]{64})`")


def flags(m: dict) -> list[str]:
    out = []
    if not 100 <= m["words"] <= 3000:  # 1,500 until the 2026-11-26 change (PROTOCOL)
        out.append("fora_100_3000")
    if not 60 <= m["wpm"] <= 220 or m["repeat4"] > 0.05:
        out.append("transcricao_suspeita")
    return out


def write() -> None:
    manifest = json.loads((VOICE / "manifest.json").read_text())
    rows = [
        "# Quais gravações são prompts?",
        "",
        "Marque `[x]` nas que são pedidos para uma IA. Salve o arquivo.",
        "",
    ]
    for key, m in sorted(manifest.items(), key=lambda kv: kv[1]["created"]):
        head = " ".join((VOICE / f"{key}.txt").read_text(encoding="utf-8").split()[:30])
        when = dt.datetime.fromtimestamp(m["created"]).strftime("%Y-%m-%d")
        f = ", ".join(flags(m)) or "ok"
        rows.append(
            f"- [ ] `{key}` **{m['file']}** · {when} · {m['seconds'] / 60:.1f} min · {m['words']} palavras · {f}"
        )
        rows.append(f"  > {head}…")
    if SCREEN.exists():
        raise SystemExit(f"refused: {SCREEN} exists; the owner may have marked it")
    tmp = SCREEN.with_suffix(".md.tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")
    os.link(
        tmp, SCREEN
    )  # publishes the complete file, fails if the owner's copy appeared meanwhile
    tmp.unlink()
    print(f"wrote {len(manifest)} rows")


def count() -> None:
    manifest = json.loads((VOICE / "manifest.json").read_text())
    marked = [
        k
        for line in SCREEN.read_text(encoding="utf-8").splitlines()
        if (m := LINE.match(line)) and m[1] != " "
        for k in [m[2]]
    ]
    ok = [k for k in marked if not flags(manifest[k])]
    print(f"marked {len(marked)} of {len(manifest)}; within bounds and clean {len(ok)}")


if __name__ == "__main__":
    {"write": write, "count": count}[sys.argv[1]]()
