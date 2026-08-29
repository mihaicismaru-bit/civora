#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "opportunities" / "official_source_operator_queue_contract.json"
DEFAULT_MATCHING_CONTRACT = EUCONS / "opportunities" / "matching_contract.json"
MATCHING_ENGINE_PATH = EUCONS / "opportunities" / "match_opportunities.py"
HEX64 = set("0123456789abcdef")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_matching_module():
    spec = importlib.util.spec_from_file_location("eucons_match_opportunities", MATCHING_ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load canonical opportunity matching engine")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def is_hex64(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value).issubset(HEX64)


def validate_contract(contract: dict[str, Any], matching_contract: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "operator queue schema drift")
    require(contract.get("engine_id") == "EUCONS_E10_OFFICIAL_SOURCE_OPERATOR_QUEUE", "operator queue engine drift")
    inputs = contract.get("input") or {}
    require(inputs.get("required_projection_product") == "EUCONS_COMMERCIAL_OS", "projection product drift")
    require(inputs.get("required_bridge_id") == "PARTENER_P11_TO_EUCONS_E09", "projection bridge drift")
    require(inputs.get("required_bridge_state") == "READY", "required bridge state drift")
    require(inputs.get("required_record_state") == "VERIFIED_AVAILABLE", "required record state drift")
    require(inputs.get("require_actionable") is True, "operator queue must remain actionable-only")
    require(inputs.get("official_registry_state") == "READ_ONLY_OFFICIAL_SOURCE_RECEIPTS", "official registry state drift")

    authority = contract.get("authority") or {}
    guards = matching_contract.get("official_source_guards") or {}
    require(authority.get("partener_role") == "DISCOVERY_ONLY", "PARTENER role must remain discovery-only")
    require(authority.get("waiting_state") == guards.get("waiting_authority_state") == "WAITING_SOURCE", "waiting authority state drift")
    require(authority.get("blocked_state") == guards.get("blocked_authority_state") == "BLOCKED_SOURCE_CONFLICT", "blocked authority state drift")
    require(authority.get("verified_state") == guards.get("verified_authority_state") == "OFFICIAL_SOURCE_VERIFIED", "verified authority state drift")
    require(
        set(authority.get("required_candidate_fact_classes") or [])
        == set(guards.get("required_candidate_fact_classes") or [])
        == {"status", "deadline"},
        "required candidate fact classes drift",
    )
    require(
        set(authority.get("material_fact_classes_requiring_official_binding") or [])
        == set(guards.get("material_fact_classes_requiring_official_binding") or []),
        "material official-binding classes drift",
    )

    triage = contract.get("triage") or {}
    require(triage.get("priority_order") == ["P0", "P1", "P2"], "triage priority order drift")
    require(triage.get("blocked_priority") == "P0", "blocked priority drift")
    require(triage.get("waiting_priority") == "P1", "waiting priority drift")
    require(triage.get("enrichment_priority") == "P2", "enrichment priority drift")
    require(triage.get("deterministic_sort") == ["priority_asc", "opportunity_id_asc"], "triage sort drift")

    output = contract.get("output") or {}
    for key in (
        "resolved_records_omitted",
        "raw_material_fact_values_forbidden",
        "person_level_fields_forbidden",
        "eligibility_conclusion_forbidden",
        "repository_runtime_output_forbidden",
    ):
        require(output.get(key) is True, f"operator queue output boundary failed open: {key}")
    require(output.get("external_action_authorized") is False, "operator queue cannot authorize external action")
    boundaries = contract.get("boundaries") or {}
    require(boundaries and all(value is False for value in boundaries.values()), "external boundary enabled")


def validate_projection(projection: dict[str, Any], contract: dict[str, Any]) -> None:
    inputs = contract["input"]
    require(projection.get("schema_version") == 1, "projection schema drift")
    require(projection.get("product") == inputs["required_projection_product"], "projection product mismatch")
    require(projection.get("bridge_id") == inputs["required_bridge_id"], "projection bridge mismatch")
    require(projection.get("bridge_state") == inputs["required_bridge_state"], "source projection is not READY")
    require(projection.get("read_only") is True, "projection must remain read-only")
    require(projection.get("source_mutation_allowed") is False, "projection source mutation must remain disabled")
    source = projection.get("source") or {}
    require(source.get("product") == "PARTENER.EU", "operator queue expects PARTENER discovery projection")
    require(source.get("policy_accepted") is True, "projection source policy is not accepted")
    require(is_hex64(source.get("sha256")), "projection source hash invalid")
    opportunities = projection.get("opportunities")
    require(isinstance(opportunities, list), "projection opportunities must be a list")


def task_for_record(
    record: dict[str, Any],
    authority_result: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any] | None:
    authority_contract = contract["authority"]
    triage = contract["triage"]
    opportunity_id = record.get("id")
    require(isinstance(opportunity_id, str) and opportunity_id.strip(), "opportunity id missing")
    material = record.get("material_facts") or {}
    require(isinstance(material, dict), f"material facts invalid for {opportunity_id}")

    allowed_material = set(authority_contract["material_fact_classes_requiring_official_binding"])
    material_classes_present = set(material).intersection(allowed_material)
    bound = set(authority_result.get("official_fact_classes") or set())
    require(bound.issubset(allowed_material), f"official fact class drift for {opportunity_id}")
    required = set(authority_contract["required_candidate_fact_classes"])
    missing_candidate = sorted(required - bound)
    unbound_material = sorted(material_classes_present - bound)
    state = authority_result.get("state")

    if state == authority_contract["blocked_state"]:
        priority = triage["blocked_priority"]
        action = triage["blocked_action"]
        reason_code = "OFFICIAL_SOURCE_CONFLICT"
    elif state == authority_contract["waiting_state"]:
        priority = triage["waiting_priority"]
        action = triage["waiting_action"]
        reason_code = "REQUIRED_OFFICIAL_BINDING_MISSING"
    elif state == authority_contract["verified_state"] and unbound_material:
        priority = triage["enrichment_priority"]
        action = triage["enrichment_action"]
        reason_code = "OPTIONAL_MATCHING_FACT_BINDINGS_INCOMPLETE"
    elif state == authority_contract["verified_state"]:
        return None
    else:
        raise ValueError(f"unexpected authority state for {opportunity_id}: {state}")

    provenance = record.get("provenance") or {}
    source_as_of = provenance.get("source_as_of") if isinstance(provenance, dict) else None
    return {
        "opportunity_id": opportunity_id,
        "title": record.get("title"),
        "programme": record.get("programme"),
        "priority": priority,
        "authority_state": state,
        "reason_code": reason_code,
        "operator_action": action,
        "required_candidate_fact_classes": sorted(required),
        "verified_fact_classes": sorted(bound),
        "missing_candidate_fact_classes": missing_candidate,
        "unbound_material_fact_classes": unbound_material,
        "official_source_count": int(authority_result.get("official_source_count") or 0),
        "discovery_context": {
            "source_product": "PARTENER.EU",
            "role": "DISCOVERY_ONLY",
            "source_as_of": source_as_of,
        },
        "external_action_authorized": False,
    }


def validate_safe_output(value: Any) -> None:
    forbidden_keys = {
        "material_facts",
        "verified_fact_hashes",
        "source_url",
        "source_document_sha256",
        "email",
        "phone",
        "address",
        "personal_identifier",
        "requested_grant_eur",
        "eligibility_conclusion",
        "award_probability",
    }
    if isinstance(value, dict):
        overlap = forbidden_keys.intersection(value)
        require(not overlap, f"operator queue leaked forbidden fields: {sorted(overlap)}")
        for item in value.values():
            validate_safe_output(item)
    elif isinstance(value, list):
        for item in value:
            validate_safe_output(item)


def build_queue(
    projection: dict[str, Any],
    registry: dict[str, Any] | None,
    contract: dict[str, Any],
    matching_contract: dict[str, Any],
) -> dict[str, Any]:
    matching = load_matching_module()
    matching._validate_contract(matching_contract)
    validate_contract(contract, matching_contract)
    validate_projection(projection, contract)
    receipts = matching.validate_official_registry(registry, matching_contract)

    inputs = contract["input"]
    priority_rank = {value: index for index, value in enumerate(contract["triage"]["priority_order"])}
    tasks: list[dict[str, Any]] = []
    eligible_count = 0
    resolved_count = 0
    skipped_count = 0
    for record in projection["opportunities"]:
        require(isinstance(record, dict), "projection opportunity must be an object")
        if record.get("commercial_state") != inputs["required_record_state"]:
            skipped_count += 1
            continue
        if inputs["require_actionable"] and record.get("actionable") is not True:
            skipped_count += 1
            continue
        eligible_count += 1
        authority_result = matching.official_authority_for_record(record, receipts, matching_contract)
        task = task_for_record(record, authority_result, contract)
        if task is None:
            resolved_count += 1
        else:
            tasks.append(task)

    tasks.sort(key=lambda row: (priority_rank[row["priority"]], row["opportunity_id"]))
    summary = {
        "eligible_actionable_records": eligible_count,
        "operator_tasks": len(tasks),
        "blocked_conflicts": sum(1 for row in tasks if row["priority"] == contract["triage"]["blocked_priority"]),
        "waiting_required_bindings": sum(1 for row in tasks if row["priority"] == contract["triage"]["waiting_priority"]),
        "enrichment_bindings": sum(1 for row in tasks if row["priority"] == contract["triage"]["enrichment_priority"]),
        "resolved_records_omitted": resolved_count,
        "non_actionable_or_held_records_skipped": skipped_count,
    }
    result = {
        "schema_version": contract["schema_version"],
        "engine_id": contract["engine_id"],
        "state": contract["output"]["state"],
        "read_only": True,
        "source_projection_sha256": projection["source"]["sha256"],
        "official_registry_state": registry.get("state") if registry is not None else "ABSENT",
        "summary": summary,
        "tasks": tasks,
        "boundaries": dict(contract["boundaries"]),
    }
    result["queue_id"] = canonical_hash({
        "engine_id": result["engine_id"],
        "source_projection_sha256": result["source_projection_sha256"],
        "official_registry_state": result["official_registry_state"],
        "tasks": tasks,
    })
    validate_safe_output(result)
    return result


def ensure_output_outside_repo(path: Path) -> None:
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return
    raise ValueError("repository runtime output is forbidden")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projection", required=True)
    parser.add_argument("--official-registry", default=None)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--matching-contract", default=str(DEFAULT_MATCHING_CONTRACT))
    parser.add_argument("--output", default=None, help="optional JSON path outside repository; stdout when omitted")
    args = parser.parse_args()

    projection = load_json(Path(args.projection))
    registry = load_json(Path(args.official_registry)) if args.official_registry else None
    contract = load_json(Path(args.contract))
    matching_contract = load_json(Path(args.matching_contract))
    result = build_queue(projection, registry, contract, matching_contract)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        ensure_output_outside_repo(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
