#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "ingest" / "eui_call_fetch.py"
spec = importlib.util.spec_from_file_location("eui_call_fetch", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)

URL = mod.DEFAULT_URL
RAW = b"""<html><body>
<h2>EUI ongoing Call for peer reviewers</h2><div>Open</div><div>Deadline date : 31/12/2028</div>
<a href='/eui'>By European Urban Initiative</a><a href='https://www.urban-initiative.eu/calls/peer'>Find out more</a>
<h2>4th EUI Call for Innovative Actions</h2><div>Closed</div><div>Deadline date : 15/06/2026</div>
<a href='/eui'>By European Urban Initiative</a><a href='https://www.urban-initiative.eu/calls/ia4'>Find out more</a>
</body></html>"""


def good_fetch(_: str):
    return {"requested_url": URL, "final_url": URL, "status": 200, "content_type": "text/html; charset=UTF-8", "raw": RAW}


def expect_failure(fetcher, message: str) -> None:
    try:
        mod.collect_live(authority_url=URL, run_id="test", fetched_at="2026-08-28T13:00:00+00:00", fetcher=fetcher)
    except (ValueError, RuntimeError):
        return
    raise AssertionError(message)


def main() -> int:
    evidence = mod.collect_live(authority_url=URL, run_id="test", fetched_at="2026-08-28T13:00:00+00:00", fetcher=good_fetch)
    assert evidence["receipt"]["raw_hash"] == hashlib.sha256(RAW).hexdigest()
    assert evidence["batch"]["raw_hash"] == evidence["receipt"]["raw_hash"]
    assert evidence["stats"]["eui_candidates"] == 2
    assert evidence["stats"]["visible_open_candidates"] == 1
    assert evidence["stats"]["open_call_authorized"] == 0
    assert evidence["material_fact_use"] is False and evidence["publish_authorized"] is False
    assert evidence["open_call_authorized"] is False and evidence["canonical_corpus_mutation"] is False

    for invalid in [
        "http://portico.urban-initiative.eu/urban-panorama/call-for-proposals",
        "https://evil.example/urban-panorama/call-for-proposals",
        "https://portico.urban-initiative.eu/other",
        "https://user:pass@portico.urban-initiative.eu/urban-panorama/call-for-proposals",
    ]:
        try:
            mod.official_url(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe URL accepted: {invalid}")

    expect_failure(lambda _: {"requested_url": URL, "final_url": "https://evil.example/x", "status": 200, "content_type": "text/html", "raw": RAW}, "hostile redirect accepted")
    expect_failure(lambda _: {"requested_url": URL, "final_url": URL, "status": 200, "content_type": "application/json", "raw": RAW}, "non-HTML accepted")
    expect_failure(lambda _: {"requested_url": URL, "final_url": URL, "status": 503, "content_type": "text/html", "raw": RAW}, "non-200 accepted")
    expect_failure(lambda _: {"requested_url": URL, "final_url": URL, "status": 200, "content_type": "text/html", "raw": b"<html>No EUI cards</html>"}, "empty official evidence accepted")

    print("PASS EUI Portico acquisition is exact-host, bounded, immutable and fail-closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
