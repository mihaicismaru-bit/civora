#!/usr/bin/env python3
"""PRS-056 acceptance: local-places persistence is split into independent sub-capabilities."""
from __future__ import annotations

import json
from copy import deepcopy

from reconciliation_engine import REQUIRED_FRESH_GATES, reconcile

INSTANCE_ID = "synthetic-instance"
NAMESPACE = "instance/synthetic-instance"
FEATURE_FAMILY = "local_places"
SUBCAPABILITIES = (
    "ingest",
    "reconciliation",
    "public_catalogue",
    "operators",
    "menus_prices",
    "local_creators",
    "publication",
)
INITIAL_READY = {
    "ingest",
    "reconciliation",
    "public_catalogue",
    "operators",
}
INITIAL_PENDING = set(SUBCAPABILITIES) - INITIAL_READY
AGGREGATE_CAPABILITY_ID = f"{NAMESPACE}:capability:{FEATURE_FAMILY}"
MAIN = "e" * 40


def _capability_id(subcapability: str) -> str:
    return f"{NAMESPACE}:capability:{FEATURE_FAMILY}:{subcapability}"


def _capability(subcapability: str) -> dict:
    capability_id = _capability_id(subcapability)
    return {
        "capability_id": capability_id,
        "instance_id": INSTANCE_ID,
        "persistence_namespace": NAMESPACE,
        "feature_family": FEATURE_FAMILY,
        "subcapability": subcapability,
        "desired_state": "READY",
        "code_state": "PARTIAL",
        "runtime_state": "UNKNOWN",
        "external_state": "NOT_APPLICABLE",
        "priority": "P1",
        "next_action": f"close independent local-places evidence for {subcapability}",
        "acceptance_test": f"{subcapability} has independent merged readiness evidence",
        "rollback": "restore the last verified namespaced sub-capability state",
    }


def _backlog(subcapability: str) -> dict:
    capability_id = _capability_id(subcapability)
    return {
        "backlog_id": f"capability:{capability_id}",
        "priority": "P1",
        "capability_id": capability_id,
        "instance_id": INSTANCE_ID,
        "persistence_namespace": NAMESPACE,
        "feature_family": FEATURE_FAMILY,
        "subcapability": subcapability,
        "exact_action": f"close independent local-places evidence for {subcapability}",
        "dependency": "SUBCAPABILITY_EVIDENCE",
        "acceptance_test": f"{subcapability} has its own merged readiness evidence",
        "rollback": "restore the last verified namespaced sub-capability state",
        "state": "TODO",
    }


def _payload(ready_subcapabilities: set[str]) -> dict:
    repository_capabilities = {}
    external_capabilities = {}
    for subcapability in SUBCAPABILITIES:
        capability_id = _capability_id(subcapability)
        ready = subcapability in ready_subcapabilities
        repository_capabilities[capability_id] = {
            "code_state": "READY" if ready else "PARTIAL",
            "runtime_state": "ACTIVE" if ready else "PARTIAL",
            "evidence": (
                [
                    f"contract:local-places-{subcapability}",
                    f"instance:{INSTANCE_ID}",
                    f"main-commit:synthetic-{subcapability}",
                ]
                if ready
                else [
                    f"instance:{INSTANCE_ID}",
                    f"subcapability:{subcapability}",
                    "state:synthetic-incomplete",
                ]
            ),
        }
        external_capabilities[capability_id] = {"external_state": "NOT_APPLICABLE"}

    return {
        "schema_version": 1,
        "scope_id": "synthetic-product",
        "instance_id": INSTANCE_ID,
        "persistence_namespace": NAMESPACE,
        "persisted": {
            "main_head": MAIN,
            "decisions": [],
            "capabilities": [_capability(subcapability) for subcapability in SUBCAPABILITIES],
            "backlog": [_backlog(subcapability) for subcapability in sorted(INITIAL_PENDING)],
        },
        "repository": {
            "main_head": MAIN,
            "scope_classification": "NO_SCOPE_CHANGE",
            "decisions": {},
            "capabilities": repository_capabilities,
        },
        "external": {
            "decisions": {},
            "capabilities": external_capabilities,
        },
        "health_gates": {gate: True for gate in REQUIRED_FRESH_GATES},
    }


