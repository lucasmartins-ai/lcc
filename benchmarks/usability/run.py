"""Measure packaged offline workflows; this is not a human usability study.

python benchmarks/usability/run.py --wheel /tmp/lcc-dist/package.whl --output /tmp/ux.json
Uses a fresh base-only venv and a working directory outside the source tree.
All commands, outputs, checks and timings are retained in the JSON evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASK = "reduce mobile booking friction"
FACT = "The mobile booking form erased patient input at step two."
CONTEXT = f"{FACT}\n\n{FACT}\n\nLOG: worker heartbeat ok in 554ms.\n\n"
API = (
    "import json; from pathlib import Path; from lcc.msi import compile; "
    f"r=compile({TASK!r}, Path('dossier.md').read_text(), task_id='ux-01'); "
    "print(json.dumps(r.to_dict(), sort_keys=True))"
)


def frame(payload: dict) -> str:
    body = json.dumps(payload)
    return f"Content-Length: {len(body.encode())}\r\n\r\n{body}"


def unframe(text: str) -> list[dict]:
    # subprocess text mode normalizes CRLF to LF; payloads here are ASCII.
    out = []
    while text:
        header, text = text.split("\n\n", 1)
        size = int(header.split(":", 1)[1])
        out.append(json.loads(text[:size]))
        text = text[size:]
    return out


def check(name: str, stdout: str, stderr: str, cwd: Path) -> bool:
    if name == "help":
        return all(word in stdout for word in ("compact", "explain", "diff", "mcp"))
    if name == "optimize":
        return FACT in (cwd / "prompt.md").read_text() and (cwd / "clean.json").is_file()
    if name == "inspect":
        return "recommendation" in json.loads((cwd / "inspect.json").read_text())
    if name == "compact":
        report = json.loads((cwd / "report.json").read_text())
        return (
            FACT in (cwd / "compacted.md").read_text()
            and report["provider_used"] == "mechanical"
            and report["semantic_guarantee"] == "none"
            and report["is_estimate"]
        )
    if name == "explain":
        return "mechanical" in stdout and "DROPPED" in stdout
    if name == "diff":
        return "approximate" in stderr.lower() and "tokens" in stderr.lower()
    if name == "python_api":
        data = json.loads(stdout)
        return (
            FACT in data["context"]
            and data["receipt"]["schema_version"] == "inference-receipt/0.1"
            and data["provider_used"] == "mechanical"
            and data["sufficiency"]["result"] == "PASS"
        )
    if name == "missing_file":
        return "missing.md" in stderr and "not found" in stderr.lower()
    if name == "invalid_report":
        return "json" in stderr.lower() and "report" in stderr.lower()
    if name == "invalid_api":
        return "non-empty task" in stdout
    if name == "retrieval_status":
        return "disabled" in stdout.lower()
    if name == "mcp":
        responses = unframe(stdout)
        data = json.loads(responses[2]["result"]["content"][0]["text"])
        return (
            [r["id"] for r in responses] == [1, 2, 3]
            and len(responses[1]["result"]["tools"]) == 6
            and data["report"]["provider_used"] == "mechanical"
            and FACT in data["compacted_text"]
        )
    raise ValueError(name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be >= 1")
    wheel = args.wheel.resolve()
    wheel_bytes = wheel.read_bytes()
    env = dict(os.environ, LCC_DISABLE_NETWORK="1", NO_COLOR="1", TERM="dumb", COLUMNS="120")
    for key in ("PYTHONPATH", "PYTHONHOME", "TYPESAFE_API_KEY", "JEV_API_KEY", "FIREWORKS_API_KEY"):
        env.pop(key, None)
    records = []
    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="lcc-ux-") as directory:
        base = Path(directory)
        venv = base / "venv"
        python = str(venv / "bin/python")
        lcc = str(venv / "bin/lcc")

        def run(name: str, command: list[str], cwd: Path, stdin: str | None = None) -> dict:
            t0 = time.perf_counter()
            proc = subprocess.run(
                command,
                input=stdin,
                text=True,
                capture_output=True,
                cwd=cwd,
                env=env,
                timeout=180,
            )
            row = {
                "name": name,
                "command": [word.replace(str(base), "<workspace>") for word in command],
                "stdin": stdin,
                "exit_code": proc.returncode,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 3),
                "stdout": proc.stdout.replace(str(base), "<workspace>"),
                "stderr": proc.stderr.replace(str(base), "<workspace>"),
            }
            records.append(row)
            return row

        for name, command in (
            ("create_venv", [sys.executable, "-m", "venv", str(venv)]),
            (
                "install_wheel",
                [python, "-m", "pip", "install", "--disable-pip-version-check", str(wheel)],
            ),
        ):
            row = run(name, command, base)
            row["pass"] = row["exit_code"] == 0
            if not row["pass"]:
                break
        else:
            dependencies = run(
                "installed_packages", [python, "-m", "pip", "list", "--format=json"], base
            )
            packages = {p["name"]: p["version"] for p in json.loads(dependencies["stdout"])}
            if "tiktoken" in packages or "laya" in packages:
                raise RuntimeError("benchmark requires a base-only installation")
            first = base / "first"
            first.mkdir()
            (first / "dossier.md").write_text(CONTEXT)
            row = run("first_compile", [python, "-c", API], first)
            row["pass"] = row["exit_code"] == 0 and check(
                "python_api", row["stdout"], row["stderr"], first
            )
            first_compile_ms = round((time.perf_counter() - start) * 1000, 3)
            requests = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "compact", "arguments": {"text": CONTEXT, "question": TASK}},
                },
            ]
            for repeat in range(args.repeats):
                cwd = base / f"run-{repeat}"
                cwd.mkdir()
                (cwd / "dossier.md").write_text(CONTEXT)
                (cwd / "bad.json").write_text("{broken")
                cases = [
                    ("help", [lcc, "--help"], 0, None),
                    (
                        "optimize",
                        [lcc, "optimize", "dossier.md", "-o", "prompt.md", "-r", "clean.json"],
                        0,
                        None,
                    ),
                    ("inspect", [lcc, "inspect", "dossier.md", "-r", "inspect.json"], 0, None),
                    (
                        "compact",
                        [
                            lcc,
                            "compact",
                            "dossier.md",
                            "-q",
                            TASK,
                            "--provider",
                            "mechanical",
                            "-o",
                            "compacted.md",
                            "-r",
                            "report.json",
                        ],
                        0,
                        None,
                    ),
                    ("explain", [lcc, "explain", "report.json", "--source", "dossier.md"], 0, None),
                    ("diff", [lcc, "diff", "dossier.md", "compacted.md"], 0, None),
                    ("python_api", [python, "-c", API], 0, None),
                    ("missing_file", [lcc, "compact", "missing.md", "-q", TASK], 1, None),
                    ("invalid_report", [lcc, "explain", "bad.json"], 1, None),
                    (
                        "invalid_api",
                        [
                            python,
                            "-c",
                            "from lcc.msi import compile\n"
                            "try: compile('', 'text')\n"
                            "except ValueError as e: print(e)\n"
                            "else: raise SystemExit(1)",
                        ],
                        0,
                        None,
                    ),
                    ("retrieval_status", [lcc, "semantic-retrieval"], 0, None),
                    ("mcp", [lcc, "mcp"], 0, "".join(frame(r) for r in requests)),
                ]
                for name, command, expected, stdin in cases:
                    row = run(name, command, cwd, stdin)
                    row["repeat"] = repeat
                    try:
                        row["pass"] = row["exit_code"] == expected and check(
                            name, row["stdout"], row["stderr"], cwd
                        )
                    except (KeyError, ValueError, IndexError, OSError) as exc:
                        row["pass"] = False
                        row["check_error"] = str(exc)
                assert (cwd / "dossier.md").read_text() == CONTEXT, "source mutated"
        payload = {
            "benchmark": "lcc-offline-workflow-usability-1.0",
            "captured_at": datetime.now(UTC).isoformat(),
            "code_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "wheel_sha256": hashlib.sha256(wheel_bytes).hexdigest(),
            "context_sha256": hashlib.sha256(CONTEXT.encode()).hexdigest(),
            "evidence_class": "BENCHMARK",
            "data_class": "CURATED workflows / SYNTHETIC text",
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "repeats": args.repeats,
            "first_compile_ms": locals().get("first_compile_ms"),
            "packages": locals().get("packages", {}),
            "limits": (
                "Fresh venv, existing pip cache. One machine, no human users or live models. "
                "Installation may use network; LCC_DISABLE_NETWORK=1 for workflows. "
                "Times include process startup."
            ),
            "records": records,
        }
        payload["summary"] = {
            name: {
                "n": len(rows),
                "passed": sum(r["pass"] for r in rows),
                "median_ms": round(statistics.median(r["elapsed_ms"] for r in rows), 3),
            }
            for name in dict.fromkeys(r["name"] for r in records if "repeat" in r)
            if (rows := [r for r in records if r["name"] == name])
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n")
        failures = [r["name"] for r in records if r.get("pass") is False]
        print(
            json.dumps(
                {
                    "first_compile_ms": payload["first_compile_ms"],
                    "summary": payload["summary"],
                    "failures": failures,
                },
                indent=2,
            )
        )
        if failures:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
