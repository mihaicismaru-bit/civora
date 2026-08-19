#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

import sys
sys.path.insert(0, str(WEB))
from build_public_site import PublicSiteBuildError, build, publishable_service_ids  # noqa: E402

IA_PATH = WEB / "information_architecture.json"
SITE_PATH = WEB / "public_site.json"
SERVICES_PATH = ROOT / "services" / "service_registry.json"
EVIDENCE_PATH = ROOT / "evidence" / "evidence_registry.json"
PEOPLE_PATH = ROOT / "people" / "people_registry.json"
CASES_PATH = ROOT / "cases" / "case_study_registry.json"


class PublicSiteValidationError(ValueError):
    pass


def fail(message: str) -> None:
    raise PublicSiteValidationError(message)


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        fail(f"cannot load {path.relative_to(ROOT)}: {exc}")


def validate_public_site() -> dict:
    ia = load(IA_PATH)
    site = load(SITE_PATH)
    services = load(SERVICES_PATH)
    evidence = load(EVIDENCE_PATH)
    people = load(PEOPLE_PATH)
    cases = load(CASES_PATH)

    if site.get("product") != "EUCONS_COMMERCIAL_OS" or site.get("phase") != "E08":
        fail("wrong E08 public-site product/phase")
    if site.get("status") != "CANONICAL" or site.get("build_state") != "DEVELOPMENT_NOINDEX":
        fail("E08 site must remain canonical DEVELOPMENT_NOINDEX")
    rules = site.get("hard_rules") or {}
    for key in (
        "all_e08_pages_noindex", "external_stylesheets_forbidden", "unsupported_claims_omitted",
        "hold_records_omitted", "fake_metrics_forbidden", "fake_testimonials_forbidden",
        "fake_clients_forbidden", "numeric_prices_forbidden_until_e13", "forms_must_be_dry_run_until_e11"
    ):
        if rules.get(key) is not True:
            fail(f"hard_rules.{key} must be true")

    with tempfile.TemporaryDirectory(prefix="eucons-e08-") as tmp:
        output = Path(tmp)
        try:
            manifest = build(output)
        except PublicSiteBuildError as exc:
            fail(str(exc))

        core_paths = {item["path"] for item in ia.get("core_routes", [])}
        service_route_by_id = {item["service_id"]: item for item in ia.get("service_routes", [])}
        public_service_ids = publishable_service_ids(evidence)
        expected_service_paths = {
            route["path"] for service_id, route in service_route_by_id.items() if service_id in public_service_ids
        }
        expected_paths = core_paths | expected_service_paths
        built_paths = {item["path"] for item in manifest.get("pages", [])}
        if built_paths != expected_paths:
            fail(f"route materialization mismatch; missing={sorted(expected_paths-built_paths)}, extra={sorted(built_paths-expected_paths)}")
        if manifest.get("core_page_count") != len(core_paths):
            fail("manifest core page count drift")
        if manifest.get("service_page_count") != len(expected_service_paths):
            fail("manifest service page count drift")
        if manifest.get("publishable_service_count") != len(public_service_ids):
            fail("manifest publishable service count drift")
        if manifest.get("funding_projection_active") is not False:
            fail("E09 funding projection must not be represented as active during E08")

        all_html = []
        hrefs = []
        for page in manifest["pages"]:
            target = output / page["file"]
            if not target.is_file():
                fail(f"manifest references missing output file {page['file']}")
            text = target.read_text(encoding="utf-8")
            all_html.append(text)
            for marker in (
                '<meta name="robots" content="noindex,nofollow">',
                'data-eucons-phase="E08"',
                'data-build-state="DEVELOPMENT_NOINDEX"',
                'class="eu-skip-link"',
                '<header class="eu-header">',
                '<main id="main-content">',
                '<footer class="eu-footer">',
                '<link rel="canonical" href="https://eucons.ro',
            ):
                if marker not in text:
                    fail(f"{page['path']} missing required E08 marker {marker}")
            if re.search(r'<link\s+[^>]*rel="stylesheet"[^>]*href="https?://', text, flags=re.I):
                fail(f"{page['path']} uses external stylesheet")
            if "wp-content" in text.lower() or "wp-json" in text.lower() or "chatgpt-sites" in text.lower():
                fail(f"{page['path']} contains forbidden platform dependency")
            hrefs.extend(re.findall(r'<a\s+[^>]*href="([^"]+)"', text, flags=re.I))

        combined = "\n".join(all_html)
        known_internal = expected_paths
        for href in hrefs:
            if href.startswith("/") and href not in known_internal:
                fail(f"orphan internal link {href}")
            if href.startswith("http://") or href.startswith("https://"):
                fail(f"external navigation link forbidden in E08 core build: {href}")

        home = (output / "index.html").read_text(encoding="utf-8")
        for marker in (
            site["homepage"]["headline"],
            site["homepage"]["lead"],
            "Cere evaluarea proiectului",
            "Solicită ofertă",
            "Servicii pentru întregul ciclu al proiectului",
            "Pornește de la situația organizației tale",
        ):
            if marker not in home:
                fail(f"homepage missing visitor/commercial marker {marker}")

        service_by_id = {item["id"]: item for item in services.get("services", [])}
        for service_id in public_service_ids:
            service = service_by_id.get(service_id)
            route = service_route_by_id.get(service_id)
            if not service or not route:
                fail(f"publishable service {service_id} missing registry/route")
            page_file = output / route["path"].strip("/") / "index.html"
            page = page_file.read_text(encoding="utf-8")
            for marker in (service["label"], service["summary"], "Limite și condiții", "De ce avem nevoie pentru analiză"):
                if marker not in page:
                    fail(f"service page {service_id} missing {marker}")

        non_public_people = [item for item in people.get("people", []) if item.get("publication_state") != "PUBLISHABLE"]
        for person in non_public_people:
            for key in ("display_name", "public_headline", "public_bio"):
                value = person.get(key)
                if isinstance(value, str) and value.strip() and value in combined:
                    fail(f"non-public person leaked into E08 output: {person.get('id')}")

        non_public_cases = [item for item in cases.get("cases", []) if item.get("publication_state") != "PUBLISHABLE"]
        for case in non_public_cases:
            for key in ("title", "public_problem", "public_intervention"):
                value = case.get(key)
                if isinstance(value, str) and value.strip() and value in combined:
                    fail(f"non-public case leaked into E08 output: {case.get('id')}")

        evidence_by_id = {item.get("id"): item for item in evidence.get("evidence_items", []) if item.get("status") == "ACTIVE"}
        for claim in evidence.get("claims", []):
            if claim.get("publication_state") == "PUBLISHABLE":
                continue
            for key in ("public_statement", "value"):
                value = claim.get(key)
                if isinstance(value, str) and value.strip() and value in combined:
                    fail(f"non-public claim leaked into E08 output: {claim.get('id')}")
        if not evidence_by_id:
            fail("E08 cannot render without active E03 evidence items")

        if 'data-eucons-dry-run="true"' not in combined:
            fail("E08 lead journey structure must be explicitly dry-run")
        if 'type="submit" disabled aria-disabled="true"' not in combined:
            fail("E08 dry-run forms must not expose an active submit")

        return {
            "pages": manifest["page_count"],
            "core_pages": manifest["core_page_count"],
            "service_pages": manifest["service_page_count"],
            "publishable_services": manifest["publishable_service_count"],
            "publishable_people": manifest["publishable_people_count"],
            "publishable_cases": manifest["publishable_case_count"],
        }


def main() -> None:
    try:
        result = validate_public_site()
    except PublicSiteValidationError as exc:
        raise SystemExit(f"EUCONS E08 public site validation failed: {exc}")
    print(
        "EUCONS E08 public site valid: "
        f"{result['pages']} pages ({result['core_pages']} core + {result['service_pages']} service), "
        f"{result['publishable_services']} evidence-backed services; people={result['publishable_people']}, cases={result['publishable_cases']}"
    )


if __name__ == "__main__":
    main()
