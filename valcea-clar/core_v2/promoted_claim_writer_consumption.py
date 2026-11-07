from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

# Keep the historical deterministic identity namespace during the migration so
# downstream evidence IDs do not change merely because runtime naming changes.
COMPATIBILITY_IDENTITY_PREFIX = "isj-writer-deadline-consumption"
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


def _consumption_id(*parts: str, identity_prefix: str = COMPATIBILITY_IDENTITY_PREFIX) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"{identity_prefix}-{digest[:24]}"


def _base() -> dict[str, Any]:
    return {
        "schema_version": "core-v2-promoted-claim-writer-consumption-shadow.v1",
        "mode": "PROMOTED_CLAIM_WRITER_CONSUMPTION_SHADOW",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "shadow_writer_consumption_allowed": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "article_projection_allowed": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "fabricated_claim_count": 0,
        "canonical_writer_consumption_builder_path": "SOURCE_NEUTRAL_MODULE",
        "canonical_writer_consumption_runtime_facade": False,
        "canonical_writer_consumption_stage": "promoted_claim_writer_consumption",
        "canonical_writer_consumption_artifact": "valcea-core-v2-promoted-claim-writer-consumption.json",
        "compatibility_identity_namespace_retained": True,
        "legacy_module_path_required_for_canonical_runtime": False,
        "source_specific_builder_canonical_producer": False,
        "source_specific_comparator_runtime_dependency": False,
        "source_specific_comparator_execution": "INDEPENDENT_CI_REGRESSION_ONLY",
        "source_specific_builder_retirement_performed": False,
    }


def _blocked(reason: str, detail: str | None = None) -> dict[str, Any]:
    result = {
        **_base(),
        "state": "BLOCKED",
        "reason": reason,
        "consumption_candidate_count": 0,
        "consumption_candidates": [],
    }
    if detail:
        result["detail"] = detail[:500]
    return result


def _require_shadow_boundary(doc: dict[str, Any], label: str) -> None:
    if doc.get("publication_authority") != "NONE":
        raise RuntimeError(f"{label}_publication_boundary_violation")
    if doc.get("acceptance_ready") is not False:
        raise RuntimeError(f"{label}_acceptance_boundary_violation")
    if doc.get("production_writer_ready") is not False:
        raise RuntimeError(f"{label}_production_writer_boundary_violation")
    if doc.get("site_publish_allowed") is not False or doc.get("social_publish_allowed") is not False:
        raise RuntimeError(f"{label}_publication_path_boundary_violation")


def _single_promoted_claim(fact_kernel: dict[str, Any]) -> dict[str, Any]:
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
    if not isinstance(item, dict) or not _norm(item.get("field")):
        raise RuntimeError("promoted_fact_claim_missing")
    return item


