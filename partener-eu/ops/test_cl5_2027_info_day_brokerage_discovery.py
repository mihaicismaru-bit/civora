#!/usr/bin/env python3
"""EC Cluster 5 2027 info day + EEN brokerage are intelligence, not live calls."""
import copy
import json
from pathlib import Path
from urllib.parse import urlparse

REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
SOURCES = {
    "SRC-EU-EC-CL5-2027-INFO-DAY-20261119": {
        "url": "https://research-and-innovation.ec.europa.eu/events/horizon-europe-info-days_en",
        "tier": "T1",
        "class": "official_european_commission_horizon_programme_information_event_discovery",
        "authority_class": "T1_OFFICIAL_EC_DG_RTD",
        "authority_scope": "PROGRAMME_INFO_DAY_NOT_EXACT_CALL",
        "observation_state": "PROGRAMMING_INFO_EVENT_DISCOVERED_RAW_PENDING",
        "host": "research-and-innovation.ec.europa.eu",
    },
    "SRC-EU-EEN-CL5-2027-GREENET-BROKERAGE-20261119": {
        "url": "https://een.ec.europa.eu/events/greenet-brokerage-event-2027-calls-horizon-europe-cluster-5",
        "tier": "T1B",
        "class": "official_eismea_enterprise_europe_network_cluster_brokerage_discovery",
        "authority_class": "T1B_OFFICIAL_EEN_EISMEA_EVENT_NOTICE",
        "authority_scope": "BROKERAGE_INFO_EVENT_NOT_CALL_AUTHORITY",
        "observation_state": "PARTNER_BROKERAGE_EVENT_DISCOVERED_RAW_PENDING",
        "host": "een.ec.europa.eu",
    },
}
FORBIDDEN = {
    "fetched_at", "final_url", "raw_sha256", "semantic_sha256", "parser_version",
    "run_id", "handoff_sha256", "call_identifier", "topic_identifier",
    "current_status", "call_status", "deadline", "application_deadline",
    "budget", "call_budget_eur", "eligibility", "application_endpoint",
    "exact_submission_endpoint", "submission_endpoint",
}

def validate(rows):
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "Duplicate source registry IDs"
    by_id = {r["id"]: r for r in rows}
    for source_id, expected in SOURCES.items():
        row = by_id[source_id]
        for key, value in expected.items():
            if key == "host":
                p = urlparse(row["url"])
                assert p.scheme == "https" and p.hostname == value
                assert not (p.username or p.password or p.port)
            else:
                assert row.get(key) == value, (source_id, key)
        assert row.get("event_date_discovery") == "2026-11-19"
        assert row.get("readback_date_discovery") == "2026-11-19"
        assert row.get("programmes") and "Cluster 5" in row["programmes"][0]
        assert {"EU_DIRECT","BRUSSELS","HORIZON_EUROPE","CLUSTER_5","PROGRAMMING_PIPELINE","DISCOVERY"} <= set(row["source_families"])
        assert not {"OPEN_CALL","EXACT_CALL_OPEN"} & set(row["source_families"])
        for flag in ("material_fact_use", "credentials_required", "open_call_authorized", "material_fact_publication_authorized"):
            assert row.get(flag) is False, (source_id, flag)
        assert not FORBIDDEN & set(row), (source_id, "unverified fact or forged raw receipt")
        for token in ("SURFACEMC", "NOT_CAPTURED", "raw_sha256", "fetched_at UTC", "parser_version", "run_id", "LKG"):
            assert token in row.get("note", ""), (source_id, token)
    a = by_id["SRC-EU-EC-CL5-2027-INFO-DAY-20261119"]
    b = by_id["SRC-EU-EEN-CL5-2027-GREENET-BROKERAGE-20261119"]
    assert a.get("info_day_event_scope") == "CLIMATE_ENERGY_MOBILITY_2027_CALL_TOPICS_AND_PROPOSAL_PREPARATION"
    assert b.get("linked_commission_source_id") == a["id"]
    assert b.get("source_publication_date_discovery") == "2026-09-09"
    assert "NO OPEN_CALL" in b["note"] and "OPEN_CALL" in a["note"]
    return True

def main():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    validate(rows)
    unsafe = [
        ("observation_state","OPEN_CALL"),("authority_scope","EXACT_CALL"),
        ("open_call_authorized",True),("material_fact_use",True),
        ("material_fact_publication_authorized",True),("deadline","2027-03-19"),
        ("budget",100000000),("eligibility",["all applicants"]),
        ("application_endpoint","https://example.invalid/apply"),
        ("topic_identifier","HORIZON-CL5-FAKE"),
        ("raw_sha256","0"*64),("fetched_at","2026-11-19T09:30:00Z"),
        ("final_url","https://example.invalid"),
        ("parser_version","fabricated"),("run_id","fabricated"),
        ("readback_date_discovery","2026-11-18"),
        ("event_date_discovery","2026-11-17"),
        ("url","https://example.invalid/news"),
    ]
    rejected=0
    for sid in SOURCES:
        for field,value in unsafe:
            changed=copy.deepcopy(rows)
            next(x for x in changed if x["id"]==sid)[field]=value
            try: validate(changed)
            except AssertionError: rejected+=1
            else: raise AssertionError("Unsafe mutation accepted: "+sid+" "+field)
        dupe=copy.deepcopy(rows)
        dupe.append(copy.deepcopy(next(x for x in rows if x["id"]==sid)))
        try: validate(dupe)
        except AssertionError: rejected+=1
        else: raise AssertionError("Duplicate accepted: "+sid)
    assert rejected==38
    print(json.dumps({"result":"PASS","official_event_sources":len(SOURCES),
        "negative_mutations_rejected":rejected,"open_call_authorized":False,
        "publication_effect":"NONE"}))

if __name__=="__main__":
    main()
