from __future__ import annotations

import hashlib
import json
from typing import Any

from research_storage import (
    RESEARCH_ID,
    ResearchStorageError,
    SQLiteResearchStorage,
    canonical_json_bytes,
    validate_record_envelope,
    validate_response_id,
)
from runtime import (
    _form_by_id,
    _validate_group,
    load_contract,
    load_forms,
    reject_forbidden_keys,
)


IMMUTABLE_RECTIFICATION_FIELDS = (
    "schema_version",
    "research_id",
    "form_id",
    "form_version",
    "response_id",
    "received_at",
    "recruitment_channel_id",
    "synthetic",
)


def build_validated_rectification(
    existing_record: dict[str, Any],
    *,
    profile: Any,
    answers: Any,
) -> dict[str, Any]:
    """Validate replacement analytical values against the frozen form definition.

    The rights path is receipt-keyed and cannot change technical/provenance fields.
    Only preset analytical profile/answer values are replaceable; direct identifiers
    and unsupported/free-form values remain subject to the ordinary form validator.
    """
    validate_record_envelope(existing_record)
    reject_forbidden_keys({"profile": profile, "answers": answers})

    contract = load_contract()
    forms = load_forms()
    if contract.get("research_id") != RESEARCH_ID:
        raise ResearchStorageError("research contract mismatch")
    if contract.get("crm_integration") != "FORBIDDEN" or contract.get("commercial_analytics") != "FORBIDDEN":
        raise ResearchStorageError("research isolation contract is not fail-closed")

    form = _form_by_id(forms, existing_record["form_id"])
    validated_profile = _validate_group(form.get("profile", []), profile, path="profile")
    validated_answers = _validate_group(form.get("questions", []), answers, path="answers")

    corrected = dict(existing_record)
    corrected["profile"] = validated_profile
    corrected["answers"] = validated_answers
    validate_record_envelope(corrected)

    for field in IMMUTABLE_RECTIFICATION_FIELDS:
        if corrected.get(field) != existing_record.get(field):
            raise ResearchStorageError(f"rectification cannot change {field}")
    return corrected


def rectify_by_response_id(
    store: SQLiteResearchStorage,
    response_id: str,
    *,
    profile: Any,
    answers: Any,
    raw_bytes: bytes,
) -> str | None:
    """Replace only validated analytical values for one opaque response receipt.

    Returns the corrected normalized SHA-256, or None when the receipt does not
    identify a live analytical record. The original transport body digest is
    deliberately preserved, while the receipt's normalized SHA-256 is advanced
    atomically so a delayed same-body retry cannot overwrite the correction.
    Active restriction/objection holds are preserved.
    """
    receipt = validate_response_id(response_id)
    existing = store.get_by_response_id(receipt)
    if existing is None:
        return None

    corrected = build_validated_rectification(existing, profile=profile, answers=answers)
    normalized = canonical_json_bytes(corrected)
    normalized_sha = hashlib.sha256(normalized).hexdigest()
    raw_sha = hashlib.sha256(raw_bytes).hexdigest()

    try:
        store.conn.execute("BEGIN IMMEDIATE")
        current_row = store.conn.execute(
            """SELECT normalized_json FROM research_responses
               WHERE research_id = ? AND response_id = ?""",
            (RESEARCH_ID, receipt),
        ).fetchone()
        if current_row is None:
            store.conn.rollback()
            return None
        current = json.loads(current_row[0])
        for field in IMMUTABLE_RECTIFICATION_FIELDS:
            if current.get(field) != existing.get(field):
                raise ResearchStorageError("record changed concurrently during rectification")

        receipt_row = store.conn.execute(
            "SELECT body_sha256 FROM idempotency_receipts WHERE response_id = ?",
            (receipt,),
        ).fetchone()
        if receipt_row is None:
            raise ResearchStorageError("rectification requires an idempotency receipt")

        updated = store.conn.execute(
            """UPDATE research_responses
               SET raw_sha256 = ?, normalized_sha256 = ?, normalized_json = ?
               WHERE research_id = ? AND response_id = ?""",
            (
                raw_sha,
                normalized_sha,
                normalized.decode("utf-8").rstrip("\n"),
                RESEARCH_ID,
                receipt,
            ),
        ).rowcount
        if updated != 1:
            raise ResearchStorageError("rectification did not update exactly one analytical row")

        store.conn.execute(
            "UPDATE idempotency_receipts SET normalized_sha256 = ? WHERE response_id = ?",
            (normalized_sha, receipt),
        )
        store.conn.commit()
        return normalized_sha
    except Exception:
        if store.conn.in_transaction:
            store.conn.rollback()
        raise
