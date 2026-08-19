#!/usr/bin/env python3
import copy
import json
from pathlib import Path

from validate_case_study_registry import CaseStudyValidationError, validate_case_study_registry

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "cases" / "case_study_registry.json").read_text(encoding="utf-8"))
EVIDENCE = json.loads((ROOT / "evidence" / "evidence_registry.json").read_text(encoding="utf-8"))
SERVICES = json.loads((ROOT / "services" / "service_registry.json").read_text(encoding="utf-8"))
PEOPLE = json.loads((ROOT / "people" / "people_registry.json").read_text(encoding="utf-8"))


def expect_failure(name, cases, evidence, contains):
    try:
        validate_case_study_registry(cases, evidence, SERVICES, PEOPLE)
    except CaseStudyValidationError as exc:
        if contains not in str(exc):
            raise SystemExit(f"{name}: wrong failure: {exc}")
        return
    raise SystemExit(f"{name}: invalid case registry unexpectedly passed")


def evidence_with_public_case_claims():
    evidence = copy.deepcopy(EVIDENCE)
    evidence["claims"].extend([
        {
            "id": "SYN-RESULT",
            "claim_class": "PROJECT_RESULT",
            "publication_state": "PUBLISHABLE",
            "confidentiality_review": "PUBLIC_APPROVED"
        },
        {
            "id": "SYN-CLIENT",
            "claim_class": "CLIENT_RELATIONSHIP",
            "publication_state": "PUBLISHABLE",
            "confidentiality_review": "PUBLIC_APPROVED"
        },
        {
            "id": "SYN-TESTIMONIAL",
            "claim_class": "TESTIMONIAL",
            "publication_state": "PUBLISHABLE",
            "confidentiality_review": "PUBLIC_APPROVED",
            "consent_verified": true
        }
    ])
    return evidence


def valid_named_case():
    return {
        "id": "synthetic-case",
        "publication_state": "PUBLISHABLE",
        "title": "Synthetic validated case",
        "confidentiality_mode": "PUBLIC_APPROVED",
        "client_attribution": "NAMED",
        "client_display_name": "Synthetic Client",
        "client_relationship_claim_id": "SYN-CLIENT",
        "result_claim_ids": ["SYN-RESULT"],
        "outcome_claim_ids": ["SYN-RESULT"],
        "testimonial_claim_ids": [],
        "service_ids": ["implementation_and_reporting"],
        "people_ids": [],
        "public_problem": "Synthetic problem used only for validator regression coverage.",
        "public_intervention": "Synthetic intervention used only for validator regression coverage.",
        "public_outcomes": ["Synthetic outcome backed by SYN-RESULT in this test fixture."]
    }


def main():
    validate_case_study_registry(CASES, EVIDENCE, SERVICES, PEOPLE)

    unsupported = copy.deepcopy(CASES)
    unsupported["cases"] = [valid_named_case()]
    unsupported["discovery_state"]["public_projection_count"] = 1
    expect_failure("unsupported public case", unsupported, EVIDENCE, "references missing PROJECT_RESULT")

    evidence = evidence_with_public_case_claims()

    named_without_public_confidentiality = copy.deepcopy(CASES)
    case = valid_named_case()
    case["confidentiality_mode"] = "ANONYMIZED_PUBLIC"
    named_without_public_confidentiality["cases"] = [case]
    named_without_public_confidentiality["discovery_state"]["public_projection_count"] = 1
    expect_failure(
        "named client confidentiality",
        named_without_public_confidentiality,
        evidence,
        "named client requires PUBLIC_APPROVED confidentiality",
    )

    anonymized_leak = copy.deepcopy(CASES)
    case = valid_named_case()
    case["confidentiality_mode"] = "ANONYMIZED_PUBLIC"
    case["client_attribution"] = "ANONYMIZED"
    case.pop("client_relationship_claim_id")
    anonymized_leak["cases"] = [case]
    anonymized_leak["discovery_state"]["public_projection_count"] = 1
    expect_failure("anonymized identifier leak", anonymized_leak, evidence, "exposes direct identifiers")

    untracked_outcome = copy.deepcopy(CASES)
    case = valid_named_case()
    case["outcome_claim_ids"] = ["SYN-OTHER"]
    untracked_outcome["cases"] = [case]
    untracked_outcome["discovery_state"]["public_projection_count"] = 1
    expect_failure("untracked outcome", untracked_outcome, evidence, "must be a subset of result_claim_ids")

    testimonial_without_consent = copy.deepcopy(CASES)
    evidence_no_consent = evidence_with_public_case_claims()
    next(claim for claim in evidence_no_consent["claims"] if claim.get("id") == "SYN-TESTIMONIAL")["consent_verified"] = False
    case = valid_named_case()
    case["testimonial_claim_ids"] = ["SYN-TESTIMONIAL"]
    testimonial_without_consent["cases"] = [case]
    testimonial_without_consent["discovery_state"]["public_projection_count"] = 1
    expect_failure("testimonial without consent", testimonial_without_consent, evidence_no_consent, "lacks explicit consent")

    hold_leak = copy.deepcopy(CASES)
    hold_leak["cases"] = [{
        "id": "held-case",
        "publication_state": "HOLD",
        "hold_reason": "Synthetic evidence gap",
        "public_outcomes": ["Invented fallback result"]
    }]
    expect_failure("HOLD case leakage", hold_leak, EVIDENCE, "must not carry public_outcomes")

    valid = copy.deepcopy(CASES)
    valid["cases"] = [valid_named_case()]
    valid["discovery_state"]["status"] = "VERIFIED_PUBLIC_CASES_AVAILABLE"
    valid["discovery_state"]["public_projection_count"] = 1
    result = validate_case_study_registry(valid, evidence, SERVICES, PEOPLE)
    if result != {"cases": 1, "publishable": 1}:
        raise SystemExit(f"valid synthetic case returned unexpected result: {result}")

    print("EUCONS E05 fail-closed case tests valid: unsupported proof, confidentiality, identifier leakage, untracked outcomes, testimonial consent and HOLD leakage are rejected")


if __name__ == "__main__":
    main()
