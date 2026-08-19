#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FB_PATH = ROOT / "eucons" / "social" / "facebook_adapter.py"
LI_PATH = ROOT / "eucons" / "social" / "linkedin_adapter.py"
FB_CONTRACT = json.loads((ROOT / "eucons" / "social" / "facebook_contract.json").read_text(encoding="utf-8"))
LI_CONTRACT = json.loads((ROOT / "eucons" / "social" / "linkedin_contract.json").read_text(encoding="utf-8"))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    if FB_CONTRACT["engine_id"] != "EUCONS_E18_FACEBOOK_ADAPTER":
        raise SystemExit("Facebook engine id drift")
    if FB_CONTRACT["dispatch"]["mode"] != "DRY_RUN_ONLY" or FB_CONTRACT["dispatch"]["real_publication_enabled"] is not False:
        raise SystemExit("Facebook publication gate must remain closed")
    if FB_CONTRACT["doctrine"]["linkedin_verbatim_reuse_forbidden"] is not True:
        raise SystemExit("Facebook/LinkedIn copy separation guard missing")

    fb = load("eucons_fb", FB_PATH)
    li = load("eucons_li_for_fb_validation", LI_PATH)
    knowledge = {
        "product": "EUCONS_COMMERCIAL_OS", "engine_id": "EUCONS_E14_KNOWLEDGE_ENGINE", "runtime_publication_enabled": False,
        "records": [{
            "id": "KNW-1", "type": "GUIDE", "publication_state": "PUBLISHABLE", "source_ref": "SRV-01",
            "title": "Ghid: pregătirea proiectului", "summary": "Pași clari, livrabile și limite verificate.",
            "semantics": "CANONICAL_SERVICE_DESCRIPTION",
            "provenance": {"source_kind": "E02_SERVICE_REGISTRY", "claim_ids": ["CLM-1"], "evidence_ids": ["EVD-1"]}
        }]
    }
    editorial = {
        "product": "EUCONS_COMMERCIAL_OS", "engine_id": "EUCONS_E15_AUTONOMOUS_EDITORIAL_LOOP",
        "runtime_publication_enabled": False, "dispatch_enabled": False,
        "decisions": [{"editorial_id": "EDT-1", "knowledge_id": "KNW-1", "type": "GUIDE", "source_ref": "SRV-01", "decision": "READY", "fact_kernel": {"content_hash": "a" * 64}}]
    }
    fb_out = fb.build_outbox(editorial, knowledge, FB_CONTRACT)
    li_out = li.build_outbox(editorial, knowledge, LI_CONTRACT)
    if len(fb_out["items"]) != 1 or fb_out["direct_publication_enabled"] is not False or fb_out["dry_run"] is not True:
        raise SystemExit("Facebook dry-run output drift")
    item = fb_out["items"][0]
    if item["dispatch_state"] != "FACEBOOK_OUTBOX_READY_AUTH_REQUIRED" or item["published"] is not False:
        raise SystemExit("Facebook authorization gate missing")
    if item["body"] == li_out["items"][0]["body"]:
        raise SystemExit("Facebook reused LinkedIn copy verbatim")
    if item["canonical_url"] not in item["body"] or not item["canonical_url"].startswith("https://eucons.ro/"):
        raise SystemExit("Facebook canonical binding failed")
    if item["idempotency_key"] != item["item_id"]:
        raise SystemExit("Facebook idempotency binding failed")
    if item["verbatim_cross_platform_reuse_allowed"] is not False or "#" in item["body"]:
        raise SystemExit("Facebook packaging guard failed")
    if len(fb_out["receipts"]) != 1 or not fb_out["receipts"][0]["receipt_hash"]:
        raise SystemExit("Facebook immutable receipt missing")
    print("EUCONS E18 Facebook Adapter: PASS (Facebook-specific dry-run copy; authorization gate closed)")


if __name__ == "__main__":
    main()
