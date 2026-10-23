"""Opt-in log of genuine LCC requests (goal strings only), for the goal-family corpus.

OFF unless ``LCC_REQUEST_LOG=1``. Writes append-only JSONL to ``LCC_REQUEST_LOG_DIR``
(default ``./.lcc/request-log``, gitignored). Each entry holds only the redacted goal,
language (EN/PT short-goal heuristic), a salted session hash, the UTC date, the entry
point (``tool``, e.g. "mcp:compact" or "cli:compact"), the caller's field (or "none"),
the LCC version and the redaction ruleset hash. Tool-call compaction entries also carry
``provider`` (the provider that ran, e.g. "specialist-v3") and ``degradation_reason``
(or "none"): fixed labels from the report, never content. The Claude Code plugin's idle
stash adds ``trigger`` ("idle"), ``gap_bucket`` (e.g. "1h-2h") and ``removed_tokens``. No MCP
tool or CLI flag supplies a ``field`` today, so it stays "none" until a caller passes one to
``log_request``.
Context/dossier text is never passed in. A failure warns (RuntimeWarning on stderr)
and never changes LCC output.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import uuid
import warnings
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lcc import __version__

ENV_FLAG = "LCC_REQUEST_LOG"
ENV_DIR = "LCC_REQUEST_LOG_DIR"
ENV_SESSION = "LCC_SESSION_ID"
DEFAULT_DIR = Path(".lcc") / "request-log"
LOG_FILE = "requests.jsonl"
SALT_FILE = ".salt"
MAX_GOAL_CHARS = 1000  # ponytail: a goal longer than this is probably pasted context

# Order matters: wider spans (URLs, emails, IPv6) go before the hosts/paths they contain.
# ponytail: regex redaction cannot see unquoted names ("patient Maria Souza age 54");
# those pass through. Quote record values, or add an NER pass if the corpus needs it.
# Scan hostnames from their required suffix, avoiding repeated failed prefix scans.
_HOSTNAME_FROM_END = r"\b[A-Za-z]{2,}(?:\.[A-Za-z0-9-]+)+\b"
_REVERSED_RULES = frozenset({_HOSTNAME_FROM_END})
_RELATIVE_PATH = r"\b[\w.-]+(?:/[\w.-]+)+\.\w{1,6}\b"

RULES: tuple[tuple[str, str], ...] = (
    (
        r"\g<url_prefix><URL>",
        r"(?<![a-zA-Z0-9+.-])(?=[a-zA-Z0-9+.-]*://\S+)"
        r"(?P<url_prefix>[a-zA-Z0-9+.-]*?)\b[a-zA-Z][a-zA-Z0-9+.-]*://\S+",
    ),
    ("<EMAIL>", r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)*\b"),
    ("<TOKEN>", r"(?i)\bauthorization\s*:\s*(?:(?:basic|bearer|digest|token)\s+)?\S+"),
    ("<TOKEN>", r"(?i)\bbearer\s+\S+"),
    (
        r"\g<jwt_prefix><TOKEN>",
        r"(?<![\w-])(?=[\w-]+\.[\w-]+\.[\w-]+)"
        r"(?P<jwt_prefix>[\w-]*?)\beyJ[\w-]+\.[\w-]+\.[\w-]+",
    ),
    ("<TOKEN>", r"(?i)\b(?:set-)?cookie\s*:\s*\S+"),
    # NAME_API_KEY=..., client_secret: ...: the secret word glued to a longer identifier.
    (
        r"\g<token_prefix><TOKEN>",
        # Only exact count names with a whole integer value are exempt; numeric secrets stay hidden.
        r"(?i)(?<![\w-])(?P<token_prefix>-*)\b"
        r"(?!(?:max_tokens|tokens)\s*[:=]\s*[0-9]+(?=\s|$))"
        r"(?=[\w-]*(?:api[_-]?key|access[_-]?key|token|secret|password|passwd))"
        r"[\w-]+\s*[:=]\s*\S+",
    ),
    (
        "<TOKEN>",
        r"(?i)\b(?:api[_-]?key|access[_-]?key|token|secret|password|passwd|pwd|senha|chave)"
        r"\s*(?:[:=]|\bis\b|\bé\b|\bwas\b|\bera\b)\s*\S+",
    ),
    # bare "senha minhasenha2024": a value with a digit; prose ("token tomorrow") survives
    (
        "<TOKEN>",
        r"(?i)\b(?:api[_-]?key|access[_-]?key|token|secret|password|passwd|pwd|senha|chave)"
        r"\s+(?=\S*\d)\S+",
    ),
    ("<TOKEN>", r"\b(?:sk|pk|rk|ghp|gho|ghs|ghu|github_pat|glpat|xox[abprs]|hf|AKIA)[-_][\w-]{8,}"),
    ("<TOKEN>", r"\bAKIA[0-9A-Z]{12,}\b"),
    ("<TOKEN>", r"\b[\w-]{32,}\b"),
    # 20+ word chars holding a 12+ alnum run that mixes lower, upper and digits ("pfx_aBcD1EfGh2").
    # ponytail: also eats long CamelCase-with-digit names (OAuth2ClientCredentials); privacy wins.
    (
        "<TOKEN>",
        r"\b(?=\w{20,}\b)\w*?(?=[A-Za-z0-9]*[a-z])(?=[A-Za-z0-9]*[A-Z])(?=[A-Za-z0-9]*\d)"
        r"[A-Za-z0-9]{12,}\w*\b",
    ),
    (
        "<HOST>",
        r"(?i)(?<![\w:])(?:(?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4}"
        r"|(?:[0-9a-f]{1,4}:)*[0-9a-f]{0,4}::(?:[0-9a-f]{1,4}:)*[0-9a-f]{0,4})(?![\w:])",
    ),
    ("<PATH>", r"\\\\[\w.$-]+\\\S*"),
    ("<PATH>", r"\b[A-Za-z]:[\\/]\S+"),
    ("<PATH>", r"(?<![\w])(?:~|\.{1,2})?/[\w.~-]+(?:/[\w.~-]*)*"),
    ("<PATH>", _RELATIVE_PATH),
    ("<HOST>", r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    ("<HOST>", _HOSTNAME_FROM_END),
    ("<HOST>", r"\b[A-Za-z][\w-]*:\d{2,5}\b|\blocalhost\b"),
    ("<VALUE>", r"\"[^\"]*\"|`[^`]*`|“[^”]*”|‘[^’]*’|(?<!\w)'[^'\n]+'(?!\w)"),
    ("<NUMBER>", r"\b\d[\d.,/:-]{3,}\d\b"),
    ("<NUMBER>", r"(?<!\d)\d{9,}(?!\d)"),  # CPF/phone glued to letters, no word boundary
)
RULESET_SHA256 = hashlib.sha256(json.dumps((RULES, sorted(_REVERSED_RULES))).encode()).hexdigest()
_COMPILED = tuple((label, re.compile(pattern)) for label, pattern in RULES)
_EMAIL_DOMAIN = re.compile(r"[\w-]+(?:\.[\w-]+)*\b")
_WORD_BOUNDARY = re.compile(r"\b")


def _redact_emails(text: str) -> str:
    """Check each @ once, preserving adjacent addresses and their word boundaries."""
    parts: list[str] = []
    cursor = 0
    for match in re.finditer("@", text):
        at = match.start()
        start = at
        while start > cursor and (text[start - 1].isalnum() or text[start - 1] in "_.+-"):
            start -= 1
        boundary = _WORD_BOUNDARY.search(text, start, at)
        if boundary is None or boundary.start() == at:
            continue
        domain = _EMAIL_DOMAIN.match(text, at + 1)
        if domain is None:
            continue
        parts.extend((text[cursor : boundary.start()], "<EMAIL>"))
        cursor = domain.end()
    parts.append(text[cursor:])
    return "".join(parts)


_PATH_SEGMENT = re.compile(r"[\w.-]+")
_PATH_EXTENSION = re.compile(r"(?<=[\w.-])\.\w{1,6}\b")
_WORD = re.compile(r"\w")


def _redact_relative_paths(text: str) -> str:
    """Visit each slash-separated segment once, keeping the last valid extension."""
    parts: list[str] = []
    cursor = 0
    start = end = 0

    def append_path(start: int, end: int) -> None:
        nonlocal cursor
        word = _WORD.search(text, start, end)
        if word is None:
            return
        slash = text.find("/", word.start(), end)
        if slash == -1:
            return
        last_extension = None
        for extension in _PATH_EXTENSION.finditer(text, slash + 1, end):
            last_extension = extension
        if last_extension is not None:
            parts.extend((text[cursor : word.start()], "<PATH>"))
            cursor = last_extension.end()

    for segment in _PATH_SEGMENT.finditer(text):
        if text[end : segment.start()] != "/":
            append_path(start, end)
            start = segment.start()
        end = segment.end()
    append_path(start, end)
    parts.append(text[cursor:])
    return "".join(parts)


def redact(text: str) -> str:
    for label, pattern in _COMPILED:
        if label == "<EMAIL>":
            text = _redact_emails(text)
        elif pattern.pattern == _RELATIVE_PATH:
            text = _redact_relative_paths(text)
        elif pattern.pattern in _REVERSED_RULES:
            text = pattern.sub(label[::-1], text[::-1])[::-1]
        else:
            text = pattern.sub(label, text)
    return text


def _cut(text: str) -> str:
    """Bound redaction work without treating a partial word as a complete value."""
    text = text.strip()
    if len(text) <= MAX_GOAL_CHARS:
        return text
    head = text[:MAX_GOAL_CHARS]
    if not text[MAX_GOAL_CHARS].isspace() and not head[-1].isspace():
        words = head.rsplit(None, 1)
        return words[0] if len(words) > 1 else ""
    return head


# Short-goal EN/PT heuristic: the PLAN section 3 gate counts EN and PT only.
# ponytail: function-word lists; a short ES/FR goal in plain ASCII reads as "en".
_PT_HINTS = frozenset(
    [
        "qual",
        "quais",
        "o",
        "os",
        "as",
        "de",
        "do",
        "da",
        "dos",
        "das",
        "no",
        "na",
        "nos",
        "nas",
        "em",
        "um",
        "uma",
        "para",
        "com",
        "por",
        "pelo",
        "pela",
        "mais",
        "menos",
        "não",
        "nao",
        "é",
        "são",
        "sao",
        "que",
        "como",
        "último",
        "ultimo",
        "última",
        "ultima",
        "recente",
        "hoje",
        "ontem",
        "valor",
        "peso",
        "paciente",
        "consulta",
    ]
)
_EN_HINTS = frozenset(
    [
        "the",
        "an",
        "of",
        "and",
        "to",
        "for",
        "in",
        "on",
        "at",
        "is",
        "are",
        "was",
        "what",
        "which",
        "how",
        "why",
        "when",
        "where",
        "who",
        "latest",
        "last",
        "most",
        "recent",
        "with",
        "from",
        "my",
        "our",
        "this",
        "that",
        "show",
        "find",
        "get",
        "list",
    ]
)
_PT_SUFFIXES = ("ção", "ções", "mento", "mentos", "agem", "dade", "dades")
_PLACEHOLDER = re.compile(r"<[A-Z]+>")


def detect_language(text: str) -> str | None:
    """Return "pt", "en", another tag from the compactor's long-text detector, or None."""
    from lcc.relevance.compactor import _detect_language

    text = _PLACEHOLDER.sub(" ", text)
    tagged = _detect_language(text)
    if tagged:
        return tagged
    words = re.findall(r"[^\W\d_]{2,}", text.lower()) + re.findall(r"\b[oa]\b", text.lower())
    if not words:
        return None
    pt = sum(w in _PT_HINTS or w.endswith(_PT_SUFFIXES) or not w.isascii() for w in words)
    en = sum(w in _EN_HINTS for w in words)
    if pt > en:
        return "pt"
    if en > pt or text.isascii():
        return "en"
    return None


