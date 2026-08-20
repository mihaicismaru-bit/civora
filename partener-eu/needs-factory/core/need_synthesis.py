from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Sequence


RANKING_DIMENSIONS = ("magnitude", "severity", "gap_strength", "call_relevance")
ALLOWED_DECISIONS = {"supported", "not_supported", "insufficient"}
FORBIDDEN_DECISION_FIELDS = {"cause", "causes", "root_cause", "root_causes", "effect", "effects"}
LOCAL_SCOPES = {"school", "beneficiary", "uat", "locality"}


class NeedSynthesisError(ValueError):
    """Raised when semantic need synthesis violates the evidence contract."""


def _sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_need_hypotheses(
    research_request: Mapping[str, Any],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> Dict[str, Any]:
    allowed_constructs = {str(item) for item in (policy.get("need_candidate_constructs") or [])}
    context_only = {str(item) for item in (policy.get("context_only_constructs") or [])}
    failures = []
    if allowed_constructs & context_only:
        failures.append("construct_list_overlap")
    if not allowed_constructs:
        failures.append("missing_need_candidate_constructs")
    if failures:
        raise NeedSynthesisError(",".join(failures))

    requirements = {str(req["requirement_id"]): req for req in (research_request.get("requirements") or [])}
    hypotheses = []
    for requirement_id, req in sorted(requirements.items()):
        construct = str(req.get("construct") or "")
        if construct not in allowed_constructs:
            continue
        evidence_ids = []
        for evidence_id, record in sorted(evidence_by_id.items()):
            constructs = {str(item) for item in (record.get("constructs") or [])}
            if construct not in constructs:
                continue
            if record.get("health") not in (None, "PASS") or record.get("quarantined") is True:
                continue
            evidence_ids.append(str(evidence_id))
        scope = "school" if req.get("direct_local_required") else (req.get("preferred_scopes") or ["national"])[0]
        direct_local_ready = any(
            evidence_by_id[eid].get("direct_measurement") is True
            and str(evidence_by_id[eid].get("scope")) in LOCAL_SCOPES
            for eid in evidence_ids
        )
        status = "EVIDENCE_AVAILABLE"
        if not evidence_ids:
            status = "INSUFFICIENT_EVIDENCE"
        elif req.get("direct_local_required") and not direct_local_ready:
            status = "INSUFFICIENT_DIRECT_LOCAL_EVIDENCE"
        hypotheses.append({
            "hypothesis_id": f"HYP-{requirement_id}",
            "requirement_id": requirement_id,
            "construct": construct,
            "scope": scope,
            "priority": req.get("priority"),
            "direct_local_required": bool(req.get("direct_local_required")),
            "evidence_ids": evidence_ids,
            "status": status,
            "prohibited_overclaim": req.get("prohibited_overclaim"),
            "decision_contract": {
                "allowed_decisions": sorted(ALLOWED_DECISIONS),
                "causal_fields_forbidden": True,
                "ranking_dimensions": list(RANKING_DIMENSIONS),
                "evidence_refs_required_for_each_ranking_dimension": True,
            },
        })
    result = {
        "schema_version": "nf.need_hypotheses.v0.1",
        "project_id": research_request.get("project_id"),
        "profile_id": policy.get("profile_id"),
        "hypotheses": hypotheses,
    }
    result["hypotheses_sha256"] = _sha256(result)
    return result


def validate_need_decision(
    decision: Mapping[str, Any],
    hypothesis: Mapping[str, Any],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    if str(decision.get("hypothesis_id")) != str(hypothesis.get("hypothesis_id")):
        failures.append({"failure": "hypothesis_id_mismatch"})
    verdict = decision.get("decision")
    if verdict not in ALLOWED_DECISIONS:
        failures.append({"failure": "invalid_decision", "value": verdict})
    forbidden = sorted(field for field in FORBIDDEN_DECISION_FIELDS if field in decision)
    if forbidden:
        failures.append({"failure": "causal_fields_forbidden_at_need_synthesis", "fields": forbidden})
    if decision.get("prohibited_overclaim") != hypothesis.get("prohibited_overclaim"):
        failures.append({"failure": "prohibited_overclaim_not_preserved"})

    evidence_ids = [str(item) for item in (decision.get("evidence_ids") or [])]
    allowed_evidence = {str(item) for item in (hypothesis.get("evidence_ids") or [])}
    unknown = sorted(set(evidence_ids) - allowed_evidence)
    if unknown:
        failures.append({"failure": "decision_uses_unapproved_evidence", "values": unknown})

    if verdict == "supported":
        if hypothesis.get("status") != "EVIDENCE_AVAILABLE":
            failures.append({"failure": "supported_decision_on_unready_hypothesis", "status": hypothesis.get("status")})
        for field in ("need_title", "need_statement"):
            if not str(decision.get(field) or "").strip():
                failures.append({"failure": f"missing_{field}"})
        if not evidence_ids:
            failures.append({"failure": "supported_need_without_evidence"})
        if hypothesis.get("direct_local_required"):
            has_direct = False
            for evidence_id in evidence_ids:
                record = evidence_by_id.get(evidence_id) or {}
                if record.get("direct_measurement") is True and str(record.get("scope")) in LOCAL_SCOPES:
                    has_direct = True
                    break
            if not has_direct:
                failures.append({"failure": "local_need_without_direct_local_evidence"})
        dimensions = decision.get("ranking_dimensions") or {}
        basis = decision.get("ranking_evidence") or {}
        for dimension in RANKING_DIMENSIONS:
            value = dimensions.get(dimension)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
                failures.append({"failure": "invalid_ranking_dimension", "dimension": dimension, "value": value})
            refs = [str(item) for item in (basis.get(dimension) or [])]
            if not refs:
                failures.append({"failure": "ranking_dimension_without_evidence", "dimension": dimension})
            extra = sorted(set(refs) - set(evidence_ids))
            if extra:
                failures.append({"failure": "ranking_dimension_uses_unapproved_evidence", "dimension": dimension, "values": extra})
    else:
        for field in ("need_title", "need_statement", "ranking_dimensions", "ranking_evidence"):
            if decision.get(field) not in (None, "", {}, []):
                failures.append({"failure": "non_supported_decision_contains_promotable_need_fields", "field": field})

    decision_receipt = {
        "hypothesis_id": hypothesis.get("hypothesis_id"),
        "decision": verdict,
        "evidence_ids": evidence_ids,
        "failures": failures,
    }
    return {
        "schema_version": "nf.need_decision_validation.v0.1",
        "valid": not failures,
        "failures": failures,
        "decision_receipt_sha256": _sha256(decision_receipt),
    }


def promote_need_decision(
    decision: Mapping[str, Any],
    hypothesis: Mapping[str, Any],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any] | None:
    validation = validate_need_decision(decision, hypothesis, evidence_by_id)
    if not validation["valid"]:
        raise NeedSynthesisError(json.dumps(validation["failures"], ensure_ascii=False, sort_keys=True))
    if decision.get("decision") != "supported":
        return None
    semantic_identity = {
        "hypothesis_id": hypothesis.get("hypothesis_id"),
        "need_statement": decision.get("need_statement"),
        "evidence_ids": sorted(str(item) for item in decision.get("evidence_ids") or []),
    }
    need_id = f"NEED-{_sha256(semantic_identity)[:12].upper()}"
    return {
        "id": need_id,
        "title": str(decision["need_title"]),
        "statement": str(decision["need_statement"]),
        "scope": hypothesis.get("scope"),
        "priority": True,
        "evidence_ids": sorted(str(item) for item in decision.get("evidence_ids") or []),
        "confidence": float(decision.get("confidence", 1.0)),
        "ranking_dimensions": {dimension: float(decision["ranking_dimensions"][dimension]) for dimension in RANKING_DIMENSIONS},
        "ranking_evidence": {dimension: sorted(str(item) for item in decision["ranking_evidence"][dimension]) for dimension in RANKING_DIMENSIONS},
        "prohibited_overclaim": hypothesis.get("prohibited_overclaim"),
        "created_from_indicator": False,
        "compliance_only": False,
        "semantic_decision": {
            "hypothesis_id": hypothesis.get("hypothesis_id"),
            "decision_receipt_sha256": validation["decision_receipt_sha256"],
        },
    }


def promote_decision_set(
    hypotheses_bundle: Mapping[str, Any],
    decisions: Sequence[Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    hypotheses = {str(item["hypothesis_id"]): item for item in (hypotheses_bundle.get("hypotheses") or [])}
    seen = set()
    needs = []
    validations = []
    failures = []
    for decision in decisions:
        hypothesis_id = str(decision.get("hypothesis_id") or "")
        if hypothesis_id in seen:
            failures.append({"failure": "duplicate_hypothesis_decision", "hypothesis_id": hypothesis_id})
            continue
        seen.add(hypothesis_id)
        hypothesis = hypotheses.get(hypothesis_id)
        if not hypothesis:
            failures.append({"failure": "unknown_hypothesis_decision", "hypothesis_id": hypothesis_id})
            continue
        validation = validate_need_decision(decision, hypothesis, evidence_by_id)
        validations.append({"hypothesis_id": hypothesis_id, **validation})
        if not validation["valid"]:
            failures.extend({"hypothesis_id": hypothesis_id, **item} for item in validation["failures"])
            continue
        promoted = promote_need_decision(decision, hypothesis, evidence_by_id)
        if promoted:
            needs.append(promoted)

    missing_decisions = sorted(set(hypotheses) - seen)
    if missing_decisions:
        failures.append({"failure": "hypotheses_without_decisions", "values": missing_decisions})
    state = "READY_FOR_RANKING" if not failures and needs else ("NO_SUPPORTED_NEEDS" if not failures else "BLOCKED_SEMANTIC")
    return {
        "schema_version": "nf.need_decision_set.v0.1",
        "state": state,
        "needs": needs,
        "validations": validations,
        "failures": failures,
        "decided_hypotheses": sorted(seen),
        "missing_hypotheses": missing_decisions,
    }
