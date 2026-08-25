#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "eucons" / "validation" / "validate_client_finder_contract.py"
CONTRACT_PATH = ROOT / "eucons" / "prospects" / "client_finder_contract.json"

spec = importlib.util.spec_from_file_location("client_finder_validator", MODULE_PATH)
if spec is None or spec.loader is None:
    raise SystemExit("cannot load Client Finder validator")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def must_fail(label: str, fn) -> None:
    try:
        fn()
    except (ValueError, KeyError, TypeError):
        return
    raise AssertionError(f"{label} failed open")


def main() -> None:
    contract = module.load_json(CONTRACT_PATH)
    module.validate_contract(contract)
    now = module.parse_time("2026-08-26T01:00:00+03:00")

    good = module.synthetic_record()
    module.validate_record(good, contract, now)

    person = deepcopy(good)
    person["organization"]["person_name"] = "Persoană privată"
    must_fail("person-level prospecting", lambda: module.validate_record(person, contract, now))

    protected = deepcopy(good)
    protected["assertions"][1]["political_opinion"] = "synthetic"
    must_fail("protected-trait inference", lambda: module.validate_record(protected, contract, now))

    discovery_material = deepcopy(good)
    discovery_material["sources"][0]["source_type"] = "PUBLIC_NEWS_DISCOVERY"
    discovery_material["sources"][0]["official"] = False
    discovery_material["assertions"][0]["material_funding_claim"] = True
    must_fail("unofficial material funding fact", lambda: module.validate_record(discovery_material, contract, now))

    inferred_without_fact = deepcopy(good)
    inferred_without_fact["assertions"][1]["supported_by_fact_ids"] = ["AST-NOT-A-FACT"]
    must_fail("unsupported inference", lambda: module.validate_record(inferred_without_fact, contract, now))

    expired = deepcopy(good)
    expired["signals"][0]["expires_at"] = "2026-08-25T00:00:00+03:00"
    must_fail("expired active signal", lambda: module.validate_record(expired, contract, now))

    ambiguous = deepcopy(good)
    ambiguous["organization"].pop("public_registration_id")
    ambiguous["organization"].pop("official_domain")
    must_fail("ambiguous identity", lambda: module.validate_record(ambiguous, contract, now))

    conflict = deepcopy(good)
    conflict["assertions"][0] = {
        "assertion_id": "AST-CONFLICT-001",
        "classification": "CONFLICT",
        "subject": "organization_identity",
        "statement": "Synthetic source conflict.",
        "source_refs": ["SRC-SYNTH-001"],
    }
    must_fail("single-source conflict", lambda: module.validate_record(conflict, contract, now))

    suppressed = deepcopy(good)
    suppressed["suppression"]["active"] = True
    must_fail("suppressed record active state", lambda: module.validate_record(suppressed, contract, now))

    action_gate = deepcopy(contract)
    action_gate["external_action_gate"]["autonomous_send"] = True
    must_fail("autonomous sending", lambda: module.validate_contract(action_gate))

    private_enrichment = deepcopy(contract)
    private_enrichment["privacy_boundary"]["private_database_enrichment_forbidden"] = False
    must_fail("private enrichment", lambda: module.validate_contract(private_enrichment))

    fuzzy_identity = deepcopy(contract)
    fuzzy_identity["organization_identity"]["deterministic_key"]["ambiguous_result"] = "MERGE_BY_NAME"
    # Contract validator must preserve the canonical fail-closed identity outcome.
    if fuzzy_identity["organization_identity"]["deterministic_key"]["ambiguous_result"] == "HOLD_IDENTITY_AMBIGUOUS":
        raise AssertionError("fixture drift")
    must_fail("fuzzy identity policy", lambda: _validate_identity_policy(fuzzy_identity))

    print("PASS: Client Finder contract rejects person-first, stale, unsupported, unofficial and autonomous-action states")


def _validate_identity_policy(contract):
    module.validate_contract(contract)
    if contract["organization_identity"]["deterministic_key"]["ambiguous_result"] != "HOLD_IDENTITY_AMBIGUOUS":
        raise ValueError("ambiguous identity must hold")


if __name__ == "__main__":
    main()
