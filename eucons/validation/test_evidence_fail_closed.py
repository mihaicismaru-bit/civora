#!/usr/bin/env python3
import copy
import json
from pathlib import Path

from validate_evidence_base import EvidenceValidationError, validate_registry

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "evidence" / "evidence_registry.json").read_text(encoding="utf-8"))
SERVICES = json.loads((ROOT / "services" / "service_registry.json").read_text(encoding="utf-8"))


def expect_failure(name, registry, contains):
    try:
        validate_registry(registry, SERVICES)
    except EvidenceValidationError as exc:
        if contains not in str(exc):
            raise SystemExit(f"{name}: wrong failure: {exc}")
        return
    raise SystemExit(f"{name}: invalid registry unexpectedly passed")


def find_claim(registry, claim_id):
    return next(claim for claim in registry["claims"] if claim["id"] == claim_id)


def main():
    unsupported = copy.deepcopy(REGISTRY)
    claim = find_claim(unsupported, "CLM-COMPANY-EXPERIENCE")
    claim["publication_state"] = "PUBLISHABLE"
    claim["public_statement"] = "Synthetic unsupported experience claim."
    claim.pop("hold_reason", None)
    expect_failure("unsupported experience", unsupported, "has no evidence")

    testimonial = copy.deepcopy(REGISTRY)
    testimonial["evidence_items"].append({
        "id": "EV-SYNTHETIC-TESTIMONIAL",
        "evidence_class": "CLIENT_CONTROLLED_RECORD",
        "source_type": "REPOSITORY_CANON",
        "source_path": "eucons/evidence/evidence_registry.json",
        "status": "ACTIVE",
        "confidentiality": "PRIVATE",
        "allowed_claim_classes": ["TESTIMONIAL"]
    })
    claim = find_claim(testimonial, "CLM-TESTIMONIAL")
    claim["publication_state"] = "PUBLISHABLE"
    claim["public_statement"] = "Synthetic testimonial."
    claim["evidence_ids"] = ["EV-SYNTHETIC-TESTIMONIAL"]
    claim["confidentiality_review"] = "PUBLIC_APPROVED"
    claim["consent_verified"] = False
    claim.pop("hold_reason", None)
    expect_failure("testimonial without consent", testimonial, "lacks explicit consent")

    wrong_source = copy.deepcopy(REGISTRY)
    claim = find_claim(wrong_source, "CLM-COMPANY-LEGAL-IDENTITY")
    claim["publication_state"] = "PUBLISHABLE"
    claim["public_statement"] = "Synthetic legal identity claim."
    claim["evidence_ids"] = ["EV-E02-SERVICE-REGISTRY"]
    claim.pop("hold_reason", None)
    expect_failure("identity backed by marketing canon", wrong_source, "lacks required evidence class")

    incomplete_services = copy.deepcopy(REGISTRY)
    incomplete_services["claims"] = [
        claim for claim in incomplete_services["claims"] if claim["id"] != "CLM-SERVICE-PM-CAPACITY"
    ]
    expect_failure("missing service claim", incomplete_services, "must exactly cover E02 services")

    leaked_hold = copy.deepcopy(REGISTRY)
    claim = find_claim(leaked_hold, "CLM-PROJECT-RESULT")
    claim["public_statement"] = "Synthetic fallback result claim."
    expect_failure("HOLD fallback leakage", leaked_hold, "must not carry fallback public_statement")

    print("EUCONS E03 fail-closed regression tests valid: unsupported, wrong-source, consent, coverage and HOLD leakage are rejected")


if __name__ == "__main__":
    main()
