#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"


def load_engine():
    path = EUCONS / "seo" / "seo_engine.py"
    spec = importlib.util.spec_from_file_location("e16_seo_fail", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def must_fail(engine, ia, services, evidence, contract, label):
    try:
        engine.build_projection(ia, services, evidence, contract)
    except engine.SEOError:
        return
    raise AssertionError(f"{label} must fail closed")


def main() -> None:
    engine = load_engine()
    contract = json.loads((EUCONS / "seo" / "seo_contract.json").read_text(encoding="utf-8"))
    ia = json.loads((EUCONS / "web" / "information_architecture.json").read_text(encoding="utf-8"))
    services = json.loads((EUCONS / "services" / "service_registry.json").read_text(encoding="utf-8"))
    evidence = json.loads((EUCONS / "evidence" / "evidence_registry.json").read_text(encoding="utf-8"))

    bad_origin = copy.deepcopy(ia)
    bad_origin["canonical_origin"] = "http://eucons.ro"
    must_fail(engine, bad_origin, services, evidence, contract, "http canonical")

    duplicate_path = copy.deepcopy(ia)
    duplicate = copy.deepcopy(duplicate_path["core_routes"][0])
    duplicate["id"] = "duplicate-home"
    duplicate_path["core_routes"].append(duplicate)
    must_fail(engine, duplicate_path, services, evidence, contract, "duplicate path")

    duplicate_id = copy.deepcopy(ia)
    duplicate = copy.deepcopy(duplicate_id["core_routes"][1])
    duplicate["path"] = "/duplicate-services/"
    duplicate_id["core_routes"].append(duplicate)
    must_fail(engine, duplicate_id, services, evidence, contract, "duplicate id")

    unknown_surface = copy.deepcopy(ia)
    unknown_surface["core_routes"][0]["surface"] = "INVENTED"
    must_fail(engine, unknown_surface, services, evidence, contract, "unknown surface")

    missing_service = copy.deepcopy(services)
    missing_service["services"] = missing_service["services"][1:]
    must_fail(engine, ia, missing_service, evidence, contract, "missing publishable service")

    reduced_evidence = copy.deepcopy(evidence)
    first_service = ia["service_routes"][0]["service_id"]
    reduced_evidence["claims"] = [
        row for row in reduced_evidence.get("claims", [])
        if not (row.get("claim_class") == "SERVICE_OFFERING" and row.get("object_ref") == first_service)
    ]
    reduced = engine.build_projection(ia, services, reduced_evidence, contract)
    assert reduced["summary"]["service_routes"] == 7
    assert all(row.get("provenance", {}).get("service_id") != first_service for row in reduced["routes"])
    assert reduced["summary"]["orphan_routes"] == 0

    try:
        engine.assert_output_path_safe(EUCONS / "seo" / "forbidden.json")
    except engine.SEOError:
        pass
    else:
        raise AssertionError("repository output path must fail closed")

    print(json.dumps({
        "status": "PASS",
        "phase": "E16",
        "fail_closed_cases": 6,
        "withheld_unproven_service": first_service,
        "preview_indexing": "DISABLED",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
