#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
CONTRACT_PATH = EUCONS / "prospects" / "client_finder_contract.json"
VALIDATOR_PATH = EUCONS / "validation" / "validate_client_finder_contract.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("client_finder_contract_validator", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load Client Finder validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = load_validator()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def empty_state(reference_time: str) -> dict[str, Any]:
    VALIDATOR.parse_time(reference_time)
    return {
        "schema_version": 1,
        "engine_id": "EUCONS_R06_CLIENT_FINDER_ENGINE",
        "evidence_label": "NON_EVIDENCE_UNTIL_SOURCE_VALIDATED",
        "reference_time": reference_time,
        "records": {},
        "source_versions": {},
        "signal_versions": {},
        "receipts": {},
        "holds": [],
        "events": [],
        "production_collection_enabled": False,
        "external_contact_enabled": False,
    }


def _assert_state_boundary(state: dict[str, Any]) -> None:
    if state.get("engine_id") != "EUCONS_R06_CLIENT_FINDER_ENGINE":
        raise ValueError("Client Finder state engine drift")
    if state.get("production_collection_enabled") is not False:
        raise ValueError("production collection failed open")
    if state.get("external_contact_enabled") is not False:
        raise ValueError("external contact failed open")
    if not isinstance(state.get("records"), dict) or not isinstance(state.get("receipts"), dict):
        raise ValueError("Client Finder state malformed")


def _version_key(row: dict[str, Any], fields: list[str]) -> str:
    return canonical_hash({field: row.get(field) for field in fields})


def _append_version(
    versions: dict[str, list[dict[str, Any]]],
    item_id: str,
    row: dict[str, Any],
    fingerprint_fields: list[str],
    time_field: str,
) -> tuple[bool, dict[str, Any]]:
    bucket = versions.setdefault(item_id, [])
    fingerprint = _version_key(row, fingerprint_fields)
    for old in bucket:
        if old["fingerprint"] == fingerprint:
            return False, old
    observed = VALIDATOR.parse_time(row[time_field])
    if bucket:
        newest = max(VALIDATOR.parse_time(old["observed_at"]) for old in bucket)
        if observed <= newest:
            raise ValueError(f"{item_id} version is not newer")
    version = {
        "version": len(bucket) + 1,
        "fingerprint": fingerprint,
        "observed_at": row[time_field],
        "payload": deepcopy(row),
    }
    bucket.append(version)
    return True, version


def _derive_state(record: dict[str, Any], now: datetime) -> str:
    if record.get("suppression", {}).get("active") is True:
        return "SUPPRESSED"
    if any(row.get("classification") == "CONFLICT" for row in record.get("assertions") or []):
        return "HOLD_CONFLICT"

    active = []
    for signal in record.get("signals") or []:
        if VALIDATOR.parse_time(signal["expires_at"]) > now:
            active.append(signal)
    if VALIDATOR.parse_time(record["expires_at"]) <= now or (record.get("signals") and not active):
        return "HOLD_STALE"
    if not active:
        return "DISCOVERED"
    if all(signal.get("job_ids") and signal.get("service_ids") for signal in active):
        return "READY_FOR_SCORING"
    return "EVIDENCE_COMPLETE"


def _merge_records(
    old: dict[str, Any] | None,
    incoming: dict[str, Any],
    source_versions: dict[str, list[dict[str, Any]]],
    signal_versions: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any], list[str]]:
    events: list[str] = []
    if old is None:
        merged = deepcopy(incoming)
    else:
        if old.get("suppression", {}).get("active") is True and incoming.get("suppression", {}).get("active") is not True:
            raise ValueError("suppression cannot be cleared by prospect ingest")
        merged = deepcopy(old)
        merged["organization"] = deepcopy(incoming["organization"])
        merged["updated_at"] = incoming["updated_at"]
        merged["expires_at"] = incoming["expires_at"]
        merged["suppression"] = deepcopy(incoming["suppression"])

        current_sources = {row["source_id"]: row for row in merged.get("sources") or []}
        for row in incoming.get("sources") or []:
            current_sources[row["source_id"]] = deepcopy(row)
        merged["sources"] = [current_sources[key] for key in sorted(current_sources)]

        assertions = {row["assertion_id"]: row for row in merged.get("assertions") or []}
        for row in incoming.get("assertions") or []:
            previous = assertions.get(row["assertion_id"])
            if previous is not None and canonical_hash(previous) != canonical_hash(row):
                raise ValueError("assertion id cannot be silently overwritten")
            assertions[row["assertion_id"]] = deepcopy(row)
        merged["assertions"] = [assertions[key] for key in sorted(assertions)]

        signals = {row["signal_id"]: row for row in merged.get("signals") or []}
        for row in incoming.get("signals") or []:
            previous = signals.get(row["signal_id"])
            if previous is not None and canonical_hash(previous) != canonical_hash(row):
                if VALIDATOR.parse_time(row["observed_at"]) <= VALIDATOR.parse_time(previous["observed_at"]):
                    raise ValueError("signal update is not newer")
            signals[row["signal_id"]] = deepcopy(row)
        merged["signals"] = [signals[key] for key in sorted(signals)]

    for row in incoming.get("sources") or []:
        added, _ = _append_version(
            source_versions,
            row["source_id"],
            row,
            ["source_id", "content_hash", "url"],
            "retrieved_at",
        )
        if added:
            events.append("SOURCE_VERSION_ADDED")
    for row in incoming.get("signals") or []:
        added, _ = _append_version(
            signal_versions,
            row["signal_id"],
            row,
            ["signal_id", "signal_type", "source_refs", "fact_assertion_ids", "observed_at", "expires_at", "job_ids", "service_ids"],
            "observed_at",
        )
        if added:
            events.append("SIGNAL_VERSION_ADDED")
    return merged, events


