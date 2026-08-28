#!/usr/bin/env python3
import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ingest" / "esc_action_fetch.py"
spec = importlib.util.spec_from_file_location("esc_action_fetch", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)

AUTHORITY = "https://youth.europa.eu/solidarity/organisations/calls-for-proposals_en"
FETCHED = "2026-08-28T12:00:00+00:00"
HTML = b"""
<html><body>
<h1>2026 European Solidarity Corps call for proposals</h1>
<p>The call for proposals EAC/A15/2025 was published in the Official Journal as C/2025/06214.</p>
<table>
<tr><th>Activity type</th><th>Deadline</th><th>Where to apply</th></tr>
<tr><td>Volunteering projects</td><td>18 February 2026; optional round 1 October 2026</td><td>National Agency</td></tr>
<tr><td>Solidarity Projects</td><td>18 February 2026; optional rounds 7 May and 1 October 2026</td><td>National Agency</td></tr>
<tr><td>Volunteering teams in high priority areas</td><td>3 March 2026</td><td>EACEA</td></tr>
<tr><td>Humanitarian Aid Volunteering</td><td>23 April 2026</td><td>EACEA</td></tr>
</table>
</body></html>
"""


def fail(message):
    raise SystemExit(f"FAIL: {message}")


def response(url, raw, final_url=None, status=200, content_type="text/html; charset=utf-8"):
    return {
        "requested_url": url,
        "final_url": final_url or url,
        "status": status,
        "content_type": content_type,
        "raw": raw,
    }


def fake_fetch(url):
    if url != AUTHORITY:
        raise AssertionError(f"unexpected URL {url}")
    return response(url, HTML)


def main():
    if module.official_url(AUTHORITY + "?tracking=1") != AUTHORITY:
        fail("official URL canonicalization must discard query material")
    for bad in (
        "http://youth.europa.eu/solidarity/organisations/calls-for-proposals_en",
        "https://example.org/solidarity/organisations/calls-for-proposals_en",
        "https://youth.europa.eu/solidarity/organisations/other-page_en",
    ):
        try:
            module.official_url(bad)
        except ValueError:
            pass
        else:
            fail(f"unsafe/non-canonical ESC URL accepted: {bad}")

    evidence = module.collect_live(
        authority_url=AUTHORITY,
        run_id="TEST-ESC-LIVE",
        fetched_at=FETCHED,
        fetcher=fake_fetch,
    )
    module.validate_live_evidence(evidence)
    receipt = evidence["receipt"]
    expected_hash = hashlib.sha256(HTML).hexdigest()
    if receipt["raw_hash"] != expected_hash or evidence["batch"]["raw_hash"] != expected_hash:
        fail("raw page hash detached from live receipt/router batch")
    if receipt["bytes"] != len(HTML) or receipt["http_status"] != 200:
        fail("bounded acquisition receipt drift")
    if evidence["stats"]["action_rows"] != 4:
        fail(f"unexpected ESC live action count: {evidence['stats']}")
    if evidence["stats"]["open_call_authorized"] != 0:
        fail("annual call framework auto-authorized OPEN")
    if evidence["stats"]["records_requiring_exact_action_evidence"] != 4:
        fail("exact action evidence gate missing")
    if evidence["publication_effect"] != "NONE" or evidence["canonical_corpus_mutation"] is not False:
        fail("live ESC evidence crossed canonical/public boundary")
    if evidence["material_fact_use"] is not False or evidence["publish_authorized"] is not False:
        fail("live ESC evidence became material/publishing")

    def bad_redirect(url):
        return response(url, HTML, final_url="https://example.org/evil")

    try:
        module.collect_live(
            authority_url=AUTHORITY,
            run_id="TEST-BAD-REDIRECT",
            fetched_at=FETCHED,
            fetcher=bad_redirect,
        )
    except ValueError:
        pass
    else:
        fail("non-official redirect did not fail closed")

    def non_html(url):
        return response(url, HTML, content_type="application/json")

    try:
        module.collect_live(
            authority_url=AUTHORITY,
            run_id="TEST-BAD-CONTENT",
            fetched_at=FETCHED,
            fetcher=non_html,
        )
    except RuntimeError:
        pass
    else:
        fail("non-HTML evidence did not fail closed")

    print("PASS ESC live acquisition: official boundary, immutable raw hash, action framework and exact-evidence gate remain fail-closed")


if __name__ == "__main__":
    main()
