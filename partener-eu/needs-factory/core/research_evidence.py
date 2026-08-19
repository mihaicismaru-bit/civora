from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

from .engine import detect_evidence_gaps, sha256_json
from .primary_research import aggregate_responses, validate_raw_responses


CONSTRUCT_ALIASES = {
    "skills_confidence": ["skills_baseline"],
    "career_guidance_need": ["career_guidance"],
    "employer_exposure": ["practice_access"],
}


def _measure_records(question: Mapping[str, Any], aggregate: Mapping[str, Any]) -> List[Dict[str, Any]]:
    qid = str(question["question_id"])
    valid_n = int(aggregate.get("valid_n") or 0)
    measures: List[Dict[str, Any]] = [
        {
            "name": "valid_responses",
            "measure_type": "count",
            "value": valid_n,
            "unit": "responses",
            "calculated": True,
        }
    ]
    response_type = question.get("response_type")
    if response_type in {"likert_1_5", "likert_1_5_optional"} and valid_n:
        measures.extend([
            {
                "name": "median",
                "measure_type": "score",
                "value": aggregate.get("median"),
                "unit": "Likert 1-5",
                "calculated": True,
            },
            {
                "name": "top2_share",
                "measure_type": "share",
                "source_measure_type": "share",
                "value": aggregate.get("top2_share"),
                "numerator": aggregate.get("top2_n"),
                "denominator_universe": f"valid responses to {qid}",
                "unit": "proportion",
                "calculated": True,
            },
        ])
    elif response_type == "yes_no" and valid_n:
        yes_n = int((aggregate.get("counts") or {}).get("yes", 0))
        measures.append({
            "name": "yes_share",
            "measure_type": "share",
            "source_measure_type": "share",
            "value": aggregate.get("yes_share"),
            "numerator": yes_n,
            "denominator_universe": f"valid responses to {qid}",
            "unit": "proportion",
            "calculated": True,
        })
    return measures


def promote_primary_research_evidence(
    rows: Sequence[Mapping[str, Any]],
    plan: Mapping[str, Any],
    population_validation: Mapping[str, Any],
    *,
    territory: str,
    school_identity: str,
    period: str,
    source_document_id: str,
) -> Dict[str, Any]:
    if not population_validation.get("valid"):
        raise ValueError("population snapshot must pass validation before primary research promotion")
    raw_validation = validate_raw_responses(rows, plan)
    if not raw_validation.get("valid"):
        raise ValueError("raw primary research responses failed validation")

    snapshot = population_validation["normalized_snapshot"]
    if plan.get("population_snapshot_id") != snapshot.get("snapshot_id"):
        raise ValueError("primary research plan/population snapshot mismatch")
    if plan.get("population_n") != snapshot.get("eligible_population_n"):
        raise ValueError("primary research plan population size mismatch")

    aggregates = aggregate_responses(rows, plan)
    raw_sha = sha256_json([dict(row) for row in rows])
    aggregate_sha = sha256_json(aggregates)
    evidence: Dict[str, Dict[str, Any]] = {}

    for question in plan.get("questions", []):
        qid = str(question["question_id"])
        construct = str(question["construct"])
        aliases = list(CONSTRUCT_ALIASES.get(construct, []))
        constructs = sorted(set([construct] + aliases))
        aggregate = aggregates["aggregates"].get(qid, {"valid_n": 0, "counts": {}})
        evidence_id = f"EV-PR-{qid}-{construct.upper().replace('_', '-')}"
        semantic_payload = {
            "question_id": qid,
            "constructs": constructs,
            "aggregate": aggregate,
            "population_snapshot_id": snapshot["snapshot_id"],
            "period": period,
        }
        evidence[evidence_id] = {
            "id": evidence_id,
            "source": f"Needs Factory primary research – {school_identity}",
            "source_type": "primary_research",
            "source_document_id": source_document_id,
            "tier": "A",
            "health": "PASS",
            "quarantined": False,
            "territory": territory,
            "scope": "school",
            "population": f"eligible population snapshot {snapshot['snapshot_id']}",
            "population_snapshot_id": snapshot["snapshot_id"],
            "constructs": constructs,
            "direct_measurement": True,
            "period": period,
            "raw_sha256": raw_sha,
            "semantic_sha256": sha256_json(semantic_payload),
            "source_population_sha256": population_validation.get("snapshot_sha256"),
            "measures": _measure_records(question, aggregate),
            "question": {
                "question_id": qid,
                "prompt": question.get("prompt"),
                "response_type": question.get("response_type"),
            },
        }

    return {
        "schema_version": "nf.primary_research_evidence.v0.1",
        "population_snapshot_id": snapshot["snapshot_id"],
        "population_snapshot_sha256": population_validation.get("snapshot_sha256"),
        "raw_response_sha256": raw_sha,
        "aggregate_sha256": aggregate_sha,
        "raw_validation": raw_validation,
        "aggregates": aggregates,
        "evidence": evidence,
    }


def attach_matching_research_evidence(
    claims: Sequence[Mapping[str, Any]],
    existing_evidence: Mapping[str, Mapping[str, Any]],
    primary_evidence: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    combined = {**{str(k): dict(v) for k, v in existing_evidence.items()}, **{str(k): dict(v) for k, v in primary_evidence.items()}}
    updated_claims: List[Dict[str, Any]] = []
    for claim in claims:
        item = dict(claim)
        ids = list(item.get("evidence_ids") or [])
        construct = str(item.get("construct") or "")
        for evidence_id, record in primary_evidence.items():
            if construct and construct in {str(value) for value in (record.get("constructs") or [])}:
                if evidence_id not in ids:
                    ids.append(evidence_id)
        item["evidence_ids"] = ids
        updated_claims.append(item)
    unresolved = detect_evidence_gaps(updated_claims, combined)
    return {
        "claims": updated_claims,
        "evidence": combined,
        "unresolved_gaps": unresolved,
    }
