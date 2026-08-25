#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCH_PATH = ROOT / "evidence" / "service_proof_architecture.json"
PORTFOLIO_PATH = ROOT / "evidence" / "portfolio_candidate_registry.json"
SERVICE_PATH = ROOT / "services" / "service_registry.json"
EVIDENCE_PATH = ROOT / "evidence" / "evidence_registry.json"
CASE_PATH = ROOT / "cases" / "case_study_registry.json"
DEMAND_PATH = ROOT / "market_intelligence" / "EUCONS_CUSTOMER_DEMAND_MODEL_2026-08-25.json"

ALLOWED_CLASSIFICATIONS = {
    "PUBLIC_VERIFIED",
    "INTERNAL_VERIFIED_NONPUBLIC",
    "NEEDS_EVIDENCE",
    "CONFIDENTIAL",
    "HOLD",
}
OWNER_PORTFOLIO_ORGS = {
    "PORT-ORG-EUROCONS",
    "PORT-ORG-CCI-VALCEA",
    "PORT-ORG-FAS",
    "PORT-ORG-FCPP-VALCEA",
}


class ValidationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def unique_ids(items, label):
    ids = []
    for item in items:
        require(isinstance(item, dict), f"{label} contains a non-object")
        item_id = item.get("id")
        require(isinstance(item_id, str) and item_id, f"{label} contains missing/invalid id")
        ids.append(item_id)
    require(len(ids) == len(set(ids)), f"{label} contains duplicate ids")
    return set(ids)


