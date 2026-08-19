#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"


def load_engine():
    path = EUCONS / "knowledge" / "knowledge_engine.py"
    spec = importlib.util.spec_from_file_location("e14_knowledge", path)
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
                    "verification_evidence": [{"id": "SYNTH-EV"}]
                }
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
                    "verification_evidence": [{"id": "SYNTH-EV-2"}]
                }
            }
        ]
    }


def main() -> None:
    engine = load_engine()
    contract = json.loads((EUCONS / "knowledge" / "knowledge_contract.json").read_text(encoding="utf-8"))
    services = json.loads((EUCONS / "services" / "service_registry.json").read_text(encoding="utf-8"))
    evidence = json.loads((EUCONS / "evidence" / "evidence_registry.json").read_text(encoding="utf-8"))
    cases = json.loads((EUCONS / "cases" / "case_study_registry.json").read_text(encoding="utf-8"))
    result = engine.build_knowledge(services, evidence, synthetic_projection(), cases, contract)

    assert result["runtime_publication_enabled"] is False
    assert result["provider_neutral"] is True
    assert result["summary"]["by_type"] == {"GUIDE": 8, "ANALYSIS": 8, "OPPORTUNITY": 2, "CASE": 0, "FAQ": 8}
    assert result["summary"]["records"] == 26
    assert result["summary"]["publishable"] == 25
    assert result["summary"]["held"] == 1
    ids = [row["id"] for row in result["records"]]
    assert len(ids) == len(set(ids))

    services_public = [row for row in result["records"] if row["type"] in {"GUIDE", "ANALYSIS", "FAQ"}]
    assert all(row["publication_state"] == "PUBLISHABLE" for row in services_public)
    assert all(row["provenance"]["claim_ids"] and row["provenance"]["evidence_ids"] == ["EV-E02-SERVICE-REGISTRY"] for row in services_public)
    analyses = [row for row in result["records"] if row["type"] == "ANALYSIS"]
    assert all(row["semantics"] == "OPERATIONAL_INTERPRETATION_NOT_FUNDING_FACT" and row.get("analysis_label") for row in analyses)

    opportunity_rows = {row["source_ref"]: row for row in result["records"] if row["type"] == "OPPORTUNITY"}
    assert opportunity_rows["fresh-synthetic-opportunity"]["publication_state"] == "PUBLISHABLE"
    assert opportunity_rows["fresh-synthetic-opportunity"]["material_facts"]["deadline"] == "2099-12-31"
    assert opportunity_rows["stale-synthetic-opportunity"]["publication_state"] == "HOLD"
    assert opportunity_rows["stale-synthetic-opportunity"]["semantics"] == "WITHHELD_FUNDING_FACTS"

    print(json.dumps({
        "status": "PASS", "phase": "E14", "records": result["summary"]["records"],
        "publishable": result["summary"]["publishable"], "held": result["summary"]["held"],
        "types": result["summary"]["by_type"], "runtime_publication": "DISABLED"
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
