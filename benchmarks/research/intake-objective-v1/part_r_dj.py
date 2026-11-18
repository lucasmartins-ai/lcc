#!/usr/bin/env python3
"""Arm DJ on Part R of intake-objective-v1 (PROTOCOL.md, Amendment 5).

    python benchmarks/research/intake-objective-v1/part_r_dj.py [--labels PATH]

Runs Amendment 3's DJ (``run_dj.dj_pick``, unchanged) once on the dictations the owner kept in
Part R. Before any Part R text leaves the machine it checks that every input is the recorded one,
that A0, A1 and D still score exactly as ``stats_r.json`` says, and that one smoke call on a fixed
synthetic text answers. Each dictation with two or more eligible blocks then goes, whole, to the
TypeSafe API at its default endpoint and model. Per-case rows and the Jev ledger stay in the
private folder; the repository gets ``stats_r_dj.json``, aggregates only.

Against ``run_dj.py`` it fixes the five findings of that runner's second review: the journal and
the results are written atomically, the ledger keeps no message text on an API error or an
unexpected answer, the model is recorded only from an answered call, and ``used_jev`` is counted
on the unrounded probability. Needs a TypeSafe key.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import part_r  # noqa: E402
import run_arms  # noqa: E402
import run_dj  # noqa: E402
from run_arms import HERE, WEIGHTS, hit  # noqa: E402

from lcc.intake.objective import analyse, choose  # noqa: E402
from lcc.relevance.jev import JevClient  # noqa: E402

PRIVATE = part_r.PRIVATE
LEDGER = PRIVATE / "jev-ledger.jsonl"
JOURNAL = PRIVATE / "results_r_dj.partial.jsonl"
RESULTS = PRIVATE / "results_r_dj.json"
LOCK = PRIVATE / ".part_r_dj.lock"
OUT = HERE / "stats_r_dj.json"
STATS_R = HERE / "stats_r.json"
FEATURE = "lcc_intake_objective_dj_part_r"
#: Inputs as Amendments 3 and 4 and the Part R run record fix them.
PINNED = {
    "run_dj.py": "cde9aa0584bc1c7976b59cee51c9c8a24cfc3b80ed5f2a9bfc9e9f9ac80b63ca",
    "part_r.py": "cc0da0564f8904f3b8094c737bdaa9fabf02af39bcbc0e659a5a5d17c7699659",
}
CANDIDATES_SHA256 = "d8f0691299647f1da608e6c2a8dc86dd1a5643dd7a1d117852323c3513131b88"
LABELS_SHA256 = "af8aac5dd9365e1f0393efc9dab4d43b3f25e36834f2fc7f91b78167778700b3"
#: The smoke call's text: synthetic, fixed here, with two eligible blocks under D.
SMOKE_TEXT = (
    "Please rename the photo folder from the event. The photos sit on the shared drive. "
    "Another thing, please fix the checkout that freezes when a customer pays by card. "
    "The checkout froze twice."
)

_MODEL = re.compile(r"jev-(?:latest|\d{1,3}(?:\.\d{1,3}){0,3})")
_LABELS = frozenset(run_dj.LABELS)
_INT_KEYS = ("http_status", "attempt", "latency_ms", "input_tokens", "output_tokens", "state_chars")
_ERROR_KINDS = ("pre_flight", "network", "malformed_response")
#: Settings that would send Part R text elsewhere or trust other certificates.
_REFUSED_ENV = ("TYPESAFE_ENDPOINT", "TYPESAFE_MODEL", "SSL_CERT_FILE", "SSL_CERT_DIR")


def _model_id(value: Any) -> str | None:
    return value if isinstance(value, str) and _MODEL.fullmatch(value) else None


def _finite(value: Any) -> float | None:
    """``value`` as a finite float, or None: JSON has no NaN or infinity."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _ledger_line(entry: dict[str, Any]) -> dict[str, Any]:
    """The ledger fields a Part R call may keep, each checked by type: an API error body, a model
    field or an answer the client did not ask for could echo the message, so none passes raw."""
    line: dict[str, Any] = {k: entry[k] for k in ("ts", "feature") if isinstance(entry.get(k), str)}
    line["status"] = "ok" if entry.get("status") == "ok" else "error"
    for key in ("model", "resolved_model"):
        if key in entry:
            line[key] = _model_id(entry[key]) or "unexpected"
    for key in _INT_KEYS:
        if type(entry.get(key)) is int:
            line[key] = entry[key]
    if "error" in entry:
        error = entry["error"] if isinstance(entry["error"], str) else ""
        line["error"] = next((k for k in _ERROR_KINDS if error.startswith(k)), "api_error")
    answers = entry.get("answers")
    main = answers.get("main") if isinstance(answers, dict) else None
    if isinstance(main, dict):
        choice = main.get("choice")
        line["answers"] = {
            "main": {
                "choice": choice if isinstance(choice, str) and choice in _LABELS else None,
                "confidence": _finite(main.get("confidence")),
            }
        }
    return line


