#!/usr/bin/env python3
from __future__ import annotations

import copy

from interreg_romania_call_surface_watch import SURFACES, collect, validate_receipt


def synthetic_body(anchors: tuple[str, ...]) -> bytes:
    return ("<html><body>" + " | ".join(str(x) for x in anchors) + "</body></html>").encode()


def lookup(url: str):
    for spec in SURFACES:
        if spec["url"] == url:
            return spec, spec["anchors"]
        fallback = spec.get("fallback")
        if fallback and fallback["url"] == url:
            return spec, fallback["anchors"]
    raise AssertionError(f"unexpected URL {url}")


def fake_fetch(url: str):
    _, anchors = lookup(url)
    return synthetic_body(tuple(anchors)), {
        "requested_url": url,
        "final_url": url,
        "status": 200,
        "content_type": "text/html; charset=utf-8",
    }


def degraded_fetch(url: str):
    spec, _ = lookup(url)
    if spec["id"] == "RO_UA" and url == spec["url"]:
        raise OSError("synthetic TLS certificate verify failed")
    return fake_fetch(url)


def degraded_fallback_fetch(url: str):
    spec, _ = lookup(url)
    if spec["id"] == "RO_UA" and (url == spec["url"] or url == spec["fallback"]["url"]):
        raise OSError("synthetic TLS certificate verify failed")
    return fake_fetch(url)


def validation_failure_fetch(url: str):
    spec, anchors = lookup(url)
    if spec["id"] == "RO_UA" and url == spec["url"]:
        return b"<html><body>unexpected direct page</body></html>", {
            "requested_url": url, "final_url": url, "status": 200, "content_type": "text/html"
        }
    if spec["id"] == "RO_UA" and url == spec["fallback"]["url"]:
        raise AssertionError("fallback must not mask direct semantic validation failure")
    return synthetic_body(tuple(anchors)), {
        "requested_url": url, "final_url": url, "status": 200, "content_type": "text/html"
    }


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
    assert receipt["schema"] == "PARTENER_EU_INTERREG_ROMANIA_CALL_SURFACE_WATCH_V2"
    assert receipt["source_health"] == "HEALTHY" and receipt["coverage_complete"] is True
    assert receipt["healthy_surface_count"] == 7 and receipt["degraded_surface_count"] == 0
    assert receipt["fallback_configured_count"] == 3 and receipt["fallback_attempted_count"] == 0
    assert receipt["fallback_healthy_count"] == 0 and receipt["fallback_degraded_count"] == 0
    assert len(raw) == 7 and len(receipt["surfaces"]) == 7
    assert receipt["discovered_call_facts"] == []
    assert receipt["fallback_does_not_restore_call_surface_coverage"] is True
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
    assert degraded["fallback_attempted_count"] == 1 and degraded["fallback_healthy_count"] == 1
    assert degraded["degraded_direct_with_healthy_fallback_count"] == 1
    assert degraded["degraded_direct_without_healthy_fallback_count"] == 0
    assert len(raw2) == 7
    ua = next(x for x in degraded["surfaces"] if x["programme_id"] == "RO_UA")
    assert ua["transport_health"] == "DEGRADED" and ua["source_sha256"] is None
    assert ua["failure_class"] == "TLS_CERTIFICATE_VERIFY_FAILED"
    assert ua["fallback_provenance"]["transport_health"] == "HEALTHY"
    assert ua["fallback_provenance"]["programme_identity_verified_non_authorizing"] is True
    assert ua["fallback_provenance"]["call_surface_authority"] is False
    assert degraded["open_call_authorized"] is False and degraded["call_alert_authorized"] is False
    validate_receipt(degraded)

    fallback_bad, _ = collect(
        run_id="synthetic-interreg-call-surfaces-3",
        fetched_at="2026-09-02T06:10:00+00:00",
        fetcher=degraded_fallback_fetch,
    )
    ua_bad = next(x for x in fallback_bad["surfaces"] if x["programme_id"] == "RO_UA")
    assert fallback_bad["fallback_attempted_count"] == 1 and fallback_bad["fallback_degraded_count"] == 1
    assert fallback_bad["degraded_direct_without_healthy_fallback_count"] == 1
    assert ua_bad["fallback_provenance"]["transport_health"] == "DEGRADED"
    validate_receipt(fallback_bad)

    semantic_bad, _ = collect(
        run_id="synthetic-interreg-call-surfaces-4",
        fetched_at="2026-09-02T06:15:00+00:00",
        fetcher=validation_failure_fetch,
    )
    ua_semantic = next(x for x in semantic_bad["surfaces"] if x["programme_id"] == "RO_UA")
    assert ua_semantic["failure_class"] == "VALIDATION_ERROR"
    assert ua_semantic["fallback_provenance"]["transport_health"] == "NOT_ATTEMPTED_DIRECT_VALIDATION_FAILURE"
    assert semantic_bad["fallback_attempted_count"] == 0
    validate_receipt(semantic_bad)

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

    t = copy.deepcopy(degraded)
    ua = next(x for x in t["surfaces"] if x["programme_id"] == "RO_UA")
    ua["fallback_provenance"]["call_surface_authority"] = True
    fail(lambda: validate_receipt(t), "fallback attempted call authority")

    t = copy.deepcopy(degraded)
    ua = next(x for x in t["surfaces"] if x["programme_id"] == "RO_UA")
    ua["fallback_provenance"]["final_url"] = "https://example.com/programme"
    fail(lambda: validate_receipt(t), "fallback escaped Interreg/Interact authority")

    t = copy.deepcopy(degraded)
    t["coverage_complete"] = True
    fail(lambda: validate_receipt(t), "coverage flag drift")

    print("Interreg Romania call-surface fallback provenance fail-closed regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
