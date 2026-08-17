#!/usr/bin/env python3
"""PRS-043 acceptance: open/unmerged PR evidence must never imply IMPLEMENTED.

Provider-neutral and mutation-free. The canonical reconciliation engine receives
repository evidence for work that exists only in an open or draft pull request.
It must preserve ACTIVE_UNIMPLEMENTED unless explicit partial implementation
evidence exists, in which case PARTIAL is allowed. MERGED/IMPLEMENTED is never
inferred from branch, asset, PR existence, or CI readiness alone.
"""
from __future__ import annotations

import json
from copy import deepcopy

from reconciliation_engine import REQUIRED_FRESH_GATES, reconcile

MAIN = "a" * 40


def _fresh_gates() -> dict[str, bool]:
    return {gate: True for gate in REQUIRED_FRESH_GATES}


def _payload(decision_id: str, implementation_state: str, *, partial_evidence: bool = False) -> dict:
    return {
        "schema_version": 1,
        "scope_id": "synthetic-product",
        "instance_id": "synthetic-instance",
        "persisted": {
            "main_head": MAIN,
            "decisions": [{
                "decision_id": decision_id,
                "status": "ACTIVE_UNIMPLEMENTED",
                "priority": "P0",
                "implementation_evidence": [],
            }],
            "capabilities": [],
            "backlog": [],
        },
        "repository": {
            "main_head": MAIN,
            "scope_classification": "NO_SCOPE_CHANGE",
            "decisions": {
                decision_id: {
                    "implementation_state": implementation_state,
                    "partial_evidence": partial_evidence,
                    "evidence": ["pull-request:OPEN"],
                }
            },
            "capabilities": {},
        },
        "external": {"decisions": {}, "capabilities": {}},
        "health_gates": _fresh_gates(),
    }


def _decision(result: dict, decision_id: str) -> dict:
    return next(row for row in result["decisions"] if row["decision_id"] == decision_id)


def main() -> int:
    cases = [
        ("D-OPEN-PR", "OPEN_PR", False, "ACTIVE_UNIMPLEMENTED"),
        ("D-DRAFT-PR", "DRAFT_PR", False, "ACTIVE_UNIMPLEMENTED"),
        ("D-OPEN-PARTIAL", "OPEN_PR", True, "PARTIAL"),
    ]
    observed = []
    for decision_id, implementation_state, partial_evidence, expected_status in cases:
        payload = _payload(decision_id, implementation_state, partial_evidence=partial_evidence)
        before = deepcopy(payload)
        result = reconcile(payload)
        assert payload == before
        row = _decision(result, decision_id)
        assert row["implementation_state"] == implementation_state
        assert row["status"] == expected_status
        assert row["status"] != "IMPLEMENTED"
        observed.append({
            "decision_id": decision_id,
            "implementation_state": implementation_state,
            "partial_evidence": partial_evidence,
            "reconciled_status": row["status"],
        })

    print(json.dumps({
        "status": "PASS",
        "prs": "PRS-043",
        "rule": "OPEN_OR_DRAFT_UNMERGED_NEVER_IMPLEMENTED",
        "cases": observed,
        "repository_input_unchanged": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
