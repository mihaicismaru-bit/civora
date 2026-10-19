from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _consumption_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"isj-writer-deadline-consumption-{digest[:24]}"


def _base() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "mode": "ISJ_WRITER_DEADLINE_CONSUMPTION_SHADOW",
        "source_kind": "isj_valcea",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "shadow_writer_consumption_allowed": False,
        "writer_allowed": False,
        "production_writer_ready": False,
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
        "consumption_candidate_count": 0,
        "consumption_candidates": [],
    }
    if detail:
        out["detail"] = detail[:500]
    return out


def _require_shadow_boundary(doc: dict[str, Any], label: str) -> None:
    if doc.get("publication_authority") != "NONE":
        raise RuntimeError(f"{label}_publication_boundary_violation")
    if doc.get("acceptance_ready") is not False:
        raise RuntimeError(f"{label}_acceptance_boundary_violation")
    if doc.get("production_writer_ready") is not False:
        raise RuntimeError(f"{label}_production_writer_boundary_violation")
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
    if len(promoted) != 1 or int(fact_kernel.get("promoted_fact_claim_count") or 0) != 1:
        raise RuntimeError("expected_one_promoted_fact_claim")
    item = promoted[0]
    if not isinstance(item, dict) or item.get("field") != "registration_deadline":
        raise RuntimeError("promoted_fact_deadline_missing")
    return item