def validate(architecture_path=ARCH_PATH, portfolio_path=PORTFOLIO_PATH):
    architecture = load_json(architecture_path)
    portfolio = load_json(portfolio_path)
    services = load_json(SERVICE_PATH)
    evidence = load_json(EVIDENCE_PATH)
    cases = load_json(CASE_PATH)
    demand = load_json(DEMAND_PATH)

    service_ids = {item["id"] for item in services["services"]}
    claims = {item["id"]: item for item in evidence["claims"]}
    case_items = {item["id"]: item for item in cases["cases"]}
    jobs = {item["id"]: item for item in demand["demand_matrix"]}

    require(architecture.get("id") == "R03-SEA-001", "wrong service-proof architecture id")
    require(architecture.get("product") == "EUCONS_COMMERCIAL_OS", "wrong architecture product")
    require(architecture.get("status") == "CANONICAL", "architecture must be CANONICAL")

    policy = architecture.get("proof_policy") or {}
    for key in ("offering_proof", "historical_proof", "gap_rule", "job_relevance_rule", "publication_rule"):
        require(str(policy.get(key, "")).strip(), f"proof_policy missing {key}")

    coverage = architecture.get("service_coverage") or []
    coverage_ids = unique_ids(
        [{"id": item.get("service_id")} for item in coverage],
        "service_coverage",
    )
    require(coverage_ids == service_ids, f"service coverage mismatch: {sorted(service_ids ^ coverage_ids)}")

    proof_objects = architecture.get("historical_proof_objects") or []
    proof_ids = unique_ids(proof_objects, "historical_proof_objects")
    proof_by_id = {item["id"]: item for item in proof_objects}

    for proof in proof_objects:
        require(proof.get("publication_state") == "PUBLISHABLE", f"{proof['id']} is not publishable")
        case_id = proof.get("case_id")
        require(case_id in case_items, f"{proof['id']} references unknown case")
        case = case_items[case_id]
        require(case.get("publication_state") == "PUBLISHABLE", f"{proof['id']} case is not publishable")
        proof_services = set(proof.get("service_ids") or [])
        require(proof_services and proof_services <= service_ids, f"{proof['id']} has unknown services")
        require(proof_services <= set(case.get("service_ids") or []), f"{proof['id']} exceeds case service scope")
        result_claim_ids = proof.get("result_claim_ids") or []
        require(result_claim_ids, f"{proof['id']} has no result claims")
        require(set(result_claim_ids) <= set(case.get("result_claim_ids") or []), f"{proof['id']} result claims exceed case")
        for claim_id in result_claim_ids:
            claim = claims.get(claim_id)
            require(claim is not None, f"{proof['id']} unknown result claim {claim_id}")
            require(claim.get("claim_class") == "PROJECT_RESULT", f"{claim_id} is not PROJECT_RESULT")
            require(claim.get("publication_state") == "PUBLISHABLE", f"{claim_id} is not publishable")
        for job_id in proof.get("supported_job_ids") or []:
            require(job_id in jobs, f"{proof['id']} references unknown job {job_id}")
            require(proof_services & set(jobs[job_id].get("service_ids") or []), f"{proof['id']} irrelevant to {job_id}")
        require(proof.get("boundaries"), f"{proof['id']} missing boundaries")

    for item in coverage:
        service_id = item["service_id"]
        claim_id = item.get("offering_claim_id")
        claim = claims.get(claim_id)
        require(claim is not None, f"{service_id} missing offering claim")
        require(claim.get("claim_class") == "SERVICE_OFFERING", f"{claim_id} is not SERVICE_OFFERING")
        require(claim.get("publication_state") == "PUBLISHABLE", f"{claim_id} is not publishable")
        require(claim.get("object_ref") == service_id, f"{claim_id} does not prove {service_id}")

        mapped_jobs = item.get("demand_job_ids") or []
        require(mapped_jobs, f"{service_id} has no demand jobs")
        for job_id in mapped_jobs:
            require(job_id in jobs, f"{service_id} references unknown job {job_id}")
            require(service_id in jobs[job_id].get("service_ids", []), f"{service_id} not mapped by {job_id}")

        history_ids = item.get("historical_proof_object_ids") or []
        require(set(history_ids) <= proof_ids, f"{service_id} references unknown proof object")
        for proof_id in history_ids:
            require(service_id in proof_by_id[proof_id]["service_ids"], f"{proof_id} does not support {service_id}")

        state = item.get("proof_state")
        if state == "OFFERING_AND_HISTORICAL_PROOF_PUBLISHABLE":
            require(history_ids, f"{service_id} claims history without proof")
        elif state == "OFFERING_VERIFIED_HISTORICAL_PROOF_GAP":
            require(not history_ids, f"{service_id} marks gap but contains history")
        else:
            raise ValidationError(f"{service_id} invalid proof state")
        require(str(item.get("gap_action", "")).strip(), f"{service_id} missing gap action")

    summary = architecture.get("proof_gap_summary") or {}
    with_history = sum(1 for item in coverage if item["historical_proof_object_ids"])
    without_history = len(coverage) - with_history
    require(summary.get("services_with_public_historical_proof") == with_history, "historical proof count drifted")
    require(summary.get("services_with_only_offering_proof") == without_history, "proof gap count drifted")
    require(set(summary.get("priority_gap_order") or []) <= service_ids, "priority gaps reference unknown services")

    decision = architecture.get("decision") or {}
    require(decision.get("state") == "PASS", "architecture decision must PASS")
    require((decision.get("next_unit") or {}).get("id") == "R04-JTBD-UX-001", "wrong next unit")

    require(portfolio.get("id") == "R03-SEA-001-PORTFOLIO", "wrong portfolio id")
    require(portfolio.get("product") == "EUCONS_COMMERCIAL_OS", "wrong portfolio product")
    require(portfolio.get("status") == "CANONICAL", "portfolio must be CANONICAL")
    contract = portfolio.get("classification_contract") or {}
    require(set(contract.get("allowed") or []) == ALLOWED_CLASSIFICATIONS, "classification contract drifted")
    for key in ("public_rule", "relationship_rule", "project_rule", "confidentiality_rule"):
        require(str(contract.get(key, "")).strip(), f"classification_contract missing {key}")

    organizations = portfolio.get("organization_candidates") or []
    organization_ids = unique_ids(organizations, "organization_candidates")
    require(organization_ids == OWNER_PORTFOLIO_ORGS, "owner-designated organization inventory is incomplete")
    organization_by_id = {item["id"]: item for item in organizations}

    for organization in organizations:
        classification = organization.get("classification")
        require(classification in ALLOWED_CLASSIFICATIONS, f"{organization['id']} invalid classification")
        if organization.get("publication_allowed") is True:
            require(classification == "PUBLIC_VERIFIED", f"{organization['id']} public without PUBLIC_VERIFIED")
            require(organization.get("evidence_ids"), f"{organization['id']} public without evidence")
            require(organization.get("claim_ids"), f"{organization['id']} public without claims")
            for claim_id in organization["claim_ids"]:
                require(claim_id in claims and claims[claim_id].get("publication_state") == "PUBLISHABLE", f"{organization['id']} has non-publishable claim")
        else:
            require(classification != "PUBLIC_VERIFIED", f"{organization['id']} verified but not public")
            require(organization.get("relationship_to_euroconsult") is None, f"{organization['id']} asserts unverified relationship")
            require(organization.get("required_next_evidence"), f"{organization['id']} missing evidence plan")

    projects = portfolio.get("project_candidates") or []
    project_ids = unique_ids(projects, "project_candidates")
    for project in projects:
        require(set(project.get("organization_candidate_ids") or []) <= organization_ids, f"{project['id']} unknown organization")
        classification = project.get("classification")
        require(classification in ALLOWED_CLASSIFICATIONS, f"{project['id']} invalid classification")
        if project.get("publication_allowed") is True:
            require(classification == "PUBLIC_VERIFIED", f"{project['id']} public without verification")
            case_id = project.get("case_id")
            require(case_id in case_items and case_items[case_id].get("publication_state") == "PUBLISHABLE", f"{project['id']} lacks public case")
            require(project.get("euroconsult_role") == "PARTNER_AS_DOCUMENTED", f"{project['id']} role is not bounded")
            for claim_id in project.get("result_claim_ids") or []:
                require(claim_id in claims and claims[claim_id].get("publication_state") == "PUBLISHABLE", f"{project['id']} result not publishable")
        else:
            require(classification != "PUBLIC_VERIFIED", f"{project['id']} verified but not public")
            require(project.get("euroconsult_role") is None, f"{project['id']} asserts unverified role")
            require(not project.get("result_claim_ids"), f"{project['id']} has unsupported results")
            require(not project.get("service_ids"), f"{project['id']} has unsupported service mapping")
            require(str(project.get("required_action", "")).strip(), f"{project['id']} missing required action")

    public_projection = set(portfolio.get("public_projection") or [])
    hold_projection = set(portfolio.get("hold_projection") or [])
    all_candidate_ids = organization_ids | project_ids
    require(public_projection | hold_projection == all_candidate_ids, "projection inventory incomplete")
    require(not (public_projection & hold_projection), "public and hold projections overlap")
    for candidate_id in public_projection:
        candidate = organization_by_id.get(candidate_id) or next((p for p in projects if p["id"] == candidate_id), None)
        require(candidate and candidate.get("publication_allowed") is True, f"{candidate_id} improperly public")
    for candidate_id in hold_projection:
        candidate = organization_by_id.get(candidate_id) or next((p for p in projects if p["id"] == candidate_id), None)
        require(candidate and candidate.get("publication_allowed") is False, f"{candidate_id} improperly held")

    return {
        "services": len(coverage),
        "proof_objects": len(proof_objects),
        "organizations": len(organizations),
        "projects": len(projects),
        "proof_gaps": without_history,
    }


def main():
    architecture_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ARCH_PATH
    portfolio_path = Path(sys.argv[2]) if len(sys.argv) > 2 else PORTFOLIO_PATH
    try:
        counts = validate(architecture_path, portfolio_path)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise SystemExit(f"EUCONS R03 service/proof validation failed: {exc}")
    print(
        "EUCONS R03 service/proof architecture valid: "
        f"{counts['services']} services, {counts['proof_objects']} public historical proof objects, "
        f"{counts['organizations']} organizations, {counts['projects']} project candidates, "
        f"{counts['proof_gaps']} explicit service proof gaps"
    )


if __name__ == "__main__":
    main()
