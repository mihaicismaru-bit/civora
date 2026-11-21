from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from orchestrator import bounded_cycle_plan, _owned_promoted_claim_contract_stages


STAGE_NAME = "isj_promoted_claim_contract_validation"
CONTRACT_STAGE = "isj_promoted_claim_contract"
EXPECTED_MODULE = "valcea-clar/core_v2/validate_isj_promoted_claim_contract_runtime.py"
EXPECTED_OUTPUT = "valcea-core-v2-isj-promoted-claim-contract-validation.json"
EXPECTED_CONTRACT_OUTPUT = "valcea-core-v2-isj-promoted-claim-contract.json"
EXPECTED_TAMPER = 4
EXPECTED_CONSUMER_TAMPER = 5
EXPECTED_TOTAL_TAMPER = 9


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected_object:{path}")
    return value


def _output_name(stage: Any) -> str | None:
    return stage.output.name if stage.output is not None else None


def _replace_output(argv: tuple[str, ...], output: Path) -> list[str]:
    values = list(argv)
    try:
        index = values.index("--output")
    except ValueError as exc:
        raise RuntimeError("ci_only_validation_output_flag_missing") from exc
    if index + 1 >= len(values):
        raise RuntimeError("ci_only_validation_output_value_missing")
    values[index + 1] = str(output)
    return values


def _identity_snapshot(doc: dict[str, Any]) -> dict[str, Any]:
    consumer = doc.get("source_neutral_consumer")
    claim = consumer.get("claim") if isinstance(consumer, dict) else None
    if not isinstance(claim, dict):
        claim = {}
    return {
        "promoted_claim_contract_id": doc.get("promoted_claim_contract_id"),
        "promoted_claim_consumer_id": doc.get("promoted_claim_consumer_id"),
        "article_claim_evidence_id": claim.get("article_claim_evidence_id"),
        "document_evidence_id": claim.get("document_evidence_id"),
        "fact_kernel_promotion_evidence_id": claim.get("fact_kernel_promotion_evidence_id"),
        "writer_projection_evidence_id": claim.get("writer_projection_evidence_id"),
        "writer_consumption_evidence_id": claim.get("writer_consumption_evidence_id"),
    }


