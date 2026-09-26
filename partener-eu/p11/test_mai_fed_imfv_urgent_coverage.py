#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
bundle = json.loads((ROOT / "opportunity_bundle.json").read_text(encoding="utf-8"))

spec = importlib.util.spec_from_file_location("projection", ROOT / "build_public_projection.py")
projection_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(projection_mod)

rows = {row["opportunity_id"]: row for row in bundle["opportunities"]}
for oid, budget in {
    "mai-imfv-bv23a-2026": 1000000,
    "mai-imfv-bv10b-2026": 13203953,
}.items():
    row = rows[oid]
    assert row["status"] == "OPEN"
    assert row["publication_state"] == "PUBLISHABLE"
    assert row["material_facts"]["deadline"]["closes"] == "2026-09-30T16:00:00+03:00"
    assert row["material_facts"]["budget"] == {
        "amount": budget,
        "currency": "RON",
        "basis": "FEN_AVAILABLE_CALL_ALLOCATION",
    }
    assert row["material_facts"]["beneficiaries"] == ["Autoritate publică centrală"]
    assert set(row["fact_evidence"]) == {"status", "deadline", "budget", "beneficiaries"}

projection = projection_mod.build(bundle)
projected = {row["id"]: row for row in projection["opportunities"]}
for oid in ("mai-imfv-bv23a-2026", "mai-imfv-bv10b-2026"):
    row = projected[oid]
    assert row["status"] == "OPEN"
    assert row["publicationDecision"]["decision"] == "ALLOW_VERIFIED_FACTS"
    assert set(row["verifiedFactClasses"]) == {"status", "deadline", "budget", "beneficiaries"}

print("PASS MAI/FED urgent IMFV coverage")
