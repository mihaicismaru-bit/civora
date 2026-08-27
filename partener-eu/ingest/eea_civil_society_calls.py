#!/usr/bin/env python3
"""Fail-closed call-level normalizer for the EEA Civil Society Fund in Romania.

The Financial Mechanism Office (eeagrants.org) is the authority for this adapter.
Programme/framework pages are discovery/programming evidence only. A record can be
classified OPEN_CALL only when the same observation contains a call number, an
exact official call-detail URL, an explicit OPEN status, and successful readback of
that exact URL. Even then, deadline/budget/eligibility remain evidence candidates
until PARTENER semantic reconciliation and quality gates authorize material facts.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from typing import Any, Iterable
from urllib.parse import urlparse

PARSER_VERSION = "EEA_CSF_ROMANIA_CALLS_V1"
SOURCE_FAMILY = "EEA_NORWAY"
PROGRAMME_FAMILY = "EEA Civil Society Fund Romania 2021-2028"
AUTHORITY_CLASS = "EEA_FMO_CIVIL_SOCIETY_FUND_ROMANIA"
OFFICIAL_HOSTS = {"eeagrants.org", "www.eeagrants.org"}
CALL_PATH_PREFIX = "/en/eea-civil-society-fund-romania/calls/"
PIPELINE_STATES = {
    "PROGRAMMING_PIPELINE",
    "PROPOSAL",
    "CONSULTATION",
    "PLANNED",
    "PROGRAMME_PREPARATION",
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


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _official_call_url(value: Any) -> str | None:
    url = _text(value)
    if not url:
        return None
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    if parsed.scheme != "https" or host not in OFFICIAL_HOSTS:
        return None
    if not path.startswith(CALL_PATH_PREFIX):
        return None
    slug = path[len(CALL_PATH_PREFIX):].strip("/")
    if not slug:
        return None
    return url


def _call_number(record: dict[str, Any]) -> str | None:
    raw = _text(_first(record, "callNumber", "call_number", "number", "identifier"))
    if not raw:
        return None
    match = re.search(r"(?:call\s*#?\s*)?(\d{1,3})\b", raw, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _call_identifier(call_number: str | None) -> str | None:
    return f"EEA-CSF-RO-CALL-{int(call_number):02d}" if call_number else None


def _status_label(record: dict[str, Any]) -> str | None:
    raw = _text(_first(record, "statusLabel", "status_label", "status"))
    if not raw or raw.isdigit():
        return None
    return raw


def _pipeline_state(record: dict[str, Any]) -> str | None:
    raw = (_text(_first(record, "observationState", "observation_state", "recordState")) or "").upper()
    return raw if raw in PIPELINE_STATES else None


def _observation_state(
    record: dict[str, Any],
    *,
    call_number: str | None,
    authority_url: str | None,
    authority_url_verified: bool,
    status_label: str | None,
) -> str:
    if _pipeline_state(record):
        return "PROGRAMMING_PIPELINE"
    label = (status_label or "").strip().upper().replace(" ", "_")
    exact_authority = bool(call_number and authority_url and authority_url_verified)
    if label in {"OPEN", "OPEN_CALL"}:
        return "OPEN_CALL" if exact_authority else "UNKNOWN"
    if label in {"FORTHCOMING", "UPCOMING", "FORTHCOMING_CALL"}:
        return "FORTHCOMING_CALL" if exact_authority else "UNKNOWN"
    if label in {"CLOSED", "CLOSED_CALL"}:
        return "CLOSED_CALL" if exact_authority else "UNKNOWN"
    return "UNKNOWN"


def _semantic_fields(record: dict[str, Any], call_identifier: str, authority_url: str | None,
                     status_label: str | None) -> dict[str, Any]:
    return {
        "call_identifier": call_identifier,
        "programme": PROGRAMME_FAMILY,
        "title": _text(_first(record, "title", "name")),
        "status_label": status_label,
        "authority_url": authority_url,
        "publication_date": _text(_first(record, "publicationDate", "publication_date")),
        "deadline": _text(_first(record, "submissionDeadline", "submission_deadline", "deadline")),
        "questions_deadline": _text(_first(record, "questionsDeadline", "questions_deadline")),
        "amount_available": _text(_first(record, "amountAvailable", "amount_available", "budget")),
        "grant_from": _text(_first(record, "grantAmountFrom", "grant_from")),
        "grant_to": _text(_first(record, "grantAmountTo", "grant_to")),
        "eligible_applicants": _text(_first(record, "eligibleApplicants", "eligible_applicants")),
    }


def normalize_record(
    record: dict[str, Any],
    *,
    fetched_at: str,
    run_id: str,
    raw_hash: str,
    verified_authority_urls: Iterable[str] = (),
) -> dict[str, Any] | None:
    call_number = _call_number(record)
    call_identifier = _call_identifier(call_number)
    if not call_identifier:
        return None
    authority_url = _official_call_url(_first(record, "authorityUrl", "authority_url", "url"))
    verified = authority_url in set(verified_authority_urls) if authority_url else False
    status_label = _status_label(record)
    observation_state = _observation_state(
        record,
        call_number=call_number,
        authority_url=authority_url,
        authority_url_verified=verified,
        status_label=status_label,
    )
    semantic = _semantic_fields(record, call_identifier, authority_url, status_label)
    return {
        "schema": "PARTENER_EU_EEA_CSF_CALL_EVIDENCE_V1",
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "call_identifier": call_identifier,
        "call_number": call_number,
        "title": semantic["title"],
        "status_label": status_label,
        "observation_state": observation_state,
        "authority_url": authority_url,
        "authority_url_verified": verified,
        "publication_date_candidate": semantic["publication_date"],
        "deadline_candidate": semantic["deadline"],
        "questions_deadline_candidate": semantic["questions_deadline"],
        "budget_candidate": semantic["amount_available"],
        "grant_from_candidate": semantic["grant_from"],
        "grant_to_candidate": semantic["grant_to"],
        "eligible_applicants_candidate": semantic["eligible_applicants"],
        "material_fact_use": False,
        "publish_authorized": False,
        "requires_reconcile": observation_state in {"OPEN_CALL", "FORTHCOMING_CALL", "UNKNOWN"},
        "fetched_at": fetched_at,
        "raw_hash": raw_hash,
        "semantic_fingerprint": _sha256(_canonical_json(semantic)),
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
    }


def _candidate_records(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, list):
        for item in payload:
            yield from _candidate_records(item)
        return
    if not isinstance(payload, dict):
        return
    if _call_number(payload):
        yield payload
        return
    for key in ("calls", "results", "items", "content", "data"):
        child = payload.get(key)
        if isinstance(child, (list, dict)):
            yield from _candidate_records(child)


def normalize_payload(
    payload: Any,
    *,
    fetched_at: str | None = None,
    run_id: str,
    verified_authority_urls: Iterable[str] = (),
) -> dict[str, Any]:
    fetched_at = fetched_at or _utc_now()
    raw_bytes = _canonical_json(payload)
    raw_hash = _sha256(raw_bytes)
    candidates = list(_candidate_records(payload))
    records: list[dict[str, Any]] = []
    seen: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    rejected_missing_identifier = 0

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
        key = (
            normalized["call_identifier"],
            normalized["programme_family"],
            normalized["authority_url"],
        )
        previous = seen.get(key)
        if previous is None:
            seen[key] = normalized
            records.append(normalized)
            continue
        if previous["semantic_fingerprint"] == normalized["semantic_fingerprint"]:
            continue
        previous["requires_reconcile"] = True
        normalized["requires_reconcile"] = True
        conflicts.append({
            "call_identifier": normalized["call_identifier"],
            "programme_family": normalized["programme_family"],
            "authority_url": normalized["authority_url"],
            "fingerprints": sorted({previous["semantic_fingerprint"], normalized["semantic_fingerprint"]}),
        })

    return {
        "schema": "PARTENER_EU_EEA_CSF_CALL_BATCH_V1",
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "fetched_at": fetched_at,
        "raw_hash": raw_hash,
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
        "records": records,
        "conflicts": conflicts,
        "stats": {
            "candidate_records": len(candidates),
            "normalized_records": len(records),
            "duplicate_records_collapsed": max(0, len(candidates) - len(records) - rejected_missing_identifier - len(conflicts)),
            "rejected_missing_identifier": rejected_missing_identifier,
            "conflicts": len(conflicts),
        },
        "publication_effect": "NONE",
    }
