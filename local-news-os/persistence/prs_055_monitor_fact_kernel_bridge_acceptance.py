#!/usr/bin/env python3
"""PRS-055 acceptance: monitor -> Fact Kernel bridge state is persisted per monitor."""
from __future__ import annotations

import json
from copy import deepcopy

from reconciliation_engine import REQUIRED_FRESH_GATES, reconcile

INSTANCE_ID = "synthetic-instance"
NAMESPACE = "instance/synthetic-instance"
READY_MONITOR = "monitor-alpha"
PENDING_MONITOR = "monitor-beta"
READY_BRIDGE_ID = f"{NAMESPACE}:capability:fact-kernel-bridge:{READY_MONITOR}"
PENDING_BRIDGE_ID = f"{NAMESPACE}:capability:fact-kernel-bridge:{PENDING_MONITOR}"
AGGREGATE_FACT_KERNEL_ID = f"{NAMESPACE}:capability:fact-kernel"
PENDING_BACKLOG_ID = f"capability:{PENDING_BRIDGE_ID}"
MAIN = "d" * 40


def _bridge(capability_id: str, monitor_id: str) -> dict:
    return {
        "capability_id": capability_id,
        "instance_id": INSTANCE_ID,
        "persistence_namespace": NAMESPACE,
        "monitor_id": monitor_id,
        "domain": "fact_kernel_monitor_bridge",
        "desired_state": "READY",
        "code_state": "PARTIAL",
        "runtime_state": "UNKNOWN",
        "external_state": "NOT_APPLICABLE",
        "priority": "P1",
        "next_action": f"close Fact Kernel bridge evidence for {monitor_id}",
        "acceptance_test": "this monitor has independent merged bridge evidence",
        "rollback": "restore the last verified per-monitor bridge state",
    }


def _payload(pending_code_state: str, pending_evidence: list[str]) -> dict:
    return {
        "schema_version": 1,
        "scope_id": "synthetic-product",
        "instance_id": INSTANCE_ID,
        "persistence_namespace": NAMESPACE,
        "persisted": {
            "main_head": MAIN,
            "decisions": [],
            "capabilities": [
                _bridge(READY_BRIDGE_ID, READY_MONITOR),
                _bridge(PENDING_BRIDGE_ID, PENDING_MONITOR),
            ],
            "backlog": [
                {
                    "backlog_id": PENDING_BACKLOG_ID,
                    "priority": "P1",
                    "capability_id": PENDING_BRIDGE_ID,
                    "instance_id": INSTANCE_ID,
                    "persistence_namespace": NAMESPACE,
                    "monitor_id": PENDING_MONITOR,
                    "exact_action": "close independent Fact Kernel bridge evidence for monitor-beta",
                    "dependency": "MONITOR_BRIDGE_EVIDENCE",
                    "acceptance_test": "monitor-beta has its own merged bridge evidence",
                    "rollback": "restore the last verified per-monitor bridge state",
                    "state": "TODO",
                }
            ],
        },
        "repository": {
            "main_head": MAIN,
            "scope_classification": "NO_SCOPE_CHANGE",
            "decisions": {},
            "capabilities": {
                READY_BRIDGE_ID: {
                    "code_state": "READY",
                    "runtime_state": "ACTIVE",
                    "evidence": [
                        "contract:fact-kernel-monitor-bridge",
                        "monitor:monitor-alpha",
                        "main-commit:synthetic-monitor-alpha",
                    ],
                },
                PENDING_BRIDGE_ID: {
                    "code_state": pending_code_state,
                    "runtime_state": "ACTIVE" if pending_code_state == "READY" else "PARTIAL",
                    "evidence": pending_evidence,
                },
            },
        },
        "external": {
            "decisions": {},
            "capabilities": {
                READY_BRIDGE_ID: {"external_state": "NOT_APPLICABLE"},
                PENDING_BRIDGE_ID: {"external_state": "NOT_APPLICABLE"},
            },
        },
        "health_gates": {gate: True for gate in REQUIRED_FRESH_GATES},
    }


def _capability(result: dict, capability_id: str) -> dict:
    return next(row for row in result["capabilities"] if row["capability_id"] == capability_id)


def main() -> int:
    partial_payload = _payload(
        "PARTIAL",
        ["monitor:monitor-beta", "bridge-state:synthetic-incomplete"],
    )
    partial_before = deepcopy(partial_payload)
    partial_result = reconcile(partial_payload)
    assert partial_payload == partial_before

    ready = _capability(partial_result, READY_BRIDGE_ID)
    pending = _capability(partial_result, PENDING_BRIDGE_ID)
    assert ready["status"] == "IMPLEMENTED"
    assert ready["gap"] is None
    assert ready["monitor_id"] == READY_MONITOR
    assert pending["status"] == "ACTIVE_UNIMPLEMENTED"
    assert pending["gap"] == "CODE_GAP"
    assert pending["monitor_id"] == PENDING_MONITOR
    assert ready["capability_id"] != pending["capability_id"]
    assert ready["persistence_namespace"] == NAMESPACE
    assert pending["persistence_namespace"] == NAMESPACE
    assert all(row["capability_id"] != AGGREGATE_FACT_KERNEL_ID for row in partial_result["capabilities"])

    active_pending_backlog = [
        row for row in partial_result["development_backlog"]
        if row.get("capability_id") == PENDING_BRIDGE_ID
    ]
    assert len(active_pending_backlog) == 1
    assert active_pending_backlog[0]["state"] == "TODO"
    assert active_pending_backlog[0]["monitor_id"] == PENDING_MONITOR
    assert active_pending_backlog[0]["dependency"] == "MONITOR_BRIDGE_EVIDENCE"
    assert all(row.get("capability_id") != READY_BRIDGE_ID for row in partial_result["development_backlog"])

    complete_payload = _payload(
        "READY",
        [
            "contract:fact-kernel-monitor-bridge",
            "monitor:monitor-beta",
            "main-commit:synthetic-monitor-beta",
        ],
    )
    complete_before = deepcopy(complete_payload)
    complete_result = reconcile(complete_payload)
    assert complete_payload == complete_before

    complete_ready = _capability(complete_result, READY_BRIDGE_ID)
    complete_pending = _capability(complete_result, PENDING_BRIDGE_ID)
    assert complete_ready["status"] == "IMPLEMENTED"
    assert complete_ready["monitor_id"] == READY_MONITOR
    assert complete_pending["status"] == "IMPLEMENTED"
    assert complete_pending["gap"] is None
    assert complete_pending["monitor_id"] == PENDING_MONITOR
    assert all(row.get("capability_id") != PENDING_BRIDGE_ID for row in complete_result["development_backlog"])
    assert all(row["capability_id"] != AGGREGATE_FACT_KERNEL_ID for row in complete_result["capabilities"])

    print(json.dumps({
        "status": "PASS",
        "prs": "PRS-055",
        "instance_id": INSTANCE_ID,
        "persistence_namespace": NAMESPACE,
        "ready_monitor_status": ready["status"],
        "pending_monitor_partial_status": pending["status"],
        "pending_monitor_backlog_retained": True,
        "pending_monitor_complete_status": complete_pending["status"],
        "per_monitor_identities": True,
        "aggregate_fact_kernel_boolean_absent": True,
        "repository_input_unchanged": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
