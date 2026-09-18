#!/usr/bin/env python3
"""Print the cleaning steps recorded in an `lcc optimize` report.

    python3 demos/cleaning_steps.py /tmp/compiled.json

Exists so the demo tapes never need nested shell quoting: `vhs` parses `python3 -c "..."`
poorly, and a tape that fails to parse is worse than no tape.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: cleaning_steps.py REPORT.json")
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    steps = payload.get("cleaning_steps") or []
    if not steps:
        print("  no cleaning steps: the input had nothing redundant to remove")
        return
    for step in steps:
        print(f"  removed: {step.get('name')}")


if __name__ == "__main__":
    main()
