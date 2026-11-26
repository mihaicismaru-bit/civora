from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from promoted_claim_projection_validation import (
    build_source_neutral_projection,
    prove_projection_tamper_regressions,
    validate_source_neutral_projection,
)

# Preserve the historical evidence namespace so the runtime path can be renamed
# without changing already-validated projection and downstream consumption IDs.
COMPATIBILITY_IDENTITY_PREFIX = "isj-writer-deadline-projection"


def _blocked_from(result: dict[str, Any], reason: str, detail: str) -> dict[str, Any]:
    out = dict(result)
    out.update({
        "state": "BLOCKED",
        "reason": reason,
        "detail": detail[:500],
        "writer_deadline_projection_allowed": False,
        "promoted_claim_projection_allowed": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "article_projection_allowed": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "projection_candidate_count": 0,
        "projection_candidates": [],
        "source_specific_builder_canonical_producer": False,
        "source_specific_builder_retirement_performed": False,
        "source_specific_comparator_runtime_dependency": False,
    })
    return out


def build_promoted_claim_writer_projection(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    *,
    identity_prefix: str = COMPATIBILITY_IDENTITY_PREFIX,
) -> dict[str, Any]:
    """Build the canonical source-neutral promoted-claim writer projection.

    The runtime module/stage/artifact are source-neutral.  The only retained ISJ
    string is the compatibility identity namespace required to keep the existing
    deterministic evidence ID stable while the architecture is being migrated.
    It is not interpreted as source semantics and grants no publication authority.
    """
    generic = build_source_neutral_projection(
        fact_kernel,
        fact_integrity,
        identity_prefix=identity_prefix,
    )
    generic.update({
        "canonical_writer_projection_builder_path": "SOURCE_NEUTRAL_MODULE",
        "canonical_writer_projection_runtime_facade": False,
        "canonical_writer_projection_stage": "promoted_claim_writer_projection",
        "canonical_writer_projection_artifact": "valcea-core-v2-promoted-claim-writer-projection.json",
        "compatibility_identity_namespace_retained": True,
        "legacy_module_path_required_for_canonical_runtime": False,
        "source_specific_builder_canonical_producer": False,
        "source_specific_builder_comparison_only": False,
        "source_specific_builder_retirement_performed": False,
        "source_specific_comparator_runtime_dependency": False,
        "source_specific_comparator_execution": "INDEPENDENT_CI_REGRESSION_ONLY",
        "source_specific_comparator_status": "NOT_RUN_CANONICAL_PATH",
    })
    if generic.get("state") != "WRITER_PROJECTION_VERIFIED_SHADOW":
        return generic

    try:
        projection_id = str(generic.get("writer_projection_evidence_id") or "")
        independent = validate_source_neutral_projection(fact_kernel, fact_integrity, generic)
        if independent.get("status") != "PASS_SHADOW":
            return _blocked_from(
                generic,
                "source_neutral_projection_validation_failed",
                str(independent.get("detail") or independent.get("reason") or "validation blocked"),
            )
        if independent.get("writer_projection_evidence_id") != projection_id:
            return _blocked_from(
                generic,
                "source_neutral_projection_validation_identity_mismatch",
                "projection identity diverged",
            )

        tamper_passed = prove_projection_tamper_regressions(fact_kernel, fact_integrity, generic)
        if tamper_passed != 4:
            return _blocked_from(
                generic,
                "source_neutral_projection_tamper_proof_incomplete",
                f"passed={tamper_passed}",
            )

        generic.update({
            "source_neutral_projection_validation_status": "PASS_SHADOW",
            "source_neutral_projection_tamper_regressions_passed": tamper_passed,
            "retirement_candidate": "isj_writer_deadline_projection_source_specific_builder",
            "retirement_candidate_proof_only": True,
            "retirement_performed": False,
            "truth_rule": (
                str(generic.get("truth_rule") or "")
                + " Canonical runtime naming, module and artifact are source-neutral; the historical identity prefix is retained only for deterministic evidence-ID compatibility. "
                + "The ISJ-specific wrapper/comparator is outside the canonical runtime and remains independent regression evidence only."
            ),
        })
        return generic
    except Exception as exc:
        return _blocked_from(
            generic,
            "promoted_claim_writer_projection_failed",
            f"{type(exc).__name__}:{exc}",
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build fail-closed source-neutral promoted-claim writer projection for CIVORA Core v2"
    )
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--fact-kernel-integrity", required=True)
    parser.add_argument("--year", type=int, default=2026, help="Compatibility-only CLI argument; evidence controls truth")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    _ = args.year
    result = build_promoted_claim_writer_projection(
        json.loads(Path(args.fact_kernel).read_text(encoding="utf-8")),
        json.loads(Path(args.fact_kernel_integrity).read_text(encoding="utf-8")),
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result.get("state"),
        "writer_projection_evidence_id": result.get("writer_projection_evidence_id"),
        "canonical_writer_projection_builder_path": result.get("canonical_writer_projection_builder_path"),
        "canonical_writer_projection_stage": result.get("canonical_writer_projection_stage"),
        "legacy_module_path_required_for_canonical_runtime": result.get("legacy_module_path_required_for_canonical_runtime"),
        "source_specific_comparator_runtime_dependency": result.get("source_specific_comparator_runtime_dependency", False),
        "source_neutral_projection_tamper_regressions_passed": result.get("source_neutral_projection_tamper_regressions_passed", 0),
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("state") == "WRITER_PROJECTION_VERIFIED_SHADOW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
