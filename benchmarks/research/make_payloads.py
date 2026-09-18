#!/usr/bin/env python3
"""Build the exact payload each agent arm receives for the real agent A/B run.

Every arm gets the SAME harness, the SAME task and the SAME questions; the only variable is
the context block: raw corpus vs an LCC-transformed artifact. Token counts here are exact
(o200k) so the delivered prompt size per arm is known independently of any provider report.
"""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
CORPORA = ROOT / "corpora"
WORK = ROOT / "work"
PAYLOADS = ROOT / "payloads"
SCALE = "medium"

TASK = """TASK
Answer the five questions below using ONLY the dossier above as evidence.

1. What share of mobile visitors is lost in the booking flow, and at which step?
2. What is the measured p75 mobile load time, and on what profile?
3. What share of inbound messages arrives outside opening hours?
4. How much chair capacity is idle after 17:00, and on which days?
5. How long does front desk spend re-typing each booking, and into what?

Reply with a numbered list, one line per answer, each line carrying the figure.
If the dossier does not contain a fact, write exactly: NOT PRESENT IN EVIDENCE.
Do not use outside knowledge. Do not invent numbers.
"""

ARMS = {
    "raw": CORPORA / f"{SCALE}.md",
    "lcc_jev": WORK / SCALE / "compact_jev" / "context.md",
    "lcc_optimize": WORK / SCALE / "optimize_claude_xml" / "context.md",
}


def main() -> None:
    import tiktoken

    enc = tiktoken.get_encoding("o200k_base")
    PAYLOADS.mkdir(exist_ok=True)
    index = {}
    for arm, path in ARMS.items():
        context = path.read_text(encoding="utf-8")
        payload = f"DOSSIER\n\n{context}\n\n{TASK}"
        (PAYLOADS / f"{arm}.txt").write_text(payload, encoding="utf-8")
        index[arm] = {
            "source": str(path),
            "context_tokens": len(enc.encode(context)),
            "payload_tokens": len(enc.encode(payload)),
            "payload_chars": len(payload),
        }
        print(f"{arm:14} context={index[arm]['context_tokens']:6} payload={index[arm]['payload_tokens']:6} tokens")
    (PAYLOADS / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
