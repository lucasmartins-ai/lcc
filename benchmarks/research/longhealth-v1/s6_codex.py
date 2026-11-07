"""LongHealth v1, S6 (PROTOCOL.md Amendment 5): `full_t` and `stashed_t` with a second answerer, GPT via `codex exec`.

It imports the frozen harness (`longhealth_v1.py`, Amendment 2) and changes none of it: the same sessions, compactions,
stashes, prompt (context, then P, then Q-T), system text, recall shim with its caps and log, scoring and bootstrap.
What differs is the CLI that carries the call, and that S6 writes only under <ROOT>/s6, with its own call ledger and
cap. The frozen D caches are read, never written. Calls run on the owner's ChatGPT plan through the Codex CLI.

    PYTHONPATH=<lcc pin worktree>/src HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 ~/lcc/.venv/bin/python \\
        benchmarks/research/longhealth-v1/s6_codex.py {toolcheck|run --arm full_t|stashed_t|score} --set pilot|D \\
        [--only <session id> ...]
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import longhealth_v1 as lh  # noqa: E402  the frozen harness, imported as is

MODEL, EFFORT = "gpt-6.1-sol", "medium"  # the Codex catalog's workhorse model, at the effort the Claude answerer had
CODEX_VERSION = "codex-cli 0.166.0"  # the driver refuses another version: the CLI shapes the prompt and the tools
S6_CAP = 130  # toolcheck 1 + pilot 4 + D 106, and room for V2 retries; not part of the 650-call D budget
PAUSE_AT = 80  # % of the plan's 5-hour or weekly window: no S6 call starts above it (Amendment 3's pacing rule)
APPROVED = None  # the owner's approval date, set by the commit that records it in Amendment 5; `run` refuses until
ARMS = ("full_t", "stashed_t")
MAIN_CODEX_HOME = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
# Everything Codex would add beyond recall is off. Shell off is what keeps the gold (ROOT/benchmark_v5.json) and the
# stash files out of reach; the rest keeps the prompt to the system text, the context, P and Q-T.
OFF = ("shell_tool", "unified_exec", "plugins", "apps", "skill_search", "view_image", "image_generation",
       "browser_use", "computer_use", "in_app_browser", "memories", "tool_suggest", "goals", "sleep_tool", "hooks")
CONFIG = ('approval_policy="never"', 'web_search="disabled"', "skills.bundled.enabled=false",
          "include_permissions_instructions=false", "include_environment_context=false",
          "include_apps_instructions=false", "include_collaboration_mode_instructions=false", "project_doc_max_bytes=0")
DENIED = {"command_execution", "file_change", "web_search"}  # an answer that used one is never scored: the run stops
TRANSPORT_RE = re.compile(r"stream disconnected|error sending request|connection (?:reset|refused|closed)|timed? ?out|"
                          r"\b50[0-4]\b|internal server error|service unavailable|bad gateway|overloaded", re.I)
# Only a provider message that says so is a refusal; any other failed turn (401, no message, ...) is infrastructure.
REFUSAL_RE = re.compile(r"refus|usage polic|content polic|safety|classifier|flagged|content.?filter|moderation|"
                        r"invalid_prompt|cyber", re.I)
PILOT = ("patient_03__ans_early", "patient_05__ans_early")  # Amendment 5's pilot: 2 sessions from the pilot pool


def s6dir(*parts) -> Path:
    return lh.ROOT.joinpath("s6", *parts)


@functools.cache
def check_version() -> None:
    v = subprocess.run(["codex", "--version"], capture_output=True, text=True).stdout.strip()
    if v != CODEX_VERSION:
        raise SystemExit(f"S6 is pinned to {CODEX_VERSION}; found {v!r}. A new version needs a dated amendment.")


def codex_home() -> Path:
    """A Codex home with only the owner's login in it (no config, AGENTS.md, skills or plugins). auth.json is a link to
    the real one, so a token refresh writes through it. If Codex ever replaced the link with a file, the two logins
    would drift: the driver stops and says how to reconcile."""
    home = s6dir("codex-home")
    home.mkdir(parents=True, exist_ok=True)
    link, real = home / "auth.json", MAIN_CODEX_HOME / "auth.json"
    if link.exists() and not link.is_symlink():
        raise SystemExit(f"{link} is a file, not a link to {real}: Codex replaced it. If it is newer, copy it over "
                         f"{real}; then delete it and rerun.")
    if not link.is_symlink():
        link.symlink_to(real)
    if link.resolve() != real.resolve():
        raise SystemExit(f"{link} points to {link.resolve()}, not {real}")
    return home


def toml(v) -> str:
    """A TOML value for `-c`: JSON strings and string arrays are valid TOML; tables are inline."""
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k} = {json.dumps(x)}" for k, x in v.items()) + "}"
    return json.dumps(v)


def argv_for(system: Path, cwd: Path, stash: Path, log: Path) -> list[str]:
    srv = lh.mcp_config(stash, log)["mcpServers"]["stash"]  # the exact server the Claude arms got
    argv = ["codex", "exec", "--json", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
            "--sandbox", "read-only", "-C", str(cwd), "-m", MODEL]
    for c in (f"model_reasoning_effort={toml(EFFORT)}", f"model_instructions_file={toml(str(system))}", *CONFIG,
              f"mcp_servers.stash.command={toml(srv['command'])}", f"mcp_servers.stash.args={toml(srv['args'])}",
              f"mcp_servers.stash.env={toml(srv['env'])}", "mcp_servers.stash.required=true",
              # approval_policy "never" otherwise refuses every MCP call; Codex's own cut of tool output sits above
              # the shim's 20,000-token cap, so the shim's cap is the one that binds, as for the Claude arms
              'mcp_servers.stash.tools.recall.approval_mode="approve"',
              "mcp_servers.stash.tools.recall.output_token_limit=40000"):
        argv += ["-c", c]
    for f in OFF:
        argv += ["--disable", f]
    argv.append("-")  # the prompt comes on stdin
    assert not any("dangerously" in a for a in argv), "never skip approvals or the sandbox"
    return argv


def plan_window(env: dict) -> dict | None:
    """The plan's 5-hour (primary) and weekly (secondary) window use in %, read from `codex app-server` (no model
    call). None when it cannot be read."""
    p = subprocess.Popen(["codex", "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, env=env)
    timer = threading.Timer(30, p.kill)
    timer.start()
    try:
        for m in ({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "lh-s6", "version": "0"}}},
                  {"method": "initialized"}, {"id": 2, "method": "account/rateLimits/read"}):
            p.stdin.write(json.dumps({"jsonrpc": "2.0", **m}) + "\n")
        p.stdin.flush()
        for line in p.stdout:
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if m.get("id") == 2:
                rl = (m.get("result") or {}).get("rateLimits") or {}
                got = {k: (rl.get(k) or {}).get("usedPercent") for k in ("primary", "secondary")}
                return got if all(isinstance(v, (int, float)) for v in got.values()) else None
    except OSError:
        pass
    finally:
        timer.cancel()
        p.kill()
        p.wait()
    return None


def codex_call(role: str, prompt: str, tool: tuple[Path, Path]) -> dict:
    """One call -> its text and usage. Written to the S6 ledger before it starts, so an interrupted call counts."""
    ledger = s6dir("calls.jsonl")
    if len(lh.jsonl(ledger)) >= S6_CAP:
        raise SystemExit(f"S6 call cap {S6_CAP} reached")
    check_version()
    home = codex_home()
    s6dir("home").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "ANTHROPIC_", "OPENAI_", "CODEX_"))}
    env.update(CODEX_HOME=str(home), HOME=str(s6dir("home")))  # HOME hides ~/.agents/skills
    before = plan_window(env)
    if before is None:
        raise SystemExit("cannot read the plan's usage windows; S6 does not call without them")
    if max(before.values()) >= PAUSE_AT:
        raise SystemExit(f"plan window at {before} (pause at {PAUSE_AT} %); rerun after the reset, the cache resumes")
    n = len(lh.jsonl(ledger)) + 1
    lh.append(ledger, {"role": role, "model": MODEL})
    with tempfile.TemporaryDirectory(prefix="longhealth-s6-") as tmp:
        cwd, system = Path(tmp) / "cwd", Path(tmp) / "system.txt"
        cwd.mkdir()
        system.write_text(lh.SYSTEM_TOOL, encoding="utf-8")
        try:
            r = subprocess.run(argv_for(system, cwd, *tool), input=prompt, capture_output=True, text=True, cwd=cwd,
                               timeout=lh.TIMEOUT_S + 60, env=env)
            out, err, rc = r.stdout, r.stderr, r.returncode
        except subprocess.TimeoutExpired as e:  # keep what streamed before the kill (bytes, whatever `text` says)
            out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            err, rc = "timeout", -9
    events = []
    for line in out.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    s6dir("events").mkdir(parents=True, exist_ok=True)
    (s6dir("events") / f"{n:04d}.jsonl").write_text(out + (f"\n# stderr\n{err[-4000:]}" if err else ""))
    rec = {"n": n, "role": role, "rc": rc, "outcome": "stopped", "plan_before": before,
           "kinds": kinds_of(events)}  # every call's items, retried and dropped attempts included
    try:
        res = parse_events(events, rc, err)
        rec["outcome"] = "refusal" if res["refusal"] else "ok"
        return res
    except (lh.InfraError, lh.LimitHit) as e:
        rec["outcome"] = type(e).__name__
        raise
    finally:
        rec["plan_after"] = plan_window(env)  # the plan share of this call, as far as whole percents show it
        lh.append(s6dir("calls-done.jsonl"), rec)


def items_of(events: list[dict], stages=("item.completed",)) -> list[dict]:
    return [e["item"] for e in events if e.get("type") in stages and isinstance(e.get("item"), dict)]


def kinds_of(events: list[dict]) -> dict[str, int]:
    kinds: dict[str, int] = {}
    for i in items_of(events):
        kinds[i.get("type", "?")] = kinds.get(i.get("type", "?"), 0) + 1
    return kinds


def parse_events(events: list[dict], rc: int, err: str) -> dict:
    items, kinds = items_of(events), kinds_of(events)
    # a denied tool that only started (then a crash or timeout) stops the run too
    used = DENIED & {i.get("type") for i in items_of(events, ("item.started", "item.updated", "item.completed"))}
    if used:
        raise SystemExit(f"isolation broke: the answerer used {sorted(used)}; nothing is scored")
    usage = {}
    for e in events:
        if e.get("type") == "turn.completed":
            for k, v in (e.get("usage") or {}).items():
                usage[k] = usage.get(k, 0) + (v or 0)
    failed = [str((e.get("error") or {}).get("message") or e) for e in events if e.get("type") == "turn.failed"]
    texts = [i.get("text") for i in items if i.get("type") == "agent_message"]
    started = any(e.get("type") == "turn.started" for e in events)
    base = {"kinds": kinds, "usage": usage, "in_tokens": usage.get("input_tokens", 0),
            "out_tokens": usage.get("output_tokens", 0)}
    if rc == 0 and not failed and texts and isinstance(texts[-1], str):
        return {**base, "text": texts[-1], "refusal": None}
    msg = " | ".join(failed) + "\n" + "\n".join(str(e.get("message")) for e in events if e.get("type") == "error") \
        + "\n" + err[-2000:]
    if lh.LIMIT_RE.search(msg):
        raise lh.LimitHit(lh.LIMIT_RE.search(msg).group(0))
    if started and failed and REFUSAL_RE.search(failed[-1]) and not TRANSPORT_RE.search(msg):
        # The provider ended the turn with a refusal: scored wrong on every question, never retried (Amendment 5).
        return {**base, "text": "", "refusal": failed[-1][:300]}
    raise lh.InfraError(f"codex: exit {rc}: {msg[-300:]}", base["in_tokens"] + base["out_tokens"])


# --- phases -----------------------------------------------------------------------------------------------------
def phase_toolcheck() -> None:
    """V4 for S6: through the real Codex path, a scripted recall of a known id returns its bytes (one call)."""
    from lcc.relevance.transcript_stash import put

    stash, log = s6dir("toolcheck", "stash"), s6dir("toolcheck", "recall.jsonl")
    stash.mkdir(parents=True, exist_ok=True)
    os.environ["LCC_STASH_DIR"] = str(stash)
    secret = f"longhealth-v1 toolcheck {lh.hashlib.sha256(str(lh.SEED).encode()).hexdigest()}"
    digest = put(secret)
    prompt = (f"Call the recall tool with id {digest[:12]} and reply with exactly the text it returns, "
              "nothing else.")
    res = lh.cached(s6dir("toolcheck", "answer.json"), lambda: answer(prompt, stash, log))
    ok = bool(res) and secret in res["text"] and any(r.get("ok") for r in lh.jsonl(log))
    lh.wj(s6dir("toolcheck", "result.json"), {"ok": ok})
    print("V4 (S6)", "pass" if ok else "FAIL")


def answer(prompt: str, stash: Path, log: Path) -> dict:
    """One answer attempt; the recall log starts empty for each attempt, as in the frozen `answer_call`."""
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("")
    return codex_call("s6", prompt, (stash, log))


def prompt_of(sess: dict, arm: str) -> tuple[str, Path]:
    """The frozen phase_run's prompt and stash for a tool arm: context, then P, then Q-T."""
    comp = lh.rj(lh.sdir("compact", f"{sess['id']}.json"))
    if arm == "full_t":
        context, stash = lh.render(sess["blocks"]), lh.sdir("stash-empty")
    else:
        context, stash = lh.render(comp["blocks"]), lh.sdir("stash", sess["id"])
    return f"{context}\n\n{sess['P']}\n\n{lh.Q_T}", stash


