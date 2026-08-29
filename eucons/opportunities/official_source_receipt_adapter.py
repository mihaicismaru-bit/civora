#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
CONTRACT_PATH = EUCONS / "opportunities" / "official_source_receipt_adapter_contract.json"
MATCHING_CONTRACT_PATH = EUCONS / "opportunities" / "matching_contract.json"
MATCHER_PATH = EUCONS / "opportunities" / "match_opportunities.py"

HEX64 = re.compile(r"^[0-9a-f]{64}$")
RFC3339_UTC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
PERSON_LEVEL_KEYS = {
    "person_name",
    "personal_email",
    "personal_phone",
    "home_address",
    "private_contact",
    "personal_identifier",
    "date_of_birth",
    "personal_social_profile",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _load_matcher():
    spec = importlib.util.spec_from_file_location("eucons_official_receipt_matcher", MATCHER_PATH)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load canonical opportunity matcher")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MATCHER = _load_matcher()


def _parse_utc_z(value: Any, label: str) -> datetime:
    require(isinstance(value, str) and RFC3339_UTC_Z.fullmatch(value) is not None, f"{label} must be RFC3339 UTC Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{label} invalid") from exc
    require(parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0, f"{label} must resolve to UTC")
    return parsed


def _walk_keys(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def validate_contract(contract: dict[str, Any], matching_contract: dict[str, Any]) -> None:
    require(contract.get("id") == "EUCONS-E10-OFFICIAL-SOURCE-RECEIPT-ADAPTER-001", "adapter contract id drift")
    require(contract.get("status") == "CANONICAL", "adapter contract must remain canonical")

    deps = contract.get("canonical_dependencies") or {}
    require(deps.get("matching_contract") == "eucons/opportunities/matching_contract.json", "matching contract dependency drift")
    require(deps.get("matching_engine") == "eucons/opportunities/match_opportunities.py", "matching engine dependency drift")
    for dependency in deps.values():
        require((ROOT / dependency).is_file(), f"missing canonical dependency: {dependency}")

    MATCHER._validate_contract(matching_contract)
    guards = matching_contract["official_source_guards"]
    readback = contract.get("readback") or {}
    output = contract.get("output_registry") or {}
    boundaries = contract.get("output_boundaries") or {}
    rules = contract.get("rules") or {}

    require(set(readback.get("allowed_fact_classes") or []) == set(guards["material_fact_classes_requiring_official_binding"]),
            "adapter material fact classes drift from matcher")
    require(set(readback.get("required_candidate_fact_classes") or []) == set(guards["required_candidate_fact_classes"]),
            "adapter candidate fact classes drift from matcher")
    require(set(readback.get("forbidden_source_products") or []) == set(guards["forbidden_source_products"]),
            "adapter forbidden source products drift from matcher")
    require(readback.get("source_url_scheme") == guards["source_url_scheme"], "adapter official URL scheme drift")

    require(output.get("schema_version") == guards["registry_schema_version"], "output registry schema drift")
    require(output.get("state") == guards["registry_state"], "output registry state drift")
    require(output.get("verified_state") == guards["verified_state"], "output verified state drift")
    require(output.get("conflict_state") == guards["conflict_state"], "output conflict state drift")
    require(output.get("verification_method") == guards["verification_method"], "output verification method drift")
    require(set(output.get("receipt_fields") or []) == MATCHER.RECEIPT_FIELDS, "output receipt fields drift")

    source = contract.get("source_projection") or {}
    require(source.get("required_product") == "EUCONS_COMMERCIAL_OS", "projection product drift")
    require(source.get("required_bridge_id") == "PARTENER_P11_TO_EUCONS_E09", "projection bridge drift")
    require(source.get("read_only_required") is True and source.get("source_mutation_allowed_required") is False,
            "projection mutation boundary failed open")

    require(boundaries.get("eligibility_state") == "NOT_ASSESSED", "eligibility boundary failed open")
    require(boundaries.get("maximum_next_state") == "RESEARCH_READY", "maximum next state failed open")
    for key in (
        "external_contact_enabled",
        "automatic_offer_enabled",
        "automatic_send_enabled",
        "crm_write_enabled",
        "pipeline_write_enabled",
        "network_fetch_enabled",
    ):
        require(boundaries.get(key) is False, f"external boundary failed open: {key}")
    require(boundaries.get("human_review_required") is True, "human review boundary missing")

    for key in (
        "partener_is_discovery_only",
        "prefetched_readbacks_only",
        "exact_projection_value_hash_binding",
        "readback_value_mismatch_becomes_conflict",
        "explicit_conflict_becomes_blocked_receipt",
        "partial_verified_fact_sets_are_allowed_but_downstream_candidate_gate_remains_authoritative",
        "duplicate_receipt_ids_fail_closed",
        "duplicate_source_fact_disagreement_fails_closed_downstream",
        "projection_source_mutation_forbidden",
        "raw_fact_values_never_emitted",
        "person_level_fields_forbidden",
        "network_fetch_forbidden",
        "external_write_or_send_forbidden",
        "repository_runtime_output_forbidden",
    ):
        require(rules.get(key) is True, f"adapter rule failed open: {key}")


def validate_projection(projection: dict[str, Any], contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    source = contract["source_projection"]
    require(isinstance(projection, dict), "projection must be an object")
    require(projection.get("product") == source["required_product"], "unexpected projection product")
    require(projection.get("bridge_id") == source["required_bridge_id"], "unexpected projection bridge")
    require(projection.get("read_only") is source["read_only_required"], "projection must be read-only")
    require(projection.get("source_mutation_allowed") is source["source_mutation_allowed_required"],
            "projection source mutation must remain forbidden")
    rows = projection.get("opportunities")
    require(isinstance(rows, list), "projection opportunities must be a list")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        require(isinstance(row, dict), "projection opportunity must be an object")
        opportunity_id = row.get(source["required_opportunity_id_field"])
        require(isinstance(opportunity_id, str) and opportunity_id.strip(), "projection opportunity id missing")
        require(opportunity_id not in result, "duplicate opportunity id in projection")
        material = row.get(source["required_material_facts_field"])
        require(isinstance(material, dict), "projection material_facts must be an object")
        result[opportunity_id] = row
    return result


def _validate_readback_shape(readback: dict[str, Any], contract: dict[str, Any], reference_time: datetime) -> None:
    config = contract["readback"]
    require(isinstance(readback, dict), "official readback must be an object")
    require(set(readback) == set(config["required_fields"]), "official readback field drift")
    state = readback.get("readback_state")
    require(state in set(config["allowed_states"]), "official readback state invalid")
    require(isinstance(readback.get("opportunity_id"), str) and readback["opportunity_id"].strip(),
            "official readback opportunity id missing")
    source_product = readback.get("source_product")
    require(isinstance(source_product, str) and source_product.strip(), "official readback source product missing")
    forbidden_products = {str(item).casefold() for item in config["forbidden_source_products"]}
    require(source_product.strip().casefold() not in forbidden_products, "PARTENER.EU cannot satisfy official authority")
    authority = readback.get("source_authority")
    require(isinstance(authority, str) and authority.strip(), "official readback source authority missing")
    source_url = readback.get("source_url")
    require(isinstance(source_url, str), "official readback source URL missing")
    parsed_url = urlparse(source_url)
    require(parsed_url.scheme == config["source_url_scheme"] and bool(parsed_url.hostname),
            "official readback source URL must be HTTPS")
    hostname = str(parsed_url.hostname or "").casefold().rstrip(".")
    for forbidden in config["forbidden_source_hostnames"]:
        denied = str(forbidden).casefold().rstrip(".")
        require(hostname != denied and not hostname.endswith("." + denied), "PARTENER.EU hostname cannot satisfy official authority")
    digest = readback.get("source_document_sha256")
    require(isinstance(digest, str) and HEX64.fullmatch(digest) is not None, "official source document hash invalid")
    verified_at = _parse_utc_z(readback.get("verified_at"), "official readback verified_at")
    if config.get("future_verified_at_forbidden") is True:
        require(verified_at <= reference_time, "official readback verified_at is in the future")
    facts = readback.get("fact_values")
    conflicts = readback.get("conflict_fact_classes")
    require(isinstance(facts, dict), "official readback fact_values must be an object")
    require(isinstance(conflicts, list), "official readback conflict_fact_classes must be a list")
    allowed = set(config["allowed_fact_classes"])
    require(set(facts).issubset(allowed), "official readback contains unsupported fact class")
    require(set(conflicts).issubset(allowed), "official conflict contains unsupported fact class")
    require(len(conflicts) == len(set(conflicts)), "duplicate conflict fact class")
    found_person_keys = PERSON_LEVEL_KEYS & {key.casefold() for key in _walk_keys(facts)}
    require(not found_person_keys, f"person-level fields forbidden in official fact values: {sorted(found_person_keys)}")
    if state == config["complete_state"]:
        require(not conflicts, "complete official readback cannot contain conflict fact classes")
        require(bool(facts), "complete official readback must bind at least one fact")
    else:
        require(bool(conflicts), "conflict readback must identify at least one conflict fact class")


def _receipt_id(payload: dict[str, Any]) -> str:
    return canonical_hash(payload)


def adapt_readback(
    readback: dict[str, Any],
    projection_row: dict[str, Any],
    contract: dict[str, Any],
    reference_time: datetime,
) -> dict[str, Any]:
    _validate_readback_shape(readback, contract, reference_time)
    config = contract["readback"]
    output = contract["output_registry"]
    material = projection_row[contract["source_projection"]["required_material_facts_field"]]
    state = readback["readback_state"]

    conflict = state == config["conflict_state"]
    fact_hashes: dict[str, str] = {}
    if not conflict:
        for fact_class, value in sorted(readback["fact_values"].items()):
            if fact_class not in material or canonical_hash(value) != canonical_hash(material[fact_class]):
                conflict = True
                fact_hashes = {}
                break
            fact_hashes[fact_class] = canonical_hash(value)

    verification_state = output["conflict_state"] if conflict else output["verified_state"]
    if verification_state == output["verified_state"]:
        require(bool(fact_hashes), "verified receipt cannot be empty")

    basis = {
        "opportunity_id": readback["opportunity_id"],
        "verification_state": verification_state,
        "verification_method": output["verification_method"],
        "source_product": readback["source_product"].strip(),
        "source_authority": readback["source_authority"].strip(),
        "source_url": readback["source_url"],
        "source_document_sha256": readback["source_document_sha256"],
        "verified_at": readback["verified_at"],
        "verified_fact_hashes": fact_hashes,
    }
    return {"receipt_id": _receipt_id(basis), **basis}


def build_registry(
    projection: dict[str, Any],
    readbacks: list[dict[str, Any]],
    reference_time: str,
    contract: dict[str, Any] | None = None,
    matching_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(CONTRACT_PATH)
    matching_contract = matching_contract or load_json(MATCHING_CONTRACT_PATH)
    validate_contract(contract, matching_contract)
    reference = _parse_utc_z(reference_time, "reference_time")
    before_projection = canonical_hash(projection)
    projection_index = validate_projection(projection, contract)
    require(isinstance(readbacks, list), "official readbacks must be a list")

    receipts: list[dict[str, Any]] = []
    for readback in readbacks:
        opportunity_id = readback.get("opportunity_id") if isinstance(readback, dict) else None
        require(opportunity_id in projection_index, "official readback references unknown opportunity")
        receipts.append(adapt_readback(readback, projection_index[opportunity_id], contract, reference))

    receipts.sort(key=lambda row: (row["opportunity_id"], row["source_authority"], row["source_url"], row["receipt_id"]))
    ids = [row["receipt_id"] for row in receipts]
    require(len(ids) == len(set(ids)), "duplicate official receipt id")

    registry = {
        "schema_version": contract["output_registry"]["schema_version"],
        "state": contract["output_registry"]["state"],
        "receipts": receipts,
    }
    MATCHER.validate_official_registry(registry, matching_contract)
    if canonical_hash(projection) != before_projection:
        raise AssertionError("projection mutated while adapting official readbacks")
    joined = json.dumps(registry, ensure_ascii=False).casefold()
    require("fact_values" not in joined and "conflict_fact_classes" not in joined,
            "raw official readback fact values leaked into output")
    return registry


def _assert_output_outside_repo(path: Path) -> None:
    resolved = path.expanduser().resolve()
    repo = ROOT.resolve()
    require(not resolved.is_relative_to(repo), "repository runtime output is forbidden")


def main() -> None:
    parser = argparse.ArgumentParser(description="EUCONS prefetched official-source readback receipt adapter")
    parser.add_argument("--projection", required=True, type=Path)
    parser.add_argument("--readbacks", required=True, type=Path)
    parser.add_argument("--reference-time", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    _assert_output_outside_repo(args.output)
    projection = load_json(args.projection)
    readbacks_payload = load_json(args.readbacks)
    require(set(readbacks_payload) == {"readbacks"}, "readbacks envelope field drift")
    result = build_registry(projection, readbacks_payload["readbacks"], args.reference_time)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "registry_state": result["state"],
        "receipt_count": len(result["receipts"]),
        "verified_receipts": sum(row["verification_state"] == "VERIFIED_OFFICIAL_SOURCE" for row in result["receipts"]),
        "blocked_receipts": sum(row["verification_state"] == "BLOCKED_SOURCE_CONFLICT" for row in result["receipts"]),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
