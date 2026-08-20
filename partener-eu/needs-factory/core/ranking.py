from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .engine import applicability_score


DIMENSION_WEIGHTS = {
    "magnitude": 0.25,
    "severity": 0.25,
    "gap_strength": 0.20,
    "call_relevance": 0.30,
}


def _unit(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric in [0,1]")
    value = float(value)
    if value < 0 or value > 1:
        raise ValueError(f"{name} must be in [0,1]")
    return value


def evidence_confidence(
    evidence_ids: Sequence[str],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    target_scope: str,
) -> Dict[str, Any]:
    """Calculate an explicit evidence cap without rewarding source volume.

    The strongest applicable source supplies 70% of the cap and the second
    independent source can supply the remaining 30%. A single-source need is
    therefore capped at 70% of that source's applicability.
    """
    scored: List[Dict[str, Any]] = []
    seen_source_keys = set()
    for evidence_id in evidence_ids:
        record = evidence_by_id.get(evidence_id)
        if not record:
            continue
        source_key = (
            record.get("source_document_id")
            or record.get("source_url")
            or record.get("source")
            or evidence_id
        )
        if source_key in seen_source_keys:
            continue
        seen_source_keys.add(source_key)
        scored.append({
            "evidence_id": evidence_id,
            "applicability": applicability_score(record, target_scope),
        })
    scored.sort(key=lambda item: (-item["applicability"], item["evidence_id"]))
    best = scored[0]["applicability"] if scored else 0.0
    second = scored[1]["applicability"] if len(scored) > 1 else 0.0
    cap = round(0.70 * best + 0.30 * second, 4)
    return {
        "confidence_cap": cap,
        "independent_evidence_count": len(scored),
        "evidence_scores": scored,
    }


def score_need(
    need: Mapping[str, Any],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Score one need transparently; evidence confidence multiplies substantive score."""
    dimensions = need.get("ranking_dimensions") or {}
    missing = [name for name in DIMENSION_WEIGHTS if name not in dimensions]
    if missing:
        return {
            "need_id": need.get("id"),
            "rankable": False,
            "score": None,
            "blocking_reason": "missing_ranking_dimensions",
            "missing_dimensions": missing,
        }

    normalized = {name: _unit(dimensions[name], name) for name in DIMENSION_WEIGHTS}
    substantive = sum(normalized[name] * weight for name, weight in DIMENSION_WEIGHTS.items())
    evidence = evidence_confidence(
        list(need.get("evidence_ids") or []),
        evidence_by_id,
        str(need.get("scope") or "national"),
    )
    supplied_confidence = need.get("confidence")
    if supplied_confidence is None:
        confidence_used = evidence["confidence_cap"]
    else:
        confidence_used = min(_unit(supplied_confidence, "confidence"), evidence["confidence_cap"])

    final = round(substantive * confidence_used * 100, 2)
    return {
        "need_id": need.get("id"),
        "rankable": True,
        "score": final,
        "substantive_score": round(substantive * 100, 2),
        "confidence_used": confidence_used,
        "confidence_cap": evidence["confidence_cap"],
        "dimensions": normalized,
        "weights": DIMENSION_WEIGHTS,
        "evidence": evidence,
    }


def rank_needs(
    needs: Iterable[Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    results = [score_need(need, evidence_by_id) for need in needs]
    rankable = [item for item in results if item["rankable"]]
    rankable.sort(key=lambda item: (-float(item["score"]), str(item["need_id"])))
    for index, item in enumerate(rankable, start=1):
        item["rank"] = index
    blocked = [item for item in results if not item["rankable"]]
    blocked.sort(key=lambda item: str(item["need_id"]))
    return {
        "schema_version": "nf.need_ranking.v0.1",
        "method": "weighted substantive score multiplied by evidence-confidence cap",
        "ranked": rankable,
        "blocked": blocked,
    }
