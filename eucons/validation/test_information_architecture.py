#!/usr/bin/env python3
import copy
import json
from pathlib import Path

from validate_information_architecture import InformationArchitectureError, validate_information_architecture

ROOT = Path(__file__).resolve().parents[1]
IA = json.loads((ROOT / "web" / "information_architecture.json").read_text(encoding="utf-8"))
SERVICES = json.loads((ROOT / "services" / "service_registry.json").read_text(encoding="utf-8"))
COMMERCIAL = json.loads((ROOT / "canon" / "commercial_canon.json").read_text(encoding="utf-8"))
PEOPLE = json.loads((ROOT / "people" / "people_registry.json").read_text(encoding="utf-8"))
CASES = json.loads((ROOT / "cases" / "case_study_registry.json").read_text(encoding="utf-8"))


def expect_failure(name, ia, contains):
    try:
        validate_information_architecture(ia, SERVICES, COMMERCIAL, PEOPLE, CASES)
    except InformationArchitectureError as exc:
        if contains not in str(exc):
            raise SystemExit(f"{name}: wrong failure: {exc}")
        return
    raise SystemExit(f"{name}: invalid information architecture unexpectedly passed")


def main():
    result = validate_information_architecture(IA, SERVICES, COMMERCIAL, PEOPLE, CASES)
    if result["service_routes"] != len(SERVICES["services"]):
        raise SystemExit("canonical IA service-route coverage mismatch")

    duplicate = copy.deepcopy(IA)
    duplicate["core_routes"].append(copy.deepcopy(duplicate["core_routes"][0]))
    duplicate["core_routes"][-1]["id"] = "duplicate_home"
    expect_failure("duplicate route path", duplicate, "duplicate materialized path")

    missing_service = copy.deepcopy(IA)
    missing_service["service_routes"].pop()
    expect_failure("missing service route", missing_service, "service routes must exactly cover E02 services")

    bad_cta = copy.deepcopy(IA)
    bad_cta["cta_destinations"][0]["journey"] = "invented_journey"
    expect_failure("CTA journey drift", bad_cta, "journey differs from E01 canon")

    legal_primary = copy.deepcopy(IA)
    legal_primary["navigation"]["primary"].append("privacy")
    expect_failure("legal in primary", legal_primary, "legal routes must not appear in primary navigation")

    bad_family = copy.deepcopy(IA)
    next(item for item in bad_family["conditional_route_families"] if item["id"] == "person_profile")["required_state"] = "HOLD"
    expect_failure("HOLD route family", bad_family, "must materialize only PUBLISHABLE records")

    bad_slug = copy.deepcopy(IA)
    bad_slug["service_routes"][0]["slug"] = "Invalid Slug"
    expect_failure("invalid service slug", bad_slug, "invalid slug")

    external_cta = copy.deepcopy(IA)
    external_cta["cta_destinations"][0]["path"] = "/outside/"
    expect_failure("CTA outside route set", external_cta, "points outside core routes")

    print("EUCONS E06 information architecture regressions valid: duplicate paths, service gaps, CTA drift, legal-nav leakage, HOLD families, bad slugs and orphan CTAs are rejected")


if __name__ == "__main__":
    main()
