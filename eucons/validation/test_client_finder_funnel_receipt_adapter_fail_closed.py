#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADAPTER_CONTRACT_PATH = ROOT / "eucons" / "analytics" / "client_finder_funnel_receipt_adapter_contract.json"
ADAPTER_ENGINE_PATH = ROOT / "eucons" / "analytics" / "client_finder_funnel_receipt_adapter.py"
R11_CONTRACT_PATH = ROOT / "eucons" / "analytics" / "client_finder_funnel_analytics_contract.json"
R11_ENGINE_PATH = ROOT / "eucons" / "analytics" / "client_finder_funnel_analytics.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ADAPTER = load_module("eucons_r11_receipt_adapter", ADAPTER_ENGINE_PATH)
R11 = load_module("eucons_r11_funnel", R11_ENGINE_PATH)
ADAPTER_CONTRACT = json.loads(ADAPTER_CONTRACT_PATH.read_text(encoding="utf-8"))
R11_CONTRACT = json.loads(R11_CONTRACT_PATH.read_text(encoding="utf-8"))


def rid(ch: str) -> str:
    return ch * 64


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
        "receipts": [],
    }


def receipt(
    receipt_char: str,
    entity_char: str,
    receipt_type: str,
    lane: str,
    contract_id: str,
    state: str,
    at: str,
    snapshot_char: str,
) -> dict:
    return {
        "receipt_id": rid(receipt_char),
        "funnel_entity_id": rid(entity_char),
        "entry_lane": lane,
        "receipt_type": receipt_type,
        "source_contract_id": contract_id,
        "source_state": state,
        "source_snapshot_hash": rid(snapshot_char),
        "occurred_at": at,
    }


PROSPECT = [
    ("CLIENT_FINDER_READY_RECEIPT", "R06-CF-CONTRACT-001", "READY_FOR_SCORING"),
    ("PROSPECT_MATCH_RECEIPT", "R07-PROSPECT-MATCH-001", "MATCHED_RESEARCH_CANDIDATE"),
    ("ACTION_PACK_READY_RECEIPT", "R08-ACTION-PACK-001", "READY_FOR_APPROVAL"),
    ("PIPELINE_CONTACT_APPROVED_RECEIPT", "R10-PIPELINE-001", "CONTACT_APPROVED"),
    ("PIPELINE_OFFER_RECEIPT", "R10-PIPELINE-001", "OFFER"),
    ("PIPELINE_WON_RECEIPT", "R10-PIPELINE-001", "WON"),
]

INBOUND = [
    ("INBOUND_COMPLETION_RECEIPT", "R05-INBOUND-001", "COMPLETED"),
    ("PROSPECT_MATCH_RECEIPT", "R07-PROSPECT-MATCH-001", "MATCHED_RESEARCH_CANDIDATE"),
    ("ACTION_PACK_READY_RECEIPT", "R08-ACTION-PACK-001", "READY_FOR_APPROVAL"),
    ("PIPELINE_CONTACT_APPROVED_RECEIPT", "R10-PIPELINE-001", "CONTACT_APPROVED"),
    ("PIPELINE_OFFER_RECEIPT", "R10-PIPELINE-001", "OFFER"),
    ("PIPELINE_WON_RECEIPT", "R10-PIPELINE-001", "WON"),
]


def add_sequence(payload: dict, lane: str, entity: str, items: list[tuple[str, str, str]], count: int, seed: int) -> None:
    chars = "0123456789abcdef"
    for index, (receipt_type, contract_id, state) in enumerate(items[:count]):
        payload["receipts"].append(
            receipt(
                chars[(seed + index) % len(chars)],
                entity,
                receipt_type,
                lane,
                contract_id,
                state,
                f"2026-08-20T{index + 1:02d}:00:00Z",
                chars[(seed + index + 7) % len(chars)],
            )
        )


def must_fail(name: str, payload: dict, contract: dict | None = None, target: dict | None = None) -> None:
    try:
        ADAPTER.build_r11_input(
            copy.deepcopy(payload),
            copy.deepcopy(contract or ADAPTER_CONTRACT),
            copy.deepcopy(target or R11_CONTRACT),
        )
    except ADAPTER.FunnelReceiptAdapterError:
        return
    raise SystemExit(f"{name}: receipt adapter failed open")


