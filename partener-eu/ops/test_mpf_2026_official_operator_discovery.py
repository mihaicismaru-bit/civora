#!/usr/bin/env python3
"""MPF 2026: official operator call labels are discovery, not canonical OPEN."""
import copy
import json
from pathlib import Path
from urllib.parse import urlparse

REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
BASE = "https://www.migrationpartnershipfacility.eu/calls-for-proposals"
PREFIX = "SRC-EU-MPF-2026-"
DATA = {
    "OFFICIAL-OPERATOR-INDEX": (BASE, "CALL_INDEX", None, None),
    "MIGRATION-PARTNERSHIPS-OPERATOR": (BASE + "/cfp2026-mps", "CALL_DETAIL", "AMIF", 6000000),
    "BORDER-MANAGEMENT-OPERATOR": (BASE + "/cfp2026-bm", "CALL_DETAIL", "BMVI", 5000000),
    "INTERNAL-SECURITY-OPERATOR": (BASE + "/cfp2026-is", "CALL_DETAIL", "ISF", 3000000),
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
    matches = [r for r in rows if r.get("id", "").startswith(PREFIX)]
    assert len(matches) == 4, "MPF 2026 operator discovery must have exactly four rows"
    for suffix, (url, kind, instrument, envelope) in DATA.items():
        ident = PREFIX + suffix
        selected = [r for r in matches if r.get("id") == ident]
        assert len(selected) == 1, "Missing/duplicate MPF source: " + ident
        row = selected[0]
        assert row.get("url") == url, "Operator URL changed"
        parsed = urlparse(url)
        assert parsed.scheme == "https" and parsed.hostname == "www.migrationpartnershipfacility.eu"
        assert parsed.username is None and parsed.password is None and parsed.port is None
        assert row.get("tier") == "T1"
        assert row.get("authority_class") == "T1_OFFICIAL_MPF_PROGRAMME_OPERATOR_ICMPD"
        assert row.get("programme_family") == "EU_DIRECT / DG_HOME / Migration Partnership Facility / 2026"
        assert row.get("readback_date_discovery") == "2026-11-19"
        assert row.get("operator_index_launch_date_discovery") == "2026-07-13"
        assert row.get("operator_index_rolling_until_funds_exhausted_discovery") is True
        assert set(("EU_DIRECT", "BRUSSELS", "DG_HOME", "OFFICIAL_PROGRAMME_OPERATOR", "DISCOVERY", kind)) <= set(row.get("source_families") or [])
        assert "OPEN_CALL" not in (row.get("source_families") or [])
        if instrument:
            assert row.get("funding_instrument_discovery") == instrument
            assert row.get("operator_announced_financial_envelope_eur_discovery") == envelope
            assert row.get("operator_page_slug_discovery") == url.rsplit("/", 1)[-1]
            assert row.get("observation_state") == "OFFICIAL_OPERATOR_SPECIFIC_CALL_PAGE_DISCOVERED_RAW_PENDING"
            assert row.get("authority_scope") == "SPECIFIC_CALL_OVERVIEW_PUBLIC_LABEL_DISCOVERY_ONLY_NO_CURRENT_APPLICATION_RECEIPT"
            assert row.get("linked_operator_index_source_id") == PREFIX + "OFFICIAL-OPERATOR-INDEX"
            assert row.get("submission_portal_generic_login_url_discovery") == "https://icmpd.eu-1.smartsimple.eu/s_Login.jsp"
        else:
            assert row.get("observation_state") == "OFFICIAL_OPERATOR_CALL_INDEX_DISCOVERED_RAW_PENDING"
            assert row.get("authority_scope") == "OFFICIAL_OPERATOR_CALL_INDEX_DISCOVERY_ONLY_NOT_EXACT_GATEWAY"
            assert row.get("operator_index_call_count_discovery") == 3
            assert sorted(row.get("linked_specific_source_ids") or []) == sorted(PREFIX + x for x in DATA if x != suffix)
        assert row.get("open_call_authorized") is False
        assert row.get("material_fact_use") is False
        assert row.get("material_fact_publication_authorized") is False
        assert row.get("credentials_required") is False
        assert not FORBIDDEN & row.keys(), "Invented official immutable receipt or canonical call facts"
        note = row.get("note") or ""
        for token in ("19 November 2026", "13 July 2026", "NOT_CAPTURED", "SURFACEMC",
                      "final_url", "fetched_at UTC", "raw_sha256", "parser_version",
                      "run_id", "OPEN_CALL", "LKG", "distribution"):
            assert token.lower() in note.lower(), "Lost evidence hold: " + token

def main():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    validate(rows)
    sample = next(r for r in rows if r.get("id") == PREFIX + "BORDER-MANAGEMENT-OPERATOR")
    changes = [
        ("observation_state", "OPEN_CALL"),
        ("authority_scope", "CURRENT_EXACT_OPEN_CALL"),
        ("authority_class", "T3_MEDIA"),
        ("tier", "T2"),
        ("url", "https://example.invalid/fake"),
        ("readback_date_discovery", "2026-11-18"),
        ("operator_index_launch_date_discovery", "2026-11-19"),
        ("operator_index_rolling_until_funds_exhausted_discovery", False),
        ("funding_instrument_discovery", "ISF"),
        ("operator_page_slug_discovery", "cfp2026-is"),
        ("operator_announced_financial_envelope_eur_discovery", 100000000),
        ("submission_portal_generic_login_url_discovery", "https://example.invalid/apply"),
        ("open_call_authorized", True),
        ("material_fact_use", True),
        ("material_fact_publication_authorized", True),
        ("status", "OPEN"),
        ("call_identifier", "MPF-2026-BM"),
        ("deadline", "2026-11-27"),
        ("budget_eur", 5000000),
        ("eligibility", ["all private firms"]),
        ("application_endpoint", "https://example.invalid/submit"),
        ("final_url", sample["url"]),
        ("fetched_at", "2026-11-19T00:00:00Z"),
        ("raw_sha256", "0" * 64),
        ("parser_version", "invented"),
        ("run_id", "invented"),
        ("handoff_sha256", "0" * 64),
    ]
    rejected = 0
    for key, val in changes:
        trial = copy.deepcopy(rows)
        next(r for r in trial if r.get("id") == sample["id"])[key] = val
        try:
            validate(trial)
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError("Unsafe operator call state/receipt admitted: " + key)
    duplicate = copy.deepcopy(rows)
    duplicate.append(copy.deepcopy(sample))
    try:
        validate(duplicate)
    except AssertionError:
        rejected += 1
    else:
        raise AssertionError("Duplicate operator call source admitted")
    print(json.dumps({"result":"PASS", "operator_sources":4,
                      "negative_mutations_rejected":rejected, "open_call_authorized":False,
                      "publication_effect":"NONE"}))

if __name__ == "__main__":
    main()
