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
DEFAULT_CONTRACT = EUCONS / "analytics" / "client_finder_funnel_analytics_contract.json"


class FunnelAnalyticsError(ValueError):
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
                raise FunnelAnalyticsError(f"forbidden funnel analytics key: {path}.{key}")
            _scan_forbidden(child, forbidden, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_forbidden(child, forbidden, f"{path}[{index}]")


def _utc_z(value: Any, label: str) -> tuple[str, datetime]:
    text = str(value or "").strip()
    if not text or not text.endswith("Z"):
        raise FunnelAnalyticsError(f"{label} must be RFC3339 UTC Z")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise FunnelAnalyticsError(f"{label} invalid") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise FunnelAnalyticsError(f"{label} must be UTC")
    return text, parsed


def _id64(value: Any, label: str, pattern: re.Pattern[str]) -> str:
    text = str(value or "").strip()
    if not pattern.fullmatch(text):
        raise FunnelAnalyticsError(f"{label} must be lowercase sha256")
    return text


def _require_exact_keys(raw: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(raw) - allowed
    missing = allowed - set(raw)
    if unknown:
        raise FunnelAnalyticsError(f"{label} unsupported keys: {sorted(unknown)}")
    if missing:
        raise FunnelAnalyticsError(f"{label} missing keys: {sorted(missing)}")


def _validate_contract(contract: dict[str, Any]) -> None:
    if contract.get("id") != "R11-FUNNEL-ANALYTICS-001":
        raise FunnelAnalyticsError("unexpected funnel analytics contract id")
    if contract.get("product") != "EUCONS_COMMERCIAL_OS":
        raise FunnelAnalyticsError("unexpected product")
    expected_boundaries = {
        "network_fetch": False,
        "transport_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
        "offer_send_enabled": False,
        "outreach_enabled": False,
        "public_reporting_enabled": False,
    }
    if contract.get("external_boundaries") != expected_boundaries:
        raise FunnelAnalyticsError("external boundary drift")
    if contract.get("source_mode") != "PREFETCHED_INTERNAL_LIFECYCLE_SNAPSHOTS_ONLY":
        raise FunnelAnalyticsError("source mode drift")


def _records(
    payload: dict[str, Any],
    contract: dict[str, Any],
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        raise FunnelAnalyticsError("records must be a list")
    pattern = re.compile(contract["privacy"]["pseudonymous_id_pattern"])
    stage_sources = contract["stage_sources"]
    lane_stages = {lane: set(stages) for lane, stages in contract["entry_lanes"].items()}
    seen_record_ids: dict[str, dict[str, Any]] = {}
    normalized: list[dict[str, Any]] = []

    allowed_keys = {
        "record_id",
        "funnel_entity_id",
        "entry_lane",
        "stage",
        "source_contract_id",
        "source_state",
        "occurred_at",
    }

    for index, raw in enumerate(raw_records):
        if not isinstance(raw, dict):
            raise FunnelAnalyticsError(f"record[{index}] must be object")
        _require_exact_keys(raw, allowed_keys, f"record[{index}]")
        record_id = _id64(raw["record_id"], f"record[{index}].record_id", pattern)
        entity_id = _id64(raw["funnel_entity_id"], f"record[{index}].funnel_entity_id", pattern)
        lane = str(raw["entry_lane"]).strip()
        if lane not in contract["entry_lanes"]:
            raise FunnelAnalyticsError(f"record[{index}] invalid entry_lane")
        stage = str(raw["stage"]).strip()
        if stage not in stage_sources or stage not in lane_stages[lane]:
            raise FunnelAnalyticsError(f"record[{index}] invalid stage for lane")
        expected = stage_sources[stage]
        if raw["source_contract_id"] != expected["source_contract_id"]:
            raise FunnelAnalyticsError(f"record[{index}] source contract mismatch")
        if raw["source_state"] != expected["source_state"]:
            raise FunnelAnalyticsError(f"record[{index}] source state mismatch")
        occurred_text, occurred = _utc_z(raw["occurred_at"], f"record[{index}].occurred_at")
        if occurred < start or occurred > end:
            raise FunnelAnalyticsError(f"record[{index}] outside cohort window")
        row = {
            "record_id": record_id,
            "funnel_entity_id": entity_id,
            "entry_lane": lane,
            "stage": stage,
            "source_contract_id": raw["source_contract_id"],
            "source_state": raw["source_state"],
            "occurred_at": occurred_text,
            "_occurred_dt": occurred,
        }
        previous = seen_record_ids.get(record_id)
        if previous is not None:
            comparable = {key: value for key, value in row.items() if key != "_occurred_dt"}
            previous_comparable = {
                key: value for key, value in previous.items() if key != "_occurred_dt"
            }
            if comparable != previous_comparable:
                raise FunnelAnalyticsError("record_id collision with different payload")
            continue
        seen_record_ids[record_id] = row
        normalized.append(row)
    return normalized


def _validate_entity_sequences(
    records: list[dict[str, Any]],
    contract: dict[str, Any],
    require_contiguous: bool,
) -> None:
    by_entity: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_entity.setdefault(record["funnel_entity_id"], []).append(record)

    for entity_id, rows in by_entity.items():
        lanes = {row["entry_lane"] for row in rows}
        if len(lanes) != 1:
            raise FunnelAnalyticsError(f"entity {entity_id} crosses entry lanes")
        lane = next(iter(lanes))
        ordered_stages = contract["entry_lanes"][lane]
        stage_index = {stage: index for index, stage in enumerate(ordered_stages)}
        rows.sort(key=lambda row: (row["_occurred_dt"], stage_index[row["stage"]], row["record_id"]))
        seen_stages: set[str] = set()
        indexes: list[int] = []
        previous_time: datetime | None = None
        for row in rows:
            stage = row["stage"]
            if stage in seen_stages:
                raise FunnelAnalyticsError(f"entity {entity_id} repeats stage {stage}")
            seen_stages.add(stage)
            index = stage_index[stage]
            indexes.append(index)
            if previous_time is not None and row["_occurred_dt"] < previous_time:
                raise FunnelAnalyticsError(f"entity {entity_id} timestamp regression")
            previous_time = row["_occurred_dt"]
        if indexes != sorted(indexes):
            raise FunnelAnalyticsError(f"entity {entity_id} stage order regression")
        if require_contiguous:
            expected = list(range(len(indexes)))
            if indexes != expected:
                raise FunnelAnalyticsError(
                    f"entity {entity_id} closed cohort requires contiguous prefix"
                )


def _lane_counts(
    records: list[dict[str, Any]],
    contract: dict[str, Any],
    lane: str,
) -> dict[str, int]:
    entity_sets = {stage: set() for stage in contract["entry_lanes"][lane]}
    for row in records:
        if row["entry_lane"] == lane:
            entity_sets[row["stage"]].add(row["funnel_entity_id"])
    return {stage: len(entity_sets[stage]) for stage in contract["entry_lanes"][lane]}


def _rates(counts: dict[str, int], stages: list[str]) -> dict[str, float | str]:
    out: dict[str, float | str] = {}
    for before, after in zip(stages, stages[1:]):
        denominator = counts[before]
        numerator = counts[after]
        key = f"{before}->{after}"
        if denominator == 0:
            out[key] = "UNKNOWN"
        else:
            out[key] = round(numerator / denominator, 6)
    return out


def build_funnel(payload: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    _validate_contract(contract)
    if not isinstance(payload, dict):
        raise FunnelAnalyticsError("payload must be object")
    _scan_forbidden(payload, set(contract["privacy"]["forbidden_keys"]))
    allowed_top = {
        "schema_version",
        "product",
        "cohort_id",
        "evidence_class",
        "cohort_closed",
        "window_start",
        "window_end",
        "as_of",
        "records",
    }
    _require_exact_keys(payload, allowed_top, "payload")
    if payload["schema_version"] != 1:
        raise FunnelAnalyticsError("unsupported payload schema_version")
    if payload["product"] != contract["product"]:
        raise FunnelAnalyticsError("product mismatch")
    pattern = re.compile(contract["privacy"]["pseudonymous_id_pattern"])
    cohort_id = _id64(payload["cohort_id"], "cohort_id", pattern)
    evidence_class = str(payload["evidence_class"]).strip()
    if evidence_class not in contract["evidence_classes"]:
        raise FunnelAnalyticsError("unsupported evidence_class")
    if not isinstance(payload["cohort_closed"], bool):
        raise FunnelAnalyticsError("cohort_closed must be boolean")
    start_text, start = _utc_z(payload["window_start"], "window_start")
    end_text, end = _utc_z(payload["window_end"], "window_end")
    as_of_text, as_of = _utc_z(payload["as_of"], "as_of")
    if not start < end:
        raise FunnelAnalyticsError("window_start must be before window_end")
    if end > as_of:
        raise FunnelAnalyticsError("window_end cannot be after as_of")

    records = _records(payload, contract, start, end)
    require_contiguous = evidence_class == "REAL_TELEMETRY" and payload["cohort_closed"]
    _validate_entity_sequences(records, contract, require_contiguous=require_contiguous)

    unknown = contract["output"]["unknown_value"]
    lane_outputs: dict[str, Any] = {}
    real_telemetry = evidence_class == "REAL_TELEMETRY"
    closed = payload["cohort_closed"]

    for lane, stages in contract["entry_lanes"].items():
        numeric_counts = _lane_counts(records, contract, lane)
        if not real_telemetry:
            counts: dict[str, int | str] = {stage: unknown for stage in stages}
            rates: dict[str, float | str] = {
                f"{before}->{after}": unknown
                for before, after in zip(stages, stages[1:])
            }
        elif not closed:
            counts = numeric_counts
            rates = {
                f"{before}->{after}": unknown
                for before, after in zip(stages, stages[1:])
            }
        else:
            counts = numeric_counts
            rates = _rates(numeric_counts, stages)
        lane_outputs[lane] = {
            "stages": stages,
            "stage_counts": counts,
            "transition_rates": rates,
        }

    if not real_telemetry:
        policy = contract["non_evidence_policy"]
    elif not closed:
        policy = contract["open_real_cohort_policy"]
    else:
        policy = contract["closed_real_cohort_policy"]

    lineage = sorted(
        {(row["source_contract_id"], row["source_state"]) for row in records}
    )
    lineage_rows = [
        {"source_contract_id": contract_id, "source_state": state}
        for contract_id, state in lineage
    ]
    record_count = len(records) if real_telemetry else unknown
    entity_count = (
        len({row["funnel_entity_id"] for row in records}) if real_telemetry else unknown
    )

    core = {
        "schema_version": contract["output"]["schema_version"],
        "product": contract["product"],
        "contract_id": contract["id"],
        "engine_id": contract["engine_id"],
        "cohort_id": cohort_id,
        "evidence_class": evidence_class,
        "cohort_closed": closed,
        "window_start": start_text,
        "window_end": end_text,
        "as_of": as_of_text,
        "performance_state": policy["state"],
        "performance_claims_enabled": policy["performance_claims_enabled"],
        "record_count": record_count,
        "entity_count": entity_count,
        "lanes": lane_outputs,
        "source_lineage": lineage_rows,
        "internal_only": True,
        "external_boundaries": contract["external_boundaries"],
    }
    core["snapshot_id"] = "R11-FNL-" + sha256_json(core)[:24]
    core["snapshot_hash"] = sha256_json(core)
    return core


def assert_output_path_safe(path: Path) -> None:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return
    raise FunnelAnalyticsError("runtime funnel analytics cannot be written under repository root")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    result = build_funnel(load_json(Path(args.input)), load_json(Path(args.contract)))
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        assert_output_path_safe(output)
        output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
