#!/usr/bin/env python3
"""PRS-044 acceptance: a superseded PR must stay historical after a later merge.

Provider-neutral and mutation-free. The canonical reconciliation engine receives
an older decision backed only by a superseded/closed-unmerged PR plus a newer
replacement decision that is actually MERGED. The replacement must reconcile to
IMPLEMENTED, while the older work remains SUPERSEDED and cannot re-enter the
active development backlog.
"""
from __future__ import annotations

import json
from copy import deepcopy

from reconciliation_engine import REQUIRED_FRESH_GATES, reconcile

MAIN = "b" * 40
OLD_DECISION = "D-OLD-PR"
NEW_DECISION = "D-LATER-MERGE"
OLD_BACKLOG = "B-OLD-PR"


def _fresh_gates() -> dict[str, bool]:
    return {gate: True for gate in REQUIRED_FRESH_GATES}


def _payload(old_implementation_state: str) -> dict:
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
                    "superseded_by": NEW_DECISION,
                    "implementation_evidence": ["pull-request:old"],
                },
                {
                    "decision_id": NEW_DECISION,
                    "status": "ACTIVE_UNIMPLEMENTED",
                    "priority": "P0",
                    "implementation_evidence": [],
                },
            ],
            "capabilities": [],
            "backlog": [
                {
                    "backlog_id": OLD_BACKLOG,
                    "priority": "P0",
                    "decision_id": OLD_DECISION,
                    "exact_action": "finish obsolete branch",
                    "dependency": "",
                    "acceptance_test": "old PR lands",
                    "rollback": "restore prior state",
                    "state": "TODO",
                }
            ],
        },
        "repository": {
            "main_head": MAIN,
            "scope_classification": "NO_SCOPE_CHANGE",
            "decisions": {
                OLD_DECISION: {
                    "implementation_state": old_implementation_state,
                    "superseded_by": NEW_DECISION,
                    "evidence": ["pull-request:old:historical"],
                },
                NEW_DECISION: {
                    "implementation_state": "MERGED",
                    "evidence": ["pull-request:new:merged", "commit:replacement"],
                },
            },
            "capabilities": {},
        },
        "external": {"decisions": {}, "capabilities": {}},
        "health_gates": _fresh_gates(),
    }


def _decision(result: dict, decision_id: str) -> dict:
    return next(row for row in result["decisions"] if row["decision_id"] == decision_id)


def main() -> int:
    observed = []
    for old_state in ("SUPERSEDED", "CLOSED_UNMERGED"):
        payload = _payload(old_state)
        before = deepcopy(payload)
        result = reconcile(payload)
        assert payload == before

        old = _decision(result, OLD_DECISION)
        new = _decision(result, NEW_DECISION)
        assert old["status"] == "SUPERSEDED"
        assert old["superseded_by"] == NEW_DECISION
        assert new["status"] == "IMPLEMENTED"
        assert new["implementation_state"] == "MERGED"

        diagnostics = result["diagnostics"]
        assert any(
            row.get("kind") == "SUPERSEDED_WORK"
            and row.get("decision_id") == OLD_DECISION
            and row.get("superseded_by") == NEW_DECISION
            for row in diagnostics
        )
        assert any(
            row.get("kind") == "FALSE_NEGATIVE_PERSISTENCE"
            and row.get("decision_id") == NEW_DECISION
            for row in diagnostics
        )

        active_backlog_ids = {row["backlog_id"] for row in result["development_backlog"]}
        assert OLD_BACKLOG not in active_backlog_ids
        assert f"decision:{OLD_DECISION}" not in active_backlog_ids
        assert f"decision:{NEW_DECISION}" not in active_backlog_ids
        assert result["persistence_health"]["state"] == "RECONCILIATION_REQUIRED"

        observed.append({
            "old_implementation_state": old_state,
            "old_reconciled_status": old["status"],
            "replacement_status": new["status"],
            "old_backlog_reactivated": OLD_BACKLOG in active_backlog_ids,
        })

    print(json.dumps({
        "status": "PASS",
        "prs": "PRS-044",
        "rule": "LATER_MERGED_REPLACEMENT_WINS_OLD_PR_HISTORICAL",
        "cases": observed,
        "repository_input_unchanged": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
