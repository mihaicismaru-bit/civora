#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
CONTRACT_PATH = EUCONS / "outreach" / "action_pack_contract.json"
CLIENT_CONTRACT_PATH = EUCONS / "prospects" / "client_finder_contract.json"
MATCH_CONTRACT_PATH = EUCONS / "prospects" / "prospect_opportunity_match_contract.json"
SERVICE_REGISTRY_PATH = EUCONS / "services" / "service_registry.json"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLIENT_ENGINE = _load_module("r08_client_finder_engine", EUCONS / "prospects" / "client_finder_engine.py")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _required_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} required")
    return text


def validate_contract(
    contract: dict[str, Any],
    client_contract: dict[str, Any],
    match_contract: dict[str, Any],
    service_registry: dict[str, Any],
) -> None:
    if contract.get("id") != "R08-ACTION-PACK-001" or contract.get("status") != "CANONICAL":
        raise ValueError("R08 action-pack contract drift")
    for dependency in (contract.get("canonical_dependencies") or {}).values():
        if not (ROOT / dependency).is_file():
            raise ValueError(f"missing canonical dependency: {dependency}")
    guards = contract.get("input_guards") or {}
    if guards.get("required_match_engine_id") != match_contract.get("engine_id"):
        raise ValueError("R07 engine dependency drift")
    if guards.get("required_match_semantics") != match_contract.get("match_semantics"):
        raise ValueError("R07 match semantics dependency drift")
    if guards.get("required_r07_maximum_state") != match_contract.get("outputs", {}).get("maximum_next_state"):
        raise ValueError("R07 state boundary dependency drift")
    if guards.get("required_eligibility_state") != "NOT_ASSESSED":
        raise ValueError("R08 eligibility boundary failed open")
    truth = contract.get("truth_policy") or {}
    if truth.get("classes") != ["FACT", "INFERENCE", "UNKNOWN", "CONFLICT"]:
        raise ValueError("R08 truth taxonomy drift")
    if truth.get("why_now_allowed_classes") != ["FACT"] or truth.get("outreach_statement_allowed_classes") != ["FACT"]:
        raise ValueError("R08 factual drafting boundary failed open")
    if truth.get("inference_handling") != "QUESTION_ONLY" or truth.get("unknown_handling") != "QUESTION_ONLY":
        raise ValueError("R08 uncertainty handling failed open")
    if truth.get("fact_source_refs_required") is not True or truth.get("material_funding_fact_official_source_required") is not True:
        raise ValueError("R08 source gate failed open")
    if truth.get("never_claim_eligibility_award_probability_or_buying_intent") is not True:
        raise ValueError("R08 forbidden-conclusion guard missing")
    if not all((contract.get("pack_components") or {}).values()):
        raise ValueError("R08 action-pack component missing")
    contact = contract.get("contact_governance") or {}
    if contact.get("mode") != "ORGANIZATION_FIRST" or contact.get("person_targeting_allowed") is not False:
        raise ValueError("R08 person-targeting boundary failed open")
    if contact.get("private_contact_data_allowed") is not False or contact.get("contact_surface_extraction_enabled") is not False:
        raise ValueError("R08 contact-data boundary failed open")
    if contact.get("lawful_basis_default_state") != "REVIEW_REQUIRED":
        raise ValueError("R08 lawful-basis review failed open")
    if contact.get("suppression_check_required") is not True or contact.get("opt_out_mechanism_required_before_send") is not True:
        raise ValueError("R08 contact governance gate missing")
    if contact.get("human_approval_required") is not True:
        raise ValueError("R08 contact approval failed open")
    commercial = contract.get("commercial_boundary") or {}
    if commercial.get("numeric_price_allowed") is not False or commercial.get("discount_allowed") is not False:
        raise ValueError("R08 pricing boundary failed open")
    if commercial.get("binding_terms_allowed") is not False or commercial.get("automatic_offer_allowed") is not False:
        raise ValueError("R08 commercial boundary failed open")
    outputs = contract.get("outputs") or {}
    if outputs.get("ready") != "READY_FOR_APPROVAL" or outputs.get("eligibility_state") != "NOT_ASSESSED":
        raise ValueError("R08 approval boundary drift")
    if any(outputs.get(key) is not False for key in ("external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled")):
        raise ValueError("R08 external action boundary failed open")
    external = contract.get("external_action_gate") or {}
    if external.get("maximum_state") != "READY_FOR_APPROVAL" or external.get("human_approval_required") is not True:
        raise ValueError("R08 human approval boundary failed open")
    if not external.get("approval_requirements"):
        raise ValueError("R08 human approval requirements missing")
    if any(external.get(key) is not False for key in ("autonomous_send", "autonomous_call", "autonomous_social_dm", "autonomous_offer")):
        raise ValueError("R08 autonomous external action failed open")
    repository = contract.get("repository_policy") or {}
    if repository.get("real_prospect_or_contact_records_forbidden") is not True or repository.get("runtime_output_under_repository_root_forbidden") is not True:
        raise ValueError("R08 repository privacy boundary failed open")
    forbidden = set(client_contract["privacy_boundary"]["person_level_fields_forbidden"])
    if not forbidden:
        raise ValueError("R08 privacy dependency missing")
    service_ids = {row.get("id") for row in service_registry.get("services") or []}
    if not service_ids or None in service_ids:
        raise ValueError("invalid canonical service registry")