def ingest(
    state: dict[str, Any],
    request_id: str,
    record: dict[str, Any],
    reference_time: str,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _assert_state_boundary(state)
    now = VALIDATOR.parse_time(reference_time)
    if now < VALIDATOR.parse_time(state["reference_time"]):
        raise ValueError("reference time cannot move backwards")
    if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 120:
        raise ValueError("request_id invalid")
    if record.get("synthetic_label") not in {"NON_EVIDENCE", None}:
        raise ValueError("unknown evidence label")
    if record.get("synthetic_label") is None and state.get("production_collection_enabled") is False:
        raise ValueError("non-synthetic ingest requires an authorized production adapter")

    contract = contract or VALIDATOR.load_json(CONTRACT_PATH)
    VALIDATOR.validate_contract(contract)
    payload_hash = canonical_hash(record)
    previous_receipt = state["receipts"].get(request_id)
    if previous_receipt:
        if previous_receipt["payload_hash"] != payload_hash:
            raise ValueError("idempotency conflict")
        replay = deepcopy(state)
        replay["last_result"] = {
            "status": "NOOP_REPLAY",
            "request_id": request_id,
            "organization_key": previous_receipt.get("organization_key"),
        }
        return replay

    candidate = deepcopy(record)
    candidate["state"] = "SUPPRESSED" if candidate.get("suppression", {}).get("active") else "DISCOVERED"

    try:
        org_key = VALIDATOR.organization_key(candidate["organization"])
    except ValueError as exc:
        if str(exc) != "HOLD_IDENTITY_AMBIGUOUS":
            raise
        next_state = deepcopy(state)
        next_state["reference_time"] = reference_time
        next_state["receipts"][request_id] = {
            "payload_hash": payload_hash,
            "result": "HOLD_IDENTITY_AMBIGUOUS",
            "organization_key": None,
        }
        next_state["holds"].append({
            "request_id": request_id,
            "reason": "HOLD_IDENTITY_AMBIGUOUS",
            "payload_hash": payload_hash,
            "at": reference_time,
        })
        next_state["events"].append({
            "event_name": "PROSPECT_HELD",
            "occurred_at": reference_time,
            "reason": "HOLD_IDENTITY_AMBIGUOUS",
            "organization_key": None,
        })
        next_state["last_result"] = {"status": "HOLD_IDENTITY_AMBIGUOUS", "request_id": request_id}
        return next_state

    VALIDATOR.validate_record(candidate, contract, now)
    next_state = deepcopy(state)
    org_sources = next_state["source_versions"].setdefault(org_key, {})
    org_signals = next_state["signal_versions"].setdefault(org_key, {})
    old = next_state["records"].get(org_key)
    merged, version_events = _merge_records(old, candidate, org_sources, org_signals)
    merged["state"] = _derive_state(merged, now)
    VALIDATOR.validate_record(merged, contract, now)
    next_state["records"][org_key] = merged
    next_state["records"] = {key: next_state["records"][key] for key in sorted(next_state["records"])}
    next_state["reference_time"] = reference_time

    action = "PROSPECT_CREATED" if old is None else "PROSPECT_UPDATED"
    event_names = version_events + [action]
    if merged["state"].startswith("HOLD_"):
        event_names.append("PROSPECT_HELD")
    for name in event_names:
        next_state["events"].append({
            "event_name": name,
            "occurred_at": reference_time,
            "organization_key": org_key,
            "state": merged["state"],
        })

    next_state["receipts"][request_id] = {
        "payload_hash": payload_hash,
        "result": merged["state"],
        "organization_key": org_key,
    }
    next_state["last_result"] = {
        "status": merged["state"],
        "request_id": request_id,
        "organization_key": org_key,
        "eligibility_state": contract["qualification_gate"]["eligibility_state"],
        "maximum_external_state": contract["external_action_gate"]["maximum_state_from_r06"],
    }
    return next_state


def refresh(state: dict[str, Any], reference_time: str) -> dict[str, Any]:
    _assert_state_boundary(state)
    now = VALIDATOR.parse_time(reference_time)
    if now < VALIDATOR.parse_time(state["reference_time"]):
        raise ValueError("reference time cannot move backwards")
    next_state = deepcopy(state)
    next_state["reference_time"] = reference_time
    for key in sorted(next_state["records"]):
        record = next_state["records"][key]
        new_status = _derive_state(record, now)
        if new_status != record["state"]:
            record["state"] = new_status
            next_state["events"].append({
                "event_name": "PROSPECT_STATE_REFRESHED",
                "occurred_at": reference_time,
                "organization_key": key,
                "state": new_status,
            })
    return next_state


def write_atomic(path: Path, payload: dict[str, Any]) -> None:
    resolved = path.resolve()
    if resolved == ROOT or ROOT in resolved.parents:
        raise ValueError("Client Finder runtime output under repository root is forbidden")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=resolved.name + ".", dir=resolved.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, resolved)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> None:
    parser = argparse.ArgumentParser(description="EUCONS organization-first Client Finder engine")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    reference_time = payload["reference_time"]
    if args.state:
        state = json.loads(args.state.read_text(encoding="utf-8"))
    else:
        state = empty_state(reference_time)
    for observation in payload.get("observations") or []:
        state = ingest(state, observation["request_id"], observation["record"], reference_time)
    state = refresh(state, reference_time)
    write_atomic(args.output, state)
    print(json.dumps({
        "status": "PASS",
        "records": len(state["records"]),
        "holds": len(state["holds"]),
        "production_collection_enabled": state["production_collection_enabled"],
        "external_contact_enabled": state["external_contact_enabled"],
        "output": str(args.output),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
