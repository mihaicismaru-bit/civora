from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from promoted_claim_projection_validation import (
    prove_projection_tamper_regressions,
    validate_source_neutral_projection,
)


def validate(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    projection: dict[str, Any],
) -> dict[str, Any]:
    """Validate the promoted-claim writer projection through the source-neutral contract only.

    This module retains the historical CLI/file name solely as a bounded compatibility
    facade for downstream ISJ stages. It no longer contains or invokes an independent
    ISJ-specific projection validator. Canonical truth comes exclusively from
    promoted_claim_projection_validation.validate_source_neutral_projection().
    """
    generic = validate_source_neutral_projection(fact_kernel, fact_integrity, projection)
    assert generic.get("status") == "PASS_SHADOW"
    assert generic.get("field") == "registration_deadline"
    assert generic.get("writer_projection_allowed") is True
    assert generic.get("publication_authority") == "NONE"
    assert generic.get("acceptance_ready") is False
    assert generic.get("production_writer_ready") is False
    assert generic.get("site_publish_allowed") is False
    assert generic.get("social_publish_allowed") is False
    assert int(generic.get("verified_projection_candidate_count") or 0) == 1
    assert int(generic.get("fabricated_claim_count") or 0) == 0

    report = dict(generic)
    report.update({
        "schema_version": "1.2",
        "mode": "CORE_V2_SOURCE_NEUTRAL_PROMOTED_CLAIM_PROJECTION_VALIDATION_RUNTIME",
        "registration_deadline": generic.get("value"),
        "writer_deadline_projection_allowed": generic.get("writer_projection_allowed") is True,
        "article_projection_allowed": False,
        "writer_allowed": False,
        "legacy_projection_validator_runtime_dependency": False,
        "legacy_projection_validator_parallel_comparison": False,
        "legacy_projection_validator_retirement_eligible": True,
        "legacy_projection_validator_retired_from_canonical_runtime": True,
        "canonical_projection_validation_path": "SOURCE_NEUTRAL_ONLY",
        "source_neutral_projection_validation_used_downstream": True,
        "replacement_path_enabled": True,
        "retirement_performed": True,
        "truth_rule": (
            "Canonical runtime projection validation is source-neutral only and is derived independently from the promoted FactKernel lineage. "
            "No ISJ-specific projection validator participates in this runtime artifact. The historical CLI and compatibility aliases remain temporarily for downstream file-shape stability only. "
            "This retirement changes no projection identity and grants no article, publication, delivery or acceptance authority."
        ),
    })
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate promoted-claim writer projection using the source-neutral canonical contract only")
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--fact-kernel-integrity", required=True)
    parser.add_argument("--projection", required=True)
    parser.add_argument("--year", type=int, default=2026, help="Compatibility argument; semantic year validation is carried by the promoted claim lineage")
    parser.add_argument("--prove-tamper", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    fact_kernel = json.loads(Path(args.fact_kernel).read_text(encoding="utf-8"))
    fact_integrity = json.loads(Path(args.fact_kernel_integrity).read_text(encoding="utf-8"))
    projection = json.loads(Path(args.projection).read_text(encoding="utf-8"))

    report = validate(fact_kernel, fact_integrity, projection)
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
        "registration_deadline": report["registration_deadline"],
        "writer_projection_evidence_id": report["writer_projection_evidence_id"],
        "writer_deadline_projection_allowed": report["writer_deadline_projection_allowed"],
        "tamper_regressions_passed": report["tamper_regressions_passed"],
        "legacy_projection_validator_runtime_dependency": False,
        "legacy_projection_validator_retired_from_canonical_runtime": True,
        "retirement_performed": True,
        "article_projection_allowed": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
