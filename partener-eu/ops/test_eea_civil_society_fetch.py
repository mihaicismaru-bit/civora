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


def main():
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

    print("PASS EEA CSF live acquisition: official discovery, exact-page readback, raw hashes, parsing, reconciliation and redirect guard")


if __name__ == "__main__":
    main()
