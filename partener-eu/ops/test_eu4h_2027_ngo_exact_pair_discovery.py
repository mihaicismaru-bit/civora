#!/usr/bin/env python3
"""HaDEA EU4Health 2027 NGO call: exact agency label + F&T shell != admitted OPEN."""
import copy
import json
from pathlib import Path
from urllib.parse import urlparse

REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
TOPIC = "EU4H-2027-SANTE-OG"
AGENCY_ID = "SRC-EU-HADEA-EU4H-2027-SANTE-OG-EXACT-CALL"
PORTAL_ID = "SRC-EU-FT-EU4H-2027-SANTE-OG-EXACT-TOPIC"
AGENCY_URL = "https://hadea.ec.europa.eu/calls-proposals/financial-contribution-functioning-health-non-governmental-organisations-implementing-one-or-more_en"
PORTAL_URL = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/" + TOPIC
FORBIDDEN = {
    "status", "current_status", "call_status", "application_endpoint",
    "exact_submission_endpoint", "deadline", "current_deadline",
    "budget", "budget_eur", "eligibility", "publish_authorized",
    "final_url", "fetched_at", "raw_sha256", "semantic_sha256",
    "parser_version", "run_id", "handoff_sha256",
}
REQUIRED = {
    "tier": "T1",
    "call_identifier_discovery": TOPIC,
    "programme_family": "EU_DIRECT / EU4HEALTH / 2027",
    "agency_publication_date_discovery": "2026-11-04",
    "agency_opening_date_discovery": "2026-11-04",
    "agency_deadline_discovery": "2027-01-19 17:00 CET (HaDEA page label, NOT canonical deadline)",
    "readback_date_discovery": "2026-11-19",
    "adapter_required": "EU4H_2027_SANTE_OG_HADEA_AND_FT_SURFACEMC_EXACT_TOPIC_RECONCILE_V1",
}
ENDPOINTS = {
    AGENCY_ID: (AGENCY_URL, "hadea.ec.europa.eu", "OFFICIAL_AGENCY_OPEN_LABEL_RAW_PENDING",
                "T1_OFFICIAL_EC_EXECUTIVE_AGENCY_HADEA"),
    PORTAL_ID: (PORTAL_URL, "ec.europa.eu", "EXACT_TOPIC_JS_SHELL_RAW_PENDING",
                "T1_OFFICIAL_EC_FUNDING_TENDERS"),
}

def validate(rows):
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids)), "duplicate source id"
    by_id = {row["id"]: row for row in rows}
    assert all(key in by_id for key in ENDPOINTS), "missing official pair"
    agency, portal = by_id[AGENCY_ID], by_id[PORTAL_ID]
    assert agency.get("linked_funding_tenders_topic_source_id") == PORTAL_ID
    assert portal.get("linked_hadea_agency_source_id") == AGENCY_ID
    for source_id, (url, hostname, state, authority) in ENDPOINTS.items():
        row = by_id[source_id]
        for key, expected in REQUIRED.items():
            assert row.get(key) == expected, (source_id, key)
        assert row.get("url") == url, (source_id, "url")
        p = urlparse(row["url"])
        assert p.scheme == "https" and p.hostname == hostname
        assert p.username is None and p.password is None and p.port is None
        assert row.get("observation_state") == state
        assert row.get("authority_class") == authority
        assert set(["EU_DIRECT", "BRUSSELS", "EU4HEALTH", "DISCOVERY"]) <= set(row.get("source_families") or [])
        assert "OPEN_CALL" not in row["source_families"]
        for flag in ("material_fact_use", "open_call_authorized",
                     "material_fact_publication_authorized", "credentials_required"):
            assert row.get(flag) is False, (source_id, flag)
        assert not FORBIDDEN.intersection(row), (source_id, "invented receipt/material field")
        note = row.get("note", "")
        for marker in ("NOT_CAPTURED" if source_id == PORTAL_ID else "NOT", "SURFACEMC",
                       "final_url", "fetched_at UTC", "raw_sha256",
                       "parser_version", "run_id", "LKG", "OPEN_CALL",
                       "NO MATERIAL PUBLICATION", "NO DISTRIBUTION"):
            assert marker in note, (source_id, marker)
    assert agency.get("agency_status_label_discovery", "").startswith("Open (")
    assert "CALL_DETAIL" in agency["source_families"]
    assert "CALL_REGISTRY" in portal["source_families"]
    assert portal.get("portal_readback_discovery", "").startswith("JS shell")
    assert agency.get("authority_scope") == "EXACT_CALL_AGENCY_PAGE_DISCOVERY_ONLY_NO_CURRENT_APPLICATION_RECEIPT"
    assert portal.get("authority_scope") == "EXACT_TOPIC_LINK_ONLY_JS_SHELL_NO_CURRENT_STATUS_OR_SUBMISSION_PROOF"
    assert "agency_lists_exact_call_identifier" in agency.get("extract", [])
    assert "no_current_exact_topic_submission_endpoint_raw_receipt" in portal.get("extract", [])

def main():
    sources = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    validate(sources)
    changes = [
        ("observation_state", "OPEN_CALL"),
        ("authority_scope", "CURRENT_OFFICIAL_OPEN_CALL"),
        ("open_call_authorized", True),
        ("material_fact_use", True),
        ("material_fact_publication_authorized", True),
        ("status", "OPEN"),
        ("deadline", "2027-01-19"),
        ("budget_eur", 1800000),
        ("eligibility", ["all NGOs"]),
        ("application_endpoint", "https://example.invalid/submit"),
        ("fetched_at", "2026-11-19T02:00:00Z"),
        ("raw_sha256", "0" * 64),
        ("parser_version", "invented"),
        ("call_identifier_discovery", "EU4H-FAKE"),
        ("agency_deadline_discovery", "2026-12-01"),
        ("url", "https://example.invalid/fake"),
    ]
    rejected = 0
    for source_id in ENDPOINTS:
        for key, value in changes:
            candidate = copy.deepcopy(sources)
            next(x for x in candidate if x["id"] == source_id)[key] = value
            try:
                validate(candidate)
            except AssertionError:
                rejected += 1
            else:
                raise AssertionError("unsafe EU4Health mutation accepted: " + source_id + "." + key)
        candidate = copy.deepcopy(sources)
        candidate.append(copy.deepcopy(next(x for x in sources if x["id"] == source_id)))
        try:
            validate(candidate)
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError("duplicate EU4Health source accepted")
    assert rejected == 34
    print(json.dumps({
        "result": "PASS", "topic": TOPIC,
        "source_ids": list(ENDPOINTS),
        "negative_mutations_rejected": rejected,
        "open_call_authorized": False, "publication_effect": "NONE",
    }))

if __name__ == "__main__":
    main()
