#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "analytics" / "client_finder_funnel_diagnostics_contract.json"
DEFAULT_SOURCE_CONTRACT = EUCONS / "analytics" / "client_finder_funnel_analytics_contract.json"


class FunnelDiagnosticsError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def _scan_forbidden(value: Any, forbidden: set[str], path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in forbidden:
                raise FunnelDiagnosticsError(f"forbidden diagnostics key: {path}.{key}")
            _scan_forbidden(child, forbidden, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_forbidden(child, forbidden, f"{path}[{index}]")


def _require_exact_keys(raw: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(raw) - allowed
    missing = allowed - set(raw)
    if unknown:
        raise FunnelDiagnosticsError(f"{label} unsupported keys: {sorted(unknown)}")
    if missing:
        raise FunnelDiagnosticsError(f"{label} missing keys: {sorted(missing)}")


def _utc_z(value: Any, label: str) -> tuple[str, datetime]:
    text = str(value or "").strip()
    if not text or not text.endswith("Z"):
        raise FunnelDiagnosticsError(f"{label} must be RFC3339 UTC Z")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise FunnelDiagnosticsError(f"{label} invalid") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise FunnelDiagnosticsError(f"{label} must be UTC")
    return text, parsed


def _id64(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise FunnelDiagnosticsError(f"{label} must be lowercase sha256")
    return text


def _validate_contract(contract: dict[str, Any]) -> None:
    if contract.get("id") != "R11-FUNNEL-DIAGNOSTICS-001":
        raise FunnelDiagnosticsError("unexpected diagnostics contract id")
    if contract.get("product") != "EUCONS_COMMERCIAL_OS":
        raise FunnelDiagnosticsError("unexpected diagnostics product")
    if contract.get("source_contract_id") != "R11-FUNNEL-ANALYTICS-001":
        raise FunnelDiagnosticsError("diagnostics source contract drift")
    if contract.get("source_engine_id") != "EUCONS_R11_CLIENT_FINDER_FUNNEL_ANALYTICS":
        raise FunnelDiagnosticsError("diagnostics source engine drift")
    expected_boundaries = {
        "network_fetch": False,
        "transport_enabled": False,
        "persistence_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
        "offer_send_enabled": False,
        "outreach_enabled": False,
        "public_reporting_enabled": False,
    }
    if contract.get("external_boundaries") != expected_boundaries:
        raise FunnelDiagnosticsError("diagnostics external boundary drift")
    expected_operator_policy = {
        "internal_only": True,
        "performance_claims_enabled": False,
        "benchmarking_enabled": False,
        "ranking_enabled": False,
        "trend_claims_enabled": False,
        "forecasting_enabled": False,
        "conversion_claims_enabled": False,
        "public_copy_generation_enabled": False,
        "diagnostic_interpretation": "DESCRIPTIVE_AVAILABILITY_ONLY",
    }
    if contract.get("operator_policy") != expected_operator_policy:
        raise FunnelDiagnosticsError("operator diagnostics policy drift")


def _validate_source_contract(source_contract: dict[str, Any], contract: dict[str, Any]) -> None:
    if source_contract.get("id") != contract["source_contract_id"]:
        raise FunnelDiagnosticsError("unexpected source analytics contract id")
    if source_contract.get("engine_id") != contract["source_engine_id"]:
        raise FunnelDiagnosticsError("unexpected source analytics engine id")
    if source_contract.get("product") != contract["product"]:
        raise FunnelDiagnosticsError("source analytics product drift")
    expected_source_boundaries = {
        "network_fetch": False,
        "transport_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
        "offer_send_enabled": False,
        "outreach_enabled": False,
        "public_reporting_enabled": False,
    }
    if source_contract.get("external_boundaries") != expected_source_boundaries:
        raise FunnelDiagnosticsError("source analytics external boundary drift")
    if source_contract.get("output", {}).get("internal_only") is not True:
        raise FunnelDiagnosticsError("source analytics must remain internal only")
    if source_contract.get("output", {}).get("unknown_value") != "UNKNOWN":
        raise FunnelDiagnosticsError("source analytics unknown sentinel drift")


def _validate_snapshot_integrity(snapshot: dict[str, Any]) -> None:
    snapshot_id = str(snapshot.get("snapshot_id") or "")
    snapshot_hash = str(snapshot.get("snapshot_hash") or "")
    suffix = snapshot_id.removeprefix("R11-FNL-")
    if not snapshot_id.startswith("R11-FNL-") or not re.fullmatch(r"[0-9a-f]{24}", suffix):
        raise FunnelDiagnosticsError("invalid source snapshot_id")
    _id64(snapshot_hash, "source snapshot_hash")

    without_hash = dict(snapshot)
    without_hash.pop("snapshot_hash")
    if sha256_json(without_hash) != snapshot_hash:
        raise FunnelDiagnosticsError("source snapshot_hash mismatch")

    basis = dict(without_hash)
    basis.pop("snapshot_id")
    expected_id = "R11-FNL-" + sha256_json(basis)[:24]
    if expected_id != snapshot_id:
        raise FunnelDiagnosticsError("source snapshot_id mismatch")


def _expected_source_policy(snapshot: dict[str, Any], source_contract: dict[str, Any]) -> dict[str, Any]:
    evidence_class = snapshot["evidence_class"]
    closed = snapshot["cohort_closed"]
    if evidence_class == "NON_EVIDENCE":
        return source_contract["non_evidence_policy"]
    if evidence_class == "REAL_TELEMETRY" and not closed:
        return source_contract["open_real_cohort_policy"]
    if evidence_class == "REAL_TELEMETRY" and closed:
        return source_contract["closed_real_cohort_policy"]
    raise FunnelDiagnosticsError("unsupported evidence/cohort state")


def _validate_source_snapshot(snapshot: dict[str, Any], contract: dict[str, Any], source_contract: dict[str, Any]) -> None:
    if not isinstance(snapshot, dict):
        raise FunnelDiagnosticsError("source snapshot must be object")
    _scan_forbidden(snapshot, set(contract["privacy"]["forbidden_keys"]))
    allowed_top = {
        "schema_version",
        "product",
        "contract_id",
        "engine_id",
        "cohort_id",
        "evidence_class",
        "cohort_closed",
        "window_start",
        "window_end",
        "as_of",
        "performance_state",
        "performance_claims_enabled",
        "record_count",
        "entity_count",
        "lanes",
        "source_lineage",
        "internal_only",
        "external_boundaries",
        "snapshot_id",
        "snapshot_hash",
    }
    _require_exact_keys(snapshot, allowed_top, "source snapshot")
    if snapshot["schema_version"] != source_contract["output"]["schema_version"]:
        raise FunnelDiagnosticsError("source snapshot schema drift")
    if snapshot["product"] != contract["product"]:
        raise FunnelDiagnosticsError("source snapshot product mismatch")
    if snapshot["contract_id"] != contract["source_contract_id"]:
        raise FunnelDiagnosticsError("source snapshot contract mismatch")
    if snapshot["engine_id"] != contract["source_engine_id"]:
        raise FunnelDiagnosticsError("source snapshot engine mismatch")
    if snapshot["internal_only"] is not True:
        raise FunnelDiagnosticsError("source snapshot must remain internal only")
    if snapshot["external_boundaries"] != source_contract["external_boundaries"]:
        raise FunnelDiagnosticsError("source snapshot boundary drift")
    if not isinstance(snapshot["cohort_closed"], bool):
        raise FunnelDiagnosticsError("source cohort_closed must be boolean")
    if snapshot["evidence_class"] not in source_contract["evidence_classes"]:
        raise FunnelDiagnosticsError("source evidence_class invalid")
    _id64(snapshot["cohort_id"], "source cohort_id")
    _, start = _utc_z(snapshot["window_start"], "source window_start")
    _, end = _utc_z(snapshot["window_end"], "source window_end")
    _, as_of = _utc_z(snapshot["as_of"], "source as_of")
    if not start < end:
        raise FunnelDiagnosticsError("source window_start must be before window_end")
    if end > as_of:
        raise FunnelDiagnosticsError("source window_end cannot be after as_of")

    expected_policy = _expected_source_policy(snapshot, source_contract)
    if snapshot["performance_state"] != expected_policy["state"]:
        raise FunnelDiagnosticsError("source performance_state mismatch")
    if snapshot["performance_claims_enabled"] is not expected_policy["performance_claims_enabled"]:
        raise FunnelDiagnosticsError("source performance-claim policy mismatch")

    unknown = source_contract["output"]["unknown_value"]
    real = snapshot["evidence_class"] == "REAL_TELEMETRY"
    closed = snapshot["cohort_closed"]
    if real:
        if not isinstance(snapshot["record_count"], int) or isinstance(snapshot["record_count"], bool) or snapshot["record_count"] < 0:
            raise FunnelDiagnosticsError("real telemetry record_count invalid")
        if not isinstance(snapshot["entity_count"], int) or isinstance(snapshot["entity_count"], bool) or snapshot["entity_count"] < 0:
            raise FunnelDiagnosticsError("real telemetry entity_count invalid")
    else:
        if snapshot["record_count"] != unknown or snapshot["entity_count"] != unknown:
            raise FunnelDiagnosticsError("NON_EVIDENCE aggregate leakage")

    if set(snapshot["lanes"]) != set(source_contract["entry_lanes"]):
        raise FunnelDiagnosticsError("source lane set drift")
    for lane, stages in source_contract["entry_lanes"].items():
        lane_row = snapshot["lanes"].get(lane)
        if not isinstance(lane_row, dict):
            raise FunnelDiagnosticsError(f"source lane {lane} must be object")
        _require_exact_keys(lane_row, {"stages", "stage_counts", "transition_rates"}, f"source lane {lane}")
        if lane_row["stages"] != stages:
            raise FunnelDiagnosticsError(f"source lane {lane} stage order drift")
        if list(lane_row["stage_counts"]) != stages:
            raise FunnelDiagnosticsError(f"source lane {lane} count key order drift")
        expected_transitions = [f"{before}->{after}" for before, after in zip(stages, stages[1:])]
        if list(lane_row["transition_rates"]) != expected_transitions:
            raise FunnelDiagnosticsError(f"source lane {lane} rate key order drift")
        for stage, value in lane_row["stage_counts"].items():
            if real:
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise FunnelDiagnosticsError(f"source count invalid: {lane}.{stage}")
            elif value != unknown:
                raise FunnelDiagnosticsError(f"NON_EVIDENCE count leakage: {lane}.{stage}")
        for transition, value in lane_row["transition_rates"].items():
            if not real or not closed:
                if value != unknown:
                    raise FunnelDiagnosticsError(f"withheld source rate leaked: {lane}.{transition}")
            elif value != unknown:
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise FunnelDiagnosticsError(f"source rate invalid: {lane}.{transition}")
                if value < 0 or value > 1:
                    raise FunnelDiagnosticsError(f"source rate outside 0..1: {lane}.{transition}")

    allowed_lineage = {
        (row["source_contract_id"], row["source_state"])
        for row in source_contract["stage_sources"].values()
    }
    if not isinstance(snapshot["source_lineage"], list):
        raise FunnelDiagnosticsError("source_lineage must be list")
    previous: tuple[str, str] | None = None
    for index, row in enumerate(snapshot["source_lineage"]):
        if not isinstance(row, dict):
            raise FunnelDiagnosticsError(f"source_lineage[{index}] must be object")
        _require_exact_keys(row, {"source_contract_id", "source_state"}, f"source_lineage[{index}]")
        pair = (row["source_contract_id"], row["source_state"])
        if pair not in allowed_lineage:
            raise FunnelDiagnosticsError("source lineage contains unknown state")
        if previous is not None and pair <= previous:
            raise FunnelDiagnosticsError("source lineage must be strictly sorted")
        previous = pair

    _validate_snapshot_integrity(snapshot)


def _diagnostic_reason(performance_state: str, value: Any, value_kind: str, unknown: str) -> str:
    if value_kind == "COUNT":
        if performance_state == "UNKNOWN_NON_EVIDENCE":
            return "NON_EVIDENCE_NUMERIC_OUTPUT_WITHHELD"
        return "AVAILABLE_INTERNAL_COUNT"
    if performance_state == "UNKNOWN_NON_EVIDENCE":
        return "NON_EVIDENCE_NUMERIC_OUTPUT_WITHHELD"
    if performance_state == "COUNTS_ONLY_OPEN_COHORT":
        return "OPEN_COHORT_RATES_WITHHELD"
    if value == unknown:
        return "ZERO_DENOMINATOR_RATE_UNKNOWN"
    return "AVAILABLE_INTERNAL_RATE"


def build_diagnostics(snapshot: dict[str, Any], contract: dict[str, Any], source_contract: dict[str, Any]) -> dict[str, Any]:
    _validate_contract(contract)
    _validate_source_contract(source_contract, contract)
    _validate_source_snapshot(snapshot, contract, source_contract)

    performance_state = snapshot["performance_state"]
    state_policy = contract["diagnostic_states"].get(performance_state)
    if not isinstance(state_policy, dict):
        raise FunnelDiagnosticsError("missing diagnostic policy for source state")
    unknown = source_contract["output"]["unknown_value"]

    lanes: dict[str, Any] = {}
    for lane, source_lane in snapshot["lanes"].items():
        count_rows = []
        for stage in source_lane["stages"]:
            value = source_lane["stage_counts"][stage]
            count_rows.append(
                {
                    "stage": stage,
                    "value": value,
                    "availability": "UNKNOWN" if value == unknown else "AVAILABLE",
                    "reason_code": _diagnostic_reason(performance_state, value, "COUNT", unknown),
                }
            )
        rate_rows = []
        for transition, value in source_lane["transition_rates"].items():
            rate_rows.append(
                {
                    "transition": transition,
                    "value": value,
                    "availability": "UNKNOWN" if value == unknown else "AVAILABLE",
                    "reason_code": _diagnostic_reason(performance_state, value, "RATE", unknown),
                }
            )
        lanes[lane] = {
            "counts_mode": state_policy["counts_mode"],
            "rates_mode": state_policy["rates_mode"],
            "stage_counts": count_rows,
            "transition_rates": rate_rows,
        }

    core = {
        "schema_version": contract["output"]["schema_version"],
        "product": contract["product"],
        "contract_id": contract["id"],
        "engine_id": contract["engine_id"],
        "source_contract_id": snapshot["contract_id"],
        "source_snapshot_id": snapshot["snapshot_id"],
        "source_snapshot_hash": snapshot["snapshot_hash"],
        "cohort_id": snapshot["cohort_id"],
        "evidence_class": snapshot["evidence_class"],
        "cohort_closed": snapshot["cohort_closed"],
        "window_start": snapshot["window_start"],
        "window_end": snapshot["window_end"],
        "as_of": snapshot["as_of"],
        "source_performance_state": performance_state,
        "diagnostic_state": state_policy["diagnostic_state"],
        "reason_codes": state_policy["reason_codes"],
        "record_count": snapshot["record_count"],
        "entity_count": snapshot["entity_count"],
        "lanes": lanes,
        "source_lineage": snapshot["source_lineage"],
        "operator_policy": contract["operator_policy"],
        "internal_only": True,
        "external_boundaries": contract["external_boundaries"],
    }
    core["diagnostic_id"] = "R11-DIAG-" + sha256_json(core)[:24]
    core["diagnostic_hash"] = sha256_json(core)
    return core


def assert_output_path_safe(path: Path) -> None:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return
    raise FunnelDiagnosticsError("runtime funnel diagnostics cannot be written under repository root")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--source-contract", default=str(DEFAULT_SOURCE_CONTRACT))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    result = build_diagnostics(
        load_json(Path(args.input)),
        load_json(Path(args.contract)),
        load_json(Path(args.source_contract)),
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        assert_output_path_safe(output)
        output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
