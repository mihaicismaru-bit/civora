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


def _drop_fingerprints(snapshot: dict) -> None:
    snapshot.pop("snapshot_semantic_fingerprint", None)
    snapshot.pop("snapshot_transport_fingerprint", None)
    for row in snapshot.get("watchlist") or []:
        row.pop("semantic_fingerprint", None)
        row.pop("transport_fingerprint", None)


def _row(snapshot: dict, source_id: str) -> dict:
    return next(row for row in snapshot["watchlist"] if row["source_id"] == source_id)


def _make_healthy(row: dict, raw_hash: str) -> None:
    health = row["source_health"]
    health.update({
        "health_state": "HEALTHY",
        "lkg_required": False,
        "final_url": row["authority_url"],
        "http_status": 200,
        "content_type": "text/html",
        "raw_sha256": raw_hash,
        "raw_size_bytes": 1234,
        "missing_marker_groups": [],
        "error": None,
    })


def _make_degraded(row: dict) -> None:
    health = row["source_health"]
    health.update({
        "health_state": "DEGRADED",
        "lkg_required": True,
        "final_url": None,
        "http_status": None,
        "content_type": None,
        "raw_sha256": None,
        "raw_size_bytes": 0,
        "missing_marker_groups": [],
        "error": "URLError: synthetic transport failure",
    })


class _FakeResponse:
    def __init__(self, *, status: int, body: str, url: str = "https://example.test/programming") -> None:
        self.status = status
        self._body = body.encode("utf-8")
        self._url = url
        self.headers = {"Content-Type": "text/html; charset=utf-8"}

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._url


def _probe_fixture() -> dict:
    return {
        "authority_url": "https://example.test/programming",
        "allowed_hosts": ["example.test"],
        "allowed_path_prefixes": ["/programming"],
        "required_markers": [["interreg"], ["2028", "2034"]],
    }


def _test_bounded_retry() -> dict:
    original_urlopen = pipeline.urlopen
    original_sleep = pipeline.time.sleep
    sleeps: list[float] = []
    try:
        responses = [
            _FakeResponse(status=202, body="Interreg programming 2028 2034"),
            _FakeResponse(status=200, body="Interreg programming 2028 2034"),
        ]

        def recovering_urlopen(request, timeout):
            return responses.pop(0)

        pipeline.urlopen = recovering_urlopen
        pipeline.time.sleep = lambda seconds: sleeps.append(seconds)
        recovered = pipeline._probe(
            _probe_fixture(),
            timeout=0.1,
            max_attempts=3,
            retry_backoff_seconds=0.01,
        )
        assert recovered["health_state"] == "HEALTHY"
        assert recovered["attempt_count"] == 2
        assert recovered["retryable_failure_count"] == 1
        assert recovered["retry_exhausted"] is False
        assert recovered["attempt_history"] == [
            {"attempt": 1, "kind": "TRANSIENT_HTTP_STATUS", "http_status": 202}
        ]
        assert sleeps == [0.01]

        calls = 0
        sleeps.clear()

        def certificate_failure(request, timeout):
            nonlocal calls
            calls += 1
            raise pipeline.URLError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")

        pipeline.urlopen = certificate_failure
        certificate = pipeline._probe(
            _probe_fixture(),
            timeout=0.1,
            max_attempts=3,
            retry_backoff_seconds=0.01,
        )
        assert certificate["health_state"] == "DEGRADED"
        assert certificate["attempt_count"] == 1
        assert certificate["retryable_failure_count"] == 0
        assert certificate["retry_exhausted"] is False
        assert calls == 1
        assert sleeps == []

        responses = [
            _FakeResponse(status=503, body="temporary one"),
            _FakeResponse(status=503, body="temporary two"),
            _FakeResponse(status=503, body="temporary three"),
        ]
        sleeps.clear()

        def exhausted_urlopen(request, timeout):
            return responses.pop(0)

        pipeline.urlopen = exhausted_urlopen
        exhausted = pipeline._probe(
            _probe_fixture(),
            timeout=0.1,
            max_attempts=3,
            retry_backoff_seconds=0.01,
        )
        assert exhausted["health_state"] == "DEGRADED_TRANSIENT_EXHAUSTED"
        assert exhausted["attempt_count"] == 3
        assert exhausted["retryable_failure_count"] == 3
        assert exhausted["retry_exhausted"] is True
        assert exhausted["http_status"] == 503
        assert len(exhausted["attempt_history"]) == 3
        assert sleeps == [0.01, 0.02]
        assert exhausted["raw_sha256"] is not None

        return {
            "recovered_attempt_count": recovered["attempt_count"],
            "certificate_attempt_count": certificate["attempt_count"],
            "exhausted_attempt_count": exhausted["attempt_count"],
        }
    finally:
        pipeline.urlopen = original_urlopen
        pipeline.time.sleep = original_sleep


