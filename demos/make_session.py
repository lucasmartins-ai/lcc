#!/usr/bin/env python3
"""Write demos/claude-session.jsonl: a synthetic Claude Code session for the README demo.

Deterministic and invented (no real session text): a "fix the flaky retry test" task with the
shapes real sessions have (file reads, a long failing pytest run, grep, git log, an edit, a
passing run), in the JSONL format Claude Code stores under ~/.claude/projects/.

    python3 demos/make_session.py
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "claude-session.jsonl"


def source(module: str, n: int) -> str:
    lines = [f'"""{module}: checkout retry policy."""', "", "import random", "import time", ""]
    for i in range(n):
        lines += [
            f"def step_{i}(attempt: int, budget: float) -> float:",
            f"    # backoff stage {i}: cap the wait so retries never exceed the budget",
            f"    wait = min(budget, (2 ** attempt) * 0.05 + {i} * 0.01)",
            "    return wait + random.uniform(0, wait / 4)",
            "",
        ]
    lines += ["MAX_ATTEMPTS = 6", "JITTER = True"]
    return "\n".join(f"{k + 1:>4}\t{line}" for k, line in enumerate(lines))


def pytest_fail() -> str:
    out = [
        "============================= test session starts ==============================",
        "platform darwin -- Python 3.12.6, pytest-8.3.3",
        "collected 214 items",
        "",
    ]
    for i in range(40):
        out.append(
            f"tests/checkout/test_retry_{i:02d}.py ...................."
            f"                [ {i * 2:>2}%]"
        )
    out += [
        "",
        "=================================== FAILURES ===================================",
        "______________________ test_retry_storm_respects_budget ______________________",
        "",
    ]
    out += [f"    attempt {k}: waited {0.05 * 2**k:.2f}s (budget 1.50s)" for k in range(8)]
    out += [
        "E   AssertionError: total wait 6.35s > budget 1.50s",
        "tests/checkout/test_retry_storm.py:88: AssertionError",
        "=========================== short test summary info ============================",
        "FAILED tests/checkout/test_retry_storm.py::test_retry_storm_respects_budget",
        "========================= 1 failed, 213 passed in 41.20s =========================",
    ]
    return "\n".join(out)


def main() -> None:
    rows: list[dict] = []
    n = 0

    def user(text: str) -> None:
        rows.append(
            {
                "type": "user",
                "message": {"role": "user", "content": [{"type": "text", "text": text}]},
            }
        )

    def call(name: str, tool_input: dict, result: str, say: str = "") -> None:
        nonlocal n
        n += 1
        tid = f"toolu_demo_{n:03d}"
        content = ([{"type": "text", "text": say}] if say else []) + [
            {"type": "tool_use", "id": tid, "name": name, "input": tool_input}
        ]
        rows.append({"type": "assistant", "message": {"role": "assistant", "content": content}})
        rows.append(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": tid, "content": result}],
                },
            }
        )

    user(
        "The retry storm test in checkout is flaky again. Find out why and fix it. "
        "Do not touch billing/legacy, and keep the change behind RETRY_V2."
    )
    call(
        "Bash",
        {"command": "pytest tests/checkout -q"},
        pytest_fail(),
        "Running the checkout suite first.",
    )
    for i, mod in enumerate(
        (
            "policy",
            "backoff",
            "budget",
            "client",
            "pool",
            "jitter",
            "settings",
            "metrics",
            "breaker",
            "queue",
            "router",
            "session",
        )
    ):
        call("Read", {"file_path": f"src/checkout/retry/{mod}.py"}, source(mod, 18 + 2 * i))
    call(
        "Bash",
        {"command": "rg -n 'MAX_ATTEMPTS|budget' src/checkout"},
        "\n".join(
            f"src/checkout/retry/{m}.py:{10 + k}:    budget = settings.retry_budget_s  # {m}"
            for m in ("policy", "backoff", "budget", "client", "pool")
            for k in range(12)
        ),
    )
    call(
        "Bash",
        {"command": "git log --oneline -25 -- src/checkout/retry"},
        "\n".join(
            f"{(0xA1B2C3 + k * 7919) & 0xFFFFFFF:07x} retry: tune backoff stage {k}"
            for k in range(25)
        ),
    )
    for i in range(16):
        call(
            "Read",
            {"file_path": f"tests/checkout/test_retry_{i:02d}.py"},
            "\n".join(
                f"{k + 1:>4}\tdef test_case_{i}_{k}(client):"
                f"  assert client.retry(attempt={k}) <= BUDGET"
                for k in range(60)
            ),
        )
    for name in [f"ci-{1925 + k}.log" for k in range(10)]:
        call(
            "Bash",
            {"command": f"cat logs/{name}"},
            "\n".join(
                f"2026-10-1{k % 9} 02:{k:02d}:11 INFO retry"
                f" attempt={k % 6} wait={0.05 * 2 ** (k % 6):.2f}s"
                for k in range(90)
            ),
        )
    call(
        "Bash",
        {"command": "ls -la src/checkout/retry tests/checkout"},
        "\n".join(
            f"-rw-r--r--  1 dev  staff  {2000 + 37 * k:>5} Oct 12 10:{k:02d} file_{k}.py"
            for k in range(50)
        ),
    )
    rows.append(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "Cause: backoff.step_* caps each wait at the budget, "
                        "but nothing caps the total across "
                        "attempts, so six attempts can wait 6.35 s against a 1.5 s budget.",
                    }
                ],
            },
        }
    )
    call(
        "Edit",
        {
            "file_path": "src/checkout/retry/backoff.py",
            "old_string": "wait = min(budget,",
            "new_string": "wait = min(budget - spent,",
        },
        "The file src/checkout/retry/backoff.py has been updated.",
    )
    call(
        "Bash",
        {"command": "pytest tests/checkout -q"},
        "\n".join(
            [
                f"tests/checkout/test_retry_{i:02d}.py ....................  [{i * 2:>3}%]"
                for i in range(40)
            ]
            + ["214 passed in 39.80s"]
        ),
    )
    user("Nice. Which file and line was the original failure on?")
    OUT.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    print(f"{OUT.name}: {len(rows)} records, {n} tool calls")


if __name__ == "__main__":
    main()
