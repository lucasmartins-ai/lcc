#!/usr/bin/env python3
"""Supervised items for fine-tuning a Laya checkpoint on LCC's keep/drop question.

Why this exists: the shipped Laya checkpoints keep every block on LCC's corpora (0.0%
reduction at every scale, `benchmarks/research/RESEARCH_STATUS.md`), and the vendor states
the reason plainly — "Laya is a fast base to specialise, not a zero-shot decision engine".
Specialising it needs supervised pairs in the exact shape production sends, which is what
this script builds:

* items come from the corpus factory (`make_corpora.build`), whose ground-truth markers
  label every block without a human in the loop;
* each item is one Laya sequence: state ``{"objective": …, "blocks": [{"id", "text"}…]}``
  (the JSON production sends) plus one ``noul`` keep question per block, built from
  :func:`lcc.relevance.compactor.keep_question` so training and inference cannot drift.

Two things this script deliberately does *not* do, because either would produce a model
that scores well here and fails in production:

1. **No benchmark label tokens.** The corpora carry literal ``GROUND TRUTH A:`` and
   ``(not evidence, ignore)`` markers. A head trained on them learns the benchmark's label
   vocabulary, so the text is de-labelled first (``_de_label``) and the labels come from
   marker matching, which survives the rewrite.
2. **No single objective.** Every corpus in the factory answers one fixed objective, so a
   head could learn "GROUND TRUTH → keep, LOG → drop" without ever reading the objective.
   Each corpus therefore contributes the same blocks under six objectives: the corpus's own
   (answer every category) plus the five numbered questions of its task text (answer one
   fact). The same evidence block is a keep for the objective it answers and a drop for the
   four it does not, which is the judgement production actually asks for.

Training seeds are >= 1000 on purpose: the canonical seed-42 corpora stay a measurement.

Run: python3 benchmarks/research/laya_finetune_items.py
     python3 benchmarks/research/laya_finetune_items.py --seeds 1001 1002 --no-xl
"""

from __future__ import annotations

# ruff: noqa: I001, E402 — sys.path bootstrap must precede sibling imports.
import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

import make_corpora  # noqa: E402  (sibling research harness)

from lcc.relevance.blocks import split_blocks  # noqa: E402
from lcc.relevance.compactor import (  # noqa: E402
    KEEP_INSTRUCTIONS,
    keep_question,
)

DEFAULT_OUT_DIR = HERE / "results" / "laya_finetune"
#: The stable prefix block carries the contract every answer must respect; it is keep
#: material under every objective.
PREFIX_MARK = "SYSTEM CONTRACT (stable reference, must never be dropped)"
#: Soft targets: a 0/1 target teaches a certainty the ground truth does not support (the same
#: block matters more or less depending on the objective).
TARGET_KEEP = (0.02, 0.98)  # render_options order is [false, true]
TARGET_DROP = (0.98, 0.02)
#: Which marker indices answer each numbered question of the corpus task text. Derived by
#: reading `make_corpora.BLOCKS` against `make_corpora.TASK`: the fact that answers the
#: question, plus the block that qualifies or supersedes it (exception, revision), because a
#: confident answer needs both halves of the pair.
NARROW_MARKERS: dict[int, tuple[int, ...]] = {
    1: (0, 7),  # mobile-visitor share + the exception that bounds it
    2: (1, 8),  # p75 load time + the revision that supersedes it
    3: (2,),  # messages outside opening hours
    4: (3,),  # idle chair capacity after 17:00
    5: (4,),  # front-desk re-typing time
}
_QUESTION_RE = re.compile(r"^\s*(\d+)\.\s+(.+?)\s*$")


def _de_label(text: str) -> str:
    """Strip the benchmark's own label vocabulary from a block.

    ``GROUND TRUTH A:`` and ``(not evidence, ignore)`` state the answer. Training on them
    measures label-token recognition, not relevance, so they are removed before the text
    reaches the model. The categories that read like ordinary dossier headers
    (``OPERATING CONSTRAINT``, ``COMPLIANCE RULE``, ``EXCEPTION``, ``REVISION``) stay.
    """
    text = re.sub(r"^GROUND TRUTH [A-Z]:\s*", "", text)
    text = re.sub(r"^DISTRACTOR \d+ \((?:not evidence, ignore)\):\s*", "", text)
    text = text.replace(" (not evidence, ignore)", "")
    text = text.replace(
        "so treat this line as unresolved background rather than evidence",
        "so treat this line as unresolved background",
    )
    return text


def _task_questions(task: str) -> list[str]:
    return [match.group(2) for match in (_QUESTION_RE.match(line) for line in task.splitlines()) if match]


def _token_count(tok, text: str) -> int:
    return len(tok(text, add_special_tokens=False)["input_ids"])


def _objective_specs(corpus: dict[str, Any]) -> list[tuple[str, str, tuple[str, ...]]]:
    """``(name, objective, keep_markers)`` rows this corpus is measured under."""
    markers = tuple(item["marker"] for item in corpus["items"])
    questions = _task_questions(corpus["task"])
    specs: list[tuple[str, str, tuple[str, ...]]] = [("full", corpus["objective"], markers)]
    for number, indices in sorted(NARROW_MARKERS.items()):
        if number > len(questions):
            continue
        specs.append((f"q{number}", questions[number - 1], tuple(markers[i] for i in indices)))
    return specs


