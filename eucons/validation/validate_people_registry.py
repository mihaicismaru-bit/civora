#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PEOPLE_PATH = ROOT / "people" / "people_registry.json"
EVIDENCE_PATH = ROOT / "evidence" / "evidence_registry.json"
SERVICES_PATH = ROOT / "services" / "service_registry.json"


class PeopleValidationError(ValueError):
    pass


def fail(message: str) -> None:
    raise PeopleValidationError(message)


def load(path: Path):
    if not path.exists():
        fail(f"missing {path.relative_to(ROOT)}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path.relative_to(ROOT)}: {exc}")


def text(obj, key, context):
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        fail(f"{context} missing {key}")
    return value.strip()


def text_list(value, context, minimum=0):
    if not isinstance(value, list) or len(value) < minimum:
        fail(f"{context} must contain at least {minimum} items")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        fail(f"{context} contains blank/non-text item")
    if len(value) != len(set(value)):
        fail(f"{context} contains duplicates")
    return value


def require_claim(claims, claim_id, expected_class, context):
    claim = claims.get(claim_id)
    if not claim:
        fail(f"{context} references missing {expected_class} claim {claim_id}")
    if claim.get("claim_class") != expected_class:
        fail(f"{context} claim {claim_id} must be {expected_class}, got {claim.get('claim_class')}")
    if claim.get("publication_state") != "PUBLISHABLE":
        fail(f"{context} claim {claim_id} is not PUBLISHABLE")
    return claim


def validate_people_registry(registry, evidence, services):
    if registry.get("product") != "EUCONS_COMMERCIAL_OS" or registry.get("phase") != "E04":
        fail("wrong product or phase")
    if registry.get("status") != "CANONICAL":
        fail("status must be CANONICAL")

    policy = registry.get("publication_policy") or {}
    if policy.get("public_state") != "PUBLISHABLE" or policy.get("unsupported_state") != "HOLD":
        fail("people publication states must be PUBLISHABLE/HOLD")
    if policy.get("required_claim_classes") != ["EXPERT_IDENTITY", "EXPERT_ROLE", "EXPERT_CREDENTIAL"]:
        fail("required_claim_classes must be identity, role and credential")
    if policy.get("minimum_current_roles") != 1 or policy.get("minimum_competence_claims") != 1:
        fail("published people require at least one role and one competence claim")
    if policy.get("invented_profiles_forbidden") is not True or policy.get("invented_portraits_forbidden") is not True:
        fail("invented profiles and portraits must be forbidden")
    if policy.get("unverified_photo_behavior") != "INITIALS_OR_NONE":
        fail("unverified photos must fall back to initials or none")

    evidence_claims = {claim.get("id"): claim for claim in evidence.get("claims", []) if isinstance(claim, dict)}
    evidence_items = {item.get("id"): item for item in evidence.get("evidence_items", []) if isinstance(item, dict)}
    service_ids = {service.get("id") for service in services.get("services", []) if isinstance(service, dict)}
    if not service_ids:
        fail("E02 service registry is empty")

    people = registry.get("people")
    if not isinstance(people, list):
        fail("people must be a list")
    ids = []
    publishable = 0
    for person in people:
        person_id = text(person, "id", "person")
        ids.append(person_id)
        context = f"person {person_id}"
        state = text(person, "publication_state", context)
        if state not in {"PUBLISHABLE", "HOLD", "RETIRED"}:
            fail(f"{context} has invalid publication_state {state}")

        if state == "PUBLISHABLE":
            publishable += 1
            text(person, "display_name", context)
            identity_claim_id = text(person, "identity_claim_id", context)
            role_claim_ids = text_list(person.get("role_claim_ids"), f"{context} role_claim_ids", minimum=1)
            competence_claim_ids = text_list(
                person.get("competence_claim_ids"), f"{context} competence_claim_ids", minimum=1
            )
            require_claim(evidence_claims, identity_claim_id, "EXPERT_IDENTITY", context)
            for claim_id in role_claim_ids:
                require_claim(evidence_claims, claim_id, "EXPERT_ROLE", context)
            for claim_id in competence_claim_ids:
                require_claim(evidence_claims, claim_id, "EXPERT_CREDENTIAL", context)

            associated_services = text_list(person.get("service_ids"), f"{context} service_ids", minimum=1)
            unknown_services = set(associated_services) - service_ids
            if unknown_services:
                fail(f"{context} references unknown services: {sorted(unknown_services)}")

            bio_claim_ids = text_list(person.get("public_bio_claim_ids", []), f"{context} public_bio_claim_ids")
            allowed_bio_ids = {identity_claim_id, *role_claim_ids, *competence_claim_ids}
            if set(bio_claim_ids) - allowed_bio_ids:
                fail(f"{context} public bio contains claims outside verified identity/role/competence set")

            photo = person.get("photo") or {"state": "NONE"}
            photo_state = photo.get("state")
            if photo_state not in {"NONE", "VERIFIED"}:
                fail(f"{context} photo state must be NONE or VERIFIED")
            if photo_state == "VERIFIED":
                source_evidence_id = text(photo, "source_evidence_id", f"{context} photo")
                item = evidence_items.get(source_evidence_id)
                if not item or item.get("status") != "ACTIVE":
                    fail(f"{context} verified photo lacks active evidence {source_evidence_id}")
                text(photo, "source_url", f"{context} photo")
        else:
            if state == "HOLD":
                text(person, "hold_reason", context)
            for key in ("public_bio", "public_headline"):
                if key in person:
                    fail(f"{context} is non-public and must not carry {key} fallback copy")

    if len(ids) != len(set(ids)):
        fail("duplicate person ids")

    discovery = registry.get("discovery_state") or {}
    if not people:
        if policy.get("empty_public_projection_allowed_during_development") is not True:
            fail("empty people registry not allowed by policy")
        if discovery.get("status") != "NO_VERIFIED_EUROCONS_PEOPLE_INGESTED":
            fail("empty people registry must explicitly declare no verified people ingested")
        if discovery.get("public_projection_count") != 0:
            fail("empty people registry must report zero public projection")
    elif discovery.get("public_projection_count") != publishable:
        fail("discovery_state.public_projection_count must equal number of PUBLISHABLE people")

    return {"people": len(people), "publishable": publishable}


def main():
    try:
        result = validate_people_registry(load(PEOPLE_PATH), load(EVIDENCE_PATH), load(SERVICES_PATH))
    except PeopleValidationError as exc:
        raise SystemExit(f"EUCONS E04 people registry validation failed: {exc}")
    print(
        "EUCONS E04 people registry valid: "
        f"{result['people']} records, {result['publishable']} publishable; unverified people fail closed"
    )


if __name__ == "__main__":
    main()
