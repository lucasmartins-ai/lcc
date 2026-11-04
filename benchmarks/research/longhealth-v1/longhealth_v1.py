"""LongHealth v1 harness (protocol: PROTOCOL.md in this directory).

Writes only under ~/.lcc/bench/longhealth-v1 (record texts, questions and answers never leave it). Model calls go
through subscription `claude -p` only, with a hard cap of 650 calls counted across pilot and D (a call is counted
before it starts). A second driver refuses to start while one holds the lock.

    PYTHONPATH=<lcc pin worktree>/src HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 ~/lcc/.venv/bin/python \\
        benchmarks/research/longhealth-v1/longhealth_v1.py \\
        {fetch|toolcheck|build|compact|locate|run --arm A|score} --set pilot|D
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import hashlib
import json
import os
import random
import re
import statistics
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("LONGHEALTH_ROOT", Path.home() / ".lcc" / "bench" / "longhealth-v1"))
HERE = Path(__file__).resolve().parent
SHIM = HERE / "recall_shim.py"
COMMIT = "479922279ce8fa528fe2cd87d854c6a2f8365d21"
BLOB = "76bf80d37f321408a0e3f421a2e2d7ef59e97c1e"
SIZE = 4_429_723
DATA_URL = f"https://raw.githubusercontent.com/kbressem/LongHealth/{COMMIT}/data/benchmark_v5.json"
SEED = 20261103
K = 6
CALL_CAP = 650
TIMEOUT_S = 1200
MAX_OUTPUT = 128_000  # CLAUDE_CODE_MAX_OUTPUT_TOKENS; S-clin summaries reach ~70k output tokens with thinking
ANSWERER, SUMMARIZER = "claude-sonnet-5-5", "claude-opus-5-5"
CONDITIONS = ("ans_early", "ans_late", "unans")
F_TEXT = "Question cannot be answered with provided documents"
GOAL = "Answer questions about one patient from today's list."
TOKEN_MODEL = "gpt-4.1"  # the counter stashed-recall-v1 and its shim used
BOOT_N = 2000

RECALL_SENTENCE = (
    "If you have the recall tool, it returns the exact removed text for an id; use it when an answer depends on "
    "removed text, and do not recall text you do not need."
)
Q_T = (
    "You are continuing a chart-review session. The context above is everything you have from the session so "
    "far; parts of it may have been compressed. Some old tool results were replaced by a marker of the form "
    "[removed: N lines, S KB · lcc recall <id>]. " + RECALL_SENTENCE + " For each numbered question, choose one "
    "option from A to F. Answer on one line per question, in this form:\n"
    '<number>: <letter>: <exact option text> | quote: "<words copied exactly from a record that support the option>"\n'
    'You may give up to three quotes, separated by " | quote: ". Each quote must be at least 20 characters copied '
    "exactly from one record. For option F, write no quote. Choose F when the records you have do not answer the "
    "question about this patient."
)
Q_0 = Q_T.replace(RECALL_SENTENCE + " ", "")
Q_N = (
    "You have no records for this patient. Answer each numbered question from what you know, choosing one option "
    "from A to E even if you are unsure. Answer on one line per question, in this form:\n"
    "<number>: <letter>: <exact option text>"
)
# probe-eval-v1's frozen S (sha256 ea72d62f… of the text plus its final newline, checked by the tests).
S_TEXT = (
    "Write a summary of this conversation that will replace it. Work will continue from your summary alone. First "
    "reason inside <analysis> tags (this part is removed), then write <summary> with these sections:\n"
    "1. Primary request and intent.\n"
    "2. Key technical concepts.\n"
    "3. Files and code sections: each file read, edited or created, why it matters, and short code snippets where "
    "needed.\n"
    "4. Errors met and how each was fixed.\n"
    "5. Problem solving done and still open.\n"
    "6. Every user message that is not a tool result. Keep security-relevant constraints word for word.\n"
    "7. Pending tasks.\n"
    "8. Current work, just before this summary.\n"
    "9. Optional next step, quoting the latest task word for word."
)
S_SHA = "ea72d62fb0091811dce1ffcc8f2decbb08a028e8790cbbc6f6250399275550e6"
S_CLIN = (
    "Write a summary of this chart review that will replace it. Work will continue from your summary alone. First "
    "reason inside <analysis> tags (this part is removed), then write <summary>. For each patient folder: the "
    "patient's name and date of birth as written; every diagnosis with its date; every treatment with drug, dose, "
    "route, schedule and dates; every lab, imaging and pathology value with its unit and date; procedures, "
    "complications and outcomes with dates; and anything recorded as absent, negative or not done. Copy names, "
    "numbers, units and dates exactly as they appear."
)
SYSTEM_TOOL = "You answer questions about a chart-review session from the context you are given. You have one tool, recall."
SYSTEM_NOTOOL = "You answer questions about a chart-review session from the context you are given. You have no tools."
SYSTEM_SUM = "You write the summary that replaces a session's context."
SYSTEM_NONE = "You answer multiple-choice questions."
# arm -> (context, tool, question text)
ARMS = {
    "none": (None, False, Q_N),
    "full_t": ("full", True, Q_T),
    "stashed_t": ("stashed", True, Q_T),
    "stashed_0": ("stashed", False, Q_0),
    "summary_s": ("summary_s", False, Q_0),
    "summary_clin": ("summary_clin", False, Q_0),
    "stashed_v": ("stashed", True, Q_T),
}
NOTE_RE = re.compile(r"\[removed: \d+ lines?, \d+(?:\.\d)? K?B · lcc recall ([0-9a-f]{12})\]")
LINE_RE = re.compile(r"^[ \t*]*(\d{1,2})[ \t*]*[:.)][ \t*]*([A-F])\b[ \t*]*:?(.*)$", re.M)
NUM_RE = re.compile(r"[0-9]+(?:[.,][0-9]+)?")
LIMIT_RE = re.compile(r"hit your (?:usage )?limit|usage limit|rate.?limit|limit reached|resets? at|\b429\b", re.I)


class LimitHit(RuntimeError):
    pass


class InfraError(RuntimeError):
    def __init__(self, msg: str, tokens: int = 0):  # tokens the failed attempt consumed (a split reply has some)
        super().__init__(msg)
        self.tokens = tokens


# --- io ---------------------------------------------------------------------------------------------------------
def rj(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def wj(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def append(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(rec) + "\n")


@contextlib.contextmanager
def driver_lock():
    """One driver at a time (stashed-recall-v1 Amendment 4: two drivers once ran the same arm)."""
    ROOT.mkdir(parents=True, exist_ok=True)
    lock = ROOT / "driver.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit(f"another driver holds {lock}; remove it only if no driver is running") from None
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


# --- data -------------------------------------------------------------------------------------------------------
def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def fetch() -> Path:
    path = ROOT / "benchmark_v5.json"
    if not path.exists():
        with urllib.request.urlopen(DATA_URL, timeout=120) as r:  # noqa: S310 -- fixed https URL
            data = r.read()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    load_benchmark(path)
    return path


def load_benchmark(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) != SIZE or git_blob_sha(data) != BLOB:
        raise SystemExit(f"{path}: not LongHealth benchmark_v5.json at {COMMIT[:12]} (size or blob hash differs)")
    return json.loads(data)


def pilot_pool(ids) -> list[str]:
    return sorted(random.Random(SEED).sample(sorted(ids), 2))


def targets(bench: dict, which: str) -> list[str]:
    pool = pilot_pool(bench)
    return pool if which == "pilot" else sorted(p for p in bench if p not in pool)


def text_ids(patient: dict) -> list[str]:
    return sorted(patient["texts"], key=lambda t: int(t.rsplit("_", 1)[-1]))


# --- sessions ---------------------------------------------------------------------------------------------------
def build_session(bench: dict, target: str, condition: str) -> dict:
    rng = random.Random(f"{target}:{condition}")
    others = rng.sample(sorted(p for p in bench if p != target), K if condition == "unans" else K - 1)
    order = {"ans_early": [target, *others], "ans_late": [*others, target], "unans": others}[condition]
    folders = {pid: f"p{n}" for pid, n in zip(order, rng.sample(range(10, 100), K), strict=True)}
    first = (
        "Chart review for today's multidisciplinary meeting: six patients, folders records/p<id> in the order "
        "listed. Read every record of each patient, in order.\n" + "\n".join(f"records/{folders[p]}" for p in order)
    )
    blocks = [{"m": 0, "role": "user", "kind": "text", "tool": None, "id": None, "content": first}]
    reads = {}  # tool_use_id -> (patient, text id, path)
    for pid in order:
        for tid in text_ids(bench[pid]):
            m, call = len(blocks), f"toolu_{len(reads):04d}"
            path = f"records/{folders[pid]}/{tid}.txt"
            reads[call] = (pid, tid, path)
            blocks.append({"m": m, "role": "assistant", "kind": "tool_use", "tool": "Read", "id": call,
                           "content": json.dumps({"file_path": path})})
            blocks.append({"m": m + 1, "role": "user", "kind": "tool_result", "tool": "Read", "id": call,
                           "content": bench[pid]["texts"][tid]})
    p = bench[target]
    return {"id": f"{target}__{condition}", "target": target, "condition": condition, "folders": folders,
            "reads": reads, "blocks": blocks, "P": questions_text(p, "ABCDEF"), "P_none": questions_text(p, "ABCDE")}


def questions_text(patient: dict, letters: str) -> str:
    parts = [f"Questions about {patient['name']}, born {patient['birthday']}:"]
    for i, q in enumerate(patient["questions"], 1):
        opts = [f"{L}: {q['answer_' + L.lower()]}" if L != "F" else f"F: {F_TEXT}" for L in letters]
        parts.append(f"{i}. {q['question']}\n" + "\n".join(opts))
    return "\n\n".join(parts)


def gold_letter(q: dict, condition: str) -> str | None:
    if condition == "unans":
        return "F"
    hits = [L for L in "ABCDE" if q[f"answer_{L.lower()}"] == q["correct"]]
    return hits[0] if len(hits) == 1 else None


def render(blocks: list[dict]) -> str:
    return "\n\n".join(
        f"[m{b['m']:04d} {b['role']} {b['kind']}{' ' + b['tool'] if b['tool'] else ''}]\n{b['content']}" for b in blocks
    )


def payload_of(blocks: list[dict]) -> list[dict]:
    msgs: dict[int, dict] = {}
    for b in blocks:
        m = msgs.setdefault(b["m"], {"role": b["role"], "text": [], "toolUses": [], "toolResults": []})
        if b["kind"] == "text":
            m["text"].append(b["content"])
        elif b["kind"] == "tool_use":
            m["toolUses"].append({"tool_use_id": b["id"], "tool": b["tool"], "input": json.loads(b["content"])})
        else:
            m["toolResults"].append({"tool_use_id": b["id"], "text": b["content"]})
    return [{**v, "text": "\n".join(v["text"])} for _, v in sorted(msgs.items())]


# --- compaction -------------------------------------------------------------------------------------------------
def independent_stash_check(blocks: list[dict], out_texts: dict, stash: Path) -> list[dict]:
    """Every pointer names the sha256 of the exact original bytes, and that blob hashes to its name. No lcc code."""
    orig = {b["id"]: b["content"] for b in blocks if b["kind"] == "tool_result"}
    bad = []
    for tid, text in out_texts.items():
        m = NOTE_RE.fullmatch(text or "")
        if text == orig.get(tid) or not m:
            continue  # ponytail: only stash pointers are checked here; lossless dedupes are verify_stashed's job
        if tid not in orig:
            bad.append({"id": tid, "why": "unknown_result"})
            continue
        digest = hashlib.sha256(orig[tid].encode("utf-8")).hexdigest()
        blob = stash / digest
        if not digest.startswith(m.group(1)):
            bad.append({"id": tid, "why": "sha_mismatch"})
        elif not blob.is_file() or hashlib.sha256(blob.read_bytes()).hexdigest() != digest:
            bad.append({"id": tid, "why": "blob_missing_or_corrupt"})
    return bad


def compact_session(sess: dict, stash: Path) -> dict:
    from lcc.relevance import TranscriptCompactionRequest, compact_transcript, messages_to_payload
    from lcc.relevance.transcript_stash import verify_stashed

    stash.mkdir(parents=True, exist_ok=True)
    os.environ["LCC_STASH_DIR"] = str(stash)
    payload = payload_of(sess["blocks"])
    r = compact_transcript(TranscriptCompactionRequest(payload=payload, question=GOAL, provider="rules",
                                                       rules_mode="stashed"))
    texts = {x.id: x.text for m in r.messages for x in m.tool_results}
    viol = verify_stashed(payload, messages_to_payload(r.messages))
    indep = independent_stash_check(sess["blocks"], texts, stash)
    out = [{**b, "content": texts.get(b["id"], b["content"])} if b["kind"] == "tool_result" else b
           for b in sess["blocks"]]
    stashed = {d["id"]: {"reason": d["reason"], "sha": d["stash"]["sha256"]}
               for d in r.decisions if d.get("decision") == "replace"}
    return {"ok": not (viol or indep), "blocks": out, "stashed": stashed, "violations": len(viol),
            "independent": indep}


def locate_session(sess: dict, comp: dict, patient: dict) -> list[dict]:
    """Per question: where its answer texts sit in C' (computed before any answer; reads the gold only here)."""
    by_text = {tid: call for call, (pid, tid, _) in sess["reads"].items() if pid == sess["target"]}
    rows = []
    for i, q in enumerate(patient["questions"], 1):
        row = {"qno": i, "exact_value": bool(re.search(r"\d", q["correct"]))}
        if sess["condition"] != "unans":
            calls = [by_text[t] for t in q["answer_location"]]
            n = sum(c in comp["stashed"] for c in calls)
            row["where"] = "stash_dependent" if n == len(calls) else "in_view" if n == 0 else "mixed"
            row["gold_shas"] = [comp["stashed"][c]["sha"] for c in calls if c in comp["stashed"]]
        rows.append(row)
    return rows


