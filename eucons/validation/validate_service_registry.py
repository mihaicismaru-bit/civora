#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMERCIAL_CANON = ROOT / "canon" / "commercial_canon.json"
SERVICE_REGISTRY = ROOT / "services" / "service_registry.json"


def fail(message: str) -> None:
    raise SystemExit(f"EUCONS E02 service registry validation failed: {message}")


def load(path: Path):
    if not path.exists():
        fail(f"missing {path.relative_to(ROOT)}")
    return json.loads(path.read_text(encoding="utf-8"))


def require_text(obj, key, context):
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        fail(f"{context} missing {key}")


def require_text_list(obj, key, context, minimum=1):
    value = obj.get(key)
    if not isinstance(value, list) or len(value) < minimum:
        fail(f"{context} {key} must contain at least {minimum} items")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        fail(f"{context} {key} contains blank/non-text item")
    if len(value) != len(set(value)):
        fail(f"{context} {key} contains duplicates")
    return value


def main() -> None:
    commercial = load(COMMERCIAL_CANON)
    registry = load(SERVICE_REGISTRY)

    if registry.get("product") != "EUCONS_COMMERCIAL_OS" or registry.get("phase") != "E02":
        fail("wrong product or phase")
    if registry.get("status") != "CANONICAL":
        fail("status must be CANONICAL")

    pricing = registry.get("pricing_policy") or {}
    if pricing.get("public_fixed_prices") is not False:
        fail("public_fixed_prices must be false until an approved pricing rule exists")
    if pricing.get("default_mode") != "SCOPED_AFTER_QUALIFICATION":
        fail("default pricing mode must fail closed to SCOPED_AFTER_QUALIFICATION")
    require_text(pricing, "rule", "pricing_policy")

    capability_ids = {item["id"] for item in commercial.get("service_capabilities", [])}
    audience_ids = {item["id"] for item in commercial.get("audiences", [])}
    cta_ids = {item["id"] for item in commercial.get("ctas", [])}
    if not capability_ids or not audience_ids or not cta_ids:
        fail("E01 canon is incomplete")

    expected_audiences = {service_id: set() for service_id in capability_ids}
    for audience in commercial["audiences"]:
        for problem in audience.get("problems", []):
            for service_id in problem.get("service_capabilities", []):
                expected_audiences[service_id].add(audience["id"])

    services = registry.get("services") or []
    service_ids = [service.get("id") for service in services]
    if len(service_ids) != len(set(service_ids)):
        fail("duplicate service ids")
    if set(service_ids) != capability_ids:
        missing = sorted(capability_ids - set(service_ids))
        extra = sorted(set(service_ids) - capability_ids)
        fail(f"service ids must exactly materialize E01 capabilities; missing={missing}, extra={extra}")

    forbidden_numeric_keys = {"price", "fee", "discount", "fixed_price", "amount"}
    for service in services:
        service_id = service["id"]
        context = f"service {service_id}"
        for key in ("label", "summary", "commercial_outcome", "pricing_mode"):
            require_text(service, key, context)
        for key, minimum in (
            ("deliverables", 3),
            ("process", 4),
            ("boundaries", 3),
            ("evidence_requirements", 2),
            ("audiences", 1),
            ("ctas", 1),
        ):
            require_text_list(service, key, context, minimum)

        if service.get("pricing_mode") != "SCOPED_AFTER_QUALIFICATION":
            fail(f"{context} must use fail-closed pricing mode")

        unknown_audiences = set(service["audiences"]) - audience_ids
        if unknown_audiences:
            fail(f"{context} references unknown audiences: {sorted(unknown_audiences)}")
        if set(service["audiences"]) != expected_audiences[service_id]:
            fail(
                f"{context} audience coverage differs from E01 mapping: "
                f"expected={sorted(expected_audiences[service_id])}, got={sorted(service['audiences'])}"
            )

        unknown_ctas = set(service["ctas"]) - cta_ids
        if unknown_ctas:
            fail(f"{context} references unknown CTAs: {sorted(unknown_ctas)}")

        for key, value in service.items():
            if key in forbidden_numeric_keys and isinstance(value, (int, float)):
                fail(f"{context} contains unapproved numeric commercial term {key}")

    print(
        "EUCONS E02 service registry valid: "
        f"{len(services)} services exactly materialize E01 capabilities with deliverables, process, boundaries, evidence and CTAs"
    )


if __name__ == "__main__":
    main()
