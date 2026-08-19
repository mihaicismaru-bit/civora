#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"


def load_engine():
    path = EUCONS / "knowledge" / "knowledge_engine.py"
    spec = importlib.util.spec_from_file_location("e14_knowledge_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def fresh_projection():
    return {
        "bridge_id": "PARTENER_P11_TO_EUCONS_E09", "bridge_state": "READY",
        "opportunities": [{
            "id": "op-1", "title": "Synthetic", "programme": "Synthetic", "status": "OPEN",
            "commercial_state": "VERIFIED_AVAILABLE", "actionable": True,
            "verified_fact_classes": ["status", "deadline"], "material_facts": {"status": "OPEN", "deadline": "2099-12-31"},
            "provenance": {"source_product": "PARTENER.EU", "source_opportunity_id": "op-1", "verification_evidence": [{"id": "ev"}]}
        }]
    }


def expect_fail(fn, label: str) -> None:
    try:
        fn()
    except Exception:
        return
    raise AssertionError(f"expected fail-closed rejection: {label}")


def main() -> None:
    engine = load_engine()
    contract = json.loads((EUCONS / "knowledge" / "knowledge_contract.json").read_text(encoding="utf-8"))
    services = json.loads((EUCONS / "services" / "service_registry.json").read_text(encoding="utf-8"))
    evidence = json.loads((EUCONS / "evidence" / "evidence_registry.json").read_text(encoding="utf-8"))
    cases = json.loads((EUCONS / "cases" / "case_study_registry.json").read_text(encoding="utf-8"))

    inactive = copy.deepcopy(evidence)
    next(row for row in inactive["evidence_items"] if row["id"] == "EV-E02-SERVICE-REGISTRY")["status"] = "RETIRED"
    result = engine.build_knowledge(services, inactive, fresh_projection(), cases, contract)
    service_rows = [row for row in result["records"] if row["type"] in {"GUIDE", "ANALYSIS", "FAQ"}]
    assert service_rows and all(row["publication_state"] == "HOLD" for row in service_rows)

    held_claim = copy.deepcopy(evidence)
    held_claim["claims"][0]["publication_state"] = "HOLD"
    result = engine.build_knowledge(services, held_claim, fresh_projection(), cases, contract)
    target = [row for row in result["records"] if row.get("source_ref") == "funding_strategy_and_eligibility" and row["type"] in {"GUIDE", "ANALYSIS", "FAQ"}]
    assert len(target) == 3 and all(row["publication_state"] == "HOLD" for row in target)

    stale = fresh_projection()
    stale["bridge_state"] = "STALE_SOURCE_HOLD"
    stale["opportunities"][0]["commercial_state"] = "HOLD_STALE_SOURCE"
    stale["opportunities"][0]["actionable"] = False
    result = engine.build_knowledge(services, evidence, stale, cases, contract)
    opportunity = next(row for row in result["records"] if row["type"] == "OPPORTUNITY")
    assert opportunity["publication_state"] == "HOLD"

    wrong_bridge = fresh_projection(); wrong_bridge["bridge_id"] = "UNKNOWN"
    expect_fail(lambda: engine.build_knowledge(services, evidence, wrong_bridge, cases, contract), "unknown bridge")

    bad_provenance = fresh_projection(); bad_provenance["opportunities"][0]["provenance"]["source_opportunity_id"] = "other"
    expect_fail(lambda: engine.build_knowledge(services, evidence, bad_provenance, cases, contract), "opportunity provenance mismatch")

    duplicate = fresh_projection(); duplicate["opportunities"].append(copy.deepcopy(duplicate["opportunities"][0]))
    expect_fail(lambda: engine.build_knowledge(services, evidence, duplicate, cases, contract), "duplicate opportunity")

    held_case_registry = copy.deepcopy(cases)
    held_case_registry["cases"] = [{"id": "case-1", "publication_state": "HOLD", "title": "Withheld", "summary": "", "claim_refs": []}]
    result = engine.build_knowledge(services, evidence, fresh_projection(), held_case_registry, contract)
    case_record = next(row for row in result["records"] if row["type"] == "CASE")
    assert case_record["publication_state"] == "HOLD"

    expect_fail(lambda: engine.assert_output_path_safe(EUCONS / "knowledge" / "runtime.json"), "repository runtime output")
    assert contract["output"]["runtime_publication_enabled"] is False
    print("PASS: E14 knowledge engine fail-closed regressions")


if __name__ == "__main__":
    main()
