#!/usr/bin/env python3
"""Fail-closed semantic reconciliation for exact EU4Health HaDEA and F&T evidence.

The module binds an exact HaDEA receipt to a fresh exact structured Funding &
Tenders topic readback. It never publishes or mutates canonical opportunity
state. F&T status wording is resolved only from official EC Facet evidence and
raw F&T responses are retained for replay when an output directory is supplied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import funding_tenders_fetch as ft

SCHEMA_VERSION = "1.0"
RECONCILER_VERSION = "EU4HEALTH_HADEA_FT_RECONCILE_V1"
AUTHORITY_CLASS = "OFFICIAL_EXECUTIVE_AGENCY_PLUS_EC_FUNDING_TENDERS_EXACT_TOPIC"
MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
)
HEX64 = set("0123456789abcdef")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fingerprint(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256(raw)


def _valid_sha256(value: Any) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(ch in HEX64 for ch in text)


def _normalize_status(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).strip().split())
    return ft.normalize_official_status_label(text) if text else None


def _topic_identity_matches(candidate: Any, expected: str) -> bool:
    """Compare exact F&T topic identity while ignoring discovery query params.

    HaDEA legitimately links to the exact topic path with search/filter query
    parameters appended. Query parameters are not topic identity; scheme, host,
    port and exact path are. This stays bounded to the canonical EC host/path.
    """
    value = str(candidate or "")
    if not value or not expected:
        return False
    parsed = urlparse(value)
    target = urlparse(expected)
    try:
        port_ok = parsed.port in (None, 443)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == target.hostname == ft.ALLOWED_TOPIC_HOST
        and port_ok
        and parsed.username is None
        and parsed.password is None
        and parsed.path.rstrip("/") == target.path.rstrip("/")
    )


def _assert_hadea_boundary(receipt: Mapping[str, Any]) -> None:
    if receipt.get("adapter_id") != "EU4HEALTH_HADEA_CALLS_V1":
        raise ValueError("unexpected HaDEA adapter identity")
    if receipt.get("source_family") != "EU_DIRECT" or receipt.get("programme_family") != "EU4Health":
        raise ValueError("HaDEA source/programme boundary drift")
    if receipt.get("observation_state") != "EXACT_CALL_EVIDENCE_UNRECONCILED":
        raise ValueError("HaDEA input must be unreconciled exact-call evidence")
    if receipt.get("market_intelligence_only") is not True or receipt.get("publication_effect") != "NONE":
        raise ValueError("HaDEA input policy drift")
    for key in MATERIAL_FLAGS:
        if receipt.get(key) is not False:
            raise ValueError(f"HaDEA input became authorizing: {key}")


def collect_exact_funding_tenders_topic(
    identifier: str,
    *,
    output_dir: Path | None = None,
    opener=None,
) -> dict[str, Any]:
    """Collect exact F&T structured identity/status plus official status label."""
    topic_page_url = ft.topic_url(identifier)
    structured, structured_raw = ft._structured_topic_readback(identifier, opener=opener)
    status_codes = list(structured.get("status_codes") or [])
    status_code = str(status_codes[0]) if structured.get("verified") is True and len(status_codes) == 1 else None
    status_label: str | None = None
    facet_attempts: list[dict[str, Any]] = []
    facet_raw_blobs: list[tuple[str, bytes]] = []

    if status_code:
        # Deliberately omit OPEN/FORTHCOMING filters so CLOSED historical fixtures
        # can also be resolved from current official Facet semantics.
        query = {"bool": {"must": [{"terms": {"type": list(ft.CALL_TYPES)}}]}}
        for index, text in enumerate((status_code, "***"), start=1):
            try:
                payload, raw, receipt = ft._safe_json_post(
                    ft.FACET_ENDPOINT,
                    text=text,
                    page_size=25,
                    page_number=1,
                    parts={"query": query, "languages": ["en"]},
                    opener=opener,
                )
                label = ft.resolve_reference_label([payload], status_code)
                facet_attempts.append({"query_text": text, "receipt": receipt, "resolved_status_label": label})
                facet_raw_blobs.append((f"funding-tenders-status-facet-{index}.json", raw))
                if label:
                    status_label = label
                    break
            except Exception as exc:
                facet_attempts.append({
                    "query_text": text,
                    "error": f"{type(exc).__name__}: {exc}",
                    "resolved_status_label": None,
                })

    topic_readback = ft._topic_readback(topic_page_url, opener=opener)
    verified = (
        structured.get("verified") is True
        and structured.get("identifier") == identifier
        and len(status_codes) == 1
        and _valid_sha256(structured.get("raw_sha256"))
        and status_label is not None
        and topic_readback.get("verified") is True
        and _valid_sha256(topic_readback.get("body_sha256"))
    )

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        if structured_raw:
            (output_dir / "funding-tenders-exact-topic.json").write_bytes(structured_raw)
        for filename, raw in facet_raw_blobs:
            (output_dir / filename).write_bytes(raw)

    return {
        "schema_version": SCHEMA_VERSION,
        "collector_version": RECONCILER_VERSION,
        "source_family": "EU_DIRECT",
        "programme_family": "EU4Health",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS_EXACT_TOPIC",
        "identifier": identifier,
        "topic_url": topic_page_url,
        "structured_topic": structured,
        "status_code": status_code,
        "status_label": status_label,
        "facet_attempts": facet_attempts,
        "topic_page_readback": topic_readback,
        "verified": bool(verified),
        "material_fact_use": False,
        "publish_authorized": False,
        "publication_effect": "NONE",
    }


def reconcile(
    hadea_receipt: Mapping[str, Any],
    funding_tenders_receipt: Mapping[str, Any],
    *,
    run_id: str,
    observed_at: str | None = None,
) -> dict[str, Any]:
    _assert_hadea_boundary(hadea_receipt)
    observed = observed_at or _utc_now()
    extracted = hadea_receipt.get("extracted") or {}
    hadea_reference = str(extracted.get("call_reference") or "")
    hadea_status = _normalize_status(extracted.get("status_candidate"))
    hadea_topic_url = str(extracted.get("funding_tenders_exact_topic_url") or "")
    hadea_hash = str((hadea_receipt.get("source_health") or {}).get("raw_sha256") or "")

    ft_reference = str(funding_tenders_receipt.get("identifier") or "")
    ft_status = _normalize_status(funding_tenders_receipt.get("status_label"))
    structured = funding_tenders_receipt.get("structured_topic") or {}
    ft_structured_hash = str(structured.get("raw_sha256") or "")
    expected_topic_url = ft.topic_url(hadea_reference) if hadea_reference else ""

    hadea_usable = (
        hadea_receipt.get("evidence_usable_for_reconciliation") is True
        and (hadea_receipt.get("source_health") or {}).get("health_state") == "HEALTHY"
        and _valid_sha256(hadea_hash)
    )
    ft_usable = (
        funding_tenders_receipt.get("verified") is True
        and funding_tenders_receipt.get("source_family") == "EU_DIRECT"
        and funding_tenders_receipt.get("programme_family") == "EU4Health"
        and funding_tenders_receipt.get("authority_class") == "EU_COMMISSION_FUNDING_TENDERS_EXACT_TOPIC"
        and _valid_sha256(ft_structured_hash)
    )
    identity_match = bool(hadea_reference) and hadea_reference == ft_reference == structured.get("identifier")
    topic_url_match = (
        bool(expected_topic_url)
        and _topic_identity_matches(hadea_topic_url, expected_topic_url)
        and _topic_identity_matches(funding_tenders_receipt.get("topic_url"), expected_topic_url)
    )
    status_match = bool(hadea_status and ft_status) and hadea_status.casefold() == ft_status.casefold()
    programme_match = extracted.get("programme_candidate") == "EU4Health"
    reconciled = all((hadea_usable, ft_usable, identity_match, topic_url_match, status_match, programme_match))

    missing: list[str] = []
    if not hadea_usable:
        missing.append("healthy_exact_hadea_evidence")
    if not ft_usable:
        missing.append("verified_exact_structured_funding_tenders_evidence")
    if not identity_match:
        missing.append("same_call_reference_match_hadea_to_funding_tenders")
    if not topic_url_match:
        missing.append("exact_funding_tenders_topic_url_match")
    if not status_match:
        missing.append("semantic_status_match_hadea_to_funding_tenders")
    if not programme_match:
        missing.append("eu4health_programme_identity")
    if reconciled:
        missing.extend([
            "downstream_material_admission_policy",
            "call_specific_deadline_budget_eligibility_and_participation_rules",
        ])
        if (ft_status or "").casefold() != "open":
            missing.append("current_funding_tenders_status_is_not_open")

    state = "EXACT_CALL_REFERENCE_AND_STATUS_RECONCILED_NON_AUTHORIZING" if reconciled else "RECONCILIATION_FAILED_CLOSED"
    semantic_payload = {
        "call_reference": hadea_reference if identity_match else None,
        "hadea_status": hadea_status,
        "funding_tenders_status": ft_status,
        "hadea_raw_sha256": hadea_hash if _valid_sha256(hadea_hash) else None,
        "funding_tenders_raw_sha256": ft_structured_hash if _valid_sha256(ft_structured_hash) else None,
        "identity_match": identity_match,
        "topic_url_match": topic_url_match,
        "status_match": status_match,
        "programme_match": programme_match,
        "reconciled": reconciled,
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "reconciler_version": RECONCILER_VERSION,
        "run_id": run_id,
        "fetched_at": observed,
        "source_family": "EU_DIRECT",
        "programme_family": "EU4Health",
        "authority_class": AUTHORITY_CLASS,
        "observation_state": state,
        "hadea_reference": hadea_reference or None,
        "funding_tenders_reference": ft_reference or None,
        "hadea_status_candidate": hadea_status,
        "funding_tenders_status": ft_status,
        "identity_match": identity_match,
        "topic_url_match": topic_url_match,
        "status_match": status_match,
        "programme_match": programme_match,
        "semantic_reconciliation_passed": reconciled,
        "material_admission_ready_for_downstream_review": reconciled,
        "candidate_material_status": ft_status if reconciled else None,
        "semantic_fingerprint": _fingerprint(semantic_payload),
        "missing_for_open_confirmation": missing,
        "market_intelligence_only": True,
        "material_fact_use": False,
        "open_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
        "note": (
            "Same-reference HaDEA and structured Funding & Tenders evidence may be semantically reconciled here, "
            "but this receipt remains non-authorizing. Downstream material admission must separately enforce "
            "current-status, deadline, budget, eligibility and participation evidence requirements."
        ),
        "rollback": "Discard this reconciliation receipt and raw evidence files; no canonical state is mutated.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile exact EU4Health HaDEA evidence with exact structured F&T evidence.")
    parser.add_argument("--hadea-evidence", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--observed-at")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    hadea = json.loads(args.hadea_evidence.read_text(encoding="utf-8"))
    reference = str((hadea.get("extracted") or {}).get("call_reference") or "")
    if not reference:
        raise ValueError("HaDEA evidence has no exact call reference")
    if not args.live:
        raise ValueError("live exact Funding & Tenders readback is required for reconciliation CLI")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    ft_receipt = collect_exact_funding_tenders_topic(reference, output_dir=args.output_dir)
    (args.output_dir / "funding-tenders-exact-topic-receipt.json").write_text(
        json.dumps(ft_receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    result = reconcile(hadea, ft_receipt, run_id=args.run_id, observed_at=args.observed_at)
    (args.output_dir / "hadea-funding-tenders-reconciliation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "observation_state": result["observation_state"],
        "hadea_reference": result["hadea_reference"],
        "funding_tenders_reference": result["funding_tenders_reference"],
        "funding_tenders_status": result["funding_tenders_status"],
        "semantic_reconciliation_passed": result["semantic_reconciliation_passed"],
        "open_call_authorized": result["open_call_authorized"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
