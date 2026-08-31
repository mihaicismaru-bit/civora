#!/usr/bin/env python3
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INGEST = ROOT / "partener-eu" / "ingest"
sys.path.insert(0, str(INGEST))
MODULE_PATH = INGEST / "funding_tenders_fetch.py"
spec = importlib.util.spec_from_file_location("funding_tenders_fetch", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

FETCHED_AT = "2026-08-28T00:00:00+00:00"
RUN_ID = "fixture-ft-live-001"
OPEN_ID = "HORIZON-TEST-2026-OPEN-01"
UPCOMING_ID = "DIGITAL-TEST-2026-UPCOMING-01"
UNKNOWN_ID = "LIFE-TEST-2026-UNKNOWN-01"


def assert_true(value, message):
    if not value:
        raise AssertionError(message)


def structured_receipt(identifier, status_code, *, call_identifier=None, verified=True):
    return {
        "identifier": identifier,
        "query_text": f'"{identifier}"',
        "api_url": f"{mod.SEARCH_ENDPOINT}?apiKey=SEDIA&text=%22{identifier}%22&pageSize=10&pageNumber=1",
        "http_status": 200,
        "content_type": "application/json",
        "bytes": 1234,
        "raw_sha256": "f" * 64,
        "matched_identifiers": [identifier],
        "exact_match_count": 1,
        "status_codes": [status_code],
        "call_identifiers": [call_identifier] if call_identifier else [],
        "raw_types": ["1"],
        "verified": verified,
    }


def main():
    query = mod.default_query()
    terms = query["bool"]["must"]
    assert_true({"terms": {"status": ["31094501", "31094502"]}} in terms, "live search must remain bounded to official status codes of interest")
    assert_true({"term": {"programmePeriod": "2021 - 2027"}} in terms, "live query period drift")

    body, content_type = mod._multipart_json({"query": query, "languages": ["en"]})
    assert_true(content_type.startswith("multipart/form-data; boundary="), "Search API request must use multipart/form-data")
    assert_true(b'name="query"; filename="blob"' in body and b"Content-Type: application/json" in body, "query part must be an application/json file part")

    search_payload = {
        "results": [
            {
                "metadata": {
                    "identifier": [OPEN_ID],
                    "callIdentifier": ["HORIZON-TEST-2026"],
                    "status": ["31094502"],
                    "programAbbreviation": ["HORIZON"],
                    "programmePeriod": ["2021 - 2027"],
                    "deadlineDate": ["2026-12-01"],
                    "budget": ["1000000"],
                },
                "content": "Open fixture topic",
                "url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/old-wrapper-value",
            },
            {
                "metadata": {
                    "identifier": [UPCOMING_ID],
                    "status": ["31094501"],
                    "programAbbreviation": ["DIGITAL"],
                    "programmePeriod": ["2021 - 2027"],
                },
                "content": "Forthcoming fixture topic",
            },
            {
                "metadata": {
                    "identifier": [UNKNOWN_ID],
                    "status": ["99999999"],
                    "programAbbreviation": ["LIFE"],
                    "programmePeriod": ["2021 - 2027"],
                },
                "content": "Unresolved reference fixture",
            },
        ]
    }

    flat = mod.flatten_search_payload(search_payload)
    assert_true(len(flat) == 3, "corporate Search wrapper should flatten to three records")
    assert_true(flat[0]["identifier"] == [OPEN_ID] and flat[0]["title"] == "Open fixture topic", "Search wrapper metadata/content binding drift")

    # Mirrors the observed official Facet payload shape: rawValue holds the
    # reference code and value holds the human-readable Commission label.
    facet_payloads = {
        "broad": {
            "facets": [{
                "name": "status",
                "values": [
                    {"count": 2, "rawValue": "31094502", "value": "Open for submission"},
                    {"count": 1, "rawValue": "31094501", "value": "Forthcoming"},
                ],
            }]
        }
    }
    assert_true(mod.resolve_reference_label(facet_payloads.values(), "31094502") == "Open", "OPEN label must be resolved from official rawValue/value Facet evidence")
    assert_true(mod.resolve_reference_label(facet_payloads.values(), "31094501") == "Forthcoming", "forthcoming label must be resolved from official rawValue/value Facet evidence")
    assert_true(mod.resolve_reference_label(facet_payloads.values(), "99999999") is None, "unknown reference code must not be guessed")

    open_url = mod.topic_url(OPEN_ID)
    upcoming_url = mod.topic_url(UPCOMING_ID)
    unknown_url = mod.topic_url(UNKNOWN_ID)
    assert_true(open_url.endswith(OPEN_ID), "topic URL should bind exact identifier")

    readbacks = {
        OPEN_ID: {"url": open_url, "final_url": open_url, "http_status": 200, "verified": True, "body_sha256": "a" * 64},
        UPCOMING_ID: {"url": upcoming_url, "final_url": upcoming_url, "http_status": 200, "verified": True, "body_sha256": "b" * 64},
        UNKNOWN_ID: {"url": unknown_url, "final_url": unknown_url, "http_status": 200, "verified": True, "body_sha256": "c" * 64},
    }
    structured = {
        OPEN_ID: structured_receipt(OPEN_ID, "31094502", call_identifier="HORIZON-TEST-2026"),
        UPCOMING_ID: structured_receipt(UPCOMING_ID, "31094501"),
        UNKNOWN_ID: structured_receipt(UNKNOWN_ID, "99999999"),
    }
    assert_true(mod._structured_receipt_confirms_record(flat[0], structured[OPEN_ID]), "exact structured topic readback should confirm matching identifier/status/call")

    evidence = mod.assemble_evidence(
        search_payload,
        facet_payloads,
        fetched_at=FETCHED_AT,
        run_id=RUN_ID,
        search_receipt={"url": mod.SEARCH_ENDPOINT, "http_status": 200, "sha256": "d" * 64},
        facet_receipts={"broad": {"url": mod.FACET_ENDPOINT, "http_status": 200, "sha256": "e" * 64}},
        readbacks=readbacks,
        structured_readbacks=structured,
    )
    mod.validate_live_evidence(evidence)
    rows = {row["identifier"]: row for row in evidence["batch"]["records"]}
    assert_true(rows[OPEN_ID]["observation_state"] == "OPEN_CALL", "official Facet OPEN plus exact structured+page readback should classify OPEN_CALL")
    assert_true(rows[UPCOMING_ID]["observation_state"] == "FORTHCOMING_CALL", "official Facet forthcoming must remain distinct")
    assert_true(rows[UNKNOWN_ID]["observation_state"] == "UNKNOWN", "unresolved status code must fail closed despite successful exact readbacks")
    assert_true(evidence["stats"]["unresolved_status_codes"] == ["99999999"], "unresolved status evidence must be explicit")
    assert_true(evidence["stats"]["verified_structured_topic_readbacks"] == 3, "structured topic readback stats drift")
    assert_true(evidence["publication_effect"] == "NONE" and evidence["canonical_corpus_mutation"] is False, "live fetch must remain non-publishing")
    assert_true(all(row["publish_authorized"] is False and row["material_fact_use"] is False for row in rows.values()), "no live record may self-authorize publication")

    # HTML 200 alone is not enough. If the exact structured status disagrees,
    # the topic cannot be marked authority-url-verified and therefore cannot OPEN.
    mismatched_structured = dict(structured)
    mismatched_structured[OPEN_ID] = structured_receipt(OPEN_ID, "31094501", call_identifier="HORIZON-TEST-2026")
    mismatch = mod.assemble_evidence(
        search_payload,
        facet_payloads,
        fetched_at=FETCHED_AT,
        run_id=RUN_ID,
        search_receipt={"url": mod.SEARCH_ENDPOINT, "http_status": 200, "sha256": "d" * 64},
        facet_receipts={"broad": {"url": mod.FACET_ENDPOINT, "http_status": 200, "sha256": "e" * 64}},
        readbacks=readbacks,
        structured_readbacks=mismatched_structured,
    )
    mismatch_rows = {row["identifier"]: row for row in mismatch["batch"]["records"]}
    assert_true(mismatch_rows[OPEN_ID]["authority_url_verified"] is False, "structured status mismatch must remove authority verification")
    assert_true(mismatch_rows[OPEN_ID]["observation_state"] == "UNKNOWN", "structured status mismatch must fail closed instead of OPEN")

    pipeline = dict(flat[0])
    pipeline["statusLabel"] = "Open"
    pipeline["observationState"] = "PROPOSAL"
    pipeline["authorityUrl"] = open_url
    from funding_tenders_api import normalize_payload
    planned = normalize_payload([pipeline], fetched_at=FETCHED_AT, run_id=RUN_ID, verified_authority_urls=[open_url])
    assert_true(planned["records"][0]["observation_state"] == "PROGRAMMING_PIPELINE", "proposal/programming record must never become OPEN_CALL")

    print("PASS Funding & Tenders live boundary: Facet status + exact structured topic + exact topic page, zero publication")


if __name__ == "__main__":
    main()
