#!/usr/bin/env python3
"""Exact current Funding & Tenders evidence for one CERV topic.

A structured CERV discovery pointer may select the identity, but all current
status evidence is re-fetched from official F&T Search/Facet and the exact topic
endpoint. Programme/programming evidence remains non-authorizing and is bound
separately. This adapter never authorizes material facts or publication.
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
from eu_direct_cerv_ft_discovery import validate_receipt as validate_discovery, validate_reference
from eu_direct_cerv_programme_watch import validate_receipt as validate_programme_watch

SCHEMA = "PARTENER_EU_CERV_FT_EXACT_EVIDENCE_V1"
PARSER_VERSION = "EU_DIRECT_CERV_FT_EXACT_V1"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "CERV"
AUTHORITY_CLASS = "EU_COMMISSION_FUNDING_TENDERS"
OBSERVATION_LAYER = "EXACT_CURRENT_TOPIC_NON_AUTHORIZING"
DIRECT_TYPES = {"1", "2"}
MATERIAL_FLAGS = (
    "material_fact_use", "open_call_authorized", "deadline_authorized",
    "budget_authorized", "eligibility_authorized", "publish_authorized",
    "distribution_authorized", "call_alert_authorized",
)


class ExactCERVConflict(ValueError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


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


def _is_cerv_label(label: str) -> bool:
    token = re.sub(r"[^a-z0-9]+", " ", str(label).casefold()).strip()
    return "citizens equality rights and values" in token or token == "cerv" or token.endswith(" cerv")


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


def select_cerv_candidate(discovery: Mapping[str, Any]) -> dict[str, Any]:
    discovery_obj = dict(discovery)
    validate_discovery(discovery_obj)
    selected = discovery_obj.get("selected_candidate")
    if not isinstance(selected, Mapping):
        raise ValueError("CERV structured discovery contains no safe exact candidate")
    identifier = validate_reference(str(discovery_obj.get("selected_reference") or ""))
    if selected.get("identifier") != identifier:
        raise ValueError("CERV structured discovery selected identity mismatch")
    return {
        "identifier": identifier,
        "source_discovery_fingerprint": discovery_obj.get("semantic_fingerprint"),
        "source_candidate_fingerprint": selected.get("semantic_fingerprint"),
        "source_status_label_candidate": selected.get("status_label_candidate"),
        "source_authority_url_candidate": selected.get("authority_url_candidate"),
        "source_call_identifier": selected.get("call_identifier"),
    }


def collect_exact(
    reference: str,
    *,
    run_id: str,
    fetched_at: str | None = None,
    source_candidate: Mapping[str, Any] | None = None,
    programme_watch: Mapping[str, Any] | None = None,
    output_dir: pathlib.Path | None = None,
    post_func: Callable[..., tuple[Any, bytes, dict[str, Any]]] = ft._safe_json_post,
    topic_func: Callable[..., dict[str, Any]] = ft._topic_readback,
) -> dict[str, Any]:
    reference = validate_reference(reference)
    fetched_at = fetched_at or utc_now()
    if programme_watch is not None:
        validate_programme_watch(programme_watch)
    common_parts = {"query": reference_query(), "languages": ["en"]}
    search_payload, search_raw, search_receipt = post_func(
        ft.SEARCH_ENDPOINT, text=reference, page_size=10, page_number=1, parts=common_parts
    )
    facet_payload, facet_raw, facet_receipt = post_func(
        ft.FACET_ENDPOINT, text=reference, page_size=10, page_number=1, parts=common_parts
    )
    matching = [
        row for row in ft.flatten_search_payload(search_payload)
        if str(ft._record_identifier(row) or "").upper() == reference
    ]
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
        if not programme_label or not _is_cerv_label(programme_label):
            raise ValueError(f"exact record is not proven to belong to CERV: {programme_ref!r} {programme_label!r}")
        status_code = ft._record_status_code(row)
        status_label = ft.resolve_reference_label([facet_payload], status_code or "") if status_code else None
        if not status_label:
            raise ValueError(f"official Facet did not resolve current status for {reference}")
        snapshot = _material_snapshot(row, programme_label=programme_label, status_label=status_label)
        material_rows.append((sha256_json(snapshot), row, snapshot))
    signatures = sorted({signature for signature, _, _ in material_rows})
    if len(signatures) != 1:
        raise ExactCERVConflict(f"conflicting exact CERV records for {reference}: {len(signatures)} material variants")
    chosen, snapshot = material_rows[0][1], material_rows[0][2]

    authority_url = ft.topic_url(reference)
    readback = topic_func(authority_url)
    if readback.get("verified") is not True:
        raise ValueError(f"exact CERV topic authority readback failed for {reference}: {readback.get('error')}")
    enriched = dict(chosen)
    enriched["statusLabel"] = snapshot["status_label"]
    enriched["authorityUrl"] = authority_url
    batch = normalize_payload(
        [enriched], fetched_at=fetched_at, run_id=run_id, verified_authority_urls=[authority_url]
    )
    records = [row for row in batch.get("records") or [] if str(row.get("identifier") or "").upper() == reference]
    if len(records) != 1:
        raise ValueError(f"exact CERV normalizer returned {len(records)} records for {reference}")
    normalized = records[0]
    if normalized.get("authority_url_verified") is not True:
        raise ValueError("exact CERV authority verification was lost during normalization")

    exact_semantics = {
        "identifier": reference,
        "call_identifier": normalized.get("call_identifier"),
        "title": normalized.get("title"),
        "programme_reference": snapshot.get("programme_reference"),
        "programme_label": snapshot.get("programme_label"),
        "status_label": normalized.get("status_label"),
        "observation_state": normalized.get("observation_state"),
        "authority_url": authority_url,
        "deadline_candidate": normalized.get("deadline_candidate"),
        "budget_candidate": normalized.get("budget_candidate"),
    }
    evidence: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_LAYER,
        "reference": reference,
        "fetched_at": fetched_at,
        "run_id": run_id,
        "search_receipt": dict(search_receipt),
        "facet_receipt": dict(facet_receipt),
        "search_raw_sha256": sha256_bytes(search_raw),
        "facet_raw_sha256": sha256_bytes(facet_raw),
        "authority_url": authority_url,
        "authority_readback": dict(readback),
        "authority_url_verified": True,
        "candidate_state": normalized.get("observation_state"),
        "status_label": normalized.get("status_label"),
        "call_identifier": normalized.get("call_identifier"),
        "title": normalized.get("title"),
        "programme_reference": snapshot.get("programme_reference"),
        "programme_label_official": snapshot.get("programme_label"),
        "deadline_candidate": normalized.get("deadline_candidate"),
        "budget_candidate": normalized.get("budget_candidate"),
        "exact_semantics": exact_semantics,
        "exact_semantic_fingerprint": sha256_json(exact_semantics),
        "primary_exact_record_count": len(primary),
        "linked_type8_record_count": len(linked_type8),
        "linked_type8_record_hashes": sorted(sha256_json(row) for row in linked_type8),
        "source_candidate": dict(source_candidate or {}),
        "source_candidate_fingerprint": sha256_json(source_candidate) if source_candidate else None,
        "programme_watch_semantic_fingerprint": programme_watch.get("semantic_fingerprint") if programme_watch else None,
        "programme_watch_sha256": sha256_json(programme_watch) if programme_watch else None,
        "semantic_reconciliation_required": True,
        "field_scoped_material_admission_required": True,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        evidence[key] = False
    validate_evidence(evidence)
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "ft-cerv-search-response.json").write_bytes(search_raw)
        (output_dir / "ft-cerv-facet-response.json").write_bytes(facet_raw)
        (output_dir / "ft-cerv-exact-evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
    return evidence


def validate_evidence(evidence: Mapping[str, Any]) -> None:
    if evidence.get("schema") != SCHEMA or evidence.get("parser_version") != PARSER_VERSION:
        raise ValueError("CERV exact evidence schema/parser drift")
    reference = validate_reference(str(evidence.get("reference") or ""))
    if evidence.get("source_family") != SOURCE_FAMILY or evidence.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("CERV exact evidence family drift")
    if evidence.get("authority_class") != AUTHORITY_CLASS:
        raise ValueError("CERV exact evidence authority class drift")
    if evidence.get("authority_url") != ft.topic_url(reference) or evidence.get("authority_url_verified") is not True:
        raise ValueError("CERV exact evidence lacks verified exact topic authority")
    readback = evidence.get("authority_readback") or {}
    if readback.get("verified") is not True or readback.get("url") != evidence.get("authority_url"):
        raise ValueError("CERV exact readback binding invalid")
    if not _is_cerv_label(str(evidence.get("programme_label_official") or "")):
        raise ValueError("CERV exact evidence lost official programme proof")
    if evidence.get("candidate_state") not in {"OPEN_CALL", "FORTHCOMING_CALL", "CLOSED_CALL", "UNKNOWN"}:
        raise ValueError("CERV exact candidate state unsupported")
    semantics = evidence.get("exact_semantics")
    if not isinstance(semantics, dict) or sha256_json(semantics) != evidence.get("exact_semantic_fingerprint"):
        raise ValueError("CERV exact semantic fingerprint mismatch")
    if evidence.get("source_candidate"):
        if evidence.get("source_candidate_fingerprint") != sha256_json(evidence.get("source_candidate")):
            raise ValueError("CERV exact source-candidate fingerprint mismatch")
        if evidence.get("source_candidate", {}).get("identifier") != reference:
            raise ValueError("CERV exact source-candidate identity mismatch")
    watch_fp = evidence.get("programme_watch_semantic_fingerprint")
    watch_sha = evidence.get("programme_watch_sha256")
    if (watch_fp is None) != (watch_sha is None):
        raise ValueError("CERV exact programme-watch binding incomplete")
    if watch_fp is not None:
        if not re.fullmatch(r"[0-9a-f]{64}", str(watch_fp)) or not re.fullmatch(r"[0-9a-f]{64}", str(watch_sha)):
            raise ValueError("CERV exact programme-watch binding malformed")
    for key in MATERIAL_FLAGS:
        if evidence.get(key) is not False:
            raise ValueError(f"CERV exact evidence attempted authorization: {key}")
    if evidence.get("publication_effect") != "NONE" or evidence.get("canonical_corpus_mutation") is not False:
        raise ValueError("CERV exact evidence crossed publication boundary")
    if evidence.get("semantic_reconciliation_required") is not True or evidence.get("field_scoped_material_admission_required") is not True:
        raise ValueError("CERV exact evidence skipped downstream gates")
    for receipt_key in ("search_receipt", "facet_receipt"):
        receipt = evidence.get(receipt_key) or {}
        if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("sha256") or "")):
            raise ValueError(f"CERV exact evidence missing immutable {receipt_key}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discovery", type=pathlib.Path)
    parser.add_argument("--reference")
    parser.add_argument("--programme-watch", type=pathlib.Path)
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    parser.add_argument("--run-id", default="cerv-ft-exact-live")
    args = parser.parse_args()
    source_candidate = None
    reference = args.reference
    if args.discovery:
        discovery = json.loads(args.discovery.read_text(encoding="utf-8"))
        source_candidate = select_cerv_candidate(discovery)
        if reference and validate_reference(reference) != source_candidate["identifier"]:
            raise ValueError("explicit CERV reference does not match structured discovery handoff")
        reference = source_candidate["identifier"]
    if not reference:
        raise ValueError("--discovery or --reference is required")
    programme_watch = None
    if args.programme_watch:
        programme_watch = json.loads(args.programme_watch.read_text(encoding="utf-8"))
        validate_programme_watch(programme_watch)
    evidence = collect_exact(
        reference,
        run_id=args.run_id,
        source_candidate=source_candidate,
        programme_watch=programme_watch,
        output_dir=args.output_dir,
    )
    print(json.dumps({
        "reference": evidence["reference"],
        "candidate_state": evidence["candidate_state"],
        "status_label": evidence["status_label"],
        "authority_url_verified": evidence["authority_url_verified"],
        "open_call_authorized": evidence["open_call_authorized"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
