#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads((ROOT / "eucons" / "social" / "facebook_contract.json").read_text(encoding="utf-8"))
ADAPTER_PATH = ROOT / "eucons" / "social" / "facebook_adapter.py"


def load_adapter():
    spec = importlib.util.spec_from_file_location("eucons_facebook_failclosed", ADAPTER_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load Facebook adapter")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_adapter()
BASE_KNOWLEDGE = {
    "product": "EUCONS_COMMERCIAL_OS", "engine_id": "EUCONS_E14_KNOWLEDGE_ENGINE", "runtime_publication_enabled": False,
    "records": [{
        "id": "KNW-1", "type": "ANALYSIS", "publication_state": "PUBLISHABLE", "source_ref": "SRV-01",
        "title": "Cum abordăm proiectul", "summary": "Interpretare operațională controlată.",
        "analysis_label": "Analiză operațională; nu modifică fapte administrative de finanțare.",
        "semantics": "OPERATIONAL_INTERPRETATION_NOT_FUNDING_FACT",
        "provenance": {"source_kind": "E02_SERVICE_REGISTRY", "claim_ids": ["CLM-1"], "evidence_ids": ["EVD-1"]}
    }]
}
BASE_EDITORIAL = {
    "product": "EUCONS_COMMERCIAL_OS", "engine_id": "EUCONS_E15_AUTONOMOUS_EDITORIAL_LOOP",
    "runtime_publication_enabled": False, "dispatch_enabled": False,
    "decisions": [{"editorial_id": "EDT-1", "knowledge_id": "KNW-1", "type": "ANALYSIS", "source_ref": "SRV-01", "decision": "READY", "fact_kernel": {"content_hash": "a" * 64}}]
}


def must_fail(name: str, editorial=None, knowledge=None) -> None:
    try:
        MODULE.build_outbox(copy.deepcopy(editorial or BASE_EDITORIAL), copy.deepcopy(knowledge or BASE_KNOWLEDGE), copy.deepcopy(CONTRACT))
    except MODULE.FacebookAdapterError:
        return
    raise SystemExit(f"{name}: adapter failed open")


def main() -> None:
    editorial = copy.deepcopy(BASE_EDITORIAL); editorial["dispatch_enabled"] = True
    must_fail("upstream dispatch enabled", editorial=editorial)
    editorial = copy.deepcopy(BASE_EDITORIAL); editorial["decisions"][0]["knowledge_id"] = "MISSING"
    must_fail("missing knowledge", editorial=editorial)
    editorial = copy.deepcopy(BASE_EDITORIAL); editorial["decisions"][0]["source_ref"] = "OTHER"
    must_fail("identity mismatch", editorial=editorial)
    knowledge = copy.deepcopy(BASE_KNOWLEDGE); knowledge["records"][0]["publication_state"] = "HOLD"
    must_fail("non-publishable knowledge", knowledge=knowledge)
    knowledge = copy.deepcopy(BASE_KNOWLEDGE); knowledge["records"][0]["analysis_label"] = ""
    must_fail("analysis label missing", knowledge=knowledge)
    knowledge = copy.deepcopy(BASE_KNOWLEDGE); knowledge["records"][0]["summary"] = "X" * 2400
    must_fail("oversized body", knowledge=knowledge)
    knowledge = copy.deepcopy(BASE_KNOWLEDGE); knowledge["runtime_publication_enabled"] = True
    must_fail("knowledge runtime enabled", knowledge=knowledge)
    print("EUCONS E18 Facebook fail-closed regressions: PASS")


if __name__ == "__main__":
    main()
