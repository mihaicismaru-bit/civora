#!/usr/bin/env python3
"""Build the fail-closed browser projection from the canonical P11 bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "p11" / "opportunity_bundle.json"
OUTPUT = ROOT / "web" / "p11-public-data.js"
ACTIVE_RESOLUTION_STATES = {"OPEN", "IN_REVIEW"}
ALLOW_DECISION = "ALLOW_VERIFIED_FACTS"
BLOCK_DECISION = "BLOCK_MATERIAL_FACTS"


def atomic_text(path: pathlib.Path, value: str) -> None:
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def render(projection: dict) -> str:
    return "window.PARTENER_P11=" + json.dumps(projection, ensure_ascii=False, separators=(",", ":")) + ";\n"


def parse_payload(value: str) -> dict:
    prefix = "window.PARTENER_P11="
    stripped = value.strip()
    if not stripped.startswith(prefix) or not stripped.endswith(";"):
        raise ValueError("public projection wrapper is invalid")
    parsed = json.loads(stripped[len(prefix):-1])
    if not isinstance(parsed, dict):
        raise ValueError("public projection object required")
    return parsed


def assert_artifact_current(path: pathlib.Path, expected: str) -> None:
    actual = path.read_text(encoding="utf-8")
    expected_projection = parse_payload(expected)
    actual_projection = parse_payload(actual)
    assert_projection_integrity(expected_projection)
    assert_projection_integrity(actual_projection)
    if actual_projection != expected_projection:
        raise ValueError(
            f"public projection drift: {path} "
            f"actual_sha256={digest(render(actual_projection))} "
            f"expected_sha256={digest(render(expected_projection))}"
        )


def projection_integrity_errors(projection: dict) -> list[str]:
    opportunities = projection.get("opportunities")
    summary = projection.get("summary")
    policy = projection.get("policy")
    if not isinstance(opportunities, list):
        return ["opportunities must be a list"]
    if not isinstance(summary, dict):
        return ["summary must be an object"]

    errors = []
    if not isinstance(policy, dict):
        errors.append("policy must be an object")
    else:
        if policy.get("unverifiedMaterialFactsVisible") is not False:
            errors.append("policy must hide unverified material facts")
        if policy.get("automaticPublication") is not False:
            errors.append("policy must disable automatic publication")
        if policy.get("summaryDerivedFromEffectiveDecisions") is not True:
            errors.append("policy must derive summary from effective decisions")
    identifiers = [row.get("id") for row in opportunities if isinstance(row, dict)]
    if len(identifiers) != len(opportunities) or any(not value for value in identifiers):
        errors.append("every opportunity must have an id")
    if len(set(identifiers)) != len(identifiers):
        errors.append("opportunity ids must be unique")

    allowed = []
    blocked = []
    for row in opportunities:
        if not isinstance(row, dict):
            errors.append("every opportunity must be an object")
            continue
        decision = (row.get("publicationDecision") or {}).get("decision")
        reason_codes = (row.get("publicationDecision") or {}).get("reasonCodes")
        blocked_fact_classes = (row.get("publicationDecision") or {}).get("blockedFactClasses")
        active_task_count = (row.get("publicationDecision") or {}).get("activeResolutionTaskCount")
        if decision == ALLOW_DECISION:
            allowed.append(row)
        elif decision == BLOCK_DECISION:
            blocked.append(row)
        else:
            errors.append(f"{row.get('id')}: unknown publication decision")
            continue

        if not isinstance(reason_codes, list) or not reason_codes:
            errors.append(f"{row.get('id')}: decision reason codes required")
        elif len(reason_codes) != len(set(reason_codes)):
            errors.append(f"{row.get('id')}: duplicate decision reason codes")
        if not isinstance(blocked_fact_classes, list):
            errors.append(f"{row.get('id')}: blocked fact classes must be a list")
        elif blocked_fact_classes != sorted(set(blocked_fact_classes)):
            errors.append(f"{row.get('id')}: blocked fact classes must be sorted and unique")

        material_fact_classes = set((row.get("materialFacts") or {}).keys())
        verified_fact_classes = set(row.get("verifiedFactClasses") or [])
        if decision == BLOCK_DECISION and material_fact_classes:
            errors.append(f"{row.get('id')}: blocked decision exposes material facts")
        if decision == ALLOW_DECISION and material_fact_classes - verified_fact_classes:
            errors.append(f"{row.get('id')}: allowed decision exposes unverified material facts")
        if decision == ALLOW_DECISION and active_task_count:
            errors.append(f"{row.get('id')}: active resolution task cannot be allowed")

    decision_counts = {
        ALLOW_DECISION: len(allowed),
        BLOCK_DECISION: len(blocked),
    }
    block_reason_codes = sorted({
        reason
        for row in blocked
        for reason in (row.get("publicationDecision") or {}).get("reasonCodes") or []
    })
    block_reason_counts = {
        reason: sum(
            1 for row in blocked
            if reason in ((row.get("publicationDecision") or {}).get("reasonCodes") or [])
        )
        for reason in block_reason_codes
    }
    expected_summary = {
        "opportunityCount": len(opportunities),
        "openVerifiedCount": sum(
            1 for row in allowed
            if row.get("status") == "OPEN"
            and {"status", "deadline"} <= set(row.get("verifiedFactClasses") or [])
        ),
        "publishableCount": len(allowed),
        "reviewCount": len(blocked),
        "decisionCounts": decision_counts,
        "blockReasonCounts": block_reason_counts,
    }
    for key, expected in expected_summary.items():
        if summary.get(key) != expected:
            errors.append(f"summary.{key} does not match effective decisions")
    return errors


def assert_projection_integrity(projection: dict) -> None:
    errors = projection_integrity_errors(projection)
    if errors:
        raise ValueError("public projection integrity failed: " + "; ".join(errors))


def publication_decision(opportunity: dict, verified_fact_classes: list[str], tasks: list[dict]) -> dict:
    active_tasks = [task for task in tasks if task.get("status") in ACTIVE_RESOLUTION_STATES]
    material_fact_classes = set((opportunity.get("material_facts") or {}).keys())
    unverified_fact_classes = material_fact_classes - set(verified_fact_classes)
    blocked_fact_classes = set(unverified_fact_classes)
    for task in active_tasks:
        blocked_fact_classes.update(task.get("blocked_fact_classes") or [])

    state = opportunity.get("publication_state")
    allowed = state == "PUBLISHABLE" and not active_tasks and not unverified_fact_classes
    if allowed:
        reason_codes = ["PUBLICATION_STATE_PUBLISHABLE", "VERIFIED_FACTS_ONLY"]
    else:
        reason_codes = []
        if state != "PUBLISHABLE":
            reason_codes.append(f"PUBLICATION_STATE_{state or 'MISSING'}")
        if active_tasks:
            reason_codes.append("ACTIVE_RESOLUTION_TASK")
        if unverified_fact_classes:
            reason_codes.append("UNVERIFIED_MATERIAL_FACTS")
        if not reason_codes:
            reason_codes.append("FAIL_CLOSED_DEFAULT")

    return {
        "decision": ALLOW_DECISION if allowed else BLOCK_DECISION,
        "reasonCodes": reason_codes,
        "blockedFactClasses": sorted(blocked_fact_classes),
        "activeResolutionTaskCount": len(active_tasks),
    }


def build(bundle: dict) -> dict:
    evidence = {row["evidence_id"]: row for row in bundle["evidence"]}
    tasks_by_opportunity: dict[str, list[dict]] = {}
    for task in bundle.get("resolution_tasks") or []:
        tasks_by_opportunity.setdefault(task["opportunity_id"], []).append(task)
    projected = []
    for opportunity in bundle["opportunities"]:
        fact_evidence = opportunity.get("fact_evidence") or {}
        verified_fact_classes = sorted(
            fact_class for fact_class, refs in fact_evidence.items()
            if any(
                evidence.get(ref, {}).get("semantic_verdict") == "VERIFIED"
                and evidence.get(ref, {}).get("source_tier") in {"T1", "T1B"}
                and fact_class in evidence.get(ref, {}).get("supports_fact_classes", [])
                for ref in refs
            )
        )
        decision = publication_decision(
            opportunity,
            verified_fact_classes,
            tasks_by_opportunity.get(opportunity["opportunity_id"], []),
        )
        projected.append({
            "id": opportunity["opportunity_id"],
            "title": opportunity["title"],
            "programme": opportunity.get("programme"),
            "code": opportunity.get("code"),
            "status": opportunity["status"],
            "publicationState": opportunity["publication_state"],
            "materialFacts": (
                opportunity.get("material_facts") or {}
                if decision["decision"] == ALLOW_DECISION
                else {}
            ),
            "verifiedFactClasses": verified_fact_classes,
            "evidenceCount": len(opportunity.get("evidence_refs") or []),
            "publicationDecision": decision,
        })
    decision_counts = {
        ALLOW_DECISION: sum(
            1 for row in projected
            if row["publicationDecision"]["decision"] == ALLOW_DECISION
        ),
        BLOCK_DECISION: sum(
            1 for row in projected
            if row["publicationDecision"]["decision"] == BLOCK_DECISION
        ),
    }
    block_reason_codes = sorted({
        reason
        for row in projected
        if row["publicationDecision"]["decision"] == BLOCK_DECISION
        for reason in row["publicationDecision"]["reasonCodes"]
    })
    block_reason_counts = {
        reason: sum(
            1 for row in projected
            if row["publicationDecision"]["decision"] == BLOCK_DECISION
            and reason in row["publicationDecision"]["reasonCodes"]
        )
        for reason in block_reason_codes
    }
    projection = {
        "schemaVersion": 2,
        "asOf": bundle.get("as_of"),
        "policy": {
            "unverifiedMaterialFactsVisible": False,
            "automaticPublication": False,
            "decisionReasonsVisible": True,
            "summaryDerivedFromEffectiveDecisions": True,
            "integrityGate": "STRICT_FAIL_CLOSED",
        },
        "summary": {
            "opportunityCount": len(projected),
            "openVerifiedCount": sum(
                1 for row in projected
                if row["publicationDecision"]["decision"] == ALLOW_DECISION
                and row["status"] == "OPEN"
                and {"status", "deadline"} <= set(row["verifiedFactClasses"])
            ),
            "publishableCount": decision_counts[ALLOW_DECISION],
            "reviewCount": decision_counts[BLOCK_DECISION],
            "decisionCounts": decision_counts,
            "blockReasonCounts": block_reason_counts,
        },
        "opportunities": projected,
    }
    assert_projection_integrity(projection)
    return projection


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    projection = build(bundle)
    payload = render(projection)
    if args.check:
        assert_artifact_current(OUTPUT, payload)
    else:
        atomic_text(OUTPUT, payload)
    print(json.dumps({**projection["summary"], "mode": "CHECK" if args.check else "WRITE"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
