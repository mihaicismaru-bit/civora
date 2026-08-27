from __future__ import annotations

import json
from typing import Any, Protocol

from http_idempotency import IdempotencyError, prepare_http_submission
from research_storage import ResearchStorageError, canonical_json_bytes
from runtime import ResearchValidationError, collection_enabled, load_contract

SUBMIT_PATH = "/research/ai4work/v1/submit"
IDEMPOTENCY_HEADER = "x-ai4work-idempotency-key"
MAX_BODY_BYTES = 64 * 1024


class IdempotentResearchStorage(Protocol):
    def append_idempotent(
        self,
        record: dict[str, Any],
        *,
        raw_bytes: bytes,
        body_sha256: str,
    ) -> tuple[str, bool]: ...


def _json_response(status: int, payload: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
    body = canonical_json_bytes(payload)
    return status, {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }, body


def _header(headers: dict[str, Any], name: str) -> Any:
    wanted = name.lower()
    for key, value in headers.items():
        if str(key).lower() == wanted:
            return value
    return None


def handle_request(
    *,
    method: str,
    path: str,
    headers: dict[str, Any],
    body: bytes,
    store: IdempotentResearchStorage,
    contract: dict[str, Any] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    """Transport-neutral, fail-closed adapter for the AI4WORK research submit route.

    This function deliberately does not bind a web server, database credential,
    proxy configuration, or deployment target. It exists so the exact HTTP
    semantics can be tested before any production route is enabled.
    """
    if path != SUBMIT_PATH:
        return _json_response(404, {"error": "not_found"})
    if method.upper() != "POST":
        return _json_response(405, {"error": "method_not_allowed"})

    effective_contract = contract or load_contract()
    if not collection_enabled(effective_contract):
        return _json_response(503, {"error": "research_collection_disabled"})

    content_type = str(_header(headers, "content-type") or "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _json_response(415, {"error": "unsupported_media_type"})
    if not isinstance(body, (bytes, bytearray)):
        return _json_response(400, {"error": "invalid_body"})
    if len(body) > MAX_BODY_BYTES:
        return _json_response(413, {"error": "payload_too_large"})

    idempotency_key = _header(headers, IDEMPOTENCY_HEADER)
    try:
        payload = json.loads(bytes(body).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _json_response(400, {"error": "invalid_json"})

    try:
        record, body_sha256 = prepare_http_submission(payload, idempotency_key)
    except IdempotencyError:
        return _json_response(400, {"error": "invalid_idempotency_key"})
    except ResearchValidationError:
        return _json_response(422, {"error": "submission_rejected"})

    try:
        normalized_sha256, inserted = store.append_idempotent(
            record,
            raw_bytes=bytes(body),
            body_sha256=body_sha256,
        )
    except ResearchStorageError as exc:
        if "idempotency key reused with different body" in str(exc):
            return _json_response(409, {"error": "idempotency_conflict"})
        return _json_response(503, {"error": "research_storage_unavailable"})

    return _json_response(
        201 if inserted else 200,
        {
            "accepted": True,
            "inserted": inserted,
            "response_id": record["response_id"],
            "normalized_sha256": normalized_sha256,
        },
    )
