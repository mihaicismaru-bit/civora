#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "ingest" / "eui_call_index.py"
spec = importlib.util.spec_from_file_location("eui_call_index", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)

FIXTURE = b"""<!doctype html><html><body>
<h1>Call for Proposals</h1>
<div class='filters'>Status <label>Open</label><label>Upcoming</label><label>Closed</label></div>
<article><h2>EUI ongoing Call for peer reviewers</h2><span>Open</span>
<div>Deadline date : 31/12/2028</div><a href='/authority/eui'>By European Urban Initiative</a>
<p>Discovery content.</p><a href='https://www.urban-initiative.eu/calls/peer-reviewers'>Find out more</a></article>
<article><h2>Foreign partner call</h2><span>Open</span><a href='/partner'>By NetZeroCities</a>
<a href='https://example.org/call'>Find out more</a></article>
<article><h2>4th EUI Call for Innovative Actions</h2><span>Closed</span>
<div>Deadline date : 15/06/2026</div><a href='/authority/eui'>By European Urban Initiative</a>
<a href='https://www.urban-initiative.eu/calls/4th-eui-ia'>Find out more</a></article>
<article><h2>Last foreign card</h2><span>Closed</span><div>Deadline date :</div><div>14/02/2025</div>
<a href='/neb'>By New European Bauhaus Prizes</a><a href='https://example.org/neb'>Find out more</a></article>
<footer><a href='https://urban-initiative.eu/'>European Urban Initiative</a></footer>
</body></html>"""

URL = "https://portico.urban-initiative.eu/urban-panorama/call-for-proposals"


def main() -> int:
    rows = mod.extract_call_candidates(FIXTURE, authority_url=URL)
    assert [row["title"] for row in rows] == [
        "EUI ongoing Call for peer reviewers",
        "4th EUI Call for Innovative Actions",
    ], rows
    assert rows[0]["status_candidate"] == "Open"
    assert rows[0]["deadline_candidate"] == "Deadline date : 31/12/2028"
    assert rows[1]["status_candidate"] == "Closed"

    a = mod.normalize_call_index(FIXTURE, authority_url=URL, fetched_at="2026-08-28T13:00:00+00:00", run_id="test")
    b = mod.normalize_call_index(FIXTURE, authority_url=URL, fetched_at="2026-08-28T13:00:00+00:00", run_id="test")
    assert a["record_count"] == 2
    assert a["raw_hash"] == mod.sha256_bytes(FIXTURE)
    assert [r["semantic_fingerprint"] for r in a["records"]] == [r["semantic_fingerprint"] for r in b["records"]]
    assert all(r["raw_hash"] == a["raw_hash"] for r in a["records"])
    assert all(r["exact_call_identifier"] is None and r["current_status_label"] is None for r in a["records"])
    assert all(r["material_fact_use"] is False and r["publish_authorized"] is False for r in a["records"])
    assert all(r["open_call_authorized"] is False for r in a["records"])
    assert all(r["requires_exact_call_evidence"] is True and r["requires_reconcile"] is True for r in a["records"])

    hostile = dict(a)
    hostile["open_call_authorized"] = True
    try:
        mod.validate_call_index_batch(hostile)
    except ValueError:
        pass
    else:
        raise AssertionError("batch OPEN authorization was not rejected")

    hostile = dict(a)
    hostile["records"] = [dict(a["records"][0], current_status_label="OPEN", open_call_authorized=True)]
    try:
        mod.validate_call_index_batch(hostile)
    except ValueError:
        pass
    else:
        raise AssertionError("row current/OPEN invention was not rejected")

    print("PASS EUI Portico call-index adapter stays discovery-only and deterministic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