def selected(bench: dict, which: str, only: list[str] | None) -> list[dict]:
    every = lh.sessions(bench, which)
    if only:
        missing = set(only) - {s["id"] for s in every}
        if missing:
            raise SystemExit(f"not in set {which}: {sorted(missing)}")
        return [s for s in every if s["id"] in only]
    return every


def phase_run(bench: dict, which: str, arm: str, only: list[str] | None) -> None:
    lh.sdir("stash-empty").mkdir(parents=True, exist_ok=True)
    for s in selected(bench, which, only):
        if s["id"] in d_dropped(which):
            continue  # S6 runs on the sessions D kept
        prompt, stash = prompt_of(s, arm)
        log = s6dir("recall-log", arm, f"{s['id']}.jsonl")
        lh.cached(s6dir("answers", arm, f"{s['id']}.json"),
                  lambda prompt=prompt, stash=stash, log=log: answer(prompt, stash, log))


def d_dropped(which: str) -> set[str]:
    path = lh.sdir(f"results-{which}.json")
    if not path.exists():
        raise SystemExit(f"{path} is missing: S6 runs on the sessions the scored {which} run kept")
    return set(lh.rj(path)["dropped"])


def pilot_failures() -> list[str]:
    """Amendment 5's gate before any D call: each pilot answer parsed (≥ 95 % of its 20 lines) and not refused, and
    `stashed_t` got recalled text back in each pilot session. A denied tool never reaches a cached answer."""
    bad = []
    for sid in PILOT:
        for arm in ARMS:
            path = s6dir("answers", arm, f"{sid}.json")
            a = lh.rj(path) if path.exists() else {}
            if not a.get("ok") or a.get("refusal"):
                bad.append(f"{arm}/{sid}: {'refused' if a.get('refusal') else 'no answer'}")
            elif sum(i in lh.parse_answers(a["text"]) for i in range(1, 21)) < 19:
                bad.append(f"{arm}/{sid}: under 95 % of lines parsed")
        if not any(r.get("ok") for r in lh.jsonl(s6dir("recall-log", "stashed_t", f"{sid}.jsonl"))):
            bad.append(f"stashed_t/{sid}: no recall returned text")
    return bad


