#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "eucons" / "analytics" / "client_finder_funnel_analytics_contract.json"
ENGINE_PATH = ROOT / "eucons" / "analytics" / "client_finder_funnel_analytics.py"


def load_engine():
    spec = importlib.util.spec_from_file_location("eucons_r11_funnel", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load R11 funnel analytics engine")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ENGINE = load_engine()
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def rid(ch: str) -> str:
    return ch * 64


def row(
    ch: str,
    entity: str,
    lane: str,
    stage: str,
    contract_id: str,
    state: str,
    at: str,
) -> dict:
    return {
        "record_id": rid(ch),
        "funnel_entity_id": rid(entity),
        "entry_lane": lane,
        "stage": stage,
        "source_contract_id": contract_id,
        "source_state": state,
        "occurred_at": at,
    }


PROSPECT_PREFIX = [
    ("PROSPECT_READY", "R06-CF-CONTRACT-001", "READY_FOR_SCORING"),
    ("MATCHED", "R07-PROSPECT-MATCH-001", "MATCHED_RESEARCH_CANDIDATE"),
    ("OUTREACH_PREPARED", "R08-ACTION-PACK-001", "READY_FOR_APPROVAL"),
    ("CONTACT_APPROVED", "R10-PIPELINE-001", "CONTACT_APPROVED"),
    ("OFFER", "R10-PIPELINE-001", "OFFER"),
    ("WON", "R10-PIPELINE-001", "WON"),
]

INBOUND_PREFIX = [
    ("INBOUND_COMPLETED", "R05-INBOUND-001", "COMPLETED"),
    ("MATCHED", "R07-PROSPECT-MATCH-001", "MATCHED_RESEARCH_CANDIDATE"),
    ("OUTREACH_PREPARED", "R08-ACTION-PACK-001", "READY_FOR_APPROVAL"),
    ("CONTACT_APPROVED", "R10-PIPELINE-001", "CONTACT_APPROVED"),
    ("OFFER", "R10-PIPELINE-001", "OFFER"),
    ("WON", "R10-PIPELINE-001", "WON"),
]


def base(evidence_class: str = "NON_EVIDENCE", closed: bool = False) -> dict:
    return {
        "schema_version": 1,
        "product": "EUCONS_COMMERCIAL_OS",
        "cohort_id": rid("f"),
        "evidence_class": evidence_class,
        "cohort_closed": closed,
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-08-28T10:00:00Z",
        "as_of": "2026-08-28T10:05:00Z",
        "records": [],
    }


def add_prefix(
    payload: dict,
    lane: str,
    entity: str,
    stages: list[tuple[str, str, str]],
    count: int,
    seed: str,
    hour: int,
) -> None:
    chars = "0123456789abcdef"
    for index, (stage, contract_id, state) in enumerate(stages[:count]):
        record_char = chars[(chars.index(seed) + index) % len(chars)]
        payload["records"].append(
            row(
                record_char,
                entity,
                lane,
                stage,
                contract_id,
                state,
                f"2026-08-20T{hour + index:02d}:00:00Z",
            )
        )


def must_fail(name: str, payload: dict) -> None:
    try:
        ENGINE.build_funnel(copy.deepcopy(payload), copy.deepcopy(CONTRACT))
    except ENGINE.FunnelAnalyticsError:
        return
    raise SystemExit(f"{name}: R11 funnel analytics failed open")


def main() -> None:
    non_evidence = base()
    add_prefix(non_evidence, "PROSPECT_DISCOVERY", "a", PROSPECT_PREFIX, 3, "1", 1)
    result = ENGINE.build_funnel(copy.deepcopy(non_evidence), copy.deepcopy(CONTRACT))
    assert result["performance_state"] == "UNKNOWN_NON_EVIDENCE"
    assert result["performance_claims_enabled"] is False
    assert result["record_count"] == "UNKNOWN"
    assert result["entity_count"] == "UNKNOWN"
    assert all(
        value == "UNKNOWN"
        for value in result["lanes"]["PROSPECT_DISCOVERY"]["stage_counts"].values()
    )
    assert all(
        value == "UNKNOWN"
        for value in result["lanes"]["PROSPECT_DISCOVERY"]["transition_rates"].values()
    )

    open_real = base("REAL_TELEMETRY", False)
    add_prefix(open_real, "INBOUND", "b", INBOUND_PREFIX, 3, "2", 1)
    result = ENGINE.build_funnel(copy.deepcopy(open_real), copy.deepcopy(CONTRACT))
    assert result["performance_state"] == "COUNTS_ONLY_OPEN_COHORT"
    assert result["performance_claims_enabled"] is False
    assert result["record_count"] == 3
    assert result["entity_count"] == 1
    assert result["lanes"]["INBOUND"]["stage_counts"]["INBOUND_COMPLETED"] == 1
    assert all(
        value == "UNKNOWN"
        for value in result["lanes"]["INBOUND"]["transition_rates"].values()
    )

    closed_real = base("REAL_TELEMETRY", True)
    add_prefix(closed_real, "PROSPECT_DISCOVERY", "a", PROSPECT_PREFIX, 6, "1", 1)
    add_prefix(closed_real, "PROSPECT_DISCOVERY", "b", PROSPECT_PREFIX, 1, "8", 10)
    result = ENGINE.build_funnel(copy.deepcopy(closed_real), copy.deepcopy(CONTRACT))
    counts = result["lanes"]["PROSPECT_DISCOVERY"]["stage_counts"]
    rates = result["lanes"]["PROSPECT_DISCOVERY"]["transition_rates"]
    assert result["performance_state"] == "CLOSED_COHORT_REAL_TELEMETRY"
    assert result["performance_claims_enabled"] is True
    assert counts["PROSPECT_READY"] == 2
    assert counts["MATCHED"] == 1
    assert rates["PROSPECT_READY->MATCHED"] == 0.5
    assert rates["MATCHED->OUTREACH_PREPARED"] == 1.0

    payload = base("REAL_TELEMETRY", True)
    add_prefix(payload, "PROSPECT_DISCOVERY", "a", PROSPECT_PREFIX, 1, "1", 1)
    payload["records"][0]["email"] = "person@example.invalid"
    must_fail("raw PII key", payload)

    payload = base("REAL_TELEMETRY", True)
    add_prefix(payload, "PROSPECT_DISCOVERY", "a", PROSPECT_PREFIX, 1, "1", 1)
    payload["records"][0]["funnel_entity_id"] = "entity-raw"
    must_fail("raw entity id", payload)

    payload = base("REAL_TELEMETRY", True)
    add_prefix(payload, "PROSPECT_DISCOVERY", "a", PROSPECT_PREFIX, 1, "1", 1)
    payload["records"][0]["occurred_at"] = "2026-08-20T04:00:00+03:00"
    must_fail("non UTC-Z timestamp", payload)

    payload = base("REAL_TELEMETRY", True)
    add_prefix(payload, "PROSPECT_DISCOVERY", "a", PROSPECT_PREFIX, 1, "1", 1)
    payload["records"][0]["source_contract_id"] = "R10-PIPELINE-001"
    must_fail("source contract drift", payload)

    payload = base("REAL_TELEMETRY", True)
    add_prefix(payload, "PROSPECT_DISCOVERY", "a", PROSPECT_PREFIX, 1, "1", 1)
    payload["records"][0]["source_state"] = "MATCHED_RESEARCH_CANDIDATE"
    must_fail("source state drift", payload)

    payload = base("REAL_TELEMETRY", True)
    payload["records"] = [
        row(
            "1",
            "a",
            "PROSPECT_DISCOVERY",
            "PROSPECT_READY",
            "R06-CF-CONTRACT-001",
            "READY_FOR_SCORING",
            "2026-08-20T01:00:00Z",
        ),
        row(
            "2",
            "a",
            "PROSPECT_DISCOVERY",
            "OUTREACH_PREPARED",
            "R08-ACTION-PACK-001",
            "READY_FOR_APPROVAL",
            "2026-08-20T02:00:00Z",
        ),
    ]
    must_fail("closed cohort skipped stage", payload)

    payload = base("REAL_TELEMETRY", True)
    payload["records"] = [
        row(
            "1",
            "a",
            "PROSPECT_DISCOVERY",
            "MATCHED",
            "R07-PROSPECT-MATCH-001",
            "MATCHED_RESEARCH_CANDIDATE",
            "2026-08-20T01:00:00Z",
        )
    ]
    must_fail("closed cohort missing entry", payload)

    payload = base("REAL_TELEMETRY", False)
    add_prefix(payload, "PROSPECT_DISCOVERY", "a", PROSPECT_PREFIX, 1, "1", 1)
    payload["records"][0]["occurred_at"] = "2026-07-31T23:59:59Z"
    must_fail("outside cohort window", payload)

    payload = base("REAL_TELEMETRY", True)
    add_prefix(payload, "PROSPECT_DISCOVERY", "a", PROSPECT_PREFIX, 1, "1", 1)
    payload["records"].append(copy.deepcopy(payload["records"][0]))
    result = ENGINE.build_funnel(payload, copy.deepcopy(CONTRACT))
    assert result["record_count"] == 1

    payload = base("REAL_TELEMETRY", True)
    add_prefix(payload, "PROSPECT_DISCOVERY", "a", PROSPECT_PREFIX, 1, "1", 1)
    collision = copy.deepcopy(payload["records"][0])
    collision["stage"] = "MATCHED"
    collision["source_contract_id"] = "R07-PROSPECT-MATCH-001"
    collision["source_state"] = "MATCHED_RESEARCH_CANDIDATE"
    payload["records"].append(collision)
    must_fail("record id collision", payload)

    payload = base("REAL_TELEMETRY", True)
    payload["window_end"] = "2026-08-28T10:10:00Z"
    must_fail("window after as_of", payload)

    drift = copy.deepcopy(CONTRACT)
    drift["external_boundaries"]["crm_write_enabled"] = True
    try:
        ENGINE.build_funnel(base(), drift)
    except ENGINE.FunnelAnalyticsError:
        pass
    else:
        raise SystemExit("external boundary drift failed open")

    try:
        ENGINE.assert_output_path_safe(ROOT / "eucons" / "analytics" / "runtime-funnel.json")
    except ENGINE.FunnelAnalyticsError:
        pass
    else:
        raise SystemExit("repository runtime output guard failed open")

    print("EUCONS R11 Client Finder funnel analytics fail-closed regressions: PASS")


if __name__ == "__main__":
    main()
