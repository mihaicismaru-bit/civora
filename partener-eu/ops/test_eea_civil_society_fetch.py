#!/usr/bin/env python3
import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ingest" / "eea_civil_society_fetch.py"
spec = importlib.util.spec_from_file_location("eea_csf_fetch", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)

INDEX = "https://eeagrants.org/en/eea-civil-society-fund-romania/calls"
CALL1 = "https://eeagrants.org/en/eea-civil-society-fund-romania/calls/call-1-strengthening-democracy-and-rule-law-through-civil-society-initiatives"
CALL2 = "https://eeagrants.org/en/eea-civil-society-fund-romania/calls/call-2-empowering-civic-participation-underserved-communities"
FETCHED = "2026-08-27T17:00:00+00:00"

INDEX_HTML = f"""
<html><body>
<a href="/en/eea-civil-society-fund-romania/calls/call-2-empowering-civic-participation-underserved-communities">Call 2</a>
<a href="{CALL1}">Call 1</a>
<a href="/ro/eea-civil-society-fund-romania/calls/call-1-strengthening-democracy-and-rule-law-through-civil-society-initiatives">Apel 1 duplicate language</a>
<a href="https://example.org/calls/999">Third party</a>
</body></html>
""".encode()

CALL1_HTML = b"""
<html><body>
<h1>Call #1 Strengthening Democracy and Rule of Law through Civil Society Initiatives</h1>
<div>Call for projects</div><div>Open</div>
<div>Submission Deadline:</div><div>08/10/2026</div>
<h2>Eligible Applicants</h2>
<p>Eligible Applicants are non-governmental and non-profit organizations, legally established in Romania.</p>
<h2>Call details</h2>
<div>Call number</div><div>1</div>
<div>Publication date</div><div>08/07/2026</div>
<div>Questions deadline date</div><div>29/09/2026</div>
<div>Submission Deadline</div><div>08/10/2026</div>
<div>Amount available</div><div>&euro;3,718,664</div>
<div>Grant amount from</div><div>&euro;200,001</div>
<div>Grant amount to</div><div>&euro;350,000</div>
</body></html>
"""

CALL2_HTML = b"""
<html><body>
<h1>Call #2 Empowering Civic Participation in Underserved Communities</h1>
<div>Call for projects</div><div>Open</div>
<div>Submission Deadline:</div><div>08/10/2026</div>
<h2>Eligible Applicants</h2>
<p>Eligible Applicants are non-governmental and non-profit organizations, legally established in Romania.</p>
<h2>Call details</h2>
<div>Call number</div><div>2</div>
<div>Publication date</div><div>08/07/2026</div>
<div>Questions deadline date</div><div>29/09/2026</div>
<div>Submission Deadline</div><div>08/10/2026</div>
<div>Amount available</div><div>&euro;4,500,000</div>
<div>Grant amount from</div><div>&euro;15,000</div>
<div>Grant amount to</div><div>&euro;350,000</div>
</body></html>
"""


def fail(message):
    raise SystemExit(f"FAIL: {message}")


def response(url, raw, final_url=None):
    return {
        "requested_url": url,
        "final_url": final_url or url,
        "status": 200,
        "content_type": "text/html; charset=utf-8",
        "raw": raw,
    }


def fake_fetch(url):
    if url == INDEX:
        return response(url, INDEX_HTML)
    if url == CALL1:
        return response(url, CALL1_HTML)
    if url == CALL2:
        return response(url, CALL2_HTML)
    raise AssertionError(f"unexpected URL {url}")


