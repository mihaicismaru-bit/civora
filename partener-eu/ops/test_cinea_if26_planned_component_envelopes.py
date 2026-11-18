#!/usr/bin/env python3
"""CINEA IF26 2026 component envelopes are planned, never currently OPEN calls."""
import copy
import json
from pathlib import Path
from urllib.parse import urlparse

REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
ID = "SRC-EU-CINEA-IF26-20261117-FIVE-PLANNED-CALLS"
URL = "https://cinea.ec.europa.eu/news-events/news/registrations-open-innovation-fund-2026-info-days-2026-11-17_en"
EXPECTED = {
    "Hydrogen auction": ("AUCTION", 500_000_000),
    "Industrial heat auction": ("AUCTION", 1_000_000_000),
    "SME grant call": ("GRANT", 200_000_000),
    "Net-zero technologies grant call": ("GRANT", 3_300_000_000),
    "Maritime grant call": ("GRANT", 200_000_000),
}
FORBIDDEN = {
    "call_identifier", "topic_identifier", "exact_call_identifier",
    "submission_deadline", "application_deadline", "deadline",
    "application_endpoint", "exact_submission_endpoint",
    "call_status", "current_status", "budget", "call_budget_eur",
    "raw_sha256", "semantic_sha256", "handoff_sha256",
    "fetched_at", "final_url", "parser_version", "run_id",
}
FORBIDDEN_COMPONENT = {
    "call_identifier", "topic_identifier", "application_endpoint", "deadline",
    "call_budget_eur", "grant_max_eur", "eligibility", "status",
}

def validate(sources):
    matches = [s for s in sources if s.get("id") == ID]
    assert len(matches) == 1, "Official CINEA IF26 planning descriptor must be unique"
    row = matches[0]
    assert row.get("url") == URL
    u = urlparse(row["url"])
    assert u.scheme == "https" and u.netloc == "cinea.ec.europa.eu"
    assert row.get("tier") == "T1"
    assert row.get("authority_scope") == "PROGRAMMING_FRAMEWORK"
    assert row.get("observation_state") == "PROGRAMMING_PIPELINE"
    assert row.get("authority_class") == "T1_OFFICIAL_CINEA_COMMISSION_CALL_PROGRAMMING_ANNOUNCEMENT"
    assert {"EU_DIRECT", "BRUSSELS", "INNOVATION_FUND", "PROGRAMMING_PIPELINE", "DISCOVERY"} <= set(row.get("source_families") or [])
    assert not {"OPEN_CALL", "CALL_EXACT_OPEN"} & set(row.get("source_families") or [])
    for field in ("material_fact_use", "credentials_required", "open_call_authorized", "material_fact_publication_authorized"):
        assert row.get(field) is False, field
    assert row.get("planned_launch_date_discovery") == "2026-12-03"
    assert row.get("planned_launch_date_scope") == "COMMISSION_PLAN_NOT_ACTUAL_CALL_OPENING"
    assert row.get("event_date_discovery") == "2026-11-17"
    assert row.get("readback_date_discovery") == "2026-11-18"
    assert not FORBIDDEN & row.keys(), "Unverified current call fact or forged immutable receipt"

    components = row.get("planned_component_envelopes_discovery")
    assert isinstance(components, list) and len(components) == 5
    seen, total = set(), 0
    for c in components:
        name = c.get("name")
        assert name in EXPECTED and name not in seen
        seen.add(name)
        expected_instrument, expected_budget = EXPECTED[name]
        assert c.get("instrument") == expected_instrument
        assert c.get("indicative_envelope_eur") == expected_budget
        assert c.get("observation_state") == "PLANNED"
        assert c.get("budget_scope") == "PLANNED_COMPONENT_NOT_LIVE_CALL"
        assert not FORBIDDEN_COMPONENT & c.keys(), "Component misrepresented as live exact call"
        total += expected_budget
    assert seen == set(EXPECTED) and total == 5_200_000_000
    assert "end-March and end-September 2027" in row.get("sme_cutoff_windows_discovery", "")
    note = row.get("note", "")
    for token in ("NOT_CAPTURED", "SURFACEMC", "OPEN_CALL", "LKG", "3 December", "PLANNED", "reconciled eligibility"):
        assert token in note, "Missing programming/receipt hold: " + token
    return row

def main():
    sources = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    validate(sources)
    attempts = [
        ("observation_state", "OPEN_CALL"),
        ("observation_state", "OPEN"),
        ("authority_scope", "EXACT_CALL"),
        ("open_call_authorized", True),
        ("material_fact_use", True),
        ("material_fact_publication_authorized", True),
        ("planned_launch_date_scope", "ACTUAL_CALL_OPEN"),
        ("planned_launch_date_discovery", "2026-11-17"),
        ("raw_sha256", "0" * 64),
        ("fetched_at", "2026-11-18T17:30:00Z"),
        ("parser_version", "fictitious"),
        ("topic_identifier", "IF26-MADE-UP"),
        ("deadline", "2027-03-31"),
        ("budget", 5_200_000_000),
    ]
    rejected = 0
    for key, value in attempts:
        trial = copy.deepcopy(sources)
        next(s for s in trial if s.get("id") == ID)[key] = value
        try:
            validate(trial)
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError("Unsafe top-level promotion: " + key)
    for key, value in [
        ("observation_state", "OPEN_CALL"),
        ("budget_scope", "LIVE_CALL_BUDGET"),
        ("indicative_envelope_eur", 5_000_000_000),
        ("call_identifier", "IF26-FAKE"),
        ("deadline", "2027-03-31"),
        ("application_endpoint", "https://example.invalid"),
    ]:
        trial = copy.deepcopy(sources)
        next(s for s in trial if s.get("id") == ID)["planned_component_envelopes_discovery"][0][key] = value
        try:
            validate(trial)
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError("Unsafe component promotion: " + key)
    trial = copy.deepcopy(sources)
    trial.append(copy.deepcopy(validate(sources)))
    try:
        validate(trial)
    except AssertionError:
        rejected += 1
    else:
        raise AssertionError("Duplicate official CINEA IF26 record accepted")
    print(json.dumps({
        "result": "PASS", "source_id": ID,
        "planned_component_count": 5,
        "indicative_total_eur": 5_200_000_000,
        "negative_mutations_rejected": rejected,
        "open_call_authorized": False, "publication_effect": "NONE",
    }))

if __name__ == "__main__":
    main()
