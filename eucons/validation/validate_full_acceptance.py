#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    engine = load_module("e27_acceptance", EUCONS / "acceptance" / "full_acceptance.py")
    contract = json.loads((EUCONS / "acceptance" / "full_acceptance_contract.json").read_text(encoding="utf-8"))
    receipt = engine.build_full_acceptance(contract)

    if receipt["status"] != "PASS" or receipt["production_side_effects_enabled"] is not False:
        raise SystemExit("E27 terminal acceptance did not pass safely")
    if [row["phase"] for row in receipt["prerequisites"]] != [f"E{i:02d}" for i in range(27)]:
        raise SystemExit("E27 prerequisite receipt chain incomplete")
    if receipt["lineage"]["source_product"] != "PARTENER.EU":
        raise SystemExit("E27 verified opportunity source lineage drift")
    if receipt["lineage"]["match_to_crm"] != "PASS" or receipt["lineage"]["crm_to_offer"] != "PASS":
        raise SystemExit("E27 commercial cross-engine lineage failed")
    if receipt["commercial"]["match_state"] != "MATCH_CANDIDATE" or receipt["commercial"]["crm_stage"] != "OFFER":
        raise SystemExit("E27 commercial journey incomplete")
    if receipt["commercial"]["pricing_state"] != "HUMAN_REQUIRED" or receipt["commercial"]["automatic_send_allowed"] is not False:
        raise SystemExit("E27 pricing/send gate failed open")

    distribution = receipt["distribution"]
    if distribution["editorial_ready"] < 1 or distribution["linkedin_items"] < 1 or distribution["facebook_items"] < 1:
        raise SystemExit("E27 distribution journey incomplete")
    if distribution["email_decision"] != "READY" or distribution["email_dispatch_state"] != "EMAIL_OUTBOX_READY_MAILBOX_AUTH_REQUIRED":
        raise SystemExit("E27 email outbox authorization state drift")

    analytics = receipt["analytics"]
    if analytics["event_names"] != contract["required_analytics_events"] or analytics["transport"] != "DRY_RUN_ONLY":
        raise SystemExit("E27 analytics acceptance drift")
    if analytics["event_count"] != len(contract["required_analytics_events"]):
        raise SystemExit("E27 analytics event count mismatch")
    if receipt["adversarial"]["scenario_count"] != 16 or receipt["adversarial"]["fail_closed"] != "PASS":
        raise SystemExit("E27 adversarial acceptance drift")
    if not all(value == "CLOSED" for value in receipt["external_gates"].values()):
        raise SystemExit("E27 external gate opened before owner handoff")

    hashes = [
        receipt["lineage"]["lead_sha256"],
        receipt["lineage"]["offer_sha256"],
        distribution["linkedin_sha256"],
        distribution["facebook_sha256"],
        distribution["email_sha256"],
        distribution["editorial_sha256"],
        analytics["stream_sha256"],
        analytics["receipt_sha256"],
        receipt["adversarial"]["suite_sha256"],
        receipt["replay_sha256"],
        receipt["journey_sha256"],
        receipt["receipt_hash"],
    ] + [row["sha256"] for row in receipt["prerequisites"]]
    if not all(re.fullmatch(r"[0-9a-f]{64}", value or "") for value in hashes):
        raise SystemExit("E27 acceptance hash manifest invalid")

    body = {key: value for key, value in receipt.items() if key != "receipt_hash"}
    if receipt["receipt_hash"] != engine.digest_json(body):
        raise SystemExit("E27 immutable receipt digest mismatch")
    serialized = json.dumps(receipt, ensure_ascii=False).lower()
    for forbidden in ["example.invalid", "synthetic preview person", "preview.e25@"]:
        if forbidden in serialized:
            raise SystemExit("E27 acceptance receipt leaked synthetic personal data")

    print(json.dumps({
        "status": "PASS",
        "phase": "E27",
        "prerequisite_phases": len(receipt["prerequisites"]),
        "commercial_lineage": "PASS",
        "distribution": "PASS",
        "analytics_events": analytics["event_count"],
        "adversarial_scenarios": receipt["adversarial"]["scenario_count"],
        "deterministic_replay": "PASS",
        "production_side_effects": "DISABLED",
        "external_gates": "CLOSED"
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
