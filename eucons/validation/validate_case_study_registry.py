#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "cases" / "case_study_registry.json"
EVIDENCE_PATH = ROOT / "evidence" / "evidence_registry.json"
SERVICES_PATH = ROOT / "services" / "service_registry.json"
PEOPLE_PATH = ROOT / "people" / "people_registry.json"


class CaseStudyValidationError(ValueError):
    pass


def fail(message: str) -> None:
    raise CaseStudyValidationError(message)


def load(path: Path):
    if not path.exists():
        fail(f"missing {path.relative_to(ROOT)}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path.relative_to(ROOT)}: {exc}")


def require_text(obj, key, context):
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        fail(f"{context} missing {key}")
    return value.strip()


def require_text_list(value, context, minimum=0):
    if not isinstance(value, list) or len(value) < minimum:
        fail(f"{context} must contain at least {minimum} items")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        fail(f"{context} contains blank/non-text item")
    if len(value) != len(set(value)):
        fail(f"{context} contains duplicates")
    return value


def require_publishable_claim(claims, claim_id, expected_class, context):
    claim = claims.get(claim_id)
    if not claim:
        fail(f"{context} references missing {expected_class} claim {claim_id}")
    if claim.get("claim_class") != expected_class:
        fail(f"{context} claim {claim_id} must be {expected_class}, got {claim.get('claim_class')}")
    if claim.get("publication_state") != "PUBLISHABLE":
        fail(f"{context} claim {claim_id} is not PUBLISHABLE")
    return claim