def _validate_inputs(
    state: dict[str, Any],
    matches: dict[str, Any],
    reference_time: str,
    contract: dict[str, Any],
    client_contract: dict[str, Any],
) -> None:
    CLIENT_ENGINE._assert_state_boundary(state)
    guards = contract["input_guards"]
    if matches.get("engine_id") != guards["required_match_engine_id"]:
        raise ValueError("unexpected R07 match engine")
    if matches.get("match_semantics") != guards["required_match_semantics"]:
        raise ValueError("unsafe R07 match semantics")
    if matches.get("maximum_next_state") != guards["required_r07_maximum_state"]:
        raise ValueError("R07 maximum state failed open")
    if matches.get("eligibility_state") != guards["required_eligibility_state"]:
        raise ValueError("R07 eligibility state failed open")
    if matches.get("reference_time") != reference_time:
        raise ValueError("R07 reference time mismatch")
    if matches.get("external_contact_enabled") is not False or matches.get("automatic_offer_enabled") is not False:
        raise ValueError("R07 external action boundary failed open")
    forbidden = set(client_contract["privacy_boundary"]["person_level_fields_forbidden"])
    for record in (state.get("records") or {}).values():
        if forbidden & set(record.get("organization") or {}):
            raise ValueError("person-level field entered R08 input")


def _source_index(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("source_id")): row for row in record.get("sources") or []}


def _assertion_index(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("assertion_id")): row for row in record.get("assertions") or []}


def _fact_cards(record: dict[str, Any], match: dict[str, Any], contract: dict[str, Any]) -> list[dict[str, Any]]:
    assertions = _assertion_index(record)
    sources = _source_index(record)
    cards: list[dict[str, Any]] = []
    for assertion_id in match.get("truth", {}).get("facts") or []:
        assertion = assertions.get(str(assertion_id))
        if not assertion or assertion.get("classification") != "FACT":
            raise ValueError("R07 FACT assertion cannot be resolved")
        refs = sorted(set(assertion.get("source_refs") or []))
        if not refs or any(ref not in sources for ref in refs):
            raise ValueError("R08 FACT missing source provenance")
        if assertion.get("material_funding_claim"):
            if not any(sources[ref].get("official") is True for ref in refs):
                raise ValueError("material funding FACT lacks official source")
        cards.append({
            "assertion_id": assertion_id,
            "classification": "FACT",
            "statement": _required_text(assertion.get("statement"), "fact statement"),
            "source_refs": refs,
        })
    if not cards:
        raise ValueError("R08 action pack requires at least one sourced FACT")
    return cards


