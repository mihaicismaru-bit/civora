#!/usr/bin/env python3
import importlib.util
import sys
from pathlib import Path
from urllib.error import HTTPError

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


def verified_readback(url, digest_char):
    body_sha = digest_char * 64
    attempt = {
        "attempt_index": 1,
        "fetched_at": FETCHED_AT,
        "outcome": "VERIFIED",
        "final_url": url,
        "http_status": 200,
        "content_type": "text/html",
        "bytes": 10,
        "body_sha256": body_sha,
        "retriable": False,
    }
    return {
        "url": url,
        "final_url": url,
        "http_status": 200,
        "content_type": "text/html",
        "bytes": 10,
        "body_sha256": body_sha,
        "verified": True,
        "attempt_count": 1,
        "attempts": [attempt],
        "recovery_state": "FIRST_ATTEMPT_HEALTHY",
    }


class FakeResponse:
    def __init__(self, url, *, status=200, content_type="text/html; charset=utf-8", body=b"topic"):
        self._url = url
        self.status = status
        self.headers = {"Content-Type": content_type}
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def geturl(self):
        return self._url

    def getcode(self):
        return self.status

    def read(self, limit=-1):
        return self._body if limit < 0 else self._body[:limit]


class SequenceOpener:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def open(self, req, timeout=None):
        self.calls += 1
        if not self.outcomes:
            raise AssertionError("unexpected extra topic readback attempt")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def http_error(url, status):
    return HTTPError(url, status, f"HTTP {status}", hdrs=None, fp=None)


def assert_topic_readback_retry_boundary():
    url = mod.topic_url(OPEN_ID)

    sleeps = []
    opener = SequenceOpener([http_error(url, 404), FakeResponse(url)])
    recovered = mod._topic_readback(url, opener=opener, sleeper=sleeps.append)
    assert_true(recovered["verified"] is True, "404->200 exact topic readback must recover within bounded retry")
    assert_true(recovered["attempt_count"] == 2, "recovered readback must preserve both attempts")
    assert_true(recovered["recovery_state"] == "RECOVERED_AFTER_TRANSIENT_FAILURE", "recovery state drift")
    assert_true(recovered["attempts"][0]["http_status"] == 404 and recovered["attempts"][0]["retriable"] is True, "initial 404 must remain in provenance")
    assert_true(recovered["attempts"][1]["outcome"] == "VERIFIED", "final recovery attempt must be explicit")
    assert_true(sleeps == [mod.TOPIC_READBACK_BACKOFF_SECONDS[0]], "bounded backoff drift")

    sleeps = []
    opener = SequenceOpener([http_error(url, 404), http_error(url, 404), http_error(url, 404)])
    exhausted = mod._topic_readback(url, opener=opener, sleeper=sleeps.append)
    assert_true(exhausted["verified"] is False, "exhausted transient readback must fail closed")
    assert_true(exhausted["failure_class"] == "TRANSIENT_READBACK_EXHAUSTED", "exhaustion failure class drift")
    assert_true(exhausted["attempt_count"] == 3, "all exhausted attempts must be preserved")
    assert_true([row["http_status"] for row in exhausted["attempts"]] == [404, 404, 404], "404 exhaustion provenance drift")
    assert_true(sleeps == list(mod.TOPIC_READBACK_BACKOFF_SECONDS), "exhaustion backoff drift")

    denied_opener = SequenceOpener([http_error(url, 403), FakeResponse(url)])
    denied = mod._topic_readback(url, opener=denied_opener, sleeper=lambda _: None)
    assert_true(denied["verified"] is False and denied["failure_class"] == "NON_RETRYABLE_READBACK_FAILURE", "non-retryable HTTP failure must remain fail closed")
    assert_true(denied_opener.calls == 1, "non-retryable HTTP failure must not be retried")

    drift_url = "https://example.com/not-authority/topic-details/" + OPEN_ID
    drift_opener = SequenceOpener([FakeResponse(drift_url), FakeResponse(url)])
    drift = mod._topic_readback(url, opener=drift_opener, sleeper=lambda _: None)
    assert_true(drift["verified"] is False and drift["failure_class"] == "AUTHORITY_OR_CONTENT_DRIFT", "authority/content drift must fail closed")
    assert_true(drift_opener.calls == 1, "authority/content drift must never be retried into success")


def main():
    assert_topic_readback_retry_boundary()

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
        OPEN_ID: verified_readback(open_url, "a"),
        UPCOMING_ID: verified_readback(upcoming_url, "b"),
        UNKNOWN_ID: verified_readback(unknown_url, "c"),
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

    print("PASS Funding & Tenders live boundary: bounded audited readback retries + Facet status + exact structured topic + exact topic page, zero publication")


if __name__ == "__main__":
    main()
