#!/usr/bin/env python3
"""PRS-054 acceptance: Source Intelligence engine readiness is separate from coverage/rating work."""
from __future__ import annotations

import json
from copy import deepcopy

from reconciliation_engine import REQUIRED_FRESH_GATES, reconcile

INSTANCE_ID = "synthetic-instance"
NAMESPACE = "instance/synthetic-instance"
ENGINE_ID = f"{NAMESPACE}:capability:source-intelligence-engine"
COVERAGE_ID = f"{NAMESPACE}:capability:source-intelligence-coverage-rating"
COVERAGE_BACKLOG_ID = f"capability:{COVERAGE_ID}"
MAIN = "c" * 40


def _payload(coverage_code_state: str, coverage_evidence: list[str]) -> dict:
    return {
        "schema_version": 1,
        "scope_id": "synthetic-product",
        "instance_id": INSTANCE_ID,
        "persistence_namespace": NAMESPACE,
        "persisted": {
            "main_head": MAIN,
            "decisions": [],
            "capabilities": [
                {
                    "capability_id": ENGINE_ID,
                    "instance_id": INSTANCE_ID,
                    "persistence_namespace": NAMESPACE,
                    "domain": "source_intelligence_engine",
                    "desired_state": "READY",
                    "code_state": "PARTIAL",
                    "runtime_state": "UNKNOWN",
                    "external_state": "NOT_APPLICABLE",
                    "priority": "P1",
                    "next_action": "maintain generic Source Intelligence engine regression",
                    "acceptance_test": "engine implementation is independently present on main",
                },
                {
                    "capability_id": COVERAGE_ID,
                    "instance_id": INSTANCE_ID,
                    "persistence_namespace": NAMESPACE,
                    "domain": "source_intelligence_coverage_rating",
                    "desired_state": "READY",
                    "code_state": "PARTIAL",
                    "runtime_state": "ACTIVE_PARTIAL",
                    "external_state": "NOT_APPLICABLE",
                    "priority": "P1",
                    "next_action": "expand and rate the instance source pack until coverage thresholds pass",
                    "acceptance_test": "coverage and rating threshold evidence is present for the instance source pack",
                    "rollback": "preserve the last verified rated source registry",
                },
            ],
            "backlog": [
                {
                    "backlog_id": COVERAGE_BACKLOG_ID,
                    "priority": "P1",
                    "capability_id": COVERAGE_ID,
                    "exact_action": "expand and rate the instance source pack until coverage thresholds pass",
                    "dependency": "SOURCE_PACK",
                    "acceptance_test": "coverage and rating threshold evidence is present for the instance source pack",
                    "rollback": "preserve the last verified rated source registry",
                    "state": "TODO",
                }
            ],
        },
        "repository": {
            "main_head": MAIN,
            "scope_classification": "NO_SCOPE_CHANGE",
            "decisions": {},
            "capabilities": {
                ENGINE_ID: {
                    "code_state": "READY",
                    "runtime_state": "ACTIVE",
                    "evidence": [
                        "contract:source-intelligence-generic-engine",
                        "main-commit:synthetic-engine",
                    ],
                },
                COVERAGE_ID: {
                    "code_state": coverage_code_state,
                    "runtime_state": "ACTIVE" if coverage_code_state == "READY" else "ACTIVE_PARTIAL",
                    "evidence": coverage_evidence,
                },
            },
        },
        "external": {
            "decisions": {},
            "capabilities": {
                ENGINE_ID: {"external_state": "NOT_APPLICABLE"},
                COVERAGE_ID: {"external_state": "NOT_APPLICABLE"},
            },
        },
        "health_gates": {gate: True for gate in REQUIRED_FRESH_GATES},
    }


def _capability(result: dict, capability_id: str) -> dict:
    return next(row for row in result["capabilities"] if row["capability_id"] == capability_id)


def main() -> int:
    # The generic engine is already implemented, while instance coverage/rating
    # remains independently incomplete. The unfinished frontier must not
    # downgrade engine readiness or disappear from the active backlog.
    partial_payload = _payload(
        "PARTIAL",
        ["source-pack:synthetic-coverage-incomplete", "rating-state:synthetic-incomplete"],
    )
    partial_before = deepcopy(partial_payload)
    partial_result = reconcile(partial_payload)
    assert partial_payload == partial_before

    engine = _capability(partial_result, ENGINE_ID)
    coverage = _capability(partial_result, COVERAGE_ID)
    assert engine["status"] == "IMPLEMENTED"
    assert engine["code_state"] == "READY"
    assert engine["gap"] is None
    assert coverage["status"] == "ACTIVE_UNIMPLEMENTED"
    assert coverage["code_state"] == "PARTIAL"
    assert coverage["gap"] == "CODE_GAP"
    assert engine["capability_id"] != coverage["capability_id"]
    assert engine["persistence_namespace"] == NAMESPACE
    assert coverage["persistence_namespace"] == NAMESPACE

    active_coverage_backlog = [
        row for row in partial_result["development_backlog"]
        if row.get("capability_id") == COVERAGE_ID
    ]
    assert len(active_coverage_backlog) == 1
    assert active_coverage_backlog[0]["state"] == "TODO"
    assert active_coverage_backlog[0]["dependency"] == "SOURCE_PACK"
    assert all(row.get("capability_id") != ENGINE_ID for row in partial_result["development_backlog"])

    # Once independent threshold evidence marks the coverage/rating capability
    # READY, only that workstream closes; the engine identity remains unchanged.
    complete_payload = _payload(
        "READY",
        ["source-pack:synthetic-coverage-thresholds-pass", "rating-state:synthetic-thresholds-pass"],
    )
    complete_before = deepcopy(complete_payload)
    complete_result = reconcile(complete_payload)
    assert complete_payload == complete_before

    complete_engine = _capability(complete_result, ENGINE_ID)
    complete_coverage = _capability(complete_result, COVERAGE_ID)
    assert complete_engine["status"] == "IMPLEMENTED"
    assert complete_engine["capability_id"] == ENGINE_ID
    assert complete_coverage["status"] == "IMPLEMENTED"
    assert complete_coverage["gap"] is None
    assert all(row.get("capability_id") != COVERAGE_ID for row in complete_result["development_backlog"])

    print(json.dumps({
        "status": "PASS",
        "prs": "PRS-054",
        "instance_id": INSTANCE_ID,
        "persistence_namespace": NAMESPACE,
        "engine_status": engine["status"],
        "coverage_partial_status": coverage["status"],
        "coverage_backlog_retained_until_thresholds": True,
        "coverage_complete_status": complete_coverage["status"],
        "engine_and_coverage_identities_separate": True,
        "repository_input_unchanged": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
