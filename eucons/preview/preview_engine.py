#!/usr/bin/env python3
from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import importlib.util
import json
import re
import threading
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "preview" / "preview_contract.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load module {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def route_from_index(build_dir: Path, index_file: Path) -> str:
    rel = index_file.relative_to(build_dir)
    if rel.as_posix() == "index.html":
        return "/"
    parent = rel.parent.as_posix().strip("/")
    return f"/{parent}/"


def discover_routes(build_dir: Path) -> list[str]:
    routes = [route_from_index(build_dir, path) for path in sorted(build_dir.rglob("index.html"))]
    if len(routes) != len(set(routes)):
        raise ValueError("duplicate preview routes")
    return sorted(routes)


def route_file(build_dir: Path, route: str) -> Path:
    if route == "/":
        return build_dir / "index.html"
    return build_dir / route.strip("/") / "index.html"


def materialize_preview_support_files(build_dir: Path, contract: dict[str, Any]) -> list[str]:
    routes = discover_routes(build_dir)
    if len(routes) < int(contract["preview"]["minimum_route_count"]):
        raise ValueError("preview route count below canonical minimum")
    origin = str(contract["preview"]["canonical_origin"]).rstrip("/")
    sitemap_rows = "".join(f"<url><loc>{escape(origin + route)}</loc></url>" for route in routes)
    sitemap = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + sitemap_rows + "</urlset>\n"
    (build_dir / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    robots = f"User-agent: *\nDisallow: /\nSitemap: {origin}/sitemap.xml\n"
    (build_dir / "robots.txt").write_text(robots, encoding="utf-8")
    return routes


def _expected_canonical(origin: str, route: str) -> str:
    return origin.rstrip("/") + route


def validate_static_build(build_dir: Path, routes: list[str], contract: dict[str, Any]) -> dict[str, Any]:
    preview = contract["preview"]
    origin = str(preview["canonical_origin"]).rstrip("/")
    required_files = [build_dir / row for row in preview["required_files"]]
    missing = [str(path.relative_to(build_dir)) for path in required_files if not path.is_file()]
    if missing:
        raise ValueError(f"preview required files missing: {missing}")

    css = (build_dir / "assets" / "eucons.css").read_text(encoding="utf-8")
    if "@media" not in css:
        raise ValueError("responsive CSS media query missing")

    route_hashes: dict[str, str] = {}
    for route in routes:
        path = route_file(build_dir, route)
        if not path.is_file():
            raise ValueError(f"missing route file: {route}")
        text = path.read_text(encoding="utf-8")
        required_fragments = [
            '<html lang="ro">',
            '<meta name="viewport"',
            '<meta name="robots" content="noindex,nofollow">',
            'class="eu-skip-link"',
            '<main id="continut">',
            'aria-label="Navigație principală"',
            f'<link rel="canonical" href="{_expected_canonical(origin, route)}">',
        ]
        for fragment in required_fragments:
            if fragment not in text:
                raise ValueError(f"{route}: preview invariant missing: {fragment}")
        if re.search(r"<form\b", text, flags=re.IGNORECASE):
            raise ValueError(f"{route}: preview must not collect live form data")
        if "fonts.googleapis.com" in text or "http://fonts." in text or "https://fonts." in text:
            raise ValueError(f"{route}: remote font dependency forbidden")
        route_hashes[route] = digest_file(path)

    robots = (build_dir / "robots.txt").read_text(encoding="utf-8")
    if "Disallow: /" not in robots or f"Sitemap: {origin}/sitemap.xml" not in robots:
        raise ValueError("preview robots policy drift")

    tree = ET.fromstring((build_dir / "sitemap.xml").read_text(encoding="utf-8"))
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    sitemap_urls = sorted(node.text or "" for node in tree.findall("sm:url/sm:loc", namespace))
    expected_urls = sorted(_expected_canonical(origin, route) for route in routes)
    if sitemap_urls != expected_urls:
        raise ValueError("preview sitemap route/canonical mismatch")

    return {
        "route_count": len(routes),
        "route_hashes": route_hashes,
        "sitemap_sha256": digest_file(build_dir / "sitemap.xml"),
        "robots_sha256": digest_file(build_dir / "robots.txt"),
        "css_sha256": digest_file(build_dir / "assets" / "eucons.css"),
    }


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def local_http_smoke(build_dir: Path, routes: list[str]) -> dict[str, Any]:
    handler = functools.partial(QuietHandler, directory=str(build_dir))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    probed = list(routes) + ["/robots.txt", "/sitemap.xml", "/assets/eucons.css"]
    statuses: dict[str, int] = {}
    try:
        for path in probed:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
                statuses[path] = int(response.status)
                if response.status != 200:
                    raise ValueError(f"local preview HTTP probe failed for {path}: {response.status}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return {"probe_count": len(statuses), "all_http_200": all(value == 200 for value in statuses.values())}


def synthetic_match_bridge() -> dict[str, Any]:
    return {
        "bridge_state": "READY",
        "opportunities": [{
            "id": "E25-SYNTH-OPP-1",
            "title": "Investiții în energie solară pentru întreprindere agricolă",
            "programme": "Program sintetic E25",
            "code": "E25-SYNTH",
            "status": "OPEN",
            "commercial_state": "VERIFIED_AVAILABLE",
            "actionable": True,
            "verified_fact_classes": ["status", "deadline", "eligibility", "grant"],
            "material_facts": {
                "status": "OPEN",
                "deadline": {"closes_at": "2026-10-01T12:00:00+03:00"},
                "eligibility": {"activity_codes_at_application": ["CAEN 10"], "eligible_classes": ["întreprindere agricolă"]},
                "grant": {"maximum_eur": 1000000},
            },
            "provenance": {
                "source_product": "PARTENER.EU",
                "source_opportunity_id": "E25-SYNTH-OPP-1",
                "source_projection_sha256": "a" * 64,
                "verification_evidence": [{"id": "E25-SYNTH-EVIDENCE"}],
            },
        }],
    }


def synthetic_commercial_journey() -> dict[str, Any]:
    lead_engine = load_module("e25_lead", EUCONS / "leads" / "process_lead.py")
    matcher = load_module("e25_match", EUCONS / "opportunities" / "match_opportunities.py")
    crm = load_module("e25_crm", EUCONS / "crm" / "crm_engine.py")
    offers = load_module("e25_offer", EUCONS / "offers" / "offer_engine.py")

    lead_contract = load_json(EUCONS / "leads" / "lead_contract.json")
    forms = load_json(EUCONS / "leads" / "forms.json")
    matching_contract = load_json(EUCONS / "opportunities" / "matching_contract.json")
    crm_contract = load_json(EUCONS / "crm" / "crm_contract.json")
    offer_contract = load_json(EUCONS / "offers" / "offer_contract.json")
    service_registry = load_json(EUCONS / "services" / "service_registry.json")

    payload = {
        "form_id": "proposal_request",
        "submission_id": "SYNTH-E25-PREVIEW",
        "submitted_at": "2026-08-19T13:00:00Z",
        "submission_age_ms": 2500,
        "website": "",
        "privacy_ack": True,
        "marketing_consent": True,
        "contact_name": "Synthetic Preview Person",
        "email": "preview.e25@example.invalid",
        "organization_name": "Întreprindere agricolă sintetică",
        "audience_id": "companies_entrepreneurs",
        "organization_labels": ["întreprindere agricolă"],
        "activity_codes": ["CAEN 10"],
        "county": "Vâlcea",
        "region_terms": ["Vâlcea"],
        "investment_terms": ["energie", "solară"],
        "requested_grant_eur": 500000,
        "project_stage": "preparation",
        "timeline": "now_30_days",
        "message": "Synthetic E25 request used only for deterministic preview acceptance.",
    }
    initial_lead = lead_engine.process(payload, lead_contract, forms)
    bridge = synthetic_match_bridge()
    matching = matcher.match(initial_lead["matching_profile"], bridge, matching_contract)
    candidates = [row for row in matching["results"] if row["state"] == "MATCH_CANDIDATE"]
    if len(candidates) != 1:
        raise ValueError("E25 synthetic journey did not produce exactly one verified match candidate")
    lead_record = lead_engine.process(payload, lead_contract, forms, matching)
    if lead_record["scores"]["matching_candidate_count"] != 1:
        raise ValueError("E25 lead scoring did not bind E10 match candidate")

    fixed = "2026-08-19T13:00:00Z"
    state, lead_id = crm.ingest_lead(crm.empty_state(), lead_record, crm_contract, at=fixed)
    state = crm.transition(state, lead_id, "QUALIFIED", crm_contract, next_action="CREATE_OPPORTUNITY", at=fixed)
    state = crm.assign_owner(state, lead_id, "synthetic-commercial-owner", at=fixed)
    state, opportunity_id = crm.create_opportunity(state, lead_id, candidates[0], at=fixed)
    state = crm.transition(state, lead_id, "OPPORTUNITY", crm_contract, next_action="PREPARE_OFFER", at=fixed)
    offer = offers.compose_offer(
        crm_state=state,
        lead_id=lead_id,
        opportunity_id=opportunity_id,
        service_ids=["funding_strategy_and_eligibility"],
        assumptions=["Synthetic preview assumption; commercial validation remains required."],
        exclusions=["No funding approval guarantee is included."],
        service_registry=service_registry,
        contract=offer_contract,
    )
    if offer["pricing"]["state"] != "HUMAN_REQUIRED" or offer["pricing"]["amount_minor"] is not None:
        raise ValueError("E25 offer pricing failed open")
    if offer["automatic_send_allowed"] is not False:
        raise ValueError("E25 offer auto-send gate failed open")
    state, _offer_entity_id = crm.register_offer(state, lead_id, f"v{offer['version']}", f"synthetic://{offer['offer_id']}", at=fixed)
    state = crm.transition(state, lead_id, "OFFER", crm_contract, next_action="COMMERCIAL_APPROVAL", at=fixed)
    crm.assert_audit(state, crm_contract)

    return {
        "lead_record": lead_record,
        "match_record": candidates[0],
        "crm_state": state,
        "lead_id": lead_id,
        "opportunity_id": opportunity_id,
        "offer": offer,
        "summary": {
            "match_state": candidates[0]["state"],
            "match_score": candidates[0]["score"],
            "lead_score": lead_record["scores"]["lead_score"],
            "crm_stage": state["leads"][lead_id]["stage"],
            "offer_status": offer["status"],
            "pricing_state": offer["pricing"]["state"],
            "automatic_send_allowed": offer["automatic_send_allowed"],
            "lead_sha256": digest_json(lead_record),
            "match_sha256": digest_json(candidates[0]),
            "crm_sha256": digest_json(state),
            "offer_sha256": digest_json({key: value for key, value in offer.items() if key != "html"}),
        },
    }


def synthetic_editorial_projection() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "bridge_id": "PARTENER_P11_TO_EUCONS_E09",
        "bridge_state": "READY",
        "opportunities": [{
            "id": "E25-SYNTH-EDITORIAL-OPP",
            "title": "Oportunitate verificată sintetică",
            "programme": "Program sintetic E25",
            "status": "OPEN",
            "commercial_state": "VERIFIED_AVAILABLE",
            "actionable": True,
            "verified_fact_classes": ["status", "deadline"],
            "material_facts": {"status": "OPEN", "deadline": "2099-12-31"},
            "provenance": {
                "source_product": "PARTENER.EU",
                "source_opportunity_id": "E25-SYNTH-EDITORIAL-OPP",
                "source_projection_sha256": "b" * 64,
                "verification_evidence": [{"id": "E25-SYNTH-EDITORIAL-EVIDENCE"}],
            },
        }],
    }


def synthetic_distribution_journey(commercial: dict[str, Any]) -> dict[str, Any]:
    knowledge_engine = load_module("e25_knowledge", EUCONS / "knowledge" / "knowledge_engine.py")
    editorial_engine = load_module("e25_editorial", EUCONS / "editorial" / "editorial_loop.py")
    linkedin = load_module("e25_linkedin", EUCONS / "social" / "linkedin_adapter.py")
    facebook = load_module("e25_facebook", EUCONS / "social" / "facebook_adapter.py")
    email_engine = load_module("e25_email", EUCONS / "email" / "email_engine.py")

    knowledge = knowledge_engine.build_knowledge(
        load_json(EUCONS / "services" / "service_registry.json"),
        load_json(EUCONS / "evidence" / "evidence_registry.json"),
        synthetic_editorial_projection(),
        load_json(EUCONS / "cases" / "case_study_registry.json"),
        load_json(EUCONS / "knowledge" / "knowledge_contract.json"),
    )
    editorial = editorial_engine.build_cycle(knowledge, load_json(EUCONS / "editorial" / "editorial_loop_contract.json"))
    if editorial["runtime_publication_enabled"] is not False or editorial["dispatch_enabled"] is not False:
        raise ValueError("E25 editorial runtime gate failed open")
    if editorial["summary"]["ready"] < 1:
        raise ValueError("E25 editorial synthetic projection produced no READY content")

    li = linkedin.build_outbox(editorial, knowledge, load_json(EUCONS / "social" / "linkedin_contract.json"))
    fb = facebook.build_outbox(editorial, knowledge, load_json(EUCONS / "social" / "facebook_contract.json"))
    if li["direct_publication_enabled"] is not False or li["dry_run"] is not True:
        raise ValueError("E25 LinkedIn live publication gate failed open")
    if fb["direct_publication_enabled"] is not False or fb["dry_run"] is not True:
        raise ValueError("E25 Facebook live publication gate failed open")
    if not li["items"] or len(li["items"]) != len(fb["items"]):
        raise ValueError("E25 social outbox coverage mismatch")
    li_by_editorial = {row["editorial_id"]: row for row in li["items"]}
    fb_by_editorial = {row["editorial_id"]: row for row in fb["items"]}
    for editorial_id in sorted(set(li_by_editorial) & set(fb_by_editorial)):
        if li_by_editorial[editorial_id]["body"] == fb_by_editorial[editorial_id]["body"]:
            raise ValueError("E25 cross-platform verbatim reuse guard failed")

    lead_record = commercial["lead_record"]
    offer = commercial["offer"]
    request = {
        "product": "EUCONS_COMMERCIAL_OS",
        "message_type": "OFFER_EMAIL",
        "recipient": lead_record["lead"]["email"],
        "reference_id": "E25-SYNTH-OFFER-EMAIL",
        "context": {},
    }
    email = email_engine.build_email(request, lead_record, load_json(EUCONS / "email" / "email_contract.json"), offer=offer)
    if email["item"]["decision"] != "READY" or email["item"]["sent"] is not False:
        raise ValueError("E25 email dry-run offer handoff failed")
    if email["direct_sending_enabled"] is not False or email["dry_run"] is not True:
        raise ValueError("E25 email live-send gate failed open")
    serialized = json.dumps(email, ensure_ascii=False)
    if lead_record["lead"]["email"] in serialized:
        raise ValueError("E25 email dry-run leaked raw recipient")

    return {
        "editorial_ready": editorial["summary"]["ready"],
        "editorial_held": editorial["summary"]["held"],
        "linkedin_items": len(li["items"]),
        "facebook_items": len(fb["items"]),
        "email_decision": email["item"]["decision"],
        "email_dispatch_state": email["item"]["dispatch_state"],
        "linkedin_sha256": digest_json(li),
        "facebook_sha256": digest_json(fb),
        "email_sha256": digest_json(email),
        "editorial_sha256": digest_json(editorial),
    }


def build_preview_receipt(build_dir: Path, contract: dict[str, Any]) -> dict[str, Any]:
    if contract.get("engine_id") != "EUCONS_E25_PREVIEW_PRODUCTION":
        raise ValueError("E25 preview engine id drift")
    if contract.get("production_deployment_enabled") is not False:
        raise ValueError("E25 cannot enable production deployment")
    if contract.get("external_credentials_required") is not False:
        raise ValueError("E25 preview cannot require external credentials")
    if not all(contract.get("forbidden", {}).values()):
        raise ValueError("E25 forbidden-state contract incomplete")

    routes = materialize_preview_support_files(build_dir, contract)
    static = validate_static_build(build_dir, routes, contract)
    http = local_http_smoke(build_dir, routes)
    commercial = synthetic_commercial_journey()
    distribution = synthetic_distribution_journey(commercial)

    body = {
        "schema_version": 1,
        "product": "EUCONS_COMMERCIAL_OS",
        "engine_id": contract["engine_id"],
        "hosting_mode": contract["hosting_mode"],
        "production_deployment_enabled": False,
        "external_credentials_used": False,
        "static": static,
        "http": http,
        "commercial": commercial["summary"],
        "distribution": distribution,
    }
    body["commercial_journey_sha256"] = digest_json(commercial["summary"])
    body["distribution_journey_sha256"] = digest_json(distribution)
    body["receipt_hash"] = digest_json(body)
    return body


def assert_output_path_safe(path: Path) -> None:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return
    raise ValueError("E25 runtime preview receipt cannot be written under repository root")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", required=True)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    receipt = build_preview_receipt(Path(args.build_dir), load_json(Path(args.contract)))
    payload = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        assert_output_path_safe(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
