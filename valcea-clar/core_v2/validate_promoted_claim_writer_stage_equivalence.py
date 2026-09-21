from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import orchestrator
import orchestrator_run81

EXPECTED_PROJECTION_ID = "isj-writer-deadline-projection-d9ae7b38596fc02a6ee7524d"
EXPECTED_CONSUMPTION_ID = "isj-writer-deadline-consumption-de8b3ece2713d4395a0c62d1"
WRITER_STAGE = "promoted_claim_writer"
WRITER_MODULE = "valcea-clar/core_v2/promoted_claim_writer.py"
WRITER_ARTIFACT = "valcea-core-v2-isj-article-shadow.json"


def _stage_semantics(stage: Any) -> tuple[str, tuple[str, ...], str | None]:
    return (
        str(stage.name),
        tuple(str(token) for token in stage.argv),
        str(stage.output) if stage.output is not None else None,
    )


def _by_name(plan: tuple[Any, ...]) -> dict[str, Any]:
    return {stage.name: stage for stage in plan}


def validate(
    base: Path,
    article: dict[str, Any],
    writer_consumption: dict[str, Any],
    writer_consumption_validation: dict[str, Any],
) -> dict[str, Any]:
    canonical = orchestrator.bounded_cycle_plan(base, live=False)
    frozen81 = orchestrator_run81.bounded_cycle_plan(base, live=False)
    canonical_by_name = _by_name(canonical)
    run81_by_name = _by_name(frozen81)

    canonical_names = [stage.name for stage in canonical]
    run81_names = [stage.name for stage in frozen81]
    if len(canonical_names) != 42:
        raise RuntimeError(f"canonical_stage_count_changed:{len(canonical_names)}")
    if canonical_names != run81_names:
        raise RuntimeError("canonical_stage_order_diverged_from_frozen_run81")

    writer = canonical_by_name[WRITER_STAGE]
    baseline = run81_by_name[WRITER_STAGE]
    direct = orchestrator._owned_writer_stage(base)
    if _stage_semantics(writer) != _stage_semantics(direct):
        raise RuntimeError("canonical_owned_writer_stage_semantics_drifted")
    if _stage_semantics(writer) != _stage_semantics(baseline):
        raise RuntimeError("promoted_claim_writer_run81_equivalence_failed")
    if len(writer.argv) < 2 or writer.argv[1] != WRITER_MODULE:
        raise RuntimeError("promoted_claim_writer_module_changed")
    if writer.output is None or writer.output.name != WRITER_ARTIFACT:
        raise RuntimeError("promoted_claim_writer_output_changed")

    writer_index = canonical_names.index(WRITER_STAGE)
    if canonical_names[writer_index - 1] != "promoted_claim_writer_consumption_validation":
        raise RuntimeError("promoted_claim_writer_upstream_position_changed")
    if canonical_names[writer_index + 1] != "isj_article_deadline_claim_gate":
        raise RuntimeError("promoted_claim_writer_downstream_position_changed")

    required_inputs = (
        "valcea-core-v2-isj-fact-kernel-shadow.json",
        "valcea-core-v2-isj-fact-kernel-integrity-shadow.json",
        "valcea-core-v2-promoted-claim-writer-consumption.json",
        "valcea-core-v2-promoted-claim-writer-consumption-validation.json",
    )
    joined = " ".join(writer.argv)
    if not all(name in joined for name in required_inputs):
        raise RuntimeError("promoted_claim_writer_lineage_inputs_changed")
    if "--writer-consumption" not in writer.argv or "--writer-consumption-validation" not in writer.argv:
        raise RuntimeError("promoted_claim_writer_explicit_consumption_binding_removed")

    for name in (
        "isj_article_deadline_claim_gate",
        "isj_article_deadline_claim_validation",
        "isj_article_integrity",
    ):
        if _stage_semantics(canonical_by_name[name]) != _stage_semantics(run81_by_name[name]):
            raise RuntimeError(f"writer_downstream_stage_semantics_diverged_from_run81:{name}")

    ownership = orchestrator._writer_stage_ownership_snapshot(canonical)
    if ownership.get("status") != "PASS_SHADOW":
        raise RuntimeError("writer_stage_ownership_not_pass_shadow")
    if ownership.get("canonical_stage_ownership") != "CORE_V2_ORCHESTRATOR_DIRECT_DEFINITION":
        raise RuntimeError("writer_stage_ownership_boundary_changed")
    if ownership.get("frozen_run81_writer_definition_consumed") is not False:
        raise RuntimeError("frozen_run81_writer_definition_reintroduced")
    if ownership.get("source_neutral_writer_facade_retained") is not True:
        raise RuntimeError("source_neutral_writer_facade_not_retained")
    if ownership.get("retained_writer_implementation_retirement_eligible") is not False:
        raise RuntimeError("retained_writer_implementation_retirement_boundary_changed")
    if ownership.get("publication_authority") != "NONE" or ownership.get("acceptance_ready") is not False:
        raise RuntimeError("writer_stage_authority_boundary_changed")
    if ownership.get("retirement_eligible") is not False:
        raise RuntimeError("writer_stage_retirement_boundary_changed")

    if writer_consumption.get("writer_projection_evidence_id") != EXPECTED_PROJECTION_ID:
        raise RuntimeError("writer_projection_evidence_id_changed")
    if writer_consumption.get("writer_consumption_evidence_id") != EXPECTED_CONSUMPTION_ID:
        raise RuntimeError("writer_consumption_evidence_id_changed")
    if writer_consumption_validation.get("writer_projection_evidence_id") != EXPECTED_PROJECTION_ID:
        raise RuntimeError("writer_projection_validation_evidence_id_changed")
    if writer_consumption_validation.get("writer_consumption_evidence_id") != EXPECTED_CONSUMPTION_ID:
        raise RuntimeError("writer_consumption_validation_evidence_id_changed")
    if int(writer_consumption_validation.get("tamper_regressions_passed") or 0) != 4:
        raise RuntimeError("writer_consumption_tamper_regression_count_changed")

    if article.get("state") != "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY":
        raise RuntimeError("writer_article_state_changed")
    if article.get("shadow_writer_executed") is not True:
        raise RuntimeError("writer_shadow_execution_flag_changed")
    if int(article.get("article_count") or 0) != 1:
        raise RuntimeError("writer_article_count_changed")
    if article.get("writer_consumes_deadline_projection") is not True:
        raise RuntimeError("writer_projection_consumption_semantics_changed")
    if int(article.get("rendered_promoted_claim_count") or 0) != 1:
        raise RuntimeError("writer_rendered_promoted_claim_count_changed")
    if article.get("article_contains_registration_deadline") is not True:
        raise RuntimeError("writer_promoted_claim_rendering_changed")
    if int(article.get("fabricated_claim_count") or 0) != 0:
        raise RuntimeError("writer_fabricated_claim_count_nonzero")
    if article.get("publication_authority") != "NONE" or article.get("acceptance_ready") is not False:
        raise RuntimeError("writer_article_authority_boundary_changed")
    if article.get("production_writer_ready") is not False:
        raise RuntimeError("writer_production_readiness_boundary_changed")
    if article.get("site_publish_allowed") is not False or article.get("social_publish_allowed") is not False:
        raise RuntimeError("writer_publication_path_boundary_changed")

    articles = article.get("articles") or []
    if len(articles) != 1 or not isinstance(articles[0], dict):
        raise RuntimeError("writer_article_package_cardinality_changed")
    package = articles[0].get("article_package") or {}
    claims = package.get("claims") or []
    pending = package.get("rendered_promoted_claims_pending_integrity") or []
    if len(claims) != 2:
        raise RuntimeError("writer_base_claim_cardinality_changed")
    if len(pending) != 1 or not isinstance(pending[0], dict):
        raise RuntimeError("writer_pending_promoted_claim_cardinality_changed")
    pending_claim = pending[0]
    if pending_claim.get("writer_projection_evidence_id") != EXPECTED_PROJECTION_ID:
        raise RuntimeError("writer_pending_projection_evidence_id_changed")
    if pending_claim.get("writer_consumption_evidence_id") != EXPECTED_CONSUMPTION_ID:
        raise RuntimeError("writer_pending_consumption_evidence_id_changed")

    result = {
        "schema_version": "core-v2-promoted-claim-writer-stage-definition-equivalence-ci.v1",
        "status": "PASS_SHADOW",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "canonical_stage_count": 42,
        "canonical_stage_order_matches_frozen_run81": True,
        "writer_stage_definition_matches_frozen_run81": True,
        "writer_stage_direct_definition_matches_canonical": True,
        "writer_stage_position_matches_frozen_run81": True,
        "writer_lineage_equivalent": True,
        "downstream_article_truth_stage_definitions_match_frozen_run81": True,
        "writer_output_semantics_preserved": True,
        "projection_evidence_id": EXPECTED_PROJECTION_ID,
        "consumption_evidence_id": EXPECTED_CONSUMPTION_ID,
        "consumption_tamper_regressions_passed": 4,
        "base_article_claim_count": 2,
        "pending_promoted_claim_count": 1,
        "fabricated_claim_count": 0,
        "retirement_authority": "NONE",
        "truth_rule": (
            "CI-only PASS_SHADOW requires the directly owned promoted_claim_writer stage to remain exactly equivalent to frozen RUN81 in stage name, argv, output and 42-stage position, preserve explicit FactKernel/writer-consumption lineage, preserve downstream article-truth stage definitions, stable evidence identities and writer output semantics, and remain fail-closed for publication, acceptance and retirement."
        ),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result
