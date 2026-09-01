#!/usr/bin/env python3
"""Read-only calibration of VÂLCEA CLAR editorial quality on the public corpus.

This audit deliberately separates two evidence classes:

* claim-bound Editorial Writer products may use the canonical writer -> quality
  adapter and receive its real quality receipt;
* legacy/public copy without a claim-level Fact Kernel receives STYLE SIGNALS
  ONLY. The audit never treats article prose as proof of its own facts and never
  upgrades legacy copy to PASS/FAIL publication authority.

The command is diagnostic. It does not rewrite copy, persist runtime state,
mutate provenance/Fact Kernels, promote breaking news or authorize publication.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import editorial_writer_quality_gate as writer_quality

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FEED = ROOT / "site" / "runtime" / "live-feed.json"
CONTRACT = "VALCEA_CLAR_EDITORIAL_CORPUS_AUDIT_V1"

# These diagnostics are independent of an asserted story type or factual basis.
# Evidence-dependent checks such as headline-number support are intentionally
# excluded for legacy copy because copy is never allowed to prove itself.
LEGACY_STYLE_CODES = {
    "BUREAUCRATIC_LEAD",
    "MECHANICAL_OR_BUREAUCRATIC_LANGUAGE",
    "CLICHE_LANGUAGE",
    "REPEATED_SENTENCE_STARTS",
    "DUPLICATE_PHRASING",
    "OVERLONG_SENTENCES",
    "OVERLONG_PARAGRAPHS",
    "LOCAL_RELEVANCE_NOT_EXPLICIT",
}


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _paragraphs(story: dict[str, Any]) -> list[str]:
    return [_text(value) for value in story.get("paragraphs") or [] if _text(value)]


def _legacy_style_receipt(story: dict[str, Any]) -> dict[str, Any]:
    paragraphs = _paragraphs(story)
    input_item = {
        # REPORT is used only to satisfy the validator contract. All checks whose
        # threshold/semantics depend on story type are excluded below.
        "story_type": "REPORT",
        "headline": _text(story.get("headline")),
        "lead": paragraphs[0] if paragraphs else "",
        "body": "\n\n".join(paragraphs[1:]),
        "provenance": story.get("sources") or [],
        # Critical boundary: never seed confirmed_facts from reader copy.
        "confirmed_facts": [],
        "locality_context": story.get("locality_context"),
        "why_it_matters": "",
    }
    result = writer_quality.quality.evaluate(input_item)
    diagnostics = [
        row
        for row in result.get("diagnostics") or []
        if isinstance(row, dict) and row.get("code") in LEGACY_STYLE_CODES
    ]
    missing_fields = []
    if not input_item["headline"]:
        missing_fields.append("headline")
    if not input_item["lead"]:
        missing_fields.append("lead")
    if not input_item["body"]:
        missing_fields.append("body")
    if not input_item["provenance"]:
        missing_fields.append("provenance")
    return {
        "mode": "LEGACY_PUBLIC_COPY_DIAGNOSTIC_ONLY",
        "story_id": _text(story.get("id")),
        "diagnostic_status": "STYLE_FLAGS" if diagnostics or missing_fields else "NO_STYLE_FLAGS_IN_BOUNDED_RULESET",
        "style_diagnostics": diagnostics,
        "missing_public_fields": missing_fields,
        "quality_pass_asserted": False,
        "quality_fail_asserted": False,
        "fact_basis_asserted": False,
        "limitations": {
            "story_type_not_inferred": True,
            "confirmed_facts_not_inferred_from_copy": True,
            "headline_fact_support_not_scored": True,
            "lead_length_story_type_threshold_not_scored": True,
            "why_it_matters_not_scored_without_claim_roles": True,
        },
    }


def audit_story(story: dict[str, Any]) -> dict[str, Any]:
    editorial = story.get("editorial_product")
    if isinstance(editorial, dict):
        mode = _text(editorial.get("writer_mode"))
        if mode == "FACT_KERNEL_COMPOSED":
            receipt = writer_quality.evaluate_writer_product(story)
            return {
                "mode": "CANONICAL_WRITER_CLAIM_BOUND",
                "story_id": _text(story.get("id")),
                "status": receipt.get("status"),
                "quality_gate_passed": receipt.get("quality_gate_passed") is True,
                "hold_reason": receipt.get("hold_reason"),
                "diagnostics": (receipt.get("quality_result") or {}).get("diagnostics") or [],
            }
        if mode and mode != "LEGACY_VERIFIED_PASSTHROUGH":
            receipt = writer_quality.evaluate_writer_product(story)
            return {
                "mode": "WRITER_CONTRACT_ANOMALY",
                "story_id": _text(story.get("id")),
                "status": receipt.get("status"),
                "quality_gate_passed": False,
                "hold_reason": receipt.get("hold_reason"),
                "diagnostics": (receipt.get("quality_result") or {}).get("diagnostics") or [],
            }
    return _legacy_style_receipt(story)


def audit_feed(payload: dict[str, Any], *, max_stories: int) -> dict[str, Any]:
    stories = payload.get("stories")
    if not isinstance(stories, list):
        raise ValueError("live_feed_stories_missing")
    selected = [story for story in stories[:max_stories] if isinstance(story, dict)]

    mode_counts: Counter[str] = Counter()
    canonical_status_counts: Counter[str] = Counter()
    style_code_counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    legacy_flagged = 0
    legacy_missing_fields = 0
    canonical_not_pass = 0

    for story in selected:
        result = audit_story(story)
        mode = str(result.get("mode") or "UNKNOWN")
        mode_counts[mode] += 1
        story_id = _text(result.get("story_id")) or "<missing-id>"

        if mode == "LEGACY_PUBLIC_COPY_DIAGNOSTIC_ONLY":
            diagnostics = result.get("style_diagnostics") or []
            missing_fields = result.get("missing_public_fields") or []
            if diagnostics or missing_fields:
                legacy_flagged += 1
            if missing_fields:
                legacy_missing_fields += 1
            for row in diagnostics:
                code = _text(row.get("code"))
                if not code:
                    continue
                style_code_counts[code] += 1
                if len(examples[code]) < 5:
                    examples[code].append(story_id)
            for field in missing_fields:
                code = f"MISSING_PUBLIC_{field.upper()}"
                style_code_counts[code] += 1
                if len(examples[code]) < 5:
                    examples[code].append(story_id)
        else:
            status = _text(result.get("status")) or "UNKNOWN"
            canonical_status_counts[status] += 1
            if result.get("quality_gate_passed") is not True:
                canonical_not_pass += 1
            for row in result.get("diagnostics") or []:
                if not isinstance(row, dict):
                    continue
                code = _text(row.get("code"))
                if code:
                    style_code_counts[code] += 1
                    if len(examples[code]) < 5:
                        examples[code].append(story_id)

    return {
        "contract": CONTRACT,
        "input": {
            "schema_version": payload.get("schema_version"),
            "generated_at": payload.get("generated_at"),
            "publication_model": payload.get("publication_model"),
            "stories_available": len(stories),
            "stories_sampled": len(selected),
            "max_stories": max_stories,
        },
        "coverage": {
            "mode_counts": dict(sorted(mode_counts.items())),
            "canonical_claim_bound_count": mode_counts.get("CANONICAL_WRITER_CLAIM_BOUND", 0),
            "legacy_diagnostic_only_count": mode_counts.get("LEGACY_PUBLIC_COPY_DIAGNOSTIC_ONLY", 0),
            "writer_contract_anomaly_count": mode_counts.get("WRITER_CONTRACT_ANOMALY", 0),
        },
        "canonical_quality": {
            "status_counts": dict(sorted(canonical_status_counts.items())),
            "not_pass_count": canonical_not_pass,
        },
        "legacy_calibration": {
            "style_flagged_story_count": legacy_flagged,
            "missing_public_fields_story_count": legacy_missing_fields,
            "style_code_counts": dict(sorted(style_code_counts.items())),
            "bounded_examples_by_code": {key: value for key, value in sorted(examples.items())},
            "pass_rate_not_computed": True,
            "reason": "legacy public copy has no claim-level fact basis; diagnostic style signals are non-authorizing",
        },
        "semantics": {
            "copy_is_not_evidence": True,
            "legacy_copy_can_never_receive_pass_from_this_audit": True,
            "legacy_copy_can_never_receive_fail_publication_authority_from_this_audit": True,
            "canonical_writer_receipts_remain_claim_bound": True,
            "calibration_only": True,
        },
        "capabilities": {
            "publication_authorized": False,
            "automatic_rewrite_authorized": False,
            "fact_inference_authorized": False,
            "fact_kernel_mutation_authorized": False,
            "source_provenance_mutation_authorized": False,
            "breaking_promotion_authorized": False,
            "runtime_persistence_authorized": False,
        },
    }


def self_test() -> int:
    legacy_mechanical = {
        "id": "legacy-mechanical",
        "headline": "Râmnicu Vâlcea: lucrări pe strada Test",
        "paragraphs": [
            "În cadrul unei acțiuni desfășurate în Râmnicu Vâlcea, instituția a informat despre lucrări.",
            "În vederea executării lucrărilor, circulația va fi modificată temporar.",
        ],
        "sources": [{"name": "Sursă oficială", "url": "https://example.test/official", "tier": "T1"}],
    }
    legacy_clean = {
        "id": "legacy-clean",
        "headline": "Râmnicu Vâlcea: strada Test se închide temporar pentru lucrări",
        "paragraphs": [
            "Strada Test din Râmnicu Vâlcea se închide temporar pentru lucrări, potrivit administrației locale.",
            "Restricția privește tronsonul central și este anunțată pe pagina oficială a instituției.",
        ],
        "sources": [{"name": "Sursă oficială", "url": "https://example.test/official", "tier": "T1"}],
    }
    malformed_writer = {
        "id": "writer-anomaly",
        "headline": "Râmnicu Vâlcea: test",
        "paragraphs": ["Un text suficient de lung pentru a intra în verificarea contractului editorial."],
        "editorial_product": {"writer_id": "manual_journalism_v1", "writer_mode": "UNKNOWN_MODE"},
    }
    payload = {"schema_version": "2.3", "generated_at": "2026-09-01T00:00:00Z", "stories": [legacy_mechanical, legacy_clean, malformed_writer]}
    result = audit_feed(payload, max_stories=10)
    assert result["coverage"]["legacy_diagnostic_only_count"] == 2, result
    assert result["coverage"]["writer_contract_anomaly_count"] == 1, result
    assert result["legacy_calibration"]["style_flagged_story_count"] == 1, result
    assert result["legacy_calibration"]["style_code_counts"]["BUREAUCRATIC_LEAD"] == 1, result
    assert result["legacy_calibration"]["pass_rate_not_computed"] is True
    assert result["semantics"]["copy_is_not_evidence"] is True
    assert result["semantics"]["legacy_copy_can_never_receive_pass_from_this_audit"] is True
    assert not any(result["capabilities"].values()), result
    print(json.dumps({"contract": CONTRACT, "self_test": "PASS", "cases": 3}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only VÂLCEA CLAR editorial corpus calibration")
    parser.add_argument("--feed", type=Path, default=DEFAULT_FEED, help="live-feed JSON to inspect")
    parser.add_argument("--max-stories", type=int, default=60, help="bounded number of leading stories to inspect (1..200)")
    parser.add_argument("--self-test", action="store_true", help="run deterministic calibration regressions")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if not 1 <= args.max_stories <= 200:
        raise SystemExit("--max-stories must be between 1 and 200")
    payload = json.loads(args.feed.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("feed must be a JSON object")
    result = audit_feed(payload, max_stories=args.max_stories)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