def test_transport_integrity():
    """Transport and raw-byte evidence tests are hermetic: never contact a live host."""
    from urllib.request import Request

    allowed_alias = CALL1.replace("https://eeagrants.org/", "https://www.eeagrants.org/")
    if module._same_official_endpoint(CALL1, allowed_alias + "/") != allowed_alias:
        fail("official same-endpoint www/trailing-slash alias must remain supported")

    redirect = module._RegisteredEEARedirect(CALL1)
    if redirect.redirect_request(Request(CALL1), None, 302, "Moved", {}, allowed_alias) is None:
        fail("same-owner same-article redirect was unexpectedly rejected")
    for bad in (
        "http://eeagrants.org/en/eea-civil-society-fund-romania/calls/" + CALL1.rsplit("/", 1)[-1],
        "https://example.org/collect",
        CALL2,
        CALL1 + "?tracking=1",
        "https://www.eeagrants.org/en/eea-civil-society-fund-romania/calls",
    ):
        try:
            redirect.redirect_request(Request(CALL1), None, 302, "Moved", {}, bad)
        except ValueError:
            pass
        else:
            fail(f"redirect hop crossed exact official source before fetch: {bad}")

    class RawResponse:
        def __init__(self, body, *, final_url=CALL1, status=200, content_type="text/html", **headers):
            self.body = body
            self.final_url = final_url
            self.status = status
            self.headers = {"Content-Type": content_type, **headers}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def getcode(self):
            return self.status
        def geturl(self):
            return self.final_url
        def read(self, size):
            return self.body[:size]

    original_open = module._open_registered_source
    def attempt(reply):
        module._open_registered_source = lambda request, *, timeout: reply
        try:
            return module.fetch_url(CALL1)
        finally:
            module._open_registered_source = original_open

    raw = CALL1_HTML
    good = attempt(RawResponse(raw, **{"Content-Length": str(len(raw))}))
    if good["raw"] != raw or good["status"] != 200 or good["final_url"] != CALL1:
        fail("valid complete EEA HTTPS raw reply must remain byte-identical")
    for bad, label in (
        (RawResponse(raw[:50], **{"Content-Length": str(len(raw))}), "truncated"),
        (RawResponse(raw, **{"Content-Length": "bogus"}), "invalid length"),
        (RawResponse(raw, **{"Content-Length": "1,1"}), "conflicting length"),
        (RawResponse(raw, **{"Content-Encoding": "gzip"}), "compressed"),
        (RawResponse(raw, status=206), "partial HTTP"),
        (RawResponse(raw, final_url=CALL2), "redirect-to-other-call"),
        (RawResponse(raw, final_url="https://example.org/evil"), "off-authority"),
        (RawResponse(raw, content_type="application/pdf"), "non-HTML"),
        (RawResponse(b""), "empty body"),
    ):
        try:
            attempt(bad)
        except (ValueError, RuntimeError):
            pass
        else:
            fail(f"EEA raw acquisition accepted an unsafe {label} response")