def session_hash(key: str, salt: bytes) -> str:
    return hmac.new(salt, key.encode(), hashlib.sha256).hexdigest()[:16]


def log_dir() -> Path:
    return Path(os.environ.get(ENV_DIR) or DEFAULT_DIR)


def enabled() -> bool:
    return os.environ.get(ENV_FLAG) == "1"


def _salt(directory: Path) -> bytes:
    path = directory / SALT_FILE
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_bytes()
    salt = secrets.token_hex(16).encode()
    with os.fdopen(fd, "wb") as handle:
        handle.write(salt)
    return salt


def _private_open(path: Path, flags: int) -> Any:
    """Open for writing as owner-only (0600): redacted goals are still someone's text."""
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | flags, 0o600), "w", encoding="utf-8")


def _append(directory: Path, entry: dict[str, Any]) -> None:
    with _private_open(directory / LOG_FILE, os.O_APPEND) as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_request(
    goal: Any,
    *,
    tool: str = "none",
    field: Any = None,
    language: Any = None,
    session_key: str | None = None,
    provider: str | None = None,
    degradation_reason: str | None = None,
    trigger: str | None = None,
    gap_bucket: str | None = None,
    removed_tokens: int | None = None,
) -> Path | None:
    """Append one redacted entry when enabled; return the log path or None. Never raises."""
    if not enabled() or not isinstance(goal, str) or not goal.strip():
        return None
    try:
        redacted = redact(_cut(goal))
        if not (isinstance(language, str) and re.fullmatch(r"[a-z]{2}", language)):
            language = detect_language(redacted)
        directory = log_dir()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        key = session_key or os.environ.get(ENV_SESSION) or str(os.getppid())
        entry = {
            "id": uuid.uuid4().hex[:12],
            "date": datetime.now(UTC).date().isoformat(),
            "goal": redacted,
            "language": language,
            "session": session_hash(key, _salt(directory)),
            "tool": tool,
            "field": (redact(_cut(field)) if isinstance(field, str) and field.strip() else "none"),
            "lcc_version": __version__,
            "redaction_ruleset_sha256": RULESET_SHA256,
        }
        if provider is not None:
            entry["provider"] = provider
            entry["degradation_reason"] = degradation_reason or "none"
        if trigger is not None:
            entry["trigger"] = trigger
            entry["gap_bucket"] = gap_bucket or "unknown"
            entry["removed_tokens"] = removed_tokens
        _append(directory, entry)
        return directory / LOG_FILE
    except Exception as exc:  # logging must never break compilation, but must be seen
        warnings.warn(f"lcc request log: entry not written: {exc}", RuntimeWarning, stacklevel=2)
        return None


def read_entries(directory: Path | None = None) -> list[dict[str, Any]]:
    path = (directory or log_dir()) / LOG_FILE
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def delete_entries(ids: set[str], directory: Path | None = None) -> int:
    """Owner deletion: rewrite the log without the given ids; return how many were removed."""
    directory = directory or log_dir()
    entries = read_entries(directory)
    kept = [e for e in entries if e.get("id") not in ids]
    if len(kept) != len(entries):
        tmp = directory / (LOG_FILE + ".tmp")
        with _private_open(tmp, os.O_TRUNC) as handle:
            handle.write("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in kept))
        tmp.replace(directory / LOG_FILE)
    return len(entries) - len(kept)


def summarize(directory: Path | None = None) -> dict[str, Any]:
    entries = read_entries(directory)
    return {
        "path": str((directory or log_dir()) / LOG_FILE),
        "enabled": enabled(),
        "total": len(entries),
        "by_language": dict(Counter(str(e.get("language") or "unknown") for e in entries)),
        "by_provider": dict(Counter(str(e["provider"]) for e in entries if "provider" in e)),
        "sessions": len({e.get("session") for e in entries}),
        "by_session": dict(Counter(str(e.get("session")) for e in entries)),
    }
