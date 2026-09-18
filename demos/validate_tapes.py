#!/usr/bin/env python3
"""Check that the demo tapes type commands that actually work.

`vhs validate` parses a tape but does not check the *command* the tape types, so a tape
can validate and still type something that fails. This script types the tape into a real
bash instead: it unescapes each `Type` argument, accumulates keystrokes until a newline
that ends a command, and then either syntax-checks (`bash -n`) or executes it.

What it models that is easy to get wrong by eye:

1. **Line continuation.** A typed line ending in an odd number of backslashes is not
   executed; bash waits for more. A tape that splits one long command across three
   `Type` lines with a trailing `\\` each types exactly one command, not three.
2. **vhs string rules.** A quoted `Type` argument is shell double-quoted, so a backslash
   only escapes `"`, `\\` and `$`. Whether vhs types a backslash or a quote for an
   argument ending in `\\"` could not be confirmed on this machine (see demos/README.md),
   which is why the tapes type every command on one line: no reading of the escape rules
   can then change what gets typed.

    python3 demos/validate_tapes.py          # syntax check, fast
    python3 demos/validate_tapes.py --run    # actually run the commands, from the repo root

`--run` is the check that settles it. A syntax check cannot: `lcc compact --provider` is
valid bash, and so is a command whose flags were swallowed by an unbalanced quote. Only
running the command shows it does what the tape claims.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess

TYPE_RE = re.compile(r"^Type\s+(?P<arg>.*)$")


def unescape_vhs(arg: str) -> str:
    """Apply shell double-quote rules to a quoted Type argument."""
    arg = arg.strip()
    if not (len(arg) >= 2 and arg[0] == '"' and arg[-1] == '"'):
        return arg
    body = arg[1:-1]
    out: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if char == "\\" and index + 1 < len(body) and body[index + 1] in {'"', "\\", "$"}:
            out.append(body[index + 1])
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def continues(command: str) -> bool:
    """True when bash would wait for more input: an odd trailing backslash run."""
    stripped = command.rstrip("\n")
    trailing = len(stripped) - len(stripped.rstrip("\\"))
    return trailing % 2 == 1


def check(path: str) -> tuple[list[str], list[str]]:
    """Return (complete commands, unterminated buffers) for a tape."""
    commands: list[str] = []
    buffer = ""
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    for line in lines:
        if line.lstrip().startswith("#"):
            continue
        match = TYPE_RE.match(line)
        if match:
            buffer += unescape_vhs(match.group("arg"))
            continue
        if line.strip() != "Enter":
            continue
        if continues(buffer):
            buffer += "\n"
            continue
        if buffer.strip():
            commands.append(buffer)
        buffer = ""
    unterminated = [buffer] if buffer.strip() else []
    return commands, unterminated


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check that the demo tapes type commands that actually work."
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="actually run each typed command instead of only syntax-checking it",
    )
    args = parser.parse_args()

    failures = 0
    for path in sorted(glob.glob("demos/*.tape")):
        commands, unterminated = check(path)
        print(f"--- {path}: {len(commands)} command(s)")
        for command in commands:
            head = command if len(command) <= 118 else command[:115] + "..."
            if args.run and not command.lstrip().startswith("#"):
                env = {**os.environ, "TIKTOKEN_CACHE_DIR": os.path.expanduser("~/.cache/tiktoken")}
                proc = subprocess.run(
                    ["bash", "-c", command],
                    capture_output=True,
                    text=True,
                    env=env,
                )
                label = "ok  " if proc.returncode == 0 else "FAIL"
                print(f"  [{label}] {head}")
                if proc.returncode != 0:
                    print(f"         exit {proc.returncode}: {proc.stderr.strip()[:300]}")
                    failures += 1
                continue
            proc = subprocess.run(["bash", "-n"], input=command, capture_output=True, text=True)
            label = "ok  " if proc.returncode == 0 else "FAIL"
            print(f"  [{label}] {head}")
            if proc.returncode != 0:
                print(f"         {proc.stderr.strip()}")
                failures += 1
        for buffer in unterminated:
            print(f"  [FAIL] unterminated command: {buffer[:100]!r}")
            failures += 1
    if failures:
        print(f"\n{failures} problem(s).")
        return 1
    mode = "ran and succeeded" if args.run else "is a complete, valid bash command"
    print(f"\nEvery typed command {mode}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
