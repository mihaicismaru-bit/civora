#!/usr/bin/env python3
"""Creative Europe exact-topic evidence via the structured Funding & Tenders API.

This is the authoritative handoff for explicit `CREA-*` references discovered
from the mixed Culture & Creativity index. It verifies exact topic identity,
resolves the current status only from official Facet evidence, and performs an
exact official topic-page readback. Even a verified OPEN candidate remains
non-publishing until PARTENER semantic reconciliation/material admission.

When the official Search endpoint returns more than one exact row with
materially different metadata, the adapter fails closed *and* persists a
sanitised conflict diagnostic before raising. This makes source disagreement
observable without selecting an arbitrary row or promoting any candidate fact.
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

import funding_tenders_fetch as ft
from funding_tenders_api import normalize_payload

ADAPTER_ID = "CREATIVE_EUROPE_CALLS_V1"
EVIDENCE_LAYER = "EXACT_FUNDING_TENDERS_TOPIC"
PARSER_VERSION = "CREATIVE_EUROPE_FT_EXACT_V1"
CONFLICT_SCHEMA = "PARTENER_EU_CREATIVE_EUROPE_FT_EXACT_CONFLICT_V1"
CONFLICT_STATE = "EXACT_STRUCTURED_RECORD_CONFLICT_NON_AUTHORIZING"
DEFAULT_REFERENCE = "CREA-MEDIA-2026-DEVMINISLATE"
REF_RE = re.compile(r"^CREA-[A-Z0-9]+(?:-[A-Z0-9]+)+$", re.IGNORECASE)
MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
)


class ExactRecordConflict(ValueError):
    """Official F&T returned materially different rows for one exact reference."""

    def __init__(self, reference: str, diagnostic: Mapping[str, Any]):
        super().__init__(f"conflicting exact Funding & Tenders records for {reference}")
        self.reference = reference
        self.diagnostic = dict(diagnostic)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def validate_reference(reference: str) -> str:
    value = str(reference or "").strip().upper()
    if not REF_RE.fullmatch(value):
        raise ValueError(f"not an explicit Creative Europe CREA-* reference: {reference!r}")
    return value


def reference_query() -> dict[str, Any]:
    # Do not filter status. The same exact call may move Open -> Closed and the
    # current official Facet label must be observed, never encoded locally.
    return {
        "bool": {
            "must": [
                {"terms": {"type": list(ft.CALL_TYPES)}},
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


def _material_snapshot(record: Mapping[str, Any]) -> dict[str, str | None]:
    """Fields whose disagreement can change topic identity/material interpretation.

    We intentionally do not include presentation-only fields such as title or
    search-result snippets. Budget is captured when the structured row exposes a
    scalar value; otherwise it remains null and cannot be inferred locally.
    """
    return {
        "identifier": ft._record_identifier(record),
        "status_code": ft._record_status_code(record),
        "programme": ft._scalar(record.get("programAbbreviation")),
        "programme_period": ft._scalar(record.get("programmePeriod")),
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
    }


def _metadata_signature(record: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json(_material_snapshot(record)))


def _build_conflict_diagnostic(
    reference: str,
    candidates: list[Mapping[str, Any]],
    *,
    fetched_at: str,
    run_id: str,
    search_receipt: Mapping[str, Any],
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
    unique_signatures = sorted({row["material_signature"] for row in rows})
    conflict_fields: list[str] = []
    keys = tuple(_material_snapshot({}).keys())
    for key in keys:
        values = {json.dumps(row["material"].get(key), ensure_ascii=False, sort_keys=True) for row in rows}
        if len(values) > 1:
            conflict_fields.append(key)

    diagnostic: dict[str, Any] = {
        "schema": CONFLICT_SCHEMA,
        "adapter_id": ADAPTER_ID,
        "evidence_layer": EVIDENCE_LAYER,
        "parser_version": PARSER_VERSION,
        "source_family": "EU_DIRECT",
        "programme_family": "CREATIVE_EUROPE",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS",
        "observation_state": CONFLICT_STATE,
        "reference": reference,
        "fetched_at": fetched_at,
        "run_id": run_id,
        "search_receipt": dict(search_receipt),
        "search_raw_sha256": sha256_bytes(search_raw),
        "candidate_count": len(rows),
        "unique_material_signature_count": len(unique_signatures),
        "unique_material_signatures": unique_signatures,
        "conflict_fields": conflict_fields,
        "candidates": rows,
        "semantic_equivalence_proven": len(unique_signatures) == 1,
        "decision": "MATERIAL_CONFLICT_REJECTED",
        "authority_url": ft.topic_url(reference),
        "authority_url_verified": False,
        "market_intelligence_only": True,
        "requires_exact_topic_recheck": True,
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
    if diagnostic.get("schema") != CONFLICT_SCHEMA:
        raise ValueError("Creative Europe exact F&T conflict schema mismatch")
    reference = validate_reference(str(diagnostic.get("reference") or ""))
    if diagnostic.get("adapter_id") != ADAPTER_ID or diagnostic.get("evidence_layer") != EVIDENCE_LAYER:
        raise ValueError("Creative Europe exact F&T conflict identity drift")
    if diagnostic.get("observation_state") != CONFLICT_STATE:
        raise ValueError("Creative Europe exact F&T conflict state drift")
    if diagnostic.get("decision") != "MATERIAL_CONFLICT_REJECTED":
        raise ValueError("Creative Europe exact F&T conflict decision drift")
    if diagnostic.get("authority_url") != ft.topic_url(reference) or diagnostic.get("authority_url_verified") is not False:
        raise ValueError("Creative Europe exact F&T conflict crossed authority-verification boundary")
    if diagnostic.get("semantic_equivalence_proven") is not False:
        raise ValueError("Creative Europe exact F&T conflict incorrectly declared equivalent")
    if diagnostic.get("market_intelligence_only") is not True:
        raise ValueError("Creative Europe exact F&T conflict lost intelligence-only boundary")
    for key in ("requires_exact_topic_recheck", "requires_semantic_reconcile", "requires_material_admission"):
        if diagnostic.get(key) is not True:
            raise ValueError(f"Creative Europe exact F&T conflict skipped downstream gate: {key}")
    if diagnostic.get("publication_effect") != "NONE" or diagnostic.get("canonical_corpus_mutation") is not False:
        raise ValueError("Creative Europe exact F&T conflict crossed publication boundary")
    for key in MATERIAL_FLAGS:
        if diagnostic.get(key) is not False:
            raise ValueError(f"Creative Europe exact F&T conflict became authorizing: {key}")
    for key in ("search_raw_sha256",):
        if not re.fullmatch(r"[0-9a-f]{64}", str(diagnostic.get(key) or "")):
            raise ValueError(f"Creative Europe exact F&T conflict hash invalid: {key}")
    rows = diagnostic.get("candidates") or []
    if len(rows) < 2 or int(diagnostic.get("candidate_count") or 0) != len(rows):
        raise ValueError("Creative Europe exact F&T conflict candidate count invalid")
    signatures = [str(row.get("material_signature") or "") for row in rows]
    if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in signatures):
        raise ValueError("Creative Europe exact F&T conflict candidate signature invalid")
    if len(set(signatures)) <= 1:
        raise ValueError("Creative Europe exact F&T conflict lacks a material disagreement")
    if int(diagnostic.get("unique_material_signature_count") or 0) != len(set(signatures)):
        raise ValueError("Creative Europe exact F&T conflict unique signature count drift")
    if not diagnostic.get("conflict_fields"):
        raise ValueError("Creative Europe exact F&T conflict fields missing")


def collect_exact(
    reference: str,
    *,
    run_id: str,
    fetched_at: str | None = None,
    output_dir: pathlib.Path | None = None,
    post_func: Callable[..., tuple[Any, bytes, dict[str, Any]]] = ft._safe_json_post,
    topic_func: Callable[..., dict[str, Any]] = ft._topic_readback,
) -> dict[str, Any]:
    reference = validate_reference(reference)
    fetched_at = fetched_at or utc_now()
    query = reference_query()
    common_parts = {"query": query, "languages": ["en"]}

    search_payload, search_raw, search_receipt = post_func(
        ft.SEARCH_ENDPOINT,
        text=reference,
        page_size=10,
        page_number=1,
        parts=common_parts,
    )
    candidates = [
        row for row in ft.flatten_search_payload(search_payload)
        if (ft._record_identifier(row) or "").upper() == reference
    ]
    if not candidates:
        raise ValueError(f"Funding & Tenders returned no exact record for {reference}")
    signatures = {_metadata_signature(row) for row in candidates}
    if len(signatures) != 1:
        diagnostic = _build_conflict_diagnostic(
            reference,
            candidates,
            fetched_at=fetched_at,
            run_id=run_id,
            search_receipt=search_receipt,
            search_raw=search_raw,
        )
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "ft-search-response.json").write_bytes(search_raw)
            (output_dir / "ft-exact-conflict.json").write_text(
                json.dumps(diagnostic, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        raise ExactRecordConflict(reference, diagnostic)

    source = copy.deepcopy(candidates[0])
    status_code = ft._record_status_code(source)
    if not status_code:
        raise ValueError(f"exact Funding & Tenders record lacks numeric status reference: {reference}")

    facet_payload, facet_raw, facet_receipt = post_func(
        ft.FACET_ENDPOINT,
        text=reference,
        page_size=10,
        page_number=1,
        parts=common_parts,
    )
    status_label = ft.resolve_reference_label([facet_payload], status_code)
    if not status_label:
        facet_payload2, facet_raw2, facet_receipt2 = post_func(
            ft.FACET_ENDPOINT,
            text=status_code,
            page_size=10,
            page_number=1,
            parts=common_parts,
        )
        status_label = ft.resolve_reference_label([facet_payload, facet_payload2], status_code)
        facet_raw = facet_raw + b"\n" + facet_raw2
        facet_receipt = {
            "primary": facet_receipt,
            "status_resolution": facet_receipt2,
            "sha256": sha256_bytes(facet_raw),
        }
    if not status_label:
        raise ValueError(f"official Facet evidence did not resolve status {status_code} for {reference}")

    exact_url = ft.topic_url(reference)
    readback = topic_func(exact_url)
    if readback.get("verified") is not True:
        raise ValueError(f"exact Funding & Tenders topic readback not verified for {reference}: {readback}")

    source["statusLabel"] = status_label
    source["authorityUrl"] = exact_url
    batch = normalize_payload(
        [source],
        fetched_at=fetched_at,
        run_id=run_id,
        verified_authority_urls=[exact_url],
    )
    rows = batch.get("records") or []
    if len(rows) != 1 or rows[0].get("identifier", "").upper() != reference:
        raise ValueError(f"normalized exact Funding & Tenders identity drift for {reference}")
    normalized = rows[0]
    candidate_state = normalized.get("observation_state")
    if candidate_state not in {"OPEN_CALL", "FORTHCOMING_CALL", "CLOSED_CALL", "UNKNOWN"}:
        raise ValueError(f"unexpected exact Funding & Tenders state: {candidate_state}")
    if candidate_state in {"OPEN_CALL", "FORTHCOMING_CALL"} and normalized.get("authority_url_verified") is not True:
        raise ValueError(f"current Creative Europe state lacks verified exact topic URL: {reference}")

    semantic = {
        "reference": reference,
        "status_code": status_code,
        "status_label": status_label,
        "candidate_observation_state": candidate_state,
        "authority_url": exact_url,
        "authority_url_verified": normalized.get("authority_url_verified"),
        "programme": normalized.get("programme"),
        "deadline_candidate": normalized.get("deadline_candidate"),
        "budget_candidate": normalized.get("budget_candidate"),
    }
    missing = [
        "semantic reconciliation against previous observation/LKG",
        "call-specific material admission for deadline/budget/eligibility/participation",
    ]
    if candidate_state != "OPEN_CALL":
        missing.insert(0, "current Funding & Tenders status is not verified OPEN")

    evidence = {
        "schema": "PARTENER_EU_CREATIVE_EUROPE_FT_EXACT_EVIDENCE_V1",
        "adapter_id": ADAPTER_ID,
        "evidence_layer": EVIDENCE_LAYER,
        "parser_version": PARSER_VERSION,
        "source_family": "EU_DIRECT",
        "programme_family": "CREATIVE_EUROPE",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS",
        "observation_state": "EXACT_TOPIC_EVIDENCE_NON_AUTHORIZING",
        **semantic,
        "fetched_at": fetched_at,
        "run_id": run_id,
        "search_receipt": dict(search_receipt),
        "search_raw_sha256": sha256_bytes(search_raw),
        "facet_receipt": facet_receipt,
        "facet_raw_sha256": sha256_bytes(facet_raw),
        "topic_readback": dict(readback),
        "semantic_fingerprint": sha256_bytes(canonical_json(semantic)),
        "market_intelligence_only": True,
        "requires_reconcile": True,
        "missing_for_material_admission": missing,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        evidence[key] = False
    validate_exact_evidence(evidence)

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "ft-search-response.json").write_bytes(search_raw)
        (output_dir / "ft-facet-response.bin").write_bytes(facet_raw)
        (output_dir / "ft-exact-evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return evidence


def validate_exact_evidence(evidence: Mapping[str, Any]) -> None:
    if evidence.get("schema") != "PARTENER_EU_CREATIVE_EUROPE_FT_EXACT_EVIDENCE_V1":
        raise ValueError("Creative Europe exact F&T evidence schema mismatch")
    reference = validate_reference(str(evidence.get("reference") or ""))
    if evidence.get("adapter_id") != ADAPTER_ID or evidence.get("evidence_layer") != EVIDENCE_LAYER:
        raise ValueError("Creative Europe exact F&T identity drift")
    if evidence.get("observation_state") != "EXACT_TOPIC_EVIDENCE_NON_AUTHORIZING":
        raise ValueError("Creative Europe exact F&T observation state drift")
    if evidence.get("market_intelligence_only") is not True or evidence.get("requires_reconcile") is not True:
        raise ValueError("Creative Europe exact F&T evidence lost reconcile boundary")
    if evidence.get("publication_effect") != "NONE" or evidence.get("canonical_corpus_mutation") is not False:
        raise ValueError("Creative Europe exact F&T evidence crossed publication boundary")
    for key in MATERIAL_FLAGS:
        if evidence.get(key) is not False:
            raise ValueError(f"Creative Europe exact F&T evidence became authorizing: {key}")
    if evidence.get("authority_url") != ft.topic_url(reference) or evidence.get("authority_url_verified") is not True:
        raise ValueError("Creative Europe exact F&T topic identity/verification drift")
    if not evidence.get("status_code") or not evidence.get("status_label"):
        raise ValueError("Creative Europe exact F&T status evidence incomplete")
    for key in ("search_raw_sha256", "facet_raw_sha256", "semantic_fingerprint"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get(key) or "")):
            raise ValueError(f"Creative Europe exact F&T hash invalid: {key}")
    readback = evidence.get("topic_readback") or {}
    if readback.get("verified") is not True or not re.fullmatch(r"[0-9a-f]{64}", str(readback.get("body_sha256") or "")):
        raise ValueError("Creative Europe exact topic readback hash/verification missing")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", default=DEFAULT_REFERENCE)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    args = parser.parse_args()
    evidence = collect_exact(
        args.reference,
        run_id=args.run_id,
        output_dir=args.output_dir,
    )
    print(json.dumps({
        "reference": evidence["reference"],
        "status_label": evidence["status_label"],
        "candidate_observation_state": evidence["candidate_observation_state"],
        "open_call_authorized": evidence["open_call_authorized"],
        "semantic_fingerprint": evidence["semantic_fingerprint"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL Creative Europe exact F&T evidence: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
