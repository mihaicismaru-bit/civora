#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
SCORING_CONTRACT_PATH = EUCONS / "prospects" / "prospect_scoring_contract.json"
CLIENT_CONTRACT_PATH = EUCONS / "prospects" / "client_finder_contract.json"
VALIDATOR_PATH = EUCONS / "validation" / "validate_client_finder_contract.py"
ENGINE_PATH = EUCONS / "prospects" / "client_finder_engine.py"
SERVICE_REGISTRY_PATH = EUCONS / "services" / "service_registry.json"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_module("client_finder_contract_validator", VALIDATOR_PATH)
ENGINE = _load_module("client_finder_engine", ENGINE_PATH)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_scoring_contract(contract: dict[str, Any], client_contract: dict[str, Any]) -> None:
    if contract.get("id") != "R06-CF-SCORING-001" or contract.get("status") != "CANONICAL":
        raise ValueError("prospect scoring contract drift")
    if contract.get("score_semantics") != "COMMERCIAL_RESEARCH_PRIORITY_NOT_ELIGIBILITY_OR_CONVERSION_PROBABILITY":
        raise ValueError("score semantics failed open")
    for dependency in (contract.get("canonical_dependencies") or {}).values():
        if not (ROOT / dependency).is_file():
            raise ValueError(f"missing canonical dependency: {dependency}")
    VALIDATOR.validate_contract(client_contract)
    components = contract.get("positive_components") or {}
    expected_components = {"source_quality", "freshness", "signal_strength", "service_coherence", "actionability"}
    if set(components) != expected_components:
        raise ValueError("positive component taxonomy drift")
    if sum(int(row.get("max_points", -1)) for row in components.values()) != 100:
        raise ValueError("positive scoring maximum must equal 100")
    allowed_sources = set(client_contract["source_contract"]["allowed_types"])
    source_weights = components["source_quality"].get("basis_points_by_source_type") or {}
    if set(source_weights) != allowed_sources or any(not isinstance(value, int) or not 0 <= value <= 1000 for value in source_weights.values()):
        raise ValueError("source quality weights incomplete or invalid")
    if components["signal_strength"].get("lane_points", {}).keys() != {"P0", "P1", "P2"}:
        raise ValueError("signal lane weights incomplete")
    penalties = contract.get("uncertainty_penalties") or {}
    if penalties.get("maximum_total_penalty") != penalties.get("unknown_assertion_max") + penalties.get("low_confidence_inference_max"):
        raise ValueError("penalty maximum drift")
    thresholds = contract.get("thresholds") or {}
    if not 0 <= thresholds.get("medium_priority_min_score", -1) < thresholds.get("high_priority_min_score", -1) <= 100:
        raise ValueError("priority thresholds invalid")
    outputs = contract.get("outputs") or {}
    if outputs.get("eligibility_state") != "NOT_ASSESSED" or outputs.get("maximum_next_state") != "RESEARCH_READY":
        raise ValueError("eligibility or external-state boundary failed open")
    if contract.get("rules", {}).get("never_claim_eligibility_award_or_conversion_probability") is not True:
        raise ValueError("non-probabilistic score rule missing")


def _round_points(value: float, maximum: int) -> int:
    return max(0, min(maximum, int(value + 0.5)))


def _held_result(organization_key: str, record: dict[str, Any], contract: dict[str, Any], reason: str) -> dict[str, Any]:
    state = contract["guards"]["held_result"]
    if record.get("state") == "HOLD_CONFLICT":
        state = contract["guards"]["conflict_result"]
    elif record.get("state") == "SUPPRESSED":
        state = contract["guards"]["suppressed_result"]
    return {
        "organization_key": organization_key,
        "prospect_id": record.get("prospect_id"),
        "priority_state": state,
        "score": None,
        "score_semantics": contract["score_semantics"],
        "eligibility_state": contract["outputs"]["eligibility_state"],
        "maximum_next_state": contract["outputs"]["maximum_next_state"],
        "recommended_service_id": None,
        "components": {},
        "penalties": {},
        "explanations": [reason],
        "verification_questions": [],
        "source_refs": [],
        "signal_ids": [],
        "evidence_label": record.get("synthetic_label") or "SOURCE_BOUND",
    }


