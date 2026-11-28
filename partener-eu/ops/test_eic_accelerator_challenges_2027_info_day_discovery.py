#!/usr/bin/env python3
"""Official EIC Accelerator Challenges 2027 briefing is intelligence, never OPEN_CALL."""
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
SOURCE_ID = "SRC-EU-EIC-ACCELERATOR-CHALLENGES-2027-INFO-DAY-20261120"
WORK_PROGRAMME_ID = "SRC-EU-EIC-WP-2027-ADOPTED-20261105"
URL = "https://eic.ec.europa.eu/events/online-info-day-accelerator-challenges-2027-2026-11-20_en"
FORBIDDEN = {
    "fetched_at", "final_url", "raw_sha256", "semantic_sha256", "parser_version",
    "run_id", "handoff_sha256", "status", "current_status", "call_status",
    "deadline", "application_deadline", "budget", "budget_eur",
    "eligibility", "exact_submission_endpoint", "application_endpoint",
    "call_identifier", "topic_identifier",
}
TOPICS = {
    "advanced_in_situ_ocean_observation",
    "climate_neutral_and_smart_cities",
    "fusion_power_plants_enabling_technologies",
    "carbon_removal_and_utilisation",
}


def validate(sources):
    ids = [x["id"] for x in sources]
    assert len(ids) == len(set(ids)), "Duplicate source ids"
    rows = {x["id"]: x for x in sources}
    assert SOURCE_ID in rows and WORK_PROGRAMME_ID in rows
    row = rows[SOURCE_ID]
    p = urlsplit(row["url"])
    assert row["url"] == URL and p.scheme == "https"
    assert p.hostname == "eic.ec.europa.eu" and not (p.username or p.password or p.port)
    assert row.get("tier") == "T1"
    assert row.get("authority_class") == "T1_OFFICIAL_EIC_EISMEA_INFO_EVENT"
    assert row.get("authority_scope") == "CHALLENGES_2027_INFORMATION_EVENT_NOT_EXACT_CALL"
    assert row.get("observation_state") == "EIC_CHALLENGES_2027_INFO_EVENT_DISCOVERED_RAW_PENDING"
    assert row.get("linked_eic_work_programme_source_id") == WORK_PROGRAMME_ID
    assert row.get("event_date_discovery") == "2026-11-20"
    assert row.get("readback_date_discovery") == "2026-11-19"
    assert row.get("registration_cutoff_label_discovery") == "2026-11-19 10:00 CET (event registration, not funding deadline)"
    assert TOPICS <= set(row.get("extract", []))
    assert {"EU_DIRECT","BRUSSELS","EIC","ACCELERATOR","MARKET_INTELLIGENCE","DISCOVERY"} <= set(row.get("source_families", []))
    assert "OPEN_CALL" not in row["source_families"]
    assert not FORBIDDEN.intersection(row), "Unverified receipt or call fact"
    for flag in ("material_fact_use","credentials_required","open_call_authorized","material_fact_publication_authorized"):
        assert row.get(flag) is False, flag
    note = row.get("note", "")
    for marker in ("SURFACEMC","NOT_CAPTURED","fetched_at UTC","raw_sha256","parser_version",
                   "run_id","LKG","OPEN_CALL","NO DISTRIBUTION"):
        assert marker in note, marker
    assert rows[WORK_PROGRAMME_ID]["observation_state"] == "PROGRAMMING_PIPELINE"


def main():
    sources = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    validate(sources)
    mutations = [
        ("observation_state","OPEN_CALL"), ("authority_scope","CURRENT_EXACT_CALL"),
        ("open_call_authorized",True), ("material_fact_use",True),
        ("material_fact_publication_authorized",True),
        ("deadline","2027-01-01"), ("budget_eur",100000000),
        ("eligibility",["any company"]), ("application_endpoint","https://example.invalid"),
        ("raw_sha256","0"*64), ("fetched_at","2026-11-19T10:25:00Z"),
        ("parser_version","fabricated"), ("run_id","fabricated"),
        ("event_date_discovery","2026-11-19"),
        ("registration_cutoff_label_discovery","2027-01-01"),
        ("url","https://example.invalid/event"),
        ("linked_eic_work_programme_source_id","SRC-FAKE"),
    ]
    rejected = 0
    for field, value in mutations:
        altered = copy.deepcopy(sources)
        next(x for x in altered if x["id"] == SOURCE_ID)[field] = value
        try:
            validate(altered)
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError("Unsafe EIC briefing mutation accepted: " + field)
    duplicate = copy.deepcopy(sources)
    duplicate.append(copy.deepcopy(next(x for x in sources if x["id"] == SOURCE_ID)))
    try:
        validate(duplicate)
    except AssertionError:
        rejected += 1
    else:
        raise AssertionError("Duplicate EIC briefing accepted")
    assert rejected == 18
    print(json.dumps({"result":"PASS","source_id":SOURCE_ID,"negative_mutations_rejected":rejected,
                      "open_call_authorized":False,"publication_effect":"NONE"}))


if __name__ == "__main__":
    main()
