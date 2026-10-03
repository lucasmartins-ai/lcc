#!/usr/bin/env python3
"""MSI 5-minute path: compile(task, context) -> context + receipt + sufficiency (offline).

No key, no network, no extra deps. Uses the deterministic planner +
mechanical compaction + bounded sufficiency restoration (``lcc.msi``).

Usage:  python3 examples/msi_quickstart.py
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, "src")

from lcc.msi import compile

TASK = "reduce mobile booking friction"

DOSSIER = (
    "The clinic booking widget loses 63 percent of mobile visitors before the second step.\n\n"
    "A quoted complaint carries the evidence: the patient wrote: the form erased everything\n"
    "when I tapped back on my phone, so I gave up and called instead.\n\n"
    "LOG 1: queue worker heartbeat ok in 554ms, backlog 287 jobs, retry budget untouched.\n\n"
    "LOG 2: cron job lead-sync finished with 366 records processed and 3377 ms elapsed.\n\n"
    "Chatter about office plants and coffee machines needing water daily without fail.\n\n"
    "The decline occurred after the mobile redesign shipped to all users in June.\n\n"
)


def main() -> None:
    result = compile(TASK, DOSSIER)
    print(f"task: {TASK}")
    print(f"provider: {result.provider_used} degraded={result.degraded}")
    print(f"sufficiency: {result.sufficiency}")
    plan = result.plan
    print(f"plan: {plan.model_class}/{plan.reasoning_budget} route={plan.route}")
    receipt = result.receipt
    print(f"receipt: {receipt.receipt_id} verification={receipt.verification_result}")
    print("--- compacted context ---")
    print(result.context)
    # Prove the receipt is schema-valid without printing all of it.
    receipt_d = result.receipt.to_spec_dict()
    assert receipt_d["schema_version"] == "inference-receipt/0.1", receipt_d.get("schema_version")
    assert receipt_d["task_id"], "receipt needs a task_id"
    print(f"receipt ok: {receipt_d['schema_version']} task={receipt_d['task_id']}")
    print(json.dumps({"sufficiency": result.sufficiency}, indent=2))


if __name__ == "__main__":
    main()