def validate_case_study_registry(registry, evidence, services, people):
    if registry.get("product") != "EUCONS_COMMERCIAL_OS" or registry.get("phase") != "E05":
        fail("wrong product or phase")
    if registry.get("status") != "CANONICAL":
        fail("status must be CANONICAL")

    policy = registry.get("publication_policy") or {}
    expected = {
        "public_state": "PUBLISHABLE",
        "unsupported_state": "HOLD",
        "required_result_claim_class": "PROJECT_RESULT",
        "named_client_requires_claim_class": "CLIENT_RELATIONSHIP",
        "testimonial_requires_claim_class": "TESTIMONIAL",
        "private_confidentiality_mode": "PRIVATE",
    }
    for key, value in expected.items():
        if policy.get(key) != value:
            fail(f"publication_policy.{key} must be {value}")
    if set(policy.get("public_confidentiality_modes") or []) != {"PUBLIC_APPROVED", "ANONYMIZED_PUBLIC"}:
        fail("public confidentiality modes must be PUBLIC_APPROVED and ANONYMIZED_PUBLIC")
    for key in (
        "quantified_outcomes_require_claim_refs",
        "invented_cases_forbidden",
        "invented_metrics_forbidden",
        "empty_public_projection_allowed_during_development",
    ):
        if policy.get(key) is not True:
            fail(f"publication_policy.{key} must be true")

    claims = {item.get("id"): item for item in evidence.get("claims", []) if isinstance(item, dict)}
    service_ids = {item.get("id") for item in services.get("services", []) if isinstance(item, dict)}
    public_people_ids = {
        item.get("id") for item in people.get("people", [])
        if isinstance(item, dict) and item.get("publication_state") == "PUBLISHABLE"
    }
    if not service_ids:
        fail("E02 service registry is empty")

    cases = registry.get("cases")
    if not isinstance(cases, list):
        fail("cases must be a list")
    case_ids = []
    publishable_count = 0

    for case in cases:
        case_id = require_text(case, "id", "case")
        case_ids.append(case_id)
        context = f"case {case_id}"
        state = require_text(case, "publication_state", context)
        if state not in {"PUBLISHABLE", "HOLD", "RETIRED"}:
            fail(f"{context} has invalid publication_state {state}")

        if state == "PUBLISHABLE":
            publishable_count += 1
            require_text(case, "title", context)
            confidentiality = require_text(case, "confidentiality_mode", context)
            if confidentiality not in {"PUBLIC_APPROVED", "ANONYMIZED_PUBLIC"}:
                fail(f"{context} must use a public confidentiality mode")

            result_claim_ids = require_text_list(
                case.get("result_claim_ids"), f"{context} result_claim_ids", minimum=1
            )
            for claim_id in result_claim_ids:
                require_publishable_claim(claims, claim_id, "PROJECT_RESULT", context)

            outcome_claim_ids = require_text_list(
                case.get("outcome_claim_ids"), f"{context} outcome_claim_ids", minimum=1
            )
            if set(outcome_claim_ids) - set(result_claim_ids):
                fail(f"{context} outcome_claim_ids must be a subset of result_claim_ids")

            service_refs = require_text_list(case.get("service_ids"), f"{context} service_ids", minimum=1)
            unknown_services = set(service_refs) - service_ids
            if unknown_services:
                fail(f"{context} references unknown services: {sorted(unknown_services)}")

            person_refs = require_text_list(case.get("people_ids", []), f"{context} people_ids")
            unknown_people = set(person_refs) - public_people_ids
            if unknown_people:
                fail(f"{context} references people that are not E04 PUBLISHABLE: {sorted(unknown_people)}")

            attribution = require_text(case, "client_attribution", context)
            if attribution == "NAMED":
                if confidentiality != "PUBLIC_APPROVED":
                    fail(f"{context} named client requires PUBLIC_APPROVED confidentiality")
                require_text(case, "client_display_name", context)
                client_claim_id = require_text(case, "client_relationship_claim_id", context)
                require_publishable_claim(claims, client_claim_id, "CLIENT_RELATIONSHIP", context)
            elif attribution == "ANONYMIZED":
                if confidentiality != "ANONYMIZED_PUBLIC":
                    fail(f"{context} anonymized client requires ANONYMIZED_PUBLIC confidentiality")
                forbidden_identifiers = [
                    key for key in ("client_display_name", "client_legal_id", "client_email", "client_phone")
                    if case.get(key) not in (None, "")
                ]
                if forbidden_identifiers:
                    fail(f"{context} anonymized case exposes direct identifiers: {forbidden_identifiers}")
            else:
                fail(f"{context} client_attribution must be NAMED or ANONYMIZED")

            testimonial_claim_ids = require_text_list(
                case.get("testimonial_claim_ids", []), f"{context} testimonial_claim_ids"
            )
            for claim_id in testimonial_claim_ids:
                claim = require_publishable_claim(claims, claim_id, "TESTIMONIAL", context)
                if claim.get("consent_verified") is not True:
                    fail(f"{context} testimonial claim {claim_id} lacks explicit consent")
                if claim.get("confidentiality_review") != "PUBLIC_APPROVED":
                    fail(f"{context} testimonial claim {claim_id} lacks PUBLIC_APPROVED confidentiality")

            for key in ("public_problem", "public_intervention", "public_outcomes"):
                value = case.get(key)
                if not isinstance(value, (str, list)) or (isinstance(value, str) and not value.strip()) or (isinstance(value, list) and not value):
                    fail(f"{context} missing {key}")
        else:
            if state == "HOLD":
                require_text(case, "hold_reason", context)
            for key in ("public_problem", "public_intervention", "public_outcomes", "testimonial_text"):
                if key in case:
                    fail(f"{context} is non-public and must not carry {key} fallback copy")

    if len(case_ids) != len(set(case_ids)):
        fail("duplicate case ids")

    discovery = registry.get("discovery_state") or {}
    if not cases:
        if discovery.get("status") != "NO_VERIFIED_PUBLIC_CASES_INGESTED":
            fail("empty registry must explicitly declare no verified public cases ingested")
        if discovery.get("public_projection_count") != 0:
            fail("empty registry must report zero public projection")
    elif discovery.get("public_projection_count") != publishable_count:
        fail("discovery_state.public_projection_count must equal PUBLISHABLE case count")

    return {"cases": len(cases), "publishable": publishable_count}


def main():
    try:
        result = validate_case_study_registry(load(CASES_PATH), load(EVIDENCE_PATH), load(SERVICES_PATH), load(PEOPLE_PATH))
    except CaseStudyValidationError as exc:
        raise SystemExit(f"EUCONS E05 case-study registry validation failed: {exc}")
    print(
        "EUCONS E05 case-study registry valid: "
        f"{result['cases']} cases, {result['publishable']} publishable; unverified results and client proof fail closed"
    )


if __name__ == "__main__":
    main()
