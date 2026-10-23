"""Request category for intake: a frozen local classifier over the 13 request-taxonomy categories.

Intake judge v1 (lcc-judge ``research/goal-engine-2026-10-04/intake-judge-v1/``): hashed word
1-2-grams + char 2-5-grams, multinomial logistic regression, trained on Opus labels of the
owner's agent prompts. Plain Python, no network, about 0.3 ms per prompt.

Measured on an owner-labelled held-out set: right on 0.51 of prompts (keyword rules 0.22, Opus
0.86). So the category is advisory: :func:`classify` returns it only at probability >=
:data:`THRESHOLD`, chosen on dev as the lowest cut with >= 0.8 accuracy (34% of dev prompts,
0.83 accurate). It never changes readiness and never rewrites the user's text.

The weights are checked against :data:`MODEL_SHA256`; a missing or altered file disables the
category (``classify`` returns ``None``) instead of failing intake.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import re
import struct
import unicodedata
import zlib
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

LOGGER = logging.getLogger("lcc.intake.category")

MODEL_RESOURCE = "intake_category_v1.json"
MODEL_SHA256 = "8fc1c9b3b6d90e836c8ff6bcdf0b1e7c9d94cd6d7f5bbef0cec874fc8fee7cbf"
NOTES_RESOURCE = "intake_categories.json"
THRESHOLD = 0.45
#: The model was trained on prompts of at most 1,000 characters (longer ones were pasted context),
#: so only the head is classified; this also keeps the cost flat on long inputs.
MAX_CHARS = 1000
BUCKETS = 1 << 15
_WORD = re.compile(r"\w+")


@dataclass(frozen=True)
class Category:
    id: str
    probability: float
    #: What the agent needs in context for this kind of request (request-taxonomy v2).
    context_needed: str


def features(text: str, kinds: str) -> dict[int, float]:
    """Frozen with the model: hashed char 2-5-grams (+ word 1-2-grams), binary, L2-normalised."""
    t = unicodedata.normalize("NFKC", text or "").lower()
    words = _WORD.findall(t)
    grams: set[str] = set()
    for w in words:
        p = f" {w} "
        for n in range(2, 6):
            grams.update("c" + p[i : i + n] for i in range(len(p) - n + 1))
    if kinds == "char+word":
        grams.update("w" + w for w in words)
        grams.update("b" + a + " " + b for a, b in zip(words, words[1:], strict=False))
    if not grams:
        grams = {"<empty>"}
    # Sorted so float sums run in one order whatever PYTHONHASHSEED is: bit-stable output.
    buckets = sorted({zlib.crc32(g.encode()) % BUCKETS for g in grams})
    v = 1 / math.sqrt(len(buckets))
    return dict.fromkeys(buckets, v)


class _Model:
    def __init__(self, data: dict, notes: dict) -> None:
        self.labels: list[str] = data["labels"]
        self.kinds: str = data["kinds"]
        self.bias: list[float] = data["bias"]
        k = len(self.labels)
        self.w = struct.unpack(f"<{BUCKETS * k}e", base64.b64decode(data["weights_f16"]))
        self.notes = notes

    def proba(self, text: str) -> list[float]:
        k = len(self.labels)
        z = list(self.bias)
        w = self.w
        for idx, v in features(text[:MAX_CHARS], self.kinds).items():
            base = idx * k
            z = [a + b * v for a, b in zip(z, w[base : base + k], strict=True)]
        m = max(z)
        e = [math.exp(x - m) for x in z]
        s = sum(e)
        return [x / s for x in e]


@lru_cache(maxsize=1)
def _load() -> _Model | None:
    pkg = resources.files("lcc.intake")
    try:
        raw = pkg.joinpath(MODEL_RESOURCE).read_bytes()
        if hashlib.sha256(raw).hexdigest() != MODEL_SHA256:
            raise ValueError("sha256 mismatch")
        notes = json.loads(pkg.joinpath(NOTES_RESOURCE).read_bytes())["categories"]
        return _Model(json.loads(raw), notes)
    except (OSError, ValueError, KeyError, TypeError, struct.error) as exc:
        LOGGER.warning("intake category model unavailable: %s", exc)
        return None


def classify(text: str, threshold: float = THRESHOLD) -> Category | None:
    """Most likely category when its probability reaches ``threshold``; else ``None``.

    ``UNKNOWN`` means "cannot tell from the text", so it is reported as no category.
    """
    model = _load()
    if model is None or not (text or "").strip():
        return None
    p = model.proba(text)
    i = max(range(len(p)), key=p.__getitem__)
    label = model.labels[i]
    if p[i] < threshold or label == "UNKNOWN":
        return None
    return Category(label, round(p[i], 4), model.notes.get(label, {}).get("context_needed", ""))
