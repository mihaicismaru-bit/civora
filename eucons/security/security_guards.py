#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import html
import json
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "eucons" / "security" / "privacy_security_contract.json"

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:API[_-]?KEY|ACCESS[_-]?TOKEN|REFRESH[_-]?TOKEN|CLIENT[_-]?SECRET|PASSWORD|AUTHORIZATION)"
    r"\s*[:=]\s*['\"]?([A-Za-z0-9_./+\-=]{12,})"
)
_SECRET_TOKENS = [
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
]
_EVENT_HANDLER = re.compile(r"(?i)\bon[a-z]+\s*=")
_SCRIPT_MARKUP = re.compile(r"(?is)<\s*/?\s*script\b")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_iso8601(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def retention_decision(retention_class: str, last_material_activity_at: str, now: str, *, hold: dict[str, Any] | None = None, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or load_contract()
    classes = contract["retention"]["classes"]
    if retention_class not in classes:
        raise ValueError(f"unknown retention class: {retention_class}")
    policy = classes[retention_class]
    activity = parse_iso8601(last_material_activity_at)
    current = parse_iso8601(now)
    if current < activity:
        raise ValueError("now cannot predate last material activity")

    if hold is not None:
        rules = contract["retention"]["holds"]
        if rules["hold_requires_reason_code"] and not hold.get("reason_code"):
            raise ValueError("hold missing reason_code")
        if rules["hold_requires_review_at"] and not hold.get("review_at"):
            raise ValueError("hold missing review_at")
        review_at = parse_iso8601(str(hold["review_at"]))
        if review_at <= current:
            return {"state": "HOLD_REVIEW_DUE", "retention_class": retention_class, "review_at": review_at.isoformat()}
        return {"state": "HELD", "retention_class": retention_class, "review_at": review_at.isoformat(), "reason_code": str(hold["reason_code"])}

    deadline = activity + timedelta(days=int(policy["days"]))
    if current >= deadline:
        return {
            "state": "RETENTION_EXPIRED",
            "retention_class": retention_class,
            "deadline": deadline.isoformat(),
            "terminal_action": policy["terminal_action"],
        }
    return {
        "state": "RETAIN",
        "retention_class": retention_class,
        "deadline": deadline.isoformat(),
        "remaining_seconds": int((deadline - current).total_seconds()),
    }


def validate_purpose_payload(purpose_id: str, payload: dict[str, Any], *, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or load_contract()
    data_map = contract["data_map"]
    if purpose_id not in data_map:
        raise ValueError(f"unknown purpose: {purpose_id}")
    spec = data_map[purpose_id]
    required = set(spec["required_fields"])
    optional = set(spec["optional_fields"])
    forbidden = set(spec["forbidden_fields"])
    keys = set(payload)
    missing = sorted(required - keys)
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")
    present_forbidden = sorted(keys & forbidden)
    if present_forbidden:
        raise ValueError(f"forbidden fields for purpose: {', '.join(present_forbidden)}")
    if not contract["input_guards"]["allow_unknown_fields"]:
        unknown = sorted(keys - required - optional)
        if unknown:
            raise ValueError(f"unknown fields for purpose: {', '.join(unknown)}")
    return deepcopy(payload)


def validate_untrusted_text(value: str, *, long_text: bool = False, contract: dict[str, Any] | None = None) -> str:
    contract = contract or load_contract()
    if not isinstance(value, str):
        raise ValueError("text value must be string")
    if contract["input_guards"]["reject_control_characters"] and _CONTROL_CHARS.search(value):
        raise ValueError("control characters forbidden")
    max_len = int(contract["input_guards"]["max_long_text_length"] if long_text else contract["input_guards"]["max_short_text_length"])
    if len(value) > max_len:
        raise ValueError("text exceeds configured maximum")
    if contract["input_guards"]["reject_raw_script_or_event_handler_markup"]:
        if _SCRIPT_MARKUP.search(value) or _EVENT_HANDLER.search(value):
            raise ValueError("active markup forbidden")
    return value


def escape_public_text(value: str) -> str:
    return html.escape(validate_untrusted_text(value, long_text=True), quote=True)


def contains_secret_like(text: str) -> bool:
    if _SECRET_ASSIGNMENT.search(text):
        return True
    return any(pattern.search(text) for pattern in _SECRET_TOKENS)


def scan_secret_like_paths(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if contains_secret_like(text):
            findings.append(str(path))
    return sorted(findings)


def redact_sensitive_logs(value: Any, *, contract: dict[str, Any] | None = None) -> Any:
    contract = contract or load_contract()
    sensitive = {key.lower() for key in contract["output_guards"]["sensitive_log_keys"]}
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in sensitive:
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = redact_sensitive_logs(item, contract=contract)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive_logs(item, contract=contract) for item in value]
    if isinstance(value, str) and contains_secret_like(value):
        return "[REDACTED]"
    return value


def consent_receipt_id(contact_ref: str, purpose_id: str, channel: str, statement_version: str, consent_at: str, source: str) -> str:
    canonical = "|".join([contact_ref, purpose_id, channel, statement_version, consent_at, source])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_consent_receipt(receipt: dict[str, Any], *, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or load_contract()
    required = contract["consent_lineage"]["required_receipt_fields"]
    missing = [key for key in required if not receipt.get(key)]
    if missing:
        raise ValueError(f"consent receipt missing: {', '.join(missing)}")
    expected = consent_receipt_id(
        str(receipt["contact_ref"]),
        str(receipt["purpose_id"]),
        str(receipt["channel"]),
        str(receipt["statement_version"]),
        str(receipt["consent_at"]),
        str(receipt["source"]),
    )
    if receipt["consent_receipt_id"] != expected:
        raise ValueError("consent receipt id mismatch")
    parse_iso8601(str(receipt["consent_at"]))
    return deepcopy(receipt)


def validate_withdrawal(withdrawal: dict[str, Any], *, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or load_contract()
    required = contract["consent_lineage"]["withdrawal_required_fields"]
    missing = [key for key in required if not withdrawal.get(key)]
    if missing:
        raise ValueError(f"withdrawal missing: {', '.join(missing)}")
    parse_iso8601(str(withdrawal["withdrawn_at"]))
    if len(str(withdrawal["suppression_receipt_id"])) != 64:
        raise ValueError("suppression receipt id must be sha256")
    return deepcopy(withdrawal)


def validate_security_headers(headers: dict[str, str], *, contract: dict[str, Any] | None = None) -> None:
    contract = contract or load_contract()
    expected = contract["web_security"]["headers"]
    missing = [key for key, value in expected.items() if headers.get(key) != value]
    if missing:
        raise ValueError(f"security header drift: {', '.join(missing)}")


def main() -> None:
    contract = load_contract()
    print(f"{contract['engine_id']}: guards loaded")


if __name__ == "__main__":
    main()
