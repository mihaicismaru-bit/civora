#!/usr/bin/env python3
import base64
import hashlib
import importlib.util
import json
import sys
import tempfile
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

    # The official index can drop all call-detail links after a deadline.
    # A missing index must yield a provenance receipt, not an exception that
    # prevents the failure artifact from being uploaded.
    empty_html = b"<html><h1>Calls</h1><p>Applications closed 8 October 2026</p><p>No results found</p></html>"

    def empty_fetch(url):
        if url != INDEX:
            raise AssertionError(f"unexpected exact-call fetch: {url}")
        return response(url, empty_html)

    held = module.collect_live(
        index_url=INDEX,
        run_id="TEST-EMPTY-INDEX",
        fetched_at=FETCHED,
        minimum_calls=7,
        fetcher=empty_fetch,
    )
    if held["source_index"]["raw_hash"] != hashlib.sha256(empty_html).hexdigest():
        fail("empty index must preserve exact official response hash")
    if held["source_index"]["url"] != INDEX or held["fetched_at"] != FETCHED:
        fail("empty index provenance URL / fetch timestamp drift")
    if held["source_index"]["observation_state"] != "NO_EXACT_CALL_LINKS":
        fail("missing exact-call links must have an explicit observation state")
    if held["acquisition_status"] != "INCOMPLETE_DISCOVERY":
        fail("empty index cannot count as complete acquisition")
    if held["stats"]["discovered_call_urls"] != 0 or not held["stats"]["discovery_shortfall"]:
        fail("empty index must fail the minimum-7 exact-call requirement")
    if held["pages"] or held["records"] or held["publish_authorized"] or held["material_fact_use"]:
        fail("empty index cannot invent or authorize call evidence")
    if held["publication_effect"] != "NONE" or held["stats"]["open_call_evidence"]:
        fail("index-only shortfall cannot promote OPEN or publish")

    # Exercise CLI behavior: nonzero failure *and* an immutable-ready JSON
    # receipt, rather than a pre-serialization exception.
    original_collect, original_argv = module.collect_live, sys.argv
    try:
        module.collect_live = lambda **kwargs: original_collect(fetcher=empty_fetch, **kwargs)
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / "live-evidence.json"
            sys.argv = ["eea_civil_society_fetch.py", "--minimum-calls", "7", "--output", str(output)]
            exit_code = module.main()
            if exit_code != 2 or not output.is_file():
                fail("CLI must fail closed and still persist index evidence")
            receipt = json.loads(output.read_text(encoding="utf-8"))
            if receipt["source_index"]["raw_hash"] != held["source_index"]["raw_hash"]:
                fail("CLI failure receipt hash drift")
    finally:
        module.collect_live, sys.argv = original_collect, original_argv

    closed_html = CALL1_HTML.replace(b"<div>Open</div>", b"<div>Closed</div>")
    def seed_fetch(url):
        if url == INDEX:
            return response(url, empty_html)
        if url == CALL1:
            return response(url, closed_html)
        raise AssertionError(f"unexpected seed {url}")

    seeded = module.collect_live(index_url=INDEX, run_id="TEST-SEED",
        fetched_at=FETCHED, minimum_calls=7, fetcher=seed_fetch, seed_urls=(CALL1,))
    if seeded["acquisition_status"] != "DIAGNOSTIC_SEED_CAPTURE" or not seeded["diagnostic_seed_mode"]:
        fail("seed capture must remain diagnostic")
    if seeded["stats"]["discovered_call_urls"] != 0 or seeded["stats"]["fetched_call_pages"] != 1:
        fail("seed pages cannot count as discovered index links")
    if base64.b64decode(seeded["pages"][0]["raw_response_b64"]) != closed_html:
        fail("seed raw page replay bytes drift")
    if base64.b64decode(seeded["source_index"]["raw_response_b64"]) != empty_html:
        fail("seed raw index replay bytes drift")
    if seeded["publish_authorized"] or seeded["material_fact_use"] or seeded["stats"]["open_call_evidence"]:
        fail("seed capture cannot authorize or invent OPEN evidence")

    def mismatch_fetch(url):
        return response(url, empty_html if url == INDEX else CALL2_HTML)
    mismatch = module.collect_live(index_url=INDEX, run_id="TEST-MISMATCH",
        fetched_at=FETCHED, fetcher=mismatch_fetch, seed_urls=(CALL1,))
    if mismatch["pages"] or mismatch["records"] or len(mismatch["errors"]) != 1:
        fail("mismatched exact-call body must be rejected")
    original_collect, original_argv = module.collect_live, sys.argv
    try:
        module.collect_live = lambda **kwargs: original_collect(fetcher=seed_fetch, **kwargs)
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / "seed.json"
            sys.argv = ["eea_civil_society_fetch.py", "--minimum-calls", "1",
                        "--seed-url", CALL1, "--output", str(output)]
            if module.main() != 2 or not output.is_file():
                fail("even sufficient diagnostic seed capture must exit nonzero")
    finally:
        module.collect_live, sys.argv = original_collect, original_argv

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

    print("PASS EEA CSF live acquisition: official discovery, exact-page readback, hashed empty-index receipt, fail-closed CLI, parsing, reconciliation and redirect guard")


if __name__ == "__main__":
    main()