def main() -> None:
    payload = base()
    add_sequence(payload, "PROSPECT_DISCOVERY", "a", PROSPECT, 3, 1)
    adapted = ADAPTER.build_r11_input(
        copy.deepcopy(payload), copy.deepcopy(ADAPTER_CONTRACT), copy.deepcopy(R11_CONTRACT)
    )
    assert set(adapted) == {
        "schema_version", "product", "cohort_id", "evidence_class", "cohort_closed",
        "window_start", "window_end", "as_of", "records"
    }
    assert len(adapted["records"]) == 3
    result = R11.build_funnel(copy.deepcopy(adapted), copy.deepcopy(R11_CONTRACT))
    assert result["performance_state"] == "UNKNOWN_NON_EVIDENCE"
    assert result["performance_claims_enabled"] is False

    payload = base("REAL_TELEMETRY", False)
    add_sequence(payload, "INBOUND", "b", INBOUND, 3, 2)
    adapted = ADAPTER.build_r11_input(
        copy.deepcopy(payload), copy.deepcopy(ADAPTER_CONTRACT), copy.deepcopy(R11_CONTRACT)
    )
    result = R11.build_funnel(copy.deepcopy(adapted), copy.deepcopy(R11_CONTRACT))
    assert result["performance_state"] == "COUNTS_ONLY_OPEN_COHORT"
    assert result["lanes"]["INBOUND"]["stage_counts"]["INBOUND_COMPLETED"] == 1
    assert all(value == "UNKNOWN" for value in result["lanes"]["INBOUND"]["transition_rates"].values())

    payload = base("REAL_TELEMETRY", True)
    add_sequence(payload, "PROSPECT_DISCOVERY", "a", PROSPECT, 6, 3)
    adapted = ADAPTER.build_r11_input(
        copy.deepcopy(payload), copy.deepcopy(ADAPTER_CONTRACT), copy.deepcopy(R11_CONTRACT)
    )
    result = R11.build_funnel(copy.deepcopy(adapted), copy.deepcopy(R11_CONTRACT))
    assert result["performance_state"] == "CLOSED_COHORT_REAL_TELEMETRY"
    assert result["lanes"]["PROSPECT_DISCOVERY"]["transition_rates"]["PROSPECT_READY->MATCHED"] == 1.0

    reordered = copy.deepcopy(payload)
    reordered["receipts"] = list(reversed(reordered["receipts"]))
    assert ADAPTER.build_r11_input(reordered, copy.deepcopy(ADAPTER_CONTRACT), copy.deepcopy(R11_CONTRACT)) == adapted

    replay = copy.deepcopy(payload)
    replay["receipts"].append(copy.deepcopy(replay["receipts"][0]))
    replay_adapted = ADAPTER.build_r11_input(
        replay, copy.deepcopy(ADAPTER_CONTRACT), copy.deepcopy(R11_CONTRACT)
    )
    assert len(replay_adapted["records"]) == 6

    bad = base("REAL_TELEMETRY", False)
    add_sequence(bad, "PROSPECT_DISCOVERY", "a", PROSPECT, 1, 1)
    bad["receipts"][0]["email"] = "person@example.invalid"
    must_fail("raw PII key", bad)

    bad = base("REAL_TELEMETRY", False)
    add_sequence(bad, "PROSPECT_DISCOVERY", "a", PROSPECT, 1, 1)
    bad["receipts"][0]["funnel_entity_id"] = "raw-entity"
    must_fail("raw entity id", bad)

    bad = base("REAL_TELEMETRY", False)
    add_sequence(bad, "PROSPECT_DISCOVERY", "a", PROSPECT, 1, 1)
    bad["receipts"][0]["source_snapshot_hash"] = "not-a-hash"
    must_fail("raw snapshot hash", bad)

    bad = base("REAL_TELEMETRY", False)
    add_sequence(bad, "PROSPECT_DISCOVERY", "a", PROSPECT, 1, 1)
    bad["receipts"][0]["receipt_type"] = "UNKNOWN_RECEIPT"
    must_fail("unknown receipt type", bad)

    bad = base("REAL_TELEMETRY", False)
    add_sequence(bad, "PROSPECT_DISCOVERY", "a", PROSPECT, 1, 1)
    bad["receipts"][0]["entry_lane"] = "INBOUND"
    must_fail("wrong lane", bad)

    bad = base("REAL_TELEMETRY", False)
    add_sequence(bad, "PROSPECT_DISCOVERY", "a", PROSPECT, 1, 1)
    bad["receipts"][0]["source_contract_id"] = "R10-PIPELINE-001"
    must_fail("source contract drift", bad)

    bad = base("REAL_TELEMETRY", False)
    add_sequence(bad, "PROSPECT_DISCOVERY", "a", PROSPECT, 1, 1)
    bad["receipts"][0]["source_state"] = "OFFER"
    must_fail("source state drift", bad)

    bad = base("REAL_TELEMETRY", False)
    add_sequence(bad, "PROSPECT_DISCOVERY", "a", PROSPECT, 1, 1)
    bad["receipts"][0]["occurred_at"] = "2026-08-20T04:00:00+03:00"
    must_fail("non UTC-Z timestamp", bad)

    bad = base("REAL_TELEMETRY", False)
    add_sequence(bad, "PROSPECT_DISCOVERY", "a", PROSPECT, 1, 1)
    bad["receipts"][0]["occurred_at"] = "2026-07-31T23:59:59Z"
    must_fail("outside cohort window", bad)

    bad = base("REAL_TELEMETRY", False)
    add_sequence(bad, "PROSPECT_DISCOVERY", "a", PROSPECT, 1, 1)
    collision = copy.deepcopy(bad["receipts"][0])
    collision["source_snapshot_hash"] = rid("e")
    bad["receipts"].append(collision)
    must_fail("receipt id collision", bad)

    drift = copy.deepcopy(ADAPTER_CONTRACT)
    drift["external_boundaries"]["transport_enabled"] = True
    must_fail("adapter external boundary drift", base(), contract=drift)

    target_drift = copy.deepcopy(R11_CONTRACT)
    target_drift["stage_sources"]["MATCHED"]["source_state"] = "WRONG"
    must_fail("target contract drift", base(), target=target_drift)

    try:
        ADAPTER.assert_output_path_safe(ROOT / "eucons" / "analytics" / "runtime-receipts.json")
    except ADAPTER.FunnelReceiptAdapterError:
        pass
    else:
        raise SystemExit("repository runtime output guard failed open")

    print("EUCONS R11 Client Finder funnel receipt adapter fail-closed regressions: PASS")


if __name__ == "__main__":
    main()
