#!/usr/bin/env python3
from __future__ import annotations

import copy

from interreg_romania_call_surface_watch import SURFACES, collect, validate_receipt


def synthetic_body(spec: dict) -> bytes:
    return ("<html><body>" + " | ".join(str(x) for x in spec["anchors"]) + "</body></html>").encode()


def fake_fetch(url: str):
    spec = next(x for x in SURFACES if x["url"] == url)
    return synthetic_body(spec), {
        "requested_url": url,
        "final_url": url,
        "status": 200,
        "content_type": "text/html; charset=utf-8",
    }


def degraded_fetch(url: str):
    spec = next(x for x in SURFACES if x["url"] == url)
    if spec["id"] == "RO_UA":
        raise OSError("synthetic TLS transport failure")
    return fake_fetch(url)


def fail(fn, needle: str) -> None:
    try:
        fn()
    except ValueError as exc:
        assert needle.casefold() in str(exc).casefold(), (needle, str(exc))
    else:
        raise AssertionError(f"expected ValueError containing {needle!r}")


def main() -> int:
    receipt, raw = collect(
        run_id="synthetic-interreg-call-surfaces-1",
        fetched_at="2026-09-02T06:00:00+00:00",
        fetcher=fake_fetch,
    )
    assert receipt["schema"] == "PARTENER_EU_INTERREG_ROMANIA_CALL_SURFACE_WATCH_V1"
    assert receipt["source_health"] == "HEALTHY" and receipt["coverage_complete"] is True
    assert receipt["healthy_surface_count"] == 7 and receipt["degraded_surface_count"] == 0
    assert len(raw) == 7 and len(receipt["surfaces"]) == 7
    assert receipt["discovered_call_facts"] == []
    assert next(x for x in receipt["surfaces"] if x["programme_id"] == "RO_RS")["observation_state"] == "PLANNED"
    assert next(x for x in receipt["surfaces"] if x["programme_id"] == "INTERREG_EUROPE")["programme_filter_required"] is True
    validate_receipt(receipt)

    degraded, raw2 = collect(
        run_id="synthetic-interreg-call-surfaces-2",
        fetched_at="2026-09-02T06:05:00+00:00",
        fetcher=degraded_fetch,
    )
    assert degraded["source_health"] == "DEGRADED" and degraded["coverage_complete"] is False
    assert degraded["healthy_surface_count"] == 6 and degraded["degraded_surface_count"] == 1
    assert len(raw2) == 6
    ua = next(x for x in degraded["surfaces"] if x["programme_id"] == "RO_UA")
    assert ua["transport_health"] == "DEGRADED" and ua["source_sha256"] is None
    assert degraded["open_call_authorized"] is False and degraded["call_alert_authorized"] is False
    validate_receipt(degraded)

    t = copy.deepcopy(receipt); t["open_call_authorized"] = True
    fail(lambda: validate_receipt(t), "attempted authorization")
    t = copy.deepcopy(receipt); t["discovered_call_facts"] = [{"status": "OPEN"}]
    fail(lambda: validate_receipt(t), "attempted to emit call facts")
    t = copy.deepcopy(receipt); t["surfaces"][0]["status_fact_authorized"] = True
    fail(lambda: validate_receipt(t), "attempted field authorization")
    t = copy.deepcopy(receipt); t["surfaces"][2]["observation_state"] = "OPEN_CALL"
    fail(lambda: validate_receipt(t), "observation/filter drift")
    t = copy.deepcopy(receipt); t["surfaces"][0]["final_url"] = "https://example.com/calls"
    fail(lambda: validate_receipt(t), "escaped official discovery authority")
    t = copy.deepcopy(receipt); t["surfaces"][0]["source_sha256"] = "0" * 64
    fail(lambda: validate_receipt(t), "semantic fingerprint mismatch")

    print("Interreg Romania call-surface watch fail-closed regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
