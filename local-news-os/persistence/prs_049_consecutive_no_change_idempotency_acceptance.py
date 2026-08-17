#!/usr/bin/env python3
"""PRS-049 acceptance: consecutive no-change reconciliations are idempotent.

Provider-neutral and mutation-free. A steady-state normalized snapshot is
reconciled, its semantic output is used as the persisted layer for a second run,
and unchanged repository/external evidence must produce zero semantic drift,
zero diagnostics and no duplicate decision/capability/backlog identities.
"""
from __future__ import annotations

import json
from copy import deepcopy

from reconciliation_engine import REQUIRED_FRESH_GATES, reconcile

MAIN = "9" * 40
ACTIVE_DECISION = "D-IDEMPOTENT-ACTIVE"
IMPLEMENTED_DECISION = "D-IDEMPOTENT-IMPLEMENTED"
OUTBOX_CAPABILITY = "C-IDEMPOTENT-OUTBOX"
DECISION_BACKLOG = f"decision:{ACTIVE_DECISION}"
CAPABILITY_BACKLOG = f"capability:{OUTBOX_CAPABILITY}"


def build_payload() -> dict:
    gates = {gate: True for gate in REQUIRED_FRESH_GATES}
    return {
        "schema_version": 1,
        "scope_id": "synthetic-product",
        "instance_id": "synthetic-instance",
        "persisted": {
            "main_head": MAIN,
            "decisions": [
                {
                    "decision_id": ACTIVE_DECISION,
                    "status": "ACTIVE_UNIMPLEMENTED",
                    "priority": "P0",
                    "next_action": "finish active synthetic decision",
                    "implementation_state": "OPEN_PR",
                    "external_state": "UNCONFIRMED",
                    "implementation_evidence": ["pr:synthetic-open"],
                    "runtime_evidence": [],
                },
                {
                    "decision_id": IMPLEMENTED_DECISION,
                    "status": "IMPLEMENTED",
                    "priority": "P1",
                    "implementation_state": "MERGED",
                    "external_state": "UNCONFIRMED",
                    "implementation_evidence": ["commit:synthetic-merged"],
                    "runtime_evidence": [],
                },
            ],
            "capabilities": [
                {
                    "capability_id": OUTBOX_CAPABILITY,
                    "priority": "P1",
                    "desired_state": "DIRECT_LIVE",
                    "status": "PARTIAL",
                    "code_state": "READY",
                    "runtime_state": "DURABLE_OUTBOX_ONLY",
                    "external_state": "UNCONFIRMED",
                    "direct_or_outbox": "OUTBOX_ONLY",
                    "gap": "DIRECT_ADAPTER_OR_ACCESS_GAP",
                    "evidence_refs": ["runtime:synthetic-outbox"],
                    "next_action": "retain outbox until direct capability is verified",
                }
            ],
            "backlog": [
                {
                    "backlog_id": DECISION_BACKLOG,
                    "priority": "P0",
                    "decision_id": ACTIVE_DECISION,
                    "exact_action": "finish active synthetic decision",
                    "dependency": "",
                    "acceptance_test": "evidence-backed implementation state",
                    "rollback": "restore previous accepted state",
                    "state": "TODO",
                    "source_id": ACTIVE_DECISION,
                },
                {
                    "backlog_id": CAPABILITY_BACKLOG,
                    "priority": "P1",
                    "capability_id": OUTBOX_CAPABILITY,
                    "exact_action": "retain outbox until direct capability is verified",
                    "dependency": "",
                    "acceptance_test": "capability gap closed with evidence",
                    "rollback": "restore previous accepted state",
                    "state": "TODO",
                    "source_id": OUTBOX_CAPABILITY,
                },
            ],
        },
        "repository": {
            "main_head": MAIN,
            "scope_classification": "NO_SCOPE_CHANGE",
            "decisions": {
                ACTIVE_DECISION: {
                    "implementation_state": "OPEN_PR",
                    "evidence": ["pr:synthetic-open"],
                },
                IMPLEMENTED_DECISION: {
                    "implementation_state": "MERGED",
                    "evidence": ["commit:synthetic-merged"],
                },
            },
            "capabilities": {
                OUTBOX_CAPABILITY: {
                    "code_state": "READY",
                    "runtime_state": "DURABLE_OUTBOX_ONLY",
                    "evidence": ["runtime:synthetic-outbox"],
                }
            },
        },
        "external": {
            "decisions": {},
            "capabilities": {
                OUTBOX_CAPABILITY: {"external_state": "UNCONFIRMED", "evidence": []}
            },
        },
        "health_gates": gates,
    }


def next_payload(previous: dict, result: dict) -> dict:
    follow_up = deepcopy(previous)
    follow_up["persisted"] = {
        "main_head": MAIN,
        "decisions": deepcopy(result["decisions"]),
        "capabilities": deepcopy(result["capabilities"]),
        "backlog": deepcopy(result["development_backlog"]),
    }
    return follow_up


def semantic_projection(result: dict) -> dict:
    return {
        "decisions": result["decisions"],
        "capabilities": result["capabilities"],
        "development_backlog": result["development_backlog"],
        "diagnostics": result["diagnostics"],
        "persistence_health": result["persistence_health"],
    }


def assert_unique(rows: list[dict], key: str) -> None:
    identities = [str(row[key]) for row in rows]
    assert len(identities) == len(set(identities)), (key, identities)


def main() -> int:
    payload = build_payload()
    original = deepcopy(payload)

    first = reconcile(payload)
    assert payload == original
    assert first["diagnostics"] == []
    assert first["persistence_health"]["state"] == "PERSISTENCE_FRESH"
    assert_unique(first["decisions"], "decision_id")
    assert_unique(first["capabilities"], "capability_id")
    assert_unique(first["development_backlog"], "backlog_id")

    first_backlog_ids = [row["backlog_id"] for row in first["development_backlog"]]
    assert first_backlog_ids.count(DECISION_BACKLOG) == 1
    assert first_backlog_ids.count(CAPABILITY_BACKLOG) == 1

    second_input = next_payload(payload, first)
    second_input_before = deepcopy(second_input)
    second = reconcile(second_input)
    assert second_input == second_input_before
    assert second["diagnostics"] == []
    assert second["persistence_health"]["state"] == "PERSISTENCE_FRESH"
    assert_unique(second["decisions"], "decision_id")
    assert_unique(second["capabilities"], "capability_id")
    assert_unique(second["development_backlog"], "backlog_id")

    second_backlog_ids = [row["backlog_id"] for row in second["development_backlog"]]
    assert second_backlog_ids.count(DECISION_BACKLOG) == 1
    assert second_backlog_ids.count(CAPABILITY_BACKLOG) == 1
    assert semantic_projection(second) == semantic_projection(first)

    print(json.dumps({
        "status": "PASS",
        "prs": "PRS-049",
        "consecutive_runs": 2,
        "semantic_drift": 0,
        "duplicate_decisions": 0,
        "duplicate_capabilities": 0,
        "duplicate_backlog_items": 0,
        "active_backlog_items": len(second["development_backlog"]),
        "diagnostics": len(second["diagnostics"]),
        "persistence_health": second["persistence_health"]["state"],
        "input_mutation": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
