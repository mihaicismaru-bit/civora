#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "partener-eu" / "ingest"))

import interreg_programming_pipeline as pipeline


def _write_registry(data: dict) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    with handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return Path(handle.name)


def _expect_fail(data: dict, needle: str) -> None:
    path = _write_registry(data)
    try:
        pipeline.load_registry(path)
    except ValueError as exc:
        if needle not in str(exc):
            raise AssertionError(f"unexpected error: {exc}") from exc
    else:
        raise AssertionError("expected fail-closed registry rejection")
    finally:
        path.unlink(missing_ok=True)


def main() -> None:
    result = pipeline.resolve(
        run_id="TEST-INTERREG-PIPELINE",
        observed_at="2026-08-31T01:49:33Z",
        live=False,
    )
    assert result["adapter_id"] == "INTERREG_PROGRAMMING_PIPELINE_V1"
    assert result["observation_state"] == "PROGRAMMING_PIPELINE"
    assert result["source_count"] == 6
    assert result["registry_freshness_state"] == "CURRENT_CHECK_30D"
    assert result["health_state"] == "NOT_PROBED"
    for key in pipeline.MATERIAL_FLAGS:
        assert result[key] is False
    assert result["publication_effect"] == "NONE"

    by_id = {row["source_id"]: row for row in result["watchlist"]}
    assert by_id["INT-PIPE-BSB-2028-2034"]["consultation_lifecycle"] == "IN_WINDOW"
    assert by_id["INT-PIPE-ROMD-2028-2034"]["consultation_lifecycle"] == "WINDOW_END_NOT_STATED"
    assert by_id["INT-PIPE-ROHU-2028-2034"]["consultation_lifecycle"] == "AFTER_WINDOW"
    assert by_id["INT-PIPE-ROBG-2028-2034"]["consultation_lifecycle"] == "AFTER_WINDOW"
    assert by_id["INT-PIPE-RORS-2028-2034"]["consultation_lifecycle"] == "AFTER_WINDOW"
    assert by_id["INT-PIPE-EU-COM-2025-552"]["observation_state"] == "PROPOSAL"
    assert result["watchlist"][0]["source_id"] == "INT-PIPE-BSB-2028-2034"
    for row in result["watchlist"]:
        for key in pipeline.MATERIAL_FLAGS:
            assert row[key] is False
        assert row["publication_effect"] == "NONE"
        assert row["market_intelligence_only"] is True
        assert "exact_call_or_topic_identifier" in row["missing_for_open_confirmation"]
        assert row["source_health"]["health_state"] == "NOT_PROBED"
        for forbidden in ("call_status", "call_budget", "call_deadline", "call_eligibility"):
            assert forbidden not in row

    registry, _ = pipeline.load_registry()
    bad = copy.deepcopy(registry)
    bad["sources"][0]["observation_state"] = "OPEN_CALL"
    _expect_fail(bad, "forbidden programming observation state")

    bad = copy.deepcopy(registry)
    bad["sources"][1]["authority_url"] = bad["sources"][1]["authority_url"].replace("https://", "http://")
    _expect_fail(bad, "non-HTTPS")

    bad = copy.deepcopy(registry)
    bad["policy"]["open_call_authorized"] = True
    _expect_fail(bad, "became authorizing")

    stale = copy.deepcopy(registry)
    stale["evidence_checked_date"] = "2026-06-01"
    path = _write_registry(stale)
    try:
        stale_result = pipeline.resolve(
            run_id="TEST-STALE",
            registry_path=path,
            observed_at="2026-08-31T01:49:33Z",
            live=False,
        )
        assert stale_result["registry_freshness_state"] == "STALE_CHECK_GT_30D"
        assert stale_result["open_call_authorized"] is False
    finally:
        path.unlink(missing_ok=True)

    future = copy.deepcopy(registry)
    future["evidence_checked_date"] = "2026-09-01"
    path = _write_registry(future)
    try:
        try:
            pipeline.resolve(
                run_id="TEST-FUTURE",
                registry_path=path,
                observed_at="2026-08-31T01:49:33Z",
                live=False,
            )
        except ValueError as exc:
            assert "future" in str(exc)
        else:
            raise AssertionError("future registry check date should fail closed")
    finally:
        path.unlink(missing_ok=True)

    print(
        json.dumps(
            {
                "status": "PASS",
                "source_count": result["source_count"],
                "top_watch": result["watchlist"][0]["source_id"],
                "top_lifecycle": result["watchlist"][0]["consultation_lifecycle"],
                "open_call_authorized": result["open_call_authorized"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
