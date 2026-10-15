from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _promotion_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"isj-fact-kernel-deadline-promotion-{digest[:24]}"


def _base() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "mode": "ISJ_FACT_KERNEL_DEADLINE_PROMOTION_SHADOW",
        "source_kind": "isj_valcea",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "material_fact_use": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
    }


def _blocked(reason: str, *, detail: str | None = None) -> dict[str, Any]:
    out = {
        **_base(),
        "state": "BLOCKED",
        "reason": reason,
        "promotion_candidate_count": 0,
        "promotion_candidates": [],
        "fabricated_claim_count": 0,
    }
    if detail:
        out["detail"] = detail[:500]
    return out


def _require_upstream_boundary(doc: dict[str, Any], label: str) -> None:
    if doc.get("publication_authority") != "NONE":
        raise ValueError(f"{label}_publication_boundary_violation")
    if doc.get("acceptance_ready") is not False:
        raise ValueError(f"{label}_acceptance_boundary_violation")
    if doc.get("fact_kernel_promotion_allowed") is not False:
        raise ValueError(f"{label}_fact_kernel_boundary_violation")
    if doc.get("writer_allowed") is not False:
        raise ValueError(f"{label}_writer_boundary_violation")
    if doc.get("site_publish_allowed") is not False or doc.get("social_publish_allowed") is not False:
        raise ValueError(f"{label}_publication_path_boundary_violation")


def _single_materiality_candidate(materiality: dict[str, Any]) -> dict[str, Any]:
    candidates = materiality.get("materiality_candidates") or []
    if materiality.get("state") != "MATERIALITY_CANDIDATE_SHADOW":
        raise RuntimeError("materiality_state_not_candidate")
    if len(candidates) != 1 or int(materiality.get("materiality_candidate_count") or 0) != 1:
        raise RuntimeError(f"expected_one_materiality_candidate:observed={len(candidates)}")
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise RuntimeError("materiality_candidate_invalid")
    if candidate.get("category") != "LOCAL_EDUCATION_LEADERSHIP":
        raise RuntimeError("materiality_category_mismatch")
    if candidate.get("fact_kernel_status") != "NOT_PROMOTED":
        raise RuntimeError("materiality_fact_kernel_status_not_pristine")
    return candidate


def _single_materiality_promotion_candidate(promotion: dict[str, Any]) -> dict[str, Any]:
    candidates = promotion.get("promotion_candidates") or []
    if promotion.get("state") != "MATERIALITY_PROMOTION_VERIFIED_SHADOW":
        raise RuntimeError("materiality_promotion_state_not_verified")
    if promotion.get("materiality_promotion_allowed") is not True:
        raise RuntimeError("materiality_promotion_not_allowed")
    if len(candidates) != 1 or int(promotion.get("promotion_candidate_count") or 0) != 1:
        raise RuntimeError(f"expected_one_materiality_promotion_candidate:observed={len(candidates)}")
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise RuntimeError("materiality_promotion_candidate_invalid")
    if candidate.get("field") != "registration_deadline":
        raise RuntimeError("materiality_promotion_field_mismatch")
    return candidate


