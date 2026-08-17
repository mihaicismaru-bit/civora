#!/usr/bin/env python3
"""PRS-048 acceptance: explicit replacement supersedes old decision, keeps new active.

Provider-neutral and mutation-free. Repository evidence explicitly marks an old
decision as replaced by a newer decision that is not yet implemented. The old
decision must reconcile to SUPERSEDED, the replacement must remain active, and
only the replacement may remain in the active backlog.
"""
from __future__ import annotations

import json
from copy import deepcopy

from reconciliation_engine import REQUIRED_FRESH_GATES, reconcile

MAIN = "8" * 40
OLD_DECISION = "D-EXPLICIT-OLD"
NEW_DECISION = "D-EXPLICIT-NEW"
OLD_BACKLOG = "B-EXPLICIT-OLD"


def build_payload() -> dict:
    gates = {gate: True for gate in REQUIRED_FRESH_GATES}
    # The replacement relationship is newly observed from current evidence and
    # has not yet been readback-bound into active persistence.
    gates["active_binding_pass"] = False
    return {
        "schema_version": 1,
        "scope_id": "synthetic-product",
        "instance_id": "synthetic-instance",
        "persisted": {
            "main_head": MAIN,
            "decisions": [
                {
                    "decision_id": OLD_DECISION,
                    "status": "ACTIVE_UNIMPLEMENTED",
                    "priority": "P0",
                    "next_action": "continue obsolete decision",
                },
                {
                    "decision_id": NEW_DECISION,
                    "status": "ACTIVE_UNIMPLEMENTED",
                    "priority": "P0",
                    "supersedes": OLD_DECISION,
                    "next_action": "implement explicit replacement",
                },
            ],
            "capabilities": [],
            "backlog": [
                {
                    "backlog_id": OLD_BACKLOG,
                    "priority": "P0",
                    "decision_id": OLD_DECISION,
                    "exact_action": "continue obsolete decision",
                    "dependency": "",
                    "acceptance_test": "old decision completes",
                    "rollback": "restore previous accepted state",
                    "state": "TODO",
                }
            ],
        },
        "repository": {
            "main_head": MAIN,
            "scope_classification": "NO_SCOPE_CHANGE",
            "decisions": {
                OLD_DECISION: {
                    "implementation_state": "ABSENT",
                    "superseded_by": NEW_DECISION,
                    "evidence": [f"decision-replacement:{OLD_DECISION}->{NEW_DECISION}"],
                },
                NEW_DECISION: {
                    "implementation_state": "ABSENT",
                    "evidence": [f"decision-active:{NEW_DECISION}"],
                },
            },
            "capabilities": {},
        },
        "external": {"decisions": {}, "capabilities": {}},
        "health_gates": gates,
    }


def _decision(result: dict, decision_id: str) -> dict:
    return next(row for row in result["decisions"] if row["decision_id"] == decision_id)


def main() -> int:
    payload = build_payload()
    before = deepcopy(payload)
    result = reconcile(payload)
    assert payload == before

    old = _decision(result, OLD_DECISION)
    new = _decision(result, NEW_DECISION)

    assert old["status"] == "SUPERSEDED"
    assert old["superseded_by"] == NEW_DECISION
    assert new["status"] == "ACTIVE_UNIMPLEMENTED"
    assert new["supersedes"] == OLD_DECISION
    assert new["implementation_state"] == "ABSENT"

    diagnostics = result["diagnostics"]
    assert any(
        row.get("kind") == "SUPERSEDED_WORK"
        and row.get("decision_id") == OLD_DECISION
        and row.get("superseded_by") == NEW_DECISION
        for row in diagnostics
    )
    assert not any(
        row.get("decision_id") == NEW_DECISION
        and row.get("kind") == "FALSE_NEGATIVE_PERSISTENCE"
        for row in diagnostics
    )

    active = {row["backlog_id"]: row for row in result["development_backlog"]}
    assert OLD_BACKLOG not in active
    assert f"decision:{OLD_DECISION}" not in active
    assert f"decision:{NEW_DECISION}" in active
    assert active[f"decision:{NEW_DECISION}"]["decision_id"] == NEW_DECISION
    assert active[f"decision:{NEW_DECISION}"]["state"] == "TODO"
    assert active[f"decision:{NEW_DECISION}"]["priority"] == "P0"

    # The newly reconciled replacement relation is not persistence-fresh until
    # active state is separately written and read back under the writer lease.
    health = result["persistence_health"]
    assert health["state"] == "RECONCILIATION_REQUIRED"
    assert "active_binding_pass" in health["missing_fresh_gates"]

    print(json.dumps({
        "status": "PASS",
        "prs": "PRS-048",
        "old_decision": OLD_DECISION,
        "old_status": old["status"],
        "replacement_decision": NEW_DECISION,
        "replacement_status": new["status"],
        "old_backlog_active": False,
        "replacement_backlog_active": True,
        "persistence_health": health["state"],
        "repository_input_unchanged": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
