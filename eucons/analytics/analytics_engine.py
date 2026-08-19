#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "analytics" / "analytics_contract.json"


class AnalyticsError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def _text(value: Any, label: str, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise AnalyticsError(f"{label} required")
    if len(text) > limit:
        raise AnalyticsError(f"{label} exceeds limit")
    return text


def _validate_timestamp(value: Any) -> str:
    text = _text(value, "occurred_at", 64)
    if not text.endswith("Z"):
        raise AnalyticsError("occurred_at must be UTC Z timestamp")
    try:
        datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise AnalyticsError("invalid occurred_at") from exc
    return text


def _scan_forbidden(value: Any, forbidden: set[str], path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in forbidden:
                raise AnalyticsError(f"forbidden analytics key: {path}.{key}")
            _scan_forbidden(child, forbidden, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_forbidden(child, forbidden, f"{path}[{index}]")


def _path(value: Any, contract: dict[str, Any], label: str = "path") -> str:
    text = _text(value, label, int(contract["privacy"]["max_path_length"]))
    if not text.startswith("/") or "?" in text or "#" in text or "://" in text:
        raise AnalyticsError(f"{label} must be a path without query, fragment or scheme")
    return text


def _properties(raw: Any, event_name: str, contract: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise AnalyticsError("properties must be an object")
    allowed = set(contract["allowed_properties"])
    unknown = set(raw) - allowed
    if unknown:
        raise AnalyticsError(f"unsupported analytics properties: {sorted(unknown)}")
    required = contract["events"][event_name]["required"]
    for key in required:
        if key not in raw or raw[key] in (None, "", []):
            raise AnalyticsError(f"required analytics property missing: {key}")

    out: dict[str, Any] = {}
    limit = int(contract["privacy"]["max_text_length"])
    pseudonymous = set(contract["privacy"]["entity_ids_must_be_pseudonymous_for"])
    pattern = re.compile(contract["privacy"]["pseudonymous_id_pattern"])
    for key, value in raw.items():
        if key == "lead_score":
            if not isinstance(value, int) or isinstance(value, bool) or not (0 <= value <= 100):
                raise AnalyticsError("lead_score must be integer 0..100")
            out[key] = value
        elif key == "path":
            out[key] = _path(value, contract)
        else:
            text = _text(value, key, limit)
            if key in pseudonymous and not pattern.fullmatch(text):
                raise AnalyticsError(f"{key} must be pseudonymous sha256")
            out[key] = text
    return out


def _touch(raw: Any, contract: dict[str, Any]) -> dict[str, str]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise AnalyticsError("attribution touch must be object")
    allowed = set(contract["attribution"]["allowed_fields"])
    unknown = set(raw) - allowed
    if unknown:
        raise AnalyticsError(f"unsupported attribution fields: {sorted(unknown)}")
    out: dict[str, str] = {}
    limit = int(contract["privacy"]["max_text_length"])
    for key, value in raw.items():
        if key == "landing_path":
            out[key] = _path(value, contract, "landing_path")
            continue
        text = _text(value, key, limit)
        if key == "referrer_domain":
            if any(token in text for token in ["://", "/", "?", "#", "@"]):
                raise AnalyticsError("referrer_domain must be domain-only")
        elif "?" in text or "#" in text:
            raise AnalyticsError("attribution query strings/fragments forbidden")
        out[key] = text
    return out


def _attribution(raw: Any, contract: dict[str, Any]) -> dict[str, dict[str, str]]:
    if raw in (None, {}):
        return {"first_touch": {}, "last_touch": {}}
    if not isinstance(raw, dict):
        raise AnalyticsError("attribution must be object")
    unknown = set(raw) - {"first_touch", "last_touch"}
    if unknown:
        raise AnalyticsError(f"unsupported attribution touch: {sorted(unknown)}")
    return {
        "first_touch": _touch(raw.get("first_touch"), contract),
        "last_touch": _touch(raw.get("last_touch"), contract),
    }


def build_event(payload: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    if payload.get("product") != contract["product"]:
        raise AnalyticsError("unknown analytics product")
    forbidden = set(contract["privacy"]["forbidden_keys"])
    _scan_forbidden(payload, forbidden)
    event_name = _text(payload.get("event_name"), "event_name", 100)
    if event_name not in contract["events"]:
        raise AnalyticsError("unknown analytics event")
    occurred_at = _validate_timestamp(payload.get("occurred_at"))
    session_id = str(payload.get("session_id") or "").strip()
    if session_id and not re.fullmatch(contract["privacy"]["pseudonymous_id_pattern"], session_id):
        raise AnalyticsError("session_id must be pseudonymous sha256 when present")
    properties = _properties(payload.get("properties") or {}, event_name, contract)
    attribution = _attribution(payload.get("attribution") or {}, contract)
    core = {
        "schema_version": 1,
        "product": contract["product"],
        "engine_id": contract["engine_id"],
        "event_name": event_name,
        "funnel_stage": contract["events"][event_name]["stage"],
        "occurred_at": occurred_at,
        "session_id": session_id or None,
        "properties": properties,
        "attribution": attribution,
    }
    event_id = sha256_json({key: core[key] for key in ["event_name", "occurred_at", "session_id", "properties", "attribution"]})
    core["event_id"] = event_id
    core["idempotency_key"] = event_id
    core["transport_state"] = contract["transport"]["dry_run_state"]
    core["transported"] = False
    receipt_core = {
        "schema_version": 1,
        "event_id": event_id,
        "event_name": event_name,
        "funnel_stage": core["funnel_stage"],
        "transport_state": core["transport_state"],
        "transported": False,
    }
    receipt = dict(receipt_core)
    receipt["receipt_id"] = "RCP-E20-" + sha256_json(receipt_core)[:24]
    receipt["receipt_hash"] = sha256_json(receipt)
    return {
        "schema_version": contract["output"]["schema_version"],
        "product": contract["product"],
        "engine_id": contract["engine_id"],
        "provider_neutral": True,
        "direct_transport_enabled": False,
        "dry_run": True,
        "event": core,
        "receipt": receipt,
    }


def assert_output_path_safe(path: Path) -> None:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return
    raise AnalyticsError("runtime analytics stream cannot be written under repository root")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    result = build_event(load_json(Path(args.input)), load_json(Path(args.contract)))
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        assert_output_path_safe(output)
        output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