def main() -> None:
    registry, _ = pipeline.load_registry()
    result = pipeline.resolve(
        run_id="TEST-INTERREG-PIPELINE",
        observed_at="2026-09-01T01:49:33Z",
        live=False,
    )
    assert result["schema_version"] == "1.0"
    assert result["adapter_id"] == "INTERREG_PROGRAMMING_PIPELINE_V1"
    assert result["observation_state"] == "PROGRAMMING_PIPELINE"
    assert result["source_count"] == len(registry["sources"]) == 11
    assert result["registry_freshness_state"] == "CURRENT_CHECK_30D"
    assert result["health_state"] == "NOT_PROBED"
    assert len(result["snapshot_semantic_fingerprint"]) == 64
    assert len(result["snapshot_transport_fingerprint"]) == 64
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
    assert by_id["INT-PIPE-INTERACT-POST-2027-2028-2034"]["observation_state"] == "PROGRAMMING_PROCESS"
    assert by_id["INT-PIPE-INTERACT-POST-2027-2028-2034"]["programme_family"] == "INTERREG_EU_FRAMEWORK"
    assert by_id["INT-PIPE-INTERACT-POST-2027-2028-2034"]["authority_class"] == "T2_OFFICIAL_INTERREG_SUPPORT"
    assert "ROUA" in by_id["INT-PIPE-INTERACT-POST-2027-2028-2034"]["programme_ids"]
    assert by_id["INT-PIPE-ROUA-POST-2027-RESEARCH"]["observation_state"] == "PROGRAMMING_PROCESS"
    assert by_id["INT-PIPE-ROUA-POST-2027-RESEARCH"]["programme_family"] == "INTERREG_EU_FRAMEWORK"
    assert by_id["INT-PIPE-ROUA-POST-2027-RESEARCH"]["authority_class"] == "T2_OFFICIAL_PROGRAMME_POST_2027_RESEARCH"
    assert by_id["INT-PIPE-ROUA-POST-2027-RESEARCH"]["programme_ids"] == ["ROUA"]
    assert by_id["INT-PIPE-DANUBE-2028-2034"]["observation_state"] == "PROGRAMMING_PROCESS"
    assert by_id["INT-PIPE-INTERREG-EUROPE-2028-2034"]["observation_state"] == "PROGRAMMING_PROCESS"
    assert by_id["INT-PIPE-HUSKROUA-2028-2034"]["observation_state"] == "PROGRAMMING_PROCESS"
    assert by_id["INT-PIPE-DANUBE-2028-2034"]["programme_ids"] == ["DANUBE"]
    assert by_id["INT-PIPE-INTERREG-EUROPE-2028-2034"]["programme_ids"] == ["INTERREG_EUROPE"]
    assert by_id["INT-PIPE-HUSKROUA-2028-2034"]["programme_ids"] == ["HUSKROUA"]
    assert result["watchlist"][0]["source_id"] == "INT-PIPE-BSB-2028-2034"
    for row in result["watchlist"]:
        for key in pipeline.MATERIAL_FLAGS:
            assert row[key] is False
        assert row["publication_effect"] == "NONE"
        assert row["market_intelligence_only"] is True
        assert "exact_call_or_topic_identifier" in row["missing_for_open_confirmation"]
        assert row["source_health"]["health_state"] == "NOT_PROBED"
        assert row["source_health"]["attempt_count"] == 0
        assert row["source_health"]["max_attempts"] == 3
        assert row["source_health"]["retry_exhausted"] is False
        assert len(row["semantic_fingerprint"]) == 64
        assert len(row["transport_fingerprint"]) == 64
        for forbidden in ("call_status", "call_budget", "call_deadline", "call_eligibility"):
            assert forbidden not in row

    retry_evidence = _test_bounded_retry()

    try:
        pipeline.resolve(
            run_id="TEST-BAD-ATTEMPTS",
            observed_at="2026-09-01T01:49:33Z",
            live=False,
            max_attempts=0,
        )
    except ValueError as exc:
        assert "max_attempts" in str(exc)
    else:
        raise AssertionError("zero max_attempts must fail closed")

    try:
        pipeline.resolve(
            run_id="TEST-BAD-BACKOFF",
            observed_at="2026-09-01T01:49:33Z",
            live=False,
            retry_backoff_seconds=-0.1,
        )
    except ValueError as exc:
        assert "retry_backoff_seconds" in str(exc)
    else:
        raise AssertionError("negative retry_backoff_seconds must fail closed")

    baseline = pipeline.reconcile_snapshots(
        result,
        reconciled_at="2026-09-01T02:00:00Z",
    )
    assert baseline["adapter_id"] == "INTERREG_PROGRAMMING_RECONCILIATION_V1"
    assert baseline["reconciliation_state"] == "BASELINE_CAPTURED_NO_PREVIOUS_SNAPSHOT"
    assert baseline["pipeline_semantic_reconciliation_status"] == "PASS"
    assert baseline["pipeline_watch_candidate"] is False
    assert baseline["call_alert_authorized"] is False
    assert baseline["distribution_authorized"] is False
    assert baseline["semantic_change_count"] == 0
    assert baseline["transport_or_content_change_count"] == 0
    assert baseline["source_count_current"] == 11

    previous = copy.deepcopy(result)
    previous["run_id"] = "TEST-PREVIOUS"
    previous["fetched_at"] = "2026-08-31T01:49:33Z"
    current_same = copy.deepcopy(result)
    current_same["run_id"] = "TEST-CURRENT-SAME"
    current_same["fetched_at"] = "2026-09-01T01:49:33Z"
    no_change = pipeline.reconcile_snapshots(
        current_same,
        previous,
        reconciled_at="2026-09-01T02:01:00Z",
    )
    assert no_change["reconciliation_state"] == "NO_CHANGE"
    assert no_change["semantic_change_count"] == 0
    assert no_change["transport_or_content_change_count"] == 0
    assert no_change["pipeline_watch_candidate"] is False

    semantic_previous = copy.deepcopy(result)
    semantic_previous["run_id"] = "TEST-PREV-SEMANTIC"
    semantic_current = copy.deepcopy(result)
    semantic_current["run_id"] = "TEST-CURR-SEMANTIC"
    target = _row(semantic_current, "INT-PIPE-ROMD-2028-2034")
    target["consultation_lifecycle"] = "AFTER_WINDOW"
    _drop_fingerprints(semantic_current)
    semantic_receipt = pipeline.reconcile_snapshots(
        semantic_current,
        semantic_previous,
        reconciled_at="2026-09-01T02:02:00Z",
    )
    assert semantic_receipt["reconciliation_state"] == "PIPELINE_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
    assert semantic_receipt["semantic_change_count"] == 1
    assert semantic_receipt["pipeline_watch_candidate"] is True
    assert semantic_receipt["pipeline_watch_label_required"] == "PROGRAMARE_VIITOARE_PIPELINE"
    assert semantic_receipt["call_alert_authorized"] is False
    assert semantic_receipt["open_call_authorized"] is False
    assert semantic_receipt["distribution_authorized"] is False

    transport_previous = copy.deepcopy(result)
    transport_previous["run_id"] = "TEST-PREV-TRANSPORT"
    transport_current = copy.deepcopy(result)
    transport_current["run_id"] = "TEST-CURR-TRANSPORT"
    _make_healthy(_row(transport_previous, "INT-PIPE-DANUBE-2028-2034"), "a" * 64)
    _make_healthy(_row(transport_current, "INT-PIPE-DANUBE-2028-2034"), "b" * 64)
    _drop_fingerprints(transport_previous)
    _drop_fingerprints(transport_current)
    transport_receipt = pipeline.reconcile_snapshots(
        transport_current,
        transport_previous,
        reconciled_at="2026-09-01T02:03:00Z",
    )
    assert transport_receipt["reconciliation_state"] == "TRANSPORT_OR_CONTENT_DRIFT_ONLY"
    assert transport_receipt["semantic_change_count"] == 0
    assert transport_receipt["transport_or_content_change_count"] == 1
    assert transport_receipt["pipeline_watch_candidate"] is False
    assert transport_receipt["source_health_watch_candidate"] is True
    assert transport_receipt["distribution_authorized"] is False

    lkg_previous = copy.deepcopy(result)
    lkg_previous["run_id"] = "TEST-PREV-LKG"
    lkg_previous["fetched_at"] = "2026-08-31T03:00:00Z"
    lkg_current = copy.deepcopy(result)
    lkg_current["run_id"] = "TEST-CURR-LKG"
    _make_healthy(_row(lkg_previous, "INT-PIPE-ROBG-2028-2034"), "c" * 64)
    _make_degraded(_row(lkg_current, "INT-PIPE-ROBG-2028-2034"))
    _drop_fingerprints(lkg_previous)
    _drop_fingerprints(lkg_current)
    lkg_receipt = pipeline.reconcile_snapshots(
        lkg_current,
        lkg_previous,
        reconciled_at="2026-09-01T02:04:00Z",
    )
    assert lkg_receipt["lkg_reference_available_count"] == 1
    lkg_change = next(row for row in lkg_receipt["changes"] if row["source_id"] == "INT-PIPE-ROBG-2028-2034")
    assert lkg_change["lkg_status"] == "REFERENCE_AVAILABLE_FROM_PREVIOUS_HEALTHY_SNAPSHOT"
    assert lkg_change["lkg_reference"]["raw_sha256"] == "c" * 64
    assert lkg_change["lkg_reference"]["previous_run_id"] == "TEST-PREV-LKG"
    assert lkg_change["material_fact_use"] is False
    assert lkg_change["distribution_authorized"] is False

    lkg_missing_previous = copy.deepcopy(result)
    lkg_missing_current = copy.deepcopy(result)
    _make_degraded(_row(lkg_missing_previous, "INT-PIPE-ROBG-2028-2034"))
    _make_degraded(_row(lkg_missing_current, "INT-PIPE-ROBG-2028-2034"))
    _drop_fingerprints(lkg_missing_previous)
    _drop_fingerprints(lkg_missing_current)
    lkg_missing_receipt = pipeline.reconcile_snapshots(
        lkg_missing_current,
        lkg_missing_previous,
        reconciled_at="2026-09-01T02:05:00Z",
    )
    assert lkg_missing_receipt["lkg_reference_missing_count"] == 1

    tampered = copy.deepcopy(result)
    tampered["open_call_authorized"] = True
    try:
        pipeline.reconcile_snapshots(tampered, result)
    except ValueError as exc:
        assert "became authorizing" in str(exc)
    else:
        raise AssertionError("authorizing snapshot must fail closed")

    fingerprint_tampered = copy.deepcopy(result)
    _row(fingerprint_tampered, "INT-PIPE-DANUBE-2028-2034")["signal_basis"] = "tampered without fingerprint refresh"
    try:
        pipeline.reconcile_snapshots(fingerprint_tampered, result)
    except ValueError as exc:
        assert "semantic fingerprint mismatch" in str(exc)
    else:
        raise AssertionError("fingerprint drift must fail closed")

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
            observed_at="2026-09-01T01:49:33Z",
            live=False,
        )
        assert stale_result["registry_freshness_state"] == "STALE_CHECK_GT_30D"
        assert stale_result["open_call_authorized"] is False
    finally:
        path.unlink(missing_ok=True)

    future = copy.deepcopy(registry)
    future["evidence_checked_date"] = "2026-09-02"
    path = _write_registry(future)
    try:
        try:
            pipeline.resolve(
                run_id="TEST-FUTURE",
                registry_path=path,
                observed_at="2026-09-01T01:49:33Z",
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
                "snapshot_semantic_fingerprint": result["snapshot_semantic_fingerprint"],
                "baseline_reconciliation": baseline["reconciliation_state"],
                "semantic_reconciliation": semantic_receipt["reconciliation_state"],
                "lkg_reference_available_count": lkg_receipt["lkg_reference_available_count"],
                "retry_recovered_attempt_count": retry_evidence["recovered_attempt_count"],
                "retry_exhausted_attempt_count": retry_evidence["exhausted_attempt_count"],
                "open_call_authorized": result["open_call_authorized"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
