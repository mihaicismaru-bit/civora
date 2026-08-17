#!/usr/bin/env python3
"""Validate the generic CIVORA reconciliation trigger contract (PRS-037)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RECONCILIATION_WORKFLOW = ROOT / ".github" / "workflows" / "civora-persistence-reconciliation.yml"
SCOPE_DRIFT_WORKFLOW = ROOT / ".github" / "workflows" / "civora-scope-drift.yml"
SCOPE_CONFIG = Path(__file__).with_name("repository_scope.json")
RECONCILIATION_WORKFLOW_PATH = ".github/workflows/civora-persistence-reconciliation.yml"

REQUIRED_EVENTS = {
    "MAIN_MERGE",
    "CAPABILITY_REGISTRY_CHANGE",
    "DEPLOYMENT_STATE_CHANGE",
    "EXTERNAL_BLOCKER_CLOSED",
    "CANON_CHANGE",
}
ALLOWED_SCOPE_OUTCOMES = {
    "NO_SCOPE_CHANGE",
    "RUNTIME_REFRESH_ONLY",
    "STRUCTURAL_RECONCILIATION",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("trigger contract must be an object")
    return value


def validate(contract: dict[str, Any]) -> None:
    if contract.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    if contract.get("scope") != "CORE_GENERIC":
        raise ValueError("scope must be CORE_GENERIC")

    policy = contract.get("policy")
    if not isinstance(policy, dict):
        raise ValueError("policy must be an object")
    for key in (
        "default_fail_closed",
        "credentials_forbidden",
        "historical_checkpoint_mutation_forbidden",
        "ready_local_never_implies_live_external",
        "scope_classifier_required_for_main_merge",
        "instance_namespace_required_for_instance_state",
    ):
        if policy.get(key) is not True:
            raise ValueError(f"policy.{key} must be true")

    events = contract.get("events")
    if not isinstance(events, list):
        raise ValueError("events must be an array")
    by_type: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(events):
        if not isinstance(raw, dict):
            raise ValueError(f"events[{index}] must be an object")
        event_type = str(raw.get("event_type") or "")
        if not event_type:
            raise ValueError(f"events[{index}] missing event_type")
        if event_type in by_type:
            raise ValueError(f"duplicate event_type={event_type}")
        if raw.get("persistence_refresh_required") is not True:
            raise ValueError(f"{event_type} must require persistence refresh")
        evidence = raw.get("minimum_evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(f"{event_type} requires non-empty minimum_evidence")
        dedupe = raw.get("dedupe_identity")
        if not isinstance(dedupe, list) or not dedupe:
            raise ValueError(f"{event_type} requires non-empty dedupe_identity")
        if not str(raw.get("fail_closed_behavior") or "").strip():
            raise ValueError(f"{event_type} requires fail_closed_behavior")
        by_type[event_type] = raw

    missing = REQUIRED_EVENTS - set(by_type)
    extra = set(by_type) - REQUIRED_EVENTS
    if missing or extra:
        raise ValueError(f"unexpected event set; missing={sorted(missing)} extra={sorted(extra)}")

    main_merge = by_type["MAIN_MERGE"]
    if main_merge.get("reconciliation_required") != "SCOPE_CLASSIFIER_DECIDES":
        raise ValueError("MAIN_MERGE must delegate reconciliation severity to scope classifier")
    if main_merge.get("scope_classifier_required") is not True:
        raise ValueError("MAIN_MERGE must require scope classifier")
    outcomes = set(main_merge.get("allowed_scope_outcomes") or [])
    if outcomes != ALLOWED_SCOPE_OUTCOMES:
        raise ValueError("MAIN_MERGE allowed_scope_outcomes mismatch")

    for event_type in REQUIRED_EVENTS - {"MAIN_MERGE"}:
        if by_type[event_type].get("reconciliation_required") is not True:
            raise ValueError(f"{event_type} must require reconciliation")

    deployment_evidence = set(by_type["DEPLOYMENT_STATE_CHANGE"].get("minimum_evidence") or [])
    if "remote_ack_or_readback_when_live_is_claimed" not in deployment_evidence:
        raise ValueError("DEPLOYMENT_STATE_CHANGE must require remote LIVE readback evidence")

    serialized = json.dumps(contract, ensure_ascii=False).lower()
    if "valcea" in serialized or "vâlcea" in serialized:
        raise ValueError("CORE_GENERIC trigger contract contains instance-specific Vâlcea hardcoding")
    for forbidden in ("access_token", "password", "secret_value", "api_key"):
        if forbidden in serialized:
            raise ValueError(f"credential-like field forbidden in trigger contract: {forbidden}")


def validate_executable_wiring() -> None:
    """Fail closed if the declarative MAIN_MERGE trigger is not executable."""
    reconciliation_workflow = RECONCILIATION_WORKFLOW.read_text(encoding="utf-8")
    scope_workflow = SCOPE_DRIFT_WORKFLOW.read_text(encoding="utf-8")
    scope_config = _load(SCOPE_CONFIG)

    required_reconciliation_fragments = (
        "workflow_run:",
        'workflows: ["CIVORA Scope Drift"]',
        "types: [completed]",
        "github.event.workflow_run.head_sha",
        "github.event.workflow_run.conclusion == 'success'",
        "github.event.workflow_run.head_branch == 'main'",
    )
    for fragment in required_reconciliation_fragments:
        if fragment not in reconciliation_workflow:
            raise ValueError(f"reconciliation workflow missing executable MAIN_MERGE wiring: {fragment}")

    if RECONCILIATION_WORKFLOW_PATH not in scope_workflow:
        raise ValueError("scope-drift workflow does not observe reconciliation workflow changes")

    include = scope_config.get("include")
    if not isinstance(include, list) or RECONCILIATION_WORKFLOW_PATH not in include:
        raise ValueError("reconciliation workflow is outside CIVORA structural scope")


def self_test(path: Path) -> None:
    contract = _load(path)
    validate(contract)
    validate_executable_wiring()

    duplicate = json.loads(json.dumps(contract))
    duplicate["events"].append(dict(duplicate["events"][0]))
    try:
        validate(duplicate)
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate event_type must fail closed")

    missing_remote = json.loads(json.dumps(contract))
    deployment = next(row for row in missing_remote["events"] if row["event_type"] == "DEPLOYMENT_STATE_CHANGE")
    deployment["minimum_evidence"] = ["deployment_target_ref", "observed_state"]
    try:
        validate(missing_remote)
    except ValueError:
        pass
    else:
        raise AssertionError("deployment LIVE evidence regression was not rejected")

    hardcoded_instance = json.loads(json.dumps(contract))
    hardcoded_instance["events"][0]["example_instance"] = "valcea"
    try:
        validate(hardcoded_instance)
    except ValueError:
        pass
    else:
        raise AssertionError("instance-specific hardcoding in CORE_GENERIC must fail closed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path(__file__).with_name("reconciliation_triggers.json"),
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    contract = _load(args.contract)
    validate(contract)
    validate_executable_wiring()
    if args.self_test:
        self_test(args.contract)
    print("PASS: CIVORA reconciliation trigger contract and executable wiring are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
