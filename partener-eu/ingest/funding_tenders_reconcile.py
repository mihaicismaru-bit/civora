#!/usr/bin/env python3
"""Fail-closed semantic reconciliation for EC Funding & Tenders live evidence.

The live Search/Facet client intentionally captures a heterogeneous portal sample.
This stage separates direct EU calls from portal-only/cascade records and semantic
conflicts before anything can enter canonical staging. It is still non-publishing.

A record is staging-ready only when:
- it is backed by the exact official F&T topic identifier;
- the exact structured Topic Details readback confirms the same current status;
- the official topic page is reachable at the exact authority URL;
- its status wording and OPEN/FORTHCOMING observation agree;
- the raw Search record type is a direct call type (1/2), never portal-only type 8;
- the identifier has no semantic conflict in the normalized batch;
- the deadline is parseable and not already elapsed when status says OPEN;
- the normalized semantic fingerprint still matches the material fields.

Rows that fail an independent record-level condition are quarantined rather than
blocking unrelated clean calls. Envelope/provenance corruption still rejects the
whole receipt.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
from typing import Any
from urllib.parse import quote, urlparse

SCHEMA = "PARTENER_EU_FUNDING_TENDERS_RECONCILIATION_RECEIPT_V1"
INPUT_SCHEMA = "PARTENER_EU_FUNDING_TENDERS_LIVE_EVIDENCE_V1"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "BRUSSELS"
AUTHORITY_CLASS = "EU_COMMISSION_FUNDING_TENDERS"
DIRECT_CALL_TYPES = {"1", "2"}
PORTAL_ONLY_TYPES = {"8"}
STATE_LABELS = {
    "OPEN_CALL": {"OPEN", "OPEN FOR SUBMISSION"},
    "FORTHCOMING_CALL": {"FORTHCOMING", "FORTHCOMING CALL", "UPCOMING"},
}
MISSING_PROOFS = ["CANONICAL_STAGING_ADMISSION", "PUBLIC_PROJECTION_QUALITY_GATE"]
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
STRUCTURED_API_HOST = "api.tech.ec.europa.eu"
STRUCTURED_API_PATH = "/search-api/prod/rest/search"


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical_json(value))


def _fail(message: str) -> None:
    raise ValueError(message)


def _scalar(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = next((item for item in value if item not in (None, "")), None)
    if isinstance(value, dict):
        for key in ("value", "id", "code", "key", "label", "name"):
            if value.get(key) not in (None, ""):
                return _scalar(value.get(key))
        return None
    text = str(value).strip()
    return text or None


def _raw_records(payload: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(payload, list):
        for child in payload:
            out.extend(_raw_records(child))
        return out
    if not isinstance(payload, dict):
        return out
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        out.append(metadata)
        return out
    if any(payload.get(key) not in (None, "", [], {}) for key in (
        "identifier", "topicIdentifier", "topicAbbreviation", "callIdentifier"
    )):
        out.append(payload)
        return out
    for value in payload.values():
        if isinstance(value, (list, dict)):
            out.extend(_raw_records(value))
    return out


def _identifier(record: dict[str, Any]) -> str | None:
    for key in ("identifier", "topicAbbreviation", "topicIdentifier", "callIdentifier"):
        value = _scalar(record.get(key))
        if value:
            return value
    return None


def _parse_timestamp(value: Any, field: str) -> dt.datetime:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{field}: timestamp required")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field}: invalid timestamp {value!r}") from exc
    if parsed.tzinfo is None:
        _fail(f"{field}: timezone required")
    return parsed.astimezone(dt.timezone.utc)


def _parse_budget(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(",", "").replace(" ", "")
    if not re.fullmatch(r"\d+", text):
        raise ValueError(f"budget candidate is not a positive integer EUR amount: {value!r}")
    amount = int(text)
    if amount <= 0:
        raise ValueError("budget candidate must be positive")
    return amount


def _expected_topic_url(identifier: str) -> str:
    return (
        "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/"
        + quote(identifier, safe="-._~:")
    )


def _semantic_from_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "identifier": record.get("identifier"),
        "call_identifier": record.get("call_identifier"),
        "title": record.get("title"),
        "programme": record.get("programme"),
        "programme_period": record.get("programme_period"),
        "status_label": record.get("status_label"),
        "authority_url": record.get("authority_url"),
        "deadline": record.get("deadline_candidate"),
        "budget": record.get("budget_candidate"),
    }


def _readback_errors(identifier: str, row: dict[str, Any], readback: Any) -> list[str]:
    """Validate the exact HTML topic-page reachability proof."""
    errors: list[str] = []
    expected_url = _expected_topic_url(identifier)
    if row.get("authority_url") != expected_url:
        errors.append("AUTHORITY_URL_IDENTITY_MISMATCH")
    if row.get("authority_url_verified") is not True:
        errors.append("AUTHORITY_URL_NOT_VERIFIED")
    if not isinstance(readback, dict) or readback.get("verified") is not True:
        errors.append("EXACT_TOPIC_READBACK_NOT_VERIFIED")
        return errors
    if readback.get("url") != expected_url or readback.get("final_url") != expected_url:
        errors.append("EXACT_TOPIC_READBACK_URL_DRIFT")
    if int(readback.get("http_status") or 0) != 200:
        errors.append("EXACT_TOPIC_HTTP_NOT_200")
    body_hash = str(readback.get("body_sha256") or "")
    if not HEX64_RE.fullmatch(body_hash):
        errors.append("EXACT_TOPIC_BODY_HASH_MISSING")
    return errors


def _structured_readback_errors(identifier: str, row: dict[str, Any], readback: Any) -> list[str]:
    """Validate exact structured Topic Details identity/status evidence."""
    errors: list[str] = []
    if not isinstance(readback, dict) or readback.get("verified") is not True:
        return ["STRUCTURED_TOPIC_READBACK_NOT_VERIFIED"]
    if readback.get("identifier") != identifier:
        errors.append("STRUCTURED_TOPIC_IDENTIFIER_MISMATCH")
    if identifier not in set(readback.get("matched_identifiers") or []):
        errors.append("STRUCTURED_TOPIC_EXACT_ID_MISSING")
    if int(readback.get("exact_match_count") or 0) < 1:
        errors.append("STRUCTURED_TOPIC_EXACT_MATCH_MISSING")

    api_url = str(readback.get("api_url") or "")
    parsed = urlparse(api_url)
    if parsed.scheme != "https" or parsed.hostname != STRUCTURED_API_HOST or parsed.path != STRUCTURED_API_PATH:
        errors.append("STRUCTURED_TOPIC_API_URL_DRIFT")
    if int(readback.get("http_status") or 0) != 200:
        errors.append("STRUCTURED_TOPIC_HTTP_NOT_200")
    if not HEX64_RE.fullmatch(str(readback.get("raw_sha256") or "")):
        errors.append("STRUCTURED_TOPIC_RAW_HASH_MISSING")

    raw_status = str(row.get("raw_status") or "")
    status_codes = {str(value) for value in (readback.get("status_codes") or [])}
    if not raw_status or raw_status not in status_codes:
        errors.append("STRUCTURED_TOPIC_STATUS_MISMATCH")

    call_identifier = str(row.get("call_identifier") or "")
    structured_calls = {str(value) for value in (readback.get("call_identifiers") or []) if value not in (None, "")}
    if call_identifier and structured_calls and call_identifier not in structured_calls:
        errors.append("STRUCTURED_TOPIC_CALL_ID_MISMATCH")
    return errors


def reconcile_live_evidence(
    evidence: dict[str, Any],
    search_payload: Any,
    *,
    search_raw_bytes: bytes,
    reconciled_at: str | None = None,
) -> dict[str, Any]:
    if not isinstance(evidence, dict) or evidence.get("schema") != INPUT_SCHEMA:
        _fail(f"input schema must be {INPUT_SCHEMA}")
    if evidence.get("source_family") != SOURCE_FAMILY or evidence.get("authority_class") != AUTHORITY_CLASS:
        _fail("source/authority mismatch")
    if evidence.get("publication_effect") != "NONE" or evidence.get("publish_authorized"):
        _fail("live evidence must remain non-publishing")
    if evidence.get("material_fact_use") or evidence.get("canonical_corpus_mutation"):
        _fail("live evidence cannot pre-authorize material facts/corpus mutation")

    search_receipt = evidence.get("search_receipt")
    if not isinstance(search_receipt, dict) or search_receipt.get("http_status") != 200:
        _fail("official Search receipt missing or not HTTP 200")
    if search_receipt.get("sha256") != _sha256_bytes(search_raw_bytes):
        _fail("raw Search response hash does not match evidence receipt")

    batch = evidence.get("batch")
    readbacks = evidence.get("authority_readbacks")
    structured_readbacks = evidence.get("structured_topic_readbacks")
    stats = evidence.get("stats")
    if not isinstance(batch, dict) or not isinstance(readbacks, dict) or not isinstance(structured_readbacks, dict) or not isinstance(stats, dict):
        _fail("live evidence envelope missing batch/readbacks/structured-readbacks/stats")
    if batch.get("schema") != "PARTENER_EU_FUNDING_TENDERS_BATCH_V1":
        _fail("normalized batch schema mismatch")
    if batch.get("publication_effect") != "NONE":
        _fail("normalized batch must remain non-publishing")

    raw_by_id: dict[str, list[dict[str, Any]]] = {}
    for raw in _raw_records(search_payload):
        identifier = _identifier(raw)
        if identifier:
            raw_by_id.setdefault(identifier, []).append(raw)

    conflict_ids = {
        str(item.get("identifier"))
        for item in (batch.get("conflicts") or [])
        if isinstance(item, dict) and item.get("identifier")
    }
    ready: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    seen: set[str] = set()
    fetched_at = _parse_timestamp(evidence.get("fetched_at"), "fetched_at")

    for row in batch.get("records") or []:
        if not isinstance(row, dict):
            _fail("normalized batch row must be an object")
        identifier = str(row.get("identifier") or "")
        if not identifier or identifier in seen:
            _fail(f"invalid/duplicate normalized identifier {identifier!r}")
        seen.add(identifier)
        reasons: list[str] = []

        if row.get("source_family") != SOURCE_FAMILY or row.get("authority_class") != AUTHORITY_CLASS:
            reasons.append("AUTHORITY_OR_FAMILY_DRIFT")
        if row.get("run_id") != evidence.get("run_id") or row.get("fetched_at") != evidence.get("fetched_at"):
            reasons.append("PROVENANCE_RUN_OR_TIME_DRIFT")
        if not HEX64_RE.fullmatch(str(row.get("raw_hash") or "")):
            reasons.append("NORMALIZED_RAW_HASH_MISSING")
        if _sha256_json(_semantic_from_record(row)) != row.get("semantic_fingerprint"):
            reasons.append("SEMANTIC_FINGERPRINT_MISMATCH")

        raw_rows = raw_by_id.get(identifier) or []
        raw_types = sorted({value for raw in raw_rows for value in [_scalar(raw.get("type"))] if value})
        if not raw_rows:
            reasons.append("RAW_SEARCH_IDENTITY_MISSING")
        elif not raw_types:
            reasons.append("RAW_SEARCH_TYPE_MISSING")
        elif any(value in PORTAL_ONLY_TYPES for value in raw_types) or not set(raw_types) <= DIRECT_CALL_TYPES:
            reasons.append("NON_DIRECT_OR_PORTAL_ONLY_CALL_TYPE")

        if identifier in conflict_ids or row.get("requires_reconcile"):
            reasons.append("SEMANTIC_CONFLICT")

        state = row.get("observation_state")
        label = str(row.get("status_label") or "").strip().upper().replace("_", " ")
        if state not in STATE_LABELS:
            reasons.append("NON_MATERIAL_OR_UNRESOLVED_STATE")
        elif label not in STATE_LABELS[state]:
            reasons.append("STATUS_LABEL_STATE_MISMATCH")

        reasons.extend(_structured_readback_errors(identifier, row, structured_readbacks.get(identifier)))
        reasons.extend(_readback_errors(identifier, row, readbacks.get(identifier)))

        deadline_iso = None
        if row.get("deadline_candidate") not in (None, ""):
            try:
                deadline = _parse_timestamp(row.get("deadline_candidate"), f"{identifier}.deadline")
                deadline_iso = deadline.isoformat()
                if state == "OPEN_CALL" and deadline < fetched_at:
                    reasons.append("STALE_DEADLINE_CONTRADICTS_OPEN")
            except ValueError:
                reasons.append("DEADLINE_FORMAT_UNRESOLVED")
        elif state == "OPEN_CALL":
            reasons.append("OPEN_CALL_DEADLINE_MISSING")

        budget_eur = None
        try:
            budget_eur = _parse_budget(row.get("budget_candidate"))
        except ValueError:
            reasons.append("BUDGET_FORMAT_UNRESOLVED")

        title = row.get("title")
        if not isinstance(title, str) or not title.strip():
            reasons.append("TITLE_MISSING")

        reasons = sorted(set(reasons))
        base = {
            "identifier": identifier,
            "call_identifier": row.get("call_identifier"),
            "authority_url": row.get("authority_url"),
            "source_run_id": row.get("run_id"),
            "fetched_at": row.get("fetched_at"),
            "raw_hash": row.get("raw_hash"),
            "semantic_fingerprint": row.get("semantic_fingerprint"),
            "raw_search_types": raw_types,
            "observation_state": state,
            "title": title.strip() if isinstance(title, str) else None,
            "programme_reference": row.get("programme"),
            "deadline": deadline_iso,
            "budget_eur": budget_eur,
            "publish_authorized": False,
            "publication_effect": "NONE",
            "canonical_corpus_mutation": False,
            "material_fact_action": "NONE",
        }
        if reasons:
            quarantined.append({
                **base,
                "reconciliation_status": "REVIEW_REQUIRED",
                "ready_for_staging": False,
                "material_fact_use": False,
                "reasons": reasons,
            })
            continue

        material_facts = {
            "title": base["title"],
            "status": "OPEN" if state == "OPEN_CALL" else "FORTHCOMING",
            "deadline": deadline_iso,
        }
        if row.get("call_identifier"):
            material_facts["call_identifier"] = row.get("call_identifier")
        if budget_eur is not None:
            material_facts["budget_eur"] = budget_eur
        ready.append({
            **base,
            "reconciliation_status": "PASS",
            "evidence_basis": "EC_SEARCH_FACET_PLUS_EXACT_STRUCTURED_TOPIC_AND_PAGE_READBACK",
            "material_facts": material_facts,
            "material_fact_use": True,
            "ready_for_staging": True,
            "missing_proofs": MISSING_PROOFS,
            "reasons": [],
        })

    if set(seen) - set(raw_by_id):
        _fail("normalized identifiers missing from raw Search response")

    reconciled_at = reconciled_at or dt.datetime.now(dt.timezone.utc).isoformat()
    return {
        "schema": SCHEMA,
        "source_schema": INPUT_SCHEMA,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "source_run_id": evidence.get("run_id"),
        "source_fetched_at": evidence.get("fetched_at"),
        "source_evidence_hash": _sha256_json(evidence),
        "search_response_sha256": _sha256_bytes(search_raw_bytes),
        "reconciled_at": reconciled_at,
        "records": ready,
        "quarantined_records": quarantined,
        "stats": {
            "normalized_records": len(seen),
            "ready_for_staging": len(ready),
            "review_required": len(quarantined),
            "direct_call_type_records": len(ready),
            "portal_only_or_non_direct_records": sum("NON_DIRECT_OR_PORTAL_ONLY_CALL_TYPE" in row.get("reasons", []) for row in quarantined),
            "semantic_conflicts": sum("SEMANTIC_CONFLICT" in row.get("reasons", []) for row in quarantined),
            "stale_deadline_contradictions": sum("STALE_DEADLINE_CONTRADICTS_OPEN" in row.get("reasons", []) for row in quarantined),
            "structured_topic_mismatches": sum(any(reason.startswith("STRUCTURED_TOPIC_") for reason in row.get("reasons", [])) for row in quarantined),
        },
        "material_fact_use": bool(ready),
        "ready_for_staging": bool(ready),
        "publish_authorized": False,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
        "material_fact_action": "NONE",
        "missing_proofs": MISSING_PROOFS if ready else [],
        "rollback": "Discard this receipt; raw live evidence remains immutable and no canonical/public state is mutated.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=pathlib.Path)
    parser.add_argument("--search-response", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    raw = args.search_response.read_bytes()
    search_payload = json.loads(raw.decode("utf-8"))
    receipt = reconcile_live_evidence(evidence, search_payload, search_raw_bytes=raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "ready_for_staging": receipt["stats"]["ready_for_staging"],
        "review_required": receipt["stats"]["review_required"],
        "portal_only_or_non_direct_records": receipt["stats"]["portal_only_or_non_direct_records"],
        "semantic_conflicts": receipt["stats"]["semantic_conflicts"],
        "structured_topic_mismatches": receipt["stats"]["structured_topic_mismatches"],
        "publish_authorized": receipt["publish_authorized"],
        "publication_effect": receipt["publication_effect"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
