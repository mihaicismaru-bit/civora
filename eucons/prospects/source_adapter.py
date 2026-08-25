#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
ADAPTER_CONTRACT_PATH = EUCONS / "prospects" / "source_adapter_contract.json"
CLIENT_CONTRACT_PATH = EUCONS / "prospects" / "client_finder_contract.json"
VALIDATOR_PATH = EUCONS / "validation" / "validate_client_finder_contract.py"
ENGINE_PATH = EUCONS / "prospects" / "client_finder_engine.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_module("client_finder_contract_validator", VALIDATOR_PATH)
ENGINE = _load_module("client_finder_engine", ENGINE_PATH)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _origin(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("source URL must be public HTTPS origin")
    return f"https://{parsed.netloc.casefold()}"


def _walk_keys(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key).casefold()
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def validate_adapter_contract(contract: dict[str, Any]) -> dict[str, Any]:
    if contract.get("id") != "R06-CF-SOURCE-ADAPTER-001" or contract.get("status") != "CANONICAL":
        raise ValueError("source adapter contract drift")
    for dependency in (contract.get("canonical_dependencies") or {}).values():
        if not (ROOT / dependency).is_file():
            raise ValueError(f"missing canonical dependency: {dependency}")
    boundary = contract.get("runtime_boundary") or {}
    required_false = {
        "network_fetch_enabled", "live_scraping_enabled", "production_persistence_enabled",
        "personal_contact_extraction_enabled", "visitor_identification_enabled", "external_contact_enabled",
    }
    if boundary.get("input_mode") != "PREFETCHED_SNAPSHOT_ONLY" or any(boundary.get(key) is not False for key in required_false):
        raise ValueError("source adapter runtime boundary failed open")
    profiles = contract.get("profiles") or []
    ids = [row.get("adapter_id") for row in profiles]
    if len(profiles) < 4 or len(ids) != len(set(ids)):
        raise ValueError("source adapter profiles incomplete or duplicated")
    dry = [row for row in profiles if row.get("activation_state") == "DRY_RUN_ONLY"]
    if len(dry) != 1 or dry[0].get("adapter_id") != contract.get("activation_gate", {}).get("dry_run_adapter"):
        raise ValueError("exactly one synthetic dry-run adapter required")
    if any(row.get("activation_state") not in {"DRY_RUN_ONLY", "DISABLED_PENDING_SOURCE_SPECIFIC_REVIEW"} for row in profiles):
        raise ValueError("unknown adapter activation state")
    if any(not row.get("allowed_origins") or not row.get("allowed_source_types") or row.get("official") is not True for row in profiles):
        raise ValueError("adapter profile source boundary incomplete")
    return {row["adapter_id"]: row for row in profiles}


def _require_snapshot_boundary(snapshot: dict[str, Any], contract: dict[str, Any], profile: dict[str, Any]) -> None:
    spec = contract["snapshot_contract"]
    missing = set(spec["required_fields"]) - set(snapshot)
    if missing:
        raise ValueError(f"snapshot required fields missing: {sorted(missing)}")
    if snapshot.get("schema_version") != 1 or snapshot.get("evidence_label") != spec["evidence_label"]:
        raise ValueError("only NON_EVIDENCE dry-run snapshots are authorized")
    if profile.get("activation_state") != "DRY_RUN_ONLY":
        raise ValueError("real source adapter is disabled pending source-specific review")
    if snapshot.get("public_access") is not True:
        raise ValueError("source is not recorded as publicly accessible")
    if snapshot.get("rate_limit_policy") != spec["required_rate_limit_policy"]:
        raise ValueError("rate policy is absent or unsafe")
    if not isinstance(snapshot.get("records"), list) or not snapshot["records"] or len(snapshot["records"]) > spec["max_records"]:
        raise ValueError("snapshot record count invalid")
    if snapshot.get("content_hash") != canonical_hash(snapshot["records"]):
        raise ValueError("snapshot content hash mismatch")

    now = VALIDATOR.parse_time(snapshot["reference_time"])
    retrieved = VALIDATOR.parse_time(snapshot["retrieved_at"])
    skew = timedelta(minutes=spec["future_clock_skew_minutes"])
    if retrieved > now + skew or now - retrieved > timedelta(hours=profile["max_age_hours"]):
        raise ValueError("snapshot is future-dated or stale")
    for field in ("terms_checked_at", "robots_checked_at"):
        checked = VALIDATOR.parse_time(snapshot[field])
        if checked > now + skew or now - checked > timedelta(hours=spec["governance_check_max_age_hours"]):
            raise ValueError(f"{field} is future-dated or stale")

    source = snapshot.get("source") or {}
    required_source = {"authority", "url", "title", "source_type"}
    if required_source - set(source):
        raise ValueError("snapshot source metadata incomplete")
    if _origin(source["url"]) not in set(profile["allowed_origins"]):
        raise ValueError("source origin not allowlisted")
    if source["source_type"] not in set(profile["allowed_source_types"]):
        raise ValueError("source type not authorized for adapter")

    forbidden = set(contract["privacy_boundary"]["forbidden_field_names"])
    if forbidden & set(_walk_keys(snapshot["records"])):
        raise ValueError("person-level or sensitive field present in organization snapshot")


def _stable_id(prefix: str, *parts: str) -> str:
    seed = "|".join(parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(seed).hexdigest()[:24].upper()}"


def adapt_snapshot(
    snapshot: dict[str, Any],
    adapter_contract: dict[str, Any] | None = None,
    client_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    adapter_contract = adapter_contract or load_json(ADAPTER_CONTRACT_PATH)
    client_contract = client_contract or load_json(CLIENT_CONTRACT_PATH)
    profiles = validate_adapter_contract(adapter_contract)
    VALIDATOR.validate_contract(client_contract)
    profile = profiles.get(snapshot.get("adapter_id"))
    if profile is None:
        raise ValueError("unknown source adapter")
    _require_snapshot_boundary(snapshot, adapter_contract, profile)

    signal_map = {row["id"]: row for row in client_contract["signal_taxonomy"]}
    source_meta = snapshot["source"]
    source_id = _stable_id("SRC", snapshot["adapter_id"], source_meta["url"], snapshot["content_hash"])
    observations: list[dict[str, Any]] = []

    for item in snapshot["records"]:
        required = {"source_record_id", "organization", "signal_type", "observed_at", "expires_at", "statement", "why_now", "job_ids", "service_ids", "confidence", "material_funding_claim"}
        if required - set(item):
            raise ValueError("source record fields incomplete")
        signal_contract = signal_map.get(item["signal_type"])
        if signal_contract is None:
            raise ValueError("unknown signal type")
        if not set(item["job_ids"]).issubset(set(signal_contract["job_ids"])):
            raise ValueError("signal job mapping drift")
        if not set(item["service_ids"]).issubset(set(signal_contract["service_ids"])):
            raise ValueError("signal service mapping drift")
        if item["material_funding_claim"] is True and source_meta["source_type"] not in set(client_contract["source_contract"]["official_types"]):
            raise ValueError("material funding fact lacks official source")
        observed = VALIDATOR.parse_time(item["observed_at"])
        expires = VALIDATOR.parse_time(item["expires_at"])
        if expires <= observed:
            raise ValueError("signal expiry must follow observation")

        record_key = str(item["source_record_id"])
        fact_id = _stable_id("AST", snapshot["adapter_id"], record_key, "FACT")
        signal_id = _stable_id("SIG", snapshot["adapter_id"], record_key, item["signal_type"])
        prospect_id = _stable_id("PROS", snapshot["adapter_id"], record_key)
        assertions = [{
            "assertion_id": fact_id,
            "classification": "FACT",
            "subject": item.get("subject") or "organization_public_signal",
            "statement": item["statement"],
            "source_refs": [source_id],
            "material_funding_claim": item["material_funding_claim"],
        }]
        if item.get("inference_statement"):
            assertions.append({
                "assertion_id": _stable_id("AST", snapshot["adapter_id"], record_key, "INFERENCE"),
                "classification": "INFERENCE",
                "subject": "potential_service_need",
                "statement": item["inference_statement"],
                "source_refs": [source_id],
                "supported_by_fact_ids": [fact_id],
                "confidence": item["confidence"],
                "verification_question": item.get("verification_question") or "Ce trebuie verificat înainte de calificare?",
            })

        record = {
            "prospect_id": prospect_id,
            "synthetic_label": "NON_EVIDENCE",
            "organization": deepcopy(item["organization"]),
            "sources": [{
                "source_id": source_id,
                "source_type": source_meta["source_type"],
                "authority": source_meta["authority"],
                "url": source_meta["url"],
                "title": source_meta["title"],
                "retrieved_at": snapshot["retrieved_at"],
                "content_hash": snapshot["content_hash"],
                "official": profile["official"],
                "public_access": snapshot["public_access"],
            }],
            "assertions": assertions,
            "signals": [{
                "signal_id": signal_id,
                "signal_type": item["signal_type"],
                "source_refs": [source_id],
                "observed_at": item["observed_at"],
                "expires_at": item["expires_at"],
                "fact_assertion_ids": [fact_id],
                "confidence": item["confidence"],
                "why_now": item["why_now"],
                "job_ids": item["job_ids"],
                "service_ids": item["service_ids"],
            }],
            "state": "DISCOVERED",
            "created_at": item["observed_at"],
            "updated_at": snapshot["retrieved_at"],
            "expires_at": item["expires_at"],
            "suppression": {"active": False, "reason": None},
        }
        VALIDATOR.validate_record(record, client_contract, VALIDATOR.parse_time(snapshot["reference_time"]))
        observations.append({
            "request_id": _stable_id("REQ", snapshot["adapter_id"], snapshot["content_hash"], record_key),
            "record": record,
        })

    return {
        "schema_version": 1,
        "adapter_unit": "R06-CF-SOURCE-ADAPTER-001",
        "adapter_id": snapshot["adapter_id"],
        "evidence_label": "NON_EVIDENCE",
        "reference_time": snapshot["reference_time"],
        "observations": observations,
        "network_fetch_enabled": False,
        "production_persistence_enabled": False,
        "personal_contact_extraction_enabled": False,
    }


def run_dry_run(snapshot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    adapted = adapt_snapshot(snapshot)
    state = ENGINE.empty_state(adapted["reference_time"])
    for observation in adapted["observations"]:
        state = ENGINE.ingest(state, observation["request_id"], observation["record"], adapted["reference_time"])
    state = ENGINE.refresh(state, adapted["reference_time"])
    return adapted, state


def main() -> None:
    parser = argparse.ArgumentParser(description="EUCONS lawful public-source snapshot adapter")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--state-output", required=True, type=Path)
    args = parser.parse_args()
    snapshot = load_json(args.input)
    adapted, state = run_dry_run(snapshot)
    ENGINE.write_atomic(args.output, adapted)
    ENGINE.write_atomic(args.state_output, state)
    print(json.dumps({
        "status": "PASS",
        "unit": "R06-CF-SOURCE-ADAPTER-001",
        "observations": len(adapted["observations"]),
        "organizations": len(state["records"]),
        "network_fetch": False,
        "production_records": 0,
        "personal_contacts": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
