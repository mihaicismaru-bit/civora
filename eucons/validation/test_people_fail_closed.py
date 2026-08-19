#!/usr/bin/env python3
import copy
import json
from pathlib import Path

from validate_people_registry import PeopleValidationError, validate_people_registry

ROOT = Path(__file__).resolve().parents[1]
PEOPLE = json.loads((ROOT / "people" / "people_registry.json").read_text(encoding="utf-8"))
EVIDENCE = json.loads((ROOT / "evidence" / "evidence_registry.json").read_text(encoding="utf-8"))
SERVICES = json.loads((ROOT / "services" / "service_registry.json").read_text(encoding="utf-8"))


def expect_failure(name, people, evidence, contains):
    try:
        validate_people_registry(people, evidence, SERVICES)
    except PeopleValidationError as exc:
        if contains not in str(exc):
            raise SystemExit(f"{name}: wrong failure: {exc}")
        return
    raise SystemExit(f"{name}: invalid people registry unexpectedly passed")


def synthetic_evidence():
    evidence = copy.deepcopy(EVIDENCE)
    evidence["claims"].extend([
        {
            "id": "SYN-IDENTITY",
            "claim_class": "EXPERT_IDENTITY",
            "publication_state": "PUBLISHABLE"
        },
        {
            "id": "SYN-ROLE",
            "claim_class": "EXPERT_ROLE",
            "publication_state": "PUBLISHABLE"
        },
        {
            "id": "SYN-CREDENTIAL",
            "claim_class": "EXPERT_CREDENTIAL",
            "publication_state": "PUBLISHABLE"
        }
    ])
    return evidence


def published_person():
    return {
        "id": "synthetic-person",
        "publication_state": "PUBLISHABLE",
        "display_name": "Synthetic Person",
        "identity_claim_id": "SYN-IDENTITY",
        "role_claim_ids": ["SYN-ROLE"],
        "competence_claim_ids": ["SYN-CREDENTIAL"],
        "service_ids": ["funding_strategy_and_eligibility"],
        "public_bio_claim_ids": ["SYN-IDENTITY", "SYN-ROLE", "SYN-CREDENTIAL"],
        "photo": {"state": "NONE"}
    }


def main():
    validate_people_registry(PEOPLE, EVIDENCE, SERVICES)

    missing_identity = copy.deepcopy(PEOPLE)
    missing_identity["people"] = [published_person()]
    missing_identity["discovery_state"]["public_projection_count"] = 1
    expect_failure("missing identity", missing_identity, EVIDENCE, "references missing EXPERT_IDENTITY")

    evidence = synthetic_evidence()
    wrong_role = copy.deepcopy(PEOPLE)
    person = published_person()
    person["role_claim_ids"] = ["SYN-CREDENTIAL"]
    wrong_role["people"] = [person]
    wrong_role["discovery_state"]["public_projection_count"] = 1
    expect_failure("wrong role claim class", wrong_role, evidence, "must be EXPERT_ROLE")

    unknown_service = copy.deepcopy(PEOPLE)
    person = published_person()
    person["service_ids"] = ["invented-service"]
    unknown_service["people"] = [person]
    unknown_service["discovery_state"]["public_projection_count"] = 1
    expect_failure("unknown service", unknown_service, evidence, "references unknown services")

    hold_leak = copy.deepcopy(PEOPLE)
    hold_leak["people"] = [{
        "id": "held-person",
        "publication_state": "HOLD",
        "hold_reason": "Synthetic missing evidence",
        "public_headline": "Invented public fallback"
    }]
    expect_failure("held profile fallback", hold_leak, EVIDENCE, "must not carry public_headline")

    verified = copy.deepcopy(PEOPLE)
    verified["people"] = [published_person()]
    verified["discovery_state"]["status"] = "VERIFIED_PEOPLE_AVAILABLE"
    verified["discovery_state"]["public_projection_count"] = 1
    result = validate_people_registry(verified, evidence, SERVICES)
    if result != {"people": 1, "publishable": 1}:
        raise SystemExit(f"verified synthetic person returned unexpected result: {result}")

    print("EUCONS E04 fail-closed people tests valid: missing claims, wrong claim class, unknown service and HOLD leakage are rejected")


if __name__ == "__main__":
    main()
