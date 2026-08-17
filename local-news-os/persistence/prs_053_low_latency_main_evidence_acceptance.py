#!/usr/bin/env python3
"""PRS-053 acceptance: later merged main evidence closes a stale low-latency gap."""
from __future__ import annotations

import json
from copy import deepcopy

from reconciliation_engine import REQUIRED_FRESH_GATES, reconcile

INSTANCE_ID = "synthetic-instance"
NAMESPACE = "instance/synthetic-instance"
DECISION_ID = f"{NAMESPACE}:decision:low-latency-discovery"
BACKLOG_ID = f"decision:{DECISION_ID}"
MAIN = "b" * 40


def _payload(implementation_state: str, evidence: list[str]) -> dict:
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
                "decision_text": "Continuous story-first discovery must remain operationally low-latency without weakening editorial gates.",
                "status": "PARTIAL",
                "priority": "P1",
                "implementation_evidence": ["pull-request:synthetic-stale-open"],
                "next_action": "retain the gap until equivalent implementation is merged or the old proposal is superseded with authoritative evidence",
                "acceptance_test": "independent merged main evidence proves bounded-parallel fail-closed discovery",
            }],
            "capabilities": [],
            "backlog": [{
                "backlog_id": BACKLOG_ID,
                "priority": "P1",
                "decision_id": DECISION_ID,
                "exact_action": "integrate bounded-parallel fail-closed discovery",
                "dependency": "current main",
                "acceptance_test": "independent merged main evidence proves bounded-parallel fail-closed discovery",
                "rollback": "retain serial discovery and active decision",
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
                    "evidence": evidence,
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
    # A stale open proposal alone remains insufficient and keeps the gap active.
    open_payload = _payload("OPEN_PR", ["pull-request:synthetic-stale-open"])
    open_before = deepcopy(open_payload)
    open_result = reconcile(open_payload)
    assert open_payload == open_before
    open_row = _decision(open_result)
    assert open_row["status"] == "ACTIVE_UNIMPLEMENTED"
    assert open_row["implementation_state"] == "OPEN_PR"
    open_backlog = [row for row in open_result["development_backlog"] if row.get("decision_id") == DECISION_ID]
    assert len(open_backlog) == 1
    assert open_backlog[0]["state"] == "TODO"

    # A later independently merged equivalent implementation is authoritative,
    # even if the persisted layer still points at the older open proposal.
    merged_evidence = [
        "pull-request:synthetic-replacement-merged",
        "main-commit:synthetic-low-latency",
        "contract:bounded-parallel-fail-closed-discovery",
    ]
    merged_payload = _payload("MERGED", merged_evidence)
    merged_before = deepcopy(merged_payload)
    merged_result = reconcile(merged_payload)
    assert merged_payload == merged_before
    merged_row = _decision(merged_result)
    assert merged_row["status"] == "IMPLEMENTED"
    assert merged_row["implementation_state"] == "MERGED"
    assert merged_row["implementation_evidence"] == merged_evidence
    assert "pull-request:synthetic-stale-open" not in merged_row["implementation_evidence"]
    assert all(row.get("decision_id") != DECISION_ID for row in merged_result["development_backlog"])
    false_negative = [
        row for row in merged_result["diagnostics"]
        if row.get("kind") == "FALSE_NEGATIVE_PERSISTENCE" and row.get("decision_id") == DECISION_ID
    ]
    assert len(false_negative) == 1

    print(json.dumps({
        "status": "PASS",
        "prs": "PRS-053",
        "instance_id": INSTANCE_ID,
        "persistence_namespace": NAMESPACE,
        "open_only_status": open_row["status"],
        "merged_replacement_status": merged_row["status"],
        "stale_open_evidence_retired": True,
        "false_negative_persistence_detected": True,
        "repository_input_unchanged": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
