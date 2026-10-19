from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from validate_shadow_runtime_run96 import (
    validate as _validate_run96,
    _validate_independent_external_auditor,
)


def validate(base: Path, repo: Path) -> None:
    """Compatibility-preserving runtime validator for tamper fixtures.

    RUN96's validator conditionally executes now-frozen 42-stage CI migration
    comparators whenever GITHUB_ACTIONS is true. RUN100 deliberately shrinks the
    canonical runtime to 41 stages, so this compatibility entrypoint suppresses
    only that CI branch while preserving all runtime truth checks. RUN100's new
    migration proofs are executed explicitly in main() after the CI-only contract
    validator has been materialized.
    """
    previous = os.environ.get("GITHUB_ACTIONS")
    try:
        os.environ["GITHUB_ACTIONS"] = "false"
        _validate_run96(base, repo)
    finally:
        if previous is None:
            os.environ.pop("GITHUB_ACTIONS", None)
        else:
            os.environ["GITHUB_ACTIONS"] = previous


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Core v2 41-stage live shadow artifacts and CI-only migration proofs")
    parser.add_argument("--base", default="/tmp")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()
    base = Path(args.base)
    repo = Path(args.repo).resolve()

    # The validator was deliberately removed from runtime. Prove that absence,
    # then execute the exact retained validator once in CI to materialize its
    # regression artifact before downstream evidence-identity checks.
    from validate_promoted_claim_contract_ci_retirement import validate as validate_contract_ci_retirement

    contract_report = validate_contract_ci_retirement(base, repo)
    contract_proof_path = base / "valcea-core-v2-promoted-claim-contract-ci-retirement-proof.json"
    contract_proof_path.write_text(json.dumps(contract_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    validate(base, repo)

    from validate_run100_runtime_extraction import validate as validate_run100_extraction

    extraction_report = validate_run100_extraction(base)
    extraction_path = base / "valcea-core-v2-run100-runtime-extraction-equivalence.json"
    extraction_path.write_text(json.dumps(extraction_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    external = _validate_independent_external_auditor(base)

    from validate_promoted_claim_audit_result_stage_equivalence import validate as validate_audit_result

    audit_report = validate_audit_result(base, repo)
    audit_proof_path = base / "valcea-core-v2-audit-result-stage-equivalence.json"
    audit_proof_path.write_text(json.dumps(audit_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "ci_only_promoted_claim_contract_retirement_proof": contract_report.get("status"),
        "runtime_stage_count": contract_report.get("canonical_runtime_stage_count"),
        "runtime_extraction_performed": contract_report.get("runtime_extraction_performed"),
        "runtime_artifact_absent_before_ci_reexecution": contract_report.get("runtime_artifact_absent_before_ci_reexecution"),
        "ci_only_artifact_materialized": contract_report.get("ci_only_artifact_materialized"),
        "total_tamper_regressions_passed": contract_report.get("total_tamper_regressions_passed"),
        "run100_runtime_extraction_equivalence": extraction_report.get("status"),
        "canonical_stage_order_equals_frozen_run81_minus_ci_only_validation": extraction_report.get("canonical_stage_order_equals_frozen_run81_minus_ci_only_validation"),
        "article_claim_evidence_id": extraction_report.get("article_claim_evidence_id"),
        "promoted_claim_contract_id": extraction_report.get("promoted_claim_contract_id"),
        "verified_article_claim_count": extraction_report.get("verified_article_claim_count"),
        "fabricated_claim_count": extraction_report.get("fabricated_claim_count"),
        "ci_only_independent_external_auditor": external.get("status"),
        "external_truth_complete": external.get("external_truth_complete"),
        "external_blocked_story_count": external.get("external_blocked_story_count"),
        "metrics": external.get("metrics"),
        "ci_only_audit_result_stage_equivalence": audit_report.get("status"),
        "audit_runtime_switched": audit_report.get("runtime_switched"),
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "cutover_authority": "NONE",
        "retirement_authority": "NONE",
    }, ensure_ascii=False, sort_keys=True))

    print("Core v2 41-stage shadow runtime invariants + CI-only extraction proofs: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
