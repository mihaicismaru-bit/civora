from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from .engine import detect_evidence_gaps, sha256_json
from .primary_research import aggregate_responses, validate_raw_responses


CONSTRUCT_ALIASES = {
    "skills_confidence": ["skills_baseline"],
    "career_guidance_need": ["career_guidance"],
    "employer_exposure": ["practice_access"],
}


def _canonical_rows(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        [dict(row) for row in rows],
        key=lambda row: (
            str(row.get("respondent_id")),
            str(row.get("question_id")),
            str(row.get("grade")),
            str(row.get("qualification")),
            str(row.get("value")),
        ),
    )


def validate_respondent_strata(
    rows: Sequence[Mapping[str, Any]],
    population_validation: Mapping[str, Any],
) -> Dict[str, Any]:
    if not population_validation.get("valid"):
        return {"valid": False, "failures": [{"failure": "population_snapshot_not_valid"}]}

    snapshot = population_validation["normalized_snapshot"]
    capacities: Dict[Tuple[str, str], int] = {}
    for row in snapshot.get("count_by_grade_and_qualification", []):
        capacities[(str(row["grade"]), str(row["qualification"]))] = int(row["count"])

    respondent_stratum: Dict[str, Tuple[str, str]] = {}
    failures: List[Dict[str, Any]] = []
    for index, row in enumerate(rows):
        respondent = str(row.get("respondent_id") or "")
        stratum = (str(row.get("grade") or ""), str(row.get("qualification") or ""))
        if stratum not in capacities:
            failures.append({
                "row": index,
                "failure": "respondent_stratum_not_in_population_snapshot",
                "grade": stratum[0],
                "qualification": stratum[1],
            })
            continue
        previous = respondent_stratum.get(respondent)
        if previous and previous != stratum:
            failures.append({
                "respondent_id": respondent,
                "failure": "respondent_changes_stratum_across_answers",
                "first_stratum": list(previous),
                "new_stratum": list(stratum),
            })
        else:
            respondent_stratum[respondent] = stratum

    counts = Counter(respondent_stratum.values())
    for stratum, count in counts.items():
        capacity = capacities[stratum]
        if count > capacity:
            failures.append({
                "failure": "respondent_count_exceeds_stratum_population",
                "grade": stratum[0],
                "qualification": stratum[1],
                "respondent_n": count,
                "population_n": capacity,
            })

    return {
        "valid": not failures,
        "failures": failures,
        "respondent_n_by_stratum": [
            {"grade": grade, "qualification": qualification, "respondent_n": count, "population_n": capacities[(grade, qualification)]}
            for (grade, qualification), count in sorted(counts.items())
        ],
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

    strata_validation = validate_respondent_strata(rows, population_validation)
    if not strata_validation.get("valid"):
        raise ValueError("primary research respondent strata failed validation")

    aggregates = aggregate_responses(rows, plan)
    canonical_rows = _canonical_rows(rows)
    raw_sha = sha256_json(canonical_rows)
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
        "canonical_raw_rows": canonical_rows,
        "aggregate_sha256": aggregate_sha,
        "raw_validation": raw_validation,
        "strata_validation": strata_validation,
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
