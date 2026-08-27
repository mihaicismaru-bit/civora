#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from channel_provenance import ChannelProvenanceError, validate_recruitment_channel_id

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "form_contract.json"
FORMS_PATH = HERE / "forms_definition.json"
TOP_LEVEL = {"form_id", "notice_read_and_voluntary_participation", "profile", "answers"}
FORBIDDEN_KEYS = {
    "name", "first_name", "last_name", "surname", "cnp", "national_id", "identity_document",
    "email", "phone", "telephone", "address", "exact_address", "exact_employer", "employer_name",
    "organisation_name", "organization_name", "cui", "ip", "ip_address", "user_agent", "cookie_id",
    "login_id", "account_id", "device_fingerprint", "advertising_id", "marketing_id", "social_account",
    "photo", "signature"
}
PII_PATTERNS = {
    "email": re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    "romanian_phone_like": re.compile(r"(?<!\d)(?:\+?40|0)\s?7(?:[ .-]?\d){8}(?!\d)"),
    "cnp_like": re.compile(r"(?<!\d)[1-8]\d{12}(?!\d)"),
    "url_like": re.compile(r"(?i)\b(?:https?://|www\.)\S+"),
}


class ResearchValidationError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_contract() -> dict[str, Any]:
    return load_json(CONTRACT_PATH)


def load_forms() -> dict[str, Any]:
    return load_json(FORMS_PATH)


