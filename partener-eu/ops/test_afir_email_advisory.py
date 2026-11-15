#!/usr/bin/env python3
"""Dated AFIR communications advisory cannot turn into a live health or funding-call fact."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "ingest" / "source_registry.json"
DISCOVERY = ROOT / "validation" / "discovery" / "afir-email-incident-20261113.json"
SOURCE_ID = "SRC-RO-AFIR-EMAIL-INCIDENT-20261113"
URL = (
    "https://www.afir.ro/info-la-zi/"
    "afir-se-confrunta-cu-lipsa-serviciilor-de-e-mail-din-cauza-"
    "problemei-care-se-manifesta-la-nivel-global/"
)

registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
rows = registry["sources"]
assert len({row["id"] for row in rows}) == len(rows), "duplicate source identity"
matches = [row for row in rows if row["id"] == SOURCE_ID]
assert len(matches) == 1, "AFIR dated advisory missing/duplicated"
row = matches[0]
assert row["url"] == URL
assert row["tier"] == "T1" and row["authority_class"] == "T1_OFFICIAL_AGENCY"
assert row["programme_family"] == "PS_PAC_2023_2027/AFIR_OPERATIONS"
assert row["observation_state"] == "OPERATIONAL_ADVISORY_DISCOVERY_ONLY"
assert row["authority_scope"] == "DATED_SERVICE_NOTICE_ONLY"
assert row["event_date_discovery"] == "2026-11-13"
assert row["current_service_status_verified"] is False
assert row["material_fact_use"] is False
assert row["open_call_authorized"] is False
assert row["material_fact_publication_authorized"] is False
assert {"ROMANIA", "AFIR", "OPERATIONAL_ADVISORY", "DISCOVERY"}.issubset(
    set(row["source_families"])
)

item = json.loads(DISCOVERY.read_text(encoding="utf-8"))
assert item["official_url"] == URL and item["source_id"] == SOURCE_ID
assert item["official_notice_date"] == "2026-11-13"
assert item["observation_state"] == row["observation_state"]
assert item["candidate_lifecycle"] == "DATED_OPERATIONS_NOTICE_NOT_CALL"
assert item["authority_class"] == row["authority_class"]
assert item["programme_family"] == row["programme_family"]
receipt = item["source_provenance"]
assert receipt["requested_url"] == URL
assert receipt["raw_original_acquired"] is False
assert receipt["semantic_replay_passed"] is False
for field in ("final_url", "fetched_at", "raw_sha256", "parser_version", "run_id"):
    assert receipt[field] is None, f"unacquired raw provenance forged: {field}"
gate = item["policy"]
for field in (
    "current_outage_confirmed", "current_recovery_confirmed", "material_fact_use",
    "open_call_authorized", "publish_authorized", "distribution_authorized",
    "material_fact_publication_authorized",
):
    assert gate[field] is False, f"operational advisory gained authority: {field}"
assert gate["publication_effect"] == "NONE"
assert item["next_gate"] and item["rollback"]
print("PASS AFIR dated mail advisory: discovery-only, historical, no inferred current state or call authority")
