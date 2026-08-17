#!/usr/bin/env python3
"""PRS-042 acceptance: stale Drive state must not downgrade newer main evidence.

This test is provider-neutral and mutation-free. It feeds an older persisted view
and a newer repository view into the canonical reconciliation engine and proves
that merged main evidence wins, stale persistence is diagnosed, and the result
remains reconciliation-required until a separately governed persistence write
is completed.
"""
from __future__ import annotations

import json
from copy import deepcopy

from reconciliation_engine import REQUIRED_FRESH_GATES, reconcile

OLD_MAIN = "1" * 40
NEW_MAIN = "2" * 40
DECISION_ID = "D-DRIVE-OLD-MAIN-NEW"


def _fresh_gates() -> dict[str, bool]:
    return {gate: True for gate in REQUIRED_FRESH_GATES}


def build_payload() -> dict:
    return {
        "schema_version": 1,
        "scope_id": "synthetic-product",
        "instance_id": "synthetic-instance",
        "persisted": {
            "main_head": OLD_MAIN,
            "decisions": [
                {
                    "decision_id": DECISION_ID,
                    "status": "ACTIVE_UNIMPLEMENTED",
                    "priority": "P0",
                    "implementation_evidence": [f"persisted-main:{OLD_MAIN}"],
                }
            ],
            "capabilities": [],
            "backlog": [],
        },
        "repository": {
            "main_head": NEW_MAIN,
            "scope_classification": "NO_SCOPE_CHANGE",
            "decisions": {
                DECISION_ID: {
                    "implementation_state": "MERGED",
                    "evidence": [f"commit:{NEW_MAIN}"],
                }
            },
            "capabilities": {},
        },
        "external": {
            "decisions": {},
            "capabilities": {},
        },
        "health_gates": _fresh_gates(),
    }


def main() -> int:
    payload = build_payload()
    before = deepcopy(payload)
    result = reconcile(payload)

    # Reconciliation is pure: it cannot mutate or "roll back" repository input.
    assert payload == before
    assert payload["repository"]["main_head"] == NEW_MAIN
    assert payload["persisted"]["main_head"] == OLD_MAIN

    decision = next(row for row in result["decisions"] if row["decision_id"] == DECISION_ID)
    assert decision["status"] == "IMPLEMENTED"
    assert decision["implementation_state"] == "MERGED"
    assert decision["implementation_evidence"] == [f"commit:{NEW_MAIN}"]
    assert f"persisted-main:{OLD_MAIN}" not in decision["implementation_evidence"]

    diagnostics = [
        row for row in result["diagnostics"]
        if row.get("decision_id") == DECISION_ID
    ]
    assert diagnostics == [{
        "kind": "FALSE_NEGATIVE_PERSISTENCE",
        "decision_id": DECISION_ID,
        "persisted_status": "ACTIVE_UNIMPLEMENTED",
        "reconciled_status": "IMPLEMENTED",
    }]

    # Even with all other freshness gates true, stale persisted truth must first
    # be reconciled/persisted; the engine must not silently claim FRESH.
    assert result["persistence_health"]["state"] == "RECONCILIATION_REQUIRED"
    assert result["persistence_health"]["blocking_diagnostic_count"] == 1

    print(json.dumps({
        "status": "PASS",
        "prs": "PRS-042",
        "persisted_main_head": OLD_MAIN,
        "repository_main_head": NEW_MAIN,
        "reconciled_decision_status": decision["status"],
        "diagnostic": diagnostics[0]["kind"],
        "persistence_health": result["persistence_health"]["state"],
        "repository_input_unchanged": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
