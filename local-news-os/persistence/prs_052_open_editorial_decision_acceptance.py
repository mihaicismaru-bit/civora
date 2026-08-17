#!/usr/bin/env python3
"""PRS-052 acceptance: open special-editorial work stays active until merged on main."""
from __future__ import annotations

import json
from copy import deepcopy

from reconciliation_engine import REQUIRED_FRESH_GATES, reconcile

INSTANCE_ID = "synthetic-instance"
NAMESPACE = "instance/synthetic-instance"
DECISION_ID = f"{NAMESPACE}:decision:special-editorial-products"
BACKLOG_ID = f"decision:{DECISION_ID}"
MAIN = "a" * 40


def _payload(implementation_state: str) -> dict:
    return {
        "schema_version": 1,
        "scope_id": "synthetic-product",
        "instance_id": INSTANCE_ID,
        "persistence_namespace": NAMESPACE,
        "persisted": {
            "main_head": MAIN,
            "decisions": [{
                "decision_id": DECISION_ID,
                "instance_id": INSTANCE_ID,
                "persistence_namespace": NAMESPACE,
                "decision_text": "Investigations and satire remain active editorial products until executable implementation is merged on main.",
                "status": "PARTIAL",
                "priority": "P1",
                "implementation_evidence": ["pull-request:synthetic-open-unmerged"],
                "next_action": "rebase, validate and merge executable implementation",
                "acceptance_test": "merged main evidence proves executable implementation",
            }],
            "capabilities": [],
            "backlog": [{
                "backlog_id": BACKLOG_ID,
                "priority": "P1",
                "decision_id": DECISION_ID,
                "exact_action": "rebase, validate and merge executable implementation",
                "dependency": "current main",
                "acceptance_test": "merged main evidence proves executable implementation",
                "rollback": "retain active decision without implementation claim",
                "state": "TODO",
            }],
        },
        "repository": {
            "main_head": MAIN,
            "scope_classification": "NO_SCOPE_CHANGE",
            "decisions": {
                DECISION_ID: {
                    "implementation_state": implementation_state,
                    "partial_evidence": False,
                    "evidence": [
                        "pull-request:synthetic-open-unmerged"
                        if implementation_state == "OPEN_PR"
                        else "main-commit:synthetic-merged"
                    ],
                }
            },
            "capabilities": {},
        },
        "external": {"decisions": {}, "capabilities": {}},
        "health_gates": {gate: True for gate in REQUIRED_FRESH_GATES},
    }


def _decision(result: dict) -> dict:
    return next(row for row in result["decisions"] if row["decision_id"] == DECISION_ID)


def main() -> int:
    open_payload = _payload("OPEN_PR")
    open_before = deepcopy(open_payload)
    open_result = reconcile(open_payload)
    assert open_payload == open_before

    open_row = _decision(open_result)
    assert open_row["instance_id"] == INSTANCE_ID
    assert open_row["persistence_namespace"] == NAMESPACE
    assert open_row["implementation_state"] == "OPEN_PR"
    assert open_row["status"] == "ACTIVE_UNIMPLEMENTED"
    assert open_row["status"] != "IMPLEMENTED"
    assert open_row["implementation_evidence"] == ["pull-request:synthetic-open-unmerged"]

    open_backlog = [row for row in open_result["development_backlog"] if row.get("decision_id") == DECISION_ID]
    assert len(open_backlog) == 1
    assert open_backlog[0]["backlog_id"] == BACKLOG_ID
    assert open_backlog[0]["state"] == "TODO"

    merged_payload = _payload("MERGED")
    merged_before = deepcopy(merged_payload)
    merged_result = reconcile(merged_payload)
    assert merged_payload == merged_before

    merged_row = _decision(merged_result)
    assert merged_row["implementation_state"] == "MERGED"
    assert merged_row["status"] == "IMPLEMENTED"
    assert all(row.get("decision_id") != DECISION_ID for row in merged_result["development_backlog"])

    print(json.dumps({
        "status": "PASS",
        "prs": "PRS-052",
        "instance_id": INSTANCE_ID,
        "persistence_namespace": NAMESPACE,
        "open_pr_status": open_row["status"],
        "open_pr_backlog_state": open_backlog[0]["state"],
        "merged_status": merged_row["status"],
        "repository_input_unchanged": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
