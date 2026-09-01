#!/usr/bin/env python3
"""Bind explicit completeness semantics to an EU_DIRECT F&T programme-watch snapshot.

The upstream watch is intentionally bounded. This receipt prevents a bounded
sample from being mistaken for a complete programme inventory. It is derived
only from the immutable watch envelope and does not perform network acquisition
or authorize any material/public fact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from typing import Any, Mapping

WATCH_SCHEMA = "PARTENER_EU_FT_PROGRAMME_COVERAGE_WATCH_V1"
SCHEMA = "PARTENER_EU_FT_PROGRAMME_COVERAGE_RECEIPT_V1"
PARSER_VERSION = "EU_DIRECT_FT_COVERAGE_RECEIPT_V1"
COMPLETE_STOP_REASONS = {"EMPTY_PAGE", "PARTIAL_LAST_PAGE"}
TRUNCATED_STOP_REASONS = {"MAX_PAGES_REACHED", "REPEATED_PAGE_SHA_FAIL_SAFE_STOP"}


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def build_coverage_receipt(watch: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(watch, Mapping) or watch.get("schema") != WATCH_SCHEMA:
        raise ValueError(f"watch schema must be {WATCH_SCHEMA}")
    for key in (
        "material_fact_use", "open_call_authorized", "deadline_authorized", "budget_authorized",
        "eligibility_authorized", "publish_authorized", "distribution_authorized", "call_alert_authorized",
        "canonical_corpus_mutation",
    ):
        if watch.get(key) is not False:
            raise ValueError(f"unsafe upstream watch authorization: {key}")
    if watch.get("publication_effect") != "NONE" or watch.get("market_intelligence_only") is not True:
        raise ValueError("upstream watch is not non-authorizing market intelligence")

    pagination = watch.get("pagination")
    if not isinstance(pagination, Mapping):
        raise ValueError("watch pagination metadata is missing")
    stop_reason = pagination.get("stop_reason")
    if stop_reason not in COMPLETE_STOP_REASONS | TRUNCATED_STOP_REASONS:
        raise ValueError(f"unknown pagination stop reason: {stop_reason!r}")
    pages_captured = pagination.get("pages_captured")
    page_size = pagination.get("page_size")
    max_pages = pagination.get("max_pages")
    if not all(isinstance(value, int) and value > 0 for value in (pages_captured, page_size, max_pages)):
        raise ValueError("invalid pagination counters")
    if pages_captured > max_pages:
        raise ValueError("pages_captured exceeds max_pages")

    coverage_complete = stop_reason in COMPLETE_STOP_REASONS
    pagination_truncated = not coverage_complete
    if stop_reason == "MAX_PAGES_REACHED" and pages_captured != max_pages:
        raise ValueError("MAX_PAGES_REACHED requires pages_captured == max_pages")
    if stop_reason == "REPEATED_PAGE_SHA_FAIL_SAFE_STOP" and pages_captured >= max_pages:
        # Repeated page may happen earlier; at max pages the bounded cap is enough to
        # state truncation, but this branch protects contradictory metadata.
        pass

    return {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_watch_schema": WATCH_SCHEMA,
        "source_watch_sha256": sha256_json(watch),
        "source_family": watch.get("source_family"),
        "programme_family": watch.get("programme_family"),
        "authority_class": watch.get("authority_class"),
        "fetched_at": watch.get("fetched_at"),
        "run_id": watch.get("run_id"),
        "coverage_complete": coverage_complete,
        "pagination_truncated": pagination_truncated,
        "more_results_possible": pagination_truncated,
        "coverage_scope": (
            "COMPLETE_QUERY_RESULT_NON_AUTHORIZING"
            if coverage_complete
            else "BOUNDED_QUERY_SAMPLE_NON_AUTHORIZING"
        ),
        "stop_reason": stop_reason,
        "pages_captured": pages_captured,
        "page_size": page_size,
        "max_pages": max_pages,
        "raw_search_records_observed": (watch.get("stats") or {}).get("raw_search_records"),
        "accepted_candidates_observed": (watch.get("stats") or {}).get("accepted_candidates"),
        "programme_family_counts_observed": watch.get("programme_family_counts") or {},
        "status_candidate_counts_observed": watch.get("status_candidate_counts") or {},
        "interpretation": (
            "The watch reached an observed query terminator; counts describe the complete bounded query result at observation time."
            if coverage_complete
            else "The watch hit a safety/cost bound before an observed query terminator; counts are a lower-bound sample and MUST NOT be represented as exhaustive programme inventory."
        ),
        "market_intelligence_only": True,
        "material_fact_use": False,
        "open_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "call_alert_authorized": False,
        "canonical_corpus_mutation": False,
        "publication_effect": "NONE",
        "rollback": "Discard this coverage receipt; the source watch and all canonical/public state remain unchanged.",
    }


def validate_coverage_receipt(receipt: Mapping[str, Any], watch: Mapping[str, Any]) -> None:
    if receipt.get("schema") != SCHEMA:
        raise ValueError("coverage receipt schema mismatch")
    if receipt.get("source_watch_sha256") != sha256_json(watch):
        raise ValueError("coverage receipt is not bound to supplied watch")
    if receipt.get("coverage_complete") is receipt.get("pagination_truncated"):
        raise ValueError("coverage completeness/truncation flags are contradictory")
    if receipt.get("coverage_complete"):
        if receipt.get("stop_reason") not in COMPLETE_STOP_REASONS:
            raise ValueError("complete coverage has invalid stop reason")
        if receipt.get("coverage_scope") != "COMPLETE_QUERY_RESULT_NON_AUTHORIZING":
            raise ValueError("complete coverage scope mismatch")
        if receipt.get("more_results_possible") is not False:
            raise ValueError("complete coverage cannot claim more results possible")
    else:
        if receipt.get("stop_reason") not in TRUNCATED_STOP_REASONS:
            raise ValueError("truncated coverage has invalid stop reason")
        if receipt.get("coverage_scope") != "BOUNDED_QUERY_SAMPLE_NON_AUTHORIZING":
            raise ValueError("truncated coverage scope mismatch")
        if receipt.get("more_results_possible") is not True:
            raise ValueError("truncated coverage must preserve more-results-possible")
    for key in (
        "material_fact_use", "open_call_authorized", "deadline_authorized", "budget_authorized",
        "eligibility_authorized", "publish_authorized", "distribution_authorized", "call_alert_authorized",
        "canonical_corpus_mutation",
    ):
        if receipt.get(key) is not False:
            raise ValueError(f"coverage receipt attempted authorization: {key}")
    if receipt.get("publication_effect") != "NONE" or receipt.get("market_intelligence_only") is not True:
        raise ValueError("coverage receipt crossed non-authorizing boundary")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("watch", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    watch = json.loads(args.watch.read_text(encoding="utf-8"))
    receipt = build_coverage_receipt(watch)
    validate_coverage_receipt(receipt, watch)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "coverage_complete": receipt["coverage_complete"],
        "pagination_truncated": receipt["pagination_truncated"],
        "coverage_scope": receipt["coverage_scope"],
        "stop_reason": receipt["stop_reason"],
        "raw_search_records_observed": receipt["raw_search_records_observed"],
        "accepted_candidates_observed": receipt["accepted_candidates_observed"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
