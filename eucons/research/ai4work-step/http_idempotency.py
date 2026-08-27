from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from runtime import validate_submission

RESEARCH_ID = "AI4WORK-STEP-NF-RUN-001"


class IdempotencyError(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def validate_idempotency_key(value: Any) -> str:
    if not isinstance(value, str):
        raise IdempotencyError("Idempotency-Key must be a UUIDv4 string")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise IdempotencyError("Idempotency-Key must be a UUIDv4 string") from exc
    canonical = str(parsed)
    if parsed.version != 4 or value.lower() != canonical:
        raise IdempotencyError("Idempotency-Key must be canonical UUIDv4")
    return canonical


def derive_response_id(form_id: str, idempotency_key: str) -> str:
    key = validate_idempotency_key(idempotency_key)
    material = f"{RESEARCH_ID}:{form_id}:{key}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def analytical_body_digest(record: dict[str, Any]) -> str:
    body = {
        "research_id": record["research_id"],
        "form_id": record["form_id"],
        "form_version": record["form_version"],
        "recruitment_channel_id": record["recruitment_channel_id"],
        "profile": record["profile"],
        "answers": record["answers"],
        "synthetic": record["synthetic"],
    }
    return hashlib.sha256(_canonical_bytes(body)).hexdigest()


def prepare_http_submission(
    payload: Any,
    idempotency_key: Any,
    recruitment_channel_id: Any,
) -> tuple[dict[str, Any], str]:
    """Validate one PROD submission and derive retry-stable transport metadata.

    The raw idempotency key is never attached to the analytical record. The
    recruitment channel is an opaque first-party dissemination-batch id, not a
    respondent/device identifier. The returned body digest is transport/storage
    metadata and must not be exported to NF06.
    """
    key = validate_idempotency_key(idempotency_key)
    record = validate_submission(
        payload,
        recruitment_channel_id=recruitment_channel_id,
    )
    if record.get("synthetic") is not False:
        raise IdempotencyError("HTTP PROD preparation cannot promote synthetic data")
    record["response_id"] = derive_response_id(record["form_id"], key)
    return record, analytical_body_digest(record)
