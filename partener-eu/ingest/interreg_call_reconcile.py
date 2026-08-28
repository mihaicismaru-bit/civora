#!/usr/bin/env python3
"""Fail-closed semantic reconciliation for INTERREG_CALL_V1 live evidence.

This gate sits between exact-call acquisition and canonical staging. It accepts only
observations whose exact official page, provenance, semantic fingerprint, status and
deadline are internally consistent. Historical/closed/unresolved controls and
transport failures are quarantined. The receipt is still non-publishing.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from typing import Any

INPUT_SCHEMA = "PARTENER_EU_INTERREG_CALL_LIVE_EVIDENCE_V1"
SCHEMA = "PARTENER_EU_INTERREG_CALL_RECONCILIATION_RECEIPT_V1"
SOURCE_FAMILY = "INTERREG"
AUTHORITY_CLASS = "OFFICIAL_INTERREG_PROGRAMME_AUTHORITY"
ADMISSIBLE_STATES = {"OPEN_CALL", "FORTHCOMING_CALL"}
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
MISSING_PROOFS = ["CANONICAL_STAGING_ADMISSION", "PUBLIC_PROJECTION_QUALITY_GATE"]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _timestamp(value: Any, field: str) -> dt.datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field}: timestamp required")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError(f"{field}: timezone required")
    return parsed.astimezone(dt.timezone.utc)


def _semantic_from_normalized(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "call_identifier": row.get("call_identifier"),
        "programme": row.get("programme_family"),
        "authority_url": row.get("authority_url"),
        "title": row.get("title"),
        "official_status": None,
        "deadline": row.get("deadline_candidate"),
        "budget_candidate": row.get("budget_candidate"),
        "eligibility_candidate": row.get("eligibility_candidate"),
        "observation_state": row.get("observation_state"),
    }


def _identity_from_normalized(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "call_identifier": row.get("call_identifier"),
        "programme": row.get("programme_family"),
        "authority_url": row.get("authority_url"),
    }


def _recompute_semantic_fingerprint(row: dict[str, Any], declared_status: str | None) -> str:
    semantic = _semantic_from_normalized(row)
    semantic["official_status"] = declared_status
    return _sha256_json(semantic)


def reconcile_live_evidence(evidence: dict[str, Any], *, reconciled_at: str | None = None) -> dict[str, Any]:
    if not isinstance(evidence, dict) or evidence.get("schema") != INPUT_SCHEMA:
        raise ValueError(f"input schema must be {INPUT_SCHEMA}")
    if evidence.get("source_family") != SOURCE_FAMILY or evidence.get("authority_class") != AUTHORITY_CLASS:
        raise ValueError("source/authority mismatch")
    if evidence.get("publication_effect") != "NONE" or evidence.get("publish_authorized") is not False:
        raise ValueError("live exact-call evidence must remain non-publishing")
    if evidence.get("canonical_corpus_mutation") is not False:
        raise ValueError("live exact-call evidence cannot mutate canonical corpus")

    created_at = _timestamp(evidence.get("created_at"), "created_at")
    run_id = str(evidence.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("run_id required")

    ready: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    identities: dict[str, str] = {}

    for source_row in evidence.get("rows") or []:
        if not isinstance(source_row, dict):
            raise ValueError("evidence row must be an object")
        probe_id = str(source_row.get("probe_id") or "").strip()
        base = {
            "probe_id": probe_id or None,
            "call_identifier": source_row.get("call_identifier"),
            "programme": source_row.get("programme"),
            "authority_url": source_row.get("final_url") or source_row.get("registered_url"),
            "source_run_id": source_row.get("run_id"),
            "fetched_at": source_row.get("fetched_at"),
            "raw_hash": source_row.get("raw_hash"),
            "publish_authorized": False,
            "publication_effect": "NONE",
            "canonical_corpus_mutation": False,
            "material_fact_action": "NONE",
        }
        reasons: list[str] = []
        if source_row.get("fetch_status") != "PASS":
            reasons.append("OFFICIAL_CALL_FETCH_FAILED")
            if source_row.get("normalized"):
                reasons.append("FETCH_FAILURE_WITH_NORMALIZED_FACTS")
        normalized = source_row.get("normalized")
        if not isinstance(normalized, dict):
            reasons.append("NORMALIZED_OBSERVATION_MISSING")
            quarantined.append({**base, "reconciliation_status": "REVIEW_REQUIRED", "ready_for_staging": False, "material_fact_use": False, "reasons": sorted(set(reasons))})
            continue

        if normalized.get("source_family") != SOURCE_FAMILY or normalized.get("authority_class") != AUTHORITY_CLASS:
            reasons.append("AUTHORITY_OR_FAMILY_DRIFT")
        if normalized.get("run_id") != run_id or normalized.get("run_id") != source_row.get("run_id"):
            reasons.append("RUN_ID_DRIFT")
        if normalized.get("fetched_at") != source_row.get("fetched_at"):
            reasons.append("FETCHED_AT_DRIFT")
        try:
            if _timestamp(normalized.get("fetched_at"), "row.fetched_at") > created_at + dt.timedelta(seconds=5):
                reasons.append("ROW_TIME_AFTER_ENVELOPE")
        except ValueError:
            reasons.append("FETCHED_AT_INVALID")

        raw_hash = str(source_row.get("raw_hash") or "")
        if not HEX64_RE.fullmatch(raw_hash):
            reasons.append("RAW_HASH_MISSING")
        if normalized.get("raw_hash") != raw_hash:
            reasons.append("RAW_HASH_DRIFT")
        if source_row.get("readback_verified") is not True or normalized.get("readback_verified") is not True:
            reasons.append("EXACT_CALL_READBACK_NOT_VERIFIED")
        if source_row.get("final_url") != normalized.get("authority_url"):
            reasons.append("EXACT_CALL_URL_DRIFT")
        if not normalized.get("call_identifier") or normalized.get("call_identifier") != source_row.get("call_identifier"):
            reasons.append("CALL_IDENTIFIER_DRIFT")
        if normalized.get("programme_family") != source_row.get("programme"):
            reasons.append("PROGRAMME_IDENTITY_DRIFT")
        if normalized.get("publish_authorized") is not False or normalized.get("material_fact_use") is not False or normalized.get("publication_effect") != "NONE":
            reasons.append("UPSTREAM_PREAUTHORIZED_FACT")

        semantic_fp = str(normalized.get("semantic_fingerprint") or "")
        identity_fp = str(normalized.get("identity_fingerprint") or "")
        if not HEX64_RE.fullmatch(semantic_fp):
            reasons.append("SEMANTIC_FINGERPRINT_MISSING")
        if not HEX64_RE.fullmatch(identity_fp):
            reasons.append("IDENTITY_FINGERPRINT_MISSING")
        declared_status = source_row.get("declared_status_from_visible_text")
        if semantic_fp and semantic_fp != _recompute_semantic_fingerprint(normalized, declared_status):
            reasons.append("SEMANTIC_FINGERPRINT_MISMATCH")
        if identity_fp and identity_fp != _sha256_json(_identity_from_normalized(normalized)):
            reasons.append("IDENTITY_FINGERPRINT_MISMATCH")

        state = normalized.get("observation_state")
        if state not in ADMISSIBLE_STATES:
            reasons.append("NON_ADMISSIBLE_CALL_STATE")
        if normalized.get("review_reasons"):
            reasons.append("UPSTREAM_REVIEW_REQUIRED")

        prior_semantic = identities.get(identity_fp) if identity_fp else None
        if prior_semantic is not None and prior_semantic != semantic_fp:
            reasons.append("SEMANTIC_CONFLICT")
        elif identity_fp:
            identities[identity_fp] = semantic_fp

        reasons = sorted(set(reasons))
        item = {
            **base,
            "observation_state": state,
            "title": normalized.get("title"),
            "deadline": normalized.get("deadline_candidate"),
            "semantic_fingerprint": semantic_fp or None,
            "identity_fingerprint": identity_fp or None,
        }
        if reasons:
            quarantined.append({**item, "reconciliation_status": "REVIEW_REQUIRED", "ready_for_staging": False, "material_fact_use": False, "reasons": reasons})
            continue

        status = "OPEN" if state == "OPEN_CALL" else "FORTHCOMING"
        ready.append({
            **item,
            "reconciliation_status": "PASS",
            "ready_for_staging": True,
            "material_fact_use": True,
            "material_facts": {
                "call_identifier": normalized.get("call_identifier"),
                "programme": normalized.get("programme_family"),
                "title": normalized.get("title"),
                "status": status,
                "deadline": normalized.get("deadline_candidate"),
                "authority_url": normalized.get("authority_url"),
            },
            "missing_proofs": MISSING_PROOFS,
            "reasons": [],
        })

    return {
        "schema": SCHEMA,
        "source_schema": INPUT_SCHEMA,
        "source_family": SOURCE_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "source_run_id": run_id,
        "source_created_at": evidence.get("created_at"),
        "source_evidence_hash": _sha256_json(evidence),
        "reconciled_at": reconciled_at or dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "records": ready,
        "quarantined_records": quarantined,
        "stats": {
            "input_rows": len(evidence.get("rows") or []),
            "ready_for_staging": len(ready),
            "review_required": len(quarantined),
        },
        "material_fact_use": bool(ready),
        "ready_for_staging": bool(ready),
        "publish_authorized": False,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
        "material_fact_action": "NONE",
        "missing_proofs": MISSING_PROOFS if ready else [],
        "rollback": "Discard this reconciliation receipt; source evidence and LKG remain unchanged.",
    }
