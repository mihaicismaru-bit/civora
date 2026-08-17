#!/usr/bin/env python3
"""PRS-047 acceptance: NO_PROGRESS checkpoint stays historical after main advances.

The checkpoint is immutable historical context, not current authority. A later
merged implementation on main must advance reconciled current state and retire
the stale backlog item without rewriting or reactivating the checkpoint.
"""
from __future__ import annotations

import json
from copy import deepcopy

from reconciliation_engine import REQUIRED_FRESH_GATES, reconcile

OLD_MAIN = "3" * 40
NEW_MAIN = "4" * 40
DECISION_ID = "D-NO-PROGRESS-THEN-MAIN"
BACKLOG_ID = "B-NO-PROGRESS-THEN-MAIN"
CHECKPOINT_ID = "CIVORA_0089"


def build_payload() -> dict:
    return {
        "schema_version": 1,
        "scope_id": "synthetic-product",
        "instance_id": "synthetic-instance",
        "persisted": {
            "main_head": OLD_MAIN,
            "historical_checkpoints": [{
                "checkpoint_id": CHECKPOINT_ID,
                "status": "NO_PROGRESS_HISTORICAL_STATE",
                "main_head": OLD_MAIN,
                "immutable": True,
                "resume_authority": False,
            }],
            "decisions": [{
                "decision_id": DECISION_ID,
                "status": "ACTIVE_UNIMPLEMENTED",
                "priority": "P0",
                "implementation_evidence": [f"checkpoint:{CHECKPOINT_ID}"],
            }],
            "capabilities": [],
            "backlog": [{
                "backlog_id": BACKLOG_ID,
                "priority": "P0",
                "decision_id": DECISION_ID,
                "exact_action": "implement after historical no-progress checkpoint",
                "dependency": "",
                "acceptance_test": "merged evidence advances current state",
                "rollback": "restore previous accepted current state",
                "state": "TODO",
            }],
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
        "external": {"decisions": {}, "capabilities": {}},
        "health_gates": {gate: True for gate in REQUIRED_FRESH_GATES},
    }


def main() -> int:
    payload = build_payload()
    before = deepcopy(payload)
    checkpoint_before = deepcopy(payload["persisted"]["historical_checkpoints"][0])
    result = reconcile(payload)

    # Reconciliation is pure. The old checkpoint remains immutable history.
    assert payload == before
    checkpoint_after = payload["persisted"]["historical_checkpoints"][0]
    assert checkpoint_after == checkpoint_before
    assert checkpoint_after["checkpoint_id"] == CHECKPOINT_ID
    assert checkpoint_after["status"] == "NO_PROGRESS_HISTORICAL_STATE"
    assert checkpoint_after["immutable"] is True
    assert checkpoint_after["resume_authority"] is False
    assert checkpoint_after["main_head"] == OLD_MAIN

    # New merged main evidence advances the current reconciled truth.
    decision = next(row for row in result["decisions"] if row["decision_id"] == DECISION_ID)
    assert payload["repository"]["main_head"] == NEW_MAIN
    assert decision["status"] == "IMPLEMENTED"
    assert decision["implementation_state"] == "MERGED"
    assert decision["implementation_evidence"] == [f"commit:{NEW_MAIN}"]

    # The stale TODO from the no-progress checkpoint cannot remain active.
    assert all(row.get("backlog_id") != BACKLOG_ID for row in result["development_backlog"])
    assert all(row.get("decision_id") != DECISION_ID for row in result["development_backlog"])

    diagnostics = [row for row in result["diagnostics"] if row.get("decision_id") == DECISION_ID]
    assert diagnostics == [{
        "kind": "FALSE_NEGATIVE_PERSISTENCE",
        "decision_id": DECISION_ID,
        "persisted_status": "ACTIVE_UNIMPLEMENTED",
        "reconciled_status": "IMPLEMENTED",
    }]

    # Persistence remains fail-closed until the advanced current truth is written
    # separately under the writer lease; the checkpoint itself is never rewritten.
    assert result["persistence_health"]["state"] == "RECONCILIATION_REQUIRED"
    current_state = {
        "canonical_main_head": payload["repository"]["main_head"],
        "decision_status": decision["status"],
        "latest_valid_checkpoint": CHECKPOINT_ID,
        "checkpoint_role": "HISTORICAL_IMMUTABLE",
    }
    assert current_state["canonical_main_head"] == NEW_MAIN
    assert current_state["decision_status"] == "IMPLEMENTED"
    assert current_state["checkpoint_role"] == "HISTORICAL_IMMUTABLE"

    print(json.dumps({
        "status": "PASS",
        "prs": "PRS-047",
        "checkpoint_id": CHECKPOINT_ID,
        "checkpoint_status": checkpoint_after["status"],
        "checkpoint_unchanged": True,
        "persisted_main_head": OLD_MAIN,
        "current_main_head": NEW_MAIN,
        "reconciled_decision_status": decision["status"],
        "stale_backlog_active": False,
        "persistence_health": result["persistence_health"]["state"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
