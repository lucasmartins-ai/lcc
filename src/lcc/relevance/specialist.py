"""Specialist v3: a frozen, CPU-only block ranker for local relevance compaction.

The model is a small ensemble (logistic regression + 350 depth-4 boosted trees, averaged)
over 50 cheap per-block features, minus a size penalty, plus a rule floor for the block that
best matches the objective and the two most recent error blocks. It ranks blocks; it does
not answer questions, so it never claims semantic judgment (``semantic_guarantee: none``).

Inference is plain Python (no numpy, no torch, no network). The weights ship as
``specialist_v3.json`` next to this module and are checked against :data:`MODEL_SHA256`
at load; any mismatch or parse error raises :class:`SpecialistModelError` and the
compactor falls back to the mechanical scorer.

Block metadata (message index, role, kind, tool name) is a **trusted field** supplied by
LCC (see :func:`render_transcript` and :class:`BlockSegment`), never parsed from block text:
a tool output can contain a line that looks like a render header.

See ``docs/SPECIALIST.md`` for the measured results and limits.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import logging
import math
import re
from array import array
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lcc.relevance.transcript import TranscriptMessage

__all__ = [
    "MODEL_SHA256",
    "SPECIALIST_PROVIDER",
    "BlockMeta",
    "BlockSegment",
    "SpecialistJudge",
    "SpecialistModelError",
    "featurize",
    "load_judge",
    "meta_for_blocks",
    "render_transcript",
]

LOGGER = logging.getLogger("lcc.specialist")

SPECIALIST_PROVIDER = "specialist-v3"
MODEL_RESOURCE = "specialist_v3.json"
MODEL_SHA256 = "219cd798d47f39d18249597892c92f0772d7946ed59610d5b86b8500fa1b51f7"

# Feature definitions are frozen with the model: changing any of them changes the scores.
HEADER_RE = re.compile(r"^\[m(\d{4,}) (user|assistant) ([a-z_]+)(?: ([^\]\n]*))?\]$", re.M)
TOKEN_RE = re.compile(r"\w+", re.U)
KEY_RE = re.compile(r"[\w./~@-]{6,}")
CAMEL_RE = re.compile(r"[a-z][A-Z]")
ERROR_RE = re.compile(
    r"Traceback \(most recent|\b(?:Error|Exception|FAILED|FATAL|panic):|\berror(?:\[| TS\d|:)|"
    r"exit code [1-9]|Exit code [1-9]|\bfailed\b|command not found|No such file",
    re.I,
)
GIT_RE = re.compile(
    r"^diff --git|^commit [0-9a-f]{7}|^@@ |"
    r"\bgit (?:status|diff|log|commit|push|add|checkout|rebase)\b",
    re.M,
)
CODE_RE = re.compile(r"[{};=()<>\[\]]")
TOOL_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("read", ("Read", "read_file", "view_image", "NotebookRead", "cat")),
    (
        "edit",
        (
            "Edit",
            "MultiEdit",
            "Write",
            "write_file",
            "patch",
            "apply_patch",
            "NotebookEdit",
            "str_replace",
        ),
    ),
    (
        "shell",
        (
            "Bash",
            "exec_command",
            "terminal",
            "execute_code",
            "write_stdin",
            "shell",
            "BashOutput",
        ),
    ),
    ("search", ("Grep", "Glob", "search_files", "ToolSearch", "tool_search", "LS", "list_files")),
    (
        "web",
        (
            "WebFetch",
            "WebSearch",
            "web_search",
            "web_fetch",
            "browser",
            "chrome",
            "playwright",
            "vision",
        ),
    ),
    ("agent", ("Agent", "Task", "delegate_task", "subagent")),
    ("plan", ("TodoWrite", "update_plan", "ExitPlanMode", "AskUserQuestion", "todo")),
    ("skill", ("skill_view", "Skill", "skill_manage")),
)
KINDS = ("user:text", "assistant:text", "assistant:tool_use", "user:tool_result")
GROUPS = tuple(g for g, _ in TOOL_GROUPS) + ("mcp", "other")
FEATURES: tuple[str, ...] = (
    "pos",
    "from_end_log",
    "tok_after_frac",
    "msg_from_end_log",
    "msg_pos",
    "log_chars",
    "n_lines_log",
    *(f"kind_{k}" for k in KINDS),
    "kind_unknown",
    *(f"tool_{g}" for g in GROUPS),
    "has_header",
    "is_error",
    "is_git",
    "code_frac",
    "bm25_goal",
    "bm25_goal_rank",
    "bm25_recent",
    "bm25_recent_rank",
    "keys_log",
    "goal_hits",
    "recent_hits",
    "later_ref",
    "later_ref_frac",
    "later_asst_ref",
    "latest_holder",
    "unique_keys",
    "superseded_path",
    "dup_later",
    "dup_earlier",
    "same_kind_after_log",
    "turns_after_log",
    "goal_chars_log",
    "goal_keys",
    "goal_question",
    "n_blocks_log",
    "goal_bm25_max_log",
    "lcc_overlap",
    "lcc_protected",
)
_COL = {name: j for j, name in enumerate(FEATURES)}
_BG, _ERR, _LC = _COL["bm25_goal"], _COL["is_error"], _COL["log_chars"]


class SpecialistModelError(RuntimeError):
    """The packaged model is missing, altered, or malformed."""


@dataclass(frozen=True)
class BlockMeta:
    """Trusted per-block metadata. ``starts_part`` marks the first block of a content part."""

    message_index: int = 0
    role: str | None = None
    kind: str | None = None  # text | tool_use | tool_result
    tool: str | None = None
    starts_part: bool = False


@dataclass(frozen=True)
class BlockSegment:
    """Character span of one rendered content part, with the fields it was rendered from."""

    character_start: int
    character_end: int
    message_index: int
    role: str
    kind: str
    tool: str | None = None


# --------------------------------------------------------------------------------------
# rendering + metadata
# --------------------------------------------------------------------------------------


def _header(message_index: int, role: str, kind: str, tool: str | None) -> str:
    return f"[m{message_index:04d} {role} {kind}" + (f" {tool}" if tool else "") + "]"


def render_transcript(
    messages: Sequence[TranscriptMessage],
) -> tuple[str, tuple[BlockSegment, ...]]:
    """Render parsed transcript messages to text plus one trusted segment per content part.

    The layout matches what the model was trained on: one ``[mNNNN role kind tool]`` header
    line per part, parts joined by a blank line. Part order inside a message is text, tool
    calls, tool results. A ``tool`` role is rendered as ``user`` (it carries tool results).
    """
    pieces: list[str] = []
    segments: list[BlockSegment] = []
    names = {call.id: call.tool for message in messages for call in message.tool_calls}
    offset = 0

    def add(m: int, role: str, kind: str, body: str, tool: str | None = None) -> None:
        nonlocal offset
        if pieces:
            offset += 2  # "\n\n" separator
        piece = f"{_header(m, role, kind, tool)}\n{body}"
        segments.append(BlockSegment(offset, offset + len(piece), m, role, kind, tool))
        pieces.append(piece)
        offset += len(piece)

    for message in messages:
        role = "user" if message.role == "tool" else message.role
        m = message.message_index
        if message.text:
            add(m, role, "text", message.text)
        for call in message.tool_calls:
            body = json.dumps(call.input, ensure_ascii=False, sort_keys=True)
            add(m, role, "tool_use", body, call.tool)
        for result in message.tool_results:
            add(m, role, "tool_result", result.text, names.get(result.id))
    return "\n\n".join(pieces), tuple(segments)


def meta_for_blocks(
    spans: Sequence[tuple[int, int]], segments: Sequence[BlockSegment] | None
) -> list[BlockMeta]:
    """Metadata per block ``(character_start, character_end)`` from trusted segments.

    A block takes the segment its first character falls in; the first block of a segment
    ``starts_part``. A block outside every segment continues the previous one. Without
    segments every block is ``BlockMeta()`` (unknown kind), which is out of the training
    distribution; the compactor warns about it.
    """
    if not segments:
        return [BlockMeta() for _ in spans]
    ordered = sorted(segments, key=lambda s: s.character_start)
    starts = [s.character_start for s in ordered]
    out: list[BlockMeta] = []
    current = BlockMeta()
    seen: set[int] = set()
    for start, _end in spans:
        k = bisect.bisect_right(starts, start) - 1
        if k >= 0 and start < ordered[k].character_end:
            seg = ordered[k]
            first = k not in seen
            seen.add(k)
            current = BlockMeta(seg.message_index, seg.role, seg.kind, seg.tool, first)
            out.append(current)
        else:
            out.append(
                BlockMeta(current.message_index, current.role, current.kind, current.tool, False)
            )
    return out


# --------------------------------------------------------------------------------------
# features (plain Python port of the research featurizer; parity-tested)
# --------------------------------------------------------------------------------------


def tool_group(tool: str | None) -> str | None:
    if not tool:
        return None
    if tool.startswith("mcp__"):
        for group, names in TOOL_GROUPS:
            if group == "web" and any(n.lower() in tool.lower() for n in names):
                return "web"
        return "mcp"
    for group, names in TOOL_GROUPS:
        if tool in names or any(n.lower() in tool.lower() for n in names if len(n) > 4):
            return group
    return "other"


def keys(text: str) -> set[str]:
    """Identifier-like strings (paths, dotted / snake / camel names, ids with digits)."""
    out: set[str] = set()
    for t in KEY_RE.findall(text):
        t = t.strip(".,-~")
        if len(t) < 6:
            continue
        if "/" in t:
            out.add(t)
            base = t.rsplit("/", 1)[-1]
            if len(base) >= 6:
                out.add(base)
        elif (
            "_" in t
            or "." in t
            or CAMEL_RE.search(t)
            or (any(c.isdigit() for c in t) and any(c.isalpha() for c in t))
        ):
            out.add(t)
    return out


def _bm25(
    q_terms: list[str],
    postings: dict[str, list[tuple[int, int]]],
    lens: list[int],
    avg: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[float]:
    n = len(lens)
    out = [0.0] * n
    for t in sorted(set(q_terms)):
        post = postings.get(t)
        if not post:
            continue
        idf = math.log(1 + (n - len(post) + 0.5) / (len(post) + 0.5))
        for i, f in post:
            out[i] += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * lens[i] / avg))
    return out


def _rank01(x: list[float]) -> list[float]:
    if len(x) < 2:
        return [0.0] * len(x)
    ordered = sorted(x)
    return [bisect.bisect_left(ordered, v) / (len(x) - 1) for v in x]


def _mechanical(goal: str, texts: Sequence[str]) -> list[tuple[float, bool]]:
    """LCC's own local pass, called exactly as at training time.

    ``fold=False`` keeps the training-time ASCII tokenization: the mechanical pass became
    accent-insensitive in 1.2, and the model's features must not drift with it.
    """
    from lcc.relevance.blocks import TextBlock
    from lcc.relevance.compactor import _score_mechanically

    res = _score_mechanically(
        [
            TextBlock(
                id=str(i),
                index=i,
                text=t,
                character_start=0,
                character_end=0,
                line_start=0,
                line_end=0,
            )
            for i, t in enumerate(texts)
        ],
        goal,
        fold=False,
    )
    return [(res[str(i)][0], res[str(i)][2] is not None) for i in range(len(texts))]


def _f32(values: list[float]) -> list[float]:
    """Round to float32, as the training feature matrix stored them."""
    return list(array("f", values))


def featurize(goal: str, texts: Sequence[str], meta: Sequence[BlockMeta]) -> list[list[float]]:
    """Objective + ordered block texts + trusted metadata -> one float32 row per block."""
    n = len(texts)
    if len(meta) != n:
        raise ValueError("featurize needs one BlockMeta per block")
    lcc = _mechanical(goal, texts)
    bodies = [HEADER_RE.sub("", t).strip() for t in texts]
    chars = [float(max(1, len(t))) for t in texts]
    ks = [keys(body) for body in bodies]
    goal_k = keys(goal)
    text_idx = [
        i for i, m in enumerate(meta) if m.kind == "text" and m.role in ("user", "assistant")
    ]
    recent_idx = text_idx[-3:]
    recent = "\n".join(bodies[i] for i in recent_idx)
    recent_k: set[str] = set().union(*(ks[i] for i in recent_idx)) if recent_idx else set()
    last: dict[str, int] = {}
    last_asst: dict[str, int] = {}
    last_rw: dict[str, int] = {}
    df_k: Counter[str] = Counter()
    for i, k in enumerate(ks):
        df_k.update(k)
        for x in k:
            last[x] = i
        if meta[i].role == "assistant" and meta[i].kind == "text":
            for x in k:
                last_asst[x] = i
        if meta[i].kind == "tool_use" and tool_group(meta[i].tool) in ("read", "edit"):
            for x in k:
                if "/" in x or "." in x:
                    last_rw[x] = i
    hashes = [
        hashlib.blake2b(b.encode(), digest_size=8).digest() if len(b) >= 40 else None
        for b in bodies
    ]
    first_h: dict[bytes, int] = {}
    last_h: dict[bytes, int] = {}
    for i, h in enumerate(hashes):
        if h is not None:
            first_h.setdefault(h, i)
            last_h[h] = i
    q_goal, q_recent = TOKEN_RE.findall(goal.lower()), TOKEN_RE.findall(recent.lower())
    qset = set(q_goal) | set(q_recent)
    postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
    lens: list[int] = []
    for i, body in enumerate(bodies):
        ts = TOKEN_RE.findall(body.lower())
        lens.append(len(ts))
        for t, f in Counter(t for t in ts if t in qset).items():
            postings[t].append((i, f))
    avg = (sum(lens) / n or 1) if n else 1
    bg = _bm25(q_goal, postings, lens, avg)
    br = _bm25(q_recent, postings, lens, avg)
    bg_rank, br_rank = _rank01(bg), _rank01(br)
    m_arr = [float(m.message_index) for m in meta]
    m_last = max(m_arr) if n else 0.0
    total_chars = sum(chars)
    tok_after = [0.0] * n
    running = 0.0
    for i in range(n - 1, -1, -1):
        tok_after[i] = running / total_chars
        running += chars[i]
    kind_count_after: Counter[tuple[str | None, str | None, str | None]] = Counter()
    same_after, turns_after = [0.0] * n, [0.0] * n
    for i in range(n - 1, -1, -1):
        kk = (meta[i].role, meta[i].kind, meta[i].tool)
        same_after[i] = kind_count_after[kk]
        turns_after[i] = kind_count_after[("user", "text", None)]
        if meta[i].starts_part or i == 0 or meta[i].message_index != meta[i - 1].message_index:
            kind_count_after[kk] += 1
    goal_chars_log = math.log1p(len(goal))
    goal_keys = math.log1p(len(goal_k))
    goal_question = float("?" in goal)
    n_blocks_log = math.log1p(n)
    goal_bm25_max_log = math.log1p(max(bg)) if n else 0.0
    rows: list[list[float]] = []
    for i in range(n):
        row = [0.0] * len(FEATURES)
        mt, k, body = meta[i], ks[i], bodies[i]
        row[_COL["pos"]] = i / max(1, n - 1)
        row[_COL["from_end_log"]] = math.log1p(n - 1 - i)
        row[_COL["tok_after_frac"]] = tok_after[i]
        row[_COL["msg_from_end_log"]] = math.log1p(m_last - m_arr[i])
        row[_COL["msg_pos"]] = m_arr[i] / max(1.0, m_last)
        row[_COL["log_chars"]] = math.log(chars[i])
        row[_COL["bm25_goal"]] = math.log1p(bg[i])
        row[_COL["bm25_goal_rank"]] = bg_rank[i]
        row[_COL["bm25_recent"]] = math.log1p(br[i])
        row[_COL["bm25_recent_rank"]] = br_rank[i]
        row[_COL["same_kind_after_log"]] = math.log1p(same_after[i])
        row[_COL["turns_after_log"]] = math.log1p(turns_after[i])
        row[_COL["goal_chars_log"]] = goal_chars_log
        row[_COL["goal_keys"]] = goal_keys
        row[_COL["goal_question"]] = goal_question
        row[_COL["n_blocks_log"]] = n_blocks_log
        row[_COL["goal_bm25_max_log"]] = goal_bm25_max_log
        row[_COL["lcc_overlap"]] = lcc[i][0]
        row[_COL["lcc_protected"]] = float(lcc[i][1])
        rk = f"{mt.role}:{mt.kind}"
        row[_COL[f"kind_{rk}"] if rk in KINDS else _COL["kind_unknown"]] = 1.0
        group = tool_group(mt.tool)
        if group:
            row[_COL[f"tool_{group}"]] = 1.0
        row[_COL["has_header"]] = float(mt.starts_part)
        row[_COL["n_lines_log"]] = math.log1p(body.count("\n"))
        row[_COL["is_error"]] = float(bool(ERROR_RE.search(body)))
        row[_COL["is_git"]] = float(bool(GIT_RE.search(body)))
        lines = body.splitlines() or [""]
        row[_COL["code_frac"]] = sum(bool(CODE_RE.search(x)) for x in lines) / len(lines)
        row[_COL["keys_log"]] = math.log1p(len(k))
        if k:
            later = sum(last[x] > i for x in k)
            row[_COL["goal_hits"]] = math.log1p(len(k & goal_k))
            row[_COL["recent_hits"]] = math.log1p(len(k & recent_k))
            row[_COL["later_ref"]] = math.log1p(later)
            row[_COL["later_ref_frac"]] = later / len(k)
            row[_COL["later_asst_ref"]] = math.log1p(sum(last_asst.get(x, -1) > i for x in k))
            row[_COL["latest_holder"]] = math.log1p(sum(last[x] == i and df_k[x] > 1 for x in k))
            row[_COL["unique_keys"]] = math.log1p(sum(df_k[x] == 1 for x in k))
            row[_COL["superseded_path"]] = float(
                any(last_rw.get(x, -1) > i for x in k if "/" in x or "." in x)
            )
        h = hashes[i]
        if h is not None:
            row[_COL["dup_later"]] = float(last_h[h] > i)
            row[_COL["dup_earlier"]] = float(first_h[h] < i)
        rows.append(_f32(row))
    return rows


# --------------------------------------------------------------------------------------
# model
# --------------------------------------------------------------------------------------

_Tree = tuple[tuple[int, ...], tuple[float, ...], tuple[float, ...], int]


class SpecialistJudge:
    """Frozen v3 ensemble. ``score(goal, texts, meta)`` -> one float per block, higher = keep."""

    def __init__(self, model: dict[str, Any]) -> None:
        if model.get("kind") != "v3":
            raise SpecialistModelError("specialist model kind must be 'v3'")
        members = model.get("members")
        if not isinstance(members, list) or not members:
            raise SpecialistModelError("specialist model has no members")
        self.alpha = float(model["alpha"])
        self.k_goal = int(model["k_goal"])
        self.k_err = int(model["k_err"])
        self.bonus = float(model["bonus"])
        self._lr: list[tuple[list[float], list[float], list[float], float]] = []
        self._gbdt: list[tuple[float, list[_Tree]]] = []
        for member in members:
            if tuple(member.get("features", ())) != FEATURES:
                raise SpecialistModelError("specialist model feature list does not match code")
            if member["kind"] == "lr":
                self._lr.append(
                    (
                        [float(v) for v in member["mu"]],
                        [float(v) for v in member["sd"]],
                        [float(v) for v in member["beta"]],
                        float(member["b0"]),
                    )
                )
            elif member["kind"] == "gbdt":
                trees = member["trees"][: member.get("n_trees", len(member["trees"]))]
                self._gbdt.append(
                    (
                        float(member["base"]),
                        [
                            (
                                tuple(int(f) for level in t["f"] for f in level),
                                tuple(float(x) for level in t["t"] for x in level),
                                tuple(float(v) for v in t["v"]),
                                len(t["f"]),
                            )
                            for t in trees
                        ],
                    )
                )
            else:
                raise SpecialistModelError(f"unknown member kind {member['kind']!r}")
        self.n_members = len(self._lr) + len(self._gbdt)

    def raw(self, rows: list[list[float]]) -> list[float]:
        n = len(rows)
        out = [0.0] * n
        for mu, sd, beta, b0 in self._lr:
            inv_sd_beta = tuple(b / s for b, s in zip(beta, sd, strict=True))
            for r, x in enumerate(rows):
                acc = b0
                for xj, mj, wj in zip(x, mu, inv_sd_beta, strict=False):
                    acc += (xj - mj) * wj
                out[r] += acc
        for base, trees in self._gbdt:
            scores = [base] * n
            for feats, thrs, leaves, depth in trees:
                if depth == 4:
                    f0, t0 = feats[0], thrs[0]
                    for r, x in enumerate(rows):
                        k = 1 + (x[f0] > t0)
                        k = 2 * k + 1 + (x[feats[k]] > thrs[k])
                        k = 2 * k + 1 + (x[feats[k]] > thrs[k])
                        k = 2 * k + 1 + (x[feats[k]] > thrs[k])
                        scores[r] += leaves[k - 15]
                else:
                    first_leaf = (1 << depth) - 1
                    for r, x in enumerate(rows):
                        k = 0  # heap order: children of k are 2k+1 (x <= t) and 2k+2 (x > t)
                        for _ in range(depth):
                            k = 2 * k + 1 + (x[feats[k]] > thrs[k])
                        scores[r] += leaves[k - first_leaf]
            for r, s in enumerate(scores):
                out[r] += s
        return [v / self.n_members for v in out]

    def _floor(self, rows: list[list[float]]) -> list[bool]:
        n = len(rows)
        mask = [False] * n
        if self.k_goal and n:
            # Highest BM25-vs-goal first; ties go to the later block.
            top = sorted(range(n), key=lambda i: (rows[i][_BG], i), reverse=True)[: self.k_goal]
            for i in top:
                if rows[i][_BG] > 0:
                    mask[i] = True
        if self.k_err:
            for i in [i for i in range(n) if rows[i][_ERR] > 0][-self.k_err :]:
                mask[i] = True
        return mask

    def score_rows(self, rows: list[list[float]]) -> list[float]:
        return self._scored(rows)[0]

    def _scored(self, rows: list[list[float]]) -> tuple[list[float], list[bool]]:
        raw = self.raw(rows)
        floor = self._floor(rows)
        scores = [
            raw[i] - self.alpha * rows[i][_LC] + (self.bonus if floor[i] else 0.0)
            for i in range(len(rows))
        ]
        return scores, floor

    def score(self, goal: str, texts: Sequence[str], meta: Sequence[BlockMeta]) -> list[float]:
        return self.score_and_floor(goal, texts, meta)[0]

    def score_and_floor(
        self, goal: str, texts: Sequence[str], meta: Sequence[BlockMeta]
    ) -> tuple[list[float], list[bool]]:
        """Scores plus the rule-floor mask (best goal match, newest error blocks).

        The compactor never drops a floor block, at any ``specialist_drop_fraction``: the
        +bonus alone only makes that likely, not certain.
        """
        if not texts:
            return [], []
        return self._scored(featurize(goal, texts, meta))


@lru_cache(maxsize=1)
def load_judge() -> SpecialistJudge:
    """Load the packaged model once per process; raise :class:`SpecialistModelError`."""
    try:
        data = resources.files("lcc.relevance").joinpath(MODEL_RESOURCE).read_bytes()
    except (FileNotFoundError, OSError) as exc:
        raise SpecialistModelError(f"specialist model not found: {exc}") from exc
    digest = hashlib.sha256(data).hexdigest()
    if digest != MODEL_SHA256:
        raise SpecialistModelError(
            f"specialist model sha256 mismatch: got {digest[:12]}, expected {MODEL_SHA256[:12]}"
        )
    try:
        return SpecialistJudge(json.loads(data))
    except SpecialistModelError:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise SpecialistModelError(f"specialist model is malformed: {exc}") from exc