def validate(base: Path, repo: Path) -> dict[str, Any]:
    plan = bounded_cycle_plan(base, live=False)
    if len(plan) != 41:
        raise RuntimeError(f"canonical_stage_count_changed:{len(plan)}")
    names = [stage.name for stage in plan]
    if STAGE_NAME in names:
        raise RuntimeError("ci_only_validation_stage_still_present_in_runtime")
    if names.count(CONTRACT_STAGE) != 1:
        raise RuntimeError("canonical_contract_stage_count_changed")
    if names[-1] != "shadow_site_package":
        raise RuntimeError("terminal_runtime_stage_changed")

    joined = "\n".join(" ".join(stage.argv) for stage in plan)
    if EXPECTED_MODULE in joined or EXPECTED_OUTPUT in joined:
        raise RuntimeError("ci_only_validation_runtime_reference_detected")
    if any(stage.name == "core_v2_external_audit" for stage in plan):
        raise RuntimeError("external_auditor_inserted_during_extraction_increment")

    retained = {stage.name: stage for stage in _owned_promoted_claim_contract_stages(base)}
    stage = retained.get(STAGE_NAME)
    if stage is None:
        raise RuntimeError("retained_ci_only_validation_definition_missing")
    if len(stage.argv) < 2 or stage.argv[1] != EXPECTED_MODULE:
        raise RuntimeError("retained_ci_only_validation_module_changed")
    if _output_name(stage) != EXPECTED_OUTPUT:
        raise RuntimeError("retained_ci_only_validation_artifact_changed")
    if "--prove-tamper" not in stage.argv or "--contract" not in stage.argv:
        raise RuntimeError("retained_ci_only_validation_contract_or_tamper_flag_missing")
    if EXPECTED_CONTRACT_OUTPUT not in " ".join(stage.argv):
        raise RuntimeError("retained_ci_only_validation_contract_identity_changed")

    runtime_artifact = base / EXPECTED_OUTPUT
    runtime_artifact_absent_before_ci_reexecution = not runtime_artifact.exists()
    if not runtime_artifact_absent_before_ci_reexecution:
        raise RuntimeError("validation_artifact_leaked_from_runtime_before_ci_only_reexecution")

    argv = _replace_output(stage.argv, runtime_artifact)
    completed = subprocess.run(argv, cwd=repo, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            "ci_only_validation_failed:"
            + (completed.stderr or completed.stdout or f"exit={completed.returncode}")[-1200:]
        )
    if not runtime_artifact.is_file():
        raise RuntimeError("ci_only_validation_artifact_not_materialized")
    isolated = _load(runtime_artifact)

    if isolated.get("status") != "PASS_SHADOW":
        raise RuntimeError("ci_only_validation_not_pass_shadow")
    if isolated.get("publication_authority") != "NONE" or isolated.get("acceptance_ready") is not False:
        raise RuntimeError("ci_only_validation_authority_boundary_changed")
    if isolated.get("site_publish_allowed") is not False or isolated.get("social_publish_allowed") is not False:
        raise RuntimeError("ci_only_validation_publish_boundary_changed")
    if int(isolated.get("fabricated_claim_count") or 0) != 0:
        raise RuntimeError("ci_only_validation_fabricated_claim_count_nonzero")
    if int(isolated.get("tamper_regressions_passed") or 0) != EXPECTED_TAMPER:
        raise RuntimeError("ci_only_contract_tamper_count_changed")
    if int(isolated.get("consumer_tamper_regressions_passed") or 0) != EXPECTED_CONSUMER_TAMPER:
        raise RuntimeError("ci_only_consumer_tamper_count_changed")
    if int(isolated.get("total_tamper_regressions_passed") or 0) != EXPECTED_TOTAL_TAMPER:
        raise RuntimeError("ci_only_total_tamper_count_changed")
    if isolated.get("source_specific_output_equivalent") is not True:
        raise RuntimeError("ci_only_source_specific_equivalence_changed")

    identity = _identity_snapshot(isolated)
    if not all(identity.values()):
        missing = sorted(key for key, value in identity.items() if not value)
        raise RuntimeError(f"ci_only_evidence_identity_incomplete:{','.join(missing)}")

    contract = _load(base / EXPECTED_CONTRACT_OUTPUT)
    if contract.get("promoted_claim_contract_id") != identity["promoted_claim_contract_id"]:
        raise RuntimeError("ci_only_contract_identity_not_bound_to_runtime_contract")
    article_claim = _load(base / "valcea-core-v2-isj-article-deadline-claim.json")
    if article_claim.get("article_deadline_claim_evidence_id") != identity["article_claim_evidence_id"]:
        raise RuntimeError("ci_only_article_claim_identity_not_bound_to_runtime_article_claim")

    return {
        "schema_version": "core-v2-promoted-claim-contract-ci-retirement-proof.v2",
        "status": "PASS_SHADOW",
        "canonical_runtime_stage_count": len(plan),
        "candidate_stage": STAGE_NAME,
        "candidate_module": stage.argv[1],
        "candidate_output": _output_name(stage),
        "candidate_present_in_runtime": False,
        "candidate_runtime_references": 0,
        "runtime_artifact_absent_before_ci_reexecution": True,
        "ci_only_artifact_materialized": True,
        "ci_only_reexecution_semantically_bound_to_runtime_contract": True,
        "artifact_identity_preserved": True,
        "evidence_identity_preserved": True,
        "evidence_identity": identity,
        "contract_tamper_regressions_passed": EXPECTED_TAMPER,
        "consumer_tamper_regressions_passed": EXPECTED_CONSUMER_TAMPER,
        "total_tamper_regressions_passed": EXPECTED_TOTAL_TAMPER,
        "runtime_extraction_performed": True,
        "external_auditor_inserted": False,
        "terminal_runtime_stage": plan[-1].name,
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "cutover_authority": "NONE",
        "retirement_authority": "NONE",
        "truth_rule": (
            "The canonical runtime contains 41 stages and no longer executes or references the promoted-claim contract "
            "validation stage/artifact. CI independently reexecutes the retained exact validator definition after the "
            "runtime cycle, binds its result back to the runtime contract/article evidence identities, and requires all "
            "9 fail-closed tamper regressions. The external auditor is not inserted in this increment, and no publication, "
            "acceptance, cutover or retirement authority is granted."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove promoted-claim contract validation is CI-only after 41-stage runtime extraction")
    parser.add_argument("--base", default="/tmp")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--output", default="/tmp/valcea-core-v2-promoted-claim-contract-ci-retirement-proof.json")
    args = parser.parse_args()
    report = validate(Path(args.base), Path(args.repo).resolve())
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