def _source_register(record: dict[str, Any], source_refs: set[str]) -> list[dict[str, Any]]:
    sources = _source_index(record)
    rows = []
    for source_ref in sorted(source_refs):
        source = sources.get(source_ref)
        if not source:
            raise ValueError("action-pack source reference missing")
        rows.append({
            "source_id": source_ref,
            "source_type": source.get("source_type"),
            "authority": source.get("authority"),
            "title": source.get("title"),
            "url": source.get("url"),
            "retrieved_at": source.get("retrieved_at"),
            "content_hash": source.get("content_hash"),
            "official": source.get("official") is True,
            "public_access": source.get("public_access") is True,
        })
    return rows


def _discovery_questions(record: dict[str, Any], match: dict[str, Any], service: dict[str, Any]) -> list[dict[str, Any]]:
    assertions = _assertion_index(record)
    questions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for classification, key in (("INFERENCE", "inferences"), ("UNKNOWN", "unknowns")):
        for assertion_id in match.get("truth", {}).get(key) or []:
            assertion = assertions.get(str(assertion_id))
            if not assertion or assertion.get("classification") != classification:
                raise ValueError(f"R07 {classification} assertion cannot be resolved")
            question = _required_text(assertion.get("verification_question"), f"{classification} verification question")
            if question not in seen:
                questions.append({"question": question, "basis": classification, "assertion_id": assertion_id})
                seen.add(question)
    for question in match.get("verification_questions") or []:
        text = _required_text(question, "R07 verification question")
        if text not in seen:
            questions.append({"question": text, "basis": "R07_MATCH_GAP", "assertion_id": None})
            seen.add(text)
    for requirement in service.get("evidence_requirements") or []:
        text = f"Puteți confirma și pune la dispoziție: {str(requirement).strip()}?"
        if text not in seen:
            questions.append({"question": text, "basis": "SERVICE_SCOPE_INPUT", "assertion_id": None})
            seen.add(text)
    return questions


def _outreach_draft(organization: dict[str, Any], service: dict[str, Any], facts: list[dict[str, Any]]) -> dict[str, Any]:
    legal_name = _required_text(organization.get("legal_name"), "organization legal name")
    fact_lines = " ".join(f"Conform sursei publice citate: {row['statement']}" for row in facts)
    body = (
        f"Bună ziua, echipa {legal_name}. {fact_lines} "
        f"Acest semnal nu confirmă eligibilitatea, intenția de achiziție sau nevoia unui serviciu. "
        f"Dacă subiectul este actual pentru organizație, Euroconsult poate propune o discuție exploratorie privind {service['label'].casefold()}, "
        "începând cu verificarea situației și a documentelor relevante. Mesajul poate fi transmis numai după verificarea temeiului de contact, a surselor și aprobarea umană."
    )
    return {
        "channel": "UNSELECTED",
        "target": {"type": "ORGANIZATION_ROLE", "organization_legal_name": legal_name, "person": None, "contact_surface": None},
        "subject": f"Discuție exploratorie — {service['label']}",
        "body": body,
        "fact_assertion_ids": [row["assertion_id"] for row in facts],
        "approval_state": "READY_FOR_APPROVAL",
        "send_state": "BLOCKED_HUMAN_APPROVAL_AND_CONTACT_GOVERNANCE",
        "automatic_send_enabled": False,
    }


def _offer_skeleton(service: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": contract["commercial_boundary"]["offer_kind"],
        "service_id": service["id"],
        "service_label": service["label"],
        "service_summary": service["summary"],
        "proposed_deliverables": deepcopy(service.get("deliverables") or []),
        "boundaries": deepcopy(service.get("boundaries") or []),
        "required_inputs": deepcopy(service.get("evidence_requirements") or []),
        "assumptions": [
            "Necesitatea serviciului nu este confirmată înaintea discuției de calificare.",
            "Eligibilitatea și condițiile materiale rămân NOT_ASSESSED până la verificarea sursei oficiale și a datelor organizației.",
            "Aria, calendarul și responsabilitățile se stabilesc numai după validarea umană a contextului."
        ],
        "pricing": {"state": contract["commercial_boundary"]["pricing_state"], "amount_minor": None, "currency": None, "binding": False},
        "approval_state": "READY_FOR_APPROVAL",
        "automatic_offer_enabled": False,
    }


