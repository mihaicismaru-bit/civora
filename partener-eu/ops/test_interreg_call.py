#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

INGEST = Path(__file__).resolve().parents[1] / "ingest"
sys.path.insert(0, str(INGEST))

from interreg_call import deduplicate_observations, normalize_call_observation

FETCHED_AT = "2026-08-28T06:00:00Z"
RAW_HASH = "a" * 64
RUN_ID = "interreg-call-regression"


def norm(**overrides):
    record = {
        "call_identifier": "DRP-THIRD-CALL-2025",
        "programme": "Danube Region Programme 2021-2027",
        "authority_url": "https://interreg-danube.eu/calls-for-proposals/third-call-for-proposals",
        "title": "Third call for proposals",
        "official_status": "CLOSED",
        "deadline": "2025-12-15T14:00:00+01:00",
        "readback_verified": True,
    }
    record.update(overrides)
    return normalize_call_observation(record, fetched_at=FETCHED_AT, raw_hash=RAW_HASH, run_id=RUN_ID)


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    closed = norm()
    check(closed["observation_state"] == "CLOSED_CALL", "historical closed call became open")
    check(closed["publish_authorized"] is False and closed["material_fact_use"] is False, "closed observation became authorizing")

    stale = norm(official_status="OPEN")
    check(stale["observation_state"] == "REVIEW_REQUIRED", "stale OPEN with expired deadline was accepted")
    check("open_status_conflicts_with_expired_deadline" in stale["review_reasons"], "deadline contradiction was not surfaced")

    pipeline = norm(official_status="CONSULTATION")
    check(pipeline["observation_state"] == "PROGRAMMING_PIPELINE", "consultation escaped programming boundary")
    check(pipeline["publish_authorized"] is False, "programming observation became authorizing")

    missing_id = norm(call_identifier="", official_status="OPEN", deadline="2026-12-15T14:00:00+01:00")
    check(missing_id["observation_state"] == "REVIEW_REQUIRED", "OPEN without exact call identifier was accepted")

    unread = norm(official_status="OPEN", deadline="2026-12-15T14:00:00+01:00", readback_verified=False)
    check(unread["observation_state"] == "REVIEW_REQUIRED", "OPEN without exact-page readback was accepted")

    synthetic_open = norm(call_identifier="SYNTHETIC-INTERREG-CALL-2026", official_status="OPEN", deadline="2026-12-15T14:00:00+01:00")
    check(synthetic_open["observation_state"] == "OPEN_CALL", "fully evidenced synthetic OPEN fixture did not classify")
    check(synthetic_open["publish_authorized"] is False and synthetic_open["publication_effect"] == "NONE", "normalization bypassed downstream reconcile")

    try:
        norm(authority_url="https://example.com/calls/third-call")
    except ValueError:
        pass
    else:
        raise AssertionError("third-party host accepted as Interreg authority")

    try:
        norm(authority_url="https://interreg-danube.eu/calls-for-proposals")
    except ValueError:
        pass
    else:
        raise AssertionError("generic call index accepted as exact call page")

    deduped = deduplicate_observations([closed, dict(closed)])
    check(len(deduped["records"]) == 1 and not deduped["reconcile_required"], "identical duplicate was not collapsed")

    changed = norm(title="Third call for proposals — corrigendum")
    conflict = deduplicate_observations([closed, changed])
    check(len(conflict["reconcile_required"]) == 1, "semantic drift did not require reconcile")
    check(conflict["reconcile_required"][0]["reason"] == "SEMANTIC_CONFLICT", "wrong reconcile reason")

    print("PASS INTERREG_CALL_V1 exact-call boundary: closed/stale/programming/missing-proof fail closed; semantic drift reconciles")


if __name__ == "__main__":
    main()
