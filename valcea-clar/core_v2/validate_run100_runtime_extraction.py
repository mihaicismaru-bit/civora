from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import orchestrator
import orchestrator_run86


EXTRACTED_STAGE = "isj_promoted_claim_contract_validation"
EXPECTED_PROJECTION_ID = "isj-writer-deadline-projection-d9ae7b38596fc02a6ee7524d"
EXPECTED_CONSUMPTION_ID = "isj-writer-deadline-consumption-de8b3ece2713d4395a0c62d1"
EXPECTED_ARTICLE_CLAIM_ID = "isj-article-deadline-claim-cc6330d494a44bd79c5340d5"
EXPECTED_PROMOTED_CONTRACT_ID = "promoted-claim-e89e691eadfeb5109eacb9fa"


def _load(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise RuntimeError(f"expected_object:{path}")
    return doc


def validate(base: Path) -> dict[str, Any]:
    canonical = orchestrator.bounded_cycle_plan(base, live=False)
    frozen81 = orchestrator_run86._BASE_PLAN(base, live=False)
    canonical_names = [stage.name for stage in canonical]
    frozen_names = [stage.name for stage in frozen81]
    expected_names = [name for name in frozen_names if name != EXTRACTED_STAGE]

    if len(frozen81) != 42:
        raise RuntimeError(f"frozen_run81_stage_count_changed:{len(frozen81)}")
    if len(canonical) != 41:
        raise RuntimeError(f"canonical_stage_count_changed:{len(canonical)}")
    if canonical_names != expected_names:
        raise RuntimeError("canonical_stage_order_not_frozen_run81_minus_ci_only_validation")
    if EXTRACTED_STAGE in canonical_names:
        raise RuntimeError("ci_only_validation_stage_leaked_into_runtime")
    if "core_v2_external_audit" in canonical_names:
        raise RuntimeError("external_auditor_inserted_in_extraction_increment")
    if canonical_names[-1] != "shadow_site_package":
        raise RuntimeError("canonical_terminal_stage_changed")

    joined = "\n".join(" ".join(stage.argv) for stage in canonical)
    if "valcea-core-v2-isj-promoted-claim-contract-validation.json" in joined:
        raise RuntimeError("ci_only_validation_artifact_consumed_by_runtime")
    if "validate_isj_promoted_claim_contract_runtime.py" in joined:
        raise RuntimeError("ci_only_validation_module_consumed_by_runtime")

    ownership_reports = {
        "fact_kernel": orchestrator._fact_kernel_stage_ownership_snapshot(canonical),
        "projection": orchestrator._promoted_claim_projection_stage_ownership_snapshot(canonical),
        "consumption": orchestrator._promoted_claim_consumption_stage_ownership_snapshot(canonical),
        "writer": orchestrator._writer_stage_ownership_snapshot(canonical),
        "article_truth": orchestrator._article_truth_stage_ownership_snapshot(canonical),
        "article_integrity": orchestrator._article_integrity_stage_ownership_snapshot(canonical),
        "promoted_contract": orchestrator._promoted_claim_contract_stage_ownership_snapshot(canonical),
    }
    for label, report in ownership_reports.items():
        if report.get("status") != "PASS_SHADOW":
            raise RuntimeError(f"ownership_snapshot_not_pass_shadow:{label}")
        if report.get("publication_authority") != "NONE" or report.get("acceptance_ready") is not False:
            raise RuntimeError(f"ownership_authority_boundary_changed:{label}")
    if ownership_reports["promoted_contract"].get("runtime_extraction_performed") is not True:
        raise RuntimeError("contract_validation_runtime_extraction_not_recorded")
    if ownership_reports["promoted_contract"].get("external_auditor_inserted") is not False:
        raise RuntimeError("external_auditor_boundary_changed")

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
        raise RuntimeError("ci_only_promoted_contract_validation_id_changed")

    tamper = {
        "projection": int(projection_validation.get("tamper_regressions_passed") or 0),
        "consumption": int(consumption_validation.get("tamper_regressions_passed") or 0),
        "article_claim": int(article_claim_validation.get("tamper_regressions_passed") or 0),
        "article_projected": int(article_claim_validation.get("projected_tamper_regressions_passed") or 0),
        "promoted_contract": int(promoted_contract_validation.get("tamper_regressions_passed") or 0),
        "promoted_consumer": int(promoted_contract_validation.get("consumer_tamper_regressions_passed") or 0),
        "promoted_total": int(promoted_contract_validation.get("total_tamper_regressions_passed") or 0),
    }
    expected_tamper = {
        "projection": 4,
        "consumption": 4,
        "article_claim": 5,
        "article_projected": 3,
        "promoted_contract": 4,
        "promoted_consumer": 5,
        "promoted_total": 9,
    }
    if tamper != expected_tamper:
        raise RuntimeError(f"tamper_regression_count_changed:{tamper}")

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
        ("promoted_contract_validation_ci_only", promoted_contract_validation),
    ):
        if doc.get("publication_authority") != "NONE" or doc.get("acceptance_ready") is not False:
            raise RuntimeError(f"artifact_authority_boundary_changed:{label}")

    return {
        "schema_version": "core-v2-run100-runtime-extraction-equivalence-ci.v1",
        "status": "PASS_SHADOW",
        "canonical_stage_count": 41,
        "frozen_reference_stage_count": 42,
        "canonical_stage_order_equals_frozen_run81_minus_ci_only_validation": True,
        "extracted_stage": EXTRACTED_STAGE,
        "runtime_validation_artifact_reference_count": 0,
        "runtime_extraction_performed": True,
        "external_auditor_inserted": False,
        "terminal_stage": canonical_names[-1],
        "promoted_claim_contract_id": EXPECTED_PROMOTED_CONTRACT_ID,
        "article_claim_evidence_id": EXPECTED_ARTICLE_CLAIM_ID,
        "writer_projection_evidence_id": EXPECTED_PROJECTION_ID,
        "writer_consumption_evidence_id": EXPECTED_CONSUMPTION_ID,
        "tamper_regressions": tamper,
        "verified_article_claim_count": 3,
        "fabricated_claim_count": 0,
        "ownership_snapshots": {key: value.get("status") for key, value in ownership_reports.items()},
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "cutover_authority": "NONE",
        "retirement_authority": "NONE",
        "truth_rule": (
            "The 41-stage canonical runtime is exactly the validated RUN81-order surface minus the redundant promoted-claim "
            "contract validation stage. That validator executes only in CI after the runtime, preserving all established "
            "evidence identities and fail-closed regressions. No external auditor is inserted and no publication, acceptance, "
            "cutover or retirement authority is granted."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate RUN100 41-stage Core v2 runtime extraction equivalence")
    parser.add_argument("--base", default="/tmp")
    parser.add_argument("--output", default="/tmp/valcea-core-v2-run100-runtime-extraction-equivalence.json")
    args = parser.parse_args()
    report = validate(Path(args.base))
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
