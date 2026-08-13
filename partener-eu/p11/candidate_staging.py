#!/usr/bin/env python3
"""Deterministic, publication-free candidate staging for P11."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = frozenset({"fbclid", "gclid", "mc_cid", "mc_eid"})


def normalize_text(value: Any) -> str:
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def normalize_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw if "://" in raw else "https://" + raw)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    port = f":{parts.port}" if parts.port and parts.port not in {80, 443} else ""
    path = re.sub(r"/+", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_QUERY_KEYS and not k.lower().startswith(TRACKING_QUERY_PREFIXES)
    )
    return urlunsplit(("https", host + port, path, urlencode(query), ""))


def identity_keys(item: Mapping[str, Any]) -> dict[str, str]:
    source_url = normalize_url(item.get("source_url"))
    programme = normalize_text(item.get("programme"))
    code = normalize_text(item.get("code"))
    title = normalize_text(item.get("title"))
    return {
        "source_url": source_url,
        "programme_code": f"{programme}|{code}" if programme and code else "",
        "programme_title": f"{programme}|{title}" if programme and title else "",
    }


def candidate_id(item: Mapping[str, Any]) -> str:
    keys = identity_keys(item)
    seed = keys["source_url"] or keys["programme_code"] or keys["programme_title"]
    if not seed:
        seed = normalize_text(item.get("title"))
    if not seed:
        raise ValueError("candidate requires source_url, programme+code, programme+title, or title")
    return "CAND-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20].upper()


def payload_sha256(item: Mapping[str, Any]) -> str:
    normalized = {
        "source_url": normalize_url(item.get("source_url")),
        "programme": normalize_text(item.get("programme")),
        "code": normalize_text(item.get("code")),
        "title": normalize_text(item.get("title")),
        "source_id": normalize_text(item.get("source_id")),
    }
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def canonical_indexes(opportunities: Iterable[Mapping[str, Any]], evidence: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, set[str]]]:
    evidence_by_id = {row["evidence_id"]: row for row in evidence}
    indexes: dict[str, dict[str, set[str]]] = {name: defaultdict(set) for name in ("source_url", "programme_code", "programme_title")}
    for opportunity in opportunities:
        opportunity_id = opportunity["opportunity_id"]
        keys = identity_keys(opportunity)
        for key_type in ("programme_code", "programme_title"):
            if keys[key_type]:
                indexes[key_type][keys[key_type]].add(opportunity_id)
        for ref in opportunity.get("evidence_refs") or []:
            url_key = normalize_url((evidence_by_id.get(ref) or {}).get("source_url"))
            if url_key:
                indexes["source_url"][url_key].add(opportunity_id)
    return indexes


def stage_candidates(bundle: Mapping[str, Any], candidates: Iterable[Mapping[str, Any]], observed_at: str) -> dict[str, Any]:
    indexes = canonical_indexes(bundle.get("opportunities") or [], bundle.get("evidence") or [])
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in candidates:
        grouped[candidate_id(item)].append(item)

    rows: list[dict[str, Any]] = []
    for cand_id in sorted(grouped):
        occurrences = grouped[cand_id]
        hashes = sorted({payload_sha256(item) for item in occurrences})
        candidate = min(occurrences, key=payload_sha256)
        keys = identity_keys(candidate)
        matches: dict[str, list[str]] = {}
        all_matches: set[str] = set()
        for key_type, key in keys.items():
            found = sorted(indexes[key_type].get(key, set())) if key else []
            if found:
                matches[key_type] = found
                all_matches.update(found)

        if len(all_matches) == 1 and len(hashes) == 1:
            disposition = "CANONICAL_MATCH"
            canonical_match_id = next(iter(all_matches))
            reason = "unique deterministic identity match"
        elif len(all_matches) > 1 or len(hashes) > 1:
            disposition = "AMBIGUOUS_REVIEW"
            canonical_match_id = None
            reason = "conflicting identity matches or payloads; automatic merge blocked"
        else:
            disposition = "NEW_CANDIDATE"
            canonical_match_id = None
            reason = "no canonical deterministic identity match"

        rows.append({
            "candidate_id": cand_id,
            "disposition": disposition,
            "canonical_match_id": canonical_match_id,
            "identity_keys": keys,
            "matched_by": matches,
            "occurrence_count": len(occurrences),
            "payload_sha256": hashes,
            "reason": reason,
            "publication_allowed": False,
            "material_fact_action": "NONE",
        })

    ledger_payload = {"schema_version": "1.0", "observed_at": observed_at, "rows": rows}
    digest_payload = {"schema_version": ledger_payload["schema_version"], "rows": rows}
    ledger_payload["ledger_sha256"] = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    ledger_payload["summary"] = {
        "input_occurrences": sum(row["occurrence_count"] for row in rows),
        "unique_candidates": len(rows),
        "canonical_matches": sum(row["disposition"] == "CANONICAL_MATCH" for row in rows),
        "new_candidates": sum(row["disposition"] == "NEW_CANDIDATE" for row in rows),
        "ambiguous_review": sum(row["disposition"] == "AMBIGUOUS_REVIEW" for row in rows),
        "published": 0,
    }
    return ledger_payload


def validate_staging_ledger(ledger: Mapping[str, Any]) -> None:
    rows = ledger.get("rows") or []
    ids = [row.get("candidate_id") for row in rows]
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        raise ValueError("staging rows must be unique and deterministically sorted")
    allowed = {"CANONICAL_MATCH", "NEW_CANDIDATE", "AMBIGUOUS_REVIEW"}
    for row in rows:
        if row.get("disposition") not in allowed:
            raise ValueError(f"invalid staging disposition: {row.get('candidate_id')}")
        if row.get("publication_allowed") is not False or row.get("material_fact_action") != "NONE":
            raise ValueError(f"staging attempted publication: {row.get('candidate_id')}")
        if row.get("disposition") != "CANONICAL_MATCH" and row.get("canonical_match_id") is not None:
            raise ValueError(f"unsafe canonical assignment: {row.get('candidate_id')}")
