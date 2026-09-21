from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import orchestrator
import orchestrator_run70
import orchestrator_run81

EXPECTED_PROJECTION_ID = "isj-writer-deadline-projection-d9ae7b38596fc02a6ee7524d"
EXPECTED_CONSUMPTION_ID = "isj-writer-deadline-consumption-de8b3ece2713d4395a0c62d1"
EXPECTED_ARTICLE_CLAIM_ID = "isj-article-deadline-claim-cc6330d494a44bd79c5340d5"
EXPECTED_PROMOTED_CONTRACT_ID = "promoted-claim-e89e691eadfeb5109eacb9fa"

FACT_STAGES = ("isj_fact_kernel", "isj_fact_kernel_integrity")


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
    frozen81 = orchestrator_run81.bounded_cycle_plan(base, live=False)
    frozen70 = orchestrator_run70.bounded_cycle_plan(base, live=False)
    owned = {stage.name: stage for stage in orchestrator._owned_fact_kernel_stages(base)}
    canonical_by_name = _by_name(canonical)
    run81_by_name = _by_name(frozen81)
    run70_by_name = _by_name(frozen70)

    canonical_names = [stage.name for stage in canonical]
    run81_names = [stage.name for stage in frozen81]
    if len(canonical_names) != 42:
        raise RuntimeError(f"canonical_stage_count_changed:{len(canonical_names)}")
    if canonical_names != run81_names:
        raise RuntimeError("canonical_stage_order_diverged_from_frozen_run81")

    for name in FACT_STAGES:
        current = _stage_semantics(canonical_by_name[name])
        direct = _stage_semantics(owned[name])
        baseline81 = _stage_semantics(run81_by_name[name])
        baseline70 = _stage_semantics(run70_by_name[name])
        if current != direct:
            raise RuntimeError(f"canonical_owned_fact_kernel_semantics_drifted:{name}")
        if current != baseline81:
            raise RuntimeError(f"fact_kernel_run81_equivalence_failed:{name}")
        if current != baseline70:
            raise RuntimeError(f"fact_kernel_run70_equivalence_failed:{name}")

    fact = canonical_by_name["isj_fact_kernel"]
    integrity = canonical_by_name["isj_fact_kernel_integrity"]
    required_fact_inputs = (
        "valcea-core-v2-isj-field-materiality-shadow.json",
        "valcea-core-v2-isj-field-evidence-shadow.json",
        "valcea-core-v2-isj-calendar-field-evidence-shadow.json",
    )
    joined_fact = " ".join(fact.argv)
    if not all(name in joined_fact for name in required_fact_inputs):
        raise RuntimeError("fact_kernel_lineage_inputs_changed")
    if "--fact-kernel" not in integrity.argv or str(fact.output) not in integrity.argv:
        raise RuntimeError("fact_kernel_integrity_lineage_changed")

    ownership = orchestrator._fact_kernel_stage_ownership_snapshot(canonical)
    if ownership.get("status") != "PASS_SHADOW":
        raise RuntimeError("fact_kernel_ownership_snapshot_not_pass_shadow")
    if ownership.get("publication_authority") != "NONE" or ownership.get("acceptance_ready") is not False:
        raise RuntimeError("fact_kernel_ownership_authority_boundary_changed")
    if ownership.get("retirement_eligible") is not False:
        raise RuntimeError("fact_kernel_retirement_boundary_changed")

    projection = _load(base / "valcea-core-v2-promoted-claim-writer-projection.json")
    projection_validation = _load(base / "valcea-core-v2-promoted-claim-projection-validation.json")
    consumption = _load(base / "valcea-core-v2-promoted-claim-writer-consumption.json")
    consumption_validation = _load(base / "valcea-core-v2-promoted-claim-writer-consumption-validation.json")
    article_claim = _load(base / "valcea-core-v2-isj-article-deadline-claim.json")
    article_claim_validation = _load(base / "valcea-core-v2-isj-article-deadline-claim-validation.json")
    article_integrity = _load(base / "valcea-core-v2-isj-article-integrity-shadow.json")
    promoted_contract = _load(base / "valcea-core-v2-isj-promoted-claim-contract.json")
    promoted_contract_validation = _load(base / "valcea-core-v2-isj-promoted-claim-contract-validation.json")

    if projection.get("writer_projection_evidence_id") != EXPECTED_PROJECTION_ID:
        raise RuntimeError("projection_evidence_id_changed")
    if projection_validation.get("writer_projection_evidence_id") != EXPECTED_PROJECTION_ID:
        raise RuntimeError("projection_validation_evidence_id_changed")
    if consumption.get("writer_consumption_evidence_id") != EXPECTED_CONSUMPTION_ID:
        raise RuntimeError("consumption_evidence_id_changed")
    if consumption_validation.get("writer_consumption_evidence_id") != EXPECTED_CONSUMPTION_ID:
        raise RuntimeError("consumption_validation_evidence_id_changed")
    if article_claim.get("article_deadline_claim_evidence_id") != EXPECTED_ARTICLE_CLAIM_ID:
        raise RuntimeError("article_claim_evidence_id_changed")
    if article_claim_validation.get("article_deadline_claim_evidence_id") != EXPECTED_ARTICLE_CLAIM_ID:
        raise RuntimeError("article_claim_validation_evidence_id_changed")
    if promoted_contract.get("promoted_claim_contract_id") != EXPECTED_PROMOTED_CONTRACT_ID:
        raise RuntimeError("promoted_contract_id_changed")
    if promoted_contract_validation.get("promoted_claim_contract_id") != EXPECTED_PROMOTED_CONTRACT_ID:
        raise RuntimeError("promoted_contract_validation_id_changed")

    checks = {
        "projection_tamper": int(projection_validation.get("tamper_regressions_passed") or 0),
        "consumption_tamper": int(consumption_validation.get("tamper_regressions_passed") or 0),
        "article_claim_tamper": int(article_claim_validation.get("tamper_regressions_passed") or 0),
        "article_projected_tamper": int(article_claim_validation.get("projected_tamper_regressions_passed") or 0),
        "promoted_contract_tamper": int(promoted_contract_validation.get("tamper_regressions_passed") or 0),
        "promoted_consumer_tamper": int(promoted_contract_validation.get("consumer_tamper_regressions_passed") or 0),
        "promoted_total_tamper": int(promoted_contract_validation.get("total_tamper_regressions_passed") or 0),
    }
    expected_checks = {
        "projection_tamper": 4,
        "consumption_tamper": 4,
        "article_claim_tamper": 5,
        "article_projected_tamper": 3,
        "promoted_contract_tamper": 4,
        "promoted_consumer_tamper": 5,
        "promoted_total_tamper": 9,
    }
    if checks != expected_checks:
        raise RuntimeError(f"tamper_regression_count_changed:{checks}")

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
        ("article_claim_validation", article_claim_validation),
        ("article_integrity", article_integrity),
        ("promoted_contract", promoted_contract),
        ("promoted_contract_validation", promoted_contract_validation),
    ):
        if doc.get("publication_authority") != "NONE":
            raise RuntimeError(f"{label}_publication_authority_changed")
        if doc.get("acceptance_ready") is not False:
            raise RuntimeError(f"{label}_acceptance_boundary_changed")

    return {
        "schema_version": "core-v2-fact-kernel-definition-equivalence-ci.v1",
        "status": "PASS_SHADOW",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "canonical_stage_count": 42,
        "canonical_stage_order_matches_frozen_run81": True,
        "fact_kernel_definitions_match_frozen_run81": True,
        "fact_kernel_definitions_match_frozen_run70": True,
        "fact_kernel_lineage_equivalent": True,
        "projection_evidence_id": EXPECTED_PROJECTION_ID,
        "consumption_evidence_id": EXPECTED_CONSUMPTION_ID,
        "article_claim_evidence_id": EXPECTED_ARTICLE_CLAIM_ID,
        "promoted_claim_contract_id": EXPECTED_PROMOTED_CONTRACT_ID,
        "tamper_regressions": checks,
        "verified_article_claim_count": 3,
        "fabricated_claim_count": 0,
        "retirement_authority": "NONE",
        "truth_rule": (
            "This CI-only regression compares the Core v2 fact-kernel definitions with the frozen RUN81 and RUN70 semantics on the same workdir, "
            "then binds that definition proof to deterministic downstream evidence identities, all existing tamper proofs and the independent article-integrity result. "
            "It grants no naming, retirement, publication, delivery, merge, deployment, acceptance or cutover authority."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="CI-only fact-kernel definition equivalence and downstream truth regression")
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
