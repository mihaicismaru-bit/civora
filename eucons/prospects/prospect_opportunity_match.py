#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
CONTRACT_PATH = EUCONS / "prospects" / "prospect_opportunity_match_contract.json"
CLIENT_CONTRACT_PATH = EUCONS / "prospects" / "client_finder_contract.json"
SCORING_CONTRACT_PATH = EUCONS / "prospects" / "prospect_scoring_contract.json"
SERVICE_REGISTRY_PATH = EUCONS / "services" / "service_registry.json"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLIENT_ENGINE = _load_module("r07_client_finder_engine", EUCONS / "prospects" / "client_finder_engine.py")
CLIENT_VALIDATOR = CLIENT_ENGINE.VALIDATOR
SCORER = _load_module("r07_prospect_scoring", EUCONS / "prospects" / "prospect_scoring.py")
OPPORTUNITY_MATCHER = _load_module("r07_opportunity_matching", EUCONS / "opportunities" / "match_opportunities.py")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def fold(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").casefold())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def validate_match_contract(
    contract: dict[str, Any],
    client_contract: dict[str, Any],
    scoring_contract: dict[str, Any],
    opportunity_contract: dict[str, Any],
    service_registry: dict[str, Any],
) -> None:
    if contract.get("id") != "R07-PROSPECT-MATCH-001" or contract.get("status") != "CANONICAL":
        raise ValueError("R07 match contract drift")
    if contract.get("match_semantics") != "RESEARCH_RELEVANCE_NOT_ELIGIBILITY_AWARD_OR_BUYING_INTENT":
        raise ValueError("match semantics failed open")
    for dependency in (contract.get("canonical_dependencies") or {}).values():
        if not (ROOT / dependency).is_file():
            raise ValueError(f"missing canonical dependency: {dependency}")
    CLIENT_VALIDATOR.validate_contract(client_contract)
    SCORER.validate_scoring_contract(scoring_contract, client_contract)
    if opportunity_contract.get("score_semantics") != "RELEVANCE_NOT_APPROVAL_PROBABILITY":
        raise ValueError("opportunity matcher semantics drift")
    opportunity_rules = opportunity_contract.get("rules", {})
    if opportunity_rules.get("never_claim_eligibility_or_award_probability") is not True:
        raise ValueError("opportunity matcher eligibility guard missing")
    if opportunity_rules.get("partener_material_facts_never_authoritative_without_official_binding") is not True:
        raise ValueError("opportunity matcher official-source boundary missing")
    official_guards = opportunity_contract.get("official_source_guards") or {}
    if official_guards.get("partener_role") != "DISCOVERY_ONLY":
        raise ValueError("PARTENER authority role failed open")
    if set(official_guards.get("required_candidate_fact_classes") or []) != {"status", "deadline"}:
        raise ValueError("official candidate fact gate drift")

    input_guards = contract.get("input_guards") or {}
    if input_guards.get("partener_role") != "DISCOVERY_ONLY":
        raise ValueError("R07 PARTENER role failed open")
    if input_guards.get("official_registry_read_only_input") is not True:
        raise ValueError("R07 official registry read-only boundary missing")
    if input_guards.get("official_status_and_deadline_required_for_candidate") is not True:
        raise ValueError("R07 official candidate gate missing")
    if input_guards.get("missing_official_registry_result") != "HOLD_SOURCE_STATE":
        raise ValueError("R07 missing-official behavior failed open")
    if input_guards.get("official_conflict_result") != "HOLD_SOURCE_STATE":
        raise ValueError("R07 official conflict behavior failed open")

    outputs = contract.get("outputs") or {}
    if outputs.get("eligibility_state") != "NOT_ASSESSED" or outputs.get("maximum_next_state") != "RESEARCH_READY":
        raise ValueError("R07 qualification boundary failed open")
    if outputs.get("external_contact_enabled") is not False or outputs.get("automatic_offer_enabled") is not False:
        raise ValueError("R07 external action boundary failed open")
    rules = contract.get("rules") or {}
    if rules.get("never_prepare_or_send_external_contact") is not True:
        raise ValueError("external contact rule missing")
    for rule in (
        "deadline_requires_official_source_binding",
        "partener_discovery_never_satisfies_material_fact_authority",
        "official_conflict_fails_closed",
    ):
        if rules.get(rule) is not True:
            raise ValueError(f"R07 authority rule failed open: {rule}")
    if contract.get("truth_model", {}).get("classes") != ["FACT", "INFERENCE", "UNKNOWN", "CONFLICT"]:
        raise ValueError("truth taxonomy drift")
    if contract.get("truth_model", {}).get("official_source_bindings_control_material_fact_authority") is not True:
        raise ValueError("R07 material fact authority rule missing")

    organization_types = set(client_contract["organization_identity"]["organization_types"])
    type_labels = set((contract.get("profile_projection") or {}).get("organization_type_labels") or {})
    if type_labels != organization_types:
        raise ValueError("organization type profile mapping incomplete")
    forbidden = set(client_contract["privacy_boundary"]["person_level_fields_forbidden"])
    if set(contract["profile_projection"]["person_level_fields_forbidden"]) != forbidden:
        raise ValueError("person-level field boundary drift")

    service_policy = contract.get("opportunity_service_policy") or {}
    service_ids = {row["id"] for row in service_registry.get("services") or []}
    mapped_services = set(service_policy.get("verified_funding_opportunity_services") or [])
    if not mapped_services or not mapped_services.issubset(service_ids):
        raise ValueError("opportunity service policy references unknown service")
    if service_policy.get("selection_preference") != "PROSPECT_RECOMMENDED_THEN_SERVICE_ID_ASC":
        raise ValueError("opportunity service selection policy drift")
    next_actions = set((contract.get("next_best_actions") or {}).keys())
    if next_actions != {"matched", "requires_verification", "no_current_opportunity", "held_source", "held_conflict", "suppressed"}:
        raise ValueError("next-best-action taxonomy incomplete")


