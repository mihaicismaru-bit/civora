#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INGEST = ROOT / "partener-eu" / "ingest"
sys.path.insert(0, str(INGEST))

import interreg_bsb_programme_fit as bsb  # noqa: E402


def synthetic_body(spec: dict, extra: str = "") -> bytes:
    return ("<html><body>" + " | ".join(spec["markers"]) + " | " + extra + "</body></html>").encode()


def fake_fetch(url: str):
    spec = next(row for row in bsb.SOURCES if row["url"] == url)
    return synthetic_body(spec), {
        "requested_url": url,
        "final_url": url,
        "http_status": 200,
        "content_type": "text/html; charset=utf-8",
    }


def fake_fetch_changed(url: str):
    spec = next(row for row in bsb.SOURCES if row["url"] == url)
    extra = "Official regional information refreshed without any call-status assertion" if spec["id"] == "ADRSE_REGION_MEMBERSHIP" else ""
    return synthetic_body(spec, extra), {
        "requested_url": url,
        "final_url": url,
        "http_status": 200,
        "content_type": "text/html; charset=utf-8",
    }


def fake_fetch_with_lexical_open(url: str):
    spec = next(row for row in bsb.SOURCES if row["url"] == url)
    extra = "OPEN terminology may occur in navigation or historical material" if spec["id"] == "BSB_KEEP_PROGRAMME_VALIDATED_GEOGRAPHY" else ""
    return synthetic_body(spec, extra), {
        "requested_url": url,
        "final_url": url,
        "http_status": 200,
        "content_type": "text/html; charset=utf-8",
    }


def fail(fn, needle: str) -> None:
    try:
        fn()
    except ValueError as exc:
        assert needle.casefold() in str(exc).casefold(), (needle, str(exc))
    else:
        raise AssertionError(f"expected ValueError containing {needle!r}")


def assert_non_authorizing(result: dict) -> None:
    assert result["schema"] == bsb.SCHEMA
    assert result["parser_version"] == bsb.PARSER_VERSION
    assert result["programme_id"] == "BSB"
    assert result["programme_cci"] == "2021TC16NXTN002"
    assert result["romania_programme_region"] == "Sud-Est"
    assert result["romania_scope"] == ["Braila", "Buzau", "Constanta", "Galati", "Tulcea", "Vrancea"]
    assert result["territorial_fit_state"] == "ROMANIA_PROGRAMME_TERRITORY_VERIFIED_NON_AUTHORIZING"
    assert set(result["supported_applicant_types"]) == {"PUBLIC_AUTHORITY", "PUBLIC_LAW_BODY", "NGO_NONPROFIT"}
    assert result["applicant_signal_observation_state"] == "HISTORICAL_CLOSED_CALL_APPLICANT_SIGNAL"
    assert result["historical_call_status_observed"] == "CLOSED"
    assert result["historical_call_status_is_current_truth"] is False
    assert result["market_intelligence_only"] is True
    assert result["fit_is_not_eligibility"] is True
    assert result["call_specific_applicant_rules_required"] is True
    assert result["publication_effect"] == "NONE"
    assert len(result["source_receipts"]) == 3
    assert all(row["source_health"] == "HEALTHY" and row["http_status"] == 200 for row in result["source_receipts"])
    assert all(len(row["raw_sha256"]) == 64 and len(row["normalized_visible_text_sha256"]) == 64 for row in result["source_receipts"])
    for flag in bsb.MATERIAL_FLAGS:
        assert result[flag] is False, (flag, result[flag])


def main() -> None:
    baseline, raw = bsb.collect(
        run_id="bsb-regression-baseline",
        fetched_at="2026-09-03T21:50:00+00:00",
        fetcher=fake_fetch,
    )
    bsb.validate(baseline)
    assert_non_authorizing(baseline)
    assert set(raw) == {"BSB_KEEP_PROGRAMME_VALIDATED_GEOGRAPHY", "BSB_OFFICIAL_SECOND_CALL_HISTORY", "ADRSE_REGION_MEMBERSHIP"}

    changed, _ = bsb.collect(
        run_id="bsb-regression-changed",
        fetched_at="2026-09-03T21:51:00+00:00",
        fetcher=fake_fetch_changed,
    )
    assert_non_authorizing(changed)
    assert changed["semantic_fingerprint"] != baseline["semantic_fingerprint"]

    lexical_open, _ = bsb.collect(
        run_id="bsb-regression-open-word",
        fetched_at="2026-09-03T21:52:00+00:00",
        fetcher=fake_fetch_with_lexical_open,
    )
    assert_non_authorizing(lexical_open)
    assert lexical_open["open_call_authorized"] is False
    assert lexical_open["historical_call_status_is_current_truth"] is False

    t = copy.deepcopy(baseline)
    t["open_call_authorized"] = True
    fail(lambda: bsb.validate(t), "attempted authorization")

    t = copy.deepcopy(baseline)
    t["historical_call_status_is_current_truth"] = True
    fail(lambda: bsb.validate(t), "widened into current truth")

    t = copy.deepcopy(baseline)
    t["romania_scope"] = ["ALL_ROMANIA"]
    fail(lambda: bsb.validate(t), "territorial scope drift")

    t = copy.deepcopy(baseline)
    t["supported_applicant_types"].append("PRIVATE_BODY")
    fail(lambda: bsb.validate(t), "applicant signal drift")

    t = copy.deepcopy(baseline)
    t["source_receipts"][0]["final_url"] = "https://example.com/not-approved"
    fail(lambda: bsb.validate(t), "authority/transport drift")

    t = copy.deepcopy(baseline)
    t["source_receipts"][0]["normalized_visible_text_sha256"] = "0" * 64
    fail(lambda: bsb.validate(t), "semantic fingerprint mismatch")

    print({
        "status": "PASS",
        "programme_id": baseline["programme_id"],
        "romania_region": baseline["romania_programme_region"],
        "romania_scope": baseline["romania_scope"],
        "content_sensitive_semantic_hash": changed["semantic_fingerprint"] != baseline["semantic_fingerprint"],
        "lexical_open_non_authorizing": True,
        "eligibility_authorized": False,
    })


if __name__ == "__main__":
    main()
