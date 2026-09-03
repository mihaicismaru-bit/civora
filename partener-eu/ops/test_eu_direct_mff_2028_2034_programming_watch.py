#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import pathlib
import tempfile
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ingest"))
import eu_direct_mff_2028_2034_programming_watch as watch

REGISTRY = pathlib.Path(__file__).resolve().parents[1] / "ingest" / "eu_direct_mff_2028_2034_programming_registry.json"


def fake_fetch(url: str):
    if url.endswith("/publications/european-competitiveness-fund_en"):
        text = "European Competitiveness Fund Proposal for a Regulation COM_2025_555_1 17 July 2025"
    elif url.endswith("/publications/horizon-europe_en"):
        text = "Horizon Europe Proposal for a Regulation COM_2025_543_1 17 July 2025"
    elif url.endswith("/publications/erasmus_en"):
        text = "Erasmus+ Proposal for a Regulation COM_2025_549_1 18 July 2025"
    elif url.endswith("/publications/connecting-europe-facility_en"):
        text = "Connecting Europe Facility Proposal for a Regulation COM_2025_547_1 17 July 2025"
    elif url.endswith("/publications/single-market-and-customs-programme_en"):
        text = "Single Market and Customs Programme Proposal for a Regulation COM_2025_590_1 3 September 2025"
    elif "commission.europa.eu" in url:
        text = "The Commission presented its proposal for the 2028-2034 Multiannual Financial Framework including European Competitiveness Fund, Erasmus+ and Horizon Europe."
    else:
        raise AssertionError(url)
    return text.encode(), {
        "requested_url": url, "final_url": url, "status": 200,
        "content_type": "text/html; charset=UTF-8",
    }


def main() -> None:
    registry = watch.load_registry(REGISTRY)
    current, raw = watch.collect(
        registry, run_id="test-1", fetched_at="2026-09-03T05:00:00+00:00", fetcher=fake_fetch)
    assert current["source_count"] == 6 and current["healthy_source_count"] == 6
    assert current["degraded_source_count"] == 0 and len(raw) == 6
    assert current["observation_state"] == "PROGRAMMING_PIPELINE"
    procedure_rows = [row for row in current["evidence"] if row.get("procedure_identifier")]
    assert len(procedure_rows) == 5
    assert {row["source_id"] for row in current["evidence"]} == {
        "MFF-2028-2034-COMMISSION-ROOT",
        "ECF-COM-2025-555",
        "HORIZON-2028-2034-COM-2025-543",
        "ERASMUS-2028-2034-COM-2025-549",
        "CEF-2028-2034-COM-2025-547",
        "SINGLE-MARKET-CUSTOMS-2028-2034-COM-2025-590",
    }
    assert all(row["semantics"]["procedure_state"] == "UNKNOWN_NON_AUTHORIZING" for row in procedure_rows)
    for flag in watch.MATERIAL_FLAGS:
        assert current[flag] is False
        assert all(row[flag] is False for row in current["evidence"])

    baseline = watch.reconcile(current, None)
    assert baseline["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
    assert baseline["pipeline_watch_candidate"] is False
    assert baseline["transport_or_content_change_count"] == 0

    same = copy.deepcopy(current)
    same["run_id"] = "test-2"
    same["fetched_at"] = "2026-09-03T06:00:00+00:00"
    no_change = watch.reconcile(same, current)
    assert no_change["reconciliation_state"] == "NO_CHANGE"
    assert no_change["semantic_change_count"] == 0
    assert no_change["transport_or_content_change_count"] == 0

    changed = copy.deepcopy(same)
    changed["evidence"][1]["semantics"]["procedure_state"] = "COMPLETED"
    changed["evidence"][1]["semantic_fingerprint"] = watch.sha256_json(changed["evidence"][1]["semantics"])
    changed["semantic_fingerprint"] = watch.sha256_json([
        row["semantics"] for row in changed["evidence"] if row.get("semantics") is not None])
    diff = watch.reconcile(changed, current)
    assert diff["reconciliation_state"] == "PROGRAMMING_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
    assert diff["semantic_change_count"] == 1 and diff["pipeline_watch_candidate"] is True
    assert diff["transport_or_content_change_count"] == 0
    for flag in watch.MATERIAL_FLAGS:
        assert diff[flag] is False

    transport = copy.deepcopy(same)
    degraded_row = transport["evidence"][2]
    degraded_row["source_health"] = {
        "health_state": "DEGRADED", "lkg_required": True,
        "requested_url": degraded_row["authority_url"], "final_url": None,
        "http_status": None, "content_type": None, "raw_size_bytes": 0,
        "raw_sha256": None, "error_type": "TIMEOUT", "error": "TimeoutError: synthetic",
    }
    degraded_row["semantics"] = None
    degraded_row["semantic_fingerprint"] = None
    transport["healthy_source_count"] = 5
    transport["degraded_source_count"] = 1
    transport["source_health"] = "DEGRADED"
    transport["semantic_fingerprint"] = watch.sha256_json([
        row["semantics"] for row in transport["evidence"] if row.get("semantics") is not None])
    transport_diff = watch.reconcile(transport, current)
    assert transport_diff["reconciliation_state"] == "TRANSPORT_OR_CONTENT_DRIFT_ONLY"
    assert transport_diff["semantic_change_count"] == 0
    assert transport_diff["transport_or_content_change_count"] == 1
    assert transport_diff["pipeline_watch_candidate"] is False
    assert transport_diff["source_health_watch_candidate"] is True
    assert transport_diff["lkg_reference_required"] is True
    assert transport_diff["lkg_reference_available"] is True
    assert transport_diff["lkg_reference_is_current_truth"] is False

    tampered = copy.deepcopy(changed)
    tampered["evidence"][1]["semantics"]["procedure_state"] = "TAMPERED"
    try:
        watch.reconcile(tampered, current)
    except ValueError:
        pass
    else:
        raise AssertionError("tampered semantic fingerprint should fail")

    bad = copy.deepcopy(registry)
    bad["policy"]["open_call_authorized"] = True
    with tempfile.TemporaryDirectory() as td:
        path = pathlib.Path(td) / "bad.json"
        path.write_text(json.dumps(bad), encoding="utf-8")
        try:
            watch.load_registry(path)
        except ValueError:
            pass
        else:
            raise AssertionError("registry authorization should fail")

    degraded, _ = watch.collect(
        registry, run_id="test-3", fetched_at="2026-09-03T07:00:00+00:00",
        fetcher=lambda url: (_ for _ in ()).throw(OSError("boom")))
    assert degraded["degraded_source_count"] == 6
    assert all(row["source_health"]["lkg_required"] is True for row in degraded["evidence"])
    assert all(row["semantic_fingerprint"] is None for row in degraded["evidence"])
    degraded_diff = watch.reconcile(degraded, current)
    assert degraded_diff["reconciliation_state"] == "TRANSPORT_OR_CONTENT_DRIFT_ONLY"
    assert degraded_diff["semantic_change_count"] == 0
    assert degraded_diff["transport_or_content_change_count"] == 6
    print(json.dumps({
        "status": "PASS", "sources": 6, "open_call_authorized": False,
        "transport_drift_is_not_semantic_change": True,
        "publication_effect": "NONE",
    }, sort_keys=True))


if __name__ == "__main__":
    main()
