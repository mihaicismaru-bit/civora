#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_inputs() -> tuple[object, dict, dict, dict, dict, dict, dict, dict, dict, dict, dict, dict, dict]:
    knowledge_engine = load_module(EUCONS / "knowledge" / "knowledge_engine.py", "r09_knowledge")
    editorial_engine = load_module(EUCONS / "editorial" / "editorial_loop.py", "r09_editorial")
    seo_engine = load_module(EUCONS / "seo" / "seo_engine.py", "r09_seo")
    authority_engine = load_module(EUCONS / "authority" / "authority_loop.py", "r09_authority")
    editorial_validator = load_module(EUCONS / "validation" / "validate_editorial_loop.py", "r09_editorial_fixture")

    demand = load_json(EUCONS / "market_intelligence" / "EUCONS_CUSTOMER_DEMAND_MODEL_2026-08-25.json")
    ux = load_json(EUCONS / "web" / "jtbd_ux_contract.json")
    services = load_json(EUCONS / "services" / "service_registry.json")
    evidence = load_json(EUCONS / "evidence" / "evidence_registry.json")
    proof = load_json(EUCONS / "evidence" / "service_proof_architecture.json")
    canon = load_json(EUCONS / "canon" / "commercial_canon.json")
    cases = load_json(EUCONS / "cases" / "case_study_registry.json")
    ia = load_json(EUCONS / "web" / "information_architecture.json")
    analytics = load_json(EUCONS / "analytics" / "analytics_contract.json")
    knowledge_contract = load_json(EUCONS / "knowledge" / "knowledge_contract.json")
    editorial_contract = load_json(EUCONS / "editorial" / "editorial_loop_contract.json")
    seo_contract = load_json(EUCONS / "seo" / "seo_contract.json")
    authority_contract = load_json(EUCONS / "authority" / "authority_loop_contract.json")

    knowledge = knowledge_engine.build_knowledge(
        services, evidence, editorial_validator.synthetic_projection(), cases, knowledge_contract
    )
    editorial = editorial_engine.build_cycle(knowledge, editorial_contract)
    seo = seo_engine.build_projection(ia, services, evidence, seo_contract)
    return (
        authority_engine, demand, ux, services, evidence, proof, canon, knowledge,
        editorial, seo, analytics, ia, authority_contract,
    )


def main() -> None:
    engine, demand, ux, services, evidence, proof, canon, knowledge, editorial, seo, analytics, ia, contract = build_inputs()
    plan = engine.build_authority_plan(
        demand, ux, services, evidence, proof, canon, knowledge, editorial, seo, analytics, ia, contract
    )
    assert plan["engine_id"] == "EUCONS_R09_AUTHORITY_LOOP"
    assert plan["summary"]["jobs_considered"] == 16
    assert plan["summary"]["ready_for_draft"] == 15
    assert plan["summary"]["held"] == 1
    assert plan["summary"]["p0_ready"] == 8
    assert plan["summary"]["with_historical_proof"] == 4
    assert plan["summary"]["published"] == 0
    assert plan["summary"]["performance_known"] == 0
    assert plan["runtime_drafting_enabled"] is False
    assert plan["runtime_publication_enabled"] is False
    assert plan["production_indexing_enabled"] is False
    assert plan["production_content_records"] == 0
    assert len({row["authority_id"] for row in plan["candidates"]}) == 16
    assert len({row["planned_route"]["path"] for row in plan["candidates"]}) == 16
    assert all(row["published"] is False and row["runtime_drafted"] is False for row in plan["candidates"])
    assert all(row["planned_route"]["indexable"] is False for row in plan["candidates"])
    assert all(row["draft_scope"]["eligibility_state"] == "NOT_ASSESSED" for row in plan["candidates"])
    assert all(row["measurement"]["performance_state"] == "UNKNOWN_UNTIL_REAL_EVENTS" for row in plan["candidates"])

    held = next(row for row in plan["candidates"] if row["job_id"] == "JTBD-REP-01")
    assert held["state"] == "HOLD_ROUTE_GAP"
    assert held["hold_reasons"] == ["NO_JOURNEY_ROUTE"]
    ready = next(row for row in plan["candidates"] if row["job_id"] == "JTBD-BEN-01")
    assert ready["state"] == "READY_FOR_DRAFT"
    assert ready["content_family"] == "IMPLEMENTATION_CONTROL_GUIDE"
    assert ready["cta"]["cta_id"] == "request_implementation_review"
    assert ready["cta"]["path"] == "/evaluare-proiect/"
    assert ready["lineage"]["knowledge_ids"]
    assert ready["lineage"]["editorial_ids"]
    assert ready["lineage"]["editorial_receipt_ids"]
    assert ready["lineage"]["service_claim_ids"]
    assert ready["lineage"]["evidence_ids"]
    assert set(ready["lineage"]["historical_proof_object_ids"]) == {
        "PROOF-CASE-COMPETENTA", "PROOF-CASE-RURALBIZ"
    }
    replay = engine.build_authority_plan(
        demand, ux, services, evidence, proof, canon, knowledge, editorial, seo, analytics, ia, contract
    )
    assert engine.stable_json(replay) == engine.stable_json(plan)

    print(json.dumps({
        "status": "PASS",
        "phase": "R09",
        "jobs": plan["summary"]["jobs_considered"],
        "ready_for_draft": plan["summary"]["ready_for_draft"],
        "held": plan["summary"]["held"],
        "p0_ready": plan["summary"]["p0_ready"],
        "historical_proof_candidates": plan["summary"]["with_historical_proof"],
        "publication": "DISABLED",
        "performance": "UNKNOWN",
        "replay": "DETERMINISTIC",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
