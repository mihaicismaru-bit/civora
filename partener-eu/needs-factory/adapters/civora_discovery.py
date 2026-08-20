from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence

from core.engine import validate_measure


class CivoraDiscoveryError(ValueError):
    """Raised when discovery output cannot be promoted into evidence candidates."""


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    text = str(value).strip()
    for fmt, size in (("%Y-%m-%d", 10), ("%Y-%m", 7), ("%Y", 4)):
        try:
            return datetime.strptime(text[:size], fmt).date()
        except ValueError:
            continue
    return None


def _scope_allowed(scope: str, preferred_scopes: Sequence[str], direct_local_required: bool) -> bool:
    if direct_local_required:
        return scope in {"school", "beneficiary", "uat", "locality"} and scope in set(preferred_scopes)
    return scope in set(preferred_scopes)


def validate_discovery_receipt(
    receipt: Mapping[str, Any],
    task: Mapping[str, Any],
    *,
    historical_cutoff: Optional[str] = None,
    media_may_support_priority_need: bool = False,
) -> Dict[str, Any]:
    failures: List[str] = []
    warnings: List[str] = []
    for field in ("candidate_id", "requirement_id", "source", "source_family", "final_url", "health", "semantic_sha256", "scope", "territory"):
        if receipt.get(field) in (None, ""):
            failures.append(f"missing_{field}")
    if str(receipt.get("requirement_id")) != str(task.get("requirement_id")):
        failures.append("requirement_id_mismatch")
    if receipt.get("health") != "PASS":
        failures.append("source_health_not_pass")
    if receipt.get("quarantined") is True:
        failures.append("source_quarantined")
    if not _scope_allowed(str(receipt.get("scope") or ""), task.get("preferred_scopes") or [], bool(task.get("direct_local_required"))):
        failures.append("scope_not_acceptable_for_task")
    construct = str(task.get("construct") or "")
    constructs = {str(item) for item in (receipt.get("constructs") or [])}
    if construct not in constructs:
        failures.append("construct_not_supported")
    if task.get("direct_local_required") and receipt.get("direct_measurement") is not True:
        failures.append("direct_local_measurement_required")

    source_family = str(receipt.get("source_family") or "")
    if task.get("priority") == "primary" and source_family.lower() in {"media", "press", "news"}:
        if not media_may_support_priority_need:
            failures.append("media_cannot_support_priority_requirement")
        else:
            warnings.append("media_source_requires_independent_official_confirmation")

    cutoff = _parse_date(historical_cutoff)
    source_date = _parse_date(receipt.get("publication_date") or receipt.get("source_date") or receipt.get("period"))
    if cutoff and source_date and source_date > cutoff:
        failures.append("post_cutoff_source")
    if cutoff and not source_date:
        warnings.append("historical_source_date_unverified")

    facts = list(receipt.get("facts") or [])
    if not facts:
        failures.append("no_structured_facts")
    for fact_index, fact in enumerate(facts):
        fact_construct = str(fact.get("construct") or "")
        if fact_construct != construct:
            failures.append(f"fact_construct_mismatch:{fact_index}")
        measures = list(fact.get("measures") or [])
        if not measures:
            failures.append(f"fact_without_measures:{fact_index}")
        allowed_measure_types = set(task.get("allowed_measure_types") or [])
        for measure_index, measure in enumerate(measures):
            measure_failures = validate_measure(measure)
            for failure in measure_failures:
                failures.append(f"measure:{fact_index}:{measure_index}:{failure}")
            measure_type = measure.get("measure_type")
            if allowed_measure_types and measure_type not in allowed_measure_types:
                failures.append(f"measure_type_not_allowed:{fact_index}:{measure_index}:{measure_type}")

    return {
        "valid": not failures,
        "failures": sorted(set(failures)),
        "warnings": sorted(set(warnings)),
        "requirement_id": task.get("requirement_id"),
        "candidate_id": receipt.get("candidate_id"),
    }


def promote_discovery_receipt(
    receipt: Mapping[str, Any],
    task: Mapping[str, Any],
    *,
    historical_cutoff: Optional[str] = None,
) -> Dict[str, Any]:
    validation = validate_discovery_receipt(receipt, task, historical_cutoff=historical_cutoff)
    if not validation["valid"]:
        raise CivoraDiscoveryError(",".join(validation["failures"]))

    evidence = []
    for index, fact in enumerate(receipt.get("facts", []) or [], start=1):
        evidence_id = f"EV-CIV-{receipt['candidate_id']}-{index:02d}"
        evidence.append({
            "id": evidence_id,
            "source": receipt.get("source"),
            "source_type": "external_discovery",
            "source_family": receipt.get("source_family"),
            "source_url": receipt.get("final_url"),
            "source_document_id": receipt.get("source_document_id"),
            "tier": receipt.get("tier") or ("A1" if receipt.get("official") else "B"),
            "health": receipt.get("health"),
            "quarantined": bool(receipt.get("quarantined")),
            "raw_sha256": receipt.get("raw_sha256"),
            "semantic_sha256": receipt.get("semantic_sha256"),
            "territory": fact.get("territory") or receipt.get("territory"),
            "scope": fact.get("scope") or receipt.get("scope"),
            "population": fact.get("population") or receipt.get("population"),
            "constructs": [str(task.get("construct"))],
            "direct_measurement": bool(receipt.get("direct_measurement")),
            "period": fact.get("period") or receipt.get("period"),
            "source_date": receipt.get("source_date"),
            "publication_date": receipt.get("publication_date"),
            "historical_availability": "verified" if not validation["warnings"] else "conditional",
            "measures": [dict(measure) for measure in (fact.get("measures") or [])],
            "provenance": {
                "provider": "CIVORA",
                "candidate_id": receipt.get("candidate_id"),
                "requirement_id": receipt.get("requirement_id"),
                "last_success": receipt.get("last_success"),
                "material_fact_state": receipt.get("material_fact_state"),
            },
        })
    return {
        "schema_version": "nf.discovery_promotion.v0.1",
        "requirement_id": task.get("requirement_id"),
        "candidate_id": receipt.get("candidate_id"),
        "validation": validation,
        "evidence": evidence,
    }


def batch_promote(
    receipts: Sequence[Mapping[str, Any]],
    request: Mapping[str, Any],
) -> Dict[str, Any]:
    tasks = {str(task["requirement_id"]): task for task in request.get("tasks", []) or []}
    accepted = []
    rejected = []
    evidence = {}
    for receipt in receipts:
        req_id = str(receipt.get("requirement_id") or "")
        task = tasks.get(req_id)
        if not task:
            rejected.append({"requirement_id": req_id, "candidate_id": receipt.get("candidate_id"), "accepted": False, "failures": ["unknown_requirement_id"]})
            continue
        try:
            promoted = promote_discovery_receipt(receipt, task, historical_cutoff=request.get("historical_cutoff"))
        except CivoraDiscoveryError as exc:
            rejected.append({"requirement_id": req_id, "candidate_id": receipt.get("candidate_id"), "accepted": False, "failures": str(exc).split(",")})
            continue
        accepted.append({"requirement_id": req_id, "candidate_id": receipt.get("candidate_id"), "accepted": True, "evidence_ids": [item["id"] for item in promoted["evidence"]]})
        for item in promoted["evidence"]:
            evidence[item["id"]] = item
    return {
        "schema_version": "nf.discovery_batch.v0.1",
        "accepted": accepted,
        "rejected": rejected,
        "evidence": evidence,
    }
