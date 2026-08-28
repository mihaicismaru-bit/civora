#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIAG_CONTRACT_PATH = ROOT / "eucons" / "analytics" / "client_finder_funnel_diagnostics_contract.json"
DIAG_ENGINE_PATH = ROOT / "eucons" / "analytics" / "client_finder_funnel_diagnostics.py"
R11_CONTRACT_PATH = ROOT / "eucons" / "analytics" / "client_finder_funnel_analytics_contract.json"
R11_ENGINE_PATH = ROOT / "eucons" / "analytics" / "client_finder_funnel_analytics.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DIAG = load_module("eucons_r11_funnel_diagnostics", DIAG_ENGINE_PATH)
R11 = load_module("eucons_r11_funnel", R11_ENGINE_PATH)
DIAG_CONTRACT = json.loads(DIAG_CONTRACT_PATH.read_text(encoding="utf-8"))
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
        "records": [],
    }


def record(record_char: str, entity_char: str, lane: str, stage: str, source_contract_id: str, source_state: str, at: str) -> dict:
    return {
        "record_id": rid(record_char),
        "funnel_entity_id": rid(entity_char),
        "entry_lane": lane,
        "stage": stage,
        "source_contract_id": source_contract_id,
        "source_state": source_state,
        "occurred_at": at,
    }


PROSPECT = [
    ("PROSPECT_READY", "R06-CF-CONTRACT-001", "READY_FOR_SCORING"),
    ("MATCHED", "R07-PROSPECT-MATCH-001", "MATCHED_RESEARCH_CANDIDATE"),
    ("OUTREACH_PREPARED", "R08-ACTION-PACK-001", "READY_FOR_APPROVAL"),
    ("CONTACT_APPROVED", "R10-PIPELINE-001", "CONTACT_APPROVED"),
    ("OFFER", "R10-PIPELINE-001", "OFFER"),
    ("WON", "R10-PIPELINE-001", "WON"),
]

INBOUND = [
    ("INBOUND_COMPLETED", "R05-INBOUND-001", "COMPLETED"),
    ("MATCHED", "R07-PROSPECT-MATCH-001", "MATCHED_RESEARCH_CANDIDATE"),
    ("OUTREACH_PREPARED", "R08-ACTION-PACK-001", "READY_FOR_APPROVAL"),
    ("CONTACT_APPROVED", "R10-PIPELINE-001", "CONTACT_APPROVED"),
    ("OFFER", "R10-PIPELINE-001", "OFFER"),
    ("WON", "R10-PIPELINE-001", "WON"),
]


def add_sequence(payload: dict, lane: str, entity: str, items: list[tuple[str, str, str]], count: int, seed: int) -> None:
    chars = "0123456789abcdef"
    for index, (stage, contract_id, state) in enumerate(items[:count]):
        payload["records"].append(
            record(
                chars[(seed + index) % len(chars)],
                entity,
                lane,
                stage,
                contract_id,
                state,
                f"2026-08-20T{index + 1:02d}:00:00Z",
            )
        )


def snapshot(evidence_class: str, closed: bool, lane: str, count: int) -> dict:
    payload = base(evidence_class, closed)
    if lane == "INBOUND":
        add_sequence(payload, lane, "a", INBOUND, count, 1)
    else:
        add_sequence(payload, lane, "b", PROSPECT, count, 3)
    return R11.build_funnel(copy.deepcopy(payload), copy.deepcopy(R11_CONTRACT))


def rehash_source(value: dict) -> dict:
    out = copy.deepcopy(value)
    out.pop("snapshot_hash", None)
    out.pop("snapshot_id", None)
    out["snapshot_id"] = "R11-FNL-" + DIAG.sha256_json(out)[:24]
    out["snapshot_hash"] = DIAG.sha256_json(out)
    return out


def must_fail(name: str, source: dict, contract: dict | None = None, source_contract: dict | None = None) -> None:
    try:
        DIAG.build_diagnostics(
            copy.deepcopy(source),
            copy.deepcopy(contract or DIAG_CONTRACT),
            copy.deepcopy(source_contract or R11_CONTRACT),
        )
    except DIAG.FunnelDiagnosticsError:
        return
    raise SystemExit(f"{name}: funnel diagnostics failed open")


