#!/usr/bin/env python3
"""Fail-closed structured adapter for the European Commission Funding & Tenders API.

This module normalizes public Funding & Tenders structured records into PARTENER.EU
*evidence candidates*. It never publishes or mutates the canonical opportunity
corpus. A record may be classified OPEN_CALL only when all three conditions are
present in the same observation: an exact call/topic identifier, an authoritative
European Commission detail URL, and an authoritative resolved OPEN status label.
Numeric status codes on their own are intentionally non-authorizing.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any, Iterable
from urllib.parse import urlparse

PARSER_VERSION = "FUNDING_TENDERS_STRUCTURED_V1"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "BRUSSELS"
AUTHORITY_CLASS = "EU_COMMISSION_FUNDING_TENDERS"
OFFICIAL_HOSTS = {"ec.europa.eu", "api.tech.ec.europa.eu"}
PIPELINE_STATES = {
    "PROGRAMMING_PIPELINE",
    "PROPOSAL",
    "CONSULTATION",
    "PLANNED",
    "LEGISLATIVE_PROPOSAL",
    "NEGOTIATION",
    "POLICY_SIGNAL",
}


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _first(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = next((v for v in value if v not in (None, "")), None)
    if isinstance(value, dict):
        value = _first(value, "label", "name", "value", "description", "id")
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _official_url(url: Any) -> str | None:
    value = _text(url)
    if not value:
        return None
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in OFFICIAL_HOSTS:
        return None
    return value


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _resolved_status_label(record: dict[str, Any]) -> str | None:
    """Return a human-readable status only when the payload itself resolves it.

    The EC documentation exposes numeric reference-data codes and a separate FACET
    API for resolving those codes. We therefore do not guess the meaning of a bare
    numeric status code here. Callers may add `statusLabel` after resolving the
    reference code through the official FACET response.
    """
    explicit = _text(_first(record, "statusLabel", "status_label", "statusDescription"))
    if explicit:
        return explicit
    raw = _text(record.get("status"))
    if raw and not raw.isdigit():
        return raw
    return None


def _identifier(record: dict[str, Any]) -> str | None:
    return _text(_first(record, "identifier", "topicAbbreviation", "topicIdentifier", "callIdentifier"))


def _authority_url(record: dict[str, Any]) -> str | None:
    return _official_url(_first(record, "authorityUrl", "authority_url", "url", "portalUrl", "topicUrl"))


def _is_call_detail_url(url: str | None) -> bool:
    if not url:
        return False
    path = (urlparse(url).path or "").lower()
    return any(marker in path for marker in (
        "/topic-details/",
        "/competitive-calls",
        "/call-details/",
        "/calls-for-proposals/",
    ))


def _pipeline_state(record: dict[str, Any]) -> str | None:
    state = (_text(_first(record, "observationState", "observation_state", "recordState", "record_state")) or "").upper()
    return state if state in PIPELINE_STATES else None


def _observation_state(record: dict[str, Any], identifier: str | None, authority_url: str | None,
                       authority_url_verified: bool, status_label: str | None) -> str:
    pipeline = _pipeline_state(record)
    if pipeline:
        return "PROGRAMMING_PIPELINE"
    label = (status_label or "").strip().upper().replace(" ", "_")
    has_authority = bool(identifier and authority_url and authority_url_verified and _is_call_detail_url(authority_url))
    if label in {"OPEN", "OPEN_CALL"}:
        return "OPEN_CALL" if has_authority else "UNKNOWN"
    if label in {"FORTHCOMING", "UPCOMING", "FORTHCOMING_CALL"}:
        return "FORTHCOMING_CALL" if has_authority else "UNKNOWN"
    if label in {"CLOSED", "CLOSED_CALL"}:
        return "CLOSED_CALL" if identifier and authority_url else "UNKNOWN"
    return "UNKNOWN"


def _semantic_fields(record: dict[str, Any], identifier: str, status_label: str | None,
                     authority_url: str | None) -> dict[str, Any]:
    return {
        "identifier": identifier,
        "call_identifier": _text(record.get("callIdentifier")),
        "title": _text(_first(record, "title", "name")),
        "programme": _text(_first(record, "programAbbreviation", "programme", "programmes", "frameworkProgramme")),
        "programme_period": _text(record.get("programmePeriod")),
        "status_label": status_label,
        "authority_url": authority_url,
        "deadline": _text(_first(record, "deadlineDate", "deadline", "deadlineDates")),
        "budget": _text(_first(record, "budget", "overallBudget", "indicativeBudget")),
    }


def normalize_record(record: dict[str, Any], *, fetched_at: str, run_id: str,
                     raw_hash: str, verified_authority_urls: Iterable[str] = ()) -> dict[str, Any] | None:
    identifier = _identifier(record)
    if not identifier:
        return None
    authority_url = _authority_url(record)
    verified = authority_url in set(verified_authority_urls) if authority_url else False
    status_label = _resolved_status_label(record)
    observation_state = _observation_state(record, identifier, authority_url, verified, status_label)
    semantic = _semantic_fields(record, identifier, status_label, authority_url)
    semantic_fingerprint = _sha256(_canonical_json(semantic))
    return {
        "schema": "PARTENER_EU_FUNDING_TENDERS_EVIDENCE_V1",
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "identifier": identifier,
        "call_identifier": semantic["call_identifier"],
        "title": semantic["title"],
        "programme": semantic["programme"],
        "programme_period": semantic["programme_period"],
        "raw_status": _text(record.get("status")),
        "status_label": status_label,
        "observation_state": observation_state,
        "authority_url": authority_url,
        "authority_url_verified": verified,
        "deadline_candidate": semantic["deadline"],
        "budget_candidate": semantic["budget"],
        "material_fact_use": False,
        "publish_authorized": False,
        "requires_reconcile": observation_state == "UNKNOWN",
        "fetched_at": fetched_at,
        "raw_hash": raw_hash,
        "semantic_fingerprint": semantic_fingerprint,
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
    }


def _candidate_records(payload: Any) -> Iterable[dict[str, Any]]:
    """Yield likely topic/call records without depending on one volatile wrapper key."""
    if isinstance(payload, list):
        for item in payload:
            yield from _candidate_records(item)
        return
    if not isinstance(payload, dict):
        return
    if _identifier(payload):
        yield payload
        return
    for key in ("results", "items", "documents", "content", "hits", "data"):
        child = payload.get(key)
        if isinstance(child, (list, dict)):
            yield from _candidate_records(child)
    source = payload.get("_source")
    if isinstance(source, dict):
        yield from _candidate_records(source)


def normalize_payload(payload: Any, *, fetched_at: str | None = None, run_id: str,
                      verified_authority_urls: Iterable[str] = ()) -> dict[str, Any]:
    fetched_at = fetched_at or _utc_now()
    raw_bytes = _canonical_json(payload)
    raw_hash = _sha256(raw_bytes)
    rows = []
    rejected_missing_identifier = 0
    seen: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []

    candidates = list(_candidate_records(payload))
    for record in candidates:
        normalized = normalize_record(
            record,
            fetched_at=fetched_at,
            run_id=run_id,
            raw_hash=raw_hash,
            verified_authority_urls=verified_authority_urls,
        )
        if normalized is None:
            rejected_missing_identifier += 1
            continue
        key = normalized["identifier"]
        previous = seen.get(key)
        if previous is None:
            seen[key] = normalized
            rows.append(normalized)
            continue
        if previous["semantic_fingerprint"] == normalized["semantic_fingerprint"]:
            continue
        previous["requires_reconcile"] = True
        normalized["requires_reconcile"] = True
        conflicts.append({
            "identifier": key,
            "fingerprints": sorted({previous["semantic_fingerprint"], normalized["semantic_fingerprint"]}),
        })

    return {
        "schema": "PARTENER_EU_FUNDING_TENDERS_BATCH_V1",
        "source_family": SOURCE_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "fetched_at": fetched_at,
        "raw_hash": raw_hash,
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
        "records": rows,
        "conflicts": conflicts,
        "stats": {
            "candidate_records": len(candidates),
            "normalized_records": len(rows),
            "duplicate_records_collapsed": max(0, len(candidates) - len(rows) - rejected_missing_identifier - len(conflicts)),
            "rejected_missing_identifier": rejected_missing_identifier,
            "conflicts": len(conflicts),
        },
        "publication_effect": "NONE",
    }
