#!/usr/bin/env python3
import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ingest" / "esc_action_router.py"
spec = importlib.util.spec_from_file_location("esc_action_router", MODULE_PATH)
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
<p>Quality Label applications may be submitted continuously.</p>
</body></html>
"""


def fail(message):
    raise SystemExit(f"FAIL: {message}")


def main():
    rows = module.extract_action_rows(HTML)
    if len(rows) != 4:
        fail(f"expected four annual-call action rows, got {rows}")
    if rows[0]["action_name"] != "Volunteering projects":
        fail("first action identity drift")
    if "1 October 2026" not in (rows[0]["deadline_candidate"] or ""):
        fail("deadline candidate was not preserved")
    if rows[2]["application_route"] != "EACEA":
        fail("application route was not preserved")

    batch = module.normalize_framework(
        HTML,
        authority_url=AUTHORITY,
        fetched_at=FETCHED,
        run_id="TEST-ESC-ROUTER",
    )
    module.validate_framework_batch(batch)
    if batch["framework_call_identifier"] != "EAC/A15/2025":
        fail(f"framework call identifier drift: {batch['framework_call_identifier']!r}")
    if batch["official_journal_identifier"] != "C/2025/06214":
        fail(f"OJ identifier drift: {batch['official_journal_identifier']!r}")
    if batch["call_year"] != "2026":
        fail(f"programme call year must derive from the explicit official call label, got {batch['call_year']!r}")
    if batch["call_year"] == batch["framework_call_identifier"].rsplit("/", 1)[-1]:
        fail("programme call year was incorrectly inferred from the notice identifier year")
    if batch["raw_hash"] != hashlib.sha256(HTML).hexdigest():
        fail("raw framework hash was not preserved exactly")
    if batch["record_count"] != 4:
        fail("record_count mismatch")
    if batch["publication_effect"] != "NONE" or batch["canonical_corpus_mutation"] is not False:
        fail("annual framework crossed publication/canonical boundary")
    for row in batch["records"]:
        if row["observation_state"] != "CALL_FRAMEWORK":
            fail(f"annual action inferred a current lifecycle state: {row}")
        if row["open_call_authorized"] is not False:
            fail("annual action auto-authorized OPEN")
        if row["material_fact_use"] is not False or row["publish_authorized"] is not False:
            fail("annual action became material/publishing")
        if not row["requires_exact_action_evidence"] or not row["requires_reconcile"]:
            fail("annual action lost exact-evidence/reconciliation gate")
        if row["exact_action_identifier"] is not None or row["current_status_label"] is not None:
            fail("annual action invented exact action/status evidence")

    batch2 = module.normalize_framework(
        HTML,
        authority_url=AUTHORITY,
        fetched_at=FETCHED,
        run_id="TEST-ESC-ROUTER",
    )
    if [r["semantic_fingerprint"] for r in batch["records"]] != [r["semantic_fingerprint"] for r in batch2["records"]]:
        fail("semantic fingerprints are not deterministic")

    print("PASS ESC action router: annual framework, identifiers, programme call year, deadline candidates and routes stay deterministic and fail-closed")


if __name__ == "__main__":
    main()
