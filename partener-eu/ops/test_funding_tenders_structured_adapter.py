#!/usr/bin/env python3
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ingest" / "funding_tenders_api.py"
spec = importlib.util.spec_from_file_location("funding_tenders_api", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

FETCHED_AT = "2026-08-27T12:00:00+00:00"
RUN_ID = "fixture-run-001"
OPEN_URL = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/HORIZON-TEST-2026-01"


def batch(records, verified=()):
    return mod.normalize_payload(
        {"results": records},
        fetched_at=FETCHED_AT,
        run_id=RUN_ID,
        verified_authority_urls=verified,
    )


def assert_true(value, message):
    if not value:
        raise AssertionError(message)


def main():
    open_record = {
        "identifier": "HORIZON-TEST-2026-01",
        "callIdentifier": "HORIZON-TEST-2026",
        "title": "Synthetic contract fixture",
        "status": "31094502",
        "statusLabel": "Open",
        "programAbbreviation": "HORIZON",
        "programmePeriod": "2021 - 2027",
        "authorityUrl": OPEN_URL,
        "deadlineDate": "2026-12-01",
        "budget": "1000000",
    }

    result = batch([open_record], verified={OPEN_URL})
    row = result["records"][0]
    assert_true(row["observation_state"] == "OPEN_CALL", "verified exact OPEN topic should classify OPEN_CALL")
    assert_true(
        row["material_fact_use"] is False and row["publish_authorized"] is False,
        "adapter must not publish or authorize material facts",
    )

    unverified = batch([open_record])["records"][0]
    assert_true(unverified["observation_state"] == "UNKNOWN", "unverified detail URL must fail closed")

    numeric_only = dict(open_record)
    numeric_only.pop("statusLabel")
    numeric = batch([numeric_only], verified={OPEN_URL})["records"][0]
    assert_true(numeric["observation_state"] == "UNKNOWN", "numeric reference code alone must not authorize OPEN")

    forthcoming = dict(open_record, statusLabel="Forthcoming")
    upcoming = batch([forthcoming], verified={OPEN_URL})["records"][0]
    assert_true(upcoming["observation_state"] == "FORTHCOMING_CALL", "forthcoming must remain distinct from open")

    pipeline = dict(open_record, statusLabel="Open", observation_state="PROPOSAL")
    planned = batch([pipeline], verified={OPEN_URL})["records"][0]
    assert_true(planned["observation_state"] == "PROGRAMMING_PIPELINE", "proposal must never become OPEN_CALL")

    no_id = dict(open_record)
    for key in ("identifier", "callIdentifier"):
        no_id.pop(key, None)
    missing = batch([no_id])
    assert_true(missing["records"] == [], "missing identifier must not enter normalized call evidence")

    generic_gateway_url = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/home"
    generic_gateway = dict(open_record, authorityUrl=generic_gateway_url)
    generic = batch([generic_gateway], verified={generic_gateway_url})["records"][0]
    assert_true(generic["observation_state"] == "UNKNOWN", "generic gateway must never authorize OPEN_CALL")

    duplicate = batch([open_record, dict(open_record)], verified={OPEN_URL})
    assert_true(len(duplicate["records"]) == 1, "identical duplicate topic must collapse deterministically")
    assert_true(duplicate["stats"]["duplicate_records_collapsed"] == 1, "duplicate metric drift")

    first = batch([open_record], verified={OPEN_URL})["records"][0]["semantic_fingerprint"]
    second = batch([dict(open_record)], verified={OPEN_URL})["records"][0]["semantic_fingerprint"]
    assert_true(first == second, "semantic fingerprint must be stable for identical material values")

    conflict_record = dict(open_record, title="Changed title requiring reconcile")
    conflict = batch([open_record, conflict_record], verified={OPEN_URL})
    assert_true(conflict["stats"]["conflicts"] == 1, "semantic duplicate conflict must be surfaced")
    assert_true(conflict["records"][0]["requires_reconcile"] is True, "conflicting identifier must require reconcile")

    print("PASS Funding & Tenders structured adapter: fail-closed OPEN gate, pipeline guard, dedup and reconcile")


if __name__ == "__main__":
    main()
