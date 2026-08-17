#!/usr/bin/env python3
"""PRS-057 acceptance: dashboard closure stays distinct from failure-recovery readiness."""
from __future__ import annotations

import json
from copy import deepcopy

from reconciliation_engine import REQUIRED_FRESH_GATES, reconcile

INSTANCE_ID = "synthetic-instance"
NAMESPACE = "instance/synthetic-instance"
DELIVERABLE_FAMILY = "operational_control"
DASHBOARD = "operational_dashboard"
FAILURE_RECOVERY = "failure_recovery"
DELIVERABLES = (DASHBOARD, FAILURE_RECOVERY)
AGGREGATE_CAPABILITY_ID = f"{NAMESPACE}:capability:dashboard-failure-recovery"
MAIN = "f" * 40


def _capability_id(deliverable: str) -> str:
    return f"{NAMESPACE}:capability:{DELIVERABLE_FAMILY}:{deliverable}"


def _capability(deliverable: str) -> dict:
    capability_id = _capability_id(deliverable)
    return {
        "capability_id": capability_id,
        "instance_id": INSTANCE_ID,
        "persistence_namespace": NAMESPACE,
        "deliverable_family": DELIVERABLE_FAMILY,
        "deliverable": deliverable,
        "desired_state": "READY",
        "code_state": "PARTIAL",
        "runtime_state": "UNKNOWN",
        "external_state": "NOT_APPLICABLE",
        "priority": "P1",
        "next_action": (
            "provide independent verifiable operational dashboard evidence"
            if deliverable == DASHBOARD
            else "provide independent failure-recovery readiness evidence"
        ),
        "acceptance_test": (
            "an operational dashboard is independently verifiable"
            if deliverable == DASHBOARD
            else "failure recovery has independent merged readiness evidence"
        ),
        "rollback": "restore the last verified namespaced operational-control state",
    }


def _backlog(deliverable: str) -> dict:
    capability_id = _capability_id(deliverable)
    return {
        "backlog_id": f"capability:{capability_id}",
        "priority": "P1",
        "capability_id": capability_id,
        "instance_id": INSTANCE_ID,
        "persistence_namespace": NAMESPACE,
        "deliverable_family": DELIVERABLE_FAMILY,
        "deliverable": deliverable,
        "exact_action": (
            "provide independent verifiable operational dashboard evidence"
            if deliverable == DASHBOARD
            else "provide independent failure-recovery readiness evidence"
        ),
        "dependency": "INDEPENDENT_DELIVERABLE_EVIDENCE",
        "acceptance_test": (
            "an operational dashboard is independently verifiable"
            if deliverable == DASHBOARD
            else "failure recovery has independent merged readiness evidence"
        ),
        "rollback": "restore the last verified namespaced operational-control state",
        "state": "TODO",
    }


def _payload(*, dashboard_ready: bool, recovery_ready: bool) -> dict:
    repository_capabilities = {
        _capability_id(DASHBOARD): {
            "code_state": "READY" if dashboard_ready else "PARTIAL",
            "runtime_state": "OPERATIONAL_PANEL_VERIFIED" if dashboard_ready else "HEALTH_WORKFLOWS_EXIST",
            "evidence": (
                [
                    "contract:operational-dashboard",
                    f"instance:{INSTANCE_ID}",
                    "readback:synthetic-dashboard-verifiable",
                ]
                if dashboard_ready
                else [
                    f"instance:{INSTANCE_ID}",
                    "runtime:health-workflows-exist",
                    "dashboard-readback:absent",
                ]
            ),
        },
        _capability_id(FAILURE_RECOVERY): {
            "code_state": "READY" if recovery_ready else "PARTIAL",
            "runtime_state": "RECOVERY_ACTIVE" if recovery_ready else "RECOVERY_PARTIAL",
            "evidence": (
                [
                    "contract:failure-recovery",
                    f"instance:{INSTANCE_ID}",
                    "main-commit:synthetic-recovery",
                ]
                if recovery_ready
                else [f"instance:{INSTANCE_ID}", "recovery:synthetic-incomplete"]
            ),
        },
    }
    external_capabilities = {
        _capability_id(deliverable): {"external_state": "NOT_APPLICABLE"}
        for deliverable in DELIVERABLES
    }
    return {
        "schema_version": 1,
        "scope_id": "synthetic-product",
        "instance_id": INSTANCE_ID,
        "persistence_namespace": NAMESPACE,
        "persisted": {
            "main_head": MAIN,
            "decisions": [],
            "capabilities": [_capability(deliverable) for deliverable in DELIVERABLES],
            "backlog": [_backlog(deliverable) for deliverable in DELIVERABLES],
        },
        "repository": {
            "main_head": MAIN,
            "scope_classification": "NO_SCOPE_CHANGE",
            "decisions": {},
            "capabilities": repository_capabilities,
        },
        "external": {"decisions": {}, "capabilities": external_capabilities},
        "health_gates": {gate: True for gate in REQUIRED_FRESH_GATES},
    }


