#!/usr/bin/env python3
"""PRS-058 acceptance: self-improvement persistence stays component-scoped and reversible."""
from __future__ import annotations

import json
from copy import deepcopy

from reconciliation_engine import REQUIRED_FRESH_GATES, reconcile

INSTANCE_ID = "synthetic-instance"
NAMESPACE = "instance/synthetic-instance"
FEATURE_FAMILY = "self_improvement"
COMPONENTS = (
    "metrics_harvest",
    "feedback",
    "ranking_influence",
    "controlled_change",
    "validation",
    "rollback",
)
INITIAL_READY = {"metrics_harvest", "feedback"}
INITIAL_PENDING = set(COMPONENTS) - INITIAL_READY
AGGREGATE_CAPABILITY_ID = f"{NAMESPACE}:capability:{FEATURE_FAMILY}"
MAIN = "9" * 40


def _capability_id(component: str) -> str:
    return f"{NAMESPACE}:capability:{FEATURE_FAMILY}:{component}"


def _capability(component: str) -> dict:
    capability_id = _capability_id(component)
    return {
        "capability_id": capability_id,
        "instance_id": INSTANCE_ID,
        "persistence_namespace": NAMESPACE,
        "feature_family": FEATURE_FAMILY,
        "component": component,
        "desired_state": "READY",
        "code_state": "PARTIAL",
        "runtime_state": "UNKNOWN",
        "external_state": "NOT_APPLICABLE",
        "priority": "P2",
        "next_action": f"close independent self-improvement evidence for {component}",
        "acceptance_test": f"{component} has independent merged readiness evidence",
        "rollback": "restore the last verified namespaced self-improvement component state",
    }


def _backlog(component: str) -> dict:
    capability_id = _capability_id(component)
    return {
        "backlog_id": f"capability:{capability_id}",
        "priority": "P2",
        "capability_id": capability_id,
        "instance_id": INSTANCE_ID,
        "persistence_namespace": NAMESPACE,
        "feature_family": FEATURE_FAMILY,
        "component": component,
        "exact_action": f"close independent self-improvement evidence for {component}",
        "dependency": "COMPONENT_EVIDENCE",
        "acceptance_test": f"{component} has its own merged readiness evidence",
        "rollback": "restore the last verified namespaced self-improvement component state",
        "state": "TODO",
    }


def _payload(ready_components: set[str]) -> dict:
    repository_capabilities = {}
    external_capabilities = {}
    for component in COMPONENTS:
        capability_id = _capability_id(component)
        ready = component in ready_components
        repository_capabilities[capability_id] = {
            "code_state": "READY" if ready else "PARTIAL",
            "runtime_state": "ACTIVE" if ready else "PARTIAL",
            "evidence": ([f"contract:self-improvement-{component}", f"instance:{INSTANCE_ID}", f"main-commit:synthetic-{component}"] if ready else [f"instance:{INSTANCE_ID}", f"component:{component}", "state:synthetic-incomplete"]),
        }
        external_capabilities[capability_id] = {"external_state": "NOT_APPLICABLE"}
    return {
        "schema_version": 1,
        "scope_id": "synthetic-product",
        "instance_id": INSTANCE_ID,
        "persistence_namespace": NAMESPACE,
        "persisted": {"main_head": MAIN, "decisions": [], "capabilities": [_capability(component) for component in COMPONENTS], "backlog": [_backlog(component) for component in sorted(INITIAL_PENDING)]},
        "repository": {"main_head": MAIN, "scope_classification": "NO_SCOPE_CHANGE", "decisions": {}, "capabilities": repository_capabilities},
        "external": {"decisions": {}, "capabilities": external_capabilities},
        "health_gates": {gate: True for gate in REQUIRED_FRESH_GATES},
    }


def _rows(result: dict) -> dict[str, dict]:
    return {row["component"]: row for row in result["capabilities"]}


