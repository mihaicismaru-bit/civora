#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"


def load_engine():
    path = EUCONS / "editorial" / "editorial_loop.py"
    spec = importlib.util.spec_from_file_location("e15_editorial_fail", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def base_record(rid: str, source_ref: str) -> dict:
    return {
        "id": rid,
        "type": "GUIDE",
        "publication_state": "PUBLISHABLE",
        "source_ref": source_ref,
        "title": "Ghid sintetic",
        "summary": "Rezumat sintetic",
        "sections": {"livrabile": ["x"], "limite": ["y"]},
        "semantics": "CANONICAL_SERVICE_DESCRIPTION",
        "provenance": {
            "source_kind": "E02_SERVICE_REGISTRY",
            "source_ref": source_ref,
            "claim_ids": ["CLM-SYNTH"],
            "evidence_ids": ["EV-SYNTH"],
        },
    }


def knowledge(records: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "product": "EUCONS_COMMERCIAL_OS",
        "engine_id": "EUCONS_E14_KNOWLEDGE_ENGINE",
        "runtime_publication_enabled": False,
        "records": records,
    }


def main() -> None:
    engine = load_engine()
    contract = json.loads((EUCONS / "editorial" / "editorial_loop_contract.json").read_text(encoding="utf-8"))

    valid = base_record("KNW-a-valid", "SVC-valid")
    duplicate = base_record("KNW-z-duplicate", "SVC-valid")

    missing_provenance = base_record("KNW-no-prov", "SVC-no-prov")
    missing_provenance["provenance"] = {}

    unknown_type = base_record("KNW-unknown", "SVC-unknown")
    unknown_type["type"] = "PRESS_RELEASE"

    bad_analysis = base_record("KNW-analysis", "SVC-analysis")
    bad_analysis.update({
        "type": "ANALYSIS",
        "semantics": "OPERATIONAL_INTERPRETATION_NOT_FUNDING_FACT",
        "analysis_label": "",
    })

    bad_opportunity = {
        "id": "KNW-bad-opp",
        "type": "OPPORTUNITY",
        "publication_state": "PUBLISHABLE",
        "source_ref": "OPP-bad",
        "title": "Oportunitate neverificată",
        "summary": "Program — OPEN",
        "material_facts": {"status": "OPEN"},
        "verified_fact_classes": ["status"],
        "semantics": "VERIFIED_FUNDING_FACTS_FROM_E09",
        "provenance": {
            "source_product": "OTHER",
            "source_opportunity_id": "OPP-bad",
            "verification_evidence": [],
        },
    }

    bad_case = {
        "id": "KNW-bad-case",
        "type": "CASE",
        "publication_state": "PUBLISHABLE",
        "source_ref": "CASE-bad",
        "title": "Caz fără dovadă",
        "summary": "Rezumat",
        "semantics": "VERIFIED_CASE_REGISTRY",
        "provenance": {"source_kind": "E05_CASE_REGISTRY", "source_ref": "CASE-bad", "claim_refs": []},
    }

    held = base_record("KNW-held", "SVC-held")
    held["publication_state"] = "HOLD"

    cycle = engine.build_cycle(
        knowledge([valid, duplicate, missing_provenance, unknown_type, bad_analysis, bad_opportunity, bad_case, held]),
        contract,
    )
    by_id = {row["knowledge_id"]: row for row in cycle["decisions"]}

    assert by_id["KNW-a-valid"]["decision"] == "READY"
    assert by_id["KNW-z-duplicate"]["decision"] == "HOLD"
    assert "DUPLICATE_SOURCE_RECORD" in by_id["KNW-z-duplicate"]["hold_reasons"]
    assert "MISSING_PROVENANCE" in by_id["KNW-no-prov"]["hold_reasons"]
    assert "UNKNOWN_TYPE" in by_id["KNW-unknown"]["hold_reasons"]
    assert "MISSING_ANALYSIS_LABEL" in by_id["KNW-analysis"]["hold_reasons"]
    assert "INVALID_OPPORTUNITY_SOURCE" in by_id["KNW-bad-opp"]["hold_reasons"]
    assert "MISSING_OPPORTUNITY_EVIDENCE" in by_id["KNW-bad-opp"]["hold_reasons"]
    assert "MISSING_CASE_CLAIMS" in by_id["KNW-bad-case"]["hold_reasons"]
    assert "INPUT_NOT_PUBLISHABLE" in by_id["KNW-held"]["hold_reasons"]
    assert cycle["summary"]["published"] == 0
    assert all(receipt["published"] is False for receipt in cycle["receipts"])

    baseline = engine.build_cycle(knowledge([valid]), contract)
    changed = [dict(baseline["receipts"][0])]
    changed[0]["content_hash"] = "0" * 64
    changed.append({
        "subject_id": "EDT-ghost",
        "receipt_id": "RCP-E15-ghost",
        "content_hash": "1" * 64,
        "decision": "READY",
        "dispatch_state": "DISABLED_RUNTIME_GATE",
    })
    replay = engine.build_cycle(knowledge([valid]), contract, changed)
    states = {row["state"] for row in replay["reconciliation"]}
    assert "SUPERSEDED" in states
    assert "WITHDRAWN" in states

    try:
        engine.build_cycle({**knowledge([valid]), "engine_id": "UNKNOWN"}, contract)
    except engine.EditorialError:
        pass
    else:
        raise AssertionError("unknown knowledge engine must fail")

    try:
        engine.assert_output_path_safe(EUCONS / "editorial" / "forbidden.json")
    except engine.EditorialError:
        pass
    else:
        raise AssertionError("repository output path must fail closed")

    print(json.dumps({
        "status": "PASS",
        "phase": "E15",
        "fail_closed_cases": 9,
        "dispatch": "DISABLED",
        "reconciliation": ["SUPERSEDED", "WITHDRAWN"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
