#!/usr/bin/env python3
from __future__ import annotations

import copy

from interreg_huskroua_call2_exact import collect, load_registry, validate_evidence

REGISTRY_PATH = "partener-eu/ingest/interreg_huskroua_call2_exact_registry.json"


def body(*parts: str) -> bytes:
    return ("<html><body>" + " | ".join(parts) + "</body></html>").encode("utf-8")


def fake_fetch(url: str):
    if url.endswith("/calls/2nd-call-for-proposals/"):
        raw = body(
            "SUMMARY OF THE 2ND CALL’S CONDITIONS AND REQUIREMENTS",
            "The 2nd Call for Proposals for the Interreg VI-A NEXT Hungary-Slovakia-Romania-Ukraine Programme has been officially launched.",
            "OPEN is a historical lexical token only and must not authorize current status.",
        )
    elif "closure-of-the-2nd-call-for-proposals" in url:
        raw = body(
            "Closure of the 2nd Call for Proposals",
            "The 2nd Call for Proposals of the Interreg VI-A NEXT Hungary-Slovakia-Romania-Ukraine Programme has officially closed.",
        )
    else:
        raise AssertionError(f"unexpected url {url}")
    return raw, {
        "requested_url": url,
        "final_url": url,
        "http_status": 200,
        "content_type": "text/html; charset=utf-8",
    }


def changed_closure_fetch(url: str):
    raw, meta = fake_fetch(url)
    if "closure-of-the-2nd-call-for-proposals" in url:
        raw = raw.replace(b"officially closed", b"officially closed UPDATED")
    return raw, meta


def missing_marker_fetch(url: str):
    raw, meta = fake_fetch(url)
    if "closure-of-the-2nd-call-for-proposals" in url:
        raw = body("Programme news without lifecycle marker")
    return raw, meta


def escaped_host_fetch(url: str):
    raw, meta = fake_fetch(url)
    if url.endswith("/calls/2nd-call-for-proposals/"):
        meta = dict(meta)
        meta["final_url"] = "https://example.com/calls/2"
    return raw, meta


def fail(fn, needle: str) -> None:
    try:
        fn()
    except ValueError as exc:
        assert needle.casefold() in str(exc).casefold(), (needle, str(exc))
    else:
        raise AssertionError(f"expected ValueError containing {needle!r}")


def main() -> int:
    registry = load_registry(REGISTRY_PATH)
    receipt, raws = collect(
        registry=registry,
        run_id="synthetic-huskroua-call2-1",
        fetched_at="2026-09-04T03:00:00+00:00",
        fetcher=fake_fetch,
    )
    assert receipt["schema"] == "PARTENER_EU_INTERREG_HUSKROUA_CALL2_EXACT_EVIDENCE_V1"
    assert receipt["source_health_state"] == "HEALTHY"
    assert receipt["official_call_identifier"] == "2"
    assert receipt["official_call_identifier_kind"] == "OFFICIAL_CALL_NUMBER"
    assert receipt["candidate_state"] == "CLOSED_CALL_CANDIDATE"
    assert receipt["candidate_status_label"] == "Closed"
    assert receipt["status_basis"] == "CURRENT_OFFICIAL_PROGRAMME_CLOSURE_ANNOUNCEMENT"
    assert receipt["current_material_truth_available"] is False
    assert receipt["previous_or_lkg_is_current_truth"] is False
    assert receipt["closed_call_authorized"] is False
    assert receipt["open_call_authorized"] is False
    assert receipt["publication_effect"] == "NONE"
    assert len(raws) == 2 and len(receipt["sources"]) == 2
    assert len(receipt["exact_semantic_fingerprint"]) == 64
    validate_evidence(receipt)

    changed, _ = collect(
        registry=registry,
        run_id="synthetic-huskroua-call2-2",
        fetched_at="2026-09-04T03:05:00+00:00",
        fetcher=changed_closure_fetch,
    )
    assert changed["source_health_state"] == "HEALTHY"
    assert changed["candidate_state"] == "CLOSED_CALL_CANDIDATE"
    assert changed["exact_semantic_fingerprint"] != receipt["exact_semantic_fingerprint"]
    assert changed["closed_call_authorized"] is False

    degraded, _ = collect(
        registry=registry,
        run_id="synthetic-huskroua-call2-3",
        fetched_at="2026-09-04T03:10:00+00:00",
        fetcher=missing_marker_fetch,
    )
    assert degraded["source_health_state"] == "DEGRADED"
    assert degraded["candidate_state"] == "UNKNOWN"
    assert degraded["lkg_required"] is True
    assert degraded["exact_semantics"] is None
    assert degraded["exact_semantic_fingerprint"] is None
    assert degraded["closed_call_authorized"] is False
    validate_evidence(degraded)

    escaped, _ = collect(
        registry=registry,
        run_id="synthetic-huskroua-call2-4",
        fetched_at="2026-09-04T03:15:00+00:00",
        fetcher=escaped_host_fetch,
    )
    assert escaped["source_health_state"] == "DEGRADED"
    assert escaped["candidate_state"] == "UNKNOWN"
    validate_evidence(escaped)

    t = copy.deepcopy(receipt)
    t["closed_call_authorized"] = True
    fail(lambda: validate_evidence(t), "attempted authorization")

    t = copy.deepcopy(receipt)
    t["current_material_truth_available"] = True
    fail(lambda: validate_evidence(t), "current material truth")

    t = copy.deepcopy(receipt)
    t["exact_semantic_fingerprint"] = "0" * 64
    fail(lambda: validate_evidence(t), "semantic fingerprint mismatch")

    t = copy.deepcopy(receipt)
    t["sources"][0]["normalized_visible_text_sha256"] = "0" * 64
    fail(lambda: validate_evidence(t), "semantic/source hash binding drift")

    print("HUSKROUA Call 2 exact fail-closed regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