def _rows(result: dict) -> dict[str, dict]:
    return {row["deliverable"]: row for row in result["capabilities"]}


def _active_backlog(result: dict) -> set[str]:
    return {
        row["deliverable"]
        for row in result["development_backlog"]
        if row.get("deliverable_family") == DELIVERABLE_FAMILY
    }


def _assert_common(result: dict) -> None:
    assert len(result["capabilities"]) == len(DELIVERABLES)
    assert {row["deliverable"] for row in result["capabilities"]} == set(DELIVERABLES)
    assert all(row["instance_id"] == INSTANCE_ID for row in result["capabilities"])
    assert all(row["persistence_namespace"] == NAMESPACE for row in result["capabilities"])
    assert all(row["deliverable_family"] == DELIVERABLE_FAMILY for row in result["capabilities"])
    assert all(row["capability_id"] != AGGREGATE_CAPABILITY_ID for row in result["capabilities"])


def main() -> int:
    # Existing health/recovery machinery can be READY while the actual dashboard
    # remains an independently open deliverable. This is the PRS-057 core rule.
    recovery_only_payload = _payload(dashboard_ready=False, recovery_ready=True)
    recovery_only_before = deepcopy(recovery_only_payload)
    recovery_only_result = reconcile(recovery_only_payload)
    assert recovery_only_payload == recovery_only_before
    _assert_common(recovery_only_result)

    recovery_only_rows = _rows(recovery_only_result)
    assert recovery_only_rows[FAILURE_RECOVERY]["status"] == "IMPLEMENTED"
    assert recovery_only_rows[FAILURE_RECOVERY]["gap"] is None
    assert recovery_only_rows[DASHBOARD]["status"] == "ACTIVE_UNIMPLEMENTED"
    assert recovery_only_rows[DASHBOARD]["gap"] == "CODE_GAP"
    assert recovery_only_rows[DASHBOARD]["runtime_state"] == "HEALTH_WORKFLOWS_EXIST"
    assert _active_backlog(recovery_only_result) == {DASHBOARD}

    # Only independent dashboard evidence may close the dashboard deliverable.
    complete_payload = _payload(dashboard_ready=True, recovery_ready=True)
    complete_before = deepcopy(complete_payload)
    complete_result = reconcile(complete_payload)
    assert complete_payload == complete_before
    _assert_common(complete_result)

    complete_rows = _rows(complete_result)
    assert complete_rows[DASHBOARD]["status"] == "IMPLEMENTED"
    assert complete_rows[DASHBOARD]["gap"] is None
    assert complete_rows[FAILURE_RECOVERY]["status"] == "IMPLEMENTED"
    assert _active_backlog(complete_result) == set()

    print(json.dumps({
        "status": "PASS",
        "prs": "PRS-057",
        "instance_id": INSTANCE_ID,
        "persistence_namespace": NAMESPACE,
        "deliverable_family": DELIVERABLE_FAMILY,
        "deliverables": list(DELIVERABLES),
        "health_workflows_do_not_close_dashboard": True,
        "failure_recovery_independent": True,
        "dashboard_requires_independent_evidence": True,
        "aggregate_capability_absent": True,
        "repository_input_unchanged": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
