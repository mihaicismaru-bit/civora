#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "partener-eu" / "ingest"))

from interreg_programming_intelligence import normalize_programming_observation  # noqa: E402

OFFICIAL_URL = "https://interreg-rohu.eu/en/"
PROGRAMME = "Interreg Romania-Hungary 2028-2034"
TEXT = (
    "STAKEHOLDER SURVEY NOW OPEN. The preparation of the future Interreg Programme "
    "between Romania and Hungary for the 2028–2034 period has officially started. "
    "We are launching a stakeholder consultation survey, open from 08.06.2026 to 01.08.2026."
)


def build(fetched_at: str, text: str = TEXT, url: str = OFFICIAL_URL):
    return normalize_programming_observation(
        {"programme": PROGRAMME, "title": "Stakeholder survey now open", "text": text, "authority_url": url},
        fetched_at=fetched_at,
        raw_hash="a" * 64,
        run_id="TEST-INTERREG-PROGRAMMING",
    )


def assert_non_authorizing(row):
    assert row["intelligence_family"] == "PROGRAMMING_PIPELINE"
    assert row["not_a_call"] is True
    assert row["open_call_authorized"] is False
    assert row["material_fact_use"] is False
    assert row["publish_authorized"] is False
    assert row["publication_effect"] == "NONE"
    assert "exact_call_identifier" in row["missing_to_confirm_call"]
    assert "official_call_detail_url" in row["missing_to_confirm_call"]


def main():
    closed = build("2026-08-28T00:49:03Z")
    assert closed["observation_state"] == "CONSULTATION_CLOSED", closed
    assert closed["consultation_start"] == "2026-06-08"
    assert closed["consultation_end"] == "2026-08-01"
    assert closed["stale_open_copy"] is True
    assert closed["confidence"] == "HIGH"
    assert_non_authorizing(closed)

    active = build("2026-07-15T12:00:00Z")
    assert active["observation_state"] == "CONSULTATION"
    assert active["stale_open_copy"] is False
    assert_non_authorizing(active)

    planned = build("2026-05-10T12:00:00Z")
    assert planned["observation_state"] == "PLANNED"
    assert_non_authorizing(planned)

    preparation = build(
        "2026-08-28T00:49:03Z",
        "The future Interreg Programme for 2028-2034 is under programme preparation and stakeholder dialogue.",
    )
    assert preparation["observation_state"] == "PROGRAMME_PREPARATION"
    assert preparation["confidence"] == "MEDIUM"
    assert_non_authorizing(preparation)

    misleading = build(
        "2026-08-28T00:49:03Z",
        "Future programme 2028-2034. OPEN CALL language appears in a news recap, but no exact call identifier or call page exists.",
    )
    assert misleading["observation_state"] == "PROGRAMME_PREPARATION"
    assert_non_authorizing(misleading)

    try:
        build("2026-08-28T00:49:03Z", url="https://example.com/post-2027")
    except ValueError as exc:
        assert "non-authoritative Interreg URL" in str(exc)
    else:
        raise AssertionError("third-party host must fail closed")

    try:
        build("2026-08-28T00:49:03")
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("naive fetched_at must fail closed")

    print("PASS Interreg programming intelligence: date-over-copy reconciliation; pipeline never authorizes OPEN_CALL")


if __name__ == "__main__":
    main()