def score_record(
    organization_key: str,
    record: dict[str, Any],
    reference_time: str,
    scoring_contract: dict[str, Any],
    client_contract: dict[str, Any],
) -> dict[str, Any]:
    now = VALIDATOR.parse_time(reference_time)
    VALIDATOR.validate_record(record, client_contract, now)
    if VALIDATOR.organization_key(record["organization"]) != organization_key:
        raise ValueError("organization key does not match record identity")
    if any(row.get("classification") == "CONFLICT" for row in record["assertions"]):
        return _held_result(organization_key, record, scoring_contract, "Conflicting evidence must be reconciled before prioritization.")
    if record.get("state") != scoring_contract["guards"]["scorable_record_state"]:
        return _held_result(organization_key, record, scoring_contract, f"record_state={record.get('state')} prevents scoring")

    active = [row for row in record["signals"] if VALIDATOR.parse_time(row["expires_at"]) > now]
    if not active:
        return _held_result(organization_key, record, scoring_contract, "No active signal remains inside its evidence window.")

    taxonomy = {row["id"]: row for row in client_contract["signal_taxonomy"]}
    sources = {row["source_id"]: row for row in record["sources"]}
    assertions = {row["assertion_id"]: row for row in record["assertions"]}
    weights = scoring_contract["positive_components"]

    source_basis: list[int] = []
    freshness_fractions: list[float] = []
    fact_covered = 0
    why_now_covered = 0
    service_signals: dict[str, list[str]] = defaultdict(list)
    source_refs: set[str] = set()
    signal_types: set[str] = set()

    for signal in active:
        refs = [ref for ref in signal["source_refs"] if ref in sources]
        source_refs.update(refs)
        qualities = [weights["source_quality"]["basis_points_by_source_type"][sources[ref]["source_type"]] for ref in refs]
        source_basis.append(max(qualities) if qualities else 0)
        observed = VALIDATOR.parse_time(signal["observed_at"])
        expires = VALIDATOR.parse_time(signal["expires_at"])
        duration = max((expires - observed).total_seconds(), 1.0)
        freshness_fractions.append(max(0.0, min(1.0, (expires - now).total_seconds() / duration)))
        if signal.get("fact_assertion_ids") and all(assertions.get(fid, {}).get("classification") == "FACT" for fid in signal["fact_assertion_ids"]):
            fact_covered += 1
        if str(signal.get("why_now") or "").strip():
            why_now_covered += 1
        signal_types.add(signal["signal_type"])
        for service_id in signal["service_ids"]:
            service_signals[service_id].append(signal["signal_id"])

    source_points = _round_points(
        weights["source_quality"]["max_points"] * (sum(source_basis) / len(source_basis) / 1000),
        weights["source_quality"]["max_points"],
    )
    freshness_points = _round_points(
        weights["freshness"]["max_points"] * (sum(freshness_fractions) / len(freshness_fractions)),
        weights["freshness"]["max_points"],
    )
    lane_points = max(weights["signal_strength"]["lane_points"][taxonomy[row["signal_type"]]["priority_lane"]] for row in active)
    confidence_points = _round_points(
        weights["signal_strength"]["confidence_points_max"] * (sum(float(row["confidence"]) for row in active) / len(active)),
        weights["signal_strength"]["confidence_points_max"],
    )
    diversity_bonus = min(
        weights["signal_strength"]["multi_signal_bonus_max"],
        max(0, len(signal_types) - 1) * weights["signal_strength"]["multi_signal_bonus_per_additional_type"],
    )
    signal_points = min(weights["signal_strength"]["max_points"], lane_points + confidence_points + diversity_bonus)

    service_rows = []
    for service_id in sorted(service_signals):
        supporting = sorted(set(service_signals[service_id]))
        service_rows.append({
            "service_id": service_id,
            "supporting_signal_ids": supporting,
            "support_count": len(supporting),
            "support_ratio": round(len(supporting) / len(active), 4),
        })
    service_rows.sort(key=lambda row: (-row["support_count"], row["service_id"]))
    recommended_service = service_rows[0]["service_id"] if service_rows else None
    service_points = _round_points(
        weights["service_coherence"]["max_points"] * (service_rows[0]["support_ratio"] if service_rows else 0),
        weights["service_coherence"]["max_points"],
    )
    action_points = _round_points(weights["actionability"]["fact_coverage_points"] * fact_covered / len(active), weights["actionability"]["fact_coverage_points"])
    action_points += _round_points(weights["actionability"]["why_now_coverage_points"] * why_now_covered / len(active), weights["actionability"]["why_now_coverage_points"])

    unknowns = [row for row in record["assertions"] if row["classification"] == "UNKNOWN"]
    low_inferences = [row for row in record["assertions"] if row["classification"] == "INFERENCE" and float(row.get("confidence", 0)) < scoring_contract["uncertainty_penalties"]["low_confidence_inference_threshold"]]
    penalties = scoring_contract["uncertainty_penalties"]
    unknown_penalty = min(penalties["unknown_assertion_max"], len(unknowns) * penalties["unknown_assertion_points"])
    inference_penalty = min(penalties["low_confidence_inference_max"], len(low_inferences) * penalties["low_confidence_inference_points"])
    total_penalty = unknown_penalty + inference_penalty

    components = {
        "source_quality": source_points,
        "freshness": freshness_points,
        "signal_strength": signal_points,
        "service_coherence": service_points,
        "actionability": action_points,
    }
    gross = sum(components.values())
    score = max(0, min(100, gross - total_penalty))
    thresholds = scoring_contract["thresholds"]
    if score >= thresholds["high_priority_min_score"] and len(signal_types) >= thresholds["high_priority_min_distinct_signal_types"] and source_points >= thresholds["high_priority_min_source_quality_points"]:
        priority = scoring_contract["outputs"]["high"]
    elif score >= thresholds["medium_priority_min_score"]:
        priority = scoring_contract["outputs"]["medium"]
    else:
        priority = scoring_contract["outputs"]["low"]

    questions = sorted({str(row.get("verification_question")) for row in record["assertions"] if row.get("verification_question")})
    return {
        "organization_key": organization_key,
        "prospect_id": record["prospect_id"],
        "priority_state": priority,
        "score": score,
        "score_semantics": scoring_contract["score_semantics"],
        "eligibility_state": scoring_contract["outputs"]["eligibility_state"],
        "maximum_next_state": scoring_contract["outputs"]["maximum_next_state"],
        "recommended_service_id": recommended_service,
        "service_ranking": service_rows,
        "components": components,
        "gross_score": gross,
        "penalties": {
            "unknown_assertions": unknown_penalty,
            "low_confidence_inferences": inference_penalty,
            "total": total_penalty,
        },
        "explanations": [
            f"{len(active)} active signal(s), {len(signal_types)} distinct type(s).",
            f"Source quality contributes {source_points}/{weights['source_quality']['max_points']}; freshness contributes {freshness_points}/{weights['freshness']['max_points']}.",
            f"Dominant service {recommended_service} is supported by {service_rows[0]['support_count'] if service_rows else 0}/{len(active)} active signals.",
            f"Uncertainty subtracts {total_penalty} point(s); score remains research priority only.",
        ],
        "verification_questions": questions,
        "source_refs": sorted(source_refs),
        "signal_ids": sorted(row["signal_id"] for row in active),
        "evidence_label": record.get("synthetic_label") or "SOURCE_BOUND",
    }


