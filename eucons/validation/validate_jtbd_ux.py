#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
DEFAULT_CONTRACT = WEB / "jtbd_ux_contract.json"
IA_PATH = WEB / "information_architecture.json"
DEMAND_PATH = ROOT / "market_intelligence" / "EUCONS_CUSTOMER_DEMAND_MODEL_2026-08-25.json"
SERVICES_PATH = ROOT / "services" / "service_registry.json"
CANON_PATH = ROOT / "canon" / "commercial_canon.json"
PROOF_PATH = ROOT / "evidence" / "service_proof_architecture.json"

EXPECTED_JOURNEYS = {
    "JRN-FUNDING-FIT",
    "JRN-PROJECT-REVIEW",
    "JRN-IMPLEMENTATION",
    "JRN-RECOVERY",
}
REQUIRED_FIRST_FIELDS = {"organization_name", "audience_id"}
REQUIRED_TRUE_RULES = {
    "start_from_job_not_organization",
    "proof_must_overlap_journey_service",
    "progressive_data_minimization",
    "inferred_eligibility_forbidden",
    "fake_urgency_forbidden",
    "unavailable_submission_state_must_be_explicit",
}


class ValidationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_builder():
    path = WEB / "build_public_site.py"
    spec = importlib.util.spec_from_file_location("eucons_build_public_site_r04", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def nonempty_strings(value, label):
    require(isinstance(value, list) and value, f"{label} must be a non-empty list")
    require(all(isinstance(item, str) and item.strip() for item in value), f"{label} contains an invalid value")


def validate(contract_path=DEFAULT_CONTRACT):
    contract = load_json(contract_path)
    ia = load_json(IA_PATH)
    demand = load_json(DEMAND_PATH)
    services = load_json(SERVICES_PATH)
    canon = load_json(CANON_PATH)
    proof = load_json(PROOF_PATH)

    require(contract.get("product") == "EUCONS_COMMERCIAL_OS", "wrong product identifier")
    require(contract.get("id") == "R04-JTBD-UX-001", "wrong contract id")
    require(contract.get("phase") == "R04_JOB_TO_BE_DONE_UX", "wrong phase")
    require(contract.get("status") == "CANONICAL", "status must be CANONICAL")

    rules = contract.get("global_rules") or {}
    for rule in REQUIRED_TRUE_RULES:
        require(rules.get(rule) is True, f"global rule {rule} must remain true")
    require(rules.get("primary_choice_count") == 4, "homepage must expose exactly four primary choices")
    require(rules.get("primary_language") == "ro", "primary language must be Romanian")

    journeys = contract.get("journeys") or []
    require(len(journeys) == 4, "exactly four priority journeys are required")
    journey_ids = [item.get("id") for item in journeys]
    require(set(journey_ids) == EXPECTED_JOURNEYS and len(journey_ids) == len(set(journey_ids)), "priority journey IDs drifted")
    paths = [item.get("path") for item in journeys]
    route_ids = [item.get("route_id") for item in journeys]
    require(len(paths) == len(set(paths)), "journey paths must be unique")
    require(len(route_ids) == len(set(route_ids)), "journey route IDs must be unique")

    ia_journeys = {
        item.get("journey_id"): item
        for item in ia.get("core_routes", [])
        if item.get("surface") == "JTBD_JOURNEY"
    }
    require(set(ia_journeys) == EXPECTED_JOURNEYS, "information architecture journey set drifted")

    jobs = {item["id"]: item for item in demand.get("demand_matrix", [])}
    service_ids = {item["id"] for item in services.get("services", [])}
    cta_ids = {item["id"] for item in canon.get("ctas", [])}
    proof_objects = proof.get("historical_proof_objects", [])

    builder = load_builder()
    render_data = builder.load_contracts()
    render_data["ux"] = contract

    for journey in journeys:
        jid = journey["id"]
        route = ia_journeys[jid]
        require(route.get("id") == journey.get("route_id"), f"{jid} route_id does not match IA")
        require(route.get("path") == journey.get("path"), f"{jid} path does not match IA")
        require(isinstance(journey.get("path"), str) and journey["path"].startswith("/") and journey["path"].endswith("/"), f"{jid} path is not canonical")

        for field in ("question", "headline", "lead", "cta_label", "boundary", "secondary_path", "secondary_label"):
            require(isinstance(journey.get(field), str) and journey[field].strip(), f"{jid} missing {field}")

        nonempty_strings(journey.get("job_ids"), f"{jid}.job_ids")
        nonempty_strings(journey.get("service_ids"), f"{jid}.service_ids")
        nonempty_strings(journey.get("first_step_fields"), f"{jid}.first_step_fields")
        nonempty_strings(journey.get("later_fields"), f"{jid}.later_fields")
        require(set(journey["job_ids"]).issubset(jobs), f"{jid} references an unknown demand job")
        require(set(journey["service_ids"]).issubset(service_ids), f"{jid} references an unknown service")
        demand_services = {
            service_id
            for job_id in journey["job_ids"]
            for service_id in jobs[job_id].get("service_ids", [])
        }
        require(set(journey["service_ids"]).issubset(demand_services), f"{jid} contains a service unsupported by its demand jobs")
        require(REQUIRED_FIRST_FIELDS.issubset(journey["first_step_fields"]), f"{jid} first step must identify organization and audience")
        require(set(journey["first_step_fields"]).isdisjoint(journey["later_fields"]), f"{jid} repeats fields across progressive steps")
        require(len(journey.get("steps") or []) == 4, f"{jid} must expose exactly four decision steps")
        require(all(isinstance(step, str) and step.strip() for step in journey["steps"]), f"{jid} contains an empty step")
        require(journey.get("cta_id") in cta_ids, f"{jid} references an unknown CTA")
        lower_boundary = journey["boundary"].lower()
        require(any(marker in lower_boundary for marker in ("nu ", "depinde", "înlocuiește")), f"{jid} boundary must state a real limitation")
        require("este garantată" not in lower_boundary and "eligibilitate garantată" not in lower_boundary, f"{jid} boundary makes a guarantee")

        selected_proof = builder.publishable_proof_for_services(render_data, journey["service_ids"])
        for item in selected_proof:
            require(
                set(item.get("service_ids", [])).intersection(journey["service_ids"]),
                f"{jid} projects unrelated proof {item.get('id')}",
            )
            require(item.get("publication_state") == "PUBLISHABLE", f"{jid} projects non-public proof")

        rendered = builder.render_journey_page(render_data, journey)
        require(rendered.count("<h1") == 1, f"{jid} must render exactly one H1")
        require("<ol" in rendered and rendered.count("<li>") >= 4, f"{jid} must render semantic ordered steps")
        require(journey["cta_label"] in rendered, f"{jid} CTA label is not rendered")
        require(journey["boundary"] in rendered, f"{jid} boundary is not rendered")
        require("<form" not in rendered.lower(), f"{jid} must not collect data before R05 runtime")

    home = contract.get("homepage_contract") or {}
    require(home.get("primary_journey_ids") == [item["id"] for item in journeys], "homepage journey order drifted")
    require(home.get("service_catalog_role") == "SECONDARY_DISCOVERY", "service catalogue must remain secondary")
    require(isinstance(home.get("proof_section_title"), str) and home["proof_section_title"].strip(), "homepage proof title is missing")

    accessibility = contract.get("accessibility_acceptance") or {}
    for flag in ("single_h1_per_page", "semantic_ordered_steps", "skip_link_required", "mobile_single_column_actions", "no_color_only_meaning", "reduced_motion_supported"):
        require(accessibility.get(flag) is True, f"accessibility rule {flag} must remain true")
    require(accessibility.get("minimum_touch_target_px", 0) >= 44, "touch target must be at least 44px")

    with tempfile.TemporaryDirectory() as td:
        pages = builder.build_site(Path(td) / "site")
        for journey in journeys:
            require(journey["path"] in pages, f"{journey['id']} was not materialized")

    return {
        "status": "PASS",
        "phase": "R04",
        "journeys": len(journeys),
        "jobs_referenced": len({job for item in journeys for job in item["job_ids"]}),
        "services_referenced": len({service for item in journeys for service in item["service_ids"]}),
        "proof_policy": "RELEVANT_PUBLISHABLE_ONLY",
        "data_collection": "DISABLED_UNTIL_R05",
    }


def main():
    print(json.dumps(validate(), ensure_ascii=False))


if __name__ == "__main__":
    main()
