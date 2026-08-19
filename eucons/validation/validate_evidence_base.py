#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "evidence" / "evidence_registry.json"
SERVICE_REGISTRY_PATH = ROOT / "services" / "service_registry.json"


class EvidenceValidationError(ValueError):
    pass


def fail(message: str) -> None:
    raise EvidenceValidationError(message)


def load_json(path: Path):
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


def require_unique_text_list(value, context, minimum=0):
    if not isinstance(value, list) or len(value) < minimum:
        fail(f"{context} must contain at least {minimum} items")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        fail(f"{context} contains blank/non-text item")
    if len(value) != len(set(value)):
        fail(f"{context} contains duplicates")
    return value


def validate_registry(registry, services, root=ROOT):
    if registry.get("product") != "EUCONS_COMMERCIAL_OS" or registry.get("phase") != "E03":
        fail("wrong product or phase")
    if registry.get("status") != "CANONICAL":
        fail("status must be CANONICAL")

    policy = registry.get("publication_policy") or {}
    if policy.get("public_states") != ["PUBLISHABLE"]:
        fail("PUBLISHABLE must be the only public state")
    if set(policy.get("non_public_states") or []) != {"HOLD", "RETIRED"}:
        fail("HOLD and RETIRED must be non-public states")
    if policy.get("unsupported_claim_state") != "HOLD":
        fail("unsupported claims must fail closed to HOLD")
    if policy.get("contradictory_material_fact_state") != "HOLD":
        fail("contradictory material facts must fail closed to HOLD")
    if policy.get("testimonial_requires_explicit_consent") is not True:
        fail("testimonial publication must require explicit consent")
    if policy.get("numeric_price_requires") != "APPROVED_PRICING_RULE":
        fail("numeric prices must require APPROVED_PRICING_RULE")

    minimum = registry.get("minimum_evidence") or {}
    required_claim_classes = {
        "SERVICE_OFFERING",
        "SERVICE_PROCESS",
        "CTA_AVAILABILITY",
        "COMPANY_IDENTITY",
        "COMPANY_EXPERIENCE",
        "CLIENT_RELATIONSHIP",
        "PROJECT_RESULT",
        "TESTIMONIAL",
        "EXPERT_IDENTITY",
        "EXPERT_ROLE",
        "EXPERT_CREDENTIAL",
        "FUNDING_FACT",
        "PRICE_TERM",
    }
    if set(minimum) != required_claim_classes:
        fail("minimum_evidence must define every canonical claim class exactly once")
    for claim_class, classes in minimum.items():
        require_unique_text_list(classes, f"minimum_evidence.{claim_class}", minimum=1)

    evidence_items = registry.get("evidence_items") or []
    evidence_by_id = {}
    for item in evidence_items:
        evidence_id = require_text(item, "id", "evidence item")
        if evidence_id in evidence_by_id:
            fail(f"duplicate evidence id {evidence_id}")
        evidence_class = require_text(item, "evidence_class", f"evidence {evidence_id}")
        require_text(item, "source_type", f"evidence {evidence_id}")
        source_path = require_text(item, "source_path", f"evidence {evidence_id}")
        if item.get("status") != "ACTIVE":
            fail(f"evidence {evidence_id} must be ACTIVE in the canonical E03 registry")
        allowed = require_unique_text_list(
            item.get("allowed_claim_classes"), f"evidence {evidence_id} allowed_claim_classes", minimum=1
        )
        unknown_allowed = set(allowed) - required_claim_classes
        if unknown_allowed:
            fail(f"evidence {evidence_id} references unknown claim classes: {sorted(unknown_allowed)}")
        if evidence_class == "DERIVED_ANALYSIS" and set(allowed) & {
            "COMPANY_IDENTITY", "CLIENT_RELATIONSHIP", "PROJECT_RESULT", "TESTIMONIAL", "FUNDING_FACT", "PRICE_TERM"
        }:
            fail(f"derived analysis cannot directly authorize material claim classes in {evidence_id}")
        resolved = root.parent / source_path
        if not resolved.exists():
            fail(f"evidence {evidence_id} source_path does not exist: {source_path}")
        evidence_by_id[evidence_id] = item

    claims = registry.get("claims") or []
    claim_ids = []
    public_service_refs = []
    hold_classes = set()
    for claim in claims:
        claim_id = require_text(claim, "id", "claim")
        claim_ids.append(claim_id)
        claim_class = require_text(claim, "claim_class", f"claim {claim_id}")
        if claim_class not in required_claim_classes:
            fail(f"claim {claim_id} has unknown claim_class {claim_class}")
        require_text(claim, "subject", f"claim {claim_id}")
        state = require_text(claim, "publication_state", f"claim {claim_id}")
        if state not in {"PUBLISHABLE", "HOLD", "RETIRED"}:
            fail(f"claim {claim_id} has invalid publication_state {state}")
        evidence_ids = require_unique_text_list(claim.get("evidence_ids"), f"claim {claim_id} evidence_ids")

        if state == "PUBLISHABLE":
            require_text(claim, "public_statement", f"claim {claim_id}")
            if not evidence_ids:
                fail(f"publishable claim {claim_id} has no evidence")
            unknown = [evidence_id for evidence_id in evidence_ids if evidence_id not in evidence_by_id]
            if unknown:
                fail(f"publishable claim {claim_id} references unknown evidence: {unknown}")
            evidence_classes = {evidence_by_id[evidence_id]["evidence_class"] for evidence_id in evidence_ids}
            if not evidence_classes & set(minimum[claim_class]):
                fail(
                    f"publishable claim {claim_id} lacks required evidence class; "
                    f"has={sorted(evidence_classes)}, requires one of={minimum[claim_class]}"
                )
            for evidence_id in evidence_ids:
                item = evidence_by_id[evidence_id]
                if claim_class not in item["allowed_claim_classes"]:
                    fail(f"evidence {evidence_id} is not authorized for claim class {claim_class}")
            if claim_class in {"CLIENT_RELATIONSHIP", "PROJECT_RESULT", "TESTIMONIAL"}:
                if claim.get("confidentiality_review") != "PUBLIC_APPROVED":
                    fail(f"publishable {claim_class} claim {claim_id} lacks PUBLIC_APPROVED confidentiality review")
            if claim_class == "TESTIMONIAL" and claim.get("consent_verified") is not True:
                fail(f"publishable testimonial claim {claim_id} lacks explicit consent")
            if claim_class == "SERVICE_OFFERING":
                public_service_refs.append(require_text(claim, "object_ref", f"claim {claim_id}"))
        else:
            hold_classes.add(claim_class)
            if "public_statement" in claim:
                fail(f"non-public claim {claim_id} must not carry fallback public_statement")
            if state == "HOLD":
                require_text(claim, "hold_reason", f"claim {claim_id}")

    if len(claim_ids) != len(set(claim_ids)):
        fail("duplicate claim ids")

    service_ids = [service.get("id") for service in services.get("services", [])]
    if not service_ids or any(not isinstance(service_id, str) or not service_id for service_id in service_ids):
        fail("E02 service registry is incomplete")
    if len(public_service_refs) != len(set(public_service_refs)):
        fail("multiple publishable SERVICE_OFFERING claims reference the same service")
    if set(public_service_refs) != set(service_ids):
        fail(
            "publishable SERVICE_OFFERING claims must exactly cover E02 services; "
            f"missing={sorted(set(service_ids) - set(public_service_refs))}, "
            f"extra={sorted(set(public_service_refs) - set(service_ids))}"
        )

    mandatory_hold_classes = {
        "COMPANY_IDENTITY",
        "COMPANY_EXPERIENCE",
        "CLIENT_RELATIONSHIP",
        "PROJECT_RESULT",
        "TESTIMONIAL",
        "EXPERT_CREDENTIAL",
        "FUNDING_FACT",
        "PRICE_TERM",
    }
    missing_hold = mandatory_hold_classes - hold_classes
    if missing_hold:
        fail(f"E03 must explicitly HOLD unsupported sensitive claim classes: {sorted(missing_hold)}")

    return {
        "evidence_items": len(evidence_items),
        "claims": len(claims),
        "publishable_service_claims": len(public_service_refs),
        "held_sensitive_classes": len(mandatory_hold_classes),
    }


def main() -> None:
    try:
        registry = load_json(REGISTRY_PATH)
        services = load_json(SERVICE_REGISTRY_PATH)
        result = validate_registry(registry, services)
    except EvidenceValidationError as exc:
        raise SystemExit(f"EUCONS E03 evidence base validation failed: {exc}")
    print(
        "EUCONS E03 evidence base valid: "
        f"{result['evidence_items']} evidence items, {result['claims']} claims, "
        f"{result['publishable_service_claims']} supported service claims, "
        f"{result['held_sensitive_classes']} sensitive claim classes fail closed"
    )


if __name__ == "__main__":
    main()
