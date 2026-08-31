#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "ingest" / "creative_europe_call_index.py"
spec = importlib.util.spec_from_file_location("creative_europe_call_index", MODULE)
m = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(m)

HTML = b"""
<html><body>
<section><h3>EAC/A03/2021</h3><span>Status:</span><span>open</span><span>Deadline:</span>
<span>30 September 2027 17:00 CEST</span><h2>Capital of Culture experts</h2></section>
<section><h3>CREA-CULT-2026-COOP</h3><span>Status:</span><span>closed</span><span>Deadline:</span>
<span>5 May 2026 17:00 CEST</span><h2>2026 European Cooperation Projects</h2>
<a href="/funding/calls/2026-european-cooperation-projects">Opportunity details</a></section>
<section><h3>CREA-CULT-2026-LIT</h3><span>Status: closed</span><span>Deadline: 29 January 2026 17:00 CET</span>
<h2>Circulation of European literary works</h2><a href="/funding/calls/literary-works">Opportunity details</a></section>
<section><h3>Call for residency hosts 2025-2026</h3><span>Status:</span><span>closed</span></section>
</body></html>
"""

batch = m.normalize_call_index(
    HTML,
    authority_url="https://culture.ec.europa.eu/funding/calls",
    fetched_at="2026-08-31T18:00:00+00:00",
    run_id="synthetic",
)
assert batch["record_count"] == 2, batch
refs = [row["call_reference_candidate"] for row in batch["records"]]
assert refs == ["CREA-CULT-2026-COOP", "CREA-CULT-2026-LIT"], refs
first = batch["records"][0]
assert first["status_candidate"] == "closed"
assert first["deadline_candidate"] == "5 May 2026 17:00 CEST"
assert first["title_candidate"] == "2026 European Cooperation Projects"
assert first["programme_strand_candidate"] == "CULT"
assert first["detail_url_candidate"].startswith("https://culture.ec.europa.eu/")
assert first["exact_call_identifier"] is None
assert first["open_call_authorized"] is False
assert first["requires_funding_tenders_structured_reconcile"] is True
for row in batch["records"]:
    for key in m.MATERIAL_FLAGS:
        assert row[key] is False, (row["call_reference_candidate"], key)

bad = dict(batch)
bad["open_call_authorized"] = True
try:
    m.validate_call_index_batch(bad)
except ValueError:
    pass
else:
    raise AssertionError("authorizing aggregate did not fail closed")

bad_row_batch = dict(batch)
bad_row_batch["records"] = [dict(batch["records"][0], exact_call_identifier="CREA-CULT-2026-COOP")]
try:
    m.validate_call_index_batch(bad_row_batch)
except ValueError:
    pass
else:
    raise AssertionError("index invented exact identifier without failing closed")

print("PASS Creative Europe mixed-index filter and non-authorizing regression")
