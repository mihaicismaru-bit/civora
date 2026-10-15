from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from promoted_claim_projection_validation import (
    prove_projection_tamper_regressions,
    validate_source_neutral_projection,
)


def validate_runtime(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    projection: dict[str, Any],
) -> dict[str, Any]:
    """Expose the canonical promoted-claim projection validator through a source-neutral runtime facade.

    The facade preserves bounded compatibility aliases required by the current ISJ
    downstream consumer, but it contains no ISJ-specific validation logic and grants
    no article, publication, delivery, or acceptance authority.
    """
    generic = validate_source_neutral_projection(fact_kernel, fact_integrity, projection)
    assert generic.get("status") == "PASS_SHADOW"
    assert generic.get("writer_projection_allowed") is True
    assert generic.get("publication_authority") == "NONE"
    assert generic.get("acceptance_ready") is False
    assert generic.get("production_writer_ready") is False
    assert generic.get("site_publish_allowed") is False
    assert generic.get("social_publish_allowed") is False
    assert int(generic.get("verified_projection_candidate_count") or 0) == 1
    assert int(generic.get("fabricated_claim_count") or 0) == 0

    field = str(generic.get("field") or "")
    value = generic.get("value")
    report = dict(generic)
    report.update({
        "schema_version": "1.3",
        "mode": "CORE_V2_SOURCE_NEUTRAL_PROMOTED_CLAIM_PROJECTION_RUNTIME",
        "source_neutral_runtime_facade": True,
        "promoted_claim_projection_allowed": True,
        "writer_deadline_projection_allowed": generic.get("writer_projection_allowed") is True,
        "registration_deadline": value if field == "registration_deadline" else None,
        "article_projection_allowed": False,
        "writer_allowed": False,
        "historical_isj_cli_runtime_dependency": False,
        "legacy_projection_validator_runtime_dependency": False,
        "legacy_projection_validator_parallel_comparison": False,
        "legacy_projection_validator_retirement_eligible": True,
        "legacy_projection_validator_retired_from_canonical_runtime": True,
        "canonical_projection_validation_path": "SOURCE_NEUTRAL_RUNTIME_FACADE",
        "source_neutral_projection_validation_used_downstream": True,
        "replacement_path_enabled": True,
        "retirement_performed": True,
        "truth_rule": (
            "Canonical runtime projection validation is source-neutral and derived independently from the promoted FactKernel lineage. "
            "Compatibility aliases may describe the current downstream ISJ deadline consumer, but no ISJ-specific validator or historical CLI path participates in this runtime stage. "
            "This facade changes no projection identity and grants no article, publication, delivery, or acceptance authority."
        ),
    })
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a promoted-claim writer projection through the source-neutral Core v2 runtime facade")
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--fact-kernel-integrity", required=True)
    parser.add_argument("--projection", required=True)
    parser.add_argument("--year", type=int, default=2026, help="Compatibility argument retained for current downstream callers; promoted-claim lineage carries semantic scope")
    parser.add_argument("--prove-tamper", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    fact_kernel = json.loads(Path(args.fact_kernel).read_text(encoding="utf-8"))
    fact_integrity = json.loads(Path(args.fact_kernel_integrity).read_text(encoding="utf-8"))
    projection = json.loads(Path(args.projection).read_text(encoding="utf-8"))

    report = validate_runtime(fact_kernel, fact_integrity, projection)
    tamper_passed = prove_projection_tamper_regressions(
        fact_kernel,
        fact_integrity,
        projection,
    ) if args.prove_tamper else 0
    if args.prove_tamper:
        assert tamper_passed >= 4

    report["tamper_regressions_requested"] = bool(args.prove_tamper)
    report["tamper_regressions_passed"] = tamper_passed

    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "canonical_projection_validation_path": report["canonical_projection_validation_path"],
        "field": report.get("field"),
        "value": report.get("value"),
        "writer_projection_evidence_id": report["writer_projection_evidence_id"],
        "promoted_claim_projection_allowed": report["promoted_claim_projection_allowed"],
        "tamper_regressions_passed": report["tamper_regressions_passed"],
        "historical_isj_cli_runtime_dependency": False,
        "legacy_projection_validator_runtime_dependency": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
