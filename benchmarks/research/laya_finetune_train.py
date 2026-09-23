#!/usr/bin/env python3
"""Head-only fine-tune of a Laya checkpoint for LCC's keep/drop question.

The shipped Laya checkpoints keep every block on LCC's corpora (0.0% reduction at every
scale) because they were never trained for this decision. The vendor's recipe for that
situation is the RLCD fine-tune in
``notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb``: noisy-logit policy gradient
on a strictly proper scoring rule plus a soft cross-entropy guide, AdamW with separate
encoder/head rates, temperatures fitted on a held-out slice afterwards.

This script runs that recipe on one device (no DDP, no CUDA) and — per the scope agreed for
the first pass — trains **only the decision head** (``type_emb``, ``head``, ``scorer``,
``act_head``) with the encoder frozen. Items come from
``benchmarks/research/laya_finetune_items.py``; validation runs on the slice the optimiser
never sees, and reports the separation the shipped checkpoint cannot produce.

Run: python3 benchmarks/research/laya_finetune_train.py \
       --items benchmarks/research/results/laya_finetune/items_train.pt \
       --out benchmarks/research/results/laya_finetune/laya-lcc-relevance-v1
"""

from __future__ import annotations

# ruff: noqa: I001, E402 — sys.path bootstrap must precede sibling imports.
import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from lcc.relevance.laya import DEFAULT_LAYA_MODEL  # noqa: E402


def collate(items: list[dict[str, Any]], pad_id: int) -> dict[str, Any]:
    """Pad a batch of items into tensors (mirrors the vendor notebook's collate)."""
    import torch

    n, length = len(items), max(len(item["ids"]) for item in items)
    kmax = max(len(item["markers"]) for item in items)
    ids = torch.full((n, length), pad_id, dtype=torch.long)
    att = torch.zeros((n, length), dtype=torch.long)
    mpos = torch.zeros((n, kmax), dtype=torch.long)
    mmask = torch.zeros((n, kmax), dtype=torch.bool)
    target = torch.zeros((n, kmax), dtype=torch.float32)
    for i, item in enumerate(items):
        ids[i, : len(item["ids"])] = torch.tensor(item["ids"])
        att[i, : len(item["ids"])] = 1
        k = len(item["markers"])
        mpos[i, :k] = torch.tensor(item["markers"])
        mmask[i, :k] = True
        target[i, : len(item["target"])] = torch.tensor(item["target"], dtype=torch.float32)
    return {
        "input_ids": ids,
        "attention_mask": att,
        "marker_pos": mpos,
        "marker_mask": mmask,
        "target": target,
        "qtype": torch.tensor([item["qtype"] for item in items]),
        "label": torch.tensor([item["label"] for item in items]),
    }


def validate(model, items: list[dict[str, Any]], pad_id: int, device: str) -> dict[str, Any]:
    """Per-item p(true) on held-out items: separation, accuracy and the drop band."""
    import torch

    model.eval()
    probs: list[float] = []
    labels: list[int] = []
    with torch.no_grad():
        for start in range(0, len(items), 16):
            chunk = items[start : start + 16]
            batch = collate(chunk, pad_id)
            logits, _ = model(
                batch["input_ids"].to(device),
                batch["attention_mask"].to(device),
                batch["marker_pos"].to(device),
                batch["marker_mask"].to(device),
                batch["qtype"].to(device),
                detach_encoder=True,
            )
            masked = logits.masked_fill(~batch["marker_mask"].to(device), -1e4)
            probs.extend(torch.softmax(masked.float(), -1)[:, 1].cpu().tolist())
            labels.extend(batch["label"].tolist())
    evidence = [p for p, y in zip(probs, labels, strict=True) if y == 1]
    noise = [p for p, y in zip(probs, labels, strict=True) if y == 0]
    mean = lambda xs: (sum(xs) / len(xs)) if xs else float("nan")  # noqa: E731
    thresholds = {}
    for threshold in (0.4, 0.5):
        kept_evidence = sum(1 for p in evidence if p >= threshold)
        dropped_noise = sum(1 for p in noise if p < threshold)
        thresholds[str(threshold)] = {
            "evidence_kept_ratio": kept_evidence / max(1, len(evidence)),
            "noise_dropped_ratio": dropped_noise / max(1, len(noise)),
            "accuracy": (kept_evidence + dropped_noise) / max(1, len(labels)),
        }
    model.train()
    return {
        "items": len(items),
        "evidence_items": len(evidence),
        "noise_items": len(noise),
        "mean_p_true_evidence": mean(evidence),
        "mean_p_true_noise": mean(noise),
        "separation": mean(evidence) - mean(noise),
        "thresholds": thresholds,
    }