def build_promoted_claim_writer_consumption(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    projection: dict[str, Any],
    projection_validation: dict[str, Any],
    *,
    expected_year: int = 2026,
    identity_prefix: str = COMPATIBILITY_IDENTITY_PREFIX,
) -> dict[str, Any]:
    """Bind one independently validated promoted-claim projection to writer consumption.

    Runtime semantics are source-neutral. Historical identity strings and the
    registration_deadline alias are retained only so already-validated downstream
    evidence identities remain stable during the controlled migration.
    """
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
        projection_allowed = projection_validation.get("writer_projection_allowed")
        if projection_allowed is None:
            projection_allowed = projection_validation.get("writer_deadline_projection_allowed")
        if projection_allowed is not True:
            raise RuntimeError("writer_projection_validation_not_allowed")
        if projection_validation.get("article_projection_allowed") is not False:
            raise RuntimeError("projection_validation_article_boundary_violation")
        if int(projection_validation.get("verified_projection_candidate_count") or 0) != 1:
            raise RuntimeError("writer_projection_not_independently_verified")
        if int(projection_validation.get("fabricated_claim_count") or 0) != 0:
            raise RuntimeError("writer_projection_validation_fabricated_claims_nonzero")
        if int(projection_validation.get("tamper_regressions_passed") or 0) < 4:
            raise RuntimeError("writer_projection_tamper_proof_missing")

        promoted = _single_promoted_claim(fact_kernel)
        candidates = projection.get("projection_candidates") or []
        if len(candidates) != 1 or not isinstance(candidates[0], dict):
            raise RuntimeError("writer_projection_candidate_missing")
        candidate = candidates[0]

        projection_id = _norm(projection.get("writer_projection_evidence_id"))
        if not projection_id or _norm(candidate.get("writer_projection_evidence_id")) != projection_id:
            raise RuntimeError("writer_projection_evidence_identity_mismatch")
        if _norm(projection_validation.get("writer_projection_evidence_id")) != projection_id:
            raise RuntimeError("writer_projection_validation_identity_mismatch")

        claim_field = _norm(candidate.get("field"))
        claim_value = _norm(candidate.get("value"))
        claim = _norm(candidate.get("claim"))
        if not claim_field or not claim_value or not claim:
            raise RuntimeError("projection_claim_incomplete")
        if claim_field != _norm(promoted.get("field")) or claim_value != _norm(promoted.get("value")) or claim != _norm(promoted.get("claim")):
            raise RuntimeError("promoted_fact_claim_mismatch")
        if claim_field == "registration_deadline":
            from datetime import date
            if date.fromisoformat(claim_value).year != expected_year:
                raise RuntimeError("registration_deadline_year_mismatch")
            if _norm(projection.get("registration_deadline")) != claim_value:
                raise RuntimeError("registration_deadline_projection_alias_mismatch")
            validation_value = projection_validation.get("value")
            if validation_value is None:
                validation_value = projection_validation.get("registration_deadline")
            if _norm(validation_value) != claim_value:
                raise RuntimeError("registration_deadline_validation_alias_mismatch")

        identities = {key: _norm(candidate.get(key)) for key in IDENTITY_KEYS}
        if any(not value for value in identities.values()):
            raise RuntimeError("writer_projection_identity_missing")
        for key, value in identities.items():
            if _norm(promoted.get(key)) != value:
                raise RuntimeError(f"promoted_fact_{key}_mismatch")

        claim_evidence_ids = [_norm(v) for v in candidate.get("claim_evidence_ids") or [] if _norm(v)]
        if not claim_evidence_ids or claim_evidence_ids != [_norm(v) for v in promoted.get("claim_evidence_ids") or [] if _norm(v)]:
            raise RuntimeError("writer_projection_claim_evidence_mismatch")
        supporting = [_norm(v) for v in candidate.get("supporting_field_evidence_ids") or [] if _norm(v)]
        if supporting != [_norm(v) for v in promoted.get("supporting_field_evidence_ids") or [] if _norm(v)]:
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
            claim_value,
            claim,
            *claim_evidence_ids,
            identities["upstream_materiality_promotion_evidence_id"],
            identities["page_text_sha256"],
            str(page_number),
            excerpt,
            identity_prefix=identity_prefix,
        )
        consumption_candidate = {
            "field": claim_field,
            "value": claim_value,
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
        result = {
            **_base(),
            "state": "WRITER_DEADLINE_CONSUMPTION_VERIFIED_SHADOW",
            "reason": "independently_validated_promoted_claim_projection_is_eligible_for_later_deterministic_shadow_writer_consumption_only",
            "claim_field": claim_field,
            "claim_value": claim_value,
            "writer_projection_evidence_id": projection_id,
            "writer_consumption_evidence_id": consumption_id,
            "shadow_writer_consumption_allowed": True,
            "consumption_candidate_count": 1,
            "consumption_candidates": [consumption_candidate],
            "builder_source_neutral": True,
            "consumption_lineage_verified": True,
            "writer_used_only_validated_projection": True,
            "truth_rule": (
                "This source-neutral gate binds one independently validated promoted-claim projection to a deterministic shadow-writer consumption identity. "
                "It grants no article, site, social, delivery or acceptance authority. Historical identity aliases are compatibility-only."
            ),
        }
        if claim_field == "registration_deadline":
            result["registration_deadline"] = claim_value
        return result
    except Exception as exc:
        return _blocked("promoted_claim_writer_consumption_gate_failed", f"{type(exc).__name__}:{exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build fail-closed source-neutral promoted-claim writer consumption gate")
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--fact-kernel-integrity", required=True)
    parser.add_argument("--projection", required=True)
    parser.add_argument("--projection-validation", required=True)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build_promoted_claim_writer_consumption(
        json.loads(Path(args.fact_kernel).read_text(encoding="utf-8")),
        json.loads(Path(args.fact_kernel_integrity).read_text(encoding="utf-8")),
        json.loads(Path(args.projection).read_text(encoding="utf-8")),
        json.loads(Path(args.projection_validation).read_text(encoding="utf-8")),
        expected_year=args.year,
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result.get("state"),
        "writer_projection_evidence_id": result.get("writer_projection_evidence_id"),
        "writer_consumption_evidence_id": result.get("writer_consumption_evidence_id"),
        "canonical_writer_consumption_builder_path": result.get("canonical_writer_consumption_builder_path"),
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("state") == "WRITER_DEADLINE_CONSUMPTION_VERIFIED_SHADOW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