def validate_projection(projection: dict[str, Any], reference_time: str, contract: dict[str, Any]) -> None:
    if projection.get("product") != "EUCONS_COMMERCIAL_OS":
        raise ValueError("unexpected opportunity projection product")
    if projection.get("bridge_id") != contract["input_guards"]["required_bridge_id"]:
        raise ValueError("unexpected opportunity projection bridge")
    if projection.get("read_only") is not True or projection.get("source_mutation_allowed") is not False:
        raise ValueError("opportunity projection is not read-only")
    generated = CLIENT_VALIDATOR.parse_time(projection.get("generated_at"))
    now = CLIENT_VALIDATOR.parse_time(reference_time)
    if generated > now:
        raise ValueError("opportunity projection generated in the future")
    required_record_state = contract["input_guards"]["required_opportunity_state"]
    for row in projection.get("opportunities") or []:
        if row.get("commercial_state") == required_record_state:
            if not row.get("verified_fact_classes"):
                raise ValueError("discovery opportunity missing projection fact classes")
            provenance = row.get("provenance") or {}
            if provenance.get("source_product") != "PARTENER.EU" or not provenance.get("source_opportunity_id"):
                raise ValueError("discovery opportunity missing PARTENER provenance")
            if (provenance.get("publication_decision") or {}).get("decision") != "ALLOW_VERIFIED_FACTS":
                raise ValueError("discovery opportunity missing fail-closed projection decision")
            if not provenance.get("verification_evidence"):
                raise ValueError("discovery opportunity missing projection evidence")


def _truth_index(record: dict[str, Any]) -> dict[str, list[str]]:
    truth = {"FACT": [], "INFERENCE": [], "UNKNOWN": [], "CONFLICT": []}
    for row in record.get("assertions") or []:
        classification = row.get("classification")
        if classification not in truth:
            raise ValueError(f"unknown assertion classification: {classification}")
        truth[classification].append(row["assertion_id"])
    return {key: sorted(values) for key, values in truth.items()}