def build_writer_deadline_consumption(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    projection: dict[str, Any],
    projection_validation: dict[str, Any],
    *,
    expected_year: int = 2026,
) -> dict[str, Any]:
    try:
        for label, doc in (
            ("fact_kernel", fact_kernel),
            ("fact_integrity", fact_integrity),
            ("projection", projection),
            ("projection_validation", projection_validation),
        ):
            _require_shadow_boundary(doc, label)

        if fact_integrity.get("status") != "PASS_SHADOW" or fact_integrity.get("fact_kernel_integrity_verified") is not True:
            raise RuntimeError("fact_kernel_integrity_not_passed")
        if int(fact_integrity.get("fabricated_claim_count") or 0) != 0:
            raise RuntimeError("fact_kernel_integrity_fabricated_claims_nonzero")
        if int(fact_integrity.get("promoted_fact_verified_count") or 0) != 1:
            raise RuntimeError("promoted_fact_not_independently_verified")

        if projection.get("state") != "WRITER_PROJECTION_VERIFIED_SHADOW":
            raise RuntimeError("writer_projection_not_verified_shadow")
        if projection.get("writer_deadline_projection_allowed") is not True:
            raise RuntimeError("writer_projection_not_allowed")
        if projection.get("writer_allowed") is not False or projection.get("article_projection_allowed") is not False:
            raise RuntimeError("writer_projection_authority_boundary_violation")
        if int(projection.get("projection_candidate_count") or 0) != 1:
            raise RuntimeError("writer_projection_candidate_count_mismatch")

        if projection_validation.get("status") != "PASS_SHADOW":
            raise RuntimeError("writer_projection_validation_not_passed")
        if projection_validation.get("writer_deadline_projection_allowed") is not True:
            raise RuntimeError("writer_projection_validation_not_allowed")
        if projection_validation.get("article_projection_allowed") is not False:
            raise RuntimeError("projection_validation_article_boundary_violation")
        if int(projection_validation.get("verified_projection_candidate_count") or 0) != 1:
            raise RuntimeError("writer_projection_not_independently_verified")
        if int(projection_validation.get("fabricated_claim_count") or 0) != 0:
            raise RuntimeError("writer_projection_validation_fabricated_claims_nonzero")
        if int(projection_validation.get("tamper_regressions_passed") or 0) < 3:
            raise RuntimeError("writer_projection_tamper_proof_missing")

        promoted = _single_promoted_deadline(fact_kernel)
        candidates = projection.get("projection_candidates") or []
        if len(candidates) != 1 or not isinstance(candidates[0], dict):
            raise RuntimeError("writer_projection_candidate_missing")
        candidate = candidates[0]

        projection_id = str(projection.get("writer_projection_evidence_id") or "")
        if not projection_id or candidate.get("writer_projection_evidence_id") != projection_id:
            raise RuntimeError("writer_projection_evidence_identity_mismatch")
        if projection_validation.get("writer_projection_evidence_id") != projection_id:
            raise RuntimeError("writer_projection_validation_identity_mismatch")

        deadline = str(candidate.get("value") or "")
        parsed = date.fromisoformat(deadline)
        if parsed.year != expected_year or projection.get("registration_deadline") != deadline or projection_validation.get("registration_deadline") != deadline:
            raise RuntimeError("registration_deadline_identity_mismatch")
        if promoted.get("value") != deadline:
            raise RuntimeError("promoted_fact_deadline_mismatch")

        claim = _norm(candidate.get("claim"))
        if not claim or claim != _norm(promoted.get("claim")):
            raise RuntimeError("promoted_fact_claim_mismatch")
        if candidate.get("field") != "registration_deadline" or promoted.get("field") != "registration_deadline":
            raise RuntimeError("registration_deadline_field_mismatch")
        if candidate.get("state") != "WRITER_DEADLINE_PROJECTION_VERIFIED_SHADOW":
            raise RuntimeError("projection_candidate_state_mismatch")
        if candidate.get("writer_deadline_projection_allowed") is not True or candidate.get("writer_allowed") is not False:
            raise RuntimeError("projection_candidate_writer_boundary_violation")
        if candidate.get("article_projection_allowed") is not False:
            raise RuntimeError("projection_candidate_article_boundary_violation")

        identity_keys = (
            "field_evidence_id",
            "scope_field_evidence_id",
            "source_registration_window_field_evidence_id",
            "document_text_evidence_id",
            "upstream_materiality_promotion_evidence_id",
            "fact_kernel_promotion_evidence_id",
            "page_text_sha256",
        )
        identities = {key: str(candidate.get(key) or "") for key in identity_keys}
        if any(not value for value in identities.values()):
            raise RuntimeError("writer_projection_identity_missing")
        for key, value in identities.items():
            if str(promoted.get(key) or "") != value:
                raise RuntimeError(f"promoted_fact_{key}_mismatch")

        claim_evidence_ids = [str(v) for v in candidate.get("claim_evidence_ids") or []]
        if not claim_evidence_ids or claim_evidence_ids != [str(v) for v in promoted.get("claim_evidence_ids") or []]:
            raise RuntimeError("writer_projection_claim_evidence_mismatch")
        supporting = [str(v) for v in candidate.get("supporting_field_evidence_ids") or []]
        if supporting != [str(v) for v in promoted.get("supporting_field_evidence_ids") or []]:
            raise RuntimeError("writer_projection_supporting_evidence_mismatch")

        page_number = int(candidate.get("page_number") or 0)
        excerpt = _norm(candidate.get("excerpt"))
        if page_number <= 0 or not excerpt:
            raise RuntimeError("writer_projection_document_location_missing")
        if int(promoted.get("page_number") or 0) != page_number or _norm(promoted.get("excerpt")) != excerpt:
            raise RuntimeError("promoted_fact_document_location_mismatch")

        consumption_id = _consumption_id(
            projection_id,
            str(expected_year),
            deadline,
            claim,
            *claim_evidence_ids,
            identities["upstream_materiality_promotion_evidence_id"],
            identities["page_text_sha256"],
            str(page_number),
            excerpt,
        )
        consumption_candidate = {
            "field": "registration_deadline",
            "value": deadline,
            "claim": claim,
            "state": "WRITER_DEADLINE_CONSUMPTION_VERIFIED_SHADOW",
            **identities,
            "supporting_field_evidence_ids": supporting,
            "claim_evidence_ids": claim_evidence_ids,
            "page_number": page_number,
            "excerpt": excerpt,
            "writer_projection_evidence_id": projection_id,
            "writer_consumption_evidence_id": consumption_id,
            "shadow_writer_consumption_allowed": True,
            "writer_allowed": False,
            "production_writer_ready": False,
            "article_projection_allowed": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
        }
        return {
            **_base(),
            "state": "WRITER_DEADLINE_CONSUMPTION_VERIFIED_SHADOW",
            "reason": "independently_validated_writer_projection_is_eligible_for_later_deterministic_shadow_writer_consumption_only",
            "registration_deadline": deadline,
            "writer_projection_evidence_id": projection_id,
            "writer_consumption_evidence_id": consumption_id,
            "shadow_writer_consumption_allowed": True,
            "consumption_candidate_count": 1,
            "consumption_candidates": [consumption_candidate],
            "truth_rule": (
                "This gate binds one independently validated writer projection to a deterministic shadow-writer consumption identity. "
                "It does not alter article prose, mark the writer as production-ready, grant article/site/social authority, or satisfy acceptance."
            ),
        }
    except Exception as exc:
        return _blocked("writer_deadline_consumption_gate_failed", detail=f"{type(exc).__name__}:{exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build fail-closed ISJ writer-deadline consumption gate")
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--fact-kernel-integrity", required=True)
    parser.add_argument("--projection", required=True)
    parser.add_argument("--projection-validation", required=True)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build_writer_deadline_consumption(
        json.loads(Path(args.fact_kernel).read_text(encoding="utf-8")),
        json.loads(Path(args.fact_kernel_integrity).read_text(encoding="utf-8")),
        json.loads(Path(args.projection).read_text(encoding="utf-8")),
        json.loads(Path(args.projection_validation).read_text(encoding="utf-8")),
        expected_year=args.year,
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result.get("state"),
        "registration_deadline": result.get("registration_deadline"),
        "shadow_writer_consumption_allowed": result.get("shadow_writer_consumption_allowed", False),
        "writer_allowed": False,
        "article_projection_allowed": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
