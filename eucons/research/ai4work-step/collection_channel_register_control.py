from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESEARCH_ID = "AI4WORK-STEP-NF-RUN-001"
REGISTER_SCHEMA = "eucons.ai4work_collection_channel_register.v0.1"
TARGET_REGIONS = {"Centru", "Sud-Muntenia", "Sud-Vest Oltenia"}
TARGET_AUDIENCES = {"adults", "employers"}
CHANNEL_ID_RE = re.compile(r"^CH-[A-Z0-9]{8,32}$")
CHANNEL_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]{2,48}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REGISTER_KEYS = {"schema_version", "research_id", "entries"}
ENTRY_KEYS = {
    "channel_id",
    "channel_type",
    "region_scope",
    "audience_scope",
    "invitation_version",
    "opened_at",
    "closed_at",
    "distributor_role",
    "non_coercion_confirmed",
}


class CollectionChannelRegisterError(ValueError):
    pass


def _parse_ts(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise CollectionChannelRegisterError(f"{field} must be a non-empty ISO-8601 timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CollectionChannelRegisterError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise CollectionChannelRegisterError(f"{field} must include timezone information")
    return parsed.astimezone(timezone.utc)


def validate_register(register: Any, *, require_nonempty: bool) -> dict[str, dict[str, Any]]:
    if not isinstance(register, dict) or set(register) != REGISTER_KEYS:
        raise CollectionChannelRegisterError(f"channel register fields must be exactly {sorted(REGISTER_KEYS)}")
    if register.get("schema_version") != REGISTER_SCHEMA:
        raise CollectionChannelRegisterError("unsupported collection-channel register schema")
    if register.get("research_id") != RESEARCH_ID:
        raise CollectionChannelRegisterError("channel register research_id mismatch")
    entries = register.get("entries")
    if not isinstance(entries, list):
        raise CollectionChannelRegisterError("channel register entries must be a list")
    if require_nonempty and not entries:
        raise CollectionChannelRegisterError("channel register must contain at least one approved dissemination batch before PROD")

    by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            raise CollectionChannelRegisterError(f"channel register entry fields must be exactly {sorted(ENTRY_KEYS)}")
        channel_id = entry.get("channel_id")
        if not isinstance(channel_id, str) or not CHANNEL_ID_RE.fullmatch(channel_id):
            raise CollectionChannelRegisterError("channel_id must match CH-[A-Z0-9]{8,32}")
        if channel_id in by_id:
            raise CollectionChannelRegisterError("duplicate channel_id in channel register")
        channel_type = entry.get("channel_type")
        if not isinstance(channel_type, str) or not CHANNEL_TYPE_RE.fullmatch(channel_type):
            raise CollectionChannelRegisterError("channel_type must be a bounded lowercase code")

        regions = entry.get("region_scope")
        if not isinstance(regions, list) or not regions or any(region not in TARGET_REGIONS for region in regions):
            raise CollectionChannelRegisterError("region_scope must contain only target regions")
        if len(regions) != len(set(regions)):
            raise CollectionChannelRegisterError("region_scope contains duplicates")

        audiences = entry.get("audience_scope")
        if not isinstance(audiences, list) or not audiences or any(item not in TARGET_AUDIENCES for item in audiences):
            raise CollectionChannelRegisterError("audience_scope must contain adults and/or employers")
        if len(audiences) != len(set(audiences)):
            raise CollectionChannelRegisterError("audience_scope contains duplicates")

        for field in ("invitation_version", "distributor_role"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise CollectionChannelRegisterError(f"{field} is required")

        opened = _parse_ts(entry.get("opened_at"), field="opened_at")
        closed = _parse_ts(entry.get("closed_at"), field="closed_at")
        if closed < opened:
            raise CollectionChannelRegisterError("channel collection window is inverted")
        if entry.get("non_coercion_confirmed") is not True:
            raise CollectionChannelRegisterError("non_coercion_confirmed must be true")
        by_id[channel_id] = entry
    return by_id


def validate_prod_binding(*, register_path: Path, collection_frame: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        import json

        register = json.loads(register_path.read_text(encoding="utf-8"))
        validate_register(register, require_nonempty=True)
    except (OSError, ValueError, CollectionChannelRegisterError) as exc:
        errors.append(f"collection_channel_register_invalid:{exc}")
        return errors

    approval = collection_frame.get("approval")
    if not isinstance(approval, dict):
        errors.append("collection_channel_register_frame_approval_missing")
        return errors
    declared = approval.get("collection_channel_register_sha256")
    actual = hashlib.sha256(register_path.read_bytes()).hexdigest()
    if not isinstance(declared, str) or not SHA256_RE.fullmatch(declared):
        errors.append("collection_channel_register_sha256_missing")
    elif declared != actual:
        errors.append("collection_channel_register_sha256_mismatch")
    return errors
