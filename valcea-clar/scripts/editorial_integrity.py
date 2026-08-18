#!/usr/bin/env python3
"""Fail-closed post-writer integrity gate for VÂLCEA CLAR.

Editorial Writer v1 turns verified fact kernels into reader-facing copy. This
module is the independent editor/checker immediately after that writer: it
proves that the material which is about to enter the newsroom gate is still the
same evidence-bound product the writer emitted.

It does not rewrite copy. It validates identity, claim hashes, source lineage,
headline/dek provenance and the writer product fingerprint. Reputational
formats remain review-only unless an explicit human approval flag is present.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PRODUCTS = ROOT / "editorial" / "editorial_products.json"
WRITER_ID = "manual_journalism_v1"
REVIEW_ONLY_FORMATS = {"investigation", "analysis"}


def canonical_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def story_source_urls(item: dict[str, Any]) -> set[str]:
    return {
        str(row.get("url") or "").strip()
        for row in item.get("sources") or []
        if isinstance(row, dict) and str(row.get("url") or "").strip()
    }


def expected_product_fingerprint(item: dict[str, Any]) -> str | None:
    editorial = item.get("editorial_product") if isinstance(item.get("editorial_product"), dict) else {}
    mode = str(editorial.get("writer_mode") or "")
    headline = str(item.get("headline") or "").strip()
    dek = str(item.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in item.get("paragraphs") or [] if str(p).strip()]
    if mode == "FACT_KERNEL_COMPOSED":
        return canonical_digest({
            "id": item.get("id"),
            "headline": headline,
            "dek": dek,
            "paragraphs": paragraphs,
            "format": editorial.get("format"),
            "claim_trace": editorial.get("claim_trace") or [],
        })
    if mode == "LEGACY_VERIFIED_PASSTHROUGH":
        return canonical_digest({
            "id": item.get("id"),
            "headline": headline,
            "dek": dek,
            "paragraphs": paragraphs,
            "source_urls": sorted(story_source_urls(item)),
        })
    return None


def _refs_valid(refs: Any, valid_urls: set[str]) -> bool:
    if not isinstance(refs, list) or not refs:
        return False
    values = {str(url).strip() for url in refs if str(url).strip()}
    return bool(values) and values.issubset(valid_urls)


def validate_story(item: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    editorial = item.get("editorial_product") if isinstance(item.get("editorial_product"), dict) else {}
    if not editorial:
        return False, "editorial_product_missing", {}
    if editorial.get("writer_id") != WRITER_ID:
        return False, "writer_identity_mismatch", {}

    mode = str(editorial.get("writer_mode") or "")
    fmt = str(editorial.get("format") or "")
    valid_urls = story_source_urls(item)
    if not valid_urls:
        return False, "story_sources_missing", {}

    if mode == "FACT_KERNEL_REJECTED_FAIL_CLOSED":
        return False, "writer_rejected_fact_kernel", {}

    if fmt in REVIEW_ONLY_FORMATS and editorial.get("human_editor_approved") is not True:
        return False, "reputational_format_requires_human_editor", {"format": fmt}

    supplied_fp = str(editorial.get("product_fingerprint_sha256") or "")
    expected_fp = expected_product_fingerprint(item)
    if not supplied_fp or not expected_fp or supplied_fp != expected_fp:
        return False, "writer_product_fingerprint_mismatch", {}

    if mode == "LEGACY_VERIFIED_PASSTHROUGH":
        if editorial.get("legacy_copy_rewritten") is not False:
            return False, "legacy_copy_rewrite_detected", {}
        if editorial.get("source_level_trace") is not True:
            return False, "legacy_source_trace_missing", {}
        return True, "PASS_LEGACY_VERIFIED_PASSTHROUGH", {
            "writer_id": WRITER_ID,
            "writer_mode": mode,
            "format": fmt,
            "source_count": len(valid_urls),
            "product_fingerprint_sha256": expected_fp,
        }

    if mode != "FACT_KERNEL_COMPOSED":
        return False, "unknown_writer_mode", {"writer_mode": mode}

    if editorial.get("claim_trace_complete") is not True or editorial.get("source_level_trace") is not True:
        return False, "claim_or_source_trace_incomplete", {}
    if editorial.get("auto_publish_eligible_by_format") is not True:
        return False, "editorial_format_requires_review", {"format": fmt}

    kernel = item.get("fact_kernel") if isinstance(item.get("fact_kernel"), dict) else {}
    if not kernel:
        return False, "fact_kernel_missing_after_composition", {}

    headline = str(item.get("headline") or "").strip()
    dek = str(item.get("dek") or "").strip()
    kernel_headline = kernel.get("headline") if isinstance(kernel.get("headline"), dict) else {}
    kernel_dek = kernel.get("dek") if isinstance(kernel.get("dek"), dict) else {}
    if headline != str(kernel_headline.get("text") or "").strip():
        return False, "headline_exceeds_or_differs_from_kernel", {}
    if dek != str(kernel_dek.get("text") or "").strip():
        return False, "dek_exceeds_or_differs_from_kernel", {}
    if not _refs_valid(editorial.get("headline_source_urls"), valid_urls):
        return False, "headline_source_trace_invalid", {}
    if not _refs_valid(editorial.get("dek_source_urls"), valid_urls):
        return False, "dek_source_trace_invalid", {}

    paragraphs = [str(p).strip() for p in item.get("paragraphs") or [] if str(p).strip()]
    trace = editorial.get("claim_trace") or []
    if not paragraphs or not isinstance(trace, list) or len(trace) != len(paragraphs):
        return False, "paragraph_claim_trace_cardinality_mismatch", {}

    kernel_claims = {
        str(row.get("id") or ""): row
        for row in kernel.get("claims") or []
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    if len(kernel_claims) != len(kernel.get("claims") or []):
        return False, "fact_kernel_claim_identity_invalid", {}

    for index, (paragraph, row) in enumerate(zip(paragraphs, trace)):
        if not isinstance(row, dict):
            return False, f"claim_trace_not_object:{index}", {}
        claim_id = str(row.get("claim_id") or "").strip()
        claim = kernel_claims.get(claim_id)
        if not claim:
            return False, f"claim_trace_unknown_claim:{claim_id or index}", {}
        if paragraph != str(claim.get("text") or "").strip():
            return False, f"paragraph_differs_from_kernel_claim:{claim_id}", {}
        if str(row.get("text_sha256") or "") != text_sha256(paragraph):
            return False, f"claim_text_hash_mismatch:{claim_id}", {}
        trace_refs = row.get("source_urls")
        claim_refs = [str(url).strip() for url in claim.get("source_urls") or [] if str(url).strip()]
        if not _refs_valid(trace_refs, valid_urls):
            return False, f"claim_source_trace_invalid:{claim_id}", {}
        if [str(url).strip() for url in trace_refs if str(url).strip()] != claim_refs:
            return False, f"claim_source_trace_differs_from_kernel:{claim_id}", {}

    return True, "PASS_FACT_KERNEL_INTEGRITY", {
        "writer_id": WRITER_ID,
        "writer_mode": mode,
        "format": fmt,
        "claim_count": len(trace),
        "source_count": len(valid_urls),
        "product_fingerprint_sha256": expected_fp,
    }


def validate_registry(document: dict[str, Any]) -> dict[str, Any]:
    rows = document.get("facts") or []
    reports = []
    failed = 0
    for item in rows:
        if not isinstance(item, dict):
            failed += 1
            reports.append({"id": None, "status": "FAIL", "reason": "story_not_object"})
            continue
        ok, reason, detail = validate_story(item)
        failed += 0 if ok else 1
        reports.append({"id": item.get("id"), "status": "PASS" if ok else "FAIL", "reason": reason, **detail})
    return {
        "schema_version": "1.0",
        "gate_id": "editorial_integrity_v1",
        "story_count": len(rows),
        "passed": len(rows) - failed,
        "failed": failed,
        "reports": reports,
    }


def self_test() -> int:
    url = "https://example.test/h1"
    claim_text = "Documentul oficial confirmă măsura și termenul absolut folosit în materialul editorial verificat."
    item = {
        "id": "integrity-test",
        "headline": "Primăria confirmă măsura documentată pentru proiect",
        "dek": "Documentul oficial confirmă măsura și permite publicarea unei explicații strict trasabile la sursă.",
        "paragraphs": [claim_text],
        "sources": [{"name": "Sursă", "url": url, "tier": "T1"}],
        "fact_kernel": {
            "format_hint": "straight_news",
            "headline": {"text": "Primăria confirmă măsura documentată pentru proiect", "source_urls": [url]},
            "dek": {"text": "Documentul oficial confirmă măsura și permite publicarea unei explicații strict trasabile la sursă.", "source_urls": [url]},
            "claims": [{"id": "c1", "role": "who_what_when_where", "kind": "fact", "text": claim_text, "source_urls": [url]}],
        },
        "editorial_product": {
            "writer_id": WRITER_ID,
            "writer_mode": "FACT_KERNEL_COMPOSED",
            "format": "straight_news",
            "claim_trace_complete": True,
            "source_level_trace": True,
            "headline_source_urls": [url],
            "dek_source_urls": [url],
            "claim_trace": [{"claim_id": "c1", "role": "who_what_when_where", "kind": "fact", "text_sha256": text_sha256(claim_text), "source_urls": [url]}],
            "auto_publish_eligible_by_format": True,
        },
    }
    item["editorial_product"]["product_fingerprint_sha256"] = expected_product_fingerprint(item)
    assert validate_story(item)[0] is True

    tampered = json.loads(json.dumps(item))
    tampered["paragraphs"][0] += " Fapt nesusținut."
    assert validate_story(tampered)[0] is False

    bad_source = json.loads(json.dumps(item))
    bad_source["editorial_product"]["claim_trace"][0]["source_urls"] = ["https://example.test/other"]
    bad_source["editorial_product"]["product_fingerprint_sha256"] = expected_product_fingerprint(bad_source)
    assert validate_story(bad_source)[0] is False

    investigation = json.loads(json.dumps(item))
    investigation["editorial_product"]["format"] = "investigation"
    investigation["editorial_product"]["product_fingerprint_sha256"] = expected_product_fingerprint(investigation)
    assert validate_story(investigation)[1] == "reputational_format_requires_human_editor"
    investigation["editorial_product"]["human_editor_approved"] = True
    investigation["editorial_product"]["product_fingerprint_sha256"] = expected_product_fingerprint(investigation)
    assert validate_story(investigation)[0] is True

    print("VÂLCEA CLAR editorial integrity self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not PRODUCTS.is_file():
        raise SystemExit("Editorial integrity FAIL: editorial_products.json is not materialized")
    document = json.loads(PRODUCTS.read_text(encoding="utf-8"))
    report = validate_registry(document)
    print(json.dumps(report, ensure_ascii=False))
    if report["failed"]:
        raise SystemExit("Editorial integrity FAIL: one or more editorial products failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