def _hold_result(match: dict[str, Any], state: str, reason: str, contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "organization_key": match.get("organization_key"),
        "prospect_id": match.get("prospect_id"),
        "state": state,
        "reason": reason,
        "action_pack": None,
        "eligibility_state": contract["outputs"]["eligibility_state"],
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
    }


def build_pack(
    record: dict[str, Any],
    match: dict[str, Any],
    service_index: dict[str, dict[str, Any]],
    contract: dict[str, Any],
) -> dict[str, Any]:
    outputs = contract["outputs"]
    if record.get("state") == "SUPPRESSED" or (record.get("suppression") or {}).get("active") is True or match.get("state") == "SUPPRESSED":
        return _hold_result(match, outputs["suppressed"], "SUPPRESSION_ACTIVE", contract)
    if match.get("truth", {}).get("conflicts") or record.get("state") == "HOLD_CONFLICT" or match.get("state") == "HOLD_CONFLICT":
        return _hold_result(match, outputs["hold_conflict"], "UNRESOLVED_CONFLICT", contract)
    if match.get("state") == "HOLD_SOURCE_STATE":
        return _hold_result(match, outputs["hold_source"], "SOURCE_NOT_CURRENT_OR_VERIFIED", contract)
    if match.get("state") != contract["input_guards"]["required_match_state"]:
        return _hold_result(match, outputs["hold_research"], "R07_MATCH_NOT_READY", contract)
    opportunity_id = _required_text(match.get("selected_opportunity_id"), "selected opportunity")
    service_id = _required_text(match.get("recommended_service_id"), "recommended service")
    service = service_index.get(service_id)
    if not service:
        raise ValueError("R08 match references unknown canonical service")
    if service_id not in set(match.get("signal_supported_service_ids") or []):
        raise ValueError("R08 service is not supported by a prospect signal")
    selected_rows = [row for row in match.get("opportunity_matches") or [] if row.get("opportunity_id") == opportunity_id]
    if len(selected_rows) != 1 or service_id not in set(selected_rows[0].get("aligned_service_ids") or []):
        raise ValueError("R08 opportunity-service alignment is inconsistent")

    facts = _fact_cards(record, match, contract)
    source_refs = {ref for fact in facts for ref in fact["source_refs"]}
    sources = _source_register(record, source_refs)
    questions = _discovery_questions(record, match, service)
    organization = record["organization"]
    pack_core = {
        "organization_key": match["organization_key"],
        "prospect_id": match["prospect_id"],
        "organization": {
            "legal_name": organization["legal_name"],
            "organization_type": organization["organization_type"],
            "country_code": organization["country_code"],
            "region": organization.get("region"),
            "official_domain": organization.get("official_domain"),
        },
        "selected_opportunity": deepcopy(selected_rows[0]),
        "recommended_service_id": service_id,
        "why_now_brief": {
            "semantics": "SOURCE_BOUND_RESEARCH_REASON_NOT_BUYING_INTENT",
            "facts": facts,
            "service_hypothesis": f"Serviciul {service['label']} merită verificat, nu este considerat contractat sau necesar fără confirmare.",
        },
        "source_register": sources,
        "discovery_questions": questions,
        "outreach_draft": _outreach_draft(organization, service, facts),
        "offer_skeleton": _offer_skeleton(service, contract),
        "contact_governance": {
            "mode": "ORGANIZATION_FIRST",
            "person_targeting": False,
            "contact_surface": None,
            "contact_surface_state": "RESEARCH_REQUIRED",
            "lawful_basis_assessment": "REVIEW_REQUIRED",
            "suppression_checked": True,
            "opt_out_mechanism": "REQUIRED_BEFORE_SEND",
        },
        "approval_checklist": deepcopy(contract["external_action_gate"]["approval_requirements"]),
        "eligibility_state": outputs["eligibility_state"],
        "approval_state": outputs["ready"],
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "evidence_label": record.get("synthetic_label") or "SOURCE_BOUND_INTERNAL_RESEARCH",
    }
    pack_core["action_pack_id"] = canonical_hash({
        "unit": contract["id"],
        "organization_key": match["organization_key"],
        "prospect_id": match["prospect_id"],
        "opportunity_id": opportunity_id,
        "service_id": service_id,
        "fact_assertion_ids": [row["assertion_id"] for row in facts],
        "source_hashes": [row["content_hash"] for row in sources],
    })
    pack_core["content_sha256"] = canonical_hash(pack_core)
    return {
        "organization_key": match["organization_key"],
        "prospect_id": match["prospect_id"],
        "state": outputs["ready"],
        "reason": "FACT_BOUND_ACTION_PACK_PREPARED",
        "action_pack": pack_core,
        "eligibility_state": outputs["eligibility_state"],
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
    }


