#!/usr/bin/env python3
"""Fail-closed programming-intelligence normalizer for official Interreg sources.

This adapter is intentionally non-authorizing. It turns official future-programming
surveys/consultations into PROGRAMMING_PIPELINE observations and resolves stale
"now open" copy against explicit date windows. It can never create OPEN_CALL or
authorize material call facts. A real funding call must be handled by a separate
call-level adapter using an exact call identifier and current official call page.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse

PARSER_VERSION = "INTERREG_PROGRAMMING_INTELLIGENCE_V1"
SOURCE_FAMILY = "INTERREG"
INTELLIGENCE_FAMILY = "PROGRAMMING_PIPELINE"
AUTHORITY_CLASS = "OFFICIAL_INTERREG_PROGRAMME_AUTHORITY"

OFFICIAL_HOSTS = {
    "interreg-rohu.eu",
    "www.interreg-rohu.eu",
    "www.interregviarobg.eu",
    "interregviarobg.eu",
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

DATE_RANGE_RE = re.compile(
    r"(?:open\s+from\s+)?(?P<start>\d{1,2}[./-]\d{1,2}[./-]\d{4})"
    r"\s*(?:to|until|–|—|-)\s*"
    r"(?P<end>\d{1,2}[./-]\d{1,2}[./-]\d{4})",
    re.IGNORECASE,
)

PROGRAMMING_TERMS = (
    "future interreg programme",
    "future programme",
    "programming 2027+",
    "post-2027",
    "2028–2034",
    "2028-2034",
    "stakeholder consultation",
    "stakeholder survey",
    "programme preparation",
)

MISSING_CALL_PROOF = [
    "exact_call_identifier",
    "official_call_detail_url",
    "official_current_open_status",
    "call_level_material_fact_evidence",
]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _parse_observed_at(value: str) -> dt.datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("fetched_at must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def _parse_day(value: str) -> dt.date:
    clean = value.strip().replace("/", ".").replace("-", ".")
    return dt.datetime.strptime(clean, "%d.%m.%Y").date()


def _official_url(value: str) -> str:
    parsed = urlparse(str(value).strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in OFFICIAL_HOSTS:
        raise ValueError(f"non-authoritative Interreg URL: {value!r}")
    return str(value).strip()


def _extract_window(text: str) -> tuple[dt.date | None, dt.date | None]:
    match = DATE_RANGE_RE.search(text)
    if not match:
        return None, None
    start = _parse_day(match.group("start"))
    end = _parse_day(match.group("end"))
    if end < start:
        raise ValueError("consultation end precedes start")
    return start, end


def _has_programming_context(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in PROGRAMMING_TERMS)


def _state(text: str, observed: dt.date, start: dt.date | None, end: dt.date | None) -> str:
    if start and end:
        if observed < start:
            return "PLANNED"
        if observed <= end:
            return "CONSULTATION"
        return "CONSULTATION_CLOSED"
    if _has_programming_context(text):
        return "PROGRAMME_PREPARATION"
    return "POLICY_SIGNAL"


def normalize_programming_observation(
    record: dict[str, Any],
    *,
    fetched_at: str,
    raw_hash: str,
    run_id: str,
) -> dict[str, Any]:
    authority_url = _official_url(str(record.get("authority_url") or record.get("url") or ""))
    title = str(record.get("title") or "").strip() or None
    text = " ".join(str(record.get(key) or "") for key in ("title", "text", "body", "content"))
    observed_at = _parse_observed_at(fetched_at)
    start, end = _extract_window(text)
    observation_state = _state(text, observed_at.date(), start, end)
    stale_open_copy = "now open" in text.lower() and observation_state not in {"CONSULTATION"}
    confidence = "HIGH" if start and end else ("MEDIUM" if _has_programming_context(text) else "LOW")
    semantic = {
        "programme": str(record.get("programme") or "").strip() or None,
        "title": title,
        "authority_url": authority_url,
        "consultation_start": start.isoformat() if start else None,
        "consultation_end": end.isoformat() if end else None,
        "observation_state": observation_state,
        "stale_open_copy": stale_open_copy,
    }
    return {
        "schema": "PARTENER_EU_INTERREG_PROGRAMMING_INTELLIGENCE_V1",
        "source_family": SOURCE_FAMILY,
        "programme_family": str(record.get("programme") or "").strip() or None,
        "intelligence_family": INTELLIGENCE_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "authority_url": authority_url,
        "title": title,
        "observation_state": observation_state,
        "consultation_start": semantic["consultation_start"],
        "consultation_end": semantic["consultation_end"],
        "stale_open_copy": stale_open_copy,
        "confidence": confidence,
        "not_a_call": True,
        "open_call_authorized": False,
        "material_fact_use": False,
        "publish_authorized": False,
        "publication_effect": "NONE",
        "missing_to_confirm_call": list(MISSING_CALL_PROOF),
        "fetched_at": observed_at.isoformat().replace("+00:00", "Z"),
        "raw_hash": raw_hash,
        "semantic_fingerprint": _sha256(_canonical_json(semantic)),
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
    }
