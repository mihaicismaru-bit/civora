#!/usr/bin/env python3
"""HaDEA 19-Nov-2026 market survey + tentative EU4Health procurement are NEVER an OPEN_CALL."""
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
SURVEY_ID = "SRC-EU-HADEA-EU4HEALTH-BIOTECH-MARKET-SURVEY-20261119"
CALENDAR_ID = "SRC-EU-HADEA-EU4HEALTH-BIOTECH-TENDER-CALENDAR-2027"
SURVEY_URL = "https://hadea.ec.europa.eu/news/eu-market-survey-help-shape-future-call-tenders-decentralised-manufacturing-biotech-medicinal-2026-11-19_en"
CALENDAR_URL = "https://hadea.ec.europa.eu/programmes/eu4health/calls-and-contracts/tentative-calendar_en"
FORBIDDEN = {
    "fetched_at", "final_url", "raw_sha256", "semantic_sha256", "parser_version",
    "run_id", "handoff_sha256", "status", "current_status", "call_status",
    "deadline", "application_deadline", "tender_deadline", "budget", "budget_eur",
    "eligibility", "call_identifier", "topic_identifier", "tender_identifier",
    "application_endpoint", "submission_endpoint", "exact_submission_endpoint",
}
REQUIRED = {"EU_DIRECT", "BRUSSELS", "EU4HEALTH", "FUTURE_PROCUREMENT",
            "MARKET_INTELLIGENCE", "DISCOVERY"}


def verify(sources):
    ids = [x["id"] for x in sources]
    assert len(ids) == len(set(ids)), "duplicate source identities"
    rows = {row["id"]: row for row in sources}
    assert SURVEY_ID in rows and CALENDAR_ID in rows
    survey, calendar = rows[SURVEY_ID], rows[CALENDAR_ID]
    for row, url in ((survey, SURVEY_URL), (calendar, CALENDAR_URL)):
        p = urlsplit(row["url"])
        assert row["url"] == url and p.scheme == "https" and p.hostname == "hadea.ec.europa.eu"
        assert p.username is None and p.password is None and p.port is None
        assert row.get("tier") == "T1" and row.get("programme_family") == "EU4HEALTH"
        assert REQUIRED <= set(row.get("source_families", []))
        assert "OPEN_CALL" not in row["source_families"]
        assert not FORBIDDEN.intersection(row), "unverified receipt or active call material fact"
        for key in ("material_fact_use", "open_call_authorized", "material_fact_publication_authorized",
                    "credentials_required"):
            assert row.get(key) is False, key
        assert row.get("readback_date_discovery") == "2026-11-19"
        assert "SURFACEMC" in row.get("note", "")
        assert "NOT_CAPTURED" in row["note"] and "LKG" in row["note"]
        assert "NO DISTRIBUTION" in row["note"]
    assert survey["authority_class"] == "T1_OFFICIAL_HADEA_MARKET_SURVEY"
    assert "PROGRAMMING_PIPELINE" not in survey["source_families"]
    assert survey["programmes"] == calendar["programmes"] == ["EU4Health — future procurement (biotech medicinal products)"]
    assert survey["authority_scope"] == "MARKET_SURVEY_FOR_POTENTIAL_FUTURE_TENDER_NOT_CALL_NOTICE"
    assert survey["observation_state"] == "FUTURE_TENDER_MARKET_SURVEY_DISCOVERED_RAW_PENDING"
    assert survey["source_publication_date_discovery"] == "2026-11-19"
    assert survey["survey_feedback_cutoff_discovery"] == "2026-12-11 (survey feedback, not tender deadline)"
    assert survey["linked_tentative_calendar_source_id"] == CALENDAR_ID
    assert survey["survey_access_note_discovery"] == "EU Login required for survey"
    assert "CONSULTATION" in survey["source_families"]
    assert calendar["authority_class"] == "T1_OFFICIAL_HADEA_PROGRAMMING_CALENDAR"
    assert calendar["authority_scope"] == "PROGRAMMING_FRAMEWORK"
    assert "PROGRAMMING_PIPELINE" in calendar["source_families"]
    assert calendar["observation_state"] == "PROGRAMMING_PIPELINE"
    assert calendar["tentative_awp_action_code_discovery"] == "HS-p-26-52"
    assert calendar["tentative_publication_period_discovery"] == "Q1 2027 (indicative, subject to change)"
    assert calendar["indicative_planning_envelope_eur_discovery"] == 3000000
    assert "PLANNED" in calendar["source_families"]
    assert "survey" not in calendar["authority_scope"].lower()


def main():
    sources = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    verify(sources)
    mutations = [
        (SURVEY_ID, "observation_state", "OPEN_CALL"),
        (CALENDAR_ID, "observation_state", "OPEN_CALL"),
        (SURVEY_ID, "open_call_authorized", True),
        (CALENDAR_ID, "material_fact_use", True),
        (SURVEY_ID, "material_fact_publication_authorized", True),
        (CALENDAR_ID, "material_fact_publication_authorized", True),
        (SURVEY_ID, "deadline", "2026-12-11"),
        (SURVEY_ID, "application_endpoint", "https://example.invalid"),
        (CALENDAR_ID, "submission_endpoint", "https://example.invalid"),
        (CALENDAR_ID, "budget_eur", 3000000),
        (SURVEY_ID, "raw_sha256", "0" * 64),
        (CALENDAR_ID, "fetched_at", "2026-11-19T00:00:00Z"),
        (SURVEY_ID, "parser_version", "fabricated"),
        (CALENDAR_ID, "run_id", "fabricated"),
        (SURVEY_ID, "authority_scope", "CURRENT_CALL"),
        (CALENDAR_ID, "authority_scope", "CURRENT_TENDER"),
        (SURVEY_ID, "survey_feedback_cutoff_discovery", "2027-01-01"),
        (CALENDAR_ID, "tentative_awp_action_code_discovery", "FAKE"),
        (SURVEY_ID, "linked_tentative_calendar_source_id", "SRC-FAKE"),
        (CALENDAR_ID, "tentative_publication_period_discovery", "OPEN NOW"),
        (SURVEY_ID, "url", "https://example.invalid"),
        (CALENDAR_ID, "url", "http://hadea.ec.europa.eu"),
    ]
    denied = 0
    for source_id, key, value in mutations:
        altered = copy.deepcopy(sources)
        next(row for row in altered if row["id"] == source_id)[key] = value
        try:
            verify(altered)
        except AssertionError:
            denied += 1
        else:
            raise AssertionError(f"Unsafe HaDEA survey/calendar promotion admitted: {source_id}.{key}")
    duplicate = copy.deepcopy(sources)
    duplicate.append(copy.deepcopy(next(row for row in sources if row["id"] == SURVEY_ID)))
    try:
        verify(duplicate)
    except AssertionError:
        denied += 1
    else:
        raise AssertionError("Duplicate HaDEA survey source accepted")
    assert denied == 23
    print(json.dumps({"result": "PASS", "source_ids": [SURVEY_ID, CALENDAR_ID],
                      "negative_mutations_rejected": denied, "open_call_authorized": False,
                      "publication_effect": "NONE"}))


if __name__ == "__main__":
    main()