class PrivateLedgerJev(JevClient):
    """A Jev client whose ledger lines are filtered by ``_ledger_line``. The filter can never
    raise into the call: the ledger is written inside ``evaluate``, and a raise there would turn a
    valid answer into DJ keeping D's pick."""

    def _ledger_append(self, entry: dict[str, Any]) -> None:
        try:
            line = _ledger_line(entry)
        except Exception:  # noqa: BLE001 - the ledger must not change a pick
            line = {"status": "error" if "error" in entry else "ok", "ledger_filter": "failed"}
        super()._ledger_append(line)


class Recorder:
    """Passes ``dj_pick``'s one call through and keeps the answer, so the row can record the
    unrounded probabilities and this call's model."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.data: dict[str, Any] | None = None

    def evaluate(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
        self.data = None
        self.data = self.client.evaluate(state, questions)
        return self.data


def _probabilities(data: dict[str, Any]) -> dict[str, float] | None:
    try:
        probs = data["answers"]["main"]["probabilities"]
        return {
            k: f
            for k, v in probs.items()
            if isinstance(k, str) and k in _LABELS and (f := _finite(v)) is not None
        }
    except (KeyError, TypeError, AttributeError):
        return None


def dj_row(rec: Recorder, case: dict[str, Any], a: Any, pick: Any) -> dict[str, Any]:
    """One Part R case under DJ: Amendment 3's decision, recorded without rounding."""
    rec.data = None
    t0 = time.perf_counter()
    dj = run_dj.dj_pick(rec, case["text"], a, pick)
    row: dict[str, Any] = {
        "id": case["id"],
        "DJ": hit(dj["span"], case["main"]),
        "DJ_span": dj["span"],
        "DJ_ms": round((time.perf_counter() - t0) * 1000, 1),
        "called": dj["called"],
        "jev": dj["jev"],
        "used_jev": False,
    }
    if "error" in dj:
        row["error"] = dj["error"]
    if dj["jev"] is not None and rec.data is not None:  # a usable answer to this very call
        # The model the API says it resolved to; never the alias this runner asked for.
        model = rec.data.get("resolved_model") or rec.data.get("model")
        row["model"] = (_model_id(model) or "unexpected") if model else "unidentified"
        row["probabilities"] = _probabilities(rec.data)
        # The same expression dj_pick decided on, before its rounding for display.
        p = float(rec.data["answers"]["main"]["probabilities"][dj["jev"]])
        row["p"] = p if math.isfinite(p) else None
        row["used_jev"] = p >= run_dj.THRESHOLD
    return row


def _interrupted(case: dict[str, Any], pick: Any) -> dict[str, Any]:
    """A case whose call may have reached Jev before an interruption: final, D's pick, an error,
    never sent again."""
    span = list(pick.objective_span)
    return {
        "id": case["id"],
        "DJ": hit(span, case["main"]),
        "DJ_span": span,
        "called": True,
        "jev": None,
        "used_jev": False,
        "error": "interrupted",
    }