def main():
    test_transport_integrity()
    urls = module.discover_call_urls(INDEX_HTML, base_url=INDEX)
    if urls != [CALL1, CALL2]:
        fail(f"call discovery must prefer EN, order by call number and ignore third party: {urls}")

    parsed = module.parse_call_page(CALL1_HTML, authority_url=CALL1)
    if parsed["callNumber"] != "1" or parsed["status"] != "Open":
        fail("call detail parser failed number/status")
    if parsed["submissionDeadline"] != "08/10/2026":
        fail("call detail parser failed deadline")
    if parsed["amountAvailable"] != "€3,718,664":
        fail(f"call detail parser failed amount: {parsed['amountAvailable']!r}")
    if "non-governmental" not in (parsed["eligibleApplicants"] or ""):
        fail("eligible applicant candidate was not preserved")

    evidence = module.collect_live(
        index_url=INDEX,
        run_id="TEST-LIVE-EVIDENCE",
        fetched_at=FETCHED,
        minimum_calls=2,
        fetcher=fake_fetch,
    )
    stats = evidence["stats"]
    if stats["discovered_call_urls"] != 2 or stats["fetched_call_pages"] != 2:
        fail(f"unexpected acquisition stats: {stats}")
    if stats["open_call_evidence"] != 2 or stats["unknown_evidence"] != 0:
        fail(f"exact verified pages must create OPEN evidence candidates: {stats}")
    if evidence["publish_authorized"] or evidence["material_fact_use"]:
        fail("live acquisition must remain non-publishing/non-authorizing")
    if evidence["publication_effect"] != "NONE" or not evidence["requires_reconcile"]:
        fail("live evidence must route to reconcile with no publication effect")
    if {r["call_identifier"] for r in evidence["records"]} != {
        "EEA-CSF-RO-CALL-01",
        "EEA-CSF-RO-CALL-02",
    }:
        fail("stable call identity drift")
    page_hashes = {p["raw_hash"] for p in evidence["pages"]}
    expected = {hashlib.sha256(CALL1_HTML).hexdigest(), hashlib.sha256(CALL2_HTML).hexdigest()}
    if page_hashes != expected:
        fail("raw page hashes are not preserved exactly")

    def bad_final(url):
        return response(url, CALL1_HTML, final_url="https://example.org/evil")

    try:
        module.collect_live(
            index_url=INDEX,
            run_id="TEST-BAD-REDIRECT",
            fetched_at=FETCHED,
            minimum_calls=1,
            fetcher=bad_final,
        )
    except ValueError:
        pass
    else:
        fail("non-official redirect must fail closed before call parsing")

    # Current official index describes validated applications but no longer
    # server-renders the seven exact call-detail anchors (November 2026).
    transitioned_index = (
        b"<html><body><h1>Calls</h1>"
        b"EEA Civil Society Fund in Romania: a total of 863 applications "
        b"validated under the seven calls for proposals."
        b"<p>No results found</p></body></html>"
    )
    fallback, mode, direct_count = module.discover_with_official_fallback(
        transitioned_index, base_url=INDEX, minimum_calls=7
    )
    expected_urls = [url for _, url in module.PINNED_OFFICIAL_CALLS]
    if fallback != expected_urls or direct_count != 0 or not mode.startswith("PINNED_"):
        fail("official seven-call transition must use exact pinned detail URLs")

    def fetch_transitioned(url):
        if url == INDEX:
            return response(url, transitioned_index)
        for number, exact in module.PINNED_OFFICIAL_CALLS:
            if url == exact:
                html = (CALL1_HTML
                    .replace(b"Call #1", f"Call #{number}".encode())
                    .replace(b"<div>Open</div>", b"<div>Closed</div>"))
                return response(url, html)
        raise AssertionError(f"unexpected pinned source {url}")

    resumed = module.collect_live(
        index_url=INDEX, run_id="TEST-TRANSITIONED-INDEX",
        fetched_at=FETCHED, minimum_calls=7, fetcher=fetch_transitioned,
    )
    if resumed["stats"]["closed_call_evidence"] != 7 or resumed["stats"]["errors"]:
        fail("seven exact pinned pages must receive independent closed-call readback")
    if resumed["stats"]["index_direct_exact_call_links"] != 0:
        fail("pinned URLs must never be falsely reported as observed index anchors")
    if not resumed["stats"]["official_pinned_fallback_used"]:
        fail("fallback origin must be explicit in the evidence")
    if resumed["source_index"]["raw_hash"] != hashlib.sha256(transitioned_index).hexdigest():
        fail("changed official index raw SHA-256 must be preserved")
    if resumed["publish_authorized"] or resumed["material_fact_use"]:
        fail("pinned fallback cannot authorize any material fact or publication")

    def fake_unverified_index(url):
        if url == INDEX:
            return response(url, b"<html><h1>Calls</h1>Seven calls for proposals</html>")
        raise AssertionError("unverified index must not fetch call details")

    for minimum in (1, 7):
        try:
            module.collect_live(
                index_url=INDEX, run_id="TEST-UNVERIFIED-INDEX",
                fetched_at=FETCHED, minimum_calls=minimum, fetcher=fake_unverified_index,
            )
        except RuntimeError as exc:
            if "below minimum" not in str(exc):
                fail(f"unexpected unverified index error: {exc}")
        else:
            fail("unverified index must fail closed instead of using pinned URLs")

    # Partial index anchors block fallback; missing links cannot be filled silently.
    partial = INDEX_HTML.replace(
        f'<a href="{CALL1}">Call 1</a>'.encode(), b""
    ).replace(
        b'<a href="/ro/eea-civil-society-fund-romania/calls/call-1-strengthening-democracy-and-rule-law-through-civil-society-initiatives">Apel 1 duplicate language</a>', b""
    )
    only_links, mode, direct_count = module.discover_with_official_fallback(
        partial, base_url=INDEX, minimum_calls=7
    )
    if len(only_links) != 1 or mode != "INDEX_EXACT_ANCHORS" or direct_count != 1:
        fail("partial official index must remain incomplete; no pinned fallback")

    print("PASS EEA CSF live acquisition: exact official redirect-hop/byte-length guards, discovery, raw hashes and non-publishing reconciliation")


if __name__ == "__main__":
    main()
