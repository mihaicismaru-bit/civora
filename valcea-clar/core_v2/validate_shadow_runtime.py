from __future__ import annotations

import argparse
import json
from pathlib import Path

from validate_shadow_runtime_run96 import validate as _validate_run96


def validate(base: Path, repo: Path) -> None:
    """Compatibility-preserving canonical runtime validator.

    Negative runtime regressions import this symbol and intentionally provide a
    reduced tamper fixture set. Keep that contract identical to RUN96. The new
    AuditResult equivalence proof is CI-only and is layered in main() only, where
    the complete external-readback artifact set exists.
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

    report = validate_audit_result(base, repo)
    proof_path = base / "valcea-core-v2-audit-result-stage-equivalence.json"
    proof_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "ci_only_audit_result_stage_equivalence": report.get("status"),
        "canonical_stage_count": report.get("canonical_stage_count"),
        "runtime_switched": report.get("runtime_switched"),
        "audit_result_schema_version": report.get("audit_result_schema_version"),
        "external_truth_complete": report.get("external_truth_complete"),
        "external_blocked_story_count": report.get("external_blocked_story_count"),
        "tamper_regression_count": report.get("tamper_regression_count"),
        "publication_authority": report.get("publication_authority"),
        "acceptance_ready": report.get("acceptance_ready"),
        "cutover_authority": report.get("cutover_authority"),
        "retirement_authority": report.get("retirement_authority"),
    }, ensure_ascii=False, sort_keys=True))
    print("Core v2 shadow runtime invariants + AuditResult contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
