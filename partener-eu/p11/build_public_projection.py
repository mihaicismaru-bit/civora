#!/usr/bin/env python3
"""Build the fail-closed browser projection from the canonical P11 bundle."""
from __future__ import annotations

import argparse
import datetime
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
PROJECTION_SCHEMA_VERSION = 4


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


def utc_timestamp(value: object, field: str) -> datetime.datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(datetime.timezone.utc)


def evidence_age_seconds(as_of: object, observed_at: object) -> int:
    age = int((utc_timestamp(as_of, "asOf") - utc_timestamp(observed_at, "observedAt")).total_seconds())
    if age < 0:
        raise ValueError("verified evidence cannot be observed after projection asOf")
    return age


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
    as_of = projection.get("asOf")
    try:
        utc_timestamp(as_of, "asOf")
    except ValueError as exc:
        errors.append(str(exc))
    if projection.get("schemaVersion") != PROJECTION_SCHEMA_VERSION:
        errors.append(f"schemaVersion must be {PROJECTION_SCHEMA_VERSION}")
    if not isinstance(policy, dict):
        errors.append("policy must be an object")
    else:
        if policy.get("unverifiedMaterialFactsVisible") is not False:
            errors.append("policy must hide unverified material facts")
        if policy.get("automaticPublication") is not False:
            errors.append("policy must disable automatic publication")
        if policy.get("summaryDerivedFromEffectiveDecisions") is not True:
            errors.append("policy must derive summary from effective decisions")
        if policy.get("verificationProvenanceVisible") is not True:
            errors.append("policy must expose verification provenance")
        if policy.get("freshnessReference") != "PROJECTION_AS_OF":
            errors.append("policy must define projection asOf as freshness reference")
        if policy.get("freshnessTelemetryAuthorizesPublication") is not False:
            errors.append("freshness telemetry must not authorize publication")
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
        verification_evidence = row.get("verificationEvidence")
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
        verified_fact_class_list = row.get("verifiedFactClasses") or []
        verified_fact_classes = (
            set(verified_fact_class_list)
            if isinstance(verified_fact_class_list, list)
            and all(isinstance(value, str) and value for value in verified_fact_class_list)
            else set()
        )
        if not isinstance(row.get("verifiedFactClasses"), list):
            errors.append(f"{row.get('id')}: verified fact classes must be a list")
        elif not all(isinstance(value, str) and value for value in verified_fact_class_list):
            errors.append(f"{row.get('id')}: verified fact classes must be non-empty strings")
        elif verified_fact_class_list != sorted(verified_fact_classes):
            errors.append(f"{row.get('id')}: verified fact classes must be sorted and unique")

        provenance_fact_classes = set()
        provenance_ids = []
        if not isinstance(verification_evidence, list):
            errors.append(f"{row.get('id')}: verification evidence must be a list")
        else:
            for item in verification_evidence:
                if not isinstance(item, dict):
                    errors.append(f"{row.get('id')}: verification evidence entries must be objects")
                    continue
                evidence_id = item.get("evidenceId")
                supported = item.get("supportedFactClasses")
                if not isinstance(evidence_id, str) or not evidence_id:
                    errors.append(f"{row.get('id')}: verification evidence id required")
                else:
                    provenance_ids.append(evidence_id)
                if item.get("sourceTier") not in {"T1", "T1B"}:
                    errors.append(f"{row.get('id')}: verification evidence must be T1 or T1B")
                if not str(item.get("sourceUrl") or "").startswith("https://"):
                    errors.append(f"{row.get('id')}: verification evidence requires an HTTPS source URL")
                if not item.get("observedAt"):
                    errors.append(f"{row.get('id')}: verification evidence observedAt required")
                else:
                    try:
                        expected_age = evidence_age_seconds(as_of, item.get("observedAt"))
                        age_value = item.get("ageSecondsAtProjection")
                        if (
                            not isinstance(age_value, int)
                            or isinstance(age_value, bool)
                            or age_value < 0
                            or age_value != expected_age
                        ):
                            errors.append(f"{row.get('id')}: verification evidence age does not match timestamps")
                    except ValueError as exc:
                        errors.append(f"{row.get('id')}: {exc}")
                if (
                    not isinstance(supported, list)
                    or not supported
                    or not all(isinstance(value, str) and value for value in supported)
                ):
                    errors.append(f"{row.get('id')}: verification evidence fact classes required")
                elif supported != sorted(set(supported)):
                    errors.append(f"{row.get('id')}: verification evidence fact classes must be sorted and unique")
                else:
                    provenance_fact_classes.update(supported)
            if len(provenance_ids) != len(verification_evidence) or provenance_ids != sorted(set(provenance_ids)):
                errors.append(f"{row.get('id')}: verification evidence ids must be sorted and unique")
            if row.get("verifiedEvidenceCount") != len(verification_evidence):
                errors.append(f"{row.get('id')}: verified evidence count does not match provenance")
        if provenance_fact_classes != verified_fact_classes:
            errors.append(f"{row.get('id')}: verification provenance does not match verified fact classes")
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
    verification_evidence = [
        item
        for row in opportunities
        if isinstance(row, dict)
        for item in (row.get("verificationEvidence") or [])
        if isinstance(item, dict)
    ]
    observed_at_values = sorted(
        item.get("observedAt")
        for item in verification_evidence
        if isinstance(item.get("observedAt"), str) and item.get("observedAt")
    )
    age_values = [
        item.get("ageSecondsAtProjection")
        for item in verification_evidence
        if isinstance(item.get("ageSecondsAtProjection"), int)
        and not isinstance(item.get("ageSecondsAtProjection"), bool)
        and item.get("ageSecondsAtProjection") >= 0
    ]
    expected_freshness = {
        "referenceTime": as_of,
        "verifiedEvidenceLinkCount": len(verification_evidence),
        "oldestObservedAt": observed_at_values[0] if observed_at_values else None,
        "newestObservedAt": observed_at_values[-1] if observed_at_values else None,
        "maximumAgeSeconds": max(age_values) if age_values else None,
        "minimumAgeSeconds": min(age_values) if age_values else None,
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
        "verificationFreshness": expected_freshness,
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


def verification_provenance(opportunity: dict, evidence: dict[str, dict], as_of: object) -> list[dict]:
    """Return deterministic public provenance for semantically verified fact classes."""
    provenance: dict[str, dict] = {}
    for fact_class, refs in (opportunity.get("fact_evidence") or {}).items():
        for evidence_id in refs:
            item = evidence.get(evidence_id) or {}
            if (
                item.get("semantic_verdict") != "VERIFIED"
                or item.get("source_tier") not in {"T1", "T1B"}
                or fact_class not in (item.get("supports_fact_classes") or [])
            ):
                continue
            entry = provenance.setdefault(evidence_id, {
                "evidenceId": evidence_id,
                "sourceTier": item.get("source_tier"),
                "sourceUrl": item.get("source_url"),
                "observedAt": item.get("observed_at"),
                "ageSecondsAtProjection": evidence_age_seconds(as_of, item.get("observed_at")),
                "supportedFactClasses": [],
            })
            entry["supportedFactClasses"].append(fact_class)
    return [
        {**provenance[evidence_id], "supportedFactClasses": sorted(set(provenance[evidence_id]["supportedFactClasses"]))}
        for evidence_id in sorted(provenance)
    ]


def build(bundle: dict) -> dict:
    evidence = {row["evidence_id"]: row for row in bundle["evidence"]}
    tasks_by_opportunity: dict[str, list[dict]] = {}
    for task in bundle.get("resolution_tasks") or []:
        tasks_by_opportunity.setdefault(task["opportunity_id"], []).append(task)
    projected = []
    for opportunity in bundle["opportunities"]:
        provenance = verification_provenance(opportunity, evidence, bundle.get("as_of"))
        verified_fact_classes = sorted({
            fact_class
            for item in provenance
            for fact_class in item["supportedFactClasses"]
        })
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
            "verifiedEvidenceCount": len(provenance),
            "verificationEvidence": provenance,
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
    verification_evidence = [
        item
        for row in projected
        for item in row["verificationEvidence"]
    ]
    observed_at_values = sorted(item["observedAt"] for item in verification_evidence)
    age_values = [item["ageSecondsAtProjection"] for item in verification_evidence]
    projection = {
        "schemaVersion": PROJECTION_SCHEMA_VERSION,
        "asOf": bundle.get("as_of"),
        "policy": {
            "unverifiedMaterialFactsVisible": False,
            "automaticPublication": False,
            "decisionReasonsVisible": True,
            "summaryDerivedFromEffectiveDecisions": True,
            "integrityGate": "STRICT_FAIL_CLOSED",
            "verificationProvenanceVisible": True,
            "freshnessReference": "PROJECTION_AS_OF",
            "freshnessTelemetryAuthorizesPublication": False,
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
            "verificationFreshness": {
                "referenceTime": bundle.get("as_of"),
                "verifiedEvidenceLinkCount": len(verification_evidence),
                "oldestObservedAt": observed_at_values[0] if observed_at_values else None,
                "newestObservedAt": observed_at_values[-1] if observed_at_values else None,
                "maximumAgeSeconds": max(age_values) if age_values else None,
                "minimumAgeSeconds": min(age_values) if age_values else None,
            },
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
