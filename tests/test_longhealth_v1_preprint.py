"""PREPRINT.md (benchmarks/research/longhealth-v1) quotes only numbers the study's files hold.

The result tables are checked cell by cell against results.json. Every other number in the prose must be derivable
from results.json or the location receipt, or appear in the study's own reports (RESULTS, PROTOCOL, PILOT).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "benchmarks" / "research" / "longhealth-v1"
DOC = (HERE / "PREPRINT.md").read_text(encoding="utf-8")
RES = json.loads((HERE / "results.json").read_text(encoding="utf-8"))
REC = json.loads((HERE / "location-receipt-D.json").read_text(encoding="utf-8"))
ARMS = ("none", "full_t", "stashed_t", "stashed_0", "summary_s", "summary_clin", "stashed_v")
MINUS = "−"
# A number token: optional sign, thousands commas, decimals, an optional "/n". Not part of a word, id or hash.
NUM = re.compile(r"(?<![\w.,/-])[+−-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:/\d+)?(?![\w/])")


def nums(text: str) -> list[str]:
    """Number tokens of `text`, an ASCII minus sign read as the Unicode one."""
    return [MINUS + t[1:] if t.startswith("-") else t for t in NUM.findall(text)]


def frac(kn: list[int]) -> str:
    k, n = kn
    return f"{k}/{n} = {k / n:.3f}" if n else "n/a"


def pp(x: float, sign: bool = True) -> set[str]:
    """Percentage points as RESULTS.md writes them: one decimal, Unicode minus, zero unsigned.

    results.json keeps 4 decimals, so a value such as -0.0045 sits on a half and RESULTS.md may show either -0.4 or
    -0.5 (it rounded the unrounded value). Both roundings are accepted, nothing else.
    """
    d = Decimal(str(x)) * 100
    out = set()
    for v in (float(d), float(d.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))):
        s = f"{v:{'+' if sign else ''}.1f}".replace("-", MINUS)
        out.add("0.0" if s.lstrip("+" + MINUS) == "0.0" else s)
    return out


def same(text: str, *values: float) -> bool:
    """The numbers in `text` are `values` in points, in order (a positive value may drop its plus sign)."""
    got = nums(text)
    return len(got) == len(values) and all(
        g in pp(v) | pp(v, sign=False) for g, v in zip(got, values, strict=True)
    )


def table(caption: str) -> dict[str, list[str]]:
    """Body rows of the pipe table under `Table: <caption>`, keyed by the first cell without backticks."""
    lines = DOC.splitlines()
    i = next(n for n, line in enumerate(lines) if line.startswith(f"Table: {caption}"))
    while not lines[i].startswith("|"):
        i += 1
    rows = []
    while i < len(lines) and lines[i].startswith("|"):
        rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
        i += 1
    return {r[0].strip("`"): r[1:] for r in rows[2:]}  # header and separator dropped


def by_condition() -> dict[tuple[str, str], list[int]]:
    correct, n = Counter(), Counter()
    for it in RES["items"]:
        correct[it["arm"], it["condition"]] += it["correct"]
        n[it["arm"], it["condition"]] += 1
    return {k: [correct[k], n[k]] for k in n}


def test_accuracy_table():
    rows = table("Accuracy by arm")
    assert set(rows) == set(ARMS)
    for arm, cells in rows.items():
        t = RES["table"][arm]
        assert cells == [
            frac(t["A"]),
            frac(t["E"]),
            *(f"{k}/{n}" if n else "n/a" for k, n in (t["U"], t["UA"])),
        ], arm


def test_condition_table():
    got = by_condition()
    rows = table("Accuracy (A) by condition")
    assert set(rows) == set(ARMS) - {"none"}
    for arm, cells in rows.items():
        early, late = got[arm, "ans_early"], got[arm, "ans_late"]
        assert [early[0] + late[0], early[1] + late[1]] == RES["table"][arm]["A"], arm
        assert cells == [frac(early), frac(late)], arm


def test_primary_contrasts_and_verdicts():
    rows = table("Primary contrasts")
    tests, verdict = RES["tests"], RES["verdict"]
    for label, key in {
        "H1": "H1",
        "H2, generic": "H2_s",
        "H2, clinical": "H2_clin",
        "H3, UA": "H3_UA",
        "H3, A": "H3_A",
    }.items():
        t = tests[key]
        assert same(rows[label][2], t["diff"]) and same(rows[label][3], t["lo"], t["hi"]), label
    lo = {k: tests[k]["lo"] for k in tests}
    assert verdict == {"H1": lo["H1"] > -0.05, "H2": lo["H2_s"] > 0 and lo["H2_clin"] > 0}
    assert rows["H1"][-1] == ("**PASS**" if verdict["H1"] else "**FAIL**")
    assert rows["H2"][-1] == ("**PASS**" if verdict["H2"] else "**FAIL**")
    assert rows["H2, generic"][-1] == ("met" if lo["H2_s"] > 0 else "not met")
    assert rows["H2, clinical"][-1] == ("met" if lo["H2_clin"] > 0 else "not met")


def test_secondary_table():
    sec = RES["secondary"]
    s2, s3, s4 = sec["S2_by_condition"], sec["S3_full_vs_summaries"], sec["S4_substring_rule"]
    assert s3["summary_s_U"] == s3["summary_clin_U"]  # one row covers both
    rows = [sec["S1_tool_effect_stash_dependent"]]
    rows += [s2[c][k] for c in ("ans_early", "ans_late") for k in ("H1", "H2_s", "H2_clin", "H3_A")]
    rows += [(s3[f"{s}_A"], s3[f"{s}_E"]) for s in ("summary_s", "summary_clin")]
    rows += [s3["summary_s_U"]] + [s4[k] for k in ("H1", "H2_s", "H2_clin", "H3_A")]
    cells = [c[0] for c in table("Secondary contrasts").values()]
    assert len(cells) == len(rows)
    for cell, row in zip(cells, rows, strict=True):
        ts = row if isinstance(row, tuple) else (row,)
        assert same(cell, *(v for t in ts for v in (t["diff"], t["lo"], t["hi"]))), cell


def test_gates_table():
    rows = table("Validity gates")
    assert all(RES["gates"].values()) and len(rows) == len(RES["gates"])
    assert all(cells[-1].startswith("pass") for cells in rows.values())
    full_a, none_a = RES["table"]["full_t"]["A"], RES["table"]["none"]["A"]
    assert frac(full_a) in rows["V1"][-1]
    assert f"{frac(none_a)} against {full_a[0] / full_a[1] - 0.10:.3f}" in rows["V6"][-1]
    assert f"{len(RES['dropped'])} of {len(REC['sessions'])}" in rows["V2"][-1]


def test_recall_table():
    r = RES["secondary"]["S1_recall_behaviour"]["stashed_t"]
    assert list(r["R6_errors"]) == ["cap"]
    want = [
        f"{r['R1_needed_recall']:.3f}",
        f"{r['R2_precision']:.3f}",
        f"{r['R3_calls_per_session']:.2f} / {r['R3_ok_calls_per_session']:.2f}",
        f"{r['R3_share_zero']:.2f} / {r['R3_share_cap']:.2f}",
        f"{r['R4_recalled_over_stashed']:.3f}",
        f"{r['R5_restored_context_median']:.3f}",
        f"{r['R6_errors']['cap']}, all of type `cap`",
    ]
    assert [cells[0] for cells in table("Recall behaviour").values()] == want


def test_verifier_table_against_results():
    rows = table("The verifier loop")
    final = by_condition()
    s5 = RES["secondary"]["S5_first_pass_catches"]
    conds = ("ans_early", "ans_late", "unans")
    assert rows["First-pass catches"] == [str(sum(s5[c]["catches"].values())) for c in conds]
    assert [c.split(" to ")[1] for c in rows["Correct lines, first pass to final"]] == [
        str(final["stashed_v", c][0]) for c in conds
    ]


def test_headline_claims_in_context():
    """The numbers in the abstract's and the results' key sentences are the right ones, not just numbers that exist."""
    tests, sec = RES["tests"], RES["secondary"]
    s1, s3 = sec["S1_tool_effect_stash_dependent"], sec["S3_full_vs_summaries"]

    def trio(t: dict) -> tuple[float, float, float]:
        return t["diff"], t["lo"], t["hi"]

    def check(pattern: str, *values: float) -> None:
        hits = re.findall(pattern.replace(" ", r"\s+"), DOC)
        assert hits, pattern
        for hit in hits:
            assert same(" ".join(hit) if isinstance(hit, tuple) else hit, *values), (pattern, hit)

    a = {arm: RES["table"][arm]["A"] for arm in ("stashed_t", "full_t")}
    short = (
        "With recall over its stash, the stashed context answered as well as the full context: "
        f"{a['stashed_t'][0] / a['stashed_t'][1]:.3f} against {a['full_t'][0] / a['full_t'][1]:.3f}, "
        "CI well inside the 5-point margin."
    )  # the H1 wording gateClaim passed, in the abstract and in the results
    assert len(re.findall(re.escape(short).replace(r"\ ", r"\s+"), DOC)) == 2
    check(r"generic summary by (\S+) points \(95% CI (\S+) to (\S+)\)", *trio(tests["H2_s"]))
    check(r"clinical summary by (\S+) points \(95% CI (\S+) to (\S+)\)", *trio(tests["H2_clin"]))
    check(r"scored (\S+) points higher on exact values", tests["H2_s"]["diff"])
    check(r"difference was (\S+) points with a CI from (\S+) to (\S+),", *trio(tests["H2_clin"]))
    check(r"led it by (\S+) points", tests["H2_clin"]["diff"])
    check(r"cost (\S+) points of (?:accuracy|A)", -tests["H3_A"]["diff"])
    check(r"stash-dependent questions at (\S+) points \((\S+) to (\S+)\)", *trio(s1))
    check(
        r"`full_t − summary_clin` at (\S+) points on A \((\S+) to (\S+)\) and (\S+) on E \((\S+) to (\S+)\)",
        *trio(s3["summary_clin_A"]),
        *trio(s3["summary_clin_E"]),
    )
    check(r"trailed the full context by (\S+) points", s3["summary_clin_E"]["diff"])
    stashed_0_early = by_condition()["stashed_0", "ans_early"]
    assert f"fell to {stashed_0_early[0]}/{stashed_0_early[1]}" in DOC


def test_result_prose_in_context():
    """Each result number in the prose is tied to its own field, so a number moved to the wrong metric fails."""
    res = (HERE / "RESULTS.md").read_text(encoding="utf-8")
    sizes, sec = RES["sizes"], RES["secondary"]
    recall = sec["S1_recall_behaviour"]["stashed_t"]
    cond = by_condition()
    kept = len({(i["patient"], i["condition"]) for i in RES["items"] if i["arm"] == "stashed_t"})
    built = len(REC["sessions"])
    ratio = f"{sizes['C_prime_tokens'] / sizes['C_tokens']:.3f}"
    restored = f"{recall['R5_restored_context_median']:.3f}"
    cohort = sizes["cumulative_usage_cohort_tokens"]

    def found(pattern: str, text: str = DOC) -> list[tuple[str, ...]]:
        hits = re.findall(pattern.replace(" ", r"\s+"), text)
        assert hits, pattern
        return [h if isinstance(h, tuple) else (h,) for h in hits]

    def exact(pattern: str, *want: object) -> None:
        for hit in found(pattern):
            assert list(hit) == [str(w) for w in want], (pattern, hit)

    exact(
        r"(\d+) target patients in three conditions, (\d+) sessions, (\d+) of them scored",
        len(RES["tests"]["H1"]["per_patient"]),
        built,
        kept,
    )
    exact(r"built and compacted all (\d+) D sessions", built)
    stashed = sum(n for s in REC["sessions"].values() for n in s["stash_reasons"].values())
    exact(r"lcc stashed (\S+) record reads", f"{stashed:,}")
    exact(
        r"and all (\d+) sessions passed both stash checks",
        sum(s["ok"] for s in REC["sessions"].values()),
    )
    ((calls, sub, api),) = found(
        r"(\d+) calls of the 650 cap\. Calls 1–(\d+) ran on the subscription, and calls from (\d+) on",
        res,
    )
    exact(r"counted (\d+) CLI calls against the 650-call cap", calls)
    exact(r"Calls 1–(\d+) ran on the subscription and calls from (\d+) on", sub, api)
    exact(r"Line (\d+) logged the start of a call", int(sub) + 1)
    exact(
        r"When the target sat in view, `stashed_0` reached (\d+/\d+)",
        "/".join(map(str, cond["stashed_0", "ans_late"])),
    )
    early, late = (sec["S2_by_condition"][c]["H2_s"]["diff"] for c in ("ans_early", "ans_late"))
    hits = found(r"with the target stashed \((\S+)\) than with the target in view \((\S+)\)")
    assert all(same(" ".join(h), early, late) for h in hits), hits
    exact(r"The (\d+) sessions without a recall", round(recall["R3_share_zero"] * kept))
    s5 = sec["S5_first_pass_catches"]
    exact(
        r"\"quote not found\" and \"number not in quote\": (\d+) and (\d+) in `ans_early`, (\d+) and (\d+) in `ans_late`",
        *(
            s5[c]["catches"][k]
            for c in ("ans_early", "ans_late")
            for k in ("quote not found", "number not in quote")
        ),
    )
    forced = found(r"(\d+) of its (\d+) forced lines had been correct", res)[0]
    exact(r"(\d+) of its (\d+) forced lines had been correct", *forced)
    exact(r"(\d+) of the (\d+) lines the loop forced to F had been correct", *forced)
    exact(
        r"full contexts `C` held (\S+) tokens and the stashed contexts `C'` held (\S+), which is (\S+) of",
        f"{sizes['C_tokens']:,}",
        f"{sizes['C_prime_tokens']:,}",
        ratio,
    )
    summ = sizes["summary_context_tokens"]
    exact(
        r"summary contexts held (\S+) tokens \(`summary_s`\) and (\S+) \(`summary_clin`\)",
        f"{summ['summary_s']:,}",
        f"{summ['summary_clin']:,}",
    )
    exact(r"restored context had a median ratio to `C` of (\S+)\.", restored)
    exact(
        r"held (\S+) of the full tokens before recall and a median (\S+) after it", ratio, restored
    )
    split = sizes["split_replies"]
    exact(
        r"infrastructure failures: (\d+) in `summary_clin` and (\d+) in `summary_s`",
        split["summary_clin"],
        split["summary_s"],
    )
    exact(
        r"recalled the answer text for (\S+) of stash-dependent questions",
        f"{recall['R1_needed_recall']:.3f}",
    )
    exact(
        r"without the tool it got (\d+) of those (\d+) questions right",
        *cond["stashed_0", "ans_early"],
    )
    assert recall["R1_n"] == cond["stashed_0", "ans_early"][1]
    exact(
        r"its arm used (\S+) times the cumulative tokens of `full_t`, against (\S+) for `stashed_t`",
        *(f"{cohort[a] / cohort['full_t']:.2f}" for a in ("summary_clin", "stashed_t")),
    )
    none_a = RES["table"]["none"]["A"]
    exact(r"`none` scored (\S+) with no records", f"{none_a[0] / none_a[1]:.3f}")
    exact(r"aggregates and (\S+) per-item 0/1 scores", f"{len(RES['items']):,}")
    rescore = found(
        r"- H1 (\S+) \((\S+) to (\S+)\);\s*- H2 vs `summary_s` (\S+) \((\S+) to (\S+)\);"
        r"\s*- H2 vs `summary_clin` (\S+) \((\S+) to (\S+)\)",
        res,
    )[0]
    exact(
        r"H1 (\S+) \((\S+) to (\S+)\); H2 against `summary_s` (\S+) \((\S+) to (\S+)\); "
        r"H2 against `summary_clin` (\S+) \((\S+) to (\S+)\)",
        *rescore,
    )


def test_token_table():
    use = RES["sizes"]["cumulative_usage_cohort_tokens"]
    rows = table("Cumulative token use")
    assert set(rows) == set(use)
    for arm, (tokens, ratio) in rows.items():
        assert tokens == f"{use[arm]:,}", arm
        assert ratio == ("n/a" if arm == "none" else f"{use[arm] / use['full_t']:.2f}"), arm


def test_per_patient_table():
    rows = table("Per-patient differences")
    tests = RES["tests"]
    assert list(rows) == sorted(tests["H1"]["per_patient"])
    for patient, cells in rows.items():
        assert same(
            " ".join(cells),
            *(tests[k]["per_patient"][patient] for k in ("H1", "H2_s", "H2_clin", "H3_A")),
        ), patient


def _tokens(text: str) -> set[str]:
    return set(nums(text))


def _derived() -> set[str]:
    """Every number results.json and the location receipt can print, in the formats the paper uses."""
    out: set[str] = set()

    def add(v) -> None:
        if isinstance(v, bool):
            return
        if isinstance(v, int):
            out.update({str(v), f"{v:,}"})
        elif isinstance(v, float):
            out.update(
                {f"{v:.3f}", f"{v:.2f}", *pp(v), *pp(v, sign=False), *pp(abs(v), sign=False)}
            )

    def walk(node) -> None:
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            if len(node) == 2 and all(type(x) is int for x in node) and node[1]:
                out.update({f"{node[0]}/{node[1]}", f"{node[0] / node[1]:.3f}"})
            for v in node:
                walk(v)
        else:
            add(node)

    walk({k: v for k, v in RES.items() if k != "items"})
    walk(list(by_condition().values()))
    sizes, recall = RES["sizes"], RES["secondary"]["S1_recall_behaviour"]["stashed_t"]
    kept = len({(i["patient"], i["condition"]) for i in RES["items"] if i["arm"] == "stashed_t"})
    built = len(REC["sessions"])
    stashed = sum(n for s in REC["sessions"].values() for n in s["stash_reasons"].values())
    for v in (
        len(RES["items"]),
        kept,
        built,
        sum(s["ok"] for s in REC["sessions"].values()),
        stashed,
        round(recall["R3_share_zero"] * kept),
        round(recall["R3_share_cap"] * kept),
        len(RES["tests"]["H1"]["per_patient"]),
    ):
        add(v)
    out.update(
        {
            f"{sizes['C_prime_tokens'] / sizes['C_tokens']:.3f}",
            f"{len(RES['dropped']) / built * 100:.1f}",
        }
    )
    return out


def _prose_numbers() -> set[str]:
    """Number tokens in the paper outside code, comments, dates and the reference list."""
    text = re.sub(r"```.*?```|`[^`]*`|<!--.*?-->", " ", DOC, flags=re.S)
    text = re.sub(r"\n# References\n.*?\n# Appendix", "\n", text, flags=re.S)
    return _tokens(re.sub(r"\d{4}-\d{2}-\d{2}", " ", text))


def test_every_number_in_the_prose_has_a_source():
    """Backstop: no number may lack any source. Membership only; the tests above tie results to their fields.
    Method constants copied from PROTOCOL.md (caps, seeds, limits) are checked only here."""
    found = _prose_numbers()
    assert {
        "0.889",
        "0.887",
        "+10.8",
        f"{MINUS}1.2",
    } <= found  # the sweep sees the headline numbers
    reports = set().union(
        *(
            _tokens((HERE / f).read_text(encoding="utf-8"))
            for f in ("RESULTS.md", "PROTOCOL.md", "PILOT.md")
        )
    )
    assert sorted(found - _derived() - reports) == []