def build_fact_kernel_deadline_promotion(
    materiality: dict[str, Any],
    materiality_promotion: dict[str, Any],
    materiality_promotion_validation: dict[str, Any],
    *,
    expected_year: int = 2026,
) -> dict[str, Any]:
    try:
        _require_upstream_boundary(materiality, "materiality")
        _require_upstream_boundary(materiality_promotion, "materiality_promotion")
        _require_upstream_boundary(materiality_promotion_validation, "materiality_promotion_validation")

        if materiality_promotion_validation.get("status") != "PASS_SHADOW":
            raise RuntimeError("materiality_promotion_independent_validation_not_passed")
        if materiality_promotion_validation.get("materiality_promotion_allowed") is not True:
            raise RuntimeError("materiality_promotion_validation_not_allowed")
        if materiality.get("registration_deadline_materiality_consumed") is not True:
            raise RuntimeError("materiality_deadline_not_consumed")

        materiality_candidate = _single_materiality_candidate(materiality)
        promotion_candidate = _single_materiality_promotion_candidate(materiality_promotion)
        promoted = (materiality_candidate.get("materiality_only_promoted_fields") or {}).get("registration_deadline")
        if not isinstance(promoted, dict):
            raise RuntimeError("materiality_candidate_missing_promoted_deadline")

        deadline = str(materiality.get("registration_deadline") or "")
        if not deadline or deadline != str(materiality_candidate.get("registration_deadline") or ""):
            raise RuntimeError("materiality_deadline_value_mismatch")
        if deadline != str(promotion_candidate.get("value") or ""):
            raise RuntimeError("materiality_vs_promotion_deadline_mismatch")
        if deadline != str(materiality_promotion_validation.get("registration_deadline") or ""):
            raise RuntimeError("materiality_vs_validation_deadline_mismatch")
        if not deadline.startswith(f"{expected_year}-"):
            raise RuntimeError("registration_deadline_year_mismatch")

        upstream_promotion_id = str(materiality.get("registration_deadline_promotion_evidence_id") or "")
        if not upstream_promotion_id:
            raise RuntimeError("materiality_missing_upstream_promotion_evidence_id")
        if upstream_promotion_id != str(materiality_promotion.get("promotion_evidence_id") or ""):
            raise RuntimeError("materiality_vs_promotion_evidence_id_mismatch")
        if upstream_promotion_id != str(materiality_promotion_validation.get("promotion_evidence_id") or ""):
            raise RuntimeError("materiality_vs_validation_promotion_evidence_id_mismatch")
        if upstream_promotion_id != str(promoted.get("promotion_evidence_id") or ""):
            raise RuntimeError("materiality_promoted_field_promotion_evidence_id_mismatch")

        identity_keys = (
            "field_evidence_id",
            "scope_field_evidence_id",
            "source_registration_window_field_evidence_id",
            "document_text_evidence_id",
            "page_text_sha256",
        )
        for key in identity_keys:
            value = str(promoted.get(key) or "")
            if not value:
                raise RuntimeError(f"materiality_promoted_deadline_missing_identity:{key}")
            if value != str(promotion_candidate.get(key) or ""):
                raise RuntimeError(f"materiality_vs_promotion_identity_mismatch:{key}")
            validation_key = "registration_deadline_field_evidence_id" if key == "field_evidence_id" else key
            if value != str(materiality_promotion_validation.get(validation_key) or ""):
                raise RuntimeError(f"materiality_vs_validation_identity_mismatch:{key}")

        supporting = list(promoted.get("supporting_field_evidence_ids") or [])
        if supporting != list(promotion_candidate.get("supporting_field_evidence_ids") or []):
            raise RuntimeError("materiality_vs_promotion_supporting_identity_mismatch")
        if supporting != list(materiality_promotion_validation.get("supporting_field_evidence_ids") or []):
            raise RuntimeError("materiality_vs_validation_supporting_identity_mismatch")
        if len(supporting) != 2 or len(set(str(v) for v in supporting)) != 2:
            raise RuntimeError("materiality_promoted_deadline_supporting_identity_invalid")

        excerpt = _norm(promoted.get("excerpt"))
        if not excerpt or excerpt != _norm(promotion_candidate.get("excerpt")):
            raise RuntimeError("materiality_vs_promotion_excerpt_mismatch")
        if excerpt != _norm(materiality_promotion_validation.get("excerpt")):
            raise RuntimeError("materiality_vs_validation_excerpt_mismatch")
        page_number = int(promoted.get("page_number") or 0)
        if page_number <= 0:
            raise RuntimeError("materiality_promoted_deadline_page_number_invalid")
        if page_number != int(promotion_candidate.get("page_number") or 0):
            raise RuntimeError("materiality_vs_promotion_page_number_mismatch")
        if page_number != int(materiality_promotion_validation.get("page_number") or 0):
            raise RuntimeError("materiality_vs_validation_page_number_mismatch")

        existing_ids = [str(v) for v in materiality_candidate.get("field_evidence_ids") or []]
        if len(existing_ids) != 4 or len(set(existing_ids)) != 4:
            raise RuntimeError("materiality_existing_fact_evidence_identity_invalid")
        deadline_field_evidence_id = str(promoted["field_evidence_id"])
        if deadline_field_evidence_id in existing_ids:
            raise RuntimeError("deadline_already_present_in_fact_kernel_evidence_ids")
        excluded = [str(v) for v in materiality_candidate.get("excluded_unverified_or_non_normalized_fields") or []]
        if "registration_deadline" not in excluded:
            raise RuntimeError("materiality_deadline_not_still_explicitly_excluded")

        fact_promotion_id = _promotion_id(
            str(expected_year),
            deadline,
            upstream_promotion_id,
            deadline_field_evidence_id,
            str(promoted["scope_field_evidence_id"]),
            str(promoted["source_registration_window_field_evidence_id"]),
            str(promoted["document_text_evidence_id"]),
            str(promoted["page_text_sha256"]),
            str(materiality_candidate.get("category") or ""),
            ",".join(existing_ids),
            excerpt,
        )
        candidate = {
            "field": "registration_deadline",
            "value": deadline,
            "normalized_date": True,
            "state": "FACT_KERNEL_FIELD_PROMOTION_VERIFIED_SHADOW",
            "field_evidence_id": deadline_field_evidence_id,
            "upstream_materiality_promotion_evidence_id": upstream_promotion_id,
            "fact_kernel_promotion_evidence_id": fact_promotion_id,
            "scope_field_evidence_id": str(promoted["scope_field_evidence_id"]),
            "source_registration_window_field_evidence_id": str(promoted["source_registration_window_field_evidence_id"]),
            "supporting_field_evidence_ids": supporting,
            "document_text_evidence_id": str(promoted["document_text_evidence_id"]),
            "page_number": page_number,
            "page_text_sha256": str(promoted["page_text_sha256"]),
            "excerpt": excerpt,
            "contest_session_year": expected_year,
            "materiality_category": str(materiality_candidate.get("category") or ""),
            "existing_fact_kernel_field_evidence_ids": existing_ids,
            "material_fact_use": True,
            "fact_kernel_promotion_allowed": True,
            "writer_allowed": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
        }
        return {
            **_base(),
            "state": "FACT_KERNEL_PROMOTION_VERIFIED_SHADOW",
            "reason": "materiality_only_deadline_preserves_exact_independently_validated_evidence_identity_for_fact_kernel_promotion",
            "registration_deadline": deadline,
            "registration_deadline_field_evidence_id": deadline_field_evidence_id,
            "upstream_materiality_promotion_evidence_id": upstream_promotion_id,
            "fact_kernel_promotion_evidence_id": fact_promotion_id,
            "material_fact_use": True,
            "fact_kernel_promotion_allowed": True,
            "promotion_candidate_count": 1,
            "promotion_candidates": [candidate],
            "fabricated_claim_count": 0,
            "truth_rule": (
                "This gate makes the independently validated materiality-only registration deadline eligible for a separate FactKernel composition step only when the exact upstream promotion ID and all supporting evidence identities remain unchanged. "
                "It does not itself alter the FactKernel, create writer/article prose, authorize publication/distribution, or satisfy acceptance."
            ),
        }
    except Exception as exc:
        return _blocked("fact_kernel_deadline_promotion_gate_failed", detail=f"{type(exc).__name__}:{exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a fail-closed ISJ registration-deadline promotion gate from materiality to FactKernel")
    parser.add_argument("--materiality", required=True)
    parser.add_argument("--materiality-promotion", required=True)
    parser.add_argument("--materiality-promotion-validation", required=True)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build_fact_kernel_deadline_promotion(
        json.loads(Path(args.materiality).read_text(encoding="utf-8")),
        json.loads(Path(args.materiality_promotion).read_text(encoding="utf-8")),
        json.loads(Path(args.materiality_promotion_validation).read_text(encoding="utf-8")),
        expected_year=args.year,
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result.get("state"),
        "registration_deadline": result.get("registration_deadline"),
        "fact_kernel_promotion_allowed": result.get("fact_kernel_promotion_allowed", False),
        "writer_allowed": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