def _journal_rows(path: Path) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Final rows and pending ids an interrupted run left. The last line, the only one an
    interruption can cut, is dropped if unreadable and the journal rewritten atomically without
    it; an unreadable line before it raises ``ValueError`` and leaves the journal as it is."""
    if not path.exists():
        return {}, set()
    done: dict[str, dict[str, Any]] = {}
    pending: set[str] = set()
    lines = path.read_text(encoding="utf-8").splitlines()
    for n, line in enumerate(lines, 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            row = None
        if not (isinstance(row, dict) and isinstance(row.get("id"), str)):
            if n == len(lines):
                break
            raise ValueError(f"journal line {n} is unreadable; nothing was sent or changed")
        if row.get("pending"):
            pending.add(row["id"])
        else:
            done[row["id"]] = row
    pending -= done.keys()
    lines = [json.dumps(r) for r in done.values()]
    lines += [json.dumps({"id": i, "pending": True}) for i in sorted(pending)]
    part_r._write_private(path, "".join(line + "\n" for line in lines))
    return done, pending


def _sync(out: Any, row: dict[str, Any]) -> None:
    out.write(json.dumps(row, allow_nan=False) + "\n")
    out.flush()
    os.fsync(out.fileno())


def run(cases: list[dict[str, Any]], rec: Recorder, journal: Path) -> list[dict[str, Any]]:
    """DJ on every case. The case id is synced to ``journal`` before its call and the row right
    after it, so a rerun neither asks Jev again nor loses a row; a failed or interrupted call
    stays final."""
    done, pending = _journal_rows(journal)
    rows = []
    fd = os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as out:
        # The journal's name, new or just renamed, must survive a crash before the first call.
        dir_fd = os.open(journal.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        for case in cases:
            if case["id"] in done:
                rows.append(done[case["id"]])
                continue
            a = analyse(case["text"])
            pick = choose(a, WEIGHTS)
            if case["id"] in pending:
                row = _interrupted(case, pick)
            else:
                # dj_pick's own test for making a call; run_dj.py is pinned, so it cannot drift.
                if len(pick.ranking[: run_dj.TOP]) >= 2:
                    _sync(out, {"id": case["id"], "pending": True})
                row = dj_row(rec, case, a, pick)
            rows.append(row)
            _sync(out, row)
    return rows


def summarise(rows: list[dict[str, Any]], d_hits: dict[str, bool]) -> dict[str, Any]:
    n = len(rows)
    return {
        "n": n,
        "DJ": part_r.wilson(sum(r["DJ"] for r in rows), n),
        "D": part_r.wilson(sum(d_hits[r["id"]] for r in rows), n),
        "dj_fixed_d_misses": sum(r["DJ"] and not d_hits[r["id"]] for r in rows),
        "dj_lost_d_hits": sum(d_hits[r["id"]] and not r["DJ"] for r in rows),
        "calls": sum(r["called"] for r in rows),
        "errors": sum("error" in r for r in rows),
        "used_jev": sum(r["used_jev"] for r in rows),
        "below_threshold": sum(r["jev"] is not None and not r["used_jev"] for r in rows),
        # Every model Jev resolved to on an answered call, so a change of model shows.
        "model": ",".join(sorted({r["model"] for r in rows if r.get("model")})),
    }


def _smoke(rec: Recorder) -> bool:
    """One call on ``SMOKE_TEXT``: a dead key, a certificate error, an unusable answer or a model
    id this runner would record as ``unexpected`` stops the run before any Part R text is sent."""
    a = analyse(SMOKE_TEXT)
    rec.data = None
    dj = run_dj.dj_pick(rec, SMOKE_TEXT, a, choose(a, WEIGHTS))
    if dj["jev"] is None or not (math.isfinite(dj["p"]) and 0.0 <= dj["p"] <= 1.0):
        return False
    return _model_id(rec.data.get("resolved_model") or rec.data.get("model")) is not None


def _read_pinned(path: Path, sha: str) -> bytes | None:
    """The file's bytes if they hash to ``sha``, read once so the checked bytes are the used ones."""
    data = path.read_bytes()
    return data if hashlib.sha256(data).hexdigest() == sha else None


