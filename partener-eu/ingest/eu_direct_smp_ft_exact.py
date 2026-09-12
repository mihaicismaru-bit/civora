#!/usr/bin/env python3
"""Exact current Funding & Tenders evidence for one Single Market Programme topic.

Programme-level Romanian relevance is retained only as non-authorizing market
intelligence. Exact current call status still requires the official F&T topic
readback and downstream semantic reconciliation/material admission. If the
structured exact record exists but the human-facing exact topic endpoint is
unresolvable, emit a degraded immutable receipt rather than inferring CLOSED,
withdrawn, removed, or any other material state.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
from typing import Any, Callable, Mapping

import funding_tenders_fetch as ft
from funding_tenders_api import normalize_payload

SCHEMA = "PARTENER_EU_SMP_FT_EXACT_EVIDENCE_V1"
PARSER_VERSION = "EU_DIRECT_SMP_FT_EXACT_V1_1"
LEGACY_PARSER_VERSION = "EU_DIRECT_SMP_FT_EXACT_V1"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "SINGLE_MARKET_PROGRAMME"
AUTHORITY_CLASS = "EU_COMMISSION_FUNDING_TENDERS"
OBSERVATION_LAYER = "EXACT_CURRENT_TOPIC_NON_AUTHORIZING"
REF_RE = re.compile(r"^SMP-[A-Z0-9]+(?:-[A-Z0-9]+)+$", re.IGNORECASE)
DIRECT_TYPES = {"1", "2"}
PROGRAMME_OVERVIEW_URL = "https://commission.europa.eu/funding-and-tenders/find-funding/eu-funding-programmes/single-market-programme_en"
ROMANIA_EU_URL = "https://european-union.europa.eu/principles-countries-history/eu-countries/romania_en"
MATERIAL_FLAGS = (
    "material_fact_use", "open_call_authorized", "deadline_authorized",
    "budget_authorized", "eligibility_authorized", "publish_authorized",
    "distribution_authorized", "call_alert_authorized",
)


class ExactSMPConflict(ValueError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def validate_reference(reference: str) -> str:
    value = str(reference or "").strip().upper()
    if not REF_RE.fullmatch(value):
        raise ValueError(f"not an explicit Single Market Programme topic reference: {reference!r}")
    return value


def _scalar(value: Any) -> str | None:
    return ft._scalar(value)


def _record_type(record: Mapping[str, Any]) -> str | None:
    return _scalar(record.get("type"))


def _record_programme_reference(record: Mapping[str, Any]) -> str | None:
    for key in ("frameworkProgramme", "programme", "programmeReference"):
        value = _scalar(record.get(key))
        if value:
            return value
    return None


def _first_scalar(record: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _scalar(record.get(key))
        if value:
            return value
    return None


def _framework_programme_map(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("official Facet response must be an object")
    facets = payload.get("facets")
    if not isinstance(facets, list):
        raise ValueError("official Facet response is missing facets")
    matches = [f for f in facets if isinstance(f, dict) and f.get("name") == "frameworkProgramme"]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one frameworkProgramme facet, found {len(matches)}")
    values = matches[0].get("values")
    if not isinstance(values, list) or not values:
        raise ValueError("frameworkProgramme facet has no values")
    result: dict[str, str] = {}
    for row in values:
        if not isinstance(row, dict):
            continue
        code = _scalar(row.get("rawValue"))
        label = _scalar(row.get("value"))
        if not code or not label or label == code or label.isdigit():
            continue
        previous = result.get(code)
        if previous and previous != label:
            raise ValueError(f"ambiguous official programme label for {code}: {previous!r} vs {label!r}")
        result[code] = label
    if not result:
        raise ValueError("frameworkProgramme facet yielded no human-readable labels")
    return result


def _is_smp_label(label: str) -> bool:
    token = re.sub(r"[^a-z0-9]+", " ", label.casefold()).strip()
    return "single market programme" in token


def reference_query() -> dict[str, Any]:
    return {"bool": {"must": [
        {"terms": {"type": list(ft.CALL_TYPES)}},
        {"term": {"programmePeriod": "2021 - 2027"}},
    ]}}


def _material_snapshot(record: Mapping[str, Any], *, programme_label: str, status_label: str) -> dict[str, Any]:
    return {
        "identifier": ft._record_identifier(record),
        "record_type": _record_type(record),
        "programme_reference": _record_programme_reference(record),
        "programme_label": programme_label,
        "call_identifier": _first_scalar(record, "callIdentifier", "callId", "callReference"),
        "status_code": ft._record_status_code(record),
        "status_label": status_label,
        "title": _first_scalar(record, "title", "topicTitle", "name"),
        "deadline_candidate": _first_scalar(record, "deadlineDate", "deadlineDates", "deadline"),
        "budget_candidate": _first_scalar(record, "budget", "budgetOverview", "topicBudget", "callBudget"),
    }


def select_smp_candidate(taxonomy: Mapping[str, Any]) -> dict[str, Any]:
    if taxonomy.get("schema") != "PARTENER_EU_FT_PROGRAMME_TAXONOMY_V1":
        raise ValueError("unexpected programme taxonomy schema")
    if taxonomy.get("market_intelligence_only") is not True or taxonomy.get("material_fact_use") is not False:
        raise ValueError("programme taxonomy crossed discovery boundary")
    candidates = []
    for row in taxonomy.get("records") or []:
        if row.get("programme_family_normalized") != PROGRAMME_FAMILY:
            continue
        identifier = validate_reference(str(row.get("identifier") or ""))
        status = str(row.get("status_label_candidate") or "").strip().casefold()
        priority = 0 if status == "open" else 1 if status in {"forthcoming", "upcoming"} else 2
        candidates.append((priority, identifier, row))
    if not candidates:
        raise ValueError("programme taxonomy contains no Single Market Programme candidate")
    _, identifier, row = sorted(candidates, key=lambda item: (item[0], item[1]))[0]
    return {
        "identifier": identifier,
        "source_taxonomy_fingerprint": row.get("taxonomy_fingerprint"),
        "source_semantic_fingerprint": row.get("source_semantic_fingerprint"),
        "source_status_label_candidate": row.get("status_label_candidate"),
        "source_authority_url_candidate": row.get("authority_url_candidate"),
    }


def programme_fit_evidence(*, observed_at: str) -> dict[str, Any]:
    facts = {
        "programme_scope": [
            "single_market_governance", "sme_competitiveness", "consumer_protection",
            "food_safety", "european_statistics", "standards_and_reporting",
        ],
        "romania_member_state_since": "2007-01-01",
        "fit_state": "ROMANIA_PROGRAMME_LEVEL_FIT_DEMONSTRATED_NON_AUTHORIZING",
    }
    return {
        "observation_state": "PROGRAMME_FIT_RESEARCH_NON_AUTHORIZING",
        "observed_at": observed_at,
        "authority_class": "EU_OFFICIAL_PROGRAMME_AND_MEMBER_STATE_PAGES",
        "programme_overview_url": PROGRAMME_OVERVIEW_URL,
        "romania_member_state_url": ROMANIA_EU_URL,
        "facts": facts,
        "semantic_fingerprint": sha256_json(facts),
        "eligibility_fact_authorized": False,
        "call_fact_authorized": False,
    }


def _build_degraded_exact_semantics(reference: str, authority_url: str, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "identifier": reference,
        "call_identifier_candidate": snapshot.get("call_identifier"),
        "title_candidate": snapshot.get("title"),
        "programme_reference": snapshot.get("programme_reference"),
        "programme_label": snapshot.get("programme_label"),
        "status_label_candidate": snapshot.get("status_label"),
        "authority_url": authority_url,
        "authority_endpoint_verified": False,
        "deadline_candidate_structured_only": snapshot.get("deadline_candidate"),
        "budget_candidate_structured_only": snapshot.get("budget_candidate"),
    }


def collect_exact(
    reference: str, *, run_id: str, fetched_at: str | None = None,
    source_candidate: Mapping[str, Any] | None = None,
    output_dir: pathlib.Path | None = None,
    post_func: Callable[..., tuple[Any, bytes, dict[str, Any]]] = ft._safe_json_post,
    topic_func: Callable[..., dict[str, Any]] = ft._topic_readback,
) -> dict[str, Any]:
    reference = validate_reference(reference)
    fetched_at = fetched_at or utc_now()
    common_parts = {"query": reference_query(), "languages": ["en"]}
    search_payload, search_raw, search_receipt = post_func(
        ft.SEARCH_ENDPOINT, text=reference, page_size=10, page_number=1, parts=common_parts
    )
    facet_payload, facet_raw, facet_receipt = post_func(
        ft.FACET_ENDPOINT, text=reference, page_size=10, page_number=1, parts=common_parts
    )
    matching = [row for row in ft.flatten_search_payload(search_payload)
                if str(ft._record_identifier(row) or "").upper() == reference]
    if not matching:
        raise ValueError(f"Funding & Tenders returned no exact record for {reference}")
    primary = [row for row in matching if _record_type(row) in DIRECT_TYPES]
    linked_type8 = [row for row in matching if _record_type(row) == "8"]
    if not primary:
        raise ValueError(f"Funding & Tenders returned no direct-call record for {reference}")

    programme_labels = _framework_programme_map(facet_payload)
    material_rows: list[tuple[str, Mapping[str, Any], dict[str, Any]]] = []
    for row in primary:
        programme_ref = _record_programme_reference(row)
        programme_label = programme_labels.get(programme_ref or "")
        if not programme_label or not _is_smp_label(programme_label):
            raise ValueError(f"exact record is not proven to belong to Single Market Programme: {programme_ref!r} {programme_label!r}")
        status_code = ft._record_status_code(row)
        status_label = ft.resolve_reference_label([facet_payload], status_code or "") if status_code else None
        if not status_label:
            raise ValueError(f"official Facet did not resolve current status for {reference}")
        snapshot = _material_snapshot(row, programme_label=programme_label, status_label=status_label)
        material_rows.append((sha256_json(snapshot), row, snapshot))
    signatures = sorted({signature for signature, _, _ in material_rows})
    if len(signatures) != 1:
        raise ExactSMPConflict(f"conflicting exact Single Market Programme records for {reference}: {len(signatures)} material variants")
    chosen, snapshot = material_rows[0][1], material_rows[0][2]

    authority_url = ft.topic_url(reference)
    readback = topic_func(authority_url)
    authority_verified = readback.get("verified") is True
    if authority_verified:
        enriched = dict(chosen)
        enriched["statusLabel"] = snapshot["status_label"]
        enriched["authorityUrl"] = authority_url
        batch = normalize_payload([enriched], fetched_at=fetched_at, run_id=run_id, verified_authority_urls=[authority_url])
        records = [row for row in batch.get("records") or [] if str(row.get("identifier") or "").upper() == reference]
        if len(records) != 1:
            raise ValueError(f"exact Single Market Programme normalizer returned {len(records)} records for {reference}")
        normalized = records[0]
        if normalized.get("authority_url_verified") is not True:
            raise ValueError("exact Single Market Programme authority verification was lost during normalization")
        exact_semantics = {
            "identifier": reference, "call_identifier": normalized.get("call_identifier"),
            "title": normalized.get("title"), "programme_reference": snapshot.get("programme_reference"),
            "programme_label": snapshot.get("programme_label"), "status_label": normalized.get("status_label"),
            "observation_state": normalized.get("observation_state"), "authority_url": authority_url,
            "deadline_candidate": normalized.get("deadline_candidate"), "budget_candidate": normalized.get("budget_candidate"),
        }
        candidate_state = normalized.get("observation_state")
        status_label = normalized.get("status_label")
        call_identifier = normalized.get("call_identifier")
        title = normalized.get("title")
        deadline_candidate = normalized.get("deadline_candidate")
        budget_candidate = normalized.get("budget_candidate")
        source_health_state = "HEALTHY"
        lkg_required = False
        evidence_usable_for_reconciliation = True
        degradation_reason = None
    else:
        exact_semantics = _build_degraded_exact_semantics(reference, authority_url, snapshot)
        candidate_state = "UNKNOWN"
        status_label = None
        call_identifier = snapshot.get("call_identifier")
        title = snapshot.get("title")
        deadline_candidate = None
        budget_candidate = None
        source_health_state = "DEGRADED_AUTHORITY_READBACK"
        lkg_required = True
        evidence_usable_for_reconciliation = False
        degradation_reason = str(readback.get("error") or "exact topic endpoint could not be verified")

    fit = programme_fit_evidence(observed_at=fetched_at)
    evidence: dict[str, Any] = {
        "schema": SCHEMA, "parser_version": PARSER_VERSION, "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY, "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_LAYER, "reference": reference, "fetched_at": fetched_at,
        "run_id": run_id, "search_receipt": dict(search_receipt), "facet_receipt": dict(facet_receipt),
        "search_raw_sha256": sha256_bytes(search_raw), "facet_raw_sha256": sha256_bytes(facet_raw),
        "authority_url": authority_url, "authority_readback": dict(readback), "authority_url_verified": authority_verified,
        "source_health_state": source_health_state, "lkg_required": lkg_required,
        "evidence_usable_for_reconciliation": evidence_usable_for_reconciliation,
        "degradation_reason": degradation_reason,
        "candidate_state": candidate_state, "status_label": status_label,
        "call_identifier": call_identifier, "title": title,
        "programme_reference": snapshot.get("programme_reference"), "programme_label_official": snapshot.get("programme_label"),
        "deadline_candidate": deadline_candidate, "budget_candidate": budget_candidate,
        "structured_candidate_snapshot": snapshot,
        "exact_semantics": exact_semantics, "exact_semantic_fingerprint": sha256_json(exact_semantics),
        "primary_exact_record_count": len(primary), "linked_type8_record_count": len(linked_type8),
        "linked_type8_record_hashes": sorted(sha256_json(row) for row in linked_type8),
        "source_candidate": dict(source_candidate or {}),
        "source_candidate_fingerprint": sha256_json(source_candidate) if source_candidate else None,
        "programme_fit_evidence": fit,
        "programme_fit_semantic_fingerprint": sha256_json(fit),
        "semantic_reconciliation_required": True, "field_scoped_material_admission_required": True,
        "publication_effect": "NONE", "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        evidence[key] = False
    validate_evidence(evidence)
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "ft-smp-search-response.json").write_bytes(search_raw)
        (output_dir / "ft-smp-facet-response.json").write_bytes(facet_raw)
        (output_dir / "ft-smp-exact-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return evidence


def validate_evidence(evidence: Mapping[str, Any]) -> None:
    parser_version = evidence.get("parser_version")
    if evidence.get("schema") != SCHEMA or parser_version not in {PARSER_VERSION, LEGACY_PARSER_VERSION}:
        raise ValueError("Single Market Programme exact evidence schema/parser drift")
    reference = validate_reference(str(evidence.get("reference") or ""))
    if evidence.get("source_family") != SOURCE_FAMILY or evidence.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("Single Market Programme exact evidence family drift")
    if evidence.get("authority_class") != AUTHORITY_CLASS:
        raise ValueError("Single Market Programme exact evidence authority class drift")
    if evidence.get("authority_url") != ft.topic_url(reference):
        raise ValueError("Single Market Programme exact evidence exact topic authority URL drift")
    legacy = parser_version == LEGACY_PARSER_VERSION
    usable = evidence.get("evidence_usable_for_reconciliation")
    if legacy and usable is None:
        usable = True
    if usable not in {True, False}:
        raise ValueError("Single Market Programme exact evidence reconciliation-usability state missing")
    readback = evidence.get("authority_readback") or {}
    if usable:
        if evidence.get("authority_url_verified") is not True:
            raise ValueError("Single Market Programme exact evidence lacks verified exact topic authority")
        if readback.get("verified") is not True or readback.get("url") != evidence.get("authority_url"):
            raise ValueError("Single Market Programme exact readback binding invalid")
        if evidence.get("candidate_state") not in {"OPEN_CALL", "FORTHCOMING_CALL", "CLOSED_CALL", "UNKNOWN"}:
            raise ValueError("Single Market Programme exact candidate state unsupported")
        if not evidence.get("status_label"):
            raise ValueError("Single Market Programme exact evidence lacks resolved official status label")
        if not legacy:
            if evidence.get("source_health_state") != "HEALTHY" or evidence.get("lkg_required") is not False:
                raise ValueError("Single Market Programme healthy exact evidence source-health binding invalid")
            if evidence.get("degradation_reason") is not None:
                raise ValueError("Single Market Programme healthy exact evidence unexpectedly carries degradation reason")
    else:
        if legacy:
            raise ValueError("legacy Single Market Programme exact evidence cannot represent degraded current authority")
        if evidence.get("authority_url_verified") is not False or readback.get("verified") is True:
            raise ValueError("Single Market Programme degraded exact evidence pretended authority verification")
        if readback.get("url") and readback.get("url") != evidence.get("authority_url"):
            raise ValueError("Single Market Programme degraded readback URL binding invalid")
        if evidence.get("source_health_state") != "DEGRADED_AUTHORITY_READBACK" or evidence.get("lkg_required") is not True:
            raise ValueError("Single Market Programme degraded exact evidence lacks LKG/source-health requirement")
        if not evidence.get("degradation_reason"):
            raise ValueError("Single Market Programme degraded exact evidence lacks failure reason")
        if evidence.get("candidate_state") != "UNKNOWN" or evidence.get("status_label") is not None:
            raise ValueError("Single Market Programme degraded exact evidence leaked structured status into current truth")
        if evidence.get("deadline_candidate") is not None or evidence.get("budget_candidate") is not None:
            raise ValueError("Single Market Programme degraded exact evidence leaked structured material candidates")
    if not _is_smp_label(str(evidence.get("programme_label_official") or "")):
        raise ValueError("Single Market Programme exact evidence lost official programme proof")
    semantics = evidence.get("exact_semantics")
    if not isinstance(semantics, dict) or sha256_json(semantics) != evidence.get("exact_semantic_fingerprint"):
        raise ValueError("Single Market Programme exact semantic fingerprint mismatch")
    fit = evidence.get("programme_fit_evidence")
    if not isinstance(fit, dict) or sha256_json(fit) != evidence.get("programme_fit_semantic_fingerprint"):
        raise ValueError("Single Market Programme fit evidence fingerprint mismatch")
    if fit.get("observation_state") != "PROGRAMME_FIT_RESEARCH_NON_AUTHORIZING":
        raise ValueError("Single Market Programme fit evidence state drift")
    if fit.get("programme_overview_url") != PROGRAMME_OVERVIEW_URL or fit.get("romania_member_state_url") != ROMANIA_EU_URL:
        raise ValueError("Single Market Programme fit authority URLs drift")
    if fit.get("eligibility_fact_authorized") is not False or fit.get("call_fact_authorized") is not False:
        raise ValueError("Single Market Programme fit research attempted material authorization")
    for key in MATERIAL_FLAGS:
        if evidence.get(key) is not False:
            raise ValueError(f"Single Market Programme exact evidence attempted authorization: {key}")
    if evidence.get("publication_effect") != "NONE" or evidence.get("canonical_corpus_mutation") is not False:
        raise ValueError("Single Market Programme exact evidence crossed publication boundary")
    if evidence.get("semantic_reconciliation_required") is not True or evidence.get("field_scoped_material_admission_required") is not True:
        raise ValueError("Single Market Programme exact evidence skipped downstream gates")
    for receipt_key in ("search_receipt", "facet_receipt"):
        receipt = evidence.get(receipt_key) or {}
        if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("sha256") or "")):
            raise ValueError(f"Single Market Programme exact evidence missing immutable {receipt_key}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--taxonomy", type=pathlib.Path)
    parser.add_argument("--reference")
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    parser.add_argument("--run-id", default="smp-ft-exact-live")
    args = parser.parse_args()
    source_candidate = None
    reference = args.reference
    if args.taxonomy:
        taxonomy = json.loads(args.taxonomy.read_text(encoding="utf-8"))
        source_candidate = select_smp_candidate(taxonomy)
        if reference and validate_reference(reference) != source_candidate["identifier"]:
            raise ValueError("explicit Single Market Programme reference does not match deterministic taxonomy handoff")
        reference = source_candidate["identifier"]
    if not reference:
        raise ValueError("--taxonomy or --reference is required")
    evidence = collect_exact(reference, run_id=args.run_id, source_candidate=source_candidate, output_dir=args.output_dir)
    print(json.dumps({
        "reference": evidence["reference"],
        "candidate_state": evidence["candidate_state"],
        "status_label": evidence["status_label"],
        "authority_url_verified": evidence["authority_url_verified"],
        "source_health_state": evidence["source_health_state"],
        "evidence_usable_for_reconciliation": evidence["evidence_usable_for_reconciliation"],
        "lkg_required": evidence["lkg_required"],
        "programme_fit_state": evidence["programme_fit_evidence"]["facts"]["fit_state"],
        "open_call_authorized": evidence["open_call_authorized"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