def _label(text: str, keep_markers: tuple[str, ...]) -> int:
    if PREFIX_MARK in text:
        return 1
    return 1 if any(re.search(marker, text) for marker in keep_markers) else 0


def _self_check(scale: str, seed: int) -> None:
    """Fail loudly if the labelling rule could mislabel the factory's own noise."""
    corpus = make_corpora.build(scale, seed)
    markers = [item["marker"] for item in corpus["items"]]
    noise_sources: list[str] = [corpus["forbidden"][0], corpus["forbidden"][1]]
    for i in range(0, 420):
        for template in make_corpora.TOOLS + make_corpora.LOGS + make_corpora.CHATTER:
            noise_sources.append(template.format(i=i, p=50, f=20, m=500, b=7))
    for marker in markers:
        hits = [text for text in noise_sources if re.search(marker, text)]
        if hits:
            raise SystemExit(
                f"labelling self-check failed for {scale}/{seed}: marker {marker!r} "
                f"matches factory noise {hits[0][:80]!r}"
            )
    for spec_name, _, keep_markers in _objective_specs(corpus):
        found = [m for m in keep_markers if re.search(m, corpus["text"])]
        if not found:
            raise SystemExit(
                f"labelling self-check failed for {scale}/{seed}/{spec_name}: no keep marker "
                "is present in the corpus text"
            )
    # The de-labelling rewrite must not disturb the markers it is meant to survive.
    for item in corpus["items"]:
        if not re.search(item["marker"], _de_label(corpus["text"])):
            raise SystemExit(
                f"de-labelling self-check failed for {scale}/{seed}: marker "
                f"{item['marker']!r} no longer matches after _de_label"
            )


def _room_for_state(tok, question: dict, max_len: int, head_max_len: int) -> int:
    """Tokens left for the state after the question head, mirroring ``build_sequence``."""
    from laya.common import build_sequence

    probe_ids, _ = build_sequence(tok, "", question, max_len, head_max_len)
    return max_len - len(probe_ids)


def _make_item(
    tok,
    objective: str,
    blocks: list[Any],
    target_block: Any,
    label: int,
    question: dict,
    max_len: int,
    head_max_len: int,
    provenance: dict[str, Any],
) -> dict[str, Any] | None:
    """One training item: the production state, one question, one target.

    ``None`` when the state cannot be shown inside the window: production keeps such blocks
    whole instead of truncating, so training must not learn from a truncated one.
    """
    from laya.common import build_sequence, serialize_state

    state = {
        "objective": objective,
        "blocks": [{"id": block.id, "text": _de_label(block.text)} for block in blocks],
    }
    if _token_count(tok, serialize_state(state)) > _room_for_state(
        tok, question, max_len, head_max_len
    ):
        return None
    ids, markers = build_sequence(tok, state, question, max_len, head_max_len)
    return {
        "ids": ids,
        "markers": markers,
        "qtype": 2,  # noul
        "target": list(TARGET_KEEP if label == 1 else TARGET_DROP),
        "label": label,
        "block_id": target_block.id,
        "state_blocks": [block.id for block in blocks],
        **provenance,
    }