def score_state(
    state: dict[str, Any],
    reference_time: str,
    scoring_contract: dict[str, Any] | None = None,
    client_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ENGINE._assert_state_boundary(state)
    if VALIDATOR.parse_time(reference_time) < VALIDATOR.parse_time(state["reference_time"]):
        raise ValueError("scoring reference time cannot move backwards")
    scoring_contract = scoring_contract or load_json(SCORING_CONTRACT_PATH)
    client_contract = client_contract or load_json(CLIENT_CONTRACT_PATH)
    validate_scoring_contract(scoring_contract, client_contract)
    results = [score_record(key, record, reference_time, scoring_contract, client_contract) for key, record in state["records"].items()]
    results.sort(key=lambda row: (row["score"] is None, -(row["score"] or 0), row["organization_key"]))
    outputs = scoring_contract["outputs"]
    return {
        "schema_version": 1,
        "engine_id": scoring_contract["engine_id"],
        "reference_time": reference_time,
        "score_semantics": scoring_contract["score_semantics"],
        "eligibility_state": outputs["eligibility_state"],
        "maximum_next_state": outputs["maximum_next_state"],
        "summary": {
            "evaluated": len(results),
            "high": sum(row["priority_state"] == outputs["high"] for row in results),
            "medium": sum(row["priority_state"] == outputs["medium"] for row in results),
            "low": sum(row["priority_state"] == outputs["low"] for row in results),
            "held_or_suppressed": sum(row["score"] is None for row in results),
        },
        "results": results,
        "production_records": 0 if all(row.get("synthetic_label") == "NON_EVIDENCE" for row in state["records"].values()) else None,
        "external_contact_enabled": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="EUCONS explainable prospect-priority scorer")
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--reference-time", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = score_state(load_json(args.state), args.reference_time)
    ENGINE.write_atomic(args.output, result)
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
