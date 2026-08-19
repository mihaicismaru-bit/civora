#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"


def load_suite():
    path = EUCONS / "adversarial" / "adversarial_suite.py"
    spec = importlib.util.spec_from_file_location("e26_adversarial", path)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load E26 adversarial suite")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    suite = load_suite()
    contract = json.loads((EUCONS / "adversarial" / "adversarial_contract.json").read_text(encoding="utf-8"))
    first = suite.run_suite(contract)
    second = suite.run_suite(contract)

    if first != second:
        raise SystemExit("E26 repeated synthetic suite is not deterministic")
    if first["scenario_count"] != len(suite.CANONICAL_SCENARIOS) or first["scenario_count"] != 16:
        raise SystemExit("E26 scenario coverage drift")
    if [row["scenario_id"] for row in first["scenarios"]] != suite.CANONICAL_SCENARIOS:
        raise SystemExit("E26 canonical scenario order drift")
    if any(row["status"] != "PASS" for row in first["scenarios"]):
        raise SystemExit("E26 scenario did not pass safely")
    if first["production_side_effects_enabled"] is not False:
        raise SystemExit("E26 activated production side effects")
    if not re.fullmatch(r"[0-9a-f]{64}", first["suite_sha256"]):
        raise SystemExit("E26 suite digest invalid")
    body = {key: value for key, value in first.items() if key != "suite_sha256"}
    if first["suite_sha256"] != suite.digest_json(body):
        raise SystemExit("E26 suite digest mismatch")

    by_id = {row["scenario_id"]: row for row in first["scenarios"]}
    expected = {
        "STALE_OPEN_OPPORTUNITY_HOLD": "HOLD_SOURCE_STATE",
        "SPAM_HONEYPOT_REJECTED": "REJECTED",
        "INVALID_EMAIL_REJECTED": "REJECTED",
        "MISSING_PROVENANCE_OFFER_REJECTED": "REJECTED",
        "MISSING_PRICING_HUMAN_REQUIRED": "HUMAN_REQUIRED",
        "DUPLICATE_CONFLICT_HOLD": "HOLD_DUPLICATE_CONFLICT",
        "DUPLICATE_SAME_KEY_COLLAPSED": "COLLAPSED",
        "ORPHAN_PREPARE_DISCARDED": "DISCARD_ORPHAN_PREPARE",
        "STALE_LEASE_RESUME": "RESUME_AFTER_STALE_LEASE",
        "LINKEDIN_OUTAGE_RETRY": "RETRY",
        "FACEBOOK_OUTAGE_EXHAUSTED_HOLD": "HOLD_RETRY_EXHAUSTED",
        "INDEXABLE_PREVIEW_REJECTED": "REJECTED",
        "PRODUCTION_DEPLOYMENT_REJECTED": "REJECTED",
        "SOCIAL_LIVE_GATES_CLOSED": "CLOSED",
        "EMAIL_LIVE_GATE_CLOSED": "CLOSED",
        "PII_REPOSITORY_WRITE_REJECTED": "REJECTED",
    }
    for scenario_id, outcome in expected.items():
        if by_id[scenario_id]["safe_outcome"] != outcome:
            raise SystemExit(f"E26 unsafe outcome drift: {scenario_id}")

    serialized = json.dumps(first, ensure_ascii=False).lower()
    for forbidden in ["example.invalid", "synthetic adversarial person", "access_token", "client_secret", "password=", '"published": true', '"sent": true']:
        if forbidden in serialized:
            raise SystemExit(f"E26 report leaked forbidden runtime material: {forbidden}")

    print(json.dumps({
        "status": "PASS",
        "phase": "E26",
        "scenarios": first["scenario_count"],
        "deterministic_replay": "PASS",
        "fail_closed": "PASS",
        "production_side_effects": "DISABLED"
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