def build_items_for_corpus(
    tok,
    scale: str,
    seed: int,
    *,
    max_len: int,
    head_max_len: int,
    multi_fraction: float,
    multi_max: int,
    block_token_budget: int,
    narrow_noise_sample: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    corpus = make_corpora.build(scale, seed)
    specs = _objective_specs(corpus)
    blocks = [block for block in split_blocks(corpus["text"]) if not block.protected]
    texts = {block.id: _de_label(block.text) for block in blocks}
    sizes = {block.id: _token_count(tok, texts[block.id]) for block in blocks}
    small_blocks = [block for block in blocks if sizes[block.id] <= block_token_budget]
    items: list[dict[str, Any]] = []

    for spec_name, objective, keep_markers in specs:
        labels = {block.id: _label(texts[block.id], keep_markers) for block in blocks}
        evidence = [block for block in small_blocks if labels[block.id] == 1]
        noise = [block for block in small_blocks if labels[block.id] == 0]
        rng.shuffle(noise)
        if spec_name != "full":
            # A narrow objective keeps one fact; the rest of the corpus is drop material and
            # is sampled rather than repeated once per question.
            noise = noise[:narrow_noise_sample]
        provenance = {"scale": scale, "seed": seed, "objective_kind": spec_name}
        for block in evidence + noise:
            question = _q_internal(keep_question(block.id))
            item = _make_item(
                tok,
                objective,
                [block],
                block,
                labels[block.id],
                question,
                max_len,
                head_max_len,
                provenance,
            )
            if item is not None:
                item["state_kind"] = "single"
                items.append(item)

        # Multi-block states: production sends up to ``--batch-size`` blocks per call, each
        # with its own question, so the judge sees candidates next to each other.
        evidence = list(evidence)
        rng.shuffle(evidence)
        while len(evidence) >= 2 and len(noise) >= 1:
            group_evidence = evidence[: rng.randint(1, min(2, len(evidence)))]
            del evidence[: len(group_evidence)]
            group_noise = noise[: rng.randint(1, min(multi_max - len(group_evidence), len(noise)))]
            del noise[: len(group_noise)]
            group = group_evidence + group_noise
            rng.shuffle(group)
            for block in group:
                question = _q_internal(keep_question(block.id))
                item = _make_item(
                    tok,
                    objective,
                    group,
                    block,
                    labels[block.id],
                    question,
                    max_len,
                    head_max_len,
                    provenance,
                )
                if item is not None:
                    item["state_kind"] = "multi"
                    items.append(item)

    if multi_fraction < 1.0:
        singles = [i for i in items if i["state_kind"] == "single"]
        multis = [i for i in items if i["state_kind"] == "multi"]
        if multis:
            wanted = int(len(singles) * multi_fraction / max(1e-9, 1 - multi_fraction))
            rng.shuffle(multis)
            keep = {id(i) for i in multis[:wanted]}
            items = [i for i in items if i["state_kind"] == "single" or id(i) in keep]
    return items


def _q_internal(question: dict) -> dict:
    """Laya's own normalisation (``Agent._to_internal``), so the harness cannot drift."""
    from laya.agent import Agent

    return Agent._to_internal(question)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--seeds",
        nargs="+",
        type=int,
        default=[1001, 1002, 1003, 1004, 1005, 1006],
        help="Corpus seeds for training items (>= 1000 keeps seed 42 held out).",
    )
    parser.add_argument(
        "--scales",
        nargs="+",
        default=["small", "medium", "large"],
        choices=list(make_corpora.SCALES),
    )
    parser.add_argument("--xl-seed", type=int, default=1099, help="One xl corpus, 0 disables.")
    parser.add_argument(
        "--checkpoint",
        default="convaiinnovations/laya-multilingual",
        help="Checkpoint whose tokenizer/config define the sequence shape.",
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT_DIR / "items_train.pt"))
    parser.add_argument("--multi-fraction", type=float, default=0.4)
    parser.add_argument("--multi-max", type=int, default=3)
    parser.add_argument(
        "--block-token-budget",
        type=int,
        default=420,
        help="Blocks larger than this are skipped (window math for multi-block states).",
    )
    parser.add_argument(
        "--narrow-noise-sample",
        type=int,
        default=24,
        help="Noise blocks sampled per narrow objective.",
    )
    args = parser.parse_args()

    import torch
    from huggingface_hub import snapshot_download
    from transformers import AutoTokenizer

    model_dir = snapshot_download(args.checkpoint, local_files_only=True)
    with open(Path(model_dir) / "rl_agent_config.json", encoding="utf-8") as handle:
        cfg = json.load(handle)
    max_len = int(cfg.get("max_len", 1024))
    head_max_len = int(cfg.get("head_max_len", 192))
    tok = AutoTokenizer.from_pretrained(str(Path(model_dir) / "tokenizer"))

    rng = random.Random(20260923)
    items: list[dict[str, Any]] = []
    jobs = [(scale, seed) for scale in args.scales for seed in args.seeds]
    if args.xl_seed:
        jobs.append(("xl", args.xl_seed))
    for scale, seed in jobs:
        _self_check(scale, seed)
        built = build_items_for_corpus(
            tok,
            scale,
            seed,
            max_len=max_len,
            head_max_len=head_max_len,
            multi_fraction=args.multi_fraction,
            multi_max=args.multi_max,
            block_token_budget=args.block_token_budget,
            narrow_noise_sample=args.narrow_noise_sample,
            rng=rng,
        )
        positive = sum(1 for item in built if item["label"] == 1)
        by_kind: dict[str, list[int]] = {}
        for item in built:
            row = by_kind.setdefault(item["objective_kind"], [0, 0])
            row[item["label"]] += 1
        detail = " ".join(
            f"{kind}:{row[1]}/{row[1] + row[0]}" for kind, row in sorted(by_kind.items())
        )
        print(f"{scale}/{seed}: {len(built)} items ({positive} evidence) [{detail}]")
        items.extend(built)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(items, out_path)
    positives = sum(1 for item in items if item["label"] == 1)
    manifest = {
        "checkpoint": args.checkpoint,
        "max_len": max_len,
        "head_max_len": head_max_len,
        "keep_instructions": KEEP_INSTRUCTIONS,
        "seeds": args.seeds,
        "scales": args.scales,
        "xl_seed": args.xl_seed,
        "de_labelled": True,
        "objective_kinds": sorted({item["objective_kind"] for item in items}),
        "items": len(items),
        "evidence_items": positives,
        "noise_items": len(items) - positives,
        "single_block_items": sum(1 for item in items if item["state_kind"] == "single"),
        "multi_block_items": sum(1 for item in items if item["state_kind"] == "multi"),
    }
    (out_path.with_suffix(".manifest.json")).write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"wrote {out_path} ({len(items)} items, {positives} evidence)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
