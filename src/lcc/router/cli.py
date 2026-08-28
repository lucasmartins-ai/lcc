"""Command-line interface for the LCC hybrid router and local agents."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

import yaml

from lcc.agents.local_agent import LocalAgent, create_local_agent_from_env
from lcc.router.config import load_policy
from lcc.router.context_adapter import inspect_context
from lcc.router.eval_runner import load_task, run_evaluation, write_reports
from lcc.router.features import extract_features
from lcc.router.router import LCCRouter, final_answer_to_dict
from lcc.router.schemas import FinalAnswer, TaskInput


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lcc-router")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run")
    run_parser.add_argument("--task", required=True, help="Path to task JSON/YAML fixture")

    eval_parser = sub.add_parser("eval")
    eval_parser.add_argument("--cases", required=True, help="Directory containing task cases")
    eval_parser.add_argument("--output", default="eval/reports/report.json")

    inspect_parser = sub.add_parser("inspect")
    inspect_parser.add_argument("--task", required=True)

    policy_parser = sub.add_parser("policy")
    policy_parser.add_argument("--show", action="store_true")

    agent_parser = sub.add_parser("agent")
    agent_sub = agent_parser.add_subparsers(dest="agent_command", required=True)

    agent_health_parser = agent_sub.add_parser("health")
    agent_health_parser.add_argument("--backend", default=None)
    agent_health_parser.add_argument("--model", default=None)
    agent_health_parser.add_argument("--endpoint", default=None)

    agent_run_parser = agent_sub.add_parser("run")
    agent_run_parser.add_argument("--prompt", required=True)
    agent_run_parser.add_argument("--backend", default=None)
    agent_run_parser.add_argument("--model", default=None)
    agent_run_parser.add_argument("--endpoint", default=None)
    agent_run_parser.add_argument("--format", default=None)

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
    if args.command == "agent":
        if args.agent_command == "health":
            agent = _get_configured_agent(args.backend, args.model, args.endpoint)
            health = agent.health_check()
            print(json.dumps(asdict(health), indent=2, ensure_ascii=False))
            return 0 if health.healthy else 1
        if args.agent_command == "run":
            agent = _get_configured_agent(args.backend, args.model, args.endpoint)
            task = TaskInput(
                task_id="cli-direct-agent",
                instruction=args.prompt,
                context="",
                expected_format=args.format,
            )
            answer = agent.solve(task, args.prompt)
            print("Local Agent Answer:")
            print(answer.answer)
            print()
            print(f"Model: {answer.model_name}")
            print(f"Latency: {answer.latency_ms} ms")
            print(f"Remote tokens used: 0 (100% local)")
            print(f"Metadata: {json.dumps(answer.metadata, ensure_ascii=False)}")
            return 0
    return 1


def _get_configured_agent(
    backend: str | None, model: str | None, endpoint: str | None
) -> LocalAgent:
    base_agent = create_local_agent_from_env()
    config = base_agent.config
    if backend:
        config.backend = backend
    if model:
        config.model_name = model
    if endpoint:
        config.endpoint = endpoint
    return LocalAgent(config)


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