def _capability_rows(result: dict) -> dict[str, dict]:
    return {row["subcapability"]: row for row in result["capabilities"]}


def _active_backlog_subcapabilities(result: dict) -> set[str]:
    return {
        row["subcapability"]
        for row in result["development_backlog"]
        if row.get("feature_family") == FEATURE_FAMILY
    }


def _assert_common(result: dict) -> None:
    assert len(result["capabilities"]) == len(SUBCAPABILITIES)
    assert all(row["instance_id"] == INSTANCE_ID for row in result["capabilities"])
    assert all(row["persistence_namespace"] == NAMESPACE for row in result["capabilities"])
    assert all(row["feature_family"] == FEATURE_FAMILY for row in result["capabilities"])
    assert {row["subcapability"] for row in result["capabilities"]} == set(SUBCAPABILITIES)
    assert all(row["capability_id"] != AGGREGATE_CAPABILITY_ID for row in result["capabilities"])


def main() -> int:
    partial_payload = _payload(set(INITIAL_READY))
    partial_before = deepcopy(partial_payload)
    partial_result = reconcile(partial_payload)
    assert partial_payload == partial_before
    _assert_common(partial_result)

    partial_rows = _capability_rows(partial_result)
    for subcapability in INITIAL_READY:
        assert partial_rows[subcapability]["status"] == "IMPLEMENTED"
        assert partial_rows[subcapability]["gap"] is None
    for subcapability in INITIAL_PENDING:
        assert partial_rows[subcapability]["status"] == "ACTIVE_UNIMPLEMENTED"
        assert partial_rows[subcapability]["gap"] == "CODE_GAP"
    assert _active_backlog_subcapabilities(partial_result) == INITIAL_PENDING

    advanced_ready = set(INITIAL_READY) | {"menus_prices"}
    advanced_payload = _payload(advanced_ready)
    advanced_before = deepcopy(advanced_payload)
    advanced_result = reconcile(advanced_payload)
    assert advanced_payload == advanced_before
    _assert_common(advanced_result)

    advanced_rows = _capability_rows(advanced_result)
    assert advanced_rows["menus_prices"]["status"] == "IMPLEMENTED"
    assert advanced_rows["menus_prices"]["gap"] is None
    assert _active_backlog_subcapabilities(advanced_result) == {"local_creators", "publication"}
    assert advanced_rows["local_creators"]["status"] == "ACTIVE_UNIMPLEMENTED"
    assert advanced_rows["publication"]["status"] == "ACTIVE_UNIMPLEMENTED"

    complete_payload = _payload(set(SUBCAPABILITIES))
    complete_before = deepcopy(complete_payload)
    complete_result = reconcile(complete_payload)
    assert complete_payload == complete_before
    _assert_common(complete_result)

    complete_rows = _capability_rows(complete_result)
    assert all(complete_rows[subcapability]["status"] == "IMPLEMENTED" for subcapability in SUBCAPABILITIES)
    assert all(complete_rows[subcapability]["gap"] is None for subcapability in SUBCAPABILITIES)
    assert _active_backlog_subcapabilities(complete_result) == set()

    print(json.dumps({
        "status": "PASS",
        "prs": "PRS-056",
        "instance_id": INSTANCE_ID,
        "persistence_namespace": NAMESPACE,
        "feature_family": FEATURE_FAMILY,
        "subcapabilities": list(SUBCAPABILITIES),
        "initial_ready": sorted(INITIAL_READY),
        "initial_pending": sorted(INITIAL_PENDING),
        "independent_progression_verified": True,
        "aggregate_capability_absent": True,
        "repository_input_unchanged": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
