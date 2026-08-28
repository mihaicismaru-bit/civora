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
DEFAULT_CONTRACT = EUCONS / "analytics" / "client_finder_funnel_receipt_adapter_contract.json"
DEFAULT_TARGET_CONTRACT = EUCONS / "analytics" / "client_finder_funnel_analytics_contract.json"


class FunnelReceiptAdapterError(ValueError):
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
                raise FunnelReceiptAdapterError(f"forbidden receipt adapter key: {path}.{key}")
            _scan_forbidden(child, forbidden, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_forbidden(child, forbidden, f"{path}[{index}]")


def _require_exact_keys(raw: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(raw) - allowed
    missing = allowed - set(raw)
    if unknown:
        raise FunnelReceiptAdapterError(f"{label} unsupported keys: {sorted(unknown)}")
    if missing:
        raise FunnelReceiptAdapterError(f"{label} missing keys: {sorted(missing)}")


def _utc_z(value: Any, label: str) -> tuple[str, datetime]:
    text = str(value or "").strip()
    if not text or not text.endswith("Z"):
        raise FunnelReceiptAdapterError(f"{label} must be RFC3339 UTC Z")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise FunnelReceiptAdapterError(f"{label} invalid") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise FunnelReceiptAdapterError(f"{label} must be UTC")
    return text, parsed


def _id64(value: Any, label: str, pattern: re.Pattern[str]) -> str:
    text = str(value or "").strip()
    if not pattern.fullmatch(text):
        raise FunnelReceiptAdapterError(f"{label} must be lowercase sha256")
    return text


def _validate_contract(contract: dict[str, Any], target: dict[str, Any]) -> None:
    if contract.get("id") != "R11-FUNNEL-RECEIPT-ADAPTER-001":
        raise FunnelReceiptAdapterError("unexpected receipt adapter contract id")
    if contract.get("product") != "EUCONS_COMMERCIAL_OS":
        raise FunnelReceiptAdapterError("unexpected product")
    if contract.get("source_mode") != "PREFETCHED_INTERNAL_RECEIPT_MANIFEST_ONLY":
        raise FunnelReceiptAdapterError("receipt adapter source mode drift")
    expected_boundaries = {
        "network_fetch": False,
        "transport_enabled": False,
        "repository_runtime_storage": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
        "offer_send_enabled": False,
        "outreach_enabled": False,
        "public_reporting_enabled": False,
    }
    if contract.get("external_boundaries") != expected_boundaries:
        raise FunnelReceiptAdapterError("receipt adapter external boundary drift")

    target_decl = contract.get("target_contract")
    if not isinstance(target_decl, dict):
        raise FunnelReceiptAdapterError("target contract declaration missing")
    if target.get("id") != target_decl.get("id"):
        raise FunnelReceiptAdapterError("target funnel contract id drift")
    if target.get("product") != contract.get("product"):
        raise FunnelReceiptAdapterError("target funnel product drift")
    if target.get("source_mode") != target_decl.get("required_source_mode"):
        raise FunnelReceiptAdapterError("target funnel source mode drift")

    target_stage_sources = target.get("stage_sources")
    target_entry_lanes = target.get("entry_lanes")
    if not isinstance(target_stage_sources, dict) or not isinstance(target_entry_lanes, dict):
        raise FunnelReceiptAdapterError("target funnel contract shape invalid")
    for receipt_type, mapping in contract.get("receipt_types", {}).items():
        if not isinstance(mapping, dict):
            raise FunnelReceiptAdapterError(f"receipt mapping invalid: {receipt_type}")
        stage = mapping.get("stage")
        expected_source = target_stage_sources.get(stage)
        if expected_source != {
            "source_contract_id": mapping.get("source_contract_id"),
            "source_state": mapping.get("source_state"),
        }:
            raise FunnelReceiptAdapterError(f"receipt mapping target drift: {receipt_type}")
        for lane in mapping.get("entry_lanes", []):
            stages = target_entry_lanes.get(lane)
            if not isinstance(stages, list) or stage not in stages:
                raise FunnelReceiptAdapterError(f"receipt lane mapping target drift: {receipt_type}")


def _normalize_receipts(
    payload: dict[str, Any],
    contract: dict[str, Any],
    target: dict[str, Any],
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    raw_receipts = payload.get("receipts")
    if not isinstance(raw_receipts, list):
        raise FunnelReceiptAdapterError("receipts must be a list")

    pattern = re.compile(contract["privacy"]["pseudonymous_id_pattern"])
    mappings = contract["receipt_types"]
    target_stages = target["entry_lanes"]
    stage_index = {
        lane: {stage: index for index, stage in enumerate(stages)}
        for lane, stages in target_stages.items()
    }
    allowed_keys = {
        "receipt_id",
        "funnel_entity_id",
        "entry_lane",
        "receipt_type",
        "source_contract_id",
        "source_state",
        "source_snapshot_hash",
        "occurred_at",
    }

    seen_receipts: dict[str, dict[str, Any]] = {}
    normalized: list[dict[str, Any]] = []

    for index, raw in enumerate(raw_receipts):
        if not isinstance(raw, dict):
            raise FunnelReceiptAdapterError(f"receipt[{index}] must be object")
        _require_exact_keys(raw, allowed_keys, f"receipt[{index}]")

        receipt_id = _id64(raw["receipt_id"], f"receipt[{index}].receipt_id", pattern)
        entity_id = _id64(
            raw["funnel_entity_id"], f"receipt[{index}].funnel_entity_id", pattern
        )
        snapshot_hash = _id64(
            raw["source_snapshot_hash"],
            f"receipt[{index}].source_snapshot_hash",
            pattern,
        )
        receipt_type = str(raw["receipt_type"]).strip()
        mapping = mappings.get(receipt_type)
        if not isinstance(mapping, dict):
            raise FunnelReceiptAdapterError(f"receipt[{index}] unsupported receipt_type")

        lane = str(raw["entry_lane"]).strip()
        if lane not in mapping["entry_lanes"]:
            raise FunnelReceiptAdapterError(f"receipt[{index}] invalid entry_lane for receipt_type")
        if raw["source_contract_id"] != mapping["source_contract_id"]:
            raise FunnelReceiptAdapterError(f"receipt[{index}] source contract mismatch")
        if raw["source_state"] != mapping["source_state"]:
            raise FunnelReceiptAdapterError(f"receipt[{index}] source state mismatch")

        occurred_text, occurred = _utc_z(raw["occurred_at"], f"receipt[{index}].occurred_at")
        if occurred < start or occurred > end:
            raise FunnelReceiptAdapterError(f"receipt[{index}] outside cohort window")

        canonical_receipt = {
            "receipt_id": receipt_id,
            "funnel_entity_id": entity_id,
            "entry_lane": lane,
            "receipt_type": receipt_type,
            "source_contract_id": mapping["source_contract_id"],
            "source_state": mapping["source_state"],
            "source_snapshot_hash": snapshot_hash,
            "occurred_at": occurred_text,
        }
        previous = seen_receipts.get(receipt_id)
        if previous is not None:
            if previous != canonical_receipt:
                raise FunnelReceiptAdapterError("receipt_id collision with different payload")
            continue
        seen_receipts[receipt_id] = canonical_receipt

        record_basis = {
            "receipt_id": receipt_id,
            "source_snapshot_hash": snapshot_hash,
            "funnel_entity_id": entity_id,
            "entry_lane": lane,
            "stage": mapping["stage"],
            "source_contract_id": mapping["source_contract_id"],
            "source_state": mapping["source_state"],
            "occurred_at": occurred_text,
        }
        normalized.append(
            {
                "record_id": sha256_json(record_basis),
                "funnel_entity_id": entity_id,
                "entry_lane": lane,
                "stage": mapping["stage"],
                "source_contract_id": mapping["source_contract_id"],
                "source_state": mapping["source_state"],
                "occurred_at": occurred_text,
                "_occurred_dt": occurred,
                "_stage_index": stage_index[lane][mapping["stage"]],
            }
        )

    normalized.sort(
        key=lambda row: (
            row["_occurred_dt"],
            row["entry_lane"],
            row["funnel_entity_id"],
            row["_stage_index"],
            row["record_id"],
        )
    )
    for row in normalized:
        row.pop("_occurred_dt", None)
        row.pop("_stage_index", None)
    return normalized


def build_r11_input(
    payload: dict[str, Any],
    contract: dict[str, Any],
    target_contract: dict[str, Any],
) -> dict[str, Any]:
    _validate_contract(contract, target_contract)
    if not isinstance(payload, dict):
        raise FunnelReceiptAdapterError("payload must be object")
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
        "receipts",
    }
    _require_exact_keys(payload, allowed_top, "payload")
    if payload["schema_version"] != 1:
        raise FunnelReceiptAdapterError("unsupported payload schema_version")
    if payload["product"] != contract["product"]:
        raise FunnelReceiptAdapterError("product mismatch")

    pattern = re.compile(contract["privacy"]["pseudonymous_id_pattern"])
    cohort_id = _id64(payload["cohort_id"], "cohort_id", pattern)
    evidence_class = str(payload["evidence_class"]).strip()
    if evidence_class not in contract["evidence_classes"]:
        raise FunnelReceiptAdapterError("unsupported evidence_class")
    if not isinstance(payload["cohort_closed"], bool):
        raise FunnelReceiptAdapterError("cohort_closed must be boolean")

    start_text, start = _utc_z(payload["window_start"], "window_start")
    end_text, end = _utc_z(payload["window_end"], "window_end")
    as_of_text, as_of = _utc_z(payload["as_of"], "as_of")
    if not start < end:
        raise FunnelReceiptAdapterError("window_start must be before window_end")
    if end > as_of:
        raise FunnelReceiptAdapterError("window_end cannot be after as_of")

    records = _normalize_receipts(payload, contract, target_contract, start, end)
    return {
        "schema_version": target_contract["output"]["schema_version"],
        "product": contract["product"],
        "cohort_id": cohort_id,
        "evidence_class": evidence_class,
        "cohort_closed": payload["cohort_closed"],
        "window_start": start_text,
        "window_end": end_text,
        "as_of": as_of_text,
        "records": records,
    }


def assert_output_path_safe(path: Path) -> None:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return
    raise FunnelReceiptAdapterError("runtime receipt normalization cannot be written under repository root")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--target-contract", default=str(DEFAULT_TARGET_CONTRACT))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    result = build_r11_input(
        load_json(Path(args.input)),
        load_json(Path(args.contract)),
        load_json(Path(args.target_contract)),
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
