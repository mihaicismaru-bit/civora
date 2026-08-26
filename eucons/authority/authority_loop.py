#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "authority" / "authority_loop_contract.json"


class AuthorityError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def authority_id(job_id: str) -> str:
    return "AUTH-" + hashlib.sha256(job_id.encode("utf-8")).hexdigest()[:24]


def slugify(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    return slug[:72] or "ghid"


def unique_index(rows: list[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = str(row.get(key) or "").strip()
        if not value or value in result:
            raise AuthorityError(f"duplicate or missing {label}")
        result[value] = row
    return result


def validate_inputs(
    demand: dict[str, Any],
    ux: dict[str, Any],
    services: dict[str, Any],
    evidence: dict[str, Any],
    proof: dict[str, Any],
    canon: dict[str, Any],
    knowledge: dict[str, Any],
    editorial: dict[str, Any],
    seo: dict[str, Any],
    analytics_contract: dict[str, Any],
    ia: dict[str, Any],
    contract: dict[str, Any],
) -> None:
    required_product = contract["input"]["required_product"]
    product_inputs = [demand, ux, services, proof, canon, knowledge, editorial, seo]
    if any(row.get("product") != required_product for row in product_inputs):
        raise AuthorityError("unknown product input")
    if demand.get("id") != contract["input"]["required_demand_model_id"]:
        raise AuthorityError("unknown demand model")
    if ux.get("id") != contract["input"]["required_jtbd_ux_id"]:
        raise AuthorityError("unknown JTBD UX contract")
    if proof.get("id") != contract["input"]["required_service_proof_id"]:
        raise AuthorityError("unknown service proof architecture")
    if knowledge.get("engine_id") != contract["input"]["required_knowledge_engine"]:
        raise AuthorityError("unknown knowledge engine")
    if editorial.get("engine_id") != contract["input"]["required_editorial_engine"]:
        raise AuthorityError("unknown editorial engine")
    if seo.get("engine_id") != contract["input"]["required_seo_engine"]:
        raise AuthorityError("unknown SEO engine")
    if knowledge.get("runtime_publication_enabled") is not False:
        raise AuthorityError("knowledge runtime publication must remain disabled")
    if editorial.get("runtime_publication_enabled") is not False or editorial.get("dispatch_enabled") is not False:
        raise AuthorityError("editorial dispatch must remain disabled")
    if any(row.get("published") is not False for row in editorial.get("decisions") or []):
        raise AuthorityError("authority input contains a published editorial record")
    if seo.get("production_indexing_enabled") is not False:
        raise AuthorityError("production indexing must remain disabled")
    for event in contract["conversion"]["required_measurement_events"]:
        if event not in (analytics_contract.get("events") or {}):
            raise AuthorityError(f"missing analytics event: {event}")
    family_id = contract["selection"]["conditional_route_family"]
    families = {row.get("id"): row for row in ia.get("conditional_route_families") or []}
    if family_id not in families:
        raise AuthorityError("missing guide conditional route family")


def select_journey(job: dict[str, Any], journeys: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    wanted = set(job.get("service_ids") or [])
    for index, journey in enumerate(journeys):
        if job.get("id") not in (journey.get("job_ids") or []):
            continue
        overlap = len(wanted.intersection(journey.get("service_ids") or []))
        candidates.append((-overlap, index, journey))
    if not candidates:
        return None
    return sorted(candidates, key=lambda row: (row[0], row[1], str(row[2].get("id") or "")))[0][2]


def service_claim_lineage(
    service_ids: list[str], evidence: dict[str, Any], contract: dict[str, Any]
) -> tuple[list[str], list[str], list[str]]:
    policy = contract["truth_and_proof"]
    items = unique_index(list(evidence.get("evidence_items") or []), "id", "evidence item id")
    claims = list(evidence.get("claims") or [])
    claim_ids: list[str] = []
    evidence_ids: list[str] = []
    missing: list[str] = []
    for service_id in service_ids:
        claim = next(
            (
                row
                for row in claims
                if row.get("object_ref") == service_id
                and row.get("claim_class") == policy["required_offering_claim_class"]
                and row.get("publication_state") == policy["required_offering_claim_state"]
            ),
            None,
        )
        if not claim:
            missing.append(service_id)
            continue
        valid_evidence = []
        for evidence_id in claim.get("evidence_ids") or []:
            item = items.get(str(evidence_id))
            if item and item.get("status") == policy["required_evidence_state"]:
                valid_evidence.append(str(evidence_id))
        if not valid_evidence:
            missing.append(service_id)
            continue
        claim_ids.append(str(claim["id"]))
        evidence_ids.extend(valid_evidence)
    return sorted(set(claim_ids)), sorted(set(evidence_ids)), sorted(set(missing))


def build_authority_plan(
    demand: dict[str, Any],
    ux: dict[str, Any],
    services: dict[str, Any],
    evidence: dict[str, Any],
    proof: dict[str, Any],
    canon: dict[str, Any],
    knowledge: dict[str, Any],
    editorial: dict[str, Any],
    seo: dict[str, Any],
    analytics_contract: dict[str, Any],
    ia: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    validate_inputs(
        demand, ux, services, evidence, proof, canon, knowledge, editorial, seo,
        analytics_contract, ia, contract,
    )
    jobs = unique_index(list(demand.get("demand_matrix") or []), "id", "demand job id")
    service_rows = unique_index(list(services.get("services") or []), "id", "service id")
    knowledge_rows = unique_index(list(knowledge.get("records") or []), "id", "knowledge record id")
    journeys = list(ux.get("journeys") or [])
    journey_rows = unique_index(journeys, "id", "journey id")
    proof_coverage = unique_index(list(proof.get("service_coverage") or []), "service_id", "proof service id")
    proof_objects = unique_index(list(proof.get("historical_proof_objects") or []), "id", "proof object id")
    ctas = unique_index(list(canon.get("ctas") or []), "id", "CTA id")
    seo_routes = unique_index(list(seo.get("routes") or []), "path", "SEO route path")
    core_routes = unique_index(list(ia.get("core_routes") or []), "id", "core route id")
    priority_order = {value: index for index, value in enumerate(contract["selection"]["priority_order"])}
    allowed_types = set(contract["input"]["allowed_knowledge_types"])
    ready_state = contract["input"]["editorial_ready_state"]
    editorial_ready: dict[str, list[dict[str, Any]]] = {}

    for decision in editorial.get("decisions") or []:
        knowledge_id = str(decision.get("knowledge_id") or "")
        source_ref = str(decision.get("source_ref") or "")
        knowledge_row = knowledge_rows.get(knowledge_id)
        if not knowledge_row:
            raise AuthorityError("editorial decision references unknown knowledge record")
        if knowledge_row.get("source_ref") != source_ref or knowledge_row.get("type") != decision.get("type"):
            raise AuthorityError("editorial and knowledge lineage mismatch")
        if decision.get("decision") == ready_state and decision.get("type") in allowed_types:
            editorial_ready.setdefault(source_ref, []).append(decision)

    cta_route_id = contract["conversion"]["required_cta_route_id"]
    cta_route = core_routes.get(cta_route_id)
    if not cta_route or cta_route.get("path") not in seo_routes:
        raise AuthorityError("CTA route is not active in SEO projection")

    candidates: list[dict[str, Any]] = []
    for job in jobs.values():
        job_id = str(job["id"])
        service_ids = [str(value) for value in job.get("service_ids") or []]
        if not service_ids or any(service_id not in service_rows for service_id in service_ids):
            raise AuthorityError(f"demand job references missing service: {job_id}")
        for service_id in service_ids:
            coverage = proof_coverage.get(service_id)
            if not coverage or job_id not in (coverage.get("demand_job_ids") or []):
                raise AuthorityError(f"service-proof demand mapping missing: {job_id}|{service_id}")

        journey = select_journey(job, journeys)
        hold_reasons: list[str] = []
        if journey is None:
            hold_reasons.append("NO_JOURNEY_ROUTE")
            journey_id = None
            journey_path = None
            cta_id = None
            content_family = "UNASSIGNED"
        else:
            journey_id = str(journey["id"])
            if journey_id not in journey_rows:
                raise AuthorityError("selected journey missing from index")
            journey_path = str(journey.get("path") or "")
            cta_id = str(journey.get("cta_id") or "")
            content_family = contract["selection"]["content_family_by_journey"].get(journey_id)
            if not content_family:
                raise AuthorityError(f"missing content family for journey: {journey_id}")
            if journey_path not in seo_routes:
                hold_reasons.append("JOURNEY_NOT_ACTIVE_IN_SEO")
            if cta_id not in ctas or cta_id not in contract["conversion"]["allowed_cta_ids"]:
                hold_reasons.append("CTA_NOT_CANONICAL")
            if not set(service_ids).intersection(journey.get("service_ids") or []):
                hold_reasons.append("JOURNEY_SERVICE_MISMATCH")

        claim_ids, evidence_ids, missing_evidence_services = service_claim_lineage(service_ids, evidence, contract)
        if missing_evidence_services:
            hold_reasons.append("SERVICE_OFFERING_EVIDENCE_MISSING")

        editorial_rows = sorted(
            [row for service_id in service_ids for row in editorial_ready.get(service_id, [])],
            key=lambda row: (str(row.get("type") or ""), str(row.get("editorial_id") or "")),
        )
        if not editorial_rows:
            hold_reasons.append("NO_READY_EDITORIAL_LINEAGE")

        relevant_proof = []
        for proof_object in proof_objects.values():
            if proof_object.get("publication_state") != contract["truth_and_proof"]["historical_proof_state"]:
                continue
            if job_id not in (proof_object.get("supported_job_ids") or []):
                continue
            if not set(service_ids).intersection(proof_object.get("service_ids") or []):
                continue
            relevant_proof.append(str(proof_object["id"]))

        primary_intent = str((job.get("search_intents") or [job_id])[0])
        planned_slug = f"{slugify(primary_intent)}-{job_id.lower()}"
        planned_path = f"{contract['selection']['planned_route_prefix']}{planned_slug}/"
        if hold_reasons:
            if any(reason in {"NO_JOURNEY_ROUTE", "JOURNEY_NOT_ACTIVE_IN_SEO", "CTA_NOT_CANONICAL", "JOURNEY_SERVICE_MISMATCH"} for reason in hold_reasons):
                state = contract["states"]["hold_route"]
            elif "SERVICE_OFFERING_EVIDENCE_MISSING" in hold_reasons:
                state = contract["states"]["hold_evidence"]
            else:
                state = contract["states"]["hold_editorial"]
        else:
            state = contract["states"]["ready"]

        candidates.append({
            "authority_id": authority_id(job_id),
            "job_id": job_id,
            "segment_id": job.get("segment_id"),
            "priority": job.get("priority"),
            "moment": job.get("moment"),
            "buyer_question": job.get("job"),
            "search_intents": list(job.get("search_intents") or []),
            "content_family": content_family,
            "draft_title": primary_intent[:1].upper() + primary_intent[1:],
            "journey_id": journey_id,
            "journey_path": journey_path,
            "service_ids": service_ids,
            "cta": {
                "cta_id": cta_id,
                "path": cta_route["path"],
                "label": ctas.get(cta_id, {}).get("label") if cta_id else None,
            },
            "planned_route": {
                "path": planned_path,
                "state": "CONDITIONAL_HOLD_UNTIL_MATERIALIZED",
                "indexable": False,
                "canonical": None,
            },
            "draft_scope": {
                "outline": [
                    "Decizia pe care trebuie să o ia organizația",
                    "Informațiile și documentele care trebuie confirmate",
                    "Separarea faptelor de interpretări și necunoscute",
                    "Serviciile Euroconsult relevante și limitele lor",
                    "Următorul pas verificabil"
                ],
                "required_inputs": list(job.get("evidence_needed") or []),
                "recommended_next_action": job.get("recommended_next_action"),
                "material_funding_fact_gate": contract["truth_and_proof"]["material_funding_fact_source"],
                "eligibility_state": "NOT_ASSESSED"
            },
            "lineage": {
                "knowledge_ids": sorted({str(row["knowledge_id"]) for row in editorial_rows}),
                "editorial_ids": sorted({str(row["editorial_id"]) for row in editorial_rows}),
                "editorial_receipt_ids": sorted({
                    str(receipt.get("receipt_id"))
                    for receipt in editorial.get("receipts") or []
                    if receipt.get("knowledge_id") in {row.get("knowledge_id") for row in editorial_rows}
                }),
                "service_claim_ids": claim_ids,
                "evidence_ids": evidence_ids,
                "historical_proof_object_ids": sorted(relevant_proof),
                "seo_journey_canonical": seo_routes.get(journey_path, {}).get("canonical") if journey_path else None,
                "seo_service_canonicals": sorted(
                    row["canonical"]
                    for row in seo.get("routes") or []
                    if row.get("provenance", {}).get("service_id") in service_ids
                ),
            },
            "measurement": {
                "events": list(contract["conversion"]["required_measurement_events"]),
                "performance_state": contract["conversion"]["telemetry_default_state"],
                "synthetic_performance": False,
            },
            "state": state,
            "hold_reasons": sorted(set(hold_reasons)),
            "runtime_drafted": False,
            "published": False,
        })

    candidates.sort(key=lambda row: (
        priority_order.get(str(row.get("priority") or ""), len(priority_order)),
        0 if row["state"] == contract["states"]["ready"] else 1,
        str(row["job_id"]),
    ))
    ready_count = 0
    for rank, candidate in enumerate(candidates, start=1):
        if candidate["state"] == contract["states"]["ready"]:
            if ready_count >= int(contract["selection"]["maximum_ready_for_draft"]):
                candidate["state"] = contract["states"]["hold_capacity"]
                candidate["hold_reasons"] = ["CYCLE_CAPACITY_REACHED"]
            else:
                ready_count += 1
        candidate["rank"] = rank

    paths = [row["planned_route"]["path"] for row in candidates]
    if len(paths) != len(set(paths)):
        raise AuthorityError("duplicate planned authority route")
    return {
        "schema_version": contract["output"]["schema_version"],
        "product": contract["output"]["product"],
        "engine_id": contract["engine_id"],
        "provider_neutral": contract["output"]["provider_neutral"],
        "runtime_drafting_enabled": contract["publication"]["runtime_drafting_enabled"],
        "runtime_publication_enabled": contract["publication"]["runtime_publication_enabled"],
        "production_indexing_enabled": contract["publication"]["production_indexing_enabled"],
        "production_content_records": contract["output"]["production_content_records"],
        "summary": {
            "jobs_considered": len(candidates),
            "ready_for_draft": sum(row["state"] == contract["states"]["ready"] for row in candidates),
            "held": sum(row["state"] != contract["states"]["ready"] for row in candidates),
            "p0_ready": sum(row["priority"] == "P0" and row["state"] == contract["states"]["ready"] for row in candidates),
            "with_historical_proof": sum(bool(row["lineage"]["historical_proof_object_ids"]) for row in candidates),
            "published": 0,
            "performance_known": 0,
        },
        "candidates": candidates,
    }


def assert_output_path_safe(path: Path) -> None:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return
    raise AuthorityError("runtime authority output cannot be written under repository root")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demand", default=str(EUCONS / "market_intelligence" / "EUCONS_CUSTOMER_DEMAND_MODEL_2026-08-25.json"))
    parser.add_argument("--ux", default=str(EUCONS / "web" / "jtbd_ux_contract.json"))
    parser.add_argument("--services", default=str(EUCONS / "services" / "service_registry.json"))
    parser.add_argument("--evidence", default=str(EUCONS / "evidence" / "evidence_registry.json"))
    parser.add_argument("--proof", default=str(EUCONS / "evidence" / "service_proof_architecture.json"))
    parser.add_argument("--canon", default=str(EUCONS / "canon" / "commercial_canon.json"))
    parser.add_argument("--knowledge", required=True)
    parser.add_argument("--editorial", required=True)
    parser.add_argument("--seo", required=True)
    parser.add_argument("--analytics-contract", default=str(EUCONS / "analytics" / "analytics_contract.json"))
    parser.add_argument("--ia", default=str(EUCONS / "web" / "information_architecture.json"))
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    result = build_authority_plan(
        load_json(Path(args.demand)), load_json(Path(args.ux)), load_json(Path(args.services)),
        load_json(Path(args.evidence)), load_json(Path(args.proof)), load_json(Path(args.canon)),
        load_json(Path(args.knowledge)), load_json(Path(args.editorial)), load_json(Path(args.seo)),
        load_json(Path(args.analytics_contract)), load_json(Path(args.ia)), load_json(Path(args.contract)),
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        assert_output_path_safe(output)
        output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