def build_action_packs(
    state: dict[str, Any],
    matches: dict[str, Any],
    reference_time: str,
    contract: dict[str, Any] | None = None,
    client_contract: dict[str, Any] | None = None,
    match_contract: dict[str, Any] | None = None,
    service_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(CONTRACT_PATH)
    client_contract = client_contract or load_json(CLIENT_CONTRACT_PATH)
    match_contract = match_contract or load_json(MATCH_CONTRACT_PATH)
    service_registry = service_registry or load_json(SERVICE_REGISTRY_PATH)
    validate_contract(contract, client_contract, match_contract, service_registry)
    _validate_inputs(state, matches, reference_time, contract, client_contract)
    before_state = canonical_hash(state)
    before_matches = canonical_hash(matches)
    service_index = {row["id"]: row for row in service_registry["services"]}
    records = state.get("records") or {}
    results = []
    seen_keys: set[str] = set()
    for match in matches.get("results") or []:
        key = _required_text(match.get("organization_key"), "organization key")
        if key in seen_keys:
            raise ValueError("duplicate organization match")
        seen_keys.add(key)
        record = records.get(key)
        if not record or record.get("prospect_id") != match.get("prospect_id"):
            raise ValueError("R07 match cannot be reconciled to prospect state")
        results.append(build_pack(record, match, service_index, contract))
    results.sort(key=lambda row: row["organization_key"])
    if canonical_hash(state) != before_state or canonical_hash(matches) != before_matches:
        raise AssertionError("R08 mutated an upstream input")
    ready_state = contract["outputs"]["ready"]
    return {
        "schema_version": 1,
        "engine_id": "EUCONS_R08_ORGANIZATION_ACTION_PACK",
        "unit": contract["id"],
        "reference_time": reference_time,
        "maximum_state": contract["external_action_gate"]["maximum_state"],
        "eligibility_state": contract["outputs"]["eligibility_state"],
        "summary": {
            "evaluated": len(results),
            "ready_for_approval": sum(row["state"] == ready_state for row in results),
            "held": sum(row["state"] != ready_state and row["state"] != contract["outputs"]["suppressed"] for row in results),
            "suppressed": sum(row["state"] == contract["outputs"]["suppressed"] for row in results),
        },
        "results": results,
        "production_records": 0 if all(record.get("synthetic_label") == "NON_EVIDENCE" for record in records.values()) else None,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
    }


def assert_output_path_safe(path: Path) -> None:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return
    raise ValueError("runtime action-pack artifacts cannot be written under repository root")


def main() -> None:
    parser = argparse.ArgumentParser(description="EUCONS organization-level research and action-pack engine")
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--matches", required=True, type=Path)
    parser.add_argument("--reference-time", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build_action_packs(load_json(args.state), load_json(args.matches), args.reference_time)
    assert_output_path_safe(args.output)
    CLIENT_ENGINE.write_atomic(args.output, result)
    print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
