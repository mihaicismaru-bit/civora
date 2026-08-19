#!/usr/bin/env python3
import json
import re
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
IA_PATH = ROOT / "web" / "information_architecture.json"
SERVICES_PATH = ROOT / "services" / "service_registry.json"
COMMERCIAL_PATH = ROOT / "canon" / "commercial_canon.json"
PEOPLE_PATH = ROOT / "people" / "people_registry.json"
CASES_PATH = ROOT / "cases" / "case_study_registry.json"


class InformationArchitectureError(ValueError):
    pass


def fail(message: str) -> None:
    raise InformationArchitectureError(message)


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


def check_path(path, context):
    if not isinstance(path, str) or not path.startswith("/"):
        fail(f"{context} path must be root-relative")
    if path != "/" and not path.endswith("/"):
        fail(f"{context} path must end with trailing slash")
    if path != path.lower():
        fail(f"{context} path must be lowercase")
    if "//" in path or "?" in path or "#" in path:
        fail(f"{context} path contains invalid URL components")
    if " " in path:
        fail(f"{context} path contains spaces")
    return path


def validate_information_architecture(ia, services, commercial, people, cases):
    if ia.get("product") != "EUCONS_COMMERCIAL_OS" or ia.get("phase") != "E06":
        fail("wrong product or phase")
    if ia.get("status") != "CANONICAL":
        fail("status must be CANONICAL")
    if ia.get("canonical_origin") != "https://eucons.ro":
        fail("canonical_origin must be https://eucons.ro")

    policy = ia.get("path_policy") or {}
    for key in ("trailing_slash", "lowercase", "canonical_origin_required", "internal_links_use_paths", "hold_objects_never_materialize_routes"):
        if policy.get(key) is not True:
            fail(f"path_policy.{key} must be true")

    required_core_ids = {
        "home", "services_index", "funding_index", "companies", "public_authorities", "ngos",
        "projects_index", "team_index", "expertise", "guides_index", "articles_index", "resources",
        "about", "project_evaluation", "request_offer", "contact", "terms", "privacy"
    }
    core_routes = ia.get("core_routes") or []
    core_by_id = {}
    all_paths = set()
    audience_ids = {item.get("id") for item in commercial.get("audiences", [])}
    for route in core_routes:
        route_id = require_text(route, "id", "core route")
        if route_id in core_by_id:
            fail(f"duplicate core route id {route_id}")
        path = check_path(route.get("path"), f"core route {route_id}")
        if path in all_paths:
            fail(f"duplicate materialized path {path}")
        all_paths.add(path)
        require_text(route, "surface", f"core route {route_id}")
        if route.get("indexable") not in {True, False}:
            fail(f"core route {route_id} indexable must be boolean")
        if route.get("surface") == "AUDIENCE":
            audience_id = require_text(route, "audience_id", f"core route {route_id}")
            if audience_id not in audience_ids:
                fail(f"core route {route_id} references unknown audience {audience_id}")
        core_by_id[route_id] = route
    if set(core_by_id) != required_core_ids:
        fail(f"core route set mismatch; missing={sorted(required_core_ids-set(core_by_id))}, extra={sorted(set(core_by_id)-required_core_ids)}")

    service_ids = {item.get("id") for item in services.get("services", [])}
    service_routes = ia.get("service_routes") or []
    service_route_ids = []
    slug_re = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    for route in service_routes:
        service_id = require_text(route, "service_id", "service route")
        service_route_ids.append(service_id)
        slug = require_text(route, "slug", f"service route {service_id}")
        if not slug_re.fullmatch(slug):
            fail(f"service route {service_id} has invalid slug {slug}")
        path = check_path(route.get("path"), f"service route {service_id}")
        if path != f"/servicii/{slug}/":
            fail(f"service route {service_id} path must be derived from slug")
        if path in all_paths:
            fail(f"duplicate materialized path {path}")
        all_paths.add(path)
    if len(service_route_ids) != len(set(service_route_ids)):
        fail("duplicate service route service_id")
    if set(service_route_ids) != service_ids:
        fail(f"service routes must exactly cover E02 services; missing={sorted(service_ids-set(service_route_ids))}, extra={sorted(set(service_route_ids)-service_ids)}")

    expected_families = {
        "person_profile": ("/echipa/{slug}/", "E04_PEOPLE_REGISTRY"),
        "case_profile": ("/proiecte/{slug}/", "E05_CASE_STUDY_REGISTRY"),
        "opportunity_profile": ("/finantari/{slug}/", "E09_OPPORTUNITY_BRIDGE"),
        "guide_profile": ("/ghiduri/{slug}/", "E14_KNOWLEDGE_ENGINE"),
        "article_profile": ("/articole/{slug}/", "E15_EDITORIAL_LOOP"),
    }
    families = ia.get("conditional_route_families") or []
    family_ids = []
    for family in families:
        family_id = require_text(family, "id", "conditional route family")
        family_ids.append(family_id)
        if family_id not in expected_families:
            fail(f"unexpected conditional route family {family_id}")
        pattern, source = expected_families[family_id]
        if family.get("pattern") != pattern or family.get("source") != source:
            fail(f"conditional route family {family_id} has wrong pattern/source")
        if family.get("required_state") != "PUBLISHABLE" or family.get("active_when_available") is not True:
            fail(f"conditional route family {family_id} must materialize only PUBLISHABLE records")
    if set(family_ids) != set(expected_families) or len(family_ids) != len(set(family_ids)):
        fail("conditional route families must exactly match the canonical family set")

    if any(item.get("publication_state") != "PUBLISHABLE" for item in people.get("people", []) if item.get("id") in []):
        fail("unreachable defensive people state")
    # E06 defines route families, but concrete people/case routes must not be pre-materialized from HOLD data.
    public_people = [item for item in people.get("people", []) if item.get("publication_state") == "PUBLISHABLE"]
    public_cases = [item for item in cases.get("cases", []) if item.get("publication_state") == "PUBLISHABLE"]
    for family_id, records in (("person_profile", public_people), ("case_profile", public_cases)):
        if records and not any(f.get("id") == family_id for f in families):
            fail(f"missing route family for available {family_id} records")

    cta_ids = {item.get("id") for item in commercial.get("ctas", [])}
    cta_journeys = {item.get("id"): item.get("journey") for item in commercial.get("ctas", [])}
    destinations = ia.get("cta_destinations") or []
    destination_ids = []
    core_paths = {route["path"] for route in core_routes}
    for destination in destinations:
        cta_id = require_text(destination, "cta_id", "cta destination")
        destination_ids.append(cta_id)
        path = check_path(destination.get("path"), f"cta destination {cta_id}")
        if path not in core_paths:
            fail(f"cta destination {cta_id} points outside core routes: {path}")
        if destination.get("journey") != cta_journeys.get(cta_id):
            fail(f"cta destination {cta_id} journey differs from E01 canon")
    if set(destination_ids) != cta_ids or len(destination_ids) != len(set(destination_ids)):
        fail("cta destinations must exactly cover E01 CTAs")

    navigation = ia.get("navigation") or {}
    for group in ("primary", "utility", "footer"):
        ids = navigation.get(group)
        if not isinstance(ids, list) or not ids:
            fail(f"navigation.{group} must be a non-empty list")
        if len(ids) != len(set(ids)):
            fail(f"navigation.{group} contains duplicates")
        unknown = set(ids) - set(core_by_id)
        if unknown:
            fail(f"navigation.{group} references unknown routes: {sorted(unknown)}")
    if {"terms", "privacy"} & set(navigation["primary"]):
        fail("legal routes must not appear in primary navigation")

    links = ia.get("internal_link_contract") or {}
    for key in ("home_must_link", "service_pages_link_to", "audience_pages_link_to", "case_pages_link_to", "knowledge_pages_link_to"):
        ids = links.get(key)
        if not isinstance(ids, list) or not ids:
            fail(f"internal_link_contract.{key} must be non-empty")
        unknown = set(ids) - set(core_by_id)
        if unknown:
            fail(f"internal_link_contract.{key} references unknown routes: {sorted(unknown)}")
    if links.get("legal_pages_must_not_be_primary_navigation") is not True:
        fail("legal page primary-nav guard must be true")

    canonicals = {path: urljoin(ia["canonical_origin"] + "/", path.lstrip("/")) for path in all_paths}
    if len(canonicals) != len(all_paths):
        fail("canonical URL generation collision")

    return {
        "core_routes": len(core_routes),
        "service_routes": len(service_routes),
        "conditional_families": len(families),
        "cta_destinations": len(destinations),
        "materialized_paths": len(all_paths),
    }


def main():
    try:
        result = validate_information_architecture(load(IA_PATH), load(SERVICES_PATH), load(COMMERCIAL_PATH), load(PEOPLE_PATH), load(CASES_PATH))
    except InformationArchitectureError as exc:
        raise SystemExit(f"EUCONS E06 information architecture validation failed: {exc}")
    print(
        "EUCONS E06 information architecture valid: "
        f"{result['core_routes']} core routes, {result['service_routes']} service routes, "
        f"{result['conditional_families']} conditional families, {result['cta_destinations']} CTA mappings"
    )


if __name__ == "__main__":
    main()
