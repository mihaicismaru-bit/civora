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


def synthetic_projection():
    return {
        "schema_version": 1,
        "bridge_id": "PARTENER_P11_TO_EUCONS_E09",
        "bridge_state": "READY",
        "opportunities": [
            {
                "id": "fresh-synthetic-opportunity",
                "title": "Oportunitate verificată sintetică",
                "programme": "Program sintetic",
                "status": "OPEN",
                "commercial_state": "VERIFIED_AVAILABLE",
                "actionable": True,
                "verified_fact_classes": ["status", "deadline"],
                "material_facts": {"status": "OPEN", "deadline": "2099-12-31"},
                "provenance": {
                    "source_product": "PARTENER.EU",
                    "source_opportunity_id": "fresh-synthetic-opportunity",
                    "source_projection_sha256": "a" * 64,
                    "verification_evidence": [{"id": "SYNTH-EV"}],
                },
            },
            {
                "id": "stale-synthetic-opportunity",
                "title": "Oportunitate veche sintetică",
                "programme": "Program sintetic",
                "status": "OPEN",
                "commercial_state": "HOLD_STALE_SOURCE",
                "actionable": False,
                "verified_fact_classes": ["status", "deadline"],
                "material_facts": {"status": "OPEN", "deadline": "2099-12-31"},
                "provenance": {
                    "source_product": "PARTENER.EU",
                    "source_opportunity_id": "stale-synthetic-opportunity",
                    "source_projection_sha256": "b" * 64,
                    "verification_evidence": [{"id": "SYNTH-EV-2"}],
                },
            },
        ],
    }


def main() -> None:
    knowledge_engine = load_module(EUCONS / "knowledge" / "knowledge_engine.py", "e14_knowledge")
    editorial_engine = load_module(EUCONS / "editorial" / "editorial_loop.py", "e15_editorial")
    knowledge_contract = json.loads((EUCONS / "knowledge" / "knowledge_contract.json").read_text(encoding="utf-8"))
    editorial_contract = json.loads((EUCONS / "editorial" / "editorial_loop_contract.json").read_text(encoding="utf-8"))
    services = json.loads((EUCONS / "services" / "service_registry.json").read_text(encoding="utf-8"))
    evidence = json.loads((EUCONS / "evidence" / "evidence_registry.json").read_text(encoding="utf-8"))
    cases = json.loads((EUCONS / "cases" / "case_study_registry.json").read_text(encoding="utf-8"))

    knowledge = knowledge_engine.build_knowledge(services, evidence, synthetic_projection(), cases, knowledge_contract)
    cycle = editorial_engine.build_cycle(knowledge, editorial_contract)
    total = int(knowledge["summary"]["records"])
    publishable = int(knowledge["summary"]["publishable"])
    max_ready = int(editorial_contract["selection"]["max_ready_per_cycle"])
    expected_ready = min(publishable, max_ready)
    expected_held = total - expected_ready

    assert cycle["engine_id"] == "EUCONS_E15_AUTONOMOUS_EDITORIAL_LOOP"
    assert cycle["runtime_publication_enabled"] is False
    assert cycle["dispatch_enabled"] is False
    assert cycle["summary"]["records_considered"] == total
    assert cycle["summary"]["ready"] == expected_ready
    assert cycle["summary"]["held"] == expected_held
    assert cycle["summary"]["published"] == 0
    assert cycle["summary"]["new_receipts"] == total
    assert len(cycle["receipts"]) == total
    assert len({row["receipt_id"] for row in cycle["receipts"]}) == total
    assert all(row["published"] is False and row["dispatch_state"] == "DISABLED_RUNTIME_GATE" for row in cycle["decisions"])

    opportunity = next(row for row in cycle["decisions"] if row["source_ref"] == "fresh-synthetic-opportunity")
    assert opportunity["decision"] == "READY"
    assert opportunity["fact_kernel"]["material_facts"]["deadline"] == "2099-12-31"
    assert opportunity["fact_kernel"]["provenance"]["source_product"] == "PARTENER.EU"

    stale = next(row for row in cycle["decisions"] if row["source_ref"] == "stale-synthetic-opportunity")
    assert stale["decision"] == "HOLD"
    assert "INPUT_NOT_PUBLISHABLE" in stale["hold_reasons"]

    case_decisions = [row for row in cycle["decisions"] if row["type"] == "CASE"]
    assert len(case_decisions) == int(knowledge["summary"]["by_type"]["CASE"])
    assert all(row["fact_kernel"].get("claim_refs") for row in case_decisions)
    assert all("MISSING_CASE_CLAIMS" not in row["hold_reasons"] for row in case_decisions)

    for receipt in cycle["receipts"]:
        body = {key: value for key, value in receipt.items() if key != "receipt_hash"}
        assert receipt["receipt_hash"] == editorial_engine.sha256_json(body)

    replay = editorial_engine.build_cycle(knowledge, editorial_contract, cycle["receipts"])
    assert replay["summary"]["new_receipts"] == 0
    assert replay["summary"]["unchanged_receipts"] == total
    assert replay["summary"]["superseded_receipts"] == 0
    assert replay["summary"]["withdrawn_receipts"] == 0
    assert [row["receipt_id"] for row in replay["receipts"]] == [row["receipt_id"] for row in cycle["receipts"]]

    print(json.dumps({
        "status": "PASS",
        "phase": "E15",
        "records": cycle["summary"]["records_considered"],
        "ready": cycle["summary"]["ready"],
        "held": cycle["summary"]["held"],
        "receipts": len(cycle["receipts"]),
        "case_records": len(case_decisions),
        "runtime_publication": "DISABLED",
        "replay": "DETERMINISTIC",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
