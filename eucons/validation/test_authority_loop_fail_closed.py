#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

from validate_authority_loop import build_inputs

ROOT = Path(__file__).resolve().parents[2]


def expect_error(engine, args: list, needle: str) -> None:
    try:
        engine.build_authority_plan(*args)
    except engine.AuthorityError as exc:
        assert needle in str(exc), (needle, str(exc))
    else:
        raise AssertionError(f"expected AuthorityError containing {needle}")


def main() -> None:
    engine, demand, ux, services, evidence, proof, canon, knowledge, editorial, seo, analytics, ia, contract = build_inputs()
    base = [demand, ux, services, evidence, proof, canon, knowledge, editorial, seo, analytics, ia, contract]

    bad = copy.deepcopy(base)
    bad[0]["product"] = "FOREIGN_PRODUCT"
    expect_error(engine, bad, "unknown product input")

    bad = copy.deepcopy(base)
    bad[0]["demand_matrix"][0]["service_ids"] = ["missing_service"]
    expect_error(engine, bad, "demand job references missing service")

    bad = copy.deepcopy(base)
    target_job = bad[0]["demand_matrix"][0]
    service_id = target_job["service_ids"][0]
    coverage = next(row for row in bad[4]["service_coverage"] if row["service_id"] == service_id)
    coverage["demand_job_ids"].remove(target_job["id"])
    expect_error(engine, bad, "service-proof demand mapping missing")

    bad = copy.deepcopy(base)
    bad[7]["decisions"][0]["knowledge_id"] = "KNW-missing"
    expect_error(engine, bad, "editorial decision references unknown knowledge record")

    bad = copy.deepcopy(base)
    bad[6]["runtime_publication_enabled"] = True
    expect_error(engine, bad, "knowledge runtime publication must remain disabled")

    bad = copy.deepcopy(base)
    bad[7]["dispatch_enabled"] = True
    expect_error(engine, bad, "editorial dispatch must remain disabled")

    bad = copy.deepcopy(base)
    bad[8]["production_indexing_enabled"] = True
    expect_error(engine, bad, "production indexing must remain disabled")

    bad = copy.deepcopy(base)
    del bad[9]["events"]["cta_click"]
    expect_error(engine, bad, "missing analytics event")

    bad = copy.deepcopy(base)
    bad[10]["conditional_route_families"] = [
        row for row in bad[10]["conditional_route_families"] if row["id"] != "guide_profile"
    ]
    expect_error(engine, bad, "missing guide conditional route family")

    missing_journey = copy.deepcopy(base)
    missing_journey[1]["journeys"] = [
        row for row in missing_journey[1]["journeys"] if "JTBD-SME-01" not in row["job_ids"]
    ]
    plan = engine.build_authority_plan(*missing_journey)
    held = next(row for row in plan["candidates"] if row["job_id"] == "JTBD-SME-01")
    assert held["state"] == "HOLD_ROUTE_GAP" and "NO_JOURNEY_ROUTE" in held["hold_reasons"]

    bad_cta = copy.deepcopy(base)
    journey = next(row for row in bad_cta[1]["journeys"] if "JTBD-SME-01" in row["job_ids"])
    journey["cta_id"] = "unknown_cta"
    plan = engine.build_authority_plan(*bad_cta)
    held = next(row for row in plan["candidates"] if row["job_id"] == "JTBD-SME-01")
    assert held["state"] == "HOLD_ROUTE_GAP" and "CTA_NOT_CANONICAL" in held["hold_reasons"]

    missing_evidence = copy.deepcopy(base)
    claim = next(row for row in missing_evidence[3]["claims"] if row.get("object_ref") == "funding_strategy_and_eligibility")
    claim["publication_state"] = "HOLD"
    plan = engine.build_authority_plan(*missing_evidence)
    held = next(row for row in plan["candidates"] if row["job_id"] == "JTBD-SME-01")
    assert held["state"] == "HOLD_EVIDENCE"
    assert "SERVICE_OFFERING_EVIDENCE_MISSING" in held["hold_reasons"]

    no_editorial = copy.deepcopy(base)
    for row in no_editorial[7]["decisions"]:
        if row.get("source_ref") == "funding_strategy_and_eligibility":
            row["decision"] = "HOLD"
    plan = engine.build_authority_plan(*no_editorial)
    held = next(row for row in plan["candidates"] if row["job_id"] == "JTBD-SME-01")
    assert held["state"] == "HOLD_EDITORIAL_LINEAGE"
    assert "NO_READY_EDITORIAL_LINEAGE" in held["hold_reasons"]

    try:
        engine.assert_output_path_safe(ROOT / "eucons" / "authority" / "forbidden.json")
    except engine.AuthorityError as exc:
        assert "cannot be written under repository root" in str(exc)
    else:
        raise AssertionError("repository runtime output should fail closed")
    with tempfile.TemporaryDirectory() as tmp:
        engine.assert_output_path_safe(Path(tmp) / "authority.json")

    baseline = engine.build_authority_plan(*base)
    assert all(row["published"] is False for row in baseline["candidates"])
    assert all(row["planned_route"]["canonical"] is None for row in baseline["candidates"])
    assert all(row["draft_scope"]["material_funding_fact_gate"] == "OFFICIAL_REQUIRED" for row in baseline["candidates"])
    assert all(row["draft_scope"]["eligibility_state"] == "NOT_ASSESSED" for row in baseline["candidates"])
    assert baseline["production_content_records"] == 0

    print(json.dumps({
        "status": "PASS",
        "phase": "R09_FAIL_CLOSED",
        "negative_cases": 13,
        "unsupported_funding_claims": "BLOCKED",
        "eligibility": "NOT_ASSESSED",
        "runtime_publication": "DISABLED",
        "production_content_records": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
