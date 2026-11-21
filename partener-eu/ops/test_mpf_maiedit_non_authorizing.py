#!/usr/bin/env python3
"""MAI MPF event: publication/edit timestamps and redirect are discovery, not OPEN."""
import copy
import json
from pathlib import Path
from urllib.parse import urlparse

REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
ID = "SRC-RO-MAI-MPF-INFORMATION-SESSION-20261117"
REQUESTED = "https://fed.mai.gov.ro/11767/11767/"
BROWSER_REDIRECT = "https://fed.mai.gov.ro/11767/facilitatea-pentru-parteneriate-in-domeniul-migratiei-sesiune-informare-ce/"
EXPECTED = {
    "id": ID,
    "url": REQUESTED,
    "tier": "T2",
    "authority_class": "T2_NATIONAL_PUBLIC_BODY_RELAY_OF_DG_HOME_MPF_INFORMATION_EVENT",
    "authority_scope": "INFORMATION_EVENT_DISCOVERY_NOT_APPLICATION_AUTHORITY",
    "observation_state": "OFFICIAL_INFORMATION_EVENT_DISCOVERED_RAW_PENDING",
    "event_announcement_date_discovery": "2026-11-17",
    "article_edit_date_discovery": "2026-11-18",
    "readback_date_discovery": "2026-11-19",
    "redirect_target_browser_observed_discovery": BROWSER_REDIRECT,
    "event_date_discovery": "2026-11-27",
    "event_time_discovery": "13:00-14:30 CET",
    "adapter_required": "MPF_2026_ORGANISER_EXACT_CALL_ID_AND_GATEWAY_RECONCILE_V1",
}
FORBIDDEN = {
    "status", "current_status", "call_status", "submission_status",
    "exact_call_identifier", "call_identifier", "topic_identifier",
    "application_endpoint", "exact_submission_endpoint",
    "deadline", "application_deadline", "submission_deadline",
    "budget", "budget_eur", "grant_max_eur", "eligibility",
    "publish_authorized", "last_verified_open",
    "final_url", "fetched_at", "raw_sha256", "semantic_sha256",
    "parser_version", "run_id", "handoff_sha256",
}

def validate(rows):
    found = [s for s in rows if s.get("id") == ID]
    assert len(found) == 1, "MAI MPF relay source must occur exactly once"
    row = found[0]
    for key, value in EXPECTED.items():
        assert row.get(key) == value, "MPF event provenance drift: " + key
    requested = urlparse(row["url"])
    redirect = urlparse(row["redirect_target_browser_observed_discovery"])
    assert requested.scheme == redirect.scheme == "https"
    assert requested.hostname == redirect.hostname == "fed.mai.gov.ro"
    assert requested.username is None and requested.password is None
    assert redirect.username is None and redirect.password is None
    families = set(row.get("source_families", []))
    assert {"ROMANIA", "MAI", "EU_DIRECT", "BRUSSELS", "INFORMATION_EVENT", "DISCOVERY"} <= families
    assert not {"OPEN_CALL", "CALL_EXACT_OPEN"} & families
    for key in ("material_fact_use", "credentials_required",
                "open_call_authorized", "material_fact_publication_authorized"):
        assert row.get(key) is False, "Event relay improperly authorizes calls: " + key
    assert not FORBIDDEN & row.keys(), "Original acquisition receipt or call fact fabricated"
    note = row.get("note") or ""
    for marker in ("17 November 2026", "18 November 2026", "19 November 2026",
                   "BROWSER REDIRECT DISCOVERY", "NOT_CAPTURED", "SURFACEMC",
                   "final_url", "raw_sha256", "parser_version", "run_id",
                   "OPEN_CALL", "LKG", "not an application deadline"):
        assert marker.lower() in note.lower(), "Lost discovery/authority hold: " + marker

def main():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    validate(rows)
    changes = [
        ("event_announcement_date_discovery", "2026-11-18"),
        ("article_edit_date_discovery", "2026-11-17"),
        ("readback_date_discovery", "2026-11-18"),
        ("event_date_discovery", "2026-11-18"),
        ("event_time_discovery", "13:00-14:30 UTC"),
        ("url", BROWSER_REDIRECT),
        ("redirect_target_browser_observed_discovery", "https://example.invalid/open-call"),
        ("authority_class", "T1_EXACT_CALL_AUTHORITY"),
        ("authority_scope", "EXACT_OPEN_CALL"),
        ("tier", "T1"),
        ("observation_state", "OPEN_CALL"),
        ("material_fact_use", True),
        ("open_call_authorized", True),
        ("material_fact_publication_authorized", True),
        ("status", "OPEN"),
        ("call_identifier", "MPF-CALL-1"),
        ("deadline", "2027-01-31"),
        ("budget_eur", 10000000),
        ("eligibility", ["all applicants"]),
        ("application_endpoint", "https://example.invalid/apply"),
        ("final_url", BROWSER_REDIRECT),
        ("fetched_at", "2026-11-19T00:00:00Z"),
        ("raw_sha256", "0"*64),
        ("parser_version", "invented"),
        ("run_id", "invented"),
    ]
    rejected = 0
    for key, value in changes:
        trial = copy.deepcopy(rows)
        next(s for s in trial if s.get("id") == ID)[key] = value
        try:
            validate(trial)
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError("Unsafe event/receipt mutation admitted: " + key)
    trial = copy.deepcopy(rows)
    trial.append(copy.deepcopy(next(s for s in rows if s.get("id") == ID)))
    try:
        validate(trial)
    except AssertionError:
        rejected += 1
    else:
        raise AssertionError("Duplicate official source admitted")
    print(json.dumps({"result": "PASS", "source_id": ID,
                      "negative_mutations_rejected": rejected,
                      "observation_state": EXPECTED["observation_state"],
                      "open_call_authorized": False,
                      "publication_effect": "NONE"}))

if __name__ == "__main__":
    main()
