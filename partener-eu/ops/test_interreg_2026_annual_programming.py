#!/usr/bin/env python3
"""Keep Interact post-2027 programming event intelligence non-authorizing.

This validates source registry semantics only; it does NOT claim a live
authoritative raw receipt or authorize programme/call publication.
"""
import copy
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "partener-eu/ingest/source_registry.json"
PLANE = ROOT / "partener-eu/ingest/data_plane_contract.json"
SOURCE_ID = "SRC-INTERREG-ANNUAL-EVENT-2026-POST2027-INTERACT"
SOURCE_URL = (
    "https://interreg.eu/news-stories/"
    "interreg-community-discusses-the-future-of-cooperation-beyond-2027/"
)
REQUIRED_FAMILIES = {"INTERREG", "PROGRAMMING_PIPELINE", "MULTI_PROGRAMME", "DISCOVERY"}
FALSE_FLAGS = ("material_fact_use", "credentials_required", "open_call_authorized",
               "material_fact_publication_authorized")
FORBIDDEN = {
    "status", "call_status", "deadline", "application_deadline", "budget",
    "budget_eur", "eligibility", "exact_call_identifier", "exact_topic_identifier",
    "submission_endpoint", "fetched_at", "final_url", "raw_sha256",
    "semantic_sha256", "parser_version", "run_id", "handoff_sha256",
}


def validate(rows, domains):
    matches = [item for item in rows if item.get("id") == SOURCE_ID]
    assert len(matches) == 1, "Missing or duplicate Interact event report"
    row = matches[0]
    assert row["url"] == SOURCE_URL
    assert urlparse(row["url"]).hostname == "interreg.eu"
    assert row["tier"] == "T2"
    assert row["authority_class"] == "T2_OFFICIAL_INTERACT_PROGRAMMING_INTELLIGENCE_NOT_MA_CALL_AUTHORITY"
    assert row["authority_scope"] == "PROGRAMMING_FRAMEWORK"
    assert row["observation_state"] == "PROGRAMMING_PIPELINE"
    assert row["event_dates_discovery"] == ["2026-11-12", "2026-11-13"]
    assert row["report_publication_date_discovery"] == "2026-11-17"
    assert row["orientation_papers_count_discovery"] == 85
    assert row["programmes"] == ["Interreg cross-programme 2028-2034"]
    assert set(domains.get("Interreg cross-programme 2028-2034", [])) == {"INTERREG_CROSS_PROGRAMME", "PROGRAMMING_FUTURE"}
    assert REQUIRED_FAMILIES.issubset(set(row["source_families"]))
    assert "post-2027" in row["programme_family"]
    for field in FALSE_FLAGS:
        assert row[field] is False, "Unsafe programming promotion: " + field
    assert not FORBIDDEN.intersection(row), "Forged raw receipt or call fact"
    note = row["note"]
    for marker in ("85 Cooperation Orientation Papers", "SECONDARY T2",
                   "NOT_CAPTURED", "SURFACEMC", "Commission",
                   "NOT an adopted", "OPEN_CALL", "application deadline",
                   "semantic reconciliation"):
        assert marker in note, "Lost authority/provenance hold: " + marker


def main():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    domains = json.loads(PLANE.read_text(encoding="utf-8"))["programmeDomains"]
    validate(rows, domains)

    mutations = {
        "tier": "T1",
        "url": "https://example.com/fictional-interreg-call",
        "observation_state": "OPEN_CALL",
        "authority_scope": "CALL_APPLICATION_AUTHORITY",
        "orientation_papers_count_discovery": 84,
        "event_dates_discovery": ["2026-11-17"],
        "report_publication_date_discovery": "2026-11-18",
        "programmes": ["Interreg Europe 2021-2027"],
        "source_families": ["INTERREG"],
        "material_fact_use": True,
        "open_call_authorized": True,
        "material_fact_publication_authorized": True,
        "deadline": "2027-01-01",
        "budget_eur": 85000000,
        "eligibility": ["all Romanian organisations"],
        "exact_call_identifier": "INTERREG-2028-FAKE",
        "fetched_at": "2026-11-18T03:00:00Z",
        "raw_sha256": "0" * 64,
        "run_id": "fabricated",
    }
    rejected = 0
    for field, value in mutations.items():
        mutant = copy.deepcopy(rows)
        next(x for x in mutant if x["id"] == SOURCE_ID)[field] = value
        try:
            validate(mutant, domains)
        except (AssertionError, KeyError):
            rejected += 1
        else:
            raise AssertionError("Unsafe Interact programming mutation admitted: " + field)
    for altered in (rows + [copy.deepcopy(next(x for x in rows if x["id"] == SOURCE_ID))],
                    [x for x in rows if x["id"] != SOURCE_ID]):
        try:
            validate(altered, domains)
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError("Duplicate or missing source accepted")
    assert rejected == len(mutations) + 2
    print(json.dumps({
        "result": "PASS",
        "negative_mutations_rejected": rejected,
        "stage": "PROGRAMMING_PIPELINE_DISCOVERY_ONLY",
        "open_call_authorized": False,
        "publication_effect": "NONE",
        "raw_receipt": "NOT_CAPTURED",
    }))


if __name__ == "__main__":
    main()
