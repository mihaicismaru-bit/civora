#!/usr/bin/env python3
"""Fail-closed exact-call normalizer for official Interreg programme authorities.

This adapter is deliberately separate from PROGRAMMING_PIPELINE. It may classify
an observation as OPEN_CALL only when an exact official call identifier and exact
current official call-detail URL are both present, the detail page was read back,
and the official current status and deadline are semantically consistent.

It never publishes or mutates the canonical opportunity corpus. Material facts
remain candidates until a downstream semantic reconciliation gate authorizes them.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any, Iterable
from urllib.parse import urlparse

PARSER_VERSION = "INTERREG_CALL_V1"
SOURCE_FAMILY = "INTERREG"
AUTHORITY_CLASS = "OFFICIAL_INTERREG_PROGRAMME_AUTHORITY"

OFFICIAL_HOSTS = {
    "interreg-rohu.eu",
    "www.interreg-rohu.eu",
    "interregviarobg.eu",
    "www.interregviarobg.eu",
    "romania-serbia.net",
    "www.romania-serbia.net",
    "ro-ua.net",
    "www.ro-ua.net",
    "ro-md.net",
    "www.ro-md.net",
    "interreg-danube.eu",
    "www.interreg-danube.eu",
    "interregeurope.eu",
    "www.interregeurope.eu",
}

NON_CALL_STATES = {
    "PROGRAMMING",
    "PIPELINE",
    "PROPOSAL",
    "CONSULTATION",
    "CONSULTATION_CLOSED",
    "PLANNED",
    "PROGRAMME_PREPARATION",
    "POLICY_SIGNAL",
}
OPEN_STATES = {"OPEN", "OPEN_CALL", "OPEN FOR SUBMISSION"}
FORTHCOMING_STATES = {"FORTHCOMING", "UPCOMING", "PREANNOUNCED", "PRE-ANNOUNCED"}
CLOSED_STATES = {"CLOSED", "CLOSED_CALL", "EXPIRED"}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _parse_timestamp(value: str) -> dt.datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("fetched_at must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def _parse_deadline(value: Any) -> dt.datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if len(text) == 10:
        parsed = dt.datetime.fromisoformat(text).replace(hour=23, minute=59, second=59, tzinfo=dt.timezone.utc)
        return parsed
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("deadline must be timezone-aware when time is supplied")
    return parsed.astimezone(dt.timezone.utc)


def _official_call_url(value: str) -> str:
    text = str(value).strip()
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in OFFICIAL_HOSTS:
        raise ValueError(f"non-authoritative Interreg call URL: {value!r}")
    path = (parsed.path or "").strip("/").lower()
    if not path or path in {"calls", "calls-for-proposals", "news", "consultations"}:
        raise ValueError("call URL must identify an exact call-detail resource")
    return text


def _state(record: dict[str, Any], observed_at: dt.datetime, deadline: dt.datetime | None) -> tuple[str, list[str]]:
    reasons: list[str] = []
    declared = str(record.get("official_status") or record.get("status") or "").strip().upper()
    call_identifier = str(record.get("call_identifier") or "").strip()
    readback_verified = record.get("readback_verified") is True

    if declared in NON_CALL_STATES:
        return "PROGRAMMING_PIPELINE", ["non_call_state"]
    if not call_identifier:
        reasons.append("missing_exact_call_identifier")
    if not readback_verified:
        reasons.append("exact_call_readback_not_verified")

    if declared in OPEN_STATES:
        if deadline is None:
            reasons.append("missing_deadline_for_open_call")
        elif deadline < observed_at:
            reasons.append("open_status_conflicts_with_expired_deadline")
        return ("OPEN_CALL" if not reasons else "REVIEW_REQUIRED"), reasons
    if declared in FORTHCOMING_STATES:
        return ("FORTHCOMING_CALL" if not reasons else "REVIEW_REQUIRED"), reasons
    if declared in CLOSED_STATES:
        return "CLOSED_CALL", reasons
    reasons.append("unresolved_official_status")
    return "REVIEW_REQUIRED", reasons


def normalize_call_observation(
    record: dict[str, Any],
    *,
    fetched_at: str,
    raw_hash: str,
    run_id: str,
) -> dict[str, Any]:
    authority_url = _official_call_url(str(record.get("authority_url") or record.get("url") or ""))
    observed_at = _parse_timestamp(fetched_at)
    deadline = _parse_deadline(record.get("deadline"))
    call_identifier = str(record.get("call_identifier") or "").strip() or None
    programme = str(record.get("programme") or "").strip() or None
    title = str(record.get("title") or "").strip() or None
    observation_state, review_reasons = _state(record, observed_at, deadline)

    semantic = {
        "call_identifier": call_identifier,
        "programme": programme,
        "authority_url": authority_url,
        "title": title,
        "official_status": str(record.get("official_status") or record.get("status") or "").strip() or None,
        "deadline": deadline.isoformat().replace("+00:00", "Z") if deadline else None,
        "budget_candidate": record.get("budget"),
        "eligibility_candidate": record.get("eligibility"),
        "observation_state": observation_state,
    }
    identity = {
        "call_identifier": call_identifier,
        "programme": programme,
        "authority_url": authority_url,
    }
    return {
        "schema": "PARTENER_EU_INTERREG_CALL_V1",
        "source_family": SOURCE_FAMILY,
        "programme_family": programme,
        "authority_class": AUTHORITY_CLASS,
        "call_identifier": call_identifier,
        "authority_url": authority_url,
        "title": title,
        "observation_state": observation_state,
        "deadline_candidate": semantic["deadline"],
        "budget_candidate": record.get("budget"),
        "eligibility_candidate": record.get("eligibility"),
        "review_reasons": review_reasons,
        "readback_verified": record.get("readback_verified") is True,
        "material_fact_use": False,
        "publish_authorized": False,
        "canonical_corpus_mutation": False,
        "publication_effect": "NONE",
        "fetched_at": observed_at.isoformat().replace("+00:00", "Z"),
        "raw_hash": str(raw_hash),
        "semantic_fingerprint": _sha256(_canonical_json(semantic)),
        "identity_fingerprint": _sha256(_canonical_json(identity)),
        "parser_version": PARSER_VERSION,
        "run_id": str(run_id),
    }


def deduplicate_observations(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    unique: dict[str, dict[str, Any]] = {}
    reconcile: list[dict[str, Any]] = []
    for record in records:
        identity = str(record.get("identity_fingerprint") or "")
        semantic = str(record.get("semantic_fingerprint") or "")
        if not identity:
            raise ValueError("missing identity_fingerprint")
        prior = unique.get(identity)
        if prior is None:
            unique[identity] = record
            continue
        if prior.get("semantic_fingerprint") != semantic:
            reconcile.append({
                "identity_fingerprint": identity,
                "reason": "SEMANTIC_CONFLICT",
                "semantic_fingerprints": sorted({str(prior.get("semantic_fingerprint")), semantic}),
            })
    return {
        "records": list(unique.values()),
        "reconcile_required": reconcile,
        "publish_authorized": False,
        "publication_effect": "NONE",
    }