def _fact_terms(record: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    config = contract["profile_projection"]
    stop = {fold(value) for value in config["fact_term_stopwords"]}
    minimum = int(config["fact_term_minimum_length"])
    candidates: set[str] = set()
    for assertion in record.get("assertions") or []:
        if assertion.get("classification") != "FACT":
            continue
        for field in ("subject", "statement"):
            for token in fold(assertion.get(field)).split():
                if len(token) >= minimum and token not in stop and not token.isdigit():
                    candidates.add(token)
    for signal in record.get("signals") or []:
        for token in fold(signal.get("why_now")).split():
            if len(token) >= minimum and token not in stop and not token.isdigit():
                candidates.add(token)
    return sorted(candidates)[: int(config["fact_term_limit"])]


def build_opportunity_profile(organization_key: str, record: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    organization = record["organization"]
    forbidden = set(contract["profile_projection"]["person_level_fields_forbidden"])
    if forbidden & set(organization):
        raise ValueError("person-level field entered organization profile")
    type_labels = contract["profile_projection"]["organization_type_labels"][organization["organization_type"]]
    activity_codes = organization.get("public_activity_codes") or []
    if not isinstance(activity_codes, list):
        raise ValueError("public_activity_codes must be a list")
    region_terms = [organization["region"]] if organization.get("region") else []
    return {
        "profile_id": f"R07-{organization_key}",
        "audience_id": organization["organization_type"].casefold(),
        "organization_labels": list(type_labels),
        "activity_codes": list(activity_codes),
        "region_terms": region_terms,
        "investment_terms": _fact_terms(record, contract),
    }


def _deadline_fact(opportunity: dict[str, Any], official_fact_classes: set[str]) -> Any:
    if "deadline" not in official_fact_classes:
        return None
    material = opportunity.get("material_facts") or {}
    return deepcopy(material.get("deadline"))


def _select_aligned_service(aligned_services: list[str], recommended_service_id: Any) -> str | None:
    if recommended_service_id in aligned_services:
        return str(recommended_service_id)
    return aligned_services[0] if aligned_services else None


def _opportunity_summary(
    row: dict[str, Any],
    projection_rows: dict[str, dict[str, Any]],
    aligned_services: list[str],
    recommended_service_id: Any,
) -> dict[str, Any]:
    source = projection_rows.get(str(row.get("opportunity_id"))) or {}
    official_fact_classes = set(row.get("official_fact_classes") or [])
    return {
        "opportunity_id": row.get("opportunity_id"),
        "title": row.get("title"),
        "programme": row.get("programme"),
        "relevance_score": row.get("score"),
        "relevance_semantics": row.get("score_semantics"),
        "confidence": row.get("confidence"),
        "state": row.get("state"),
        "authority_state": row.get("authority_state"),
        "official_fact_classes": sorted(official_fact_classes),
        "official_source_count": row.get("official_source_count", 0),
        "aligned_service_ids": aligned_services,
        "selected_service_id": _select_aligned_service(aligned_services, recommended_service_id),
        "explanations": list(row.get("explanations") or []),
        "hard_exclusion_reasons": list(row.get("hard_exclusion_reasons") or []),
        "verified_fact_classes": sorted(official_fact_classes),
        "discovery_projection_fact_classes": sorted(source.get("verified_fact_classes") or []),
        "source_supported_deadline": _deadline_fact(source, official_fact_classes),
        "source_provenance": deepcopy(row.get("source_provenance") or {}),
    }


def _base_result(organization_key: str, record: dict[str, Any], score: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    truth = _truth_index(record)
    questions = sorted({str(row.get("verification_question")) for row in record.get("assertions") or [] if row.get("verification_question")})
    return {
        "organization_key": organization_key,
        "prospect_id": record.get("prospect_id"),
        "priority_state": score.get("priority_state"),
        "priority_score": score.get("score"),
        "match_semantics": contract["match_semantics"],
        "eligibility_state": contract["outputs"]["eligibility_state"],
        "maximum_next_state": contract["outputs"]["maximum_next_state"],
        "state": contract["outputs"]["requires_verification"],
        "recommended_service_id": score.get("recommended_service_id"),
        "signal_supported_service_ids": sorted({service for signal in record.get("signals") or [] for service in signal.get("service_ids") or []}),
        "truth": {
            "facts": truth["FACT"],
            "inferences": truth["INFERENCE"],
            "unknowns": truth["UNKNOWN"],
            "conflicts": truth["CONFLICT"],
        },
        "source_refs": sorted({ref for row in record.get("assertions") or [] for ref in row.get("source_refs") or []}),
        "signal_ids": sorted(row["signal_id"] for row in record.get("signals") or []),
        "verification_questions": questions,
        "opportunity_matches": [],
        "selected_opportunity_id": None,
        "selected_service_id": None,
        "next_best_action": contract["next_best_actions"]["requires_verification"],
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "evidence_label": record.get("synthetic_label") or "SOURCE_BOUND",
    }


def match_record(
    organization_key: str,
    record: dict[str, Any],
    score: dict[str, Any],
    projection: dict[str, Any],
    contract: dict[str, Any],
    opportunity_contract: dict[str, Any],
    official_registry: dict[str, Any] | None,
) -> dict[str, Any]:
    result = _base_result(organization_key, record, score, contract)
    outputs = contract["outputs"]
    actions = contract["next_best_actions"]

    if record.get("state") == "SUPPRESSED" or score.get("priority_state") == "SUPPRESSED":
        result.update(state=outputs["suppressed"], next_best_action=actions["suppressed"], recommended_service_id=None)
        return result
    if result["truth"]["conflicts"] or record.get("state") == "HOLD_CONFLICT" or score.get("priority_state") == "HOLD_CONFLICT":
        result.update(state=outputs["held_conflict"], next_best_action=actions["held_conflict"], recommended_service_id=None)
        return result
    if record.get("state") != contract["input_guards"]["required_prospect_state"] or score.get("score") is None:
        result.update(state=outputs["requires_verification"], next_best_action=actions["requires_verification"])
        return result
    if projection.get("bridge_state") != contract["input_guards"]["required_bridge_state"]:
        result.update(state=outputs["held_source"], next_best_action=actions["held_source"])
        return result

    profile = build_opportunity_profile(organization_key, record, contract)
    matched = OPPORTUNITY_MATCHER.match(profile, projection, opportunity_contract, official_registry)
    projection_rows = {str(row.get("id")): row for row in projection.get("opportunities") or []}
    opportunity_services = set(contract["opportunity_service_policy"]["verified_funding_opportunity_services"])
    prospect_services = set(result["signal_supported_service_ids"])
    aligned_services = sorted(opportunity_services & prospect_services)
    rows = []
    for row in matched["results"]:
        aligned = aligned_services if row.get("state") == opportunity_contract["outputs"]["candidate"] else []
        rows.append(_opportunity_summary(row, projection_rows, aligned, result["recommended_service_id"]))
    result["opportunity_matches"] = rows

    if matched["summary"]["evaluated"] and matched["summary"]["held_source_state"] == matched["summary"]["evaluated"]:
        result.update(state=outputs["held_source"], next_best_action=actions["held_source"])
        return result

    aligned_candidates = [row for row in rows if row["state"] == opportunity_contract["outputs"]["candidate"] and row["aligned_service_ids"]]
    raw_candidates = [row for row in rows if row["state"] == opportunity_contract["outputs"]["candidate"]]
    if aligned_candidates:
        selected = aligned_candidates[0]
        if selected.get("authority_state") != opportunity_contract["official_source_guards"]["verified_authority_state"]:
            raise AssertionError("R07 candidate crossed official-source authority boundary")
        if not {"status", "deadline"}.issubset(set(selected.get("official_fact_classes") or [])):
            raise AssertionError("R07 candidate lacks required official status/deadline bindings")
        result.update(
            state=outputs["matched"],
            selected_opportunity_id=selected["opportunity_id"],
            selected_service_id=selected["selected_service_id"],
            next_best_action=actions["matched"],
        )
        result["verification_questions"] = sorted(set(result["verification_questions"] + [
            "Este proiecția oportunității încă actuală la momentul revizuirii umane?",
            "Îndeplinește organizația toate condițiile aplicabile din sursa oficială curentă?",
            "Este serviciul recomandat necesar și necontractat deja?",
        ]))
    elif raw_candidates:
        result.update(state=outputs["requires_verification"], next_best_action=actions["requires_verification"])
        result["verification_questions"] = sorted(set(result["verification_questions"] + [
            "Ce serviciu EUROCONSULT este susținut de nevoia reală a organizației?",
        ]))
    else:
        result.update(state=outputs["no_current_opportunity"], next_best_action=actions["no_current_opportunity"])
    return result


def match_state(
    state: dict[str, Any],
    projection: dict[str, Any],
    reference_time: str,
    contract: dict[str, Any] | None = None,
    client_contract: dict[str, Any] | None = None,
    scoring_contract: dict[str, Any] | None = None,
    opportunity_contract: dict[str, Any] | None = None,
    service_registry: dict[str, Any] | None = None,
    official_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    CLIENT_ENGINE._assert_state_boundary(state)
    contract = contract or load_json(CONTRACT_PATH)
    client_contract = client_contract or load_json(CLIENT_CONTRACT_PATH)
    scoring_contract = scoring_contract or load_json(SCORING_CONTRACT_PATH)
    opportunity_contract = opportunity_contract or load_json(EUCONS / "opportunities" / "matching_contract.json")
    service_registry = service_registry or load_json(SERVICE_REGISTRY_PATH)
    validate_match_contract(contract, client_contract, scoring_contract, opportunity_contract, service_registry)
    validate_projection(projection, reference_time, contract)
    before_projection = canonical_hash(projection)
    before_registry = canonical_hash(official_registry)
    scores = SCORER.score_state(state, reference_time, scoring_contract, client_contract)
    score_index = {row["organization_key"]: row for row in scores["results"]}
    results = [
        match_record(key, record, score_index[key], projection, contract, opportunity_contract, official_registry)
        for key, record in sorted(state["records"].items())
    ]
    priority = {"PRIORITY_HIGH_RESEARCH": 0, "PRIORITY_MEDIUM_RESEARCH": 1, "PRIORITY_LOW_RESEARCH": 2}
    results.sort(key=lambda row: (priority.get(str(row.get("priority_state")), 9), -(row.get("priority_score") or 0), row["organization_key"]))
    if before_projection != canonical_hash(projection):
        raise AssertionError("opportunity projection mutated during R07 matching")
    if before_registry != canonical_hash(official_registry):
        raise AssertionError("official-source registry mutated during R07 matching")
    outputs = contract["outputs"]
    official_states = [
        match.get("authority_state")
        for row in results
        for match in row.get("opportunity_matches") or []
        if match.get("authority_state")
    ]
    return {
        "schema_version": 1,
        "engine_id": contract["engine_id"],
        "reference_time": reference_time,
        "match_semantics": contract["match_semantics"],
        "eligibility_state": outputs["eligibility_state"],
        "maximum_next_state": outputs["maximum_next_state"],
        "bridge_state": projection.get("bridge_state"),
        "partener_role": opportunity_contract["official_source_guards"]["partener_role"],
        "summary": {
            "evaluated_prospects": len(results),
            "matched": sum(row["state"] == outputs["matched"] for row in results),
            "requires_verification": sum(row["state"] == outputs["requires_verification"] for row in results),
            "no_current_opportunity": sum(row["state"] == outputs["no_current_opportunity"] for row in results),
            "held_source": sum(row["state"] == outputs["held_source"] for row in results),
            "held_conflict": sum(row["state"] == outputs["held_conflict"] for row in results),
            "suppressed": sum(row["state"] == outputs["suppressed"] for row in results),
            "official_source_verified_rows": sum(value == opportunity_contract["official_source_guards"]["verified_authority_state"] for value in official_states),
            "waiting_source_rows": sum(value == opportunity_contract["official_source_guards"]["waiting_authority_state"] for value in official_states),
            "blocked_source_conflict_rows": sum(value == opportunity_contract["official_source_guards"]["blocked_authority_state"] for value in official_states),
        },
        "results": results,
        "production_records": 0 if all(row.get("synthetic_label") == "NON_EVIDENCE" for row in state["records"].values()) else None,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="EUCONS prospect-to-opportunity-to-service research matcher")
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--projection", required=True, type=Path)
    parser.add_argument("--reference-time", required=True)
    parser.add_argument("--official-verification-registry", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    official_registry = load_json(args.official_verification_registry) if args.official_verification_registry else None
    result = match_state(
        load_json(args.state),
        load_json(args.projection),
        args.reference_time,
        official_registry=official_registry,
    )
    CLIENT_ENGINE.write_atomic(args.output, result)
    print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
