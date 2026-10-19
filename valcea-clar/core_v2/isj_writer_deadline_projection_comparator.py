from __future__ import annotations

import hashlib
from datetime import date
from typing import Any


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _romanian_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    months = (
        "ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
        "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie",
    )
    return f"{parsed.day} {months[parsed.month - 1]} {parsed.year}"


def _projection_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"isj-writer-deadline-projection-{digest[:24]}"


def _boundary(doc: dict[str, Any], label: str) -> None:
    if doc.get("publication_authority") != "NONE":
        raise ValueError(f"{label}_publication_authority_violation")
    if doc.get("acceptance_ready") is not False:
        raise ValueError(f"{label}_acceptance_boundary_violation")
    if doc.get("site_publish_allowed") is not False or doc.get("social_publish_allowed") is not False:
        raise ValueError(f"{label}_publication_path_boundary_violation")
    if doc.get("production_writer_ready") is not False:
        raise ValueError(f"{label}_production_writer_boundary_violation")


def compare_source_specific_projection(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    projection: dict[str, Any],
    *,
    expected_year: int = 2026,
) -> dict[str, Any]:
    """Independent compatibility comparator for the retiring ISJ-specific builder.

    This module deliberately does not import the source-neutral builder. It rebuilds
    the historical registration-deadline identity rules and verifies that the new
    canonical producer preserves the exact evidence and authority boundary.
    """
    base = {
        "schema_version": "1.0",
        "mode": "ISJ_WRITER_DEADLINE_PROJECTION_COMPARATOR_SHADOW",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "fabricated_claim_count": 0,
    }
    try:
        for label, doc in (("fact_kernel", fact_kernel), ("fact_integrity", fact_integrity), ("projection", projection)):
            _boundary(doc, label)
        if fact_integrity.get("status") != "PASS_SHADOW" or fact_integrity.get("fact_kernel_integrity_verified") is not True:
            raise ValueError("fact_kernel_integrity_not_passed")
        if int(fact_integrity.get("fabricated_claim_count") or 0) != 0:
            raise ValueError("fact_kernel_integrity_fabricated_claims_nonzero")
        if int(fact_integrity.get("promoted_fact_verified_count") or 0) != 1:
            raise ValueError("promoted_fact_not_independently_verified")

        kernels = fact_kernel.get("kernels") or []
        if len(kernels) != 1 or not isinstance(kernels[0], dict):
            raise ValueError("expected_one_fact_kernel")
        row = kernels[0]
        promoted_rows = row.get("promoted_fact_claims") or []
        if len(promoted_rows) != 1 or not isinstance(promoted_rows[0], dict):
            raise ValueError("expected_one_promoted_fact_claim")
        promoted = promoted_rows[0]
        if promoted.get("field") != "registration_deadline":
            raise ValueError("promoted_fact_field_mismatch")
        deadline = str(promoted.get("value") or "")
        parsed = date.fromisoformat(deadline)
        if parsed.year != expected_year:
            raise ValueError("deadline_year_mismatch")
        claim = _norm(promoted.get("claim"))
        expected_claim = (
            f"Calendarul oficial verificat pentru sesiunea {expected_year} indică data de "
            f"{_romanian_date(deadline)} ca termen-limită al perioadei de înscriere."
        )
        if claim != expected_claim:
            raise ValueError("promoted_fact_claim_text_mismatch")

        identity_keys = (
            "field_evidence_id", "scope_field_evidence_id", "source_registration_window_field_evidence_id",
            "document_text_evidence_id", "upstream_materiality_promotion_evidence_id",
            "fact_kernel_promotion_evidence_id", "page_text_sha256",
        )
        identities = {key: str(promoted.get(key) or "") for key in identity_keys}
        if any(not value for value in identities.values()):
            raise ValueError("promoted_fact_identity_missing")
        supporting = [str(v) for v in promoted.get("supporting_field_evidence_ids") or []]
        expected_supporting = [identities["scope_field_evidence_id"], identities["source_registration_window_field_evidence_id"]]
        if supporting != expected_supporting:
            raise ValueError("supporting_evidence_identity_mismatch")
        claim_evidence = [str(v) for v in promoted.get("claim_evidence_ids") or []]
        expected_claim_evidence = [
            identities["field_evidence_id"], identities["scope_field_evidence_id"],
            identities["source_registration_window_field_evidence_id"], identities["document_text_evidence_id"],
            identities["fact_kernel_promotion_evidence_id"],
        ]
        if claim_evidence != expected_claim_evidence:
            raise ValueError("claim_evidence_binding_mismatch")
        page_number = int(promoted.get("page_number") or 0)
        excerpt = _norm(promoted.get("excerpt"))
        if page_number <= 0 or not excerpt:
            raise ValueError("document_evidence_location_missing")

        expected_projection_id = _projection_id(
            str(expected_year), deadline, claim, *expected_claim_evidence,
            identities["upstream_materiality_promotion_evidence_id"], identities["page_text_sha256"],
            str(page_number), excerpt,
        )
        if projection.get("state") != "WRITER_PROJECTION_VERIFIED_SHADOW":
            raise ValueError("projection_not_verified_shadow")
        if projection.get("writer_projection_evidence_id") != expected_projection_id:
            raise ValueError("projection_identity_mismatch")
        if projection.get("writer_deadline_projection_allowed") is not True:
            raise ValueError("projection_not_allowed")
        if projection.get("writer_allowed") is not False or projection.get("article_projection_allowed") is not False:
            raise ValueError("projection_authority_boundary_violation")
        candidates = projection.get("projection_candidates") or []
        if len(candidates) != 1 or not isinstance(candidates[0], dict):
            raise ValueError("projection_candidate_missing")
        candidate = candidates[0]
        expected = {
            "field": "registration_deadline", "value": deadline, "claim": claim,
            **identities, "supporting_field_evidence_ids": supporting,
            "claim_evidence_ids": expected_claim_evidence, "page_number": page_number,
            "excerpt": excerpt, "writer_projection_evidence_id": expected_projection_id,
        }
        for key, value in expected.items():
            actual = candidate.get(key)
            if key == "claim":
                actual = _norm(actual)
            if actual != value:
                raise ValueError(f"projection_candidate_lineage_mismatch:{key}")
        if candidate.get("writer_deadline_projection_allowed") is not True:
            raise ValueError("projection_candidate_not_allowed")
        if candidate.get("writer_allowed") is not False or candidate.get("article_projection_allowed") is not False:
            raise ValueError("projection_candidate_authority_boundary_violation")

        return {
            **base,
            "status": "PASS_SHADOW",
            "state": "ISJ_SOURCE_SPECIFIC_COMPARATOR_EQUIVALENT_SHADOW",
            "registration_deadline": deadline,
            "writer_projection_evidence_id": expected_projection_id,
            "source_specific_identity_equivalent": True,
            "source_specific_lineage_equivalent": True,
            "source_specific_authority_flags_equivalent": True,
            "retirement_performed": False,
            "truth_rule": "This source-specific comparator is an independent regression guard only. It grants no publication or acceptance authority and is not the canonical writer-projection producer.",
        }
    except Exception as exc:
        return {
            **base,
            "status": "BLOCKED",
            "state": "BLOCKED",
            "reason": "source_specific_writer_projection_comparison_failed",
            "detail": f"{type(exc).__name__}:{exc}"[:500],
            "source_specific_identity_equivalent": False,
            "source_specific_lineage_equivalent": False,
            "source_specific_authority_flags_equivalent": False,
            "retirement_performed": False,
        }
