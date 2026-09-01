#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "partener-eu" / "web"))

from programming_pipeline_preview import build_manifest, render


def fixture() -> dict:
    base_false = {
        "market_intelligence_only": True,
        "material_fact_use": False,
        "open_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "publication_effect": "NONE",
    }
    return {
        "schema_version": "1.0",
        "projection_id": "PROGRAMMING_PIPELINE_PUBLIC_PROJECTION_V1",
        "surface": "PROGRAMARE_VIITOARE_PIPELINE",
        "surface_state": "PREVIEW_READ_ONLY_NOT_PUBLISHED",
        "generated_from_run_id": "test-run",
        "observed_at": "2026-09-01T00:45:00Z",
        "source_family": "INTERREG",
        "programme_period": "2028-2034",
        "card_count": 2,
        "healthy_source_count": 1,
        "degraded_source_count": 1,
        "reconciliation_state": "NO_CHANGE",
        "semantic_change_count": 0,
        "transport_or_content_change_count": 1,
        "pipeline_watch_candidate": False,
        "pipeline_watch_label": None,
        "source_health_watch_candidate": True,
        "framework_mapped_programme_ids": ["ROUA"],
        "programme_specific_covered_programme_ids": [],
        "programme_specific_coverage_state": "PARTIAL_FRAMEWORK_ONLY_GAPS_PRESENT",
        "coverage_gap_count": 1,
        "coverage_gaps": [{
            "programme_id": "ROUA",
            "programme_period": "2028-2034",
            "coverage_state": "FRAMEWORK_ONLY_RESEARCH_WATCH_NOT_ADMITTED",
            "observation_label_ro": "Monitorizare cercetare",
            "framework_evidence": [{
                "source_id": "SRC-FRAMEWORK",
                "authority_url": "https://official.example/framework",
                "observation_state": "PROPOSAL",
            }],
            "confidence": "LOW",
            "programme_specific_admission_state": "NOT_ADMITTED_MISSING_PROGRAMME_SPECIFIC_AUTHORITY",
            "missing_for_programme_specific_admission": [
                "programme_specific_official_2028_2034_authority",
                "bounded_official_programme_endpoint",
                "programme_specific_semantic_reconciliation",
            ],
            "open_confirmation_state": "NOT_APPLICABLE_PROGRAMME_SPECIFIC_PIPELINE_NOT_ADMITTED",
            **base_false,
        }],
        "cards": [
            {
                "source_id": "SRC-PROPOSAL",
                "programme_ids": ["TEST-A"],
                "programme": "Program <Alpha>",
                "programme_family": "TEST",
                "programme_period": "2028-2034",
                "observation_state": "PROPOSAL",
                "observation_label_ro": "Propunere",
                "authority_class": "T1",
                "authority_url": "https://official.example/alpha",
                "supporting_authority_url": None,
                "observed_at": "2026-09-01T00:45:00Z",
                "source_published_date": "2026-08-20",
                "consultation_start_date": None,
                "consultation_end_date": None,
                "consultation_lifecycle": "NOT_A_CONSULTATION",
                "freshness_state": "CURRENT_60D",
                "watch_priority": 70,
                "source_health": {
                    "health_state": "HEALTHY",
                    "lkg_required": False,
                    "http_status": 200,
                    "raw_sha256": "a" * 64,
                },
                "reconciliation": {
                    "change_kind": "NO_CHANGE",
                    "semantic_changed": False,
                    "transport_or_content_changed": False,
                    "lkg_status": "NOT_REQUIRED_CURRENT_SOURCE_USABLE",
                },
                "confidence": "HIGH",
                "confidence_reason": "CURRENT_OFFICIAL_EVIDENCE_VERIFIED",
                "open_confirmation_state": "NOT_CONFIRMED_MISSING_EXACT_CALL_EVIDENCE",
                "missing_for_open_confirmation": [
                    "exact_call_or_topic_identifier",
                    "current_official_exact_call_endpoint",
                    "explicit_current_official_call_status",
                    "call_specific_deadline_budget_eligibility_and_geography",
                    "semantic_reconciliation",
                ],
                **base_false,
            },
            {
                "source_id": "SRC-CONSULT",
                "programme_ids": ["TEST-B"],
                "programme": "Program Beta",
                "programme_family": "TEST",
                "programme_period": "2028-2034",
                "observation_state": "CONSULTATION",
                "observation_label_ro": "Consultare",
                "authority_class": "T1",
                "authority_url": "https://official.example/beta",
                "supporting_authority_url": "https://official.example/beta-support",
                "observed_at": "2026-09-01T00:45:00Z",
                "source_published_date": "2026-08-20",
                "consultation_start_date": "2026-08-20",
                "consultation_end_date": "2026-09-30",
                "consultation_lifecycle": "IN_WINDOW",
                "freshness_state": "CURRENT_60D",
                "watch_priority": 90,
                "source_health": {
                    "health_state": "DEGRADED_CERTIFICATE_VERIFY_FAILED",
                    "lkg_required": True,
                    "http_status": None,
                    "raw_sha256": None,
                },
                "reconciliation": {
                    "change_kind": "TRANSPORT_OR_CONTENT_CHANGE",
                    "semantic_changed": False,
                    "transport_or_content_changed": True,
                    "lkg_status": "REQUIRED_REFERENCE_UNAVAILABLE",
                },
                "confidence": "LOW",
                "confidence_reason": "CURRENT_TRANSPORT_DEGRADED_CURRENT_PROOF_MISSING",
                "open_confirmation_state": "NOT_CONFIRMED_MISSING_EXACT_CALL_EVIDENCE",
                "missing_for_open_confirmation": [
                    "exact_call_or_topic_identifier",
                    "current_official_exact_call_endpoint",
                    "explicit_current_official_call_status",
                    "call_specific_deadline_budget_eligibility_and_geography",
                    "semantic_reconciliation",
                ],
                **base_false,
            },
        ],
        "reader_copy_generated": False,
        "seo_indexing_state": "NOINDEX_PREVIEW_ONLY",
        "call_alert_authorized": False,
        "note": "preview only",
        **base_false,
    }


