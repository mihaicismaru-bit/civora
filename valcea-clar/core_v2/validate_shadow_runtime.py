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
    photo = load(base / "valcea-core-v2-photo-truth.json")
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