def _active_backlog_components(result: dict) -> set[str]:
    return {row["component"] for row in result["development_backlog"] if row.get("feature_family") == FEATURE_FAMILY}


def _assert_common(result: dict) -> None:
    assert len(result["capabilities"]) == len(COMPONENTS)
    assert {row["component"] for row in result["capabilities"]} == set(COMPONENTS)
    assert all(row["instance_id"] == INSTANCE_ID for row in result["capabilities"])
    assert all(row["persistence_namespace"] == NAMESPACE for row in result["capabilities"])
    assert all(row["feature_family"] == FEATURE_FAMILY for row in result["capabilities"])
    assert all(row["capability_id"] != AGGREGATE_CAPABILITY_ID for row in result["capabilities"])


def main() -> int:
    partial_payload = _payload(set(INITIAL_READY))
    partial_before = deepcopy(partial_payload)
    partial_result = reconcile(partial_payload)
    assert partial_payload == partial_before
    _assert_common(partial_result)
    partial_rows = _rows(partial_result)
    for component in INITIAL_READY:
        assert partial_rows[component]["status"] == "IMPLEMENTED"
        assert partial_rows[component]["gap"] is None
    for component in INITIAL_PENDING:
        assert partial_rows[component]["status"] == "ACTIVE_UNIMPLEMENTED"
        assert partial_rows[component]["gap"] == "CODE_GAP"
    assert _active_backlog_components(partial_result) == INITIAL_PENDING

    ranked_ready = set(INITIAL_READY) | {"ranking_influence"}
    ranked_payload = _payload(ranked_ready)
    ranked_before = deepcopy(ranked_payload)
    ranked_result = reconcile(ranked_payload)
    assert ranked_payload == ranked_before
    _assert_common(ranked_result)
    ranked_rows = _rows(ranked_result)
    assert ranked_rows["ranking_influence"]["status"] == "IMPLEMENTED"
    assert ranked_rows["controlled_change"]["status"] == "ACTIVE_UNIMPLEMENTED"
    assert ranked_rows["validation"]["status"] == "ACTIVE_UNIMPLEMENTED"
    assert ranked_rows["rollback"]["status"] == "ACTIVE_UNIMPLEMENTED"
    assert _active_backlog_components(ranked_result) == {"controlled_change", "validation", "rollback"}

    change_ready = ranked_ready | {"controlled_change"}
    change_payload = _payload(change_ready)
    change_before = deepcopy(change_payload)
    change_result = reconcile(change_payload)
    assert change_payload == change_before
    _assert_common(change_result)
    change_rows = _rows(change_result)
    assert change_rows["controlled_change"]["status"] == "IMPLEMENTED"
    assert change_rows["validation"]["status"] == "ACTIVE_UNIMPLEMENTED"
    assert change_rows["rollback"]["status"] == "ACTIVE_UNIMPLEMENTED"
    assert _active_backlog_components(change_result) == {"validation", "rollback"}

    complete_payload = _payload(set(COMPONENTS))
    complete_before = deepcopy(complete_payload)
    complete_result = reconcile(complete_payload)
    assert complete_payload == complete_before
    _assert_common(complete_result)
    complete_rows = _rows(complete_result)
    assert all(complete_rows[component]["status"] == "IMPLEMENTED" for component in COMPONENTS)
    assert all(complete_rows[component]["gap"] is None for component in COMPONENTS)
    assert _active_backlog_components(complete_result) == set()

    print(json.dumps({"status": "PASS", "prs": "PRS-058", "instance_id": INSTANCE_ID, "persistence_namespace": NAMESPACE, "feature_family": FEATURE_FAMILY, "components": list(COMPONENTS), "metrics_feedback_do_not_close_loop": True, "ranking_influence_independent": True, "controlled_change_does_not_bypass_validation_or_rollback": True, "aggregate_capability_absent": True, "repository_input_unchanged": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
