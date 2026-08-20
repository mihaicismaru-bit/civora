from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


OFFICIAL_TIERS = {"A1", "A1-with-provenance-caveat", "A2", "A", "T1", "T1B"}
LOCAL_SCOPES = {"school", "beneficiary", "uat", "locality"}
VALID_MEASURE_TYPES = {"count", "share", "rate", "index", "currency", "qualitative", "score"}


class NeedsFactoryValidationError(ValueError):
    """Raised when a fail-closed Needs Factory rule is violated."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    text = str(value).strip()
    candidates = [("%Y-%m-%d", 10), ("%Y-%m", 7), ("%Y", 4)]
    for fmt, size in candidates:
        try:
            return datetime.strptime(text[:size], fmt).date()
        except ValueError:
            continue
    return None


def historical_availability(source: Mapping[str, Any], cutoff: Optional[str]) -> str:
    """Return verified/conditional/excluded for a historical source."""
    if not cutoff:
        return "verified"
    declared = source.get("historical_availability")
    if declared in {"verified", "conditional", "excluded"}:
        return str(declared)
    cutoff_date = _parse_date(cutoff)
    publication = _parse_date(source.get("publication_date") or source.get("source_date"))
    if cutoff_date and publication:
        return "verified" if publication <= cutoff_date else "excluded"
    return "conditional"


def validate_measure(measure: Mapping[str, Any]) -> List[str]:
    failures: List[str] = []
    measure_type = measure.get("measure_type")
    if measure_type not in VALID_MEASURE_TYPES:
        failures.append("invalid_or_missing_measure_type")
    if measure_type in {"rate", "share"}:
        if not measure.get("denominator_universe"):
            failures.append("missing_denominator_universe")
        if measure.get("value") is None:
            failures.append("missing_value")
    if measure_type == "rate" and measure.get("source_measure_type") == "share":
        failures.append("share_relabelled_as_rate")
    if measure_type == "share" and measure.get("source_measure_type") == "rate":
        failures.append("rate_relabelled_as_share")
    return failures


def validate_evidence_record(record: Mapping[str, Any], historical_cutoff: Optional[str] = None) -> Dict[str, Any]:
    failures: List[str] = []
    warnings: List[str] = []
    for field in ("id", "source", "tier", "territory"):
        if not record.get(field):
            failures.append(f"missing_{field}")
    if not (record.get("period") or record.get("source_date") or record.get("publication_date")):
        failures.append("missing_period_or_date")
    if record.get("quarantined") is True:
        failures.append("source_quarantined")
    if record.get("health") not in (None, "PASS"):
        failures.append("source_health_not_pass")

    availability = historical_availability(record, historical_cutoff)
    if availability == "excluded":
        failures.append("post_cutoff_source")
    elif availability == "conditional":
        warnings.append("historical_publication_provenance_conditional")

    for measure in record.get("measures", []) or []:
        failures.extend(validate_measure(measure))

    return {
        "id": record.get("id"),
        "valid": not failures,
        "failures": sorted(set(failures)),
        "warnings": sorted(set(warnings)),
        "historical_availability": availability,
    }


def _tier_score(tier: str) -> float:
    if tier in {"A1", "A"}:
        return 1.0
    if tier in {"A1-with-provenance-caveat", "T1", "T1B"}:
        return 0.9
    if tier == "A2":
        return 0.85
    if tier == "B":
        return 0.65
    return 0.35


def applicability_score(record: Mapping[str, Any], target_scope: str) -> float:
    """Score evidence applicability; never upgrades evidence validity."""
    tier = _tier_score(str(record.get("tier", "")))
    territory_fit = float(record.get("territory_fit", 1.0 if record.get("scope") == target_scope else 0.7))
    population_fit = float(record.get("population_fit", 0.8))
    recency = float(record.get("recency_score", 0.8))
    directness = float(record.get("directness", 0.8))
    score = tier * territory_fit * population_fit * recency * directness
    return round(max(0.0, min(1.0, score)), 4)


def validate_sample_consistency(values: Mapping[str, Optional[int]]) -> Dict[str, Any]:
    observed = {k: v for k, v in values.items() if v is not None}
    distinct = sorted(set(observed.values()))
    return {
        "valid": len(distinct) <= 1,
        "observed": observed,
        "distinct_values": distinct,
        "failure": None if len(distinct) <= 1 else "sample_n_inconsistent",
    }


def evidence_scope_satisfies_claim(claim_scope: str, evidence_scope: str) -> bool:
    if claim_scope in LOCAL_SCOPES:
        return evidence_scope in {claim_scope, "school", "beneficiary", "uat", "locality"}
    if claim_scope == "county":
        return evidence_scope in {"school", "beneficiary", "uat", "locality", "county"}
    if claim_scope == "region":
        return evidence_scope in {"school", "beneficiary", "uat", "locality", "county", "region"}
    return True


def evidence_matches_claim(claim: Mapping[str, Any], evidence: Mapping[str, Any]) -> bool:
    """Match evidence by territory, construct and directness rather than geography alone."""
    if not evidence_scope_satisfies_claim(
        str(claim.get("scope", "national")),
        str(evidence.get("scope", "national")),
    ):
        return False

    construct = claim.get("construct")
    if construct:
        supported = {str(item) for item in (evidence.get("constructs") or [])}
        if str(construct) not in supported:
            return False

    if claim.get("requires_direct_local") and evidence.get("direct_measurement") is not True:
        return False
    return True


def detect_evidence_gaps(claims: Sequence[Mapping[str, Any]], evidence_by_id: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    gaps: List[Dict[str, Any]] = []
    for claim in claims:
        ids = list(claim.get("evidence_ids") or [])
        matching = []
        for evidence_id in ids:
            evidence = evidence_by_id.get(evidence_id)
            if not evidence:
                continue
            if evidence_matches_claim(claim, evidence):
                matching.append(evidence_id)
        if claim.get("requires_direct_local") and not matching:
            gaps.append({
                "gap_id": f"GAP-{claim.get('id')}",
                "claim_id": claim.get("id"),
                "gap_type": claim.get("gap_type", "direct_local_evidence"),
                "construct": claim.get("construct"),
                "scope": claim.get("scope"),
                "blocking": bool(claim.get("priority", True)),
                "reason": "local_claim_without_direct_construct_matching_evidence",
            })
        elif not ids:
            gaps.append({
                "gap_id": f"GAP-{claim.get('id')}",
                "claim_id": claim.get("id"),
                "gap_type": "missing_evidence",
                "construct": claim.get("construct"),
                "scope": claim.get("scope"),
                "blocking": bool(claim.get("priority", True)),
                "reason": "claim_has_no_evidence",
            })
    return gaps


def validate_need(need: Mapping[str, Any], evidence_by_id: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    failures: List[str] = []
    evidence_ids = list(need.get("evidence_ids") or [])
    if need.get("priority", True) and not evidence_ids:
        failures.append("priority_need_without_evidence")
    found = [evidence_by_id[eid] for eid in evidence_ids if eid in evidence_by_id]
    if len(found) != len(evidence_ids):
        failures.append("unknown_evidence_reference")
    if need.get("priority", True) and found and not any(str(item.get("tier")) in OFFICIAL_TIERS for item in found):
        failures.append("priority_need_without_official_or_primary_evidence")
    if need.get("created_from_indicator"):
        failures.append("indicator_used_to_create_need")
    if need.get("compliance_only") and need.get("priority", True):
        failures.append("compliance_requirement_promoted_to_need_without_evidence")
    return {"id": need.get("id"), "valid": not failures, "failures": sorted(set(failures))}


def validate_traceability(
    chains: Sequence[Mapping[str, Any]],
    need_ids: Iterable[str],
    allowed_indicator_ids: Iterable[str],
) -> Dict[str, Any]:
    valid_needs = set(need_ids)
    indicators = set(allowed_indicator_ids)
    failures: List[Dict[str, Any]] = []
    covered: set[str] = set()
    for idx, chain in enumerate(chains):
        need_id = chain.get("need_id")
        if need_id not in valid_needs:
            failures.append({"index": idx, "failure": "unknown_need_id", "value": need_id})
            continue
        covered.add(str(need_id))
        if not chain.get("evidence_ids"):
            failures.append({"index": idx, "failure": "missing_evidence_ids"})
        if not chain.get("intervention"):
            failures.append({"index": idx, "failure": "missing_intervention"})
        indicator = chain.get("indicator_id")
        if indicator and indicator not in indicators:
            failures.append({"index": idx, "failure": "unknown_indicator_id", "value": indicator})
    missing_needs = sorted(valid_needs - covered)
    for need_id in missing_needs:
        failures.append({"failure": "need_without_traceability_chain", "value": need_id})
    return {"valid": not failures, "failures": failures, "covered_need_ids": sorted(covered)}


def validate_release(qa_report: Mapping[str, Any]) -> Dict[str, Any]:
    failures = list(qa_report.get("failures") or [])
    blocking = [
        f for f in failures
        if str(f.get("severity", "")).lower() == "critical"
        or (str(f.get("severity", "")).lower() == "high" and not f.get("waived"))
    ]
    gaps = [g for g in qa_report.get("evidence_gaps", []) or [] if g.get("blocking")]
    return {
        "ready_for_narrative": not blocking and not gaps,
        "blocking_failures": blocking,
        "blocking_evidence_gaps": gaps,
    }