def clean_text(value: Any, limit: int) -> str:
    text = unicodedata.normalize("NFC", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        raise ResearchValidationError(f"text exceeds {limit} characters")
    return text


def safe_text(value: Any, limit: int) -> str:
    text = clean_text(value, limit)
    hits = [label for label, pattern in PII_PATTERNS.items() if pattern.search(text)]
    if hits:
        raise ResearchValidationError(f"free text contains identifier-like data: {sorted(hits)}")
    return text


def reject_forbidden_keys(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in FORBIDDEN_KEYS:
                raise ResearchValidationError(f"forbidden field at {path}.{key}")
            reject_forbidden_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            reject_forbidden_keys(child, f"{path}[{idx}]")


def _form_by_id(forms: dict[str, Any], form_id: str) -> dict[str, Any]:
    matches = [form for form in forms.get("forms", []) if form.get("id") == form_id]
    if len(matches) != 1:
        raise ResearchValidationError("unknown or duplicate form_id")
    return matches[0]


def _validate_scalar(field: dict[str, Any], value: Any, *, path: str) -> Any:
    ftype = field["type"]
    if ftype == "rating":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ResearchValidationError(f"{path} must be an integer")
        low, high = int(field["min"]), int(field["max"])
        if not low <= value <= high:
            raise ResearchValidationError(f"{path} must be {low}..{high}")
        return value
    if ftype == "boolean":
        if not isinstance(value, bool):
            raise ResearchValidationError(f"{path} must be boolean")
        return value
    if ftype == "single" or ftype == "select":
        if value not in field.get("options", []):
            raise ResearchValidationError(f"{path} is outside the allowed option set")
        return value
    if ftype == "multi":
        if not isinstance(value, list):
            raise ResearchValidationError(f"{path} must be a list")
        max_sel = field.get("max_selections")
        if max_sel is not None and len(value) > int(max_sel):
            raise ResearchValidationError(f"{path} allows at most {max_sel} selections")
        allowed = set(field.get("options", []))
        if any(item not in allowed for item in value):
            raise ResearchValidationError(f"{path} contains an unsupported option")
        if len(value) != len(dict.fromkeys(value)):
            raise ResearchValidationError(f"{path} contains duplicate selections")
        return list(value)
    if ftype == "rating_matrix":
        rows = field.get("rows", {})
        if not isinstance(value, dict) or set(value) != set(rows):
            raise ResearchValidationError(f"{path} matrix keys mismatch")
        low, high = int(field["min"]), int(field["max"])
        out: dict[str, int] = {}
        for key in rows:
            score = value[key]
            if isinstance(score, bool) or not isinstance(score, int) or not low <= score <= high:
                raise ResearchValidationError(f"{path}.{key} must be {low}..{high}")
            out[key] = score
        return out
    if ftype in {"text", "textarea"}:
        return safe_text(value, int(field.get("max_chars", 160)))
    raise ResearchValidationError(f"unsupported field type at {path}: {ftype}")


def _depends_on_active(field: dict[str, Any], values: dict[str, Any]) -> bool:
    rule = field.get("depends_on")
    if not rule:
        return True
    return values.get(rule.get("field")) == rule.get("equals")


def _validate_group(definitions: list[dict[str, Any]], values: Any, *, path: str) -> dict[str, Any]:
    if not isinstance(values, dict):
        raise ResearchValidationError(f"{path} must be an object")
    definition_by_id = {field["id"]: field for field in definitions}
    unknown = set(values) - set(definition_by_id)
    if unknown:
        raise ResearchValidationError(f"{path} contains unknown fields: {sorted(unknown)}")
    out: dict[str, Any] = {}
    for field in definitions:
        fid = field["id"]
        active = _depends_on_active(field, values)
        required = bool(field.get("required", True)) and active
        if fid not in values:
            if required:
                raise ResearchValidationError(f"{path}.{fid} is required")
            if field["type"] in {"text", "textarea"}:
                out[fid] = ""
            continue
        if not active:
            if values[fid] not in (None, "", []):
                raise ResearchValidationError(f"{path}.{fid} must be empty when dependency is inactive")
            if field["type"] in {"text", "textarea"}:
                out[fid] = ""
            continue
        out[fid] = _validate_scalar(field, values[fid], path=f"{path}.{fid}")
    return out


def validate_submission(
    payload: Any,
    contract: dict[str, Any] | None = None,
    forms: dict[str, Any] | None = None,
    *,
    recruitment_channel_id: Any,
) -> dict[str, Any]:
    contract = contract or load_contract()
    forms = forms or load_forms()
    if contract.get("crm_integration") != "FORBIDDEN" or contract.get("commercial_analytics") != "FORBIDDEN":
        raise ResearchValidationError("research isolation contract is not fail-closed")
    if not isinstance(payload, dict) or set(payload) != TOP_LEVEL:
        raise ResearchValidationError(f"top-level fields must be exactly {sorted(TOP_LEVEL)}")
    reject_forbidden_keys(payload)
    try:
        channel_id = validate_recruitment_channel_id(recruitment_channel_id)
    except ChannelProvenanceError as exc:
        raise ResearchValidationError(str(exc)) from exc
    if payload["notice_read_and_voluntary_participation"] is not True:
        raise ResearchValidationError("voluntary participation acknowledgement is required")
    form_id = payload["form_id"]
    form = _form_by_id(forms, form_id)
    profile = _validate_group(form.get("profile", []), payload["profile"], path="profile")
    answers = _validate_group(form.get("questions", []), payload["answers"], path="answers")
    return {
        "schema_version": 1,
        "research_id": contract["research_id"],
        "form_id": form_id,
        "form_version": 1,
        "response_id": str(uuid.uuid4()),
        "received_at": datetime.now(timezone.utc).isoformat(),
        "recruitment_channel_id": channel_id,
        "profile": profile,
        "answers": answers,
        "synthetic": False,
    }


def collection_enabled(contract: dict[str, Any] | None = None) -> bool:
    contract = contract or load_contract()
    return contract.get("production_enabled") is True


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Validate one AI4WORK research submission and emit a research-only record envelope.")
    parser.add_argument("payload", type=Path)
    parser.add_argument("--recruitment-channel-id", required=True)
    args = parser.parse_args()
    try:
        record = validate_submission(
            json.loads(args.payload.read_text(encoding="utf-8")),
            recruitment_channel_id=args.recruitment_channel_id,
        )
    except (OSError, json.JSONDecodeError, ResearchValidationError) as exc:
        raise SystemExit(f"REJECTED: {exc}")
    print(json.dumps(record, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