def _refuse(why: str) -> int:
    print(f"refused: {why}")
    return 2


def _finish(summary: dict[str, Any]) -> int:
    part_r._write_private(OUT, json.dumps(summary, indent=1, allow_nan=False) + "\n", mode=0o644)
    JOURNAL.unlink(missing_ok=True)
    print(json.dumps(summary, indent=1))
    return 0


def _main(labels_path: Path) -> int:
    if OUT.exists():
        return _refuse("DJ already ran on Part R (stats_r_dj.json exists)")
    if RESULTS.exists():  # a run stopped between its two writes: publish its summary, send nothing
        return _finish(json.loads(RESULTS.read_text(encoding="utf-8"))["summary"])
    for name, sha in PINNED.items():
        if _read_pinned(HERE / name, sha) is None:
            return _refuse(f"{name} is not the file its amendment pins")
    candidates_bytes = _read_pinned(PRIVATE / "candidates.json", CANDIDATES_SHA256)
    if candidates_bytes is None:
        return _refuse("candidates.json is not the pool Amendment 4 records")
    labels_bytes = _read_pinned(labels_path, LABELS_SHA256)
    if labels_bytes is None:
        return _refuse("the labels are not the ones the Part R run record names")
    if run_arms._code_sha256() != run_arms.FROZEN_OBJECTIVE_SHA256 or (
        run_arms.run("dev", WEIGHTS)["summary"]["d_sha256"] != run_arms.FROZEN_D_SHA256
    ):
        return _refuse("D is not the frozen D (code or dev output differ from Amendment 2)")
    part_r._check_parser()
    candidates = json.loads(candidates_bytes)
    kept, skips = part_r.labelled(candidates, json.loads(labels_bytes))
    d_rows, d_summary = part_r.score(kept)
    recorded = json.loads(STATS_R.read_text(encoding="utf-8"))
    if {"pool": candidates["counts"], "skipped": skips, **d_summary} != recorded:
        return _refuse("A0, A1 and D no longer reproduce stats_r.json")
    try:
        done, pending = _journal_rows(JOURNAL)
    except ValueError as exc:
        return _refuse(str(exc))
    to_send = [c for c in kept if c["id"] not in done and c["id"] not in pending]
    rec = Recorder(None)  # a finished journal needs no key: run() then makes no call
    if to_send:
        # One HTTP attempt per case, as Amendment 3 sets; the ledger stays in the private folder.
        rec.client = PrivateLedgerJev.from_env(ledger_path=LEDGER, feature=FEATURE, attempts=1)
        if rec.client is None:
            return _refuse("no TypeSafe key or network disabled; DJ without Jev is D")
        if not _smoke(rec):
            return _refuse("the smoke call got no usable answer; no Part R text was sent")
    rows = run(kept, rec, JOURNAL)
    summary = summarise(rows, {r["id"]: r["D"] for r in d_rows})
    result = {"top": run_dj.TOP, "threshold": run_dj.THRESHOLD, "rows": rows, "summary": summary}
    part_r._write_private(RESULTS, json.dumps(result, indent=1, allow_nan=False))
    return _finish(summary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--labels", default=str(PRIVATE / "labels.json"))
    args = parser.parse_args(argv)
    for var in _REFUSED_ENV:
        if var in os.environ:
            return _refuse(f"{var} is set; Part R text goes only to the default endpoint and model")
    # The client's opener honours proxies from the environment and, on macOS, the system settings.
    if urllib.request.getproxies().keys() & {"https", "all"}:
        return _refuse("an HTTPS proxy is set; Part R text goes straight to the endpoint")
    fd = os.open(LOCK, os.O_WRONLY | os.O_CREAT, 0o600)
    with os.fdopen(fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return _refuse("another part_r_dj.py run holds the lock")
        return _main(Path(args.labels))


if __name__ == "__main__":
    sys.exit(main())
