"""Request category for intake: a frozen local classifier over the 13 request-taxonomy categories.

Two frozen models from lcc-judge (``research/goal-engine-2026-10-04/intake-judge-v*/``), both hashed
word 1-2-grams + char 2-5-grams with multinomial logistic regression, plain Python, no network:

* **v3, the default.** It also reads the tail of the agent's previous turn when one is given,
  and it was trained on the owner's prompts plus public agent and coding-chat prompts. On other
  people's prompts it is right on 0.70 (v1 0.30). On the owner's own prompts it scored 0.46
  against v1's 0.52, and that test did not show it non-inferior. It is the default by a product
  decision taken after that result (lcc-judge ``intake-judge-v3/RESULTS_OWNER.md``), not by a
  passed test.
* **v1**, trained on the owner's prompts only. Set ``LCC_INTAKE_CATEGORY_MODEL=v1`` to pin it.

The category is advisory: :func:`classify` returns it only at the model's probability threshold, the
lowest dev cut with >= 0.8 accuracy. It never changes readiness and never rewrites the user's text.

The weights are checked against the model's pinned sha256; a missing or altered file disables the
category (``classify`` returns ``None``) instead of failing intake.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import os
import re
import struct
import unicodedata
import zlib
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

LOGGER = logging.getLogger("lcc.intake.category")

#: name -> (resource, sha256, display threshold)
MODELS = {
    "v3": (
        "intake_category_v3.json",
        "47f76322a4efe2896668c0fdb2ea8b35975b9354e3ca5c27b329bc0bec9b39ec",
        0.5,
    ),
    "v1": (
        "intake_category_v1.json",
        "8fc1c9b3b6d90e836c8ff6bcdf0b1e7c9d94cd6d7f5bbef0cec874fc8fee7cbf",
        0.45,
    ),
}
DEFAULT_MODEL = "v3"
MODEL_ENV = "LCC_INTAKE_CATEGORY_MODEL"
NOTES_RESOURCE = "intake_categories.json"
NOTES_SHA256 = "38f17b94234d594b8ff4ebf3ee41b37da6e789c12af7b09fa346527842cd7b5a"
#: The models were trained on prompts of at most 1,000 characters (longer ones were pasted context),
#: so only the head is classified; this also keeps the cost flat on long inputs.
MAX_CHARS = 1000
#: v3 saw the last 600 characters of the agent's previous turn.
PREV_CHARS = 600
BUCKETS = 1 << 15
PREV_BUCKETS = 1 << 14
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


def model_name() -> str:
    """The model in use: ``LCC_INTAKE_CATEGORY_MODEL`` if it names one, else the default."""
    name = os.environ.get(MODEL_ENV, "").strip().lower()
    return name if name in MODELS else DEFAULT_MODEL


class _Model:
    def __init__(self, data: dict, notes: dict[str, str], threshold: float) -> None:
        self.labels: list[str] = data["labels"]
        self.bias: list[float] = data["bias"]
        self.threshold = threshold
        if data.get("format") == "lcc-intake-judge/2":  # v3: prompt rows, then previous-turn rows
            if data["ranges"] != [[0, BUCKETS], [BUCKETS, BUCKETS + PREV_BUCKETS]]:
                raise ValueError(f"unsupported ranges {data['ranges']}")
            self.kinds, rows, self.reads_prev = "char+word", BUCKETS + PREV_BUCKETS, True
        else:
            self.kinds, rows, self.reads_prev = data["kinds"], BUCKETS, False
        k = len(self.labels)
        self.w = struct.unpack(f"<{rows * k}e", base64.b64decode(data["weights_f16"]))
        self.notes = notes

    def proba(self, text: str, previous_turn: str | None = None) -> list[float]:
        k = len(self.labels)
        z = list(self.bias)
        w = self.w
        feats = features(text[:MAX_CHARS], self.kinds)
        if self.reads_prev and isinstance(previous_turn, str) and previous_turn:
            # Same featuriser in its own index range, binary and L2-normalised on its own.
            block = sorted(
                {
                    BUCKETS + i % PREV_BUCKETS
                    for i in features(previous_turn[-PREV_CHARS:], self.kinds)
                }
            )
            feats.update(dict.fromkeys(block, 1 / math.sqrt(len(block))))
        for idx, v in feats.items():
            base = idx * k
            z = [a + b * v for a, b in zip(z, w[base : base + k], strict=True)]
        m = max(z)
        e = [math.exp(x - m) for x in z]
        s = sum(e)
        return [x / s for x in e]


@lru_cache(maxsize=4)
def _load(name: str | None = None) -> _Model | None:
    pkg = resources.files("lcc.intake")
    try:
        resource, sha256, threshold = MODELS[name or model_name()]
        raw = pkg.joinpath(resource).read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha256:
            raise ValueError("sha256 mismatch")
        notes_raw = pkg.joinpath(NOTES_RESOURCE).read_bytes()
        if hashlib.sha256(notes_raw).hexdigest() != NOTES_SHA256:
            raise ValueError("notes sha256 mismatch")
        # The notes reach the agent prompt: pinned above, and flattened to plain strings here.
        notes = {
            str(label): str(entry["context_needed"])
            for label, entry in json.loads(notes_raw)["categories"].items()
        }
        return _Model(json.loads(raw), notes, threshold)
    except (OSError, ValueError, KeyError, TypeError, struct.error) as exc:
        LOGGER.warning("intake category model unavailable: %s", exc)
        return None


def classify(
    text: str, threshold: float | None = None, previous_turn: str | None = None
) -> Category | None:
    """Most likely category when its probability reaches ``threshold`` (default: the model's own);
    else ``None``. ``previous_turn`` is the agent's last message before ``text``, if known.

    ``UNKNOWN`` means "cannot tell from the text", so it is reported as no category.
    """
    model = _load(model_name())
    if model is None or not (text or "").strip():
        return None
    p = model.proba(text, previous_turn)
    i = max(range(len(p)), key=p.__getitem__)
    label = model.labels[i]
    if p[i] < (model.threshold if threshold is None else threshold) or label == "UNKNOWN":
        return None
    return Category(label, round(p[i], 4), model.notes.get(label, ""))
