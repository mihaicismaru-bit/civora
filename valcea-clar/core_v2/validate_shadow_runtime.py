from __future__ import annotations

import argparse
import json
from pathlib import Path

from validate_shadow_runtime_run96 import validate as _validate_run96


def validate(base: Path, repo: Path) -> None:
    """Compatibility-preserving canonical runtime validator.

    Negative runtime regressions import this symbol and intentionally provide a
    reduced tamper fixture set. Keep that contract identical to RUN96. New Core v2
    migration proofs are CI-only and are layered in main() only, where the complete
    natural shadow artifact set exists.
    """
    _validate_run96(base, repo)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate all Core v2 live shadow artifacts remain non-authoritative")
    parser.add_argument("--base", default="/tmp")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()
    base = Path(args.base)
    repo = Path(args.repo).resolve()

    validate(base, repo)

    from validate_promoted_claim_audit_result_stage_equivalence import validate as validate_audit_result

    audit_report = validate_audit_result(base, repo)
    audit_proof_path = base / "valcea-core-v2-audit-result-stage-equivalence.json"
    audit_proof_path.write_text(json.dumps(audit_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "ci_only_audit_result_stage_equivalence": audit_report.get("status"),
        "canonical_stage_count": audit_report.get("canonical_stage_count"),
        "runtime_switched": audit_report.get("runtime_switched"),
        "audit_result_schema_version": audit_report.get("audit_result_schema_version"),
        "external_truth_complete": audit_report.get("external_truth_complete"),
        "external_blocked_story_count": audit_report.get("external_blocked_story_count"),
        "tamper_regression_count": audit_report.get("tamper_regression_count"),
        "publication_authority": audit_report.get("publication_authority"),
        "acceptance_ready": audit_report.get("acceptance_ready"),
        "cutover_authority": audit_report.get("cutover_authority"),
        "retirement_authority": audit_report.get("retirement_authority"),
    }, ensure_ascii=False, sort_keys=True))

    from validate_promoted_claim_contract_ci_retirement import validate as validate_contract_ci_retirement

    contract_report = validate_contract_ci_retirement(base, repo)
    contract_proof_path = base / "valcea-core-v2-promoted-claim-contract-ci-retirement-proof.json"
    contract_proof_path.write_text(json.dumps(contract_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "ci_only_promoted_claim_contract_retirement_proof": contract_report.get("status"),
        "candidate_stage": contract_report.get("candidate_stage"),
        "candidate_downstream_consumers": contract_report.get("candidate_downstream_consumers"),
        "ci_only_reexecution_semantically_identical": contract_report.get("ci_only_reexecution_semantically_identical"),
        "evidence_identity_preserved": contract_report.get("evidence_identity_preserved"),
        "total_tamper_regressions_passed": contract_report.get("total_tamper_regressions_passed"),
        "eligible_for_ci_only_regression_extraction": contract_report.get("eligible_for_ci_only_regression_extraction"),
        "runtime_extraction_performed": contract_report.get("runtime_extraction_performed"),
        "external_auditor_inserted": contract_report.get("external_auditor_inserted"),
        "publication_authority": contract_report.get("publication_authority"),
        "acceptance_ready": contract_report.get("acceptance_ready"),
        "retirement_authority": contract_report.get("retirement_authority"),
    }, ensure_ascii=False, sort_keys=True))

    print("Core v2 shadow runtime invariants + migration proofs: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
