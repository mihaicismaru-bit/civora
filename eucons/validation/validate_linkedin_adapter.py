#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "eucons" / "social" / "linkedin_contract.json"
ADAPTER_PATH = ROOT / "eucons" / "social" / "linkedin_adapter.py"


def load_adapter():
    spec = importlib.util.spec_from_file_location("eucons_linkedin_adapter", ADAPTER_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load LinkedIn adapter")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    required = {"schema_version", "engine_id", "input", "doctrine", "presentation", "dispatch", "output"}
    missing = sorted(required - set(contract))
    if missing:
        raise SystemExit(f"LinkedIn contract missing: {missing}")
    if contract["engine_id"] != "EUCONS_E17_LINKEDIN_ADAPTER":
        raise SystemExit("LinkedIn engine id drift")
    if contract["dispatch"]["mode"] != "DRY_RUN_ONLY":
        raise SystemExit("LinkedIn must remain dry-run before external authorization")
    if contract["dispatch"]["real_publication_enabled"] is not False:
        raise SystemExit("LinkedIn real publication enabled prematurely")
    if contract["output"]["direct_publication_enabled"] is not False:
        raise SystemExit("LinkedIn output falsely claims direct publication")
    if contract["presentation"]["hashtags_default"] is not False:
        raise SystemExit("LinkedIn generic hashtags must stay disabled by default")
    if contract["doctrine"]["site_is_canonical"] is not True:
        raise SystemExit("EUCONS site must remain LinkedIn canonical source")
    if contract["doctrine"]["no_cross_platform_verbatim_reuse"] is not True:
        raise SystemExit("LinkedIn cross-platform reuse guard missing")

    module = load_adapter()
    knowledge = {
        "product": "EUCONS_COMMERCIAL_OS",
        "engine_id": "EUCONS_E14_KNOWLEDGE_ENGINE",
        "runtime_publication_enabled": False,
        "records": [
            {
                "id": "KNW-GUIDE-1", "type": "GUIDE", "publication_state": "PUBLISHABLE", "source_ref": "SRV-01",
                "title": "Ghid: consultanță pentru pregătirea proiectului",
                "summary": "Structurăm pașii, livrabilele și limitele serviciului pe baza registrului canonic.",
                "semantics": "CANONICAL_SERVICE_DESCRIPTION",
                "provenance": {"source_kind": "E02_SERVICE_REGISTRY", "source_ref": "SRV-01", "claim_ids": ["CLM-1"], "evidence_ids": ["EVD-1"]},
            },
            {
                "id": "KNW-OPP-1", "type": "OPPORTUNITY", "publication_state": "PUBLISHABLE", "source_ref": "OPP-01",
                "title": "Oportunitate verificată", "summary": "Program verificat — apel deschis",
                "material_facts": {"status": "OPEN"}, "verified_fact_classes": ["STATUS"],
                "semantics": "VERIFIED_FUNDING_FACTS_FROM_E09",
                "provenance": {"source_product": "PARTENER.EU", "source_opportunity_id": "OPP-01", "verification_evidence": ["receipt-1"]},
            },
        ],
    }
    editorial = {
        "product": "EUCONS_COMMERCIAL_OS",
        "engine_id": "EUCONS_E15_AUTONOMOUS_EDITORIAL_LOOP",
        "runtime_publication_enabled": False,
        "dispatch_enabled": False,
        "decisions": [
            {"editorial_id": "EDT-1", "knowledge_id": "KNW-GUIDE-1", "type": "GUIDE", "source_ref": "SRV-01", "decision": "READY", "fact_kernel": {"content_hash": "a" * 64}},
            {"editorial_id": "EDT-2", "knowledge_id": "KNW-OPP-1", "type": "OPPORTUNITY", "source_ref": "OPP-01", "decision": "READY", "fact_kernel": {"content_hash": "b" * 64}},
            {"editorial_id": "EDT-HOLD", "knowledge_id": "KNW-GUIDE-1", "type": "GUIDE", "source_ref": "SRV-01", "decision": "HOLD", "fact_kernel": {"content_hash": "c" * 64}},
        ],
    }

    outbox = module.build_outbox(editorial, knowledge, contract)
    items = outbox["items"]
    if len(items) != 2:
        raise SystemExit("LinkedIn adapter must materialize READY decisions only")
    if outbox["direct_publication_enabled"] is not False or outbox["dry_run"] is not True:
        raise SystemExit("LinkedIn outbox publication gate drift")
    if outbox["authorization_required"] is not True:
        raise SystemExit("LinkedIn external authorization gate missing")
    if any(item["published"] is not False for item in items):
        raise SystemExit("LinkedIn item falsely claims publication")
    if any(item["dispatch_state"] != "OUTBOX_READY_AUTH_REQUIRED" for item in items):
        raise SystemExit("LinkedIn dry-run state mismatch")
    if any(item["idempotency_key"] != item["item_id"] for item in items):
        raise SystemExit("LinkedIn idempotency binding mismatch")
    if any("#" in item["body"] for item in items):
        raise SystemExit("LinkedIn body includes default hashtags")
    if any(item["verbatim_cross_platform_reuse_allowed"] is not False for item in items):
        raise SystemExit("LinkedIn cross-platform guard missing")
    if len(outbox["receipts"]) != len(items):
        raise SystemExit("LinkedIn immutable receipt coverage mismatch")
    if len({r["receipt_hash"] for r in outbox["receipts"]}) != len(items):
        raise SystemExit("LinkedIn receipt hashes must be unique per item")
    for item in items:
        if not item["canonical_url"].startswith("https://eucons.ro/"):
            raise SystemExit("LinkedIn canonical URL must stay on EUCONS")
        if item["canonical_url"] not in item["body"]:
            raise SystemExit("LinkedIn body must include canonical URL")

    print(f"EUCONS E17 LinkedIn Adapter: PASS ({len(items)} dry-run items; authorization gate closed)")


if __name__ == "__main__":
    main()