def fit_one_temp(sel: list[tuple[list[float], list[float]]]) -> float:
    """Fit one temperature by minimising log loss on held-out logits (vendor recipe)."""
    import torch

    if len(sel) < 10:
        return 1.0
    kmax = max(len(z) for z, _ in sel)
    z_tensor = torch.full((len(sel), kmax), -1e4)
    t_tensor = torch.zeros((len(sel), kmax))
    for i, (z, t) in enumerate(sel):
        z_tensor[i, : len(z)] = torch.tensor(z)
        t_tensor[i, : len(t)] = torch.tensor(t, dtype=torch.float32)
    log_t = torch.zeros(1, requires_grad=True)
    optimizer = torch.optim.LBFGS([log_t], lr=0.1, max_iter=100)

    def closure():  # pragma: no cover - LBFGS closure
        optimizer.zero_grad()
        loss = -(t_tensor * torch.log_softmax(z_tensor / log_t.exp(), -1)).sum(-1).mean()
        loss.backward()
        return loss

    optimizer.step(closure)
    return float(torch.clamp(log_t.exp(), 0.5, 5.0).item())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--items", required=True, help="Items .pt from laya_finetune_items.py.")
    parser.add_argument("--checkpoint", default=DEFAULT_LAYA_MODEL)
    parser.add_argument("--out", required=True, help="Output checkpoint directory.")
    parser.add_argument("--device", default="mps", choices=("mps", "cpu", "cuda"))
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--micro-batch", type=int, default=8)
    parser.add_argument("--grad-accum", type=int, default=4)
    parser.add_argument("--group-size", type=int, default=4, help="GRPO baseline samples.")
    parser.add_argument("--lr-head", type=float, default=1.0e-4)
    parser.add_argument("--sigma-start", type=float, default=0.4)
    parser.add_argument("--sigma-end", type=float, default=0.1)
    parser.add_argument("--max-items", type=int, default=0, help="Debug: cap the item count.")
    parser.add_argument("--holdout", type=int, default=400, help="Items reserved for calibration.")
    parser.add_argument(
        "--evidence-ratio",
        type=float,
        default=0.35,
        help="Share of evidence items per training epoch. The corpora are ~7%% evidence, and a "
        "head trained on that prior answers 'drop' (the LCC failure, inverted).",
    )
    parser.add_argument(
        "--evidence-weight",
        type=float,
        default=2.0,
        help="Loss weight of an evidence item relative to a noise item. A false drop breaks an "
        "answer; a false keep costs tokens, so the imbalance is deliberate.",
    )
    parser.add_argument("--seed", type=int, default=20260923)
    parser.add_argument("--save-every-epoch", action="store_true", default=True)
    args = parser.parse_args()

    import torch
    from huggingface_hub import snapshot_download
    from safetensors.torch import load_file
    from transformers import AutoTokenizer

    from laya.common import QTYPES, build_model, proper_reward

    device = args.device
    if device == "mps" and not torch.backends.mps.is_available():
        print("mps unavailable; falling back to cpu")
        device = "cpu"

    model_dir = Path(snapshot_download(args.checkpoint, local_files_only=True))
    with open(model_dir / "rl_agent_config.json", encoding="utf-8") as handle:
        cfg = json.load(handle)
    tok = AutoTokenizer.from_pretrained(str(model_dir / "tokenizer"))
    model = build_model(cfg, encoder_dir=str(model_dir / "encoder"))
    model.load_state_dict(load_file(str(model_dir / "model.safetensors")), strict=True)

    # Freeze the encoder: this pass trains the decision head only (agreed scope: prove the
    # head can learn the judgement before spending hours on encoder adaptation).
    for name, param in model.named_parameters():
        param.requires_grad_("encoder." not in name)
    model.encoder.eval()

    items: list[dict[str, Any]] = torch.load(args.items, weights_only=False)
    if args.max_items:
        items = items[: args.max_items]
    order = list(range(len(items)))
    random.Random(args.seed).shuffle(order)
    holdout = min(args.holdout, max(1, len(items) // 10))
    calib_items = [items[i] for i in sorted(order[:holdout])]
    train_items = [items[i] for i in sorted(order[holdout:])]
    print(
        f"device={device} checkpoint={args.checkpoint} items={len(items)} "
        f"train={len(train_items)} calib={len(calib_items)}"
    )

    model.to(device)
    model.train()

    head_params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(head_params, lr=args.lr_head, weight_decay=0.01)
    updates_per_epoch = max(1, len(train_items) // (args.micro_batch * args.grad_accum))
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=max(1, updates_per_epoch * args.epochs), eta_min=1e-6
    )
    use_amp = device == "mps"
    history: list[dict[str, Any]] = []
    started = time.time()

    evidence_pool = [item for item in train_items if item["label"] == 1]
    noise_pool = [item for item in train_items if item["label"] == 0]

    def balanced_epoch(seed: int) -> list[dict[str, Any]]:
        """One epoch's items: noise plus evidence repeated up to ``--evidence-ratio``.

        The corpora are ~7% evidence, so an unweighted head learns the prior and answers
        'drop' — the mirror image of the keep-all failure this work exists to fix.
        """
        if not evidence_pool or args.evidence_ratio <= 0 or not noise_pool:
            epoch_items = list(train_items)
        else:
            wanted = max(
                1, int(len(noise_pool) * args.evidence_ratio / max(1e-6, 1 - args.evidence_ratio))
            )
            copies = max(1, wanted // len(evidence_pool))
            epoch_items = list(noise_pool) + evidence_pool * copies
        random.Random(seed).shuffle(epoch_items)
        return epoch_items

    for epoch in range(args.epochs):
        epoch_items = balanced_epoch(args.seed + epoch)
        epoch_evidence = sum(1 for item in epoch_items if item["label"] == 1)
        print(
            f"epoch {epoch + 1}/{args.epochs}: {len(epoch_items)} items "
            f"({epoch_evidence} evidence, {100 * epoch_evidence / max(1, len(epoch_items)):.1f}%)",
            flush=True,
        )
        progress = epoch / max(1, args.epochs - 1)
        sigma = args.sigma_start + (args.sigma_end - args.sigma_start) * progress
        epoch_loss, steps = 0.0, 0
        optimizer.zero_grad(set_to_none=True)
        for step_index, start in enumerate(
            range(0, len(epoch_items), args.micro_batch), start=1
        ):
            chunk = epoch_items[start : start + args.micro_batch]
            batch = collate(chunk, tok.pad_token_id)
            inputs = {k: batch[k].to(device) for k in ("input_ids", "attention_mask", "marker_pos", "marker_mask", "qtype")}
            with torch.autocast(device_type=device, dtype=torch.bfloat16, enabled=use_amp):
                logits, _ = model(**inputs, detach_encoder=True)
            logits = logits.float()
            mask = batch["marker_mask"].to(device)
            target = batch["target"].to(device)
            k = mask.sum(-1, keepdim=True).float()

            eps = torch.randn((args.group_size,) + logits.shape, device=device) * sigma * mask
            eps = (eps - eps.sum(-1, keepdim=True) / k) * mask
            z = logits.detach().unsqueeze(0) + eps
            q = torch.softmax(z.masked_fill(~mask, -1e4), -1)
            with torch.no_grad():
                reward = proper_reward(
                    q, target.unsqueeze(0), batch["qtype"].to(device), mask, w_sph=0.75, w_rps=1.0
                )
                advantage = reward - reward.mean(0, keepdim=True)
                advantage = advantage / (advantage.std() + 1e-6)

            logp = -(((z - logits.unsqueeze(0)) ** 2) * mask).sum(-1) / (2 * sigma**2)
            rl_per_item = -(advantage * logp).mean(0)
            ce_per_item = -(
                target * torch.log_softmax(logits.masked_fill(~mask, -1e4), -1)
            ).sum(-1)
            weights = torch.tensor(
                [args.evidence_weight if item["label"] == 1 else 1.0 for item in chunk],
                device=device,
            )
            weights = weights / weights.sum()
            loss = ((weights * rl_per_item).sum() + (weights * ce_per_item).sum()) / args.grad_accum
            loss.backward()
            steps += 1
            epoch_loss += float(loss.item()) * args.grad_accum
            if step_index % args.grad_accum == 0 or start + args.micro_batch >= len(epoch_items):
                torch.nn.utils.clip_grad_norm_(head_params, 1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad(set_to_none=True)
            if steps % 50 == 0:
                print(
                    f"  epoch {epoch + 1}/{args.epochs} step {steps} "
                    f"loss {epoch_loss / steps:.4f} sigma {sigma:.2f}",
                    flush=True,
                )

        metrics = validate(model, calib_items, tok.pad_token_id, device)
        metrics.update({"epoch": epoch + 1, "avg_loss": epoch_loss / max(1, steps), "seconds": round(time.time() - started, 1)})
        history.append(metrics)
        print(
            f"epoch {epoch + 1}/{args.epochs} loss {metrics['avg_loss']:.4f} "
            f"| evidence p {metrics['mean_p_true_evidence']:.3f} "
            f"noise p {metrics['mean_p_true_noise']:.3f} "
            f"separation {metrics['separation']:.3f} "
            f"| @0.4 evidence kept {metrics['thresholds']['0.4']['evidence_kept_ratio']:.3f} "
            f"noise dropped {metrics['thresholds']['0.4']['noise_dropped_ratio']:.3f}",
            flush=True,
        )
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        if args.save_every_epoch:
            _save_checkpoint(model, tok, cfg, out_dir / "checkpoint_latest", metrics, args)
            print(f"  saved rolling checkpoint to {out_dir / 'checkpoint_latest'}", flush=True)

    # Final: fit the calibration temperature on held-out logits, then write the checkpoint.
    print("fitting post-training temperature on the held-out slice", flush=True)
    model.eval()
    logit_rows: list[tuple[list[float], list[float]]] = []
    with torch.no_grad():
        for start in range(0, len(calib_items), 16):
            chunk = calib_items[start : start + 16]
            batch = collate(chunk, tok.pad_token_id)
            logits, _ = model(
                batch["input_ids"].to(device),
                batch["attention_mask"].to(device),
                batch["marker_pos"].to(device),
                batch["marker_mask"].to(device),
                batch["qtype"].to(device),
                detach_encoder=True,
            )
            for row, item in zip(logits.cpu().tolist(), chunk, strict=True):
                k = len(item["markers"])
                logit_rows.append((row[:k], item["target"]))
    fitted = fit_one_temp(logit_rows)
    fitted_temperatures = list(cfg.get("temperature", [1.0, 1.0, 1.0]))
    fitted_temperatures[QTYPES["noul"]] = fitted
    print(f"fitted noul temperature: {fitted:.3f}", flush=True)

    out_dir = Path(args.out)
    metrics = {"history": history, "fitted_noul_temperature": fitted}
    _save_checkpoint(model, tok, cfg, out_dir, metrics, args, temperatures=fitted_temperatures)
    (out_dir / "training_meta.json").write_text(
        json.dumps(
            {
                "checkpoint": args.checkpoint,
                "items": args.items,
                "device": device,
                "epochs": args.epochs,
                "micro_batch": args.micro_batch,
                "grad_accum": args.grad_accum,
                "lr_head": args.lr_head,
                "train_items": len(train_items),
                "calib_items": len(calib_items),
                "frozen_encoder": True,
                "history": history,
                "fitted_noul_temperature": fitted,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"checkpoint written to {out_dir}")
    return 0


def _save_checkpoint(model, tok, cfg: dict[str, Any], out_dir: Path, metrics: dict[str, Any], args, temperatures=None) -> None:
    """Write a directory ``laya.load`` accepts: weights, encoder config, tokenizer, config."""
    from safetensors.torch import save_file

    from laya.agent import _fix_tokenizer_config

    out_dir.mkdir(parents=True, exist_ok=True)
    state = {k: v.half().contiguous().cpu() for k, v in model.state_dict().items()}
    save_file(state, str(out_dir / "model.safetensors"))
    model.encoder.config.save_pretrained(str(out_dir / "encoder"))
    tok.save_pretrained(str(out_dir / "tokenizer"))
    _fix_tokenizer_config(str(out_dir))
    out_cfg = dict(cfg)
    out_cfg["fine_tuned"] = True
    out_cfg["model_name"] = "laya-lcc-relevance"
    if temperatures is not None:
        out_cfg["temperature"] = temperatures
        # A per-bucket override would hide the freshly fitted value.
        out_cfg.pop("temperature_by_options", None)
    out_cfg["lcc_training"] = {
        "task": "lcc keep/drop noul question (benchmarks/research/laya_finetune_items.py)",
        "frozen_encoder": True,
        "metrics": {k: v for k, v in metrics.items() if k != "history"},
    }
    (out_dir / "rl_agent_config.json").write_text(json.dumps(out_cfg, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
