"""Deterministic agent-transcript corpora for tool-call compaction studies.

Builds sessions with the five parts a compaction claim needs to be testable
(`context-transform-benchmarking`): a stable prefix carrying the task and its constraints,
tool calls of three kinds (spent, evidence, noise), a volatile tail, and ground-truth facts
phrased with **weak lexical overlap** against the objective so a scorer cannot keep them by
accident.

Each session declares, per tool call, what the honest outcome is:

- ``spent``: the work it was run for is over (the file was rewritten, the listing is stale)
  — dropping it is correct.
- ``evidence``: carries a required fact — dropping it is a false drop.
- ``noise``: topically distant chatter — dropping it is fine, keeping it costs tokens.
- ``pinned``: inside the newest messages, which both implementations pin by design.

Run: ``python3 benchmarks/research/make_transcripts.py`` (writes ``corpora/transcripts/``).
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "corpora" / "transcripts"

#: Facts a compacted session must still contain. Each is a literal line inside the matching
#: evidence result, and deliberately worded away from the objective ("retry storm on
#: checkout") so a scorer cannot keep it by lexical overlap. `main()` asserts every literal
#: is really in its result: a corpus that drifts from its own ground truth measures nothing.
REQUIRED_FACTS = {
    "latency-tail": "quantile 0.99 value 4310 window 02:10..02:40",
    "idempotency": "the server treats every attempt as a new charge",
    "flag": "rollout 0 state off",
    "constraint": "billing/legacy stays frozen",
    "window": "weekday change window closes at 17:00 local",
}

SPENT_TOOLS = [
    ("Read", {"file_path": "src/checkout/attempts.ts"}),
    ("Bash", {"command": "ls -la src/checkout"}),
    ("Read", {"file_path": "src/checkout/queue.ts"}),
    ("Grep", {"pattern": "TODO", "path": "src/checkout"}),
    ("Bash", {"command": "git log --oneline -12"}),
    ("Read", {"file_path": "package.json"}),
]

NOISE_RESULTS = [
    "ci: nightly build finished, 41 artifacts uploaded, cache hit ratio 0.62",
    "docs: the style guide still lists the old font stack and colour tokens",
    "infra: the staging certificate renews automatically on the 14th of each month",
    "meeting notes: design review moved to Thursday, room changed to 4B",
    "marketing: the landing hero copy was shortened to 11 words last week",
]

EVIDENCE_RESULTS = {
    "latency-tail": (
        "metrics export (02:00-03:00 UTC)\n"
        "series: http_server_duration_ms{route=\"POST /pay\"}\n"
        "quantile 0.99 value 4310 window 02:10..02:40\n"
        "sample: the spike starts right after the first client in the pool reconnects"
    ),
    "idempotency": (
        "request capture, three consecutive attempts\n"
        "attempt 1 header Idempotency-Key: 9f2c-...\n"
        "attempt 2 header Idempotency-Key: 9f2c-...\n"
        "attempt 3 header Idempotency-Key: 9f2c-...\n"
        "the server treats every attempt as a new charge"
    ),
    "flag": (
        "feature flags (exported)\n"
        "RETRY_V2 audience none region all rollout 0 state off\n"
        "the worker reads the value once at boot"
    ),
    "constraint": (
        "policy note from the platform review\n"
        "billing/legacy stays frozen: no schema, no retry semantics, no owner change\n"
        "questions go to the payments group"
    ),
    "window": (
        "release calendar\n"
        "weekday change window closes at 17:00 local\n"
        "weekend freezes apply to the payments group"
    ),
}


def _pair(index: int, tool: str, tool_input: dict, result: str, kind: str) -> tuple[list[dict], dict]:
    """One assistant message with a tool call plus the user message carrying its result."""
    call_id = f"toolu_{index:04d}"
    assistant = {
        "role": "assistant",
        "text": f"Step {index}.",
        "toolUses": [{"tool_use_id": call_id, "tool": tool, "input": tool_input}],
    }
    user = {"role": "user", "text": "", "toolResults": [{"tool_use_id": call_id, "text": result}]}
    return [assistant, user], {"id": call_id, "tool": tool, "kind": kind}


def _plan(evidence_count: int, spent: int, noise: int) -> list[str]:
    """Interleave the three kinds deterministically until every quota is spent."""
    quotas = {"evidence": evidence_count, "spent": spent, "noise": noise}
    plan: list[str] = []
    while any(quotas.values()):
        for kind in ("evidence", "spent", "noise"):
            if quotas[kind] > 0:
                plan.append(kind)
                quotas[kind] -= 1
    return plan


def build_session(
    session_id: str, objective: str, task: str, evidence: list[str], spent: int, noise: int, tail: int
) -> dict:
    """A session whose tool calls interleave evidence, spent and noise, then a pinned tail."""
    messages: list[dict] = [{"role": "user", "text": task}]
    calls: list[dict] = []

    index = 0
    seen = {"evidence": 0, "spent": 0, "noise": 0}
    for kind in _plan(len(evidence), spent, noise):
        index += 1
        if kind == "evidence":
            fact = evidence[seen["evidence"] % len(evidence)]
            seen["evidence"] += 1
            pair, call = _pair(
                index, "Bash", {"command": f"cat reports/{fact}.txt"}, EVIDENCE_RESULTS[fact], "evidence"
            )
        elif kind == "spent":
            tool, tool_input = SPENT_TOOLS[seen["spent"] % len(SPENT_TOOLS)]
            seen["spent"] += 1
            pair, call = _pair(
                index, tool, tool_input, f"stale output for {tool_input}\n" + "x" * 120, "spent"
            )
        else:
            pair, call = _pair(
                index,
                "Bash",
                {"command": "tail -n 40 logs/side.log"},
                NOISE_RESULTS[seen["noise"] % len(NOISE_RESULTS)],
                "noise",
            )
            seen["noise"] += 1
        messages.extend(pair)
        calls.append(call)

    # The volatile tail: newest calls, which both implementations pin (preserve_recent).
    for _ in range(tail):
        index += 1
        pair, call = _pair(
            index,
            "Bash",
            {"command": f"pytest tests/checkout/test_attempts.py -k case_{index}"},
            "latest run: 1 failed, 24 passed",
            "pinned",
        )
        messages.extend(pair)
        calls.append(call)

    return {
        "id": session_id,
        "objective": objective,
        "task": task,
        "messages": messages,
        "calls": calls,
        "counts": {
            "spent": sum(1 for call in calls if call["kind"] == "spent"),
            "noise": sum(1 for call in calls if call["kind"] == "noise"),
            "evidence": sum(1 for call in calls if call["kind"] == "evidence"),
            "pinned": sum(1 for call in calls if call["kind"] == "pinned"),
        },
        "required_facts": [REQUIRED_FACTS[fact] for fact in evidence],
    }


def build_corpus() -> list[dict]:
    task = (
        "Cut the retry storm on checkout. Constraints from the platform review: billing/legacy "
        "must not be touched, and the change ships behind RETRY_V2. Report what you changed."
    )
    objective = "cut the retry storm on checkout"
    return [
        build_session(
            "small",
            objective,
            task,
            evidence=["latency-tail", "idempotency"],
            spent=4,
            noise=2,
            tail=3,
        ),
        build_session(
            "medium",
            objective,
            task,
            evidence=["latency-tail", "idempotency", "flag"],
            spent=8,
            noise=6,
            tail=3,
        ),
        build_session(
            "large",
            objective,
            task,
            evidence=["latency-tail", "idempotency", "flag", "constraint", "window"],
            spent=14,
            noise=10,
            tail=3,
        ),
    ]


def main() -> None:
    for fact, literal in REQUIRED_FACTS.items():
        assert literal in EVIDENCE_RESULTS[fact], f"ground truth drifted for {fact!r}"
        assert literal.lower() not in "cut the retry storm on checkout", "objective leaks the fact"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    index = []
    for session in build_corpus():
        path = OUT_DIR / f"{session['id']}.json"
        path.write_text(json.dumps(session, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        index.append(
            {
                "id": session["id"],
                "path": str(path.relative_to(HERE.parent.parent)),
                "messages": len(session["messages"]),
                "calls": len(session["calls"]),
                "counts": session["counts"],
                "chars": len("".join(message.get("text", "") for message in session["messages"])),
            }
        )
    (OUT_DIR / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    for row in index:
        print(
            f"{row['id']:8} messages={row['messages']:4} tool_calls={row['calls']:3} "
            f"spent={row['counts']['spent']:2} noise={row['counts']['noise']:2} "
            f"evidence={row['counts']['evidence']} pinned={row['counts']['pinned']}"
        )


if __name__ == "__main__":
    main()
