#!/usr/bin/env python3
"""An Erasmus exact-call OPEN label is not an immutable, reconciled application receipt."""
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit

FILE = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
IDENT = "SRC-EU-ERASMUS-EAC-S13-2026-LITERACY-COALITION-20261119"
URL = "https://erasmus-plus.ec.europa.eu/funding-opportunities/european-literacy-coalition-consortium-fpa-sga"
FORBIDDEN = {
    "status", "current_status", "call_status", "deadline", "submission_deadline",
    "application_deadline", "budget", "budget_eur", "eligibility",
    "submission_endpoint", "application_endpoint", "exact_submission_endpoint",
    "final_url", "fetched_at", "raw_sha256", "semantic_sha256",
    "parser_version", "run_id", "handoff_sha256"
}

def validate(rows):
    assert len(rows) == len({x["id"] for x in rows}), "duplicate source IDs"
    row = next(x for x in rows if x["id"] == IDENT)
    assert row["tier"] == "T1"
    assert row["url"] == URL
    assert row["call_identifier_discovery"] == "EAC/S13/2026"
    assert row["programme_family"] == "Erasmus+ / European Literacy Coalition / 2026"
    assert row["authority_class"] == "T1_OFFICIAL_EC_DG_EAC_ERASMUS_EXACT_CALL_PAGE"
    assert row["authority_scope"] == "EXACT_CALL_OPEN_LABEL_NOT_RECONCILED_SUBMISSION_ENDPOINT"
    assert row["observation_state"] == "EXACT_CALL_OPEN_LABEL_DISCOVERED_RAW_PENDING"
    assert row["readback_date_discovery"] == "2026-11-19"
    assert row["historical_opening_label_discovery"] == "22 September 2026 09:00 CEST (official label only)"
    assert row["deadline_label_discovery"] == "23 November 2026 17:00 CET (official label, NOT admitted)"
    assert row["linked_official_listing_url_discovery"] == "https://erasmus-plus.ec.europa.eu/funding-calls"
    assert row["linked_official_call_document_page_discovery"] == (
        "https://erasmus-plus.ec.europa.eu/resources-and-tools/documents-and-guidelines/"
        "eacs132026-european-literacy-coalition-consortium-fpa-sga"
    )
    for key in ("url", "linked_official_listing_url_discovery", "linked_official_call_document_page_discovery"):
        parsed = urlsplit(row[key])
        assert parsed.scheme == "https" and parsed.hostname == "erasmus-plus.ec.europa.eu"
        assert not (parsed.username or parsed.password or parsed.port or parsed.fragment or parsed.query)
    assert {"EU_DIRECT", "BRUSSELS", "ERASMUS_PLUS", "CALL_REGISTRY", "DISCOVERY"} <= set(row["source_families"])
    assert not {"OPEN_CALL", "CLOSED_CALL", "PROGRAMMING_PIPELINE"} & set(row["source_families"])
    assert not FORBIDDEN.intersection(row), "synthetic material fact/provenance admitted"
    for flag in ("material_fact_use", "credentials_required", "open_call_authorized", "material_fact_publication_authorized"):
        assert row.get(flag) is False, ("unsafe material permission", flag)
    for marker in (
        "EAC/S13/2026", "23 November 2026", "17:00 CET", "NOT an application endpoint",
        "SURFACEMC", "NOT_CAPTURED", "fetched_at UTC", "raw_sha256", "semantic_sha256",
        "parser_version", "run_id", "handoff_sha256", "LKG", "OPEN_CALL",
        "NO DISTRIBUTION", "NO ALERT"
    ):
        assert marker in row["note"], ("lost gate", marker)
    for marker in (
        "exact_official_call_page_open_label_not_a_current_submission_receipt",
        "official_listing_same_identifier_and_deadline_label",
        "application_route_and_call_document_originals_not_acquired",
        "NO_BUDGET_ELIGIBILITY_OR_STATUS_ADMISSION"
    ):
        assert marker in row["extract"], ("lost discovery", marker)

def main():
    rows = json.loads(FILE.read_text(encoding="utf-8"))["sources"]
    validate(rows)
    muts = [
        ("observation_state", "OPEN_CALL"), ("authority_scope", "EXACT_LIVE_OPEN"),
        ("open_call_authorized", True), ("material_fact_use", True),
        ("material_fact_publication_authorized", True), ("credentials_required", True),
        ("call_identifier_discovery", "EAC/S14/2026"),
        ("deadline_label_discovery", "24 November 2026"),
        ("historical_opening_label_discovery", "22 September 2027"),
        ("url", "https://example.invalid/fake"), ("linked_official_listing_url_discovery", "https://example.invalid"),
        ("budget_eur", 1000000), ("deadline", "2026-11-23"),
        ("submission_endpoint", "https://example.invalid/apply"),
        ("status", "OPEN_CALL"), ("eligibility", "all EU NGOs"),
        ("fetched_at", "2026-11-19T15:30:00Z"),
        ("raw_sha256", "0" * 64), ("semantic_sha256", "0" * 64),
        ("parser_version", "guess-v1"), ("run_id", "invented"),
        ("handoff_sha256", "0" * 64)
    ]
    rejected = 0
    for field, value in muts:
        changed = copy.deepcopy(rows)
        next(x for x in changed if x["id"] == IDENT)[field] = value
        try:
            validate(changed)
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError("Unsafe literacy-call mutation accepted: " + field)
    changed = copy.deepcopy(rows)
    changed.append(copy.deepcopy(next(x for x in changed if x["id"] == IDENT)))
    try:
        validate(changed)
    except AssertionError:
        rejected += 1
    else:
        raise AssertionError("Duplicate literacy-call source accepted")
    assert rejected == 23, rejected
    print(json.dumps({"result": "PASS", "source": IDENT, "negative_mutations_rejected": rejected,
                      "open_call_authorized": False, "publication_effect": "NONE"}))

if __name__ == "__main__":
    main()