# --- model calls ------------------------------------------------------------------------------------------------
def n_calls() -> int:
    return len(jsonl(ROOT / "calls.jsonl"))


def mcp_config(stash: Path, log: Path) -> dict:
    env = {"LCC_STASH_DIR": str(stash), "RECALL_LOG": str(log), "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
           "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    return {"mcpServers": {"stash": {"type": "stdio", "command": sys.executable, "args": [str(SHIM)], "env": env}}}


def cli(role: str, model: str, system: str, prompt: str, effort: str, tool: tuple[Path, Path] | None = None) -> dict:
    """One subscription call -> its text and envelope facts. tool=(stash dir, recall log) enables recall.

    The call is written to calls.jsonl before it starts, so an interrupted call still counts toward the cap."""
    if n_calls() >= CALL_CAP:
        raise SystemExit(f"call cap {CALL_CAP} reached")
    # A pause point below the cap, so the operator can check plan usage between chunks; rerun resumes from cache.
    if n_calls() >= int(os.environ.get("LONGHEALTH_PAUSE_AT", CALL_CAP)):
        raise SystemExit(f"pause point {os.environ['LONGHEALTH_PAUSE_AT']} reached")
    append(ROOT / "calls.jsonl", {"role": role, "model": model})
    with tempfile.TemporaryDirectory(prefix="longhealth-cwd-") as cwd:
        argv = ["claude", "-p", "--model", model, "--tools", "", "--output-format", "json", "--no-session-persistence",
                "--disable-slash-commands", "--strict-mcp-config", "--permission-prompts", "none",
                "--setting-sources", "", "--exclude-dynamic-system-prompt-sections", "--system-prompt", system,
                "--effort", effort]
        if tool:
            cfg = Path(cwd) / "mcp.json"
            cfg.write_text(json.dumps(mcp_config(*tool)))
            argv += ["--mcp-config", str(cfg), "--allowedTools", "mcp__stash__recall"]
        assert not any("dangerously" in a for a in argv), "never skip permissions"
        try:
            penv = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "ANTHROPIC_"))}
            penv["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(MAX_OUTPUT)  # the CLI clamps it to the model's upper limit
            r = subprocess.run(argv, input=prompt, capture_output=True, text=True, cwd=cwd, timeout=TIMEOUT_S + 60,
                               env=penv)
            out, err, rc = r.stdout, r.stderr, r.returncode
        except subprocess.TimeoutExpired:
            out, err, rc = "", "timeout", -9
    try:
        env = json.loads(out)
    except ValueError:
        env = None
    ok = rc == 0 and isinstance(env, dict) and not env.get("is_error") and isinstance(env.get("result"), str)
    # With no tools a reply has one turn; a second is the CLI resuming a reply that was cut (output cap or a refusal
    # stop), and `result` then holds only the resumed tail (pilot: 2 of 6 summary_clin "summaries" of ~600 chars).
    split = ok and tool is None and (env.get("num_turns") or 1) > 1
    append(ROOT / "calls-done.jsonl", {"role": role, "model": model, "ok": ok and not split, "rc": rc})
    if split:
        append(ROOT / "split-envelopes.jsonl", {"role": role, **{k: v for k, v in env.items() if k != "result"}})
        raise InfraError(f"{role}: reply split over {env['num_turns']} turns without tools "
                         f"(stop_reason {env.get('stop_reason')}, models {sorted(env.get('modelUsage') or {})})",
                         sum(usage_tokens(env.get("usage") or {})))
    if not ok:
        msg = f"{out[-2000:]}\n{err[-2000:]}"
        if LIMIT_RE.search(msg):
            raise LimitHit(LIMIT_RE.search(msg).group(0))
        raise InfraError(f"{role}: exit {rc}: {msg[-300:]}")
    in_tokens, out_tokens = usage_tokens(env.get("usage") or {})
    return {"text": env["result"], "turns": env.get("num_turns"), "denials": len(env.get("permission_denials") or []),
            "stop_reason": env.get("stop_reason"), "models": sorted(env.get("modelUsage") or {}),
            "in_tokens": in_tokens, "out_tokens": out_tokens}


def usage_tokens(usage: dict) -> tuple[int, int]:
    return (sum(usage.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
            usage.get("output_tokens") or 0)


def cached(path: Path, fn) -> dict | None:
    """Run fn once per path. Infrastructure failures and usage limits are retried up to 3 attempts in all (V2):
    2 per run for transport errors; a usage limit is recorded as an attempt and stops the driver, so the next run
    resumes from cache after the reset. Model answers, refusals included, are never retried."""
    prev = rj(path) if path.exists() else None
    if prev and prev.get("ok"):
        return prev
    attempts = prev["attempts"] if prev else 0
    wasted = prev.get("retry_tokens", 0) if prev else 0  # tokens of rejected attempts, still part of the arm's cost
    for _ in range(2):
        if attempts >= 3:
            break
        attempts += 1
        try:
            res = {"ok": True, "attempts": attempts, **fn(), "retry_tokens": wasted}
            wj(path, res)
            return res
        except InfraError as e:
            wasted += e.tokens
            wj(path, {"ok": False, "attempts": attempts, "error": str(e)[:300], "retry_tokens": wasted})
        except LimitHit as e:
            wj(path, {"ok": False, "attempts": attempts, "error": f"usage limit: {e}", "retry_tokens": wasted})
            raise SystemExit(f"usage limit ({e}); rerun after the reset, the cache resumes") from None
    return None


# --- contexts ---------------------------------------------------------------------------------------------------
@functools.lru_cache(maxsize=8192)
def tokens(text: str) -> int:
    from lcc.token_budget.counters import count_tokens

    return count_tokens(text, TOKEN_MODEL).value


def head_tokens(text: str, cap: int) -> str:
    if tokens(text) <= cap:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        lo, hi = (mid, hi) if tokens(text[:mid]) <= cap else (lo, mid - 1)
    return text[:lo]


def summary_context(sess: dict, summary_text: str) -> str:
    """probe-eval-v1's native arm: the summary, then up to 5 recently read files (≤ 5 000 tokens each, ≤ 50 000)."""
    s = re.sub(r"<analysis>.*?</analysis>", "", summary_text, flags=re.S)
    m = re.search(r"<summary>(.*?)(?:</summary>|$)", s, flags=re.S)
    parts, seen, total = [f"[summary of the earlier session]\n{(m.group(1) if m else s).strip()}"], set(), 0
    for b in reversed(sess["blocks"]):
        if len(seen) == 5 or total >= 50_000:
            break
        if b["kind"] != "tool_result":
            continue
        path = sess["reads"][b["id"]][2]
        if path in seen:
            continue
        seen.add(path)
        body = head_tokens(b["content"], min(5000, 50_000 - total))
        total += tokens(body)
        parts.append(f"[re-attached file {path}]\n{body}")
    return "\n\n".join(parts)


def recalled_texts(log: Path) -> str:
    """What the first pass's recalls returned, exactly as the shim emitted it (truncation notice included)."""
    parts = []
    for rec in jsonl(log):
        if rec.get("ok"):
            lines = f" lines {rec['lines']}" if rec.get("lines") else ""
            parts.append(f"[recalled {rec['id']}{lines}]\n{rec['text']}")
    return "\n\n".join(parts)


# --- answers ----------------------------------------------------------------------------------------------------
def parse_answers(text: str) -> dict[int, tuple[str, list[str], str]]:
    """number -> (letter, quotes, rest of the line after the letter, quotes included). The first line wins."""
    out: dict[int, tuple[str, list[str], str]] = {}
    for m in LINE_RE.finditer(text or ""):
        quotes = [q.strip().strip('"“”').strip() for q in m.group(3).split("| quote:")[1:]]
        out.setdefault(int(m.group(1)), (m.group(2), [q for q in quotes if q], m.group(3).strip()))
    return out


def squash(s: str) -> str:
    return " ".join(s.split())


def nums(s: str) -> set[str]:
    return {n.replace(",", ".") for n in NUM_RE.findall(s)}


def check_line(letter: str, quotes: list[str], option: str, records: dict[str, list[str]], folder: str | None,
               patient_check: bool = True) -> str | None:
    """The three verifier checks; returns the failed one, or None. records: folder -> record texts read in C.
    patient_check=False is S5's offline replay without check 2."""
    if letter == "F":
        return None
    if not quotes:
        return "quote not found"
    for q in quotes:
        sq = squash(q)
        found = [f for f, texts in records.items() if len(sq) >= 20 and any(sq in squash(t) for t in texts)]
        if not found:
            return "quote not found"
        if patient_check and folder not in found:
            return "quote is not from this patient's records"
    if not nums(option) <= nums(" ".join(quotes)):
        return "number not in quote"
    return None


def records_by_folder(sess: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for b in sess["blocks"]:
        if b["kind"] == "tool_result":
            out.setdefault(sess["reads"][b["id"]][2].split("/")[1], []).append(b["content"])
    return out


def options_of(q: dict) -> dict[str, str]:
    return {**{L: q[f"answer_{L.lower()}"] for L in "ABCDE"}, "F": F_TEXT}


def verify(sess: dict, patient: dict, first: str, patient_check: bool = True) -> dict[int, str]:
    """First-pass catches: question number -> failed check, over the parsed lines that are not F."""
    records, folder = records_by_folder(sess), sess["folders"].get(sess["target"])
    got, catches = parse_answers(first), {}
    for i, q in enumerate(patient["questions"], 1):
        if i in got:
            why = check_line(got[i][0], got[i][1], options_of(q)[got[i][0]], records, folder, patient_check)
            if why:
                catches[i] = why
    return catches


def merge_reask(sess: dict, patient: dict, first: str, second: str, catches: dict) -> tuple[dict, dict]:
    """Final lines: number -> [letter or None, option part]. First-pass lines that passed stay; a caught line takes
    its re-asked line when that passes, becomes F when the re-asked line fails again (logged with the check that
    failed the second time), and stays a response failure when the re-ask has no line for it."""
    records, folder = records_by_folder(sess), sess["folders"].get(sess["target"])
    got, again, final, forced = parse_answers(first), parse_answers(second), {}, {}
    for i, q in enumerate(patient["questions"], 1):
        if i not in catches:
            final[i] = [got[i][0], got[i][2]] if i in got else [None, ""]
        elif i not in again:
            final[i] = [None, ""]
        else:
            why = check_line(again[i][0], again[i][1], options_of(q)[again[i][0]], records, folder)
            final[i] = ["F", F_TEXT] if why else [again[i][0], again[i][2]]
            if why:
                forced[i] = why
    return final, forced


# --- phases -----------------------------------------------------------------------------------------------------
def sdir(*parts) -> Path:
    return ROOT.joinpath(*parts)


def sessions(bench: dict, which: str) -> list[dict]:
    return [rj(sdir("sessions", f"{t}__{c}.json")) for t in targets(bench, which) for c in CONDITIONS]


def phase_toolcheck() -> None:
    """V4: through the real CLI path, a scripted recall of a known id returns its bytes (one call)."""
    from lcc.relevance.transcript_stash import put

    stash, log = sdir("toolcheck", "stash"), sdir("toolcheck", "recall.jsonl")
    stash.mkdir(parents=True, exist_ok=True)
    os.environ["LCC_STASH_DIR"] = str(stash)
    secret = f"longhealth-v1 toolcheck {hashlib.sha256(str(SEED).encode()).hexdigest()}"
    digest = put(secret)
    prompt = (f"Call the recall tool with id {digest[:12]} and reply with exactly the text it returns, "
              "nothing else.")
    res = cached(sdir("toolcheck", "answer.json"),
                 lambda: cli("toolcheck", ANSWERER, SYSTEM_TOOL, prompt, "medium", (stash, log)))
    ok = bool(res) and secret in res["text"] and any(r.get("ok") for r in jsonl(log))
    wj(sdir("toolcheck", "result.json"), {"ok": ok})
    print("V4", "pass" if ok else "FAIL")


def phase_build(bench: dict, which: str) -> None:
    bad = []
    for t in targets(bench, which):
        bad += [(t, i) for i, q in enumerate(bench[t]["questions"], 1) if gold_letter(q, "ans_early") is None]
        for c in CONDITIONS:
            wj(sdir("sessions", f"{t}__{c}.json"), build_session(bench, t, c))
    print(f"built {3 * len(targets(bench, which))} sessions; questions whose correct text matches no single option: "
          f"{len(bad)} {bad[:5]}")


def phase_compact(bench: dict, which: str) -> None:
    import lcc

    for s in sessions(bench, which):
        res = compact_session(s, sdir("stash", s["id"]))
        wj(sdir("compact", f"{s['id']}.json"), {**res, "lcc_version": lcc.__version__, "lcc_file": lcc.__file__})
        print(s["id"], "ok" if res["ok"] else "VIOLATION", len(res["stashed"]), "stashed")


def phase_locate(bench: dict, which: str) -> None:
    receipt = {}
    for s in sessions(bench, which):
        comp = rj(sdir("compact", f"{s['id']}.json"))
        reasons: dict[str, int] = {}
        for r in comp["stashed"].values():
            reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
        receipt[s["id"]] = {"rows": locate_session(s, comp, bench[s["target"]]), "stash_reasons": reasons,
                            "ok": comp["ok"]}
    counts: dict[str, dict[str, int]] = {}
    for sid, r in receipt.items():
        c = counts.setdefault(sid.split("__")[1], {})
        for row in r["rows"]:
            c[row.get("where", "absent")] = c.get(row.get("where", "absent"), 0) + 1
    wj(sdir(f"location-receipt-{which}.json"), {"counts": counts, "sessions": receipt})
    print(json.dumps(counts))


def answer_call(arm: str, prompt: str, tool: bool, use) -> dict:
    """One answer attempt; the recall log starts empty for each attempt, so it belongs to the saved answer."""
    if use:
        use[1].parent.mkdir(parents=True, exist_ok=True)
        use[1].write_text("")
    return cli(arm, ANSWERER, SYSTEM_TOOL if tool else SYSTEM_NOTOOL, prompt, "medium", use)


def phase_run(bench: dict, which: str, arm: str) -> None:
    ctx_kind, tool, qtext = ARMS[arm]
    empty = sdir("stash-empty")
    empty.mkdir(parents=True, exist_ok=True)
    if arm == "none":
        for t in targets(bench, which):
            prompt = f"{rj(sdir('sessions', f'{t}__ans_early.json'))['P_none']}\n\n{Q_N}"
            cached(sdir("answers", arm, f"{t}.json"),
                   lambda prompt=prompt: cli("none", ANSWERER, SYSTEM_NONE, prompt, "medium"))
        return
    for s in sessions(bench, which):
        comp = rj(sdir("compact", f"{s['id']}.json"))
        if ctx_kind == "full":
            context, stash = render(s["blocks"]), empty
        elif ctx_kind == "stashed":
            context, stash = render(comp["blocks"]), sdir("stash", s["id"])
        else:
            text = S_TEXT if ctx_kind == "summary_s" else S_CLIN
            summ = cached(sdir("summaries", ctx_kind, f"{s['id']}.json"),
                          lambda s=s, text=text: cli("summary", SUMMARIZER, SYSTEM_SUM,
                                                     f"{render(s['blocks'])}\n\n{text}", "high"))
            if not summ:
                continue
            context, stash = summary_context(s, summ["text"]), None
        prompt = f"{context}\n\n{s['P']}\n\n{qtext}"
        use = (stash, sdir("recall-log", arm, f"{s['id']}.jsonl")) if tool else None
        first = cached(sdir("answers", arm, f"{s['id']}.json"),
                       lambda prompt=prompt, use=use: answer_call(arm, prompt, tool, use))
        if arm != "stashed_v" or not first:
            continue
        patient = bench[s["target"]]
        catches = verify(s, patient, first["text"])
        replay = verify(s, patient, first["text"], patient_check=False)  # S5, offline
        if not catches:
            wj(sdir("verify", f"{s['id']}.json"),
               {"catches": {}, "catches_no_patient_check": replay, "forced": {}, "reask": False, "final": None})
            continue
        note = "\n".join(f"{i}: {catches[i]}" for i in sorted(catches))
        recalled = recalled_texts(use[1])
        reask = (f"{prompt}\n\n" + (f"Records you recalled while answering:\n{recalled}\n\n" if recalled else "")
                 + f"Your earlier answer:\n{first['text']}\n\nThese answers failed the record check:\n{note}\n"
                 "Answer again only these question numbers, in the same form.")
        use2 = (stash, sdir("recall-log", "stashed_v_reask", f"{s['id']}.jsonl"))
        second = cached(sdir("answers", "stashed_v_reask", f"{s['id']}.json"),
                        lambda reask=reask, use2=use2: answer_call("reask", reask, True, use2))
        if second:
            final, forced = merge_reask(s, patient, first["text"], second["text"], catches)
            wj(sdir("verify", f"{s['id']}.json"), {"catches": catches, "catches_no_patient_check": replay,
                                                   "forced": forced, "reask": True, "final": final})


# --- scoring ----------------------------------------------------------------------------------------------------
def score_session(arm: str, sess: dict, patient: dict, text: str, final: dict | None = None,
                  where: dict | None = None) -> list[dict]:
    """One row per question. `substring` is LongHealth's own rule (S4): the correct text anywhere in the answer line,
    quotes included."""
    got = parse_answers(text)
    rows = []
    for i, q in enumerate(patient["questions"], 1):
        if final:
            letter, opt = final[i]
        else:
            letter, opt = (got[i][0], got[i][2]) if i in got else (None, "")
        gold = gold_letter(q, sess["condition"])
        want = F_TEXT if sess["condition"] == "unans" else q["correct"]
        rows.append({"patient": sess["target"], "qno": i, "condition": sess["condition"], "arm": arm,
                     "correct": int(letter is not None and letter == gold), "failure": int(letter is None),
                     "unsupported": int(sess["condition"] == "unans" and letter in tuple("ABCDE")),
                     "substring": int(want in opt), "exact_value": bool(re.search(r"\d", q["correct"])),
                     "where": (where or {}).get(i)})
    return rows


def metric(rows: list[dict], name: str, key: str = "correct", where: str | None = None,
           condition: str | None = None) -> tuple[int, int]:
    sel = [r for r in rows if (where is None or r["where"] == where)
           and (condition is None or r["condition"] == condition)]
    if name in ("A", "E"):
        sel = [r for r in sel if r["condition"] != "unans" and (name == "A" or r["exact_value"])]
        return sum(r[key] for r in sel), len(sel)
    sel = [r for r in sel if r["condition"] == "unans"]
    return sum(r[key if name == "U" else "unsupported"] for r in sel), len(sel)


def bootstrap(rows: list[dict], a: str, b: str, name: str, n: int | None = None, **filt) -> dict:
    """Paired cluster bootstrap over target patients of pooled(a) − pooled(b) on metric `name`."""
    by: dict[str, dict[str, list[dict]]] = {}
    for r in rows:
        by.setdefault(r["patient"], {}).setdefault(r["arm"], []).append(r)
    clusters = sorted(p for p, arms in by.items() if a in arms and b in arms)

    def diff(sample):
        na = [metric(by[p][a], name, **filt) for p in sample]
        nb = [metric(by[p][b], name, **filt) for p in sample]
        da, db = sum(x[1] for x in na), sum(x[1] for x in nb)
        return (sum(x[0] for x in na) / da if da else 0.0) - (sum(x[0] for x in nb) / db if db else 0.0)

    rng = random.Random(SEED)
    n = n or BOOT_N
    draws = sorted(diff([rng.choice(clusters) for _ in clusters]) for _ in range(n)) if clusters else [0.0]
    return {"diff": round(diff(clusters), 4), "lo": round(draws[int(0.025 * len(draws))], 4),
            "hi": round(draws[min(len(draws) - 1, int(0.975 * len(draws)))], 4), "clusters": len(clusters),
            "per_patient": {p: round(diff([p]), 4) for p in clusters}}


def verdicts(tests: dict, gates: dict, complete: bool) -> dict | None:
    """H1–H3 pass/fail, or None when the run is invalid: any gate failed, or an arm is missing (PROTOCOL.md)."""
    if not complete or not all(gates.values()):
        return None
    return {"H1": tests["H1"]["lo"] > -0.05, "H2": tests["H2_s"]["lo"] > 0 and tests["H2_clin"]["lo"] > 0,
            "H3": tests["H3_UA"]["hi"] < 0 and tests["H3_A"]["lo"] > -0.05}


def answer_of(arm: str, sid: str) -> dict | None:
    """A finished answer: ok, and for stashed_v also its verifier record (re-ask included when one was needed)."""
    a = sdir("answers", arm, f"{sid}.json")
    if not (a.exists() and rj(a).get("ok")):
        return None
    usage = rj(a)["in_tokens"] + rj(a)["out_tokens"]
    if arm != "stashed_v":
        return {"text": rj(a)["text"], "final": None, "usage": usage}
    v = sdir("verify", f"{sid}.json")
    if not v.exists():
        return None
    final = rj(v).get("final")
    r2 = sdir("answers", "stashed_v_reask", f"{sid}.json")
    if r2.exists() and rj(r2).get("ok"):
        usage += rj(r2)["in_tokens"] + rj(r2)["out_tokens"]
    return {"text": rj(a)["text"], "final": {int(k): x for k, x in final.items()} if final else None, "usage": usage}


def recall_behaviour(arm: str, kept: list[dict], loc: dict, comp_of) -> dict:
    """R1–R6 for a tool arm, from its recall logs (behaviour only; never an outcome)."""
    needed = hit = calls = ok_calls = gold_calls = cap = zero = 0
    recalled_tok = stashed_tok = 0
    errors: dict[str, int] = {}
    ratios = []
    for s in kept:
        log = jsonl(sdir("recall-log", arm, f"{s['id']}.jsonl"))
        ok = [r for r in log if r.get("ok")]  # retrieval and token metrics; R3 counts every attempt
        rows = loc["sessions"][s["id"]]["rows"]
        gold = {sha[:12] for r in rows for sha in r.get("gold_shas", [])}
        for r in rows:
            if r.get("where") == "stash_dependent":
                needed += 1
                hit += any(c["id"][:12] in {x[:12] for x in r["gold_shas"]} for c in ok)
        calls += len(log)
        ok_calls += len(ok)
        gold_calls += sum(c["id"][:12] in gold for c in ok)
        cap += any(r.get("error") == "cap" for r in log)
        zero += not log
        for r in log:
            if not r.get("ok"):
                errors[r.get("error", "?")[:40]] = errors.get(r.get("error", "?")[:40], 0) + 1
        comp = comp_of(s["id"])
        st = sum(tokens(b["content"]) for b in s["blocks"] if b["kind"] == "tool_result" and b["id"] in comp["stashed"])
        rt = sum(c.get("tokens") or 0 for c in ok)
        stashed_tok, recalled_tok = stashed_tok + st, recalled_tok + rt
        ctx = render(comp["blocks"]) if arm != "full_t" else render(s["blocks"])
        ratios.append((tokens(ctx) + rt) / max(1, tokens(render(s["blocks"]))))
    n = max(1, len(kept))
    return {"R1_needed_recall": hit / max(1, needed), "R1_n": needed, "R2_precision": gold_calls / max(1, ok_calls),
            "R3_calls_per_session": calls / n, "R3_ok_calls_per_session": ok_calls / n, "R3_share_zero": zero / n,
            "R3_share_cap": cap / n,
            "R4_recalled_over_stashed": recalled_tok / max(1, stashed_tok),
            "R5_restored_context_median": statistics.median(ratios) if ratios else None, "R6_errors": errors}


def status_of(path: Path) -> str:
    """ok, terminal (an infrastructure failure after 3 attempts) or pending (never run, or still retryable)."""
    if not path.exists():
        return "pending"
    r = rj(path)
    return "ok" if r.get("ok") else "terminal" if r.get("attempts", 0) >= 3 else "pending"


def session_status(arm: str, sid: str) -> str:
    kind = ARMS[arm][0]
    if kind in ("summary_s", "summary_clin") and status_of(sdir("summaries", kind, f"{sid}.json")) != "ok":
        return status_of(sdir("summaries", kind, f"{sid}.json"))
    st = status_of(sdir("answers", arm, f"{sid}.json"))
    if st != "ok" or arm != "stashed_v" or sdir("verify", f"{sid}.json").exists():
        return st
    return status_of(sdir("answers", "stashed_v_reask", f"{sid}.json"))


def consumed_usage() -> dict[str, int]:
    """Every call's tokens by arm, dropped sessions and rejected (split) attempts included (the re-ask counts for
    stashed_v, each summary for its arm)."""
    out: dict[str, int] = {}
    for group, arm_of in (("answers", lambda d: "stashed_v" if d == "stashed_v_reask" else d), ("summaries", str)):
        for f in sdir(group).glob("*/*.json") if sdir(group).is_dir() else ():
            r, arm = rj(f), arm_of(f.parent.name)
            used = r.get("retry_tokens", 0) + (r["in_tokens"] + r["out_tokens"] if r.get("ok") else 0)
            out[arm] = out.get(arm, 0) + used
    return out


def phase_score(bench: dict, which: str) -> None:
    present = [a for a in ARMS if sdir("answers", a).is_dir()]
    run_arms = [a for a in present if a != "none"]
    every = sessions(bench, which)
    status = {s["id"]: [session_status(a, s["id"]) for a in run_arms] for s in every}
    none_status = {t: status_of(sdir("answers", "none", f"{t}.json")) for t in targets(bench, which)}
    pending = any("pending" in st for st in status.values()) or (
        "none" in present and "pending" in none_status.values())
    # Verdicts need every arm and no answer still to run; only terminal infrastructure failures drop (V2).
    complete = set(present) == set(ARMS) and not pending
    # V2: a session with a terminal failure in any arm, the none baseline of its target included, is dropped
    # from every arm.
    kept = [s for s in every if all(x == "ok" for x in status[s["id"]])
            and ("none" not in present or none_status[s["target"]] == "ok")]
    none_ok = {t for t, st in none_status.items() if st == "ok"}
    loc_path = sdir(f"location-receipt-{which}.json")
    loc = rj(loc_path) if loc_path.exists() else {"counts": {}, "sessions": {}}
    comps = {s["id"]: rj(sdir("compact", f"{s['id']}.json")) for s in every}
    rows: list[dict] = []
    usage: dict[str, int] = {}
    for s in kept:
        where = {r["qno"]: r.get("where") for r in loc["sessions"].get(s["id"], {}).get("rows", [])}
        for arm in run_arms:
            ans = answer_of(arm, s["id"])
            got = score_session(arm, s, bench[s["target"]], ans["text"], ans["final"], where)
            if not comps[s["id"]]["ok"] and ARMS[arm][0] == "stashed":  # broken stash contract: treatment failure
                got = [{**r, "correct": 0, "substring": 0} for r in got]
            rows += got
            extra = 0
            if ARMS[arm][0] in ("summary_s", "summary_clin"):
                sm = rj(sdir("summaries", ARMS[arm][0], f"{s['id']}.json"))
                extra = sm["in_tokens"] + sm["out_tokens"]
            usage[arm] = usage.get(arm, 0) + ans["usage"] + extra
    for t in sorted(none_ok & {s["target"] for s in kept}):
        a = rj(sdir("answers", "none", f"{t}.json"))
        rows += score_session("none", {"target": t, "condition": "ans_early"}, bench[t], a["text"])
        usage["none"] = usage.get("none", 0) + a["in_tokens"] + a["out_tokens"]

    table = {arm: {m: metric([r for r in rows if r["arm"] == arm], m) for m in ("A", "E", "U", "UA")}
             for arm in present}
    acc = {arm: v["A"][0] / v["A"][1] if v["A"][1] else None for arm, v in table.items()}

    def share(cond, where):
        c = loc["counts"].get(cond, {})
        return c.get(where, 0) / sum(c.values()) if c else 0.0

    def parse_rate(arm):
        sel = [r for r in rows if r["arm"] == arm]
        return 1 - sum(r["failure"] for r in sel) / len(sel) if sel else 0.0

    dropped = [s["id"] for s in every if s not in kept and "pending" not in status[s["id"]]]
    toolcheck = sdir("toolcheck", "result.json")
    gates = {
        "V1": (acc.get("full_t") or 0) >= 0.60,
        "V2": bool(every) and len(dropped) <= 0.05 * len(every),
        "V3": share("ans_early", "stash_dependent") >= 0.80,
        "V3b": share("ans_late", "in_view") >= 0.80,
        "V4": toolcheck.exists() and rj(toolcheck)["ok"],
        "V5": bool(present) and all(parse_rate(arm) >= 0.95 for arm in present),
        "V6_not_contaminated": acc.get("none") is not None and acc.get("full_t") is not None
        and acc["none"] < acc["full_t"] - 0.10,
    }
    tests = {
        "H1": bootstrap(rows, "stashed_t", "full_t", "A"),
        "H2_s": bootstrap(rows, "stashed_t", "summary_s", "E"),
        "H2_clin": bootstrap(rows, "stashed_t", "summary_clin", "E"),
        "H3_UA": bootstrap(rows, "stashed_v", "stashed_t", "UA"),
        "H3_A": bootstrap(rows, "stashed_v", "stashed_t", "A"),
    }
    secondary = {
        "S1_tool_effect_stash_dependent": bootstrap(rows, "stashed_t", "stashed_0", "A", where="stash_dependent"),
        "S1_recall_behaviour": {arm: recall_behaviour(arm, kept, loc, comps.get) for arm in ("stashed_t", "full_t")
                                if arm in run_arms},
        "S2_by_condition": {c: {k: bootstrap(rows, a, b, m, condition=c) for k, (a, b, m) in {
            "H1": ("stashed_t", "full_t", "A"), "H2_s": ("stashed_t", "summary_s", "E"),
            "H2_clin": ("stashed_t", "summary_clin", "E"), "H3_A": ("stashed_v", "stashed_t", "A")}.items()}
            for c in ("ans_early", "ans_late")},
        "S3_full_vs_summaries": {f"{b}_{m}": bootstrap(rows, "full_t", b, m)
                                 for b in ("summary_s", "summary_clin") for m in ("A", "U", "E")},
        "S4_substring_rule": {k: bootstrap(rows, a, b, m, key="substring") for k, (a, b, m) in {
            "H1": ("stashed_t", "full_t", "A"), "H2_s": ("stashed_t", "summary_s", "E"),
            "H2_clin": ("stashed_t", "summary_clin", "E"), "H3_U": ("stashed_v", "stashed_t", "U"),
            "H3_A": ("stashed_v", "stashed_t", "A")}.items()},
        "S5_first_pass_catches": s5_counts(kept),
    }
    sizes = {
        "C_tokens": sum(tokens(render(s["blocks"])) for s in kept),
        "C_prime_tokens": sum(tokens(render(comps[s["id"]]["blocks"])) for s in kept),
        "summary_context_tokens": {k: sum(tokens(summary_context(s, rj(sdir("summaries", k, f"{s['id']}.json"))["text"]))
                                          for s in kept if sdir("summaries", k, f"{s['id']}.json").exists())
                                   for k in ("summary_s", "summary_clin")},
        "cumulative_usage_tokens": consumed_usage(),
        "cumulative_usage_cohort_tokens": usage,
    }
    failures = {arm: {c: sum(r["failure"] for r in rows if r["arm"] == arm and r["condition"] == c)
                      for c in CONDITIONS} for arm in present}
    verdict = verdicts(tests, gates, complete)
    wj(sdir(f"results-{which}.json"), {"complete": complete, "table": table, "gates": gates, "tests": tests,
                                       "verdict": verdict, "secondary": secondary, "sizes": sizes,
                                       "response_failures": failures, "dropped": dropped, "items": rows})
    print(json.dumps({"complete": complete, "table": table, "gates": gates, "verdict": verdict, "dropped": dropped},
                     indent=1))


def s5_counts(kept: list[dict]) -> dict:
    """First-pass catches by check, with and without check 2, split by condition (S5 says nothing about H3)."""
    out: dict[str, dict[str, dict[str, int]]] = {}
    for s in kept:
        v = sdir("verify", f"{s['id']}.json")
        if not v.exists():
            continue
        rec = rj(v)
        for kind in ("catches", "catches_no_patient_check"):
            c = out.setdefault(s["condition"], {}).setdefault(kind, {})
            for why in rec[kind].values():
                c[why] = c.get(why, 0) + 1
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=("fetch", "toolcheck", "build", "compact", "locate", "run", "score"))
    ap.add_argument("--set", dest="which", choices=("pilot", "D"), default="pilot")
    ap.add_argument("--arm", choices=tuple(ARMS))
    a = ap.parse_args(argv)
    with driver_lock():
        bench = load_benchmark(fetch())
        if a.phase == "toolcheck":
            phase_toolcheck()
        elif a.phase == "build":
            phase_build(bench, a.which)
        elif a.phase == "compact":
            phase_compact(bench, a.which)
        elif a.phase == "locate":
            phase_locate(bench, a.which)
        elif a.phase == "run":
            if not a.arm:
                raise SystemExit("run needs --arm")
            phase_run(bench, a.which, a.arm)
        elif a.phase == "score":
            phase_score(bench, a.which)


if __name__ == "__main__":
    main()
