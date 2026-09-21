from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import orchestrator
import orchestrator_run86

EXPECTED_PROJECTION_ID = "isj-writer-deadline-projection-d9ae7b38596fc02a6ee7524d"
EXPECTED_CONSUMPTION_ID = "isj-writer-deadline-consumption-de8b3ece2713d4395a0c62d1"
EXPECTED_ARTICLE_CLAIM_ID = "isj-article-deadline-claim-cc6330d494a44bd79c5340d5"
EXPECTED_PROMOTED_CONTRACT_ID = "promoted-claim-e89e691eadfeb5109eacb9fa"

CONSUMPTION_STAGES = (
    "promoted_claim_writer_consumption",
    "promoted_claim_writer_consumption_validation",
)


def _load(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise RuntimeError(f"expected_object:{path}")
    return doc


def _stage_semantics(stage: Any) -> tuple[str, tuple[str, ...], str | None]:
    return (
        str(stage.name),
        tuple(str(token) for token in stage.argv),
        str(stage.output) if stage.output is not None else None,
    )


def _by_name(plan: tuple[Any, ...]) -> dict[str, Any]:
    return {stage.name: stage for stage in plan}


def validate(base: Path) -> dict[str, Any]:
    canonical = orchestrator.bounded_cycle_plan(base, live=False)
    # Immutable RUN81 comparator: orchestrator_run86 captured the validated
    # RUN81 plan function before later wrappers patched module-level plan seams.
    # Calling orchestrator_run81.bounded_cycle_plan here is unsafe because newer
    # wrappers intentionally replace that public symbol for runtime delegation.
    frozen81 = orchestrator_run86._BASE_PLAN(base, live=False)
    owned = {stage.name: stage for stage in orchestrator._owned_consumption_stages(base)}
    canonical_by_name = _by_name(canonical)
    run81_by_name = _by_name(frozen81)

    canonical_names = [stage.name for stage in canonical]
    run81_names = [stage.name for stage in frozen81]
    if len(canonical_names) != 42:
        raise RuntimeError(f"canonical_stage_count_changed:{len(canonical_names)}")
    if canonical_names != run81_names:
        raise RuntimeError("canonical_stage_order_diverged_from_frozen_run81")

    for name in CONSUMPTION_STAGES:
        current = _stage_semantics(canonical_by_name[name])
        direct = _stage_semantics(owned[name])
        baseline = _stage_semantics(run81_by_name[name])
        if current != direct:
            raise RuntimeError(f"canonical_owned_consumption_semantics_drifted:{name}")
        if current != baseline:
            raise RuntimeError(f"consumption_run81_equivalence_failed:{name}")

    consumption_stage = canonical_by_name["promoted_claim_writer_consumption"]
    validation_stage = canonical_by_name["promoted_claim_writer_consumption_validation"]
    required_inputs = (
        "valcea-core-v2-isj-fact-kernel-shadow.json",
        "valcea-core-v2-isj-fact-kernel-integrity-shadow.json",
        "valcea-core-v2-promoted-claim-writer-projection.json",
        "valcea-core-v2-promoted-claim-projection-validation.json",
    )
    consumption_joined = " ".join(consumption_stage.argv)
    validation_joined = " ".join(validation_stage.argv)
    if not all(name in consumption_joined for name in required_inputs):
        raise RuntimeError("consumption_lineage_inputs_changed")
    if not all(name in validation_joined for name in required_inputs):
        raise RuntimeError("consumption_validation_lineage_inputs_changed")
    if "--consumption" not in validation_stage.argv or str(consumption_stage.output) not in validation_stage.argv:
        raise RuntimeError("consumption_validation_binding_changed")
    if "--year" not in consumption_stage.argv or "2026" not in consumption_stage.argv:
        raise RuntimeError("consumption_year_boundary_changed")
    if "--year" not in validation_stage.argv or "2026" not in validation_stage.argv:
        raise RuntimeError("consumption_validation_year_boundary_changed")
    if "--prove-tamper" not in validation_stage.argv:
        raise RuntimeError("consumption_tamper_validation_removed")

    ownership = orchestrator._promoted_claim_consumption_stage_ownership_snapshot(canonical)
    if ownership.get("status") != "PASS_SHADOW":
        raise RuntimeError("consumption_ownership_snapshot_not_pass_shadow")
    if ownership.get("canonical_stage_ownership") != "CORE_V2_ORCHESTRATOR_DIRECT_DEFINITION":
        raise RuntimeError("consumption_ownership_boundary_changed")
    if ownership.get("frozen_run81_consumption_definitions_consumed") is not False:
        raise RuntimeError("frozen_run81_consumption_definition_reintroduced")
    if ownership.get("publication_authority") != "NONE" or ownership.get("acceptance_ready") is not False:
        raise RuntimeError("consumption_ownership_authority_boundary_changed")
    if ownership.get("retirement_eligible") is not False:
        raise RuntimeError("consumption_retirement_boundary_changed")

    projection = _load(base / "valcea-core-v2-promoted-claim-writer-projection.json")
    projection_validation = _load(base / "valcea-core-v2-promoted-claim-projection-validation.json")
    consumption = _load(base / "valcea-core-v2-promoted-claim-writer-consumption.json")
    consumption_validation = _load(base / "valcea-core-v2-promoted-claim-writer-consumption-validation.json")
    article_claim = _load(base / "valcea-core-v2-isj-article-deadline-claim.json")
    article_integrity = _load(base / "valcea-core-v2-isj-article-integrity-shadow.json")
    promoted_contract = _load(base / "valcea-core-v2-isj-promoted-claim-contract.json")

    if projection.get("writer_projection_evidence_id") != EXPECTED_PROJECTION_ID:
        raise RuntimeError("projection_evidence_id_changed")
    if projection_validation.get("writer_projection_evidence_id") != EXPECTED_PROJECTION_ID:
        raise RuntimeError("projection_validation_evidence_id_changed")
    if consumption.get("writer_consumption_evidence_id") != EXPECTED_CONSUMPTION_ID:
        raise RuntimeError("consumption_evidence_id_changed")
    if consumption_validation.get("writer_consumption_evidence_id") != EXPECTED_CONSUMPTION_ID:
        raise RuntimeError("consumption_validation_evidence_id_changed")
    if int(consumption_validation.get("tamper_regressions_passed") or 0) != 4:
        raise RuntimeError("consumption_tamper_regression_count_changed")
    if article_claim.get("article_deadline_claim_evidence_id") != EXPECTED_ARTICLE_CLAIM_ID:
        raise RuntimeError("article_claim_evidence_id_changed")
    if promoted_contract.get("promoted_claim_contract_id") != EXPECTED_PROMOTED_CONTRACT_ID:
        raise RuntimeError("promoted_contract_id_changed")
    if article_integrity.get("status") != "PASS_SHADOW":
        raise RuntimeError("article_integrity_not_pass_shadow")
    if int(article_integrity.get("verified_claim_count") or 0) != 3:
        raise RuntimeError("verified_article_claim_count_changed")
    if int(article_integrity.get("fabricated_claim_count") or 0) != 0:
        raise RuntimeError("fabricated_claim_count_nonzero")

    for label, doc in (
        ("projection", projection),
        ("projection_validation", projection_validation),
        ("consumption", consumption),
        ("consumption_validation", consumption_validation),
        ("article_claim", article_claim),
        ("article_integrity", article_integrity),
        ("promoted_contract", promoted_contract),
    ):
        if doc.get("publication_authority") != "NONE":
            raise RuntimeError(f"{label}_publication_authority_changed")
        if doc.get("acceptance_ready") is not False:
            raise RuntimeError(f"{label}_acceptance_boundary_changed")

    return {
        "schema_version": "core-v2-promoted-claim-consumption-definition-equivalence-ci.v2",
        "status": "PASS_SHADOW",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "canonical_stage_count": 42,
        "canonical_stage_order_matches_frozen_run81": True,
        "consumption_definitions_match_frozen_run81": True,
        "frozen_run81_comparator_source": "orchestrator_run86._BASE_PLAN",
        "frozen_run81_comparator_immutable": True,
        "consumption_lineage_equivalent": True,
        "projection_evidence_id": EXPECTED_PROJECTION_ID,
        "consumption_evidence_id": EXPECTED_CONSUMPTION_ID,
        "article_claim_evidence_id": EXPECTED_ARTICLE_CLAIM_ID,
        "promoted_claim_contract_id": EXPECTED_PROMOTED_CONTRACT_ID,
        "consumption_tamper_regressions_passed": 4,
        "verified_article_claim_count": 3,
        "fabricated_claim_count": 0,
        "retirement_authority": "NONE",
        "truth_rule": (
            "This CI-only regression independently compares the Core v2 promoted-claim consumption pair with the immutable, pre-patch RUN81 plan captured by orchestrator_run86._BASE_PLAN on the same verified workdir. It binds that definition proof to exact evidence identities, the established 4/4 fail-closed consumption tamper proof, downstream article integrity, and explicit no-authority flags. It grants no naming, retirement, publication, delivery, merge, deployment, acceptance or cutover authority."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="CI-only promoted-claim consumption definition equivalence regression")
    parser.add_argument("--base", default="/tmp")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = validate(Path(args.base))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
