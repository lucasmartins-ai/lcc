"""Command-line interface for the ACT II router."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

import yaml

from act2_router.config import load_policy
from act2_router.eval_runner import load_task, run_evaluation, write_reports
from act2_router.features import extract_features
from act2_router.lcc_adapter import inspect_context
from act2_router.router import LCCRouter, final_answer_to_dict
from act2_router.schemas import FinalAnswer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m act2_router.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run")
    run_parser.add_argument("--task", required=True)

    eval_parser = sub.add_parser("eval")
    eval_parser.add_argument("--cases", required=True)
    eval_parser.add_argument("--output", default="eval/reports/report.json")

    inspect_parser = sub.add_parser("inspect")
    inspect_parser.add_argument("--task", required=True)

    policy_parser = sub.add_parser("policy")
    policy_parser.add_argument("--show", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "run":
        task, _raw = load_task(args.task)
        final = LCCRouter().run(task)
        _print_run(final)
        return 0
    if args.command == "eval":
        report = run_evaluation(args.cases)
        out = write_reports(report, args.output)
        print(f"Wrote {out} and {out.with_suffix('.md')}")
        print(json.dumps(report["result"], indent=2, ensure_ascii=False))
        return 0
    if args.command == "inspect":
        task, _raw = load_task(args.task)
        policy = load_policy()
        summary = inspect_context(task)
        features = extract_features(task, summary, policy.risk)
        print(json.dumps({"lcc": asdict(summary), "features": asdict(features)}, indent=2))
        return 0
    if args.command == "policy":
        if args.show:
            print(yaml.safe_dump(load_policy().to_dict(), sort_keys=False))
            return 0
        parser.error("policy requires --show")
    return 1


def _print_run(final: FinalAnswer) -> None:
    payload = final_answer_to_dict(final)
    print("Final answer:")
    print(payload["answer"])
    print()
    print(f"route_taken: {payload['route_taken']}")
    print(f"remote_tokens_used: {payload['remote_tokens_used']}")
    metadata = payload.get("metadata", {})
    if isinstance(metadata, dict):
        print(f"lcc_compression_applied: {metadata.get('compression_applied', False)}")
        lcc = metadata.get("lcc", {})
        if isinstance(lcc, dict) and lcc.get("warnings"):
            print("warnings:")
            for warning in lcc["warnings"]:
                print(f"- {warning}")
    verification = payload.get("verification")
    if isinstance(verification, dict):
        print(f"verifier_decision: {verification.get('decision')}")
        print(f"verifier_confidence: {verification.get('confidence')}")


if __name__ == "__main__":
    raise SystemExit(main())
