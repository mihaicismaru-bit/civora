from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from orchestrator import bounded_cycle_plan


STAGE_NAME = "isj_promoted_claim_contract_validation"
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


def _downstream_consumers(plan: tuple[Any, ...], index: int) -> list[str]:
    output = plan[index].output
    if output is None:
        return []
    needle = str(output)
    return [stage.name for stage in plan[index + 1 :] if needle in stage.argv]


def _replace_output(argv: tuple[str, ...], output: Path) -> list[str]:
    values = list(argv)
    try:
        index = values.index("--output")
    except ValueError as exc:
        raise RuntimeError("canonical_validation_output_flag_missing") from exc
    if index + 1 >= len(values):
        raise RuntimeError("canonical_validation_output_value_missing")
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
    if len(plan) != 42:
        raise RuntimeError(f"canonical_stage_count_changed:{len(plan)}")

    matches = [(index, stage) for index, stage in enumerate(plan) if stage.name == STAGE_NAME]
    if len(matches) != 1:
        raise RuntimeError(f"canonical_validation_stage_count_changed:{len(matches)}")
    stage_index, stage = matches[0]

    if len(stage.argv) < 2 or stage.argv[1] != EXPECTED_MODULE:
        raise RuntimeError("canonical_validation_module_changed")
    if _output_name(stage) != EXPECTED_OUTPUT:
        raise RuntimeError("canonical_validation_artifact_changed")
    if "--prove-tamper" not in stage.argv:
        raise RuntimeError("canonical_validation_tamper_flag_missing")
    if "--contract" not in stage.argv:
        raise RuntimeError("canonical_validation_contract_flag_missing")
    if EXPECTED_CONTRACT_OUTPUT not in " ".join(stage.argv):
        raise RuntimeError("canonical_validation_contract_identity_changed")

    downstream = _downstream_consumers(plan, stage_index)
    if downstream:
        raise RuntimeError(f"candidate_has_downstream_consumers:{downstream}")

    canonical_path = base / EXPECTED_OUTPUT
    if not canonical_path.is_file():
        raise RuntimeError(f"canonical_validation_artifact_missing:{canonical_path}")
    canonical = _load(canonical_path)

    with tempfile.TemporaryDirectory(prefix="valcea-core-v2-contract-ci-only-") as td:
        isolated_path = Path(td) / EXPECTED_OUTPUT
        isolated_argv = _replace_output(stage.argv, isolated_path)
        completed = subprocess.run(
            isolated_argv,
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "ci_only_validation_failed:"
                + (completed.stderr or completed.stdout or f"exit={completed.returncode}")[-800:]
            )
        isolated = _load(isolated_path)

    if isolated != canonical:
        differing = sorted(key for key in set(canonical) | set(isolated) if canonical.get(key) != isolated.get(key))
        raise RuntimeError(f"ci_only_semantic_equivalence_drifted:{','.join(differing)}")

    for label, doc in (("canonical", canonical), ("ci_only", isolated)):
        if doc.get("status") != "PASS_SHADOW":
            raise RuntimeError(f"{label}_validation_not_pass_shadow")
        if doc.get("publication_authority") != "NONE" or doc.get("acceptance_ready") is not False:
            raise RuntimeError(f"{label}_authority_boundary_changed")
        if doc.get("site_publish_allowed") is not False or doc.get("social_publish_allowed") is not False:
            raise RuntimeError(f"{label}_publish_boundary_changed")
        if int(doc.get("fabricated_claim_count") or 0) != 0:
            raise RuntimeError(f"{label}_fabricated_claim_count_nonzero")
        if int(doc.get("tamper_regressions_passed") or 0) != EXPECTED_TAMPER:
            raise RuntimeError(f"{label}_contract_tamper_count_changed")
        if int(doc.get("consumer_tamper_regressions_passed") or 0) != EXPECTED_CONSUMER_TAMPER:
            raise RuntimeError(f"{label}_consumer_tamper_count_changed")
        if int(doc.get("total_tamper_regressions_passed") or 0) != EXPECTED_TOTAL_TAMPER:
            raise RuntimeError(f"{label}_total_tamper_count_changed")
        if doc.get("source_specific_output_equivalent") is not True:
            raise RuntimeError(f"{label}_source_specific_equivalence_changed")

    canonical_identity = _identity_snapshot(canonical)
    isolated_identity = _identity_snapshot(isolated)
    if canonical_identity != isolated_identity:
        raise RuntimeError("ci_only_evidence_identity_drifted")
    if not all(canonical_identity.values()):
        missing = sorted(key for key, value in canonical_identity.items() if not value)
        raise RuntimeError(f"canonical_evidence_identity_incomplete:{','.join(missing)}")

    hypothetical_plan = tuple(item for item in plan if item.name != STAGE_NAME)
    if len(hypothetical_plan) != 41:
        raise RuntimeError(f"hypothetical_runtime_stage_count_unexpected:{len(hypothetical_plan)}")
    if any(EXPECTED_OUTPUT in " ".join(item.argv) for item in hypothetical_plan):
        raise RuntimeError("validation_artifact_still_consumed_after_candidate_extraction")
    if hypothetical_plan[-1].name != plan[-1].name or hypothetical_plan[-1].name != "shadow_site_package":
        raise RuntimeError("terminal_runtime_stage_changed_by_candidate_extraction")

    return {
        "schema_version": "core-v2-promoted-claim-contract-ci-retirement-proof.v1",
        "status": "PASS_SHADOW",
        "canonical_stage_count": len(plan),
        "candidate_stage": STAGE_NAME,
        "candidate_stage_index": stage_index,
        "candidate_module": stage.argv[1],
        "candidate_output": _output_name(stage),
        "candidate_downstream_consumers": downstream,
        "ci_only_reexecution_semantically_identical": True,
        "artifact_identity_preserved": True,
        "evidence_identity_preserved": True,
        "evidence_identity": canonical_identity,
        "contract_tamper_regressions_passed": EXPECTED_TAMPER,
        "consumer_tamper_regressions_passed": EXPECTED_CONSUMER_TAMPER,
        "total_tamper_regressions_passed": EXPECTED_TOTAL_TAMPER,
        "hypothetical_runtime_stage_count_after_extraction": len(hypothetical_plan),
        "hypothetical_terminal_stage_after_extraction": hypothetical_plan[-1].name,
        "eligible_for_ci_only_regression_extraction": True,
        "runtime_extraction_performed": False,
        "external_auditor_inserted": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "cutover_authority": "NONE",
        "retirement_authority": "NONE",
        "truth_rule": (
            "The canonical promoted-claim contract validation stage is eligible to move from runtime execution to "
            "CI-only regression coverage because its artifact has zero in-plan downstream consumers and an isolated "
            "re-execution using the canonical argv is JSON-semantically identical, preserves artifact/evidence identity, "
            "and retains all 9 fail-closed tamper regressions. This proof does not remove the stage, insert the external "
            "auditor, merge evidence producers, or grant publication, acceptance, cutover or retirement authority."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove promoted-claim contract validation can move to CI-only coverage")
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