def expect_fail(data: dict, label: str) -> None:
    try:
        render(data)
    except ValueError:
        return
    raise AssertionError(f"expected fail-closed preview rejection: {label}")


def main() -> None:
    data = fixture()
    rendered = render(data)
    assert '<meta name="robots" content="noindex,nofollow">' in rendered
    assert "Nu este o listă de apeluri deschise." in rendered
    assert "Nu este apel deschis." in rendered
    assert "Termen al consultării" in rendered
    assert "Nu este termen de apel de finanțare." in rendered
    assert "Program &lt;Alpha&gt;" in rendered
    assert "Program <Alpha>" not in rendered
    assert 'data-filter="PROPOSAL"' in rendered
    assert 'data-filter="CONSULTATION"' in rendered
    assert 'data-filter="PROGRAMMING_PROCESS"' in rendered
    assert "ROUA · 2028–2034" in rendered
    assert "Preview tehnic noindex" in rendered

    projection_raw = (json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    html_raw = rendered.encode("utf-8")
    manifest = build_manifest(projection_raw=projection_raw, html_raw=html_raw, data=data)
    assert manifest["preview_id"] == "PROGRAMMING_PIPELINE_ACCESSIBLE_PREVIEW_V1"
    assert manifest["projection_sha256"] == hashlib.sha256(projection_raw).hexdigest()
    assert manifest["preview_html_sha256"] == hashlib.sha256(html_raw).hexdigest()
    assert manifest["publish_authorized"] is False
    assert manifest["distribution_authorized"] is False
    assert manifest["call_alert_authorized"] is False
    assert manifest["publication_effect"] == "NONE"

    bad = copy.deepcopy(data)
    bad["cards"][0]["observation_state"] = "OPEN_CALL"
    expect_fail(bad, "OPEN_CALL card")

    bad = copy.deepcopy(data)
    bad["cards"][0]["publish_authorized"] = True
    expect_fail(bad, "card publish authorization")

    bad = copy.deepcopy(data)
    bad["cards"][0]["authority_url"] = "http://official.example/alpha"
    expect_fail(bad, "non-HTTPS authority")

    bad = copy.deepcopy(data)
    bad["coverage_gaps"][0]["open_call_authorized"] = True
    expect_fail(bad, "coverage gap authorizes OPEN")

    bad = copy.deepcopy(data)
    bad["card_count"] = 3
    expect_fail(bad, "card inventory mismatch")

    print("PASS accessible PROGRAMARE VIITOARE preview is mobile-first, noindex, explainable and fail-closed")


if __name__ == "__main__":
    main()
