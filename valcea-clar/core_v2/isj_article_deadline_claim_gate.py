from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


IDENTITY_KEYS = (
    "field_evidence_id",
    "scope_field_evidence_id",
    "source_registration_window_field_evidence_id",
    "document_text_evidence_id",
    "upstream_materiality_promotion_evidence_id",
    "fact_kernel_promotion_evidence_id",
    "page_text_sha256",
)


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _claim_gate_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"isj-article-deadline-claim-{digest[:24]}"


def _base() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "mode": "ISJ_ARTICLE_DEADLINE_CLAIM_GATE_SHADOW",
        "source_kind": "isj_valcea",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "canonical_article_mutation_allowed": False,
        "article_projection_allowed": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "fabricated_claim_count": 0,
    }


def _blocked(reason: str, *, detail: str | None = None) -> dict[str, Any]:
    out = {
        **_base(),
        "state": "BLOCKED",
        "reason": reason,
        "claim_candidate_count": 0,
        "claim_candidates": [],
        "shadow_article_claim_integrity_passed": False,
    }
    if detail:
        out["detail"] = detail[:500]
    return out


def _require_shadow_boundary(doc: dict[str, Any], label: str) -> None:
    if doc.get("publication_authority") != "NONE":
        raise RuntimeError(f"{label}_publication_boundary_violation")
    if doc.get("acceptance_ready") is not False:
        raise RuntimeError(f"{label}_acceptance_boundary_violation")
    if doc.get("site_publish_allowed") is not False or doc.get("social_publish_allowed") is not False:
        raise RuntimeError(f"{label}_publication_path_boundary_violation")


def _single_promoted_deadline(fact_kernel: dict[str, Any]) -> dict[str, Any]:
    if fact_kernel.get("state") != "FACT_KERNEL_VERIFIED_SHADOW":
        raise RuntimeError("fact_kernel_not_verified_shadow")
    if fact_kernel.get("writer_allowed") is not False:
        raise RuntimeError("fact_kernel_writer_boundary_violation")
    kernels = fact_kernel.get("kernels") or []
    if len(kernels) != 1 or not isinstance(kernels[0], dict):
        raise RuntimeError("expected_one_fact_kernel")
    promoted = kernels[0].get("promoted_fact_claims") or []
    if int(fact_kernel.get("promoted_fact_claim_count") or 0) != 1 or len(promoted) != 1 or not isinstance(promoted[0], dict):
        raise RuntimeError("expected_one_promoted_fact_claim")
    item = promoted[0]
    if item.get("field") != "registration_deadline":
        raise RuntimeError("promoted_fact_deadline_missing")
    return item


