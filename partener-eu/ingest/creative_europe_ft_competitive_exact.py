#!/usr/bin/env python3
"""Exact Creative Europe competitive/cascading-call evidence from Funding & Tenders.

Type-8 Funding & Tenders rows are downstream competitive/cascading opportunities,
not the primary CREA-* topic that funded them. This adapter verifies one explicit
competitive-call identity using structured Search/Facet evidence plus a bounded
readback of the exact official ``competitive-calls-cs/<id>`` surface.

The output is evidence only. Even a verified OPEN candidate requires semantic
reconciliation and a separate material-admission decision before PARTENER may
publish status, deadline, budget, eligibility, distribution, or an alert.
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
from urllib.request import Request, build_opener

import funding_tenders_fetch as ft
from creative_europe_ft_exact import validate_reference

ADAPTER_ID = "CREATIVE_EUROPE_COMPETITIVE_CALLS_V1"
EVIDENCE_LAYER = "EXACT_FUNDING_TENDERS_COMPETITIVE_CALL"
PARSER_VERSION = "CREATIVE_EUROPE_FT_COMPETITIVE_EXACT_V1"
SCHEMA = "PARTENER_EU_CREATIVE_EUROPE_FT_COMPETITIVE_EXACT_EVIDENCE_V1"
CONFLICT_SCHEMA = "PARTENER_EU_CREATIVE_EUROPE_FT_COMPETITIVE_EXACT_CONFLICT_V1"
CONFLICT_STATE = "EXACT_COMPETITIVE_STRUCTURED_RECORD_CONFLICT_NON_AUTHORIZING"
COMPETITIVE_BASE = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/competitive-calls-cs/"
COMPETITIVE_PATH_RE = re.compile(r"^/info/funding-tenders/opportunities/portal/screen/opportunities/competitive-calls-cs/([0-9]{1,20})/?$")
COMPETITIVE_ID_RE = re.compile(r"^[0-9]{1,20}$")
MAX_READBACK_BYTES = 2 * 1024 * 1024
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


class CompetitiveRecordConflict(ValueError):
    """Official F&T returned materially different rows for one competitive id."""

    def __init__(self, competitive_id: str, diagnostic: Mapping[str, Any]):
        super().__init__(f"conflicting exact Funding & Tenders competitive records for {competitive_id}")
        self.competitive_id = competitive_id
        self.diagnostic = dict(diagnostic)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def validate_competitive_id(value: str) -> str:
    competitive_id = str(value or "").strip()
    if not COMPETITIVE_ID_RE.fullmatch(competitive_id):
        raise ValueError(f"invalid Funding & Tenders competitive-call id: {value!r}")
    return competitive_id


def competitive_url(competitive_id: str) -> str:
    return COMPETITIVE_BASE + validate_competitive_id(competitive_id)


def competitive_query() -> dict[str, Any]:
    return {
        "bool": {
            "must": [
                {"term": {"type": "8"}},
                {"term": {"programmePeriod": "2021 - 2027"}},
            ]
        }
    }


def _first_scalar(record: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = ft._scalar(record.get(key))
        if value not in (None, ""):
            return value
    return None


def _structured_url(record: Mapping[str, Any]) -> str | None:
    return _first_scalar(record, "esST_URL", "url")


def _competitive_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(str(url))
    match = COMPETITIVE_PATH_RE.fullmatch(parsed.path)
    if parsed.scheme != "https" or parsed.hostname != "ec.europa.eu" or not match:
        return None
    return match.group(1)


def _matches(parent_reference: str, competitive_id: str, record: Mapping[str, Any]) -> bool:
    if ft._scalar(record.get("type")) != "8":
        return False
    if str(ft._record_identifier(record) or "").upper() != parent_reference:
        return False
    return _competitive_id_from_url(_structured_url(record)) == competitive_id


def _material_snapshot(record: Mapping[str, Any]) -> dict[str, str | None]:
    return {
        "parent_reference": str(ft._record_identifier(record) or "").upper() or None,
        "structured_type": ft._scalar(record.get("type")),
        "authority_url_candidate": _structured_url(record),
        "status_code": ft._record_status_code(record),
        "programme": ft._scalar(record.get("programAbbreviation")),
        "call_identifier": ft._scalar(record.get("callIdentifier")),
        "deadline_candidate": _first_scalar(record, "deadlineDate", "deadlineDates"),
        "budget_candidate": _first_scalar(
            record,
            "budget",
            "budgetOverview",
            "budgetTopicAction",
            "topicBudget",
            "callBudget",
        ),
        "title_candidate": ft._scalar(record.get("title")),
    }


def _metadata_signature(record: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json(_material_snapshot(record)))


def _observation_state(status_label: str | None) -> str:
    token = (status_label or "").strip().lower()
    if token == "open":
        return "OPEN_CALL"
    if token == "forthcoming":
        return "FORTHCOMING_CALL"
    if token == "closed":
        return "CLOSED_CALL"
    return "UNKNOWN"


def _competitive_readback(url: str, *, max_bytes: int = MAX_READBACK_BYTES, opener=None) -> dict[str, Any]:
    parsed = urlparse(url)
    match = COMPETITIVE_PATH_RE.fullmatch(parsed.path)
    if parsed.scheme != "https" or parsed.hostname != "ec.europa.eu" or not match:
        raise ValueError(f"unsafe Funding & Tenders competitive-call URL: {url}")
    req = Request(url, method="GET", headers=ft._request_headers(accept="text/html,application/xhtml+xml"))
    op = opener or build_opener()
    try:
        with op.open(req, timeout=25) as response:
            final_url = response.geturl()
            final = urlparse(final_url)
            final_match = COMPETITIVE_PATH_RE.fullmatch(final.path)
            status = getattr(response, "status", response.getcode())
            ctype = (response.headers.get("Content-Type") or "").lower()
            raw = response.read(max_bytes + 1)
    except Exception as exc:
        return {"url": url, "verified": False, "error": f"{type(exc).__name__}: {exc}"}
    if len(raw) > max_bytes:
        return {
            "url": url,
            "final_url": final_url,
            "http_status": status,
            "verified": False,
            "error": "response too large",
        }
    verified = (
        status == 200
        and final.scheme == "https"
        and final.hostname == "ec.europa.eu"
        and final_match is not None
        and final_match.group(1) == match.group(1)
        and "html" in ctype
    )
    return {
        "url": url,
        "final_url": final_url,
        "http_status": status,
        "content_type": ctype,
        "bytes": len(raw),
        "body_sha256": sha256_bytes(raw),
        "verified": bool(verified),
    }


def _build_conflict_diagnostic(
    parent_reference: str,
    competitive_id: str,
    candidates: list[Mapping[str, Any]],
    *,
    fetched_at: str,
    run_id: str,
    search_receipts: list[Mapping[str, Any]],
    search_raw: bytes,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for index, record in enumerate(candidates):
        material = _material_snapshot(record)
        rows.append({
            "candidate_index": index,
            "material": material,
            "material_signature": sha256_bytes(canonical_json(material)),
            "record_sha256": sha256_bytes(canonical_json(record)),
        })
    signatures = sorted({row["material_signature"] for row in rows})
    fields: list[str] = []
    for key in _material_snapshot({}).keys():
        values = {json.dumps(row["material"].get(key), ensure_ascii=False, sort_keys=True) for row in rows}
        if len(values) > 1:
            fields.append(key)
    diagnostic: dict[str, Any] = {
        "schema": CONFLICT_SCHEMA,
        "adapter_id": ADAPTER_ID,
        "evidence_layer": EVIDENCE_LAYER,
        "parser_version": PARSER_VERSION,
        "source_family": "EU_DIRECT",
        "programme_family": "CREATIVE_EUROPE",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS_COMPETITIVE_CALL",
        "observation_state": CONFLICT_STATE,
        "parent_reference": parent_reference,
        "competitive_call_id": competitive_id,
        "identity_key": f"FUNDING_TENDERS_COMPETITIVE_CALL:{competitive_id}",
        "authority_url": competitive_url(competitive_id),
        "authority_url_verified": False,
        "fetched_at": fetched_at,
        "run_id": run_id,
        "search_receipts": [dict(item) for item in search_receipts],
        "search_raw_sha256": sha256_bytes(search_raw),
        "candidate_count": len(rows),
        "unique_material_signature_count": len(signatures),
        "unique_material_signatures": signatures,
        "conflict_fields": fields,
        "candidates": rows,
        "semantic_equivalence_proven": len(signatures) == 1,
        "decision": "MATERIAL_CONFLICT_REJECTED",
        "market_intelligence_only": True,
        "requires_exact_competitive_call_recheck": True,
        "requires_semantic_reconcile": True,
        "requires_material_admission": True,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        diagnostic[key] = False
    validate_conflict_diagnostic(diagnostic)
    return diagnostic


def validate_conflict_diagnostic(diagnostic: Mapping[str, Any]) -> None:
    if diagnostic.get("schema") != CONFLICT_SCHEMA or diagnostic.get("adapter_id") != ADAPTER_ID:
        raise ValueError("Creative Europe competitive conflict identity drift")
    parent = validate_reference(str(diagnostic.get("parent_reference") or ""))
    competitive_id = validate_competitive_id(str(diagnostic.get("competitive_call_id") or ""))
    if diagnostic.get("identity_key") != f"FUNDING_TENDERS_COMPETITIVE_CALL:{competitive_id}":
        raise ValueError("Creative Europe competitive conflict identity-key drift")
    if diagnostic.get("authority_url") != competitive_url(competitive_id) or diagnostic.get("authority_url_verified") is not False:
        raise ValueError("Creative Europe competitive conflict crossed authority boundary")
    if diagnostic.get("observation_state") != CONFLICT_STATE or diagnostic.get("decision") != "MATERIAL_CONFLICT_REJECTED":
        raise ValueError("Creative Europe competitive conflict state/decision drift")
    if diagnostic.get("semantic_equivalence_proven") is not False:
        raise ValueError("Creative Europe competitive conflict incorrectly declared equivalent")
    rows = list(diagnostic.get("candidates") or [])
    if len(rows) < 2 or len(rows) != int(diagnostic.get("candidate_count") or 0):
        raise ValueError("Creative Europe competitive conflict candidate count invalid")
    signatures = [str(row.get("material_signature") or "") for row in rows]
    if len(set(signatures)) <= 1 or any(not re.fullmatch(r"[0-9a-f]{64}", item) for item in signatures):
        raise ValueError("Creative Europe competitive conflict lacks material disagreement")
    if not diagnostic.get("conflict_fields"):
        raise ValueError("Creative Europe competitive conflict fields missing")
    if not re.fullmatch(r"[0-9a-f]{64}", str(diagnostic.get("search_raw_sha256") or "")):
        raise ValueError("Creative Europe competitive conflict search hash invalid")
    if diagnostic.get("market_intelligence_only") is not True:
        raise ValueError("Creative Europe competitive conflict lost intelligence boundary")
    for key in MATERIAL_FLAGS:
        if diagnostic.get(key) is not False:
            raise ValueError(f"Creative Europe competitive conflict became authorizing: {key}")
    if parent != str(diagnostic.get("parent_reference") or "").upper():
        raise ValueError("Creative Europe competitive conflict parent identity drift")


def collect_exact(
    parent_reference: str,
    competitive_id: str,
    *,
    run_id: str,
    fetched_at: str | None = None,
    output_dir: pathlib.Path | None = None,
    source_candidate: Mapping[str, Any] | None = None,
    post_func: Callable[..., tuple[Any, bytes, dict[str, Any]]] = ft._safe_json_post,
    readback_func: Callable[..., dict[str, Any]] = _competitive_readback,
) -> dict[str, Any]:
    parent_reference = validate_reference(parent_reference)
    competitive_id = validate_competitive_id(competitive_id)
    if not str(run_id or "").strip():
        raise ValueError("run_id is required")
    fetched_at = fetched_at or utc_now()
    query = competitive_query()
    parts = {"query": query, "languages": ["en"]}

    search_receipts: list[dict[str, Any]] = []
    search_raw_parts: list[bytes] = []
    matching: list[dict[str, Any]] = []
    for text in (parent_reference, competitive_id):
        payload, raw, receipt = post_func(
            ft.SEARCH_ENDPOINT,
            text=text,
            page_size=25,
            page_number=1,
            parts=parts,
        )
        search_receipts.append(dict(receipt))
        search_raw_parts.append(raw)
        for row in ft.flatten_search_payload(payload):
            if _matches(parent_reference, competitive_id, row):
                matching.append(copy.deepcopy(row))
        if matching:
            break
    if not matching:
        raise ValueError(
            f"Funding & Tenders returned no exact type-8 record for {parent_reference} competitive call {competitive_id}"
        )

    dedup: dict[str, dict[str, Any]] = {}
    for row in matching:
        dedup.setdefault(sha256_bytes(canonical_json(row)), row)
    matching = list(dedup.values())
    signatures = {_metadata_signature(row) for row in matching}
    search_raw = b"\n".join(search_raw_parts)
    if len(signatures) != 1:
        diagnostic = _build_conflict_diagnostic(
            parent_reference,
            competitive_id,
            matching,
            fetched_at=fetched_at,
            run_id=run_id,
            search_receipts=search_receipts,
            search_raw=search_raw,
        )
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "ft-competitive-search-response.bin").write_bytes(search_raw)
            (output_dir / "ft-competitive-exact-conflict.json").write_text(
                json.dumps(diagnostic, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        raise CompetitiveRecordConflict(competitive_id, diagnostic)

    source = copy.deepcopy(matching[0])
    status_code = ft._record_status_code(source)
    if not status_code:
        raise ValueError(f"exact competitive Funding & Tenders record lacks numeric status: {competitive_id}")

    facet_payload, facet_raw, facet_receipt = post_func(
        ft.FACET_ENDPOINT,
        text=competitive_id,
        page_size=10,
        page_number=1,
        parts=parts,
    )
    status_label = ft.resolve_reference_label([facet_payload], status_code)
    if not status_label:
        facet_payload2, facet_raw2, facet_receipt2 = post_func(
            ft.FACET_ENDPOINT,
            text=status_code,
            page_size=10,
            page_number=1,
            parts=parts,
        )
        status_label = ft.resolve_reference_label([facet_payload, facet_payload2], status_code)
        facet_raw = facet_raw + b"\n" + facet_raw2
        facet_receipt = {
            "primary": facet_receipt,
            "status_resolution": facet_receipt2,
            "sha256": sha256_bytes(facet_raw),
        }
    if not status_label:
        raise ValueError(f"official Facet evidence did not resolve status {status_code} for competitive call {competitive_id}")

    authority_url = competitive_url(competitive_id)
    readback = readback_func(authority_url)
    if readback.get("verified") is not True:
        raise ValueError(f"exact Funding & Tenders competitive-call readback not verified for {competitive_id}: {readback}")

    candidate_state = _observation_state(status_label)
    material = _material_snapshot(source)
    semantic = {
        "identity_key": f"FUNDING_TENDERS_COMPETITIVE_CALL:{competitive_id}",
        "competitive_call_id": competitive_id,
        "parent_reference": parent_reference,
        "status_code": status_code,
        "status_label": status_label,
        "candidate_observation_state": candidate_state,
        "authority_url": authority_url,
        "authority_url_verified": True,
        "programme": material.get("programme"),
        "call_identifier": material.get("call_identifier"),
        "deadline_candidate": material.get("deadline_candidate"),
        "budget_candidate": material.get("budget_candidate"),
        "title_candidate": material.get("title_candidate"),
    }
    source_candidate_fingerprint = None
    if source_candidate is not None:
        candidate_identity = str(source_candidate.get("identity_key") or "")
        if candidate_identity != semantic["identity_key"]:
            raise ValueError("competitive exact source-candidate identity mismatch")
        candidate_parent = validate_reference(str(source_candidate.get("parent_reference") or ""))
        if candidate_parent != parent_reference:
            raise ValueError("competitive exact source-candidate parent mismatch")
        source_candidate_fingerprint = str(source_candidate.get("semantic_fingerprint") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", source_candidate_fingerprint):
            raise ValueError("competitive exact source-candidate fingerprint invalid")

    missing = [
        "identity-keyed semantic reconciliation against previous exact competitive-call observation",
        "competitive/cascading-call material admission for deadline/budget/eligibility/participation",
    ]
    if candidate_state != "OPEN_CALL":
        missing.insert(0, "current Funding & Tenders competitive-call status is not verified OPEN")

    evidence: dict[str, Any] = {
        "schema": SCHEMA,
        "adapter_id": ADAPTER_ID,
        "evidence_layer": EVIDENCE_LAYER,
        "parser_version": PARSER_VERSION,
        "source_family": "EU_DIRECT",
        "programme_family": "CREATIVE_EUROPE",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS_COMPETITIVE_CALL",
        "observation_state": "EXACT_COMPETITIVE_CALL_EVIDENCE_NON_AUTHORIZING",
        **semantic,
        "fetched_at": fetched_at,
        "run_id": run_id,
        "search_receipts": search_receipts,
        "search_raw_sha256": sha256_bytes(search_raw),
        "facet_receipt": dict(facet_receipt),
        "facet_raw_sha256": sha256_bytes(facet_raw),
        "authority_readback": dict(readback),
        "semantic_fingerprint": sha256_bytes(canonical_json(semantic)),
        "source_candidate_semantic_fingerprint": source_candidate_fingerprint,
        "market_intelligence_only": True,
        "requires_reconcile": True,
        "requires_material_admission": True,
        "missing_for_material_admission": missing,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        evidence[key] = False
    validate_exact_evidence(evidence)

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "ft-competitive-search-response.bin").write_bytes(search_raw)
        (output_dir / "ft-competitive-facet-response.bin").write_bytes(facet_raw)
        (output_dir / "ft-competitive-exact-evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return evidence


def validate_exact_evidence(evidence: Mapping[str, Any]) -> None:
    if evidence.get("schema") != SCHEMA or evidence.get("adapter_id") != ADAPTER_ID:
        raise ValueError("Creative Europe competitive exact evidence identity drift")
    parent = validate_reference(str(evidence.get("parent_reference") or ""))
    competitive_id = validate_competitive_id(str(evidence.get("competitive_call_id") or ""))
    if evidence.get("identity_key") != f"FUNDING_TENDERS_COMPETITIVE_CALL:{competitive_id}":
        raise ValueError("Creative Europe competitive exact identity-key drift")
    if evidence.get("evidence_layer") != EVIDENCE_LAYER:
        raise ValueError("Creative Europe competitive exact layer drift")
    if evidence.get("observation_state") != "EXACT_COMPETITIVE_CALL_EVIDENCE_NON_AUTHORIZING":
        raise ValueError("Creative Europe competitive exact observation-state drift")
    if evidence.get("authority_url") != competitive_url(competitive_id) or evidence.get("authority_url_verified") is not True:
        raise ValueError("Creative Europe competitive exact authority identity/verification drift")
    if evidence.get("market_intelligence_only") is not True or evidence.get("requires_reconcile") is not True:
        raise ValueError("Creative Europe competitive exact evidence lost reconciliation boundary")
    if evidence.get("requires_material_admission") is not True:
        raise ValueError("Creative Europe competitive exact evidence skipped material-admission gate")
    if evidence.get("candidate_observation_state") not in {"OPEN_CALL", "FORTHCOMING_CALL", "CLOSED_CALL", "UNKNOWN"}:
        raise ValueError("Creative Europe competitive exact candidate state invalid")
    if not evidence.get("status_code") or not evidence.get("status_label"):
        raise ValueError("Creative Europe competitive exact status evidence incomplete")
    if evidence.get("publication_effect") != "NONE" or evidence.get("canonical_corpus_mutation") is not False:
        raise ValueError("Creative Europe competitive exact evidence crossed publication boundary")
    for key in MATERIAL_FLAGS:
        if evidence.get(key) is not False:
            raise ValueError(f"Creative Europe competitive exact evidence became authorizing: {key}")
    for key in ("search_raw_sha256", "facet_raw_sha256", "semantic_fingerprint"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get(key) or "")):
            raise ValueError(f"Creative Europe competitive exact hash invalid: {key}")
    source_fp = evidence.get("source_candidate_semantic_fingerprint")
    if source_fp is not None and not re.fullmatch(r"[0-9a-f]{64}", str(source_fp)):
        raise ValueError("Creative Europe competitive exact source-candidate binding invalid")
    readback = evidence.get("authority_readback") or {}
    if readback.get("verified") is not True or not re.fullmatch(r"[0-9a-f]{64}", str(readback.get("body_sha256") or "")):
        raise ValueError("Creative Europe competitive exact readback verification/hash missing")
    if parent != str(evidence.get("parent_reference") or "").upper():
        raise ValueError("Creative Europe competitive exact parent identity drift")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-reference", required=True)
    parser.add_argument("--competitive-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    args = parser.parse_args()
    evidence = collect_exact(
        args.parent_reference,
        args.competitive_id,
        run_id=args.run_id,
        output_dir=args.output_dir,
    )
    print(json.dumps({
        "identity_key": evidence["identity_key"],
        "parent_reference": evidence["parent_reference"],
        "status_label": evidence["status_label"],
        "candidate_observation_state": evidence["candidate_observation_state"],
        "authority_url_verified": evidence["authority_url_verified"],
        "open_call_authorized": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL Creative Europe exact competitive F&T evidence: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
