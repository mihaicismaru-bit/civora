from __future__ import annotations

from typing import Any

from isj_article_deadline_claim_gate import (
    build_article_deadline_claim_gate as build_retained_article_claim_gate,
)
from validate_isj_article_deadline_claim_gate import (
    project_validated_deadline_claim as project_retained_validated_claim,
    prove_projected_tamper_regressions as prove_retained_projected_tamper_regressions,
    prove_tamper_regressions as prove_retained_tamper_regressions,
    validate as validate_retained_article_claim_gate,
    validate_projected_article as validate_retained_projected_article,
)

RETAINED_GATE_IMPLEMENTATION = "valcea-clar/core_v2/isj_article_deadline_claim_gate.py"
RETAINED_VALIDATOR_IMPLEMENTATION = "valcea-clar/core_v2/validate_isj_article_deadline_claim_gate.py"
RUNTIME_FACADE_MODE = "CORE_V2_SOURCE_NEUTRAL_PROMOTED_CLAIM_ARTICLE_TRUTH_FACADE"


def _require_non_authorizing(doc: dict[str, Any], label: str) -> None:
    if doc.get("publication_authority") != "NONE":
        raise ValueError(f"{label}_publication_boundary_violation")
    if doc.get("acceptance_ready") is not False:
        raise ValueError(f"{label}_acceptance_boundary_violation")
    if doc.get("site_publish_allowed") is not False or doc.get("social_publish_allowed") is not False:
        raise ValueError(f"{label}_publication_path_boundary_violation")
    if int(doc.get("fabricated_claim_count") or 0) != 0:
        raise ValueError(f"{label}_fabricated_claim_count_nonzero")


def build_promoted_claim_article_truth_gate(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    writer_consumption: dict[str, Any],
    writer_consumption_validation: dict[str, Any],
    article_report: dict[str, Any],
) -> dict[str, Any]:
    """Source-neutral facade around the retained deterministic article claim gate.

    During the controlled migration this function returns the retained gate document
    unchanged. The compatibility evidence namespace (including
    ``article_deadline_claim_evidence_id``) is intentionally preserved until a
    separately validated runtime switch. No publication, acceptance, projection,
    deployment or retirement authority is created here.
    """
    result = build_retained_article_claim_gate(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        article_report,
    )
    if not isinstance(result, dict):
        raise TypeError("article_truth_facade_retained_gate_returned_non_object")
    _require_non_authorizing(result, "article_truth_facade_gate")
    if result.get("canonical_article_mutation_allowed") is not False:
        raise ValueError("article_truth_facade_gate_canonical_mutation_boundary_violation")
    if result.get("article_projection_allowed") is not False:
        raise ValueError("article_truth_facade_gate_projection_boundary_violation")
    return result


def validate_promoted_claim_article_truth_gate(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    writer_consumption: dict[str, Any],
    writer_consumption_validation: dict[str, Any],
    article_report: dict[str, Any],
    gate: dict[str, Any],
) -> dict[str, Any]:
    result = validate_retained_article_claim_gate(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        article_report,
        gate,
    )
    if not isinstance(result, dict):
        raise TypeError("article_truth_facade_retained_validation_returned_non_object")
    _require_non_authorizing(result, "article_truth_facade_validation")
    if result.get("canonical_article_mutation_allowed") is not False:
        raise ValueError("article_truth_facade_validation_canonical_mutation_boundary_violation")
    if result.get("article_projection_allowed") is not False:
        raise ValueError("article_truth_facade_validation_projection_boundary_violation")
    return result


def project_promoted_claim_article_shadow(
    article_report: dict[str, Any],
    gate: dict[str, Any],
    validation_summary: dict[str, Any],
) -> dict[str, Any]:
    result = project_retained_validated_claim(article_report, gate, validation_summary)
    if not isinstance(result, dict):
        raise TypeError("article_truth_facade_retained_projection_returned_non_object")
    _require_non_authorizing(result, "article_truth_facade_projected_article")
    if result.get("article_projection_allowed") is not False:
        raise ValueError("article_truth_facade_projected_article_authority_violation")
    return result


def validate_promoted_claim_projected_article(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    writer_consumption: dict[str, Any],
    writer_consumption_validation: dict[str, Any],
    projected_article: dict[str, Any],
    gate: dict[str, Any],
) -> dict[str, Any]:
    result = validate_retained_projected_article(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        projected_article,
        gate,
    )
    if not isinstance(result, dict):
        raise TypeError("article_truth_facade_retained_projected_validation_returned_non_object")
    _require_non_authorizing(result, "article_truth_facade_projected_validation")
    if result.get("article_projection_allowed") is not False:
        raise ValueError("article_truth_facade_projected_validation_authority_violation")
    return result


def prove_promoted_claim_article_truth_tamper_regressions(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    writer_consumption: dict[str, Any],
    writer_consumption_validation: dict[str, Any],
    article_report: dict[str, Any],
    gate: dict[str, Any],
) -> int:
    return prove_retained_tamper_regressions(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        article_report,
        gate,
    )


def prove_promoted_claim_projected_tamper_regressions(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    writer_consumption: dict[str, Any],
    writer_consumption_validation: dict[str, Any],
    projected_article: dict[str, Any],
    gate: dict[str, Any],
) -> int:
    return prove_retained_projected_tamper_regressions(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        projected_article,
        gate,
    )