def main() -> None:
    non_evidence = snapshot("NON_EVIDENCE", False, "PROSPECT_DISCOVERY", 3)
    diag = DIAG.build_diagnostics(copy.deepcopy(non_evidence), copy.deepcopy(DIAG_CONTRACT), copy.deepcopy(R11_CONTRACT))
    assert diag["diagnostic_state"] == "UNKNOWN_NON_EVIDENCE"
    assert diag["operator_policy"]["performance_claims_enabled"] is False
    assert diag["operator_policy"]["benchmarking_enabled"] is False
    assert diag["operator_policy"]["ranking_enabled"] is False
    assert diag["internal_only"] is True
    for lane in diag["lanes"].values():
        assert all(row["value"] == "UNKNOWN" for row in lane["stage_counts"])
        assert all(row["value"] == "UNKNOWN" for row in lane["transition_rates"])
        assert all(
            row["reason_code"] == "NON_EVIDENCE_NUMERIC_OUTPUT_WITHHELD"
            for row in lane["stage_counts"] + lane["transition_rates"]
        )

    open_real = snapshot("REAL_TELEMETRY", False, "INBOUND", 3)
    diag = DIAG.build_diagnostics(copy.deepcopy(open_real), copy.deepcopy(DIAG_CONTRACT), copy.deepcopy(R11_CONTRACT))
    assert diag["diagnostic_state"] == "COUNTS_ONLY_OPEN_COHORT"
    inbound_counts = {row["stage"]: row for row in diag["lanes"]["INBOUND"]["stage_counts"]}
    assert inbound_counts["INBOUND_COMPLETED"]["value"] == 1
    assert inbound_counts["INBOUND_COMPLETED"]["reason_code"] == "AVAILABLE_INTERNAL_COUNT"
    assert all(
        row["value"] == "UNKNOWN" and row["reason_code"] == "OPEN_COHORT_RATES_WITHHELD"
        for row in diag["lanes"]["INBOUND"]["transition_rates"]
    )

    closed_real = snapshot("REAL_TELEMETRY", True, "PROSPECT_DISCOVERY", 6)
    assert closed_real["performance_claims_enabled"] is True
    diag = DIAG.build_diagnostics(copy.deepcopy(closed_real), copy.deepcopy(DIAG_CONTRACT), copy.deepcopy(R11_CONTRACT))
    assert diag["diagnostic_state"] == "RATES_AVAILABLE_INTERNAL_ONLY"
    assert diag["operator_policy"]["performance_claims_enabled"] is False
    prospect_rates = {row["transition"]: row for row in diag["lanes"]["PROSPECT_DISCOVERY"]["transition_rates"]}
    assert prospect_rates["PROSPECT_READY->MATCHED"]["value"] == 1.0
    assert prospect_rates["PROSPECT_READY->MATCHED"]["reason_code"] == "AVAILABLE_INTERNAL_RATE"
    assert all(
        row["value"] == "UNKNOWN" and row["reason_code"] == "ZERO_DENOMINATOR_RATE_UNKNOWN"
        for row in diag["lanes"]["INBOUND"]["transition_rates"]
    )

    repeated = DIAG.build_diagnostics(copy.deepcopy(closed_real), copy.deepcopy(DIAG_CONTRACT), copy.deepcopy(R11_CONTRACT))
    assert repeated == diag

    bad = copy.deepcopy(open_real)
    bad["email"] = "person@example.invalid"
    bad = rehash_source(bad)
    must_fail("PII leakage", bad)

    bad = copy.deepcopy(open_real)
    bad["record_count"] += 1
    must_fail("snapshot hash tamper", bad)

    bad = copy.deepcopy(open_real)
    bad["performance_state"] = "CLOSED_COHORT_REAL_TELEMETRY"
    bad = rehash_source(bad)
    must_fail("performance state drift", bad)

    bad = copy.deepcopy(open_real)
    key = "INBOUND_COMPLETED->MATCHED"
    bad["lanes"]["INBOUND"]["transition_rates"][key] = 0.5
    bad = rehash_source(bad)
    must_fail("open cohort rate leakage", bad)

    bad = copy.deepcopy(closed_real)
    bad["external_boundaries"]["public_reporting_enabled"] = True
    bad = rehash_source(bad)
    must_fail("source public reporting boundary", bad)

    bad = copy.deepcopy(closed_real)
    bad["window_end"] = "2026-08-28T13:00:00+03:00"
    bad = rehash_source(bad)
    must_fail("non UTC-Z source timestamp", bad)

    bad = copy.deepcopy(closed_real)
    bad["cohort_id"] = "raw-cohort"
    bad = rehash_source(bad)
    must_fail("raw cohort id", bad)

    bad = copy.deepcopy(closed_real)
    bad["source_lineage"].append({"source_contract_id": "R99-UNKNOWN", "source_state": "UNKNOWN"})
    bad["source_lineage"] = sorted(bad["source_lineage"], key=lambda row: (row["source_contract_id"], row["source_state"]))
    bad = rehash_source(bad)
    must_fail("unknown source lineage", bad)

    contract_drift = copy.deepcopy(DIAG_CONTRACT)
    contract_drift["operator_policy"]["performance_claims_enabled"] = True
    must_fail("diagnostic performance claim drift", closed_real, contract=contract_drift)

    source_contract_drift = copy.deepcopy(R11_CONTRACT)
    source_contract_drift["external_boundaries"]["public_reporting_enabled"] = True
    must_fail("source contract public reporting drift", closed_real, source_contract=source_contract_drift)

    try:
        DIAG.assert_output_path_safe(ROOT / "eucons" / "analytics" / "runtime-funnel-diagnostics.json")
    except DIAG.FunnelDiagnosticsError:
        pass
    else:
        raise SystemExit("repository runtime output guard failed open")

    print("EUCONS R11 Client Finder funnel diagnostics fail-closed regressions: PASS")


if __name__ == "__main__":
    main()
