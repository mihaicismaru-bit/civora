#!/usr/bin/env python3
"""Historical ETA Râmnicu Vâlcea detail evidence with explicit currentness reconciliation.

The adapter follows only first-party ETA communication URLs discovered from the
bounded annual archive adapter, captures the same evidence tags used by the
current ETA detail verifier, and compares archive references with the current
ETA communications index. Historical material remains context-only: exact or
topic-level matches on the current index never prove current route, timetable,
fare, entitlement, disruption, event-service or realtime state.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from eta_valcea_transport_archive_reference_adapter import (
    build_receipt as build_archive_receipt,
)
from eta_valcea_transport_detail_evidence import (
    HIGH_VALUE_TOPICS,
    _extract_html_evidence,
    _fetch_detail,
    _sha256_bytes,
    _sha256_text,
)
from eta_valcea_transport_reference_adapter import (
    SOURCE_URL as CURRENT_INDEX_URL,
    build_receipt as build_current_index_receipt,
)

SCHEMA = "ETA_VALCEA_TRANSPORT_HISTORICAL_DETAIL_RECONCILIATION_V1"
PARSER_VERSION = "ETA_VALCEA_TRANSPORT_HISTORICAL_DETAIL_RECONCILIATION_2026_09_02"
SOURCE_FAMILY = "ETA_VALCEA_PUBLIC_TRANSPORT"
AUTHORITY_CLASS = "FIRST_PARTY_LOCAL_PUBLIC_TRANSPORT_OPERATOR_HISTORICAL_DETAIL"
OBSERVATION_STATE = "HISTORICAL_DETAIL_CONTEXT_WITH_CURRENT_INDEX_RECONCILIATION_NON_AUTHORIZING"
SOURCE_ASSERTION_SCOPE = "ETA_HISTORICAL_FIRST_PARTY_STATEMENT_ONLY_CURRENTNESS_NOT_INFERRED"
MAX_DETAILS = 12
MAX_CURRENT_TOPIC_CANDIDATES = 6

NON_AUTHORIZING_FLAGS = {
    "material_fact_use": False,
    "historical_state_promoted_to_current": False,
    "currentness_inference_authorized": False,
    "route_service_current_authorized": False,
    "timetable_current_authorized": False,
    "fare_current_authorized": False,
    "ticketing_current_authorized": False,
    "passenger_entitlement_current_authorized": False,
    "service_disruption_current_authorized": False,
    "event_service_current_authorized": False,
    "realtime_arrival_authorized": False,
    "same_event_dedupe_authorized": False,
    "fact_kernel_write_authorized": False,
    "editorial_writer_authorized": False,
    "publication_authorized": False,
    "distribution_authorized": False,
    "runtime_persistence_authorized": False,
}


def _eligible_archive_reference(ref: dict[str, Any]) -> bool:
    return (
        str(ref.get("source_kind") or "") == "COMMUNIQUES_ARCHIVE"
        and bool(ref.get("historical_reference"))
        and str(ref.get("topic_class") or "") in HIGH_VALUE_TOPICS
        and isinstance(ref.get("archive_year"), int)
    )


def _current_references_by_topic(index: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for ref in index.get("references", []):
        topic = str(ref.get("topic_class") or "")
        target = str(ref.get("target_url") or "")
        title = str(ref.get("title") or "")
        if topic not in HIGH_VALUE_TOPICS or not target:
            continue
        grouped.setdefault(topic, []).append({"title": title, "target_url": target})
    for topic in grouped:
        grouped[topic] = sorted(
            grouped[topic], key=lambda item: (item["target_url"], item["title"].casefold())
        )[:MAX_CURRENT_TOPIC_CANDIDATES]
    return grouped


def _reconciliation_for(
    archive_ref: dict[str, Any],
    current_targets: set[str],
    current_by_topic: dict[str, list[dict[str, str]]],
) -> dict[str, Any]:
    target = str(archive_ref.get("target_url") or "")
    topic = str(archive_ref.get("topic_class") or "")
    topic_candidates = current_by_topic.get(topic, [])
    if target in current_targets:
        state = "CURRENT_INDEX_EXACT_REFERENCE_PRESENT_NON_AUTHORIZING"
    elif topic_candidates:
        state = "CURRENT_INDEX_TOPIC_REFERENCE_PRESENT_REQUIRES_SEMANTIC_REVIEW"
    else:
        state = "NO_CURRENT_INDEX_MATCH_HISTORICAL_ONLY"
    basis = json.dumps(
        {
            "archive_evidence_sha256": str(archive_ref.get("evidence_sha256") or ""),
            "archive_year": archive_ref.get("archive_year"),
            "target_url": target,
            "topic_class": topic,
            "reconciliation_state": state,
            "current_topic_candidates": topic_candidates,
            "source_assertion_scope": SOURCE_ASSERTION_SCOPE,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "reconciliation_state": state,
        "current_exact_reference_present": target in current_targets,
        "current_topic_candidates": topic_candidates,
        "current_service_status": "UNRESOLVED",
        "historical_context_use": "CONTEXT_ONLY_REQUIRES_EDITORIAL_ATTRIBUTION_AND_DATE_BOUNDARY",
        "reconciliation_evidence_sha256": _sha256_text(basis),
    }


def _historical_field_evidence(
    field_items: tuple[Any, ...], archive_year: int, detail_sha256: str
) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for item in field_items:
        tags = list(item.epistemic_tags)
        basis = json.dumps(
            {
                "archive_year": archive_year,
                "detail_sha256": detail_sha256,
                "excerpt": item.excerpt,
                "epistemic_tags": tags,
                "source_assertion_scope": SOURCE_ASSERTION_SCOPE,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        rendered.append(
            {
                "excerpt": item.excerpt,
                "epistemic_tags": tags,
                "detail_extractor_evidence_sha256": item.evidence_sha256,
                "historical_evidence_sha256": _sha256_text(basis),
                "source_assertion_scope": SOURCE_ASSERTION_SCOPE,
                "archive_year": archive_year,
            }
        )
    return rendered


def _base_payload(status: str, archive: dict[str, Any] | None, current: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "status": status,
        "source_family": SOURCE_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "source_assertion_scope": SOURCE_ASSERTION_SCOPE,
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "coverage_note": "BOUNDED_FIRST_PARTY_ETA_ARCHIVE_DETAIL_WITH_CURRENT_INDEX_RECONCILIATION",
        "archive_run_id": (archive or {}).get("run_id"),
        "current_index_run_id": (current or {}).get("run_id"),
        "archive_reference_count": (archive or {}).get("reference_count", 0),
        "current_index_reference_count": (current or {}).get("reference_count", 0),
        "eligible_historical_detail_count": 0,
        "historical_detail_evidence_count": 0,
        "historical_detail_hold_count": 0,
        "details": [],
        "holds": [],
        "limitations": {
            "archive_notice_is_historical_context_not_current_status": True,
            "current_index_presence_does_not_prove_current_service_state": True,
            "same_topic_current_reference_is_not_same_event_or_same_policy": True,
            "absence_from_current_index_does_not_prove_expiry_or_reversal": True,
            "event_transport_schedule_must_not_be_reused_for_future_events": True,
            "current_material_fields_require_separate_first_party_verification": True,
            "sample_is_bounded_and_non_exhaustive": True,
        },
        "interpretation": (
            "HISTORICAL_DETAIL_EVIDENCE_MAY_SUPPORT_DATE_BOUND_CONTEXT_ONLY;"
            "CURRENT_INDEX_RECONCILIATION_IS_DISCOVERY_NOT_CURRENTNESS_PROOF"
        ),
        **NON_AUTHORIZING_FLAGS,
    }


def build_live_receipt() -> dict[str, Any]:
    try:
        archive = build_archive_receipt()
    except (HTTPError, URLError, OSError, RuntimeError, ValueError) as exc:
        payload = _base_payload("HOLD_ARCHIVE_INDEX_FETCH_FAILED_NON_AUTHORIZING", None, None)
        payload["holds"] = [{
            "target_url": "https://eta-bus.ro/comunicate/2025",
            "state": "HOLD_ARCHIVE_INDEX_FETCH_FAILED_NON_AUTHORIZING",
            "reason": f"{type(exc).__name__}:{exc}",
        }]
        stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload["run_id"] = _sha256_text(stable)[:24]
        return payload

    try:
        current = build_current_index_receipt()
    except (HTTPError, URLError, OSError, RuntimeError, ValueError) as exc:
        payload = _base_payload("HOLD_CURRENT_INDEX_FETCH_FAILED_NON_AUTHORIZING", archive, None)
        payload["holds"] = [{
            "target_url": CURRENT_INDEX_URL,
            "state": "HOLD_CURRENT_INDEX_FETCH_FAILED_NON_AUTHORIZING",
            "reason": f"{type(exc).__name__}:{exc}",
        }]
        stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload["run_id"] = _sha256_text(stable)[:24]
        return payload

    if archive.get("status") != "PASS" or current.get("status") != "PASS":
        payload = _base_payload("HOLD_REFERENCE_INDEX_NOT_PASS_NON_AUTHORIZING", archive, current)
        payload["holds"] = [{
            "target_url": CURRENT_INDEX_URL,
            "state": "HOLD_REFERENCE_INDEX_NOT_PASS_NON_AUTHORIZING",
            "reason": f"archive={archive.get('status')};current={current.get('status')}",
        }]
        stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload["run_id"] = _sha256_text(stable)[:24]
        return payload

    candidates = [ref for ref in archive.get("references", []) if _eligible_archive_reference(ref)][:MAX_DETAILS]
    current_targets = {
        str(ref.get("target_url") or "") for ref in current.get("references", []) if ref.get("target_url")
    }
    current_by_topic = _current_references_by_topic(current)

    details: list[dict[str, Any]] = []
    holds: list[dict[str, str]] = []
    for ref in candidates:
        target_url = str(ref.get("target_url") or "")
        archive_year = int(ref.get("archive_year"))
        try:
            body, final_url, content_type = _fetch_detail(target_url)
            detail_sha256 = _sha256_bytes(body)
            visible_title, publication_date, effective_date, field_items, tag_counts = _extract_html_evidence(
                body, detail_sha256, str(ref.get("title") or "") or None
            )
            details.append(
                {
                    "source_kind": "COMMUNIQUES_ARCHIVE_DETAIL",
                    "topic_class": str(ref.get("topic_class") or ""),
                    "archive_year": archive_year,
                    "historical_reference": True,
                    "index_title": str(ref.get("title") or ""),
                    "detail_url": final_url,
                    "detail_host": (urlsplit(final_url).hostname or "").lower(),
                    "content_type": content_type,
                    "content_length": len(body),
                    "detail_sha256": detail_sha256,
                    "archive_index_evidence_sha256": str(ref.get("evidence_sha256") or ""),
                    "visible_title": visible_title,
                    "publication_date_text": publication_date,
                    "effective_date_text": effective_date,
                    "field_evidence": _historical_field_evidence(field_items, archive_year, detail_sha256),
                    "tag_counts": tag_counts,
                    "currentness_state": "HISTORICAL_CONTEXT_ONLY_CURRENT_SERVICE_UNRESOLVED",
                    "verification_state": "ETA_HISTORICAL_SOURCE_TEXT_EVIDENCE_CAPTURED_NON_AUTHORIZING",
                    "authority_class": AUTHORITY_CLASS,
                    "observation_state": OBSERVATION_STATE,
                    "source_assertion_scope": SOURCE_ASSERTION_SCOPE,
                    "parser_version": PARSER_VERSION,
                    "current_reconciliation": _reconciliation_for(ref, current_targets, current_by_topic),
                }
            )
        except (HTTPError, URLError, OSError, RuntimeError, ValueError) as exc:
            holds.append(
                {
                    "target_url": target_url,
                    "archive_year": str(archive_year),
                    "archive_index_evidence_sha256": str(ref.get("evidence_sha256") or ""),
                    "state": "HOLD_HISTORICAL_DETAIL_FETCH_FAILED_NON_AUTHORIZING",
                    "reason": f"{type(exc).__name__}:{exc}",
                }
            )

    if not candidates:
        status = "HOLD_NO_ELIGIBLE_HISTORICAL_DETAIL_REFERENCES"
    elif not details:
        status = "HOLD_NO_HISTORICAL_DETAIL_EVIDENCE"
    else:
        status = "PASS"

    payload = _base_payload(status, archive, current)
    payload.update(
        {
            "eligible_historical_detail_count": len(candidates),
            "historical_detail_evidence_count": len(details),
            "historical_detail_hold_count": len(holds),
            "details": details,
            "holds": holds,
        }
    )
    stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["run_id"] = _sha256_text(stable)[:24]
    return payload


def _self_test() -> None:
    archive_ref = {
        "source_kind": "COMMUNIQUES_ARCHIVE",
        "historical_reference": True,
        "archive_year": 2025,
        "topic_class": "ROUTE_CHANGE",
        "target_url": "https://eta-bus.ro/comunicate/deviere-linia-5",
        "evidence_sha256": "a" * 64,
    }
    assert _eligible_archive_reference(archive_ref)
    assert not _eligible_archive_reference({**archive_ref, "historical_reference": False})
    assert not _eligible_archive_reference({**archive_ref, "source_kind": "COMMUNIQUES"})

    current = {
        "references": [
            {
                "topic_class": "ROUTE_CHANGE",
                "title": "Deviere nouă",
                "target_url": "https://eta-bus.ro/comunicate/deviere-noua",
            },
            {
                "topic_class": "FARE_TICKETING",
                "title": "Tarife",
                "target_url": "https://eta-bus.ro/comunicate/tarife",
            },
        ]
    }
    grouped = _current_references_by_topic(current)
    assert list(grouped) == ["ROUTE_CHANGE", "FARE_TICKETING"]
    topic_only = _reconciliation_for(
        archive_ref,
        {"https://eta-bus.ro/comunicate/deviere-noua"},
        grouped,
    )
    assert topic_only["reconciliation_state"] == "CURRENT_INDEX_TOPIC_REFERENCE_PRESENT_REQUIRES_SEMANTIC_REVIEW"
    assert topic_only["current_service_status"] == "UNRESOLVED"
    assert re.fullmatch(r"[0-9a-f]{64}", topic_only["reconciliation_evidence_sha256"])

    exact = _reconciliation_for(
        archive_ref,
        {archive_ref["target_url"]},
        grouped,
    )
    assert exact["reconciliation_state"] == "CURRENT_INDEX_EXACT_REFERENCE_PRESENT_NON_AUTHORIZING"
    none = _reconciliation_for(archive_ref, set(), {})
    assert none["reconciliation_state"] == "NO_CURRENT_INDEX_MATCH_HISTORICAL_ONLY"
    assert all(value is False for value in NON_AUTHORIZING_FLAGS.values())
    print("ETA Vâlcea historical detail/currentness reconciliation self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description="ETA Vâlcea historical detail/currentness reconciliation")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--live-check", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return 0
    if not args.live_check:
        parser.error("use --self-test or --live-check")

    payload = build_live_receipt()
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