def phase_score(bench: dict, which: str, only: list[str] | None) -> None:
    """S6's report (Amendment 5): the table, gates V1, V2, V4 and V5, and `stashed_t − full_t` with its CI. No pass
    or fail: S6 has no hypothesis."""
    every = [s for s in selected(bench, which, only) if s["id"] not in d_dropped(which)]
    cap_spent = len(lh.jsonl(s6dir("calls.jsonl"))) >= S6_CAP
    status = {s["id"]: [lh.status_of(s6dir("answers", a, f"{s['id']}.json")) for a in ARMS] for s in every}
    if cap_spent:
        status = {sid: ["terminal" if x == "pending" else x for x in st] for sid, st in status.items()}
    pending = any("pending" in st for st in status.values())
    kept = [s for s in every if all(x == "ok" for x in status[s["id"]])]
    dropped = [s["id"] for s in every if s not in kept and "pending" not in status[s["id"]]]
    loc_path = lh.sdir(f"location-receipt-{which}.json")
    loc = lh.rj(loc_path) if loc_path.exists() else {"counts": {}, "sessions": {}}
    comps = {s["id"]: lh.rj(lh.sdir("compact", f"{s['id']}.json")) for s in every}
    rows: list[dict] = []
    usage: dict[str, dict[str, int]] = {}
    refusals: dict[str, list[str]] = {}
    kinds: dict[str, dict[str, int]] = {}
    for s in kept:
        where = {r["qno"]: r.get("where") for r in loc["sessions"].get(s["id"], {}).get("rows", [])}
        for arm in ARMS:
            ans = lh.rj(s6dir("answers", arm, f"{s['id']}.json"))
            got = lh.score_session(arm, s, bench[s["target"]], ans["text"], None, where)
            if not comps[s["id"]]["ok"] and arm == "stashed_t":  # broken stash contract: treatment failure, as in D
                got = [{**r, "correct": 0, "substring": 0} for r in got]
            rows += got
            u = usage.setdefault(arm, {})
            for k, v in {**ans["usage"], "retry_tokens": ans.get("retry_tokens", 0)}.items():
                u[k] = u.get(k, 0) + v
            if ans.get("refusal"):
                refusals.setdefault(arm, []).append(s["id"])
            for k, v in ans["kinds"].items():
                kinds.setdefault(arm, {})[k] = kinds.setdefault(arm, {}).get(k, 0) + v
    table = {arm: {m: lh.metric([r for r in rows if r["arm"] == arm], m) for m in ("A", "E", "U", "UA")}
             for arm in ARMS}
    acc = {arm: v["A"][0] / v["A"][1] if v["A"][1] else None for arm, v in table.items()}

    def parse_rate(arm):
        sel = [r for r in rows if r["arm"] == arm]
        return 1 - sum(r["failure"] for r in sel) / len(sel) if sel else 0.0

    toolcheck = s6dir("toolcheck", "result.json")
    gates = {"V1": (acc["full_t"] or 0) >= 0.60, "V2": bool(every) and len(dropped) <= 0.05 * len(every),
             "V4": toolcheck.exists() and lh.rj(toolcheck)["ok"], "V5": all(parse_rate(a) >= 0.95 for a in ARMS)}
    contrasts = {"A": lh.bootstrap(rows, "stashed_t", "full_t", "A"), "E": lh.bootstrap(rows, "stashed_t", "full_t", "E"),
                 "A_by_condition": {c: lh.bootstrap(rows, "stashed_t", "full_t", "A", condition=c)
                                    for c in ("ans_early", "ans_late")},
                 "A_substring_rule": lh.bootstrap(rows, "stashed_t", "full_t", "A", key="substring")}
    root, s6root = lh.ROOT, s6dir()
    lh.ROOT = s6root  # recall_behaviour reads <ROOT>/recall-log; S6's logs live under s6/
    try:
        recall = {arm: lh.recall_behaviour(arm, kept, loc, comps.get) for arm in ARMS}
    finally:
        lh.ROOT = root
    calls_done = lh.jsonl(s6dir("calls-done.jsonl"))
    done = [d.get("outcome", "untracked") for d in calls_done]  # calls 1–3 predate outcome and kinds
    every_call: dict[str, int] = {}  # the tool audit: every S6 call, retries, toolcheck and drops included
    for d in calls_done:
        for k, v in (d.get("kinds") or {}).items():
            every_call[k] = every_call.get(k, 0) + v
    out ={"complete": not pending, "valid": not pending and all(gates.values()), "model": MODEL, "effort": EFFORT,
           "cli": CODEX_VERSION, "table": table, "gates": gates, "contrast_stashed_t_minus_full_t": contrasts,
           "recall_behaviour": recall, "usage_cohort": usage, "refusals": refusals, "item_kinds_cohort": kinds,
           "item_kinds_every_call": every_call,
           "response_failures": {a: {c: sum(r["failure"] for r in rows if r["arm"] == a and r["condition"] == c)
                                     for c in lh.CONDITIONS} for a in ARMS},
           "calls": {"started": len(lh.jsonl(s6dir("calls.jsonl"))), "cap": S6_CAP,
                     "outcomes": {o: done.count(o) for o in sorted(set(done))}},
           "subset": sorted(only) if only else None, "dropped": dropped, "items": rows}
    # A subset (the pilot's 2 sessions, or a check) never overwrites the whole set's results
    lh.wj(s6dir(f"results-{which}{'-subset' if only else ''}.json"), out)
    print(json.dumps({k: out[k] for k in ("complete", "valid", "table", "gates", "dropped")}, indent=1))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=("toolcheck", "run", "score"))
    ap.add_argument("--set", dest="which", choices=("pilot", "D"), default="pilot")
    ap.add_argument("--arm", choices=ARMS)
    ap.add_argument("--only", action="append", help="a session id; repeat for more (the pilot uses two)")
    a = ap.parse_args(argv)
    if a.which == "pilot":  # the S6 pilot is these 2 sessions, not the whole pilot set
        if not set(a.only or PILOT) <= set(PILOT):
            raise SystemExit(f"the S6 pilot is {list(PILOT)} only")
        a.only = a.only or list(PILOT)
    if a.phase == "run" and not APPROVED:
        raise SystemExit("Amendment 5 is not approved yet: no pilot or D answer runs before the owner's OK")
    if a.phase == "run" and a.which == "D" and pilot_failures():
        raise SystemExit(f"the S6 pilot gate has not passed: {pilot_failures()}")
    with lh.driver_lock():  # one driver at a time, D's or S6's
        if a.phase == "toolcheck":
            phase_toolcheck()
            return
        bench = lh.load_benchmark(lh.fetch())
        if a.phase == "run":
            if not a.arm:
                raise SystemExit("run needs --arm")
            phase_run(bench, a.which, a.arm, a.only)
        else:
            phase_score(bench, a.which, a.only)


if __name__ == "__main__":
    main()