def build_article_deadline_claim_gate(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    writer_consumption: dict[str, Any],
    writer_consumption_validation: dict[str, Any],
    article_report: dict[str, Any],
) -> dict[str, Any]:
    try:
        for label, doc in (
            ("fact_kernel", fact_kernel),
            ("fact_integrity", fact_integrity),
            ("writer_consumption", writer_consumption),
            ("writer_consumption_validation", writer_consumption_validation),
            ("article_report", article_report),
        ):
            _require_shadow_boundary(doc, label)

        if fact_integrity.get("status") != "PASS_SHADOW" or fact_integrity.get("fact_kernel_integrity_verified") is not True:
            raise RuntimeError("fact_kernel_integrity_not_passed")
        if int(fact_integrity.get("promoted_fact_verified_count") or 0) != 1:
            raise RuntimeError("promoted_fact_not_independently_verified")
        if int(fact_integrity.get("fabricated_claim_count") or 0) != 0:
            raise RuntimeError("fact_kernel_integrity_fabricated_claims_nonzero")

        if writer_consumption.get("state") != "WRITER_DEADLINE_CONSUMPTION_VERIFIED_SHADOW":
            raise RuntimeError("writer_consumption_not_verified_shadow")
        if writer_consumption.get("shadow_writer_consumption_allowed") is not True:
            raise RuntimeError("writer_consumption_not_allowed")
        if writer_consumption.get("writer_allowed") is not False or writer_consumption.get("article_projection_allowed") is not False:
            raise RuntimeError("writer_consumption_authority_boundary_violation")
        if int(writer_consumption.get("consumption_candidate_count") or 0) != 1:
            raise RuntimeError("writer_consumption_candidate_count_mismatch")

        if writer_consumption_validation.get("status") != "PASS_SHADOW":
            raise RuntimeError("writer_consumption_validation_not_passed")
        if writer_consumption_validation.get("shadow_writer_consumption_allowed") is not True:
            raise RuntimeError("writer_consumption_validation_not_allowed")
        if writer_consumption_validation.get("article_projection_allowed") is not False:
            raise RuntimeError("writer_consumption_validation_article_boundary_violation")
        if int(writer_consumption_validation.get("verified_consumption_candidate_count") or 0) != 1:
            raise RuntimeError("writer_consumption_not_independently_verified")
        if int(writer_consumption_validation.get("fabricated_claim_count") or 0) != 0:
            raise RuntimeError("writer_consumption_validation_fabricated_claims_nonzero")
        if int(writer_consumption_validation.get("tamper_regressions_passed") or 0) < 4:
            raise RuntimeError("writer_consumption_tamper_proof_missing")

        if article_report.get("state") != "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY":
            raise RuntimeError("article_not_pending_integrity")
        if article_report.get("shadow_writer_executed") is not True:
            raise RuntimeError("shadow_writer_execution_missing")
        if article_report.get("writer_consumes_deadline_projection") is not True:
            raise RuntimeError("writer_deadline_consumption_not_rendered")
        if int(article_report.get("rendered_promoted_claim_count") or 0) != 1:
            raise RuntimeError("rendered_promoted_claim_count_mismatch")
        if article_report.get("article_contains_registration_deadline") is not False:
            raise RuntimeError("deadline_already_in_canonical_article")

        promoted = _single_promoted_deadline(fact_kernel)

        consumption_id = _norm(writer_consumption.get("writer_consumption_evidence_id"))
        if not consumption_id:
            raise RuntimeError("writer_consumption_evidence_id_missing")
        if _norm(writer_consumption_validation.get("writer_consumption_evidence_id")) != consumption_id:
            raise RuntimeError("writer_consumption_validation_identity_mismatch")

        consumption_candidates = writer_consumption.get("consumption_candidates") or []
        if len(consumption_candidates) != 1 or not isinstance(consumption_candidates[0], dict):
            raise RuntimeError("writer_consumption_candidate_missing")
        consumption_candidate = consumption_candidates[0]
        if _norm(consumption_candidate.get("writer_consumption_evidence_id")) != consumption_id:
            raise RuntimeError("writer_consumption_candidate_identity_mismatch")
        if consumption_candidate.get("state") != "WRITER_DEADLINE_CONSUMPTION_VERIFIED_SHADOW":
            raise RuntimeError("writer_consumption_candidate_state_mismatch")

        articles = article_report.get("articles") or []
        if len(articles) != 1 or not isinstance(articles[0], dict):
            raise RuntimeError("expected_one_article")
        package = articles[0].get("article_package") or {}
        if not isinstance(package, dict):
            raise RuntimeError("article_package_missing")
        if package.get("publication_authority") != "NONE":
            raise RuntimeError("article_package_publication_boundary_violation")
        if package.get("article_projection_allowed") is not False:
            raise RuntimeError("article_package_projection_boundary_violation")
        if package.get("site_publish_allowed") is not False or package.get("social_publish_allowed") is not False:
            raise RuntimeError("article_package_publication_path_boundary_violation")
        if package.get("writer_consumes_deadline_projection") is not True:
            raise RuntimeError("article_package_writer_consumption_missing")
        if package.get("article_contains_registration_deadline") is not False:
            raise RuntimeError("article_package_deadline_already_projected")

        pending = package.get("rendered_promoted_claims_pending_integrity") or []
        if len(pending) != 1 or not isinstance(pending[0], dict):
            raise RuntimeError("expected_one_pending_deadline_claim")
        pending_claim = pending[0]
        if pending_claim.get("state") != "WRITER_RENDERED_SHADOW_PENDING_ARTICLE_CLAIM_INTEGRITY":
            raise RuntimeError("pending_claim_state_mismatch")
        if pending_claim.get("field") != "registration_deadline":
            raise RuntimeError("pending_claim_field_mismatch")
        if pending_claim.get("article_projection_allowed") is not False or pending_claim.get("publication_authority") != "NONE":
            raise RuntimeError("pending_claim_authority_boundary_violation")
        if _norm(pending_claim.get("writer_consumption_evidence_id")) != consumption_id:
            raise RuntimeError("pending_claim_consumption_identity_mismatch")

        deadline = _norm(pending_claim.get("value"))
        claim = _norm(pending_claim.get("text"))
        if not deadline or not claim:
            raise RuntimeError("pending_claim_missing_value_or_text")
        if deadline != _norm(writer_consumption.get("registration_deadline")):
            raise RuntimeError("pending_claim_deadline_mismatch")
        if deadline != _norm(writer_consumption_validation.get("registration_deadline")):
            raise RuntimeError("pending_claim_validation_deadline_mismatch")
        if deadline != _norm(consumption_candidate.get("value")) or deadline != _norm(promoted.get("value")):
            raise RuntimeError("pending_claim_upstream_deadline_mismatch")
        if claim != _norm(consumption_candidate.get("claim")) or claim != _norm(promoted.get("claim")):
            raise RuntimeError("pending_claim_upstream_text_mismatch")

        projection_id = _norm(pending_claim.get("writer_projection_evidence_id"))
        if not projection_id:
            raise RuntimeError("pending_claim_projection_identity_missing")
        if projection_id != _norm(writer_consumption.get("writer_projection_evidence_id")):
            raise RuntimeError("pending_claim_projection_identity_mismatch")
        if projection_id != _norm(consumption_candidate.get("writer_projection_evidence_id")):
            raise RuntimeError("pending_claim_candidate_projection_identity_mismatch")

        claim_evidence_ids = [_norm(v) for v in pending_claim.get("claim_evidence_ids") or [] if _norm(v)]
        if not claim_evidence_ids:
            raise RuntimeError("pending_claim_evidence_missing")
        if claim_evidence_ids != [_norm(v) for v in consumption_candidate.get("claim_evidence_ids") or [] if _norm(v)]:
            raise RuntimeError("pending_claim_consumption_evidence_mismatch")
        if claim_evidence_ids != [_norm(v) for v in promoted.get("claim_evidence_ids") or [] if _norm(v)]:
            raise RuntimeError("pending_claim_fact_kernel_evidence_mismatch")

        supporting_ids = [_norm(v) for v in pending_claim.get("supporting_field_evidence_ids") or [] if _norm(v)]
        if supporting_ids != [_norm(v) for v in consumption_candidate.get("supporting_field_evidence_ids") or [] if _norm(v)]:
            raise RuntimeError("pending_claim_supporting_evidence_mismatch")
        if supporting_ids != [_norm(v) for v in promoted.get("supporting_field_evidence_ids") or [] if _norm(v)]:
            raise RuntimeError("pending_claim_fact_kernel_supporting_evidence_mismatch")

        identities: dict[str, str] = {}
        for key in IDENTITY_KEYS:
            value = _norm(pending_claim.get(key))
            if not value:
                raise RuntimeError(f"pending_claim_identity_missing:{key}")
            if value != _norm(consumption_candidate.get(key)) or value != _norm(promoted.get(key)):
                raise RuntimeError(f"pending_claim_identity_mismatch:{key}")
            identities[key] = value

        page_number = int(pending_claim.get("page_number") or 0)
        excerpt = _norm(pending_claim.get("excerpt"))
        if page_number <= 0 or not excerpt:
            raise RuntimeError("pending_claim_document_location_missing")
        if page_number != int(consumption_candidate.get("page_number") or 0) or excerpt != _norm(consumption_candidate.get("excerpt")):
            raise RuntimeError("pending_claim_consumption_document_location_mismatch")
        if page_number != int(promoted.get("page_number") or 0) or excerpt != _norm(promoted.get("excerpt")):
            raise RuntimeError("pending_claim_fact_kernel_document_location_mismatch")

        article_id = _norm(package.get("article_id"))
        if not article_id:
            raise RuntimeError("article_id_missing")
        canonical_claim_texts = [_norm(row.get("text")) for row in package.get("claims") or [] if isinstance(row, dict)]
        if claim in canonical_claim_texts:
            raise RuntimeError("pending_claim_already_in_canonical_claims")
        body = _norm(package.get("body"))
        if deadline in body or claim in body:
            raise RuntimeError("pending_claim_already_in_canonical_body")

        claim_gate_id = _claim_gate_id(
            article_id,
            consumption_id,
            projection_id,
            deadline,
            claim,
            *claim_evidence_ids,
            identities["upstream_materiality_promotion_evidence_id"],
            identities["fact_kernel_promotion_evidence_id"],
            identities["page_text_sha256"],
            str(page_number),
            excerpt,
        )
        candidate = {
            "article_id": article_id,
            "field": "registration_deadline",
            "value": deadline,
            "claim": claim,
            "state": "ARTICLE_DEADLINE_CLAIM_EVIDENCE_VERIFIED_SHADOW",
            **identities,
            "supporting_field_evidence_ids": supporting_ids,
            "claim_evidence_ids": claim_evidence_ids,
            "page_number": page_number,
            "excerpt": excerpt,
            "writer_projection_evidence_id": projection_id,
            "writer_consumption_evidence_id": consumption_id,
            "article_deadline_claim_evidence_id": claim_gate_id,
            "shadow_article_claim_integrity_passed": True,
            "canonical_article_mutation_allowed": False,
            "article_projection_allowed": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
            "publication_authority": "NONE",
        }
        return {
            **_base(),
            "state": "ARTICLE_DEADLINE_CLAIM_EVIDENCE_VERIFIED_SHADOW",
            "reason": "rendered_pending_deadline_claim_is_exactly_rebound_to_independently_validated_writer_consumption_and_fact_kernel_evidence",
            "article_id": article_id,
            "registration_deadline": deadline,
            "writer_projection_evidence_id": projection_id,
            "writer_consumption_evidence_id": consumption_id,
            "article_deadline_claim_evidence_id": claim_gate_id,
            "shadow_article_claim_integrity_passed": True,
            "claim_candidate_count": 1,
            "claim_candidates": [candidate],
            "truth_rule": (
                "This gate verifies one pending writer-rendered registration-deadline claim against the exact independently validated "
                "writer-consumption identity and full promoted FactKernel evidence chain. It does not modify canonical article claims/body "
                "and grants no article projection, site, social, merge, deployment or acceptance authority."
            ),
        }
    except Exception as exc:
        return _blocked("article_deadline_claim_gate_failed", detail=f"{type(exc).__name__}:{exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build fail-closed ISJ article deadline claim↔evidence gate")
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--fact-kernel-integrity", required=True)
    parser.add_argument("--writer-consumption", required=True)
    parser.add_argument("--writer-consumption-validation", required=True)
    parser.add_argument("--article", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = build_article_deadline_claim_gate(
        json.loads(Path(args.fact_kernel).read_text(encoding="utf-8")),
        json.loads(Path(args.fact_kernel_integrity).read_text(encoding="utf-8")),
        json.loads(Path(args.writer_consumption).read_text(encoding="utf-8")),
        json.loads(Path(args.writer_consumption_validation).read_text(encoding="utf-8")),
        json.loads(Path(args.article).read_text(encoding="utf-8")),
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result.get("state"),
        "registration_deadline": result.get("registration_deadline"),
        "shadow_article_claim_integrity_passed": result.get("shadow_article_claim_integrity_passed", False),
        "canonical_article_mutation_allowed": False,
        "article_projection_allowed": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
