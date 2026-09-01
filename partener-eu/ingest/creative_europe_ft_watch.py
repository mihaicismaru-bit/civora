#!/usr/bin/env python3
"""Programme-wide Creative Europe discovery from structured Funding & Tenders evidence.

This adapter is discovery/watch only. It enumerates explicit ``CREA-*`` topic
references from the official EC Search API, resolves human-readable status labels
only from official Facet evidence, and keeps different opportunity surfaces
separate before deduplication.

Primary Funding & Tenders topic rows (types other than 8) may enter the exact-topic
priority queue. Type-8 competitive/cascading-call rows can inherit a parent CREA
identifier, so they are retained as linked competitive-call discovery evidence and
never allowed to create a false parent-topic conflict.

It never authorizes OPEN/status/deadline/budget/eligibility/publication. A primary
topic must still pass exact topic readback, semantic reconciliation and the separate
material-admission policy. Linked competitive calls require their own exact
authority adapter and admission path before any reader-facing fact is allowed.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

import funding_tenders_fetch as ft

ADAPTER_ID = "CREATIVE_EUROPE_CALLS_V1"
WATCH_ID = "CREATIVE_EUROPE_FT_PROGRAMME_WATCH_V1"
PARSER_VERSION = "CREATIVE_EUROPE_FT_WATCH_V1"
DEFAULT_TEXT = "CREA-"
MAX_PAGE_SIZE = 100
MAX_PAGES = 5
MAX_STATUS_FALLBACKS = 8
REF_RE = re.compile(r"^CREA-[A-Z0-9]+(?:-[A-Z0-9]+)+$", re.IGNORECASE)
COMPETITIVE_PATH_RE = re.compile(r"/competitive-calls-cs/([0-9]+)(?:/|$)", re.IGNORECASE)
MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
    "call_alert_authorized",
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def programme_query() -> dict[str, Any]:
    # Do not filter status. Programme-wide watch must observe OPEN/FORTHCOMING/
    # CLOSED transitions instead of encoding one desired state into discovery.
    return {
        "bool": {
            "must": [
                {"terms": {"type": list(ft.CALL_TYPES)}},
                {"term": {"programmePeriod": "2021 - 2027"}},
            ]
        }
    }


def _reference(record: Mapping[str, Any]) -> str | None:
    value = (ft._record_identifier(record) or "").strip().upper()
    return value if REF_RE.fullmatch(value) else None


def _first_scalar(record: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = ft._scalar(record.get(key))
        if value not in (None, ""):
            return value
    return None


def _structured_type(record: Mapping[str, Any]) -> str | None:
    return ft._scalar(record.get("type"))


def _structured_url(record: Mapping[str, Any]) -> str | None:
    return _first_scalar(record, "esST_URL", "url")


def _is_linked_competitive(record: Mapping[str, Any]) -> bool:
    return _structured_type(record) == "8"


def _metadata_signature(record: Mapping[str, Any]) -> str:
    useful = {
        "identifier": _reference(record),
        "structured_type": _structured_type(record),
        "structured_url": _structured_url(record),
        "status": ft._record_status_code(record),
        "programme": ft._scalar(record.get("programAbbreviation")),
        "callIdentifier": ft._scalar(record.get("callIdentifier")),
        "deadlineDate": _first_scalar(record, "deadlineDate", "deadlineDates"),
        "title": ft._scalar(record.get("title")),
    }
    return sha256_bytes(canonical_json(useful))


def _priority(status_label: str | None) -> int:
    token = (status_label or "").strip().lower()
    if token == "open":
        return 100
    if token == "forthcoming":
        return 90
    if token == "closed":
        return 30
    return 20


def _candidate_state(status_label: str | None) -> str:
    token = (status_label or "").strip().lower()
    if token == "open":
        return "OPEN_CANDIDATE_NON_AUTHORIZING"
    if token == "forthcoming":
        return "FORTHCOMING_CANDIDATE_NON_AUTHORIZING"
    if token == "closed":
        return "CLOSED_OBSERVATION_NON_AUTHORIZING"
    return "UNKNOWN_STATUS_NON_AUTHORIZING"


def _competitive_identity(url: str | None, record: Mapping[str, Any]) -> tuple[str | None, str]:
    candidate_url = str(url or "").strip() or None
    competitive_id: str | None = None
    if candidate_url:
        parsed = urlparse(candidate_url)
        match = COMPETITIVE_PATH_RE.search(parsed.path)
        if parsed.scheme == "https" and parsed.hostname == "ec.europa.eu" and match:
            competitive_id = match.group(1)
            return competitive_id, f"FUNDING_TENDERS_COMPETITIVE_CALL:{competitive_id}"
    return None, f"OPAQUE_TYPE8_RECORD:{sha256_bytes(canonical_json(record))}"


def _build_competitive_discovery(
    rows: list[dict[str, Any]],
    *,
    status_resolution: Mapping[str, str | None],
) -> list[dict[str, Any]]:
    discovery: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        parent_reference = _reference(row)
        if not parent_reference:
            continue
        structured_url = _structured_url(row)
        competitive_id, identity_key = _competitive_identity(structured_url, row)
        record_sha = sha256_bytes(canonical_json(row))
        dedup_key = identity_key if not identity_key.startswith("OPAQUE_TYPE8_RECORD:") else record_sha
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        status_code = ft._record_status_code(row)
        status_label = status_resolution.get(status_code) if status_code else None
        semantic = {
            "opportunity_class": "COMPETITIVE_CASCADING_CALL",
            "parent_reference": parent_reference,
            "structured_type": "8",
            "competitive_call_id_candidate": competitive_id,
            "authority_url_candidate": structured_url,
            "status_code": status_code,
            "status_label_candidate": status_label,
            "candidate_observation_state": _candidate_state(status_label),
            "programme_candidate": ft._scalar(row.get("programAbbreviation")),
            "call_identifier_candidate": ft._scalar(row.get("callIdentifier")),
            "deadline_candidate": _first_scalar(row, "deadlineDate", "deadlineDates"),
            "title_candidate": ft._scalar(row.get("title")),
        }
        candidate: dict[str, Any] = {
            **semantic,
            "identity_key": identity_key,
            "record_sha256": record_sha,
            "authority_url_verified": False,
            "market_intelligence_only": True,
            "requires_separate_competitive_call_adapter": True,
            "requires_exact_competitive_call_authority_readback": True,
            "requires_semantic_reconcile": True,
            "requires_material_admission": True,
            "semantic_fingerprint": sha256_bytes(canonical_json(semantic)),
            "publication_effect": "NONE",
            "canonical_corpus_mutation": False,
        }
        for key in MATERIAL_FLAGS:
            candidate[key] = False
        discovery.append(candidate)
    discovery.sort(
        key=lambda item: (
            -_priority(item.get("status_label_candidate")),
            str(item.get("parent_reference") or ""),
            str(item.get("identity_key") or ""),
        )
    )
    return discovery


def collect_watch(
    *,
    run_id: str,
    fetched_at: str | None = None,
    text: str = DEFAULT_TEXT,
    page_size: int = 50,
    max_pages: int = 3,
    output_dir: pathlib.Path | None = None,
    post_func: Callable[..., tuple[Any, bytes, dict[str, Any]]] = ft._safe_json_post,
) -> dict[str, Any]:
    if not run_id.strip():
        raise ValueError("run_id is required")
    fetched_at = fetched_at or utc_now()
    text = str(text or "").strip()
    if not text or len(text) > 64 or "CREA" not in text.upper():
        raise ValueError("Creative Europe programme watch requires a bounded CREA search token")
    if not 1 <= int(page_size) <= MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be 1..{MAX_PAGE_SIZE}")
    if not 1 <= int(max_pages) <= MAX_PAGES:
        raise ValueError(f"max_pages must be 1..{MAX_PAGES}")

    query = programme_query()
    parts = {"query": query, "languages": ["en"]}
    search_pages: list[dict[str, Any]] = []
    flattened: list[dict[str, Any]] = []
    page_hashes: set[str] = set()
    repeated_page_detected = False

    for page_number in range(1, int(max_pages) + 1):
        payload, raw, receipt = post_func(
            ft.SEARCH_ENDPOINT,
            text=text,
            page_size=int(page_size),
            page_number=page_number,
            parts=parts,
        )
        raw_hash = sha256_bytes(raw)
        if raw_hash in page_hashes:
            repeated_page_detected = True
            break
        page_hashes.add(raw_hash)
        rows = ft.flatten_search_payload(payload)
        search_pages.append({
            "page_number": page_number,
            "receipt": dict(receipt),
            "raw_sha256": raw_hash,
            "search_records": len(rows),
        })
        flattened.extend(copy.deepcopy(rows))
        if not rows or len(rows) < int(page_size):
            break

    groups: dict[str, list[dict[str, Any]]] = {}
    linked_competitive_rows: list[dict[str, Any]] = []
    non_crea_records = 0
    for row in flattened:
        ref = _reference(row)
        if not ref:
            non_crea_records += 1
            continue
        if _is_linked_competitive(row):
            linked_competitive_rows.append(copy.deepcopy(row))
            continue
        groups.setdefault(ref, []).append(row)

    conflicts: list[dict[str, Any]] = []
    unique_rows: dict[str, dict[str, Any]] = {}
    for ref, rows in sorted(groups.items()):
        signatures = sorted({_metadata_signature(row) for row in rows})
        if len(signatures) != 1:
            conflicts.append({
                "reference": ref,
                "record_count": len(rows),
                "metadata_signatures": signatures,
                "reason": "CONFLICTING_PRIMARY_TOPIC_METADATA_EXCLUDED",
            })
            continue
        unique_rows[ref] = copy.deepcopy(rows[0])

    status_codes = sorted({
        code
        for code in (
            ft._record_status_code(row)
            for row in [*unique_rows.values(), *linked_competitive_rows]
        )
        if code
    })
    facet_payload, facet_raw, facet_receipt = post_func(
        ft.FACET_ENDPOINT,
        text=text,
        page_size=min(int(page_size), MAX_PAGE_SIZE),
        page_number=1,
        parts=parts,
    )
    facet_payloads = [facet_payload]
    facet_parts = [facet_raw]
    facet_receipts: list[dict[str, Any]] = [dict(facet_receipt)]
    status_resolution: dict[str, str | None] = {
        code: ft.resolve_reference_label(facet_payloads, code) for code in status_codes
    }

    unresolved = [code for code, label in status_resolution.items() if not label]
    if len(unresolved) > MAX_STATUS_FALLBACKS:
        raise ValueError("too many unresolved Funding & Tenders status codes for bounded fallback")
    for code in unresolved:
        payload2, raw2, receipt2 = post_func(
            ft.FACET_ENDPOINT,
            text=code,
            page_size=10,
            page_number=1,
            parts=parts,
        )
        facet_payloads.append(payload2)
        facet_parts.append(raw2)
        facet_receipts.append(dict(receipt2))
        status_resolution[code] = ft.resolve_reference_label(facet_payloads, code)

    candidates: list[dict[str, Any]] = []
    for ref, row in sorted(unique_rows.items()):
        status_code = ft._record_status_code(row)
        status_label = status_resolution.get(status_code) if status_code else None
        semantic = {
            "reference": ref,
            "status_code": status_code,
            "status_label_candidate": status_label,
            "candidate_observation_state": _candidate_state(status_label),
            "programme_candidate": ft._scalar(row.get("programAbbreviation")),
            "call_identifier_candidate": ft._scalar(row.get("callIdentifier")),
            "deadline_candidate": _first_scalar(row, "deadlineDate", "deadlineDates"),
            "authority_url_candidate": ft.topic_url(ref),
        }
        candidate = {
            **semantic,
            "priority": _priority(status_label),
            "authority_url_verified": False,
            "requires_exact_topic_readback": True,
            "requires_semantic_reconcile": True,
            "requires_material_admission": True,
            "semantic_fingerprint": sha256_bytes(canonical_json(semantic)),
            "missing_for_open_confirmation": [
                "exact current official Funding & Tenders topic readback",
                "exact current official per-topic status verification",
                "semantic reconciliation against previous exact-topic observation/LKG",
                "call-specific material admission for deadline/budget/eligibility/participation",
            ],
        }
        for key in MATERIAL_FLAGS:
            candidate[key] = False
        candidates.append(candidate)

    linked_competitive_discovery = _build_competitive_discovery(
        linked_competitive_rows,
        status_resolution=status_resolution,
    )

    candidates.sort(key=lambda item: (-int(item["priority"]), item["reference"]))
    unresolved_codes = sorted(code for code, label in status_resolution.items() if not label)
    source_health = "HEALTHY" if candidates else "DEGRADED_EMPTY_STRUCTURED_DISCOVERY"
    lkg_required = not bool(candidates)
    semantic_basis = {
        "references": [
            {
                "reference": row["reference"],
                "status_code": row["status_code"],
                "status_label_candidate": row["status_label_candidate"],
                "candidate_observation_state": row["candidate_observation_state"],
                "semantic_fingerprint": row["semantic_fingerprint"],
            }
            for row in candidates
        ],
        "conflict_references": [c["reference"] for c in conflicts],
    }

    evidence = {
        "schema": "PARTENER_EU_CREATIVE_EUROPE_FT_PROGRAMME_WATCH_V1",
        "adapter_id": ADAPTER_ID,
        "watch_id": WATCH_ID,
        "parser_version": PARSER_VERSION,
        "source_family": "EU_DIRECT",
        "programme_family": "CREATIVE_EUROPE",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS_STRUCTURED",
        "observation_state": "PROGRAMME_WIDE_EXACT_REFERENCE_DISCOVERY_NON_AUTHORIZING",
        "fetched_at": fetched_at,
        "run_id": run_id,
        "search_text": text,
        "query": query,
        "source_health": source_health,
        "lkg_required": lkg_required,
        "search_pages": search_pages,
        "facet_receipts": facet_receipts,
        "facet_raw_sha256": sha256_bytes(b"\n".join(facet_parts)),
        "status_resolution": status_resolution,
        "candidates": candidates,
        "conflicts": conflicts,
        "linked_competitive_discovery": linked_competitive_discovery,
        "linked_competitive_discovery_semantic_reconcile_included": False,
        "linked_competitive_discovery_requires_separate_reconcile": True,
        "semantic_fingerprint": sha256_bytes(canonical_json(semantic_basis)),
        "stats": {
            "pages_fetched": len(search_pages),
            "search_records": len(flattened),
            "non_crea_records_excluded": non_crea_records,
            "explicit_crea_references_seen": len(groups),
            "exact_reference_candidates": len(candidates),
            "conflicting_references_excluded": len(conflicts),
            "linked_competitive_records_seen": len(linked_competitive_rows),
            "linked_competitive_discovery_candidates": len(linked_competitive_discovery),
            "linked_competitive_parent_references": len({
                str(item.get("parent_reference") or "")
                for item in linked_competitive_discovery
                if item.get("parent_reference")
            }),
            "open_candidates_non_authorizing": sum(
                c["candidate_observation_state"] == "OPEN_CANDIDATE_NON_AUTHORIZING" for c in candidates
            ),
            "forthcoming_candidates_non_authorizing": sum(
                c["candidate_observation_state"] == "FORTHCOMING_CANDIDATE_NON_AUTHORIZING" for c in candidates
            ),
            "open_linked_competitive_candidates_non_authorizing": sum(
                c["candidate_observation_state"] == "OPEN_CANDIDATE_NON_AUTHORIZING"
                for c in linked_competitive_discovery
            ),
            "unresolved_status_codes": unresolved_codes,
            "pagination_repeat_detected": repeated_page_detected,
        },
        "market_intelligence_only": True,
        "requires_exact_topic_handoff": True,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        evidence[key] = False
    validate_watch_evidence(evidence)

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "ft-programme-watch-evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return evidence


def _validate_linked_competitive_candidate(candidate: Mapping[str, Any]) -> None:
    parent_reference = str(candidate.get("parent_reference") or "").upper()
    if not REF_RE.fullmatch(parent_reference):
        raise ValueError("Creative Europe linked competitive candidate parent reference invalid")
    if candidate.get("opportunity_class") != "COMPETITIVE_CASCADING_CALL":
        raise ValueError("Creative Europe linked competitive opportunity class drift")
    if candidate.get("structured_type") != "8":
        raise ValueError("Creative Europe linked competitive type drift")
    if candidate.get("market_intelligence_only") is not True:
        raise ValueError("Creative Europe linked competitive candidate lost intelligence boundary")
    if candidate.get("requires_separate_competitive_call_adapter") is not True:
        raise ValueError("Creative Europe linked competitive candidate skipped separate adapter")
    if candidate.get("requires_exact_competitive_call_authority_readback") is not True:
        raise ValueError("Creative Europe linked competitive candidate skipped exact authority gate")
    if candidate.get("requires_semantic_reconcile") is not True or candidate.get("requires_material_admission") is not True:
        raise ValueError("Creative Europe linked competitive candidate skipped downstream gate")
    if candidate.get("authority_url_verified") is not False:
        raise ValueError("Creative Europe linked competitive candidate self-verified authority")
    if candidate.get("publication_effect") != "NONE" or candidate.get("canonical_corpus_mutation") is not False:
        raise ValueError("Creative Europe linked competitive candidate crossed publication boundary")
    for key in MATERIAL_FLAGS:
        if candidate.get(key) is not False:
            raise ValueError(f"Creative Europe linked competitive candidate became authorizing: {key}")
    for key in ("record_sha256", "semantic_fingerprint"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(candidate.get(key) or "")):
            raise ValueError(f"Creative Europe linked competitive candidate hash invalid: {key}")

    url = candidate.get("authority_url_candidate")
    competitive_id = candidate.get("competitive_call_id_candidate")
    identity_key = str(candidate.get("identity_key") or "")
    if url:
        parsed = urlparse(str(url))
        match = COMPETITIVE_PATH_RE.search(parsed.path)
        if parsed.scheme != "https" or parsed.hostname != "ec.europa.eu" or not match:
            raise ValueError("Creative Europe linked competitive candidate URL is not a bounded EC competitive-call surface")
        if competitive_id != match.group(1):
            raise ValueError("Creative Europe linked competitive candidate id/url mismatch")
        if identity_key != f"FUNDING_TENDERS_COMPETITIVE_CALL:{competitive_id}":
            raise ValueError("Creative Europe linked competitive candidate identity drift")
    else:
        if competitive_id is not None or not identity_key.startswith("OPAQUE_TYPE8_RECORD:"):
            raise ValueError("Creative Europe opaque type-8 candidate identity drift")


def validate_watch_evidence(evidence: Mapping[str, Any]) -> None:
    if evidence.get("schema") != "PARTENER_EU_CREATIVE_EUROPE_FT_PROGRAMME_WATCH_V1":
        raise ValueError("Creative Europe programme watch schema mismatch")
    if evidence.get("adapter_id") != ADAPTER_ID or evidence.get("watch_id") != WATCH_ID:
        raise ValueError("Creative Europe programme watch identity drift")
    if evidence.get("source_family") != "EU_DIRECT" or evidence.get("programme_family") != "CREATIVE_EUROPE":
        raise ValueError("Creative Europe programme watch family drift")
    if evidence.get("observation_state") != "PROGRAMME_WIDE_EXACT_REFERENCE_DISCOVERY_NON_AUTHORIZING":
        raise ValueError("Creative Europe programme watch observation-state drift")
    if evidence.get("market_intelligence_only") is not True or evidence.get("requires_exact_topic_handoff") is not True:
        raise ValueError("Creative Europe programme watch lost exact-topic boundary")
    if evidence.get("publication_effect") != "NONE" or evidence.get("canonical_corpus_mutation") is not False:
        raise ValueError("Creative Europe programme watch crossed publication boundary")
    for key in MATERIAL_FLAGS:
        if evidence.get(key) is not False:
            raise ValueError(f"Creative Europe programme watch became authorizing: {key}")
    if evidence.get("source_health") not in {"HEALTHY", "DEGRADED_EMPTY_STRUCTURED_DISCOVERY"}:
        raise ValueError("Creative Europe programme watch source-health drift")
    candidates = list(evidence.get("candidates") or [])
    if evidence.get("source_health") == "HEALTHY" and not candidates:
        raise ValueError("HEALTHY Creative Europe watch has no exact-reference candidates")
    if evidence.get("source_health") == "DEGRADED_EMPTY_STRUCTURED_DISCOVERY" and evidence.get("lkg_required") is not True:
        raise ValueError("empty Creative Europe structured discovery did not require LKG")
    seen: set[str] = set()
    conflict_refs = {str(c.get("reference") or "") for c in (evidence.get("conflicts") or [])}
    for candidate in candidates:
        ref = str(candidate.get("reference") or "").upper()
        if not REF_RE.fullmatch(ref) or ref in seen or ref in conflict_refs:
            raise ValueError(f"invalid/duplicate/conflicted Creative Europe watch reference: {ref}")
        seen.add(ref)
        if candidate.get("authority_url_candidate") != ft.topic_url(ref):
            raise ValueError(f"Creative Europe watch topic URL drift: {ref}")
        if candidate.get("authority_url_verified") is not False:
            raise ValueError(f"programme watch incorrectly verified exact topic URL: {ref}")
        if candidate.get("requires_exact_topic_readback") is not True or candidate.get("requires_semantic_reconcile") is not True:
            raise ValueError(f"Creative Europe watch lost downstream verification boundary: {ref}")
        for key in MATERIAL_FLAGS:
            if candidate.get(key) is not False:
                raise ValueError(f"Creative Europe watch candidate became authorizing: {ref} {key}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(candidate.get("semantic_fingerprint") or "")):
            raise ValueError(f"Creative Europe watch candidate fingerprint invalid: {ref}")

    linked = list(evidence.get("linked_competitive_discovery") or [])
    identities: set[str] = set()
    for candidate in linked:
        _validate_linked_competitive_candidate(candidate)
        identity = str(candidate.get("identity_key") or "")
        if identity in identities:
            raise ValueError(f"duplicate Creative Europe linked competitive identity: {identity}")
        identities.add(identity)
    if evidence.get("linked_competitive_discovery_semantic_reconcile_included") is not False:
        raise ValueError("Creative Europe linked competitive discovery incorrectly entered parent watch reconcile")
    if evidence.get("linked_competitive_discovery_requires_separate_reconcile") is not True:
        raise ValueError("Creative Europe linked competitive discovery lost separate reconcile boundary")

    for conflict in evidence.get("conflicts") or []:
        if conflict.get("reason") != "CONFLICTING_PRIMARY_TOPIC_METADATA_EXCLUDED":
            raise ValueError("Creative Europe watch conflict reason drift")

    for key in ("facet_raw_sha256", "semantic_fingerprint"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get(key) or "")):
            raise ValueError(f"Creative Europe programme watch hash invalid: {key}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=3)
    args = parser.parse_args()
    evidence = collect_watch(
        run_id=args.run_id,
        output_dir=args.output_dir,
        text=args.text,
        page_size=args.page_size,
        max_pages=args.max_pages,
    )
    print(json.dumps({
        "source_health": evidence["source_health"],
        "candidates": evidence["stats"]["exact_reference_candidates"],
        "open_candidates_non_authorizing": evidence["stats"]["open_candidates_non_authorizing"],
        "linked_competitive_discovery_candidates": evidence["stats"]["linked_competitive_discovery_candidates"],
        "open_linked_competitive_candidates_non_authorizing": evidence["stats"]["open_linked_competitive_candidates_non_authorizing"],
        "forthcoming_candidates_non_authorizing": evidence["stats"]["forthcoming_candidates_non_authorizing"],
        "open_call_authorized": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL Creative Europe programme-wide F&T watch: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
