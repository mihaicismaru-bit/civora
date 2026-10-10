from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require_none_authority(doc: dict[str, Any], label: str) -> None:
    assert doc.get("publication_authority") == "NONE", f"{label}: publication authority escaped shadow"
    if "acceptance_ready" in doc:
        assert doc.get("acceptance_ready") is False, f"{label}: acceptance_ready must remain false"


def validate(base: Path, repo: Path) -> None:
    checkpoint = load(repo / "valcea-clar/core_v2/checkpoint.json")
    sources = load(repo / "valcea-clar/core_v2/pilot_sources.json")
    apavil = load(base / "valcea-core-v2-apavil-shadow.json")
    ipj = load(base / "valcea-core-v2-ipj-shadow.json")
    isu = load(base / "valcea-core-v2-isu-shadow.json")
    municipal = load(base / "valcea-core-v2-municipal-shadow.json")
    municipal_docs = load(base / "valcea-core-v2-municipal-documents.json")
    municipal_materiality = load(base / "valcea-core-v2-municipal-materiality.json")
    municipal_kernels = load(base / "valcea-core-v2-municipal-fact-kernels.json")
    municipal_articles = load(base / "valcea-core-v2-municipal-articles.json")
    cj_road = load(base / "valcea-core-v2-cj-road-shadow.json")
    eta = load(base / "valcea-core-v2-eta-shadow.json")
    isj = load(base / "valcea-core-v2-isj-shadow.json")
    isj_detail = load(base / "valcea-core-v2-isj-detail-shadow.json")
    isj_materiality = load(base / "valcea-core-v2-isj-materiality-shadow.json")
    isj_embedded = load(base / "valcea-core-v2-isj-embedded-notice-shadow.json")
    isj_fact_kernel = load(base / "valcea-core-v2-isj-fact-kernel-shadow.json")
    isj_fact_integrity = load(base / "valcea-core-v2-isj-fact-kernel-integrity-shadow.json")
    isj_article = load(base / "valcea-core-v2-isj-article-shadow.json")
    isj_article_integrity = load(base / "valcea-core-v2-isj-article-integrity-shadow.json")
    photo = load(base / "valcea-core-v2-photo-truth.json")
    shadow_site = load(base / "valcea-core-v2-shadow-site-package.json")
    ledger = load(base / "valcea-core-v2-shadow-candidates.json")
    readback = load(base / "valcea-core-v2-site-readback.json")
    visual = load(base / "valcea-core-v2-visual-readback.json")
    meta = load(base / "valcea-core-v2-meta-readback.json")
    receipts = load(base / "valcea-core-v2-shadow-receipts.json")
    transactions = load(base / "valcea-core-v2-shadow-transactions.json")
    gates = load(base / "valcea-core-v2-gate-report.json")

    assert checkpoint.get("core_v2_mode") == "SHADOW_ONLY"
    require_none_authority(checkpoint, "checkpoint")
    require_none_authority(sources, "pilot_sources")
    assert sources.get("source_expansion_forbidden_during_pilot") is True

    require_none_authority(apavil, "apavil")

    for label, public_safety in (("ipj", ipj), ("isu", isu)):
        require_none_authority(public_safety, label)
        assert public_safety.get("production_writer_ready") is False
        assert int(public_safety.get("fabricated_claim_count") or 0) == 0
        assert int(public_safety.get("structured_editorial_count") or 0) == int(
            public_safety.get("verified_written_shadow_count") or 0
        )
        for row in public_safety.get("rows") or []:
            if row.get("state") != "VERIFIED_WRITTEN_SHADOW":
                continue
            assert (row.get("integrity") or {}).get("status") == "PASS"
            assert int((row.get("integrity") or {}).get("fabricated_claims") or 0) == 0
            assert row.get("production_writer_ready") is False
            assert (row.get("article_package") or {}).get("writer_id") == "shadow_structured_editorial_v2"
            assert (row.get("currentness") or {}).get("publication_date_is_event_time") is False

    require_none_authority(municipal, "municipal_reference")
    assert municipal.get("production_writer_ready") is False
    assert int(municipal.get("verified_written_shadow_count") or 0) == 0
    for row in municipal.get("rows") or []:
        assert row.get("state") in {"NO_STORY", "BLOCKED"}
        assert "fact_kernel" not in row and "article_package" not in row

    require_none_authority(municipal_docs, "municipal_documents")
    assert municipal_docs.get("fact_kernel_promotion_allowed") is False
    assert municipal_docs.get("writer_allowed") is False
    assert int(municipal_docs.get("fabricated_claim_count") or 0) == 0
    document_evidence = {
        (int(row.get("decision_number") or 0), str(row.get("decision_date") or "")): {
            str(item.get("evidence_id"))
            for item in (row.get("evidence") or [])
            if item.get("evidence_id")
        }
        for row in (municipal_docs.get("rows") or [])
    }
    for row in municipal_docs.get("rows") or []:
        assert row.get("state") in {"DOCUMENT_EVIDENCE_READY", "BLOCKED"}
        assert row.get("publication_authority") == "NONE"
        assert row.get("fact_kernel_promotion_allowed") is False
        assert row.get("writer_allowed") is False
        assert "fact_kernel" not in row and "article_package" not in row
        for evidence in row.get("evidence") or []:
            assert evidence.get("material_fact_status") == "UNADJUDICATED"
            assert evidence.get("epistemic_status") == "FIRST_PARTY_DOCUMENT_TEXT"

    require_none_authority(municipal_materiality, "municipal_materiality")
    assert municipal_materiality.get("fact_kernel_promotion_allowed") is False
    assert municipal_materiality.get("writer_allowed") is False
    assert municipal_materiality.get("production_writer_ready") is False
    assert int(municipal_materiality.get("fabricated_claim_count") or 0) == 0
    for row in municipal_materiality.get("rows") or []:
        assert row.get("state") in {"MATERIALITY_CANDIDATE", "NO_STORY", "BLOCKED"}
        assert row.get("publication_authority") == "NONE"
        assert row.get("fact_kernel_promotion_allowed") is False
        assert row.get("writer_allowed") is False
        assert "fact_kernel" not in row and "article_package" not in row
        evidence_ids = document_evidence.get(
            (int(row.get("decision_number") or 0), str(row.get("decision_date") or "")), set()
        )
        for candidate in row.get("materiality_candidates") or []:
            candidate_ids = set(candidate.get("evidence_ids") or [])
            assert candidate_ids and candidate_ids <= evidence_ids
            assert candidate.get("epistemic_status") == "DOCUMENT_SUPPORTED_MATERIALITY_CANDIDATE"
            assert candidate.get("fact_kernel_status") == "NOT_PROMOTED"

    require_none_authority(municipal_kernels, "municipal_kernels")
    assert municipal_kernels.get("writer_allowed") is False
    assert municipal_kernels.get("production_writer_ready") is False
    assert municipal_kernels.get("site_publish_allowed") is False
    assert municipal_kernels.get("social_publish_allowed") is False
    assert int(municipal_kernels.get("fabricated_claim_count") or 0) == 0
    for row in municipal_kernels.get("rows") or []:
        assert row.get("state") in {"FACT_KERNEL_VERIFIED_SHADOW", "NO_STORY", "BLOCKED"}
        if row.get("state") != "FACT_KERNEL_VERIFIED_SHADOW":
            continue
        for kernel in row.get("kernels") or []:
            integrity = kernel.get("integrity") or {}
            assert integrity.get("status") == "PASS_SHADOW"
            assert integrity.get("all_claims_evidence_bound") is True
            assert int(integrity.get("fabricated_claims") or 0) == 0
            fact_kernel = kernel.get("fact_kernel") or {}
            assert fact_kernel.get("claims") and fact_kernel.get("evidence_ids")
            for binding in kernel.get("claim_evidence") or []:
                assert binding.get("claim") in fact_kernel.get("claims")
                assert binding.get("evidence_ids")

    require_none_authority(municipal_articles, "municipal_articles")
    assert municipal_articles.get("production_writer_ready") is False
    assert municipal_articles.get("site_publish_allowed") is False
    assert municipal_articles.get("social_publish_allowed") is False
    assert int(municipal_articles.get("fabricated_claim_count") or 0) == 0
    for row in municipal_articles.get("rows") or []:
        assert row.get("state") in {"VERIFIED_WRITTEN_SHADOW", "NO_STORY", "BLOCKED"}
        if row.get("state") != "VERIFIED_WRITTEN_SHADOW":
            continue
        assert row.get("articles")
        for article in row.get("articles") or []:
            assert article.get("state") == "VERIFIED_WRITTEN_SHADOW"
            assert article.get("publication_authority") == "NONE"
            assert article.get("production_writer_ready") is False
            assert article.get("site_publish_allowed") is False
            assert article.get("social_publish_allowed") is False
            integrity = article.get("integrity") or {}
            assert integrity.get("status") == "PASS"
            assert integrity.get("body_fully_controlled") is True
            assert int(integrity.get("fabricated_claims") or 0) == 0
            assert (article.get("article_package") or {}).get("writer_id") == "municipal_shadow_editorial_v1"

    require_none_authority(cj_road, "cj_road")
    assert cj_road.get("fact_kernel_promotion_allowed") is False
    assert cj_road.get("writer_allowed") is False
    assert cj_road.get("production_writer_ready") is False
    assert int(cj_road.get("verified_written_shadow_count") or 0) == 0
    assert int(cj_road.get("fabricated_claim_count") or 0) == 0

    require_none_authority(eta, "eta")
    assert eta.get("fact_kernel_promotion_allowed") is False
    assert eta.get("writer_allowed") is False
    assert eta.get("production_writer_ready") is False
    assert eta.get("site_publish_allowed") is False
    assert eta.get("social_publish_allowed") is False
    for row in eta.get("rows") or []:
        assert row.get("state") in {"MATERIAL_SIGNAL_SHADOW", "NO_STORY", "BLOCKED"}
        assert row.get("publication_authority") == "NONE"
        assert row.get("fact_kernel_promotion_allowed") is False
        assert row.get("writer_allowed") is False
        assert row.get("site_publish_allowed") is False
        assert row.get("social_publish_allowed") is False
        assert "fact_kernel" not in row and "article_package" not in row
        assert row.get("visual_candidate_promoted") is not True

    require_none_authority(isj, "isj")
    assert isj.get("fact_kernel_promotion_allowed") is False
    assert isj.get("writer_allowed") is False
    assert isj.get("production_writer_ready") is False
    assert isj.get("site_publish_allowed") is False
    assert isj.get("social_publish_allowed") is False
    for row in isj.get("rows") or []:
        assert row.get("state") in {"MATERIAL_SIGNAL_SHADOW", "NO_STORY", "BLOCKED"}
        assert row.get("publication_authority") == "NONE"
        assert row.get("fact_kernel_promotion_allowed") is False
        assert row.get("writer_allowed") is False
        assert row.get("site_publish_allowed") is False
        assert row.get("social_publish_allowed") is False
        assert row.get("person_fact_extraction_allowed") is False
        assert row.get("sensitive_result_projection_allowed") is False
        assert "fact_kernel" not in row and "article_package" not in row
        if row.get("state") == "MATERIAL_SIGNAL_SHADOW":
            assert row.get("document_body_required_for_fact_kernel") is True
            assert row.get("label_date_is_event_time") is False

    require_none_authority(isj_detail, "isj_detail")
    assert isj_detail.get("fact_kernel_promotion_allowed") is False
    assert isj_detail.get("writer_allowed") is False
    for row in isj_detail.get("rows") or []:
        assert row.get("state") in {"DETAIL_EVIDENCE_SHADOW", "BLOCKED"}
        assert row.get("publication_authority") == "NONE"
        assert row.get("fact_kernel_promotion_allowed") is False
        assert row.get("writer_allowed") is False
        assert row.get("sensitive_result_projection_allowed") is False
        assert "fact_kernel" not in row and "article_package" not in row

    require_none_authority(isj_materiality, "isj_materiality")
    assert isj_materiality.get("fact_kernel_promotion_allowed") is False
    assert isj_materiality.get("writer_allowed") is False
    assert isj_materiality.get("production_writer_ready") is False
    for row in isj_materiality.get("rows") or []:
        assert row.get("state") in {"MATERIAL_DETAIL_CANDIDATE_SHADOW", "NO_STORY", "BLOCKED"}
        assert row.get("publication_authority") == "NONE"
        assert row.get("fact_kernel_promotion_allowed") is False
        assert row.get("writer_allowed") is False
        assert row.get("sensitive_result_projection_allowed") is False
        assert "fact_kernel" not in row and "article_package" not in row

    require_none_authority(isj_embedded, "isj_embedded_notice")
    assert isj_embedded.get("fact_kernel_promotion_allowed") is False
    assert isj_embedded.get("writer_allowed") is False
    assert isj_embedded.get("site_publish_allowed") is False
    assert isj_embedded.get("social_publish_allowed") is False
    for row in isj_embedded.get("rows") or []:
        assert row.get("state") in {"EMBEDDED_NOTICE_EVIDENCE_SHADOW", "BLOCKED"}
        assert row.get("publication_authority") == "NONE"
        assert row.get("fact_kernel_promotion_allowed") is False
        assert row.get("writer_allowed") is False
        assert row.get("sensitive_result_projection_allowed") is False
        assert row.get("event_time_verified") is not True
        assert row.get("deadline_verified") is not True
        assert row.get("vacancy_count_verified") is not True
        assert row.get("embedded_targets_fetched") is not True
        assert row.get("embedded_document_content_verified") is not True
        assert "fact_kernel" not in row and "article_package" not in row
        if row.get("state") == "EMBEDDED_NOTICE_EVIDENCE_SHADOW":
            assert row.get("parent_identity_reverified") is True
            assert row.get("embedded_file_labels")
            assert row.get("explicit_current_material_catalog") is True

    # Late ISJ truth must be validated from the actual artifacts, not only from
    # the orchestrator summary or a workflow-local assertion block.
    for label, doc in (
        ("isj_fact_kernel", isj_fact_kernel),
        ("isj_fact_kernel_integrity", isj_fact_integrity),
        ("isj_article", isj_article),
        ("isj_article_integrity", isj_article_integrity),
    ):
        require_none_authority(doc, label)
        assert doc.get("production_writer_ready") is False
        assert doc.get("site_publish_allowed") is False
        assert doc.get("social_publish_allowed") is False

    assert isj_fact_kernel.get("writer_allowed") is False
    assert isj_fact_kernel.get("state") == "FACT_KERNEL_VERIFIED_SHADOW"
    assert int(isj_fact_kernel.get("fact_kernel_count") or 0) == 1
    assert int(isj_fact_kernel.get("fabricated_claim_count") or 0) == 0
    isj_kernels = isj_fact_kernel.get("kernels") or []
    assert len(isj_kernels) == 1 and isinstance(isj_kernels[0], dict)
    isj_kernel_row = isj_kernels[0]
    isj_kernel = isj_kernel_row.get("fact_kernel") or {}
    assert isj_kernel_row.get("integrity_status") == "PENDING_SEPARATE_GATE"
    assert "writer" not in isj_kernel_row and "article" not in isj_kernel_row
    assert len(isj_kernel.get("claims") or []) == 2
    assert len(set(isj_kernel.get("evidence_ids") or [])) == 4
    assert isj_kernel.get("source_url") == "https://www.isjvalcea.ro/management/concurs-directori-2026"

    assert isj_fact_integrity.get("status") == "PASS_SHADOW"
    assert isj_fact_integrity.get("fact_kernel_integrity_verified") is True
    assert isj_fact_integrity.get("writer_allowed") is False
    assert isj_fact_integrity.get("writer_gate_status") == "ELIGIBLE_FOR_SEPARATE_SHADOW_WRITER_IMPLEMENTATION"
    assert int(isj_fact_integrity.get("verified_claim_count") or 0) == 2
    assert int(isj_fact_integrity.get("fabricated_claim_count") or 0) == 0

    assert isj_article.get("state") == "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY"
    assert isj_article.get("shadow_writer_executed") is True
    assert int(isj_article.get("article_count") or 0) == 1
    assert int(isj_article.get("fabricated_claim_count") or 0) == 0
    isj_articles = isj_article.get("articles") or []
    assert len(isj_articles) == 1 and isinstance(isj_articles[0], dict)
    isj_article_row = isj_articles[0]
    assert isj_article_row.get("fact_kernel") == isj_kernel
    assert isj_article_row.get("state") == "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY"
    assert isj_article_row.get("publication_authority") == "NONE"
    assert isj_article_row.get("production_writer_ready") is False
    assert isj_article_row.get("site_publish_allowed") is False
    assert isj_article_row.get("social_publish_allowed") is False
    isj_package = isj_article_row.get("article_package") or {}
    assert isj_package.get("article_id") == "isj-directori-2026-conducere-scoli"
    assert isj_package.get("writer_id") == "isj_shadow_editorial_v1"
    assert len(isj_package.get("claims") or []) == len(isj_kernel.get("claims") or [])
    excluded_fields = set(isj_package.get("excluded_unverified_or_non_normalized_fields") or [])
    assert {"registration_deadline", "interview_window_text", "appointment_decision_deadline_text"}.issubset(excluded_fields)

    assert isj_article_integrity.get("status") == "PASS_SHADOW"
    assert isj_article_integrity.get("article_truth_state") == "VERIFIED_WRITTEN_SHADOW"
    assert isj_article_integrity.get("article_integrity_verified") is True
    assert isj_article_integrity.get("photo_gate_status") == "ELIGIBLE_FOR_SEPARATE_PHOTO_TRUTH_GATE"
    assert int(isj_article_integrity.get("verified_article_count") or 0) == 1
    assert int(isj_article_integrity.get("verified_claim_count") or 0) == 2
    assert int(isj_article_integrity.get("fabricated_claim_count") or 0) == 0
    verified_isj_candidates = isj_article_integrity.get("verified_candidates") or []
    assert len(verified_isj_candidates) == 1
    assert verified_isj_candidates[0].get("article_id") == isj_package.get("article_id")
    assert verified_isj_candidates[0].get("source_url") == isj_kernel.get("source_url")

    require_none_authority(photo, "photo_truth")
    assert photo.get("site_publish_allowed") is False
    assert photo.get("social_publish_allowed") is False
    for row in photo.get("rows") or []:
        assert row.get("status") in {"VISUAL_CANDIDATE_VERIFIED_SHADOW", "BLOCKED"}
        assert row.get("publication_authority") == "NONE"
        assert row.get("social_publish_allowed") is False
        if row.get("status") == "VISUAL_CANDIDATE_VERIFIED_SHADOW":
            assert row.get("visual_ready_for_future_site_binding") is True
            assert row.get("article_binding_verified") is False
        else:
            assert row.get("reason")

    require_none_authority(shadow_site, "shadow_site_package")
    assert shadow_site.get("site_publish_allowed") is False
    assert shadow_site.get("social_publish_allowed") is False
    assert shadow_site.get("public_article_binding_verified") is False
    assert shadow_site.get("visual_ready") is False
    for row in shadow_site.get("rows") or []:
        assert row.get("status") in {"PACKAGE_IMAGE_BOUND_SHADOW", "BLOCKED"}
        assert row.get("publication_authority") == "NONE"
        assert row.get("site_publish_allowed") is False
        assert row.get("social_publish_allowed") is False
        assert row.get("public_article_binding_verified") is False
        assert row.get("visual_ready") is False
        if row.get("status") == "PACKAGE_IMAGE_BOUND_SHADOW":
            assert row.get("staged_package_binding_verified") is True
            assert (row.get("binding") or {}).get("article_image_bound") is True
        else:
            assert row.get("reason")

    for label, doc in (
        ("legacy_candidates", ledger),
        ("site_readback", readback),
        ("visual_readback", visual),
        ("meta_readback", meta),
        ("shadow_receipts", receipts),
        ("shadow_transactions", transactions),
        ("shadow_gates", gates),
    ):
        require_none_authority(doc, label)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate all Core v2 live shadow artifacts remain non-authoritative")
    parser.add_argument("--base", default="/tmp")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()
    validate(Path(args.base), Path(args.repo))
    print("Core v2 shadow runtime invariants: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
