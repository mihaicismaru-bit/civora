from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import orchestrator
import orchestrator_run86

EXPECTED_PROJECTION_ID = "isj-writer-deadline-projection-d9ae7b38596fc02a6ee7524d"
EXPECTED_CONSUMPTION_ID = "isj-writer-deadline-consumption-de8b3ece2713d4395a0c62d1"
WRITER_STAGE = "promoted_claim_writer"
WRITER_MODULE = "valcea-clar/core_v2/promoted_claim_writer.py"
WRITER_ARTIFACT = "valcea-core-v2-isj-article-shadow.json"
EXTRACTED_STAGE = "isj_promoted_claim_contract_validation"


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
    frozen81 = orchestrator_run86._BASE_PLAN(base, live=False)
    canonical_by_name = _by_name(canonical)
    frozen_by_name = _by_name(frozen81)

    canonical_names = [stage.name for stage in canonical]
    frozen_names = [stage.name for stage in frozen81]
    expected_names = [name for name in frozen_names if name != EXTRACTED_STAGE]
    if len(canonical_names) != 41:
        raise RuntimeError(f"canonical_stage_count_changed:{len(canonical_names)}")
    if len(frozen_names) != 42:
        raise RuntimeError(f"frozen_run81_stage_count_changed:{len(frozen_names)}")
    if canonical_names != expected_names:
        raise RuntimeError("canonical_stage_order_not_frozen_run81_minus_ci_only_validation")

    writer = canonical_by_name[WRITER_STAGE]
    baseline = frozen_by_name[WRITER_STAGE]
    direct = orchestrator._owned_writer_stage(base)
    if _stage_semantics(writer) != _stage_semantics(direct):
        raise RuntimeError("canonical_owned_writer_stage_semantics_drifted")
    if _stage_semantics(writer) != _stage_semantics(baseline):
        raise RuntimeError("promoted_claim_writer_frozen_run81_equivalence_failed")
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

    # The downstream article stages have intentionally migrated to source-neutral
    # facades, so compare their preserved names/artifacts/order rather than lying
    # that their module argv is byte-identical to frozen RUN81.
    gate = canonical_by_name["isj_article_deadline_claim_gate"]
    validation = canonical_by_name["isj_article_deadline_claim_validation"]
    integrity = canonical_by_name["isj_article_integrity"]
    if gate.argv[1] != "valcea-clar/core_v2/promoted_claim_article_truth.py" or gate.argv[2:4] != ("--mode", "gate"):
        raise RuntimeError("writer_downstream_gate_source_neutral_definition_changed")
    if validation.argv[1] != "valcea-clar/core_v2/promoted_claim_article_truth.py" or validation.argv[2:4] != ("--mode", "validate"):
        raise RuntimeError("writer_downstream_validation_source_neutral_definition_changed")
    if integrity.argv[1] != "valcea-clar/core_v2/promoted_claim_article_integrity.py":
        raise RuntimeError("writer_downstream_integrity_source_neutral_definition_changed")
    if gate.output is None or gate.output.name != "valcea-core-v2-isj-article-deadline-claim.json":
        raise RuntimeError("writer_downstream_gate_artifact_changed")
    if validation.output is None or validation.output.name != "valcea-core-v2-isj-article-deadline-claim-validation.json":
        raise RuntimeError("writer_downstream_validation_artifact_changed")
    if integrity.output is None or integrity.output.name != "valcea-core-v2-isj-article-integrity-shadow.json":
        raise RuntimeError("writer_downstream_integrity_artifact_changed")

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
    if article.get("article_contains_registration_deadline") is not False:
        raise RuntimeError("writer_pre_gate_article_claim_boundary_changed")
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
    if package.get("article_contains_registration_deadline") is not False:
        raise RuntimeError("writer_package_pre_gate_article_claim_boundary_changed")
    if len(pending) != 1 or not isinstance(pending[0], dict):
        raise RuntimeError("writer_pending_promoted_claim_cardinality_changed")
    pending_claim = pending[0]
    if pending_claim.get("field") != "registration_deadline":
        raise RuntimeError("writer_pending_promoted_claim_field_changed")
    if pending_claim.get("state") != "WRITER_RENDERED_SHADOW_PENDING_ARTICLE_CLAIM_INTEGRITY":
        raise RuntimeError("writer_pending_promoted_claim_state_changed")
    if pending_claim.get("publication_authority") != "NONE" or pending_claim.get("article_projection_allowed") is not False:
        raise RuntimeError("writer_pending_promoted_claim_authority_changed")
    if pending_claim.get("writer_projection_evidence_id") != EXPECTED_PROJECTION_ID:
        raise RuntimeError("writer_pending_projection_evidence_id_changed")
    if pending_claim.get("writer_consumption_evidence_id") != EXPECTED_CONSUMPTION_ID:
        raise RuntimeError("writer_pending_consumption_evidence_id_changed")

    result = {
        "schema_version": "core-v2-promoted-claim-writer-stage-definition-equivalence-ci.v3",
        "status": "PASS_SHADOW",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "canonical_stage_count": 41,
        "frozen_reference_stage_count": 42,
        "canonical_stage_order_matches_frozen_run81_minus_ci_only_validation": True,
        "writer_stage_definition_matches_frozen_run81": True,
        "writer_stage_direct_definition_matches_canonical": True,
        "writer_stage_position_preserved": True,
        "writer_lineage_equivalent": True,
        "downstream_article_truth_source_neutral_boundaries_preserved": True,
        "writer_pre_gate_semantics_preserved": True,
        "writer_output_semantics_preserved": True,
        "projection_evidence_id": EXPECTED_PROJECTION_ID,
        "consumption_evidence_id": EXPECTED_CONSUMPTION_ID,
        "consumption_tamper_regressions_passed": 4,
        "base_article_claim_count": 2,
        "pending_promoted_claim_count": 1,
        "canonical_article_contains_registration_deadline_pre_gate": False,
        "fabricated_claim_count": 0,
        "retirement_authority": "NONE",
        "truth_rule": (
            "CI-only PASS_SHADOW compares the canonical writer to the immutable frozen RUN81 writer definition while "
            "recognizing the controlled 41-stage extraction and the separately validated source-neutral article-truth/integrity "
            "facades. It preserves exact writer lineage/evidence and the fail-closed pre-claim-gate boundary without pretending "
            "that intentionally migrated downstream module argv is still byte-identical to RUN81. No publication, acceptance, "
            "cutover or retirement authority is granted."
        ),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result
