from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from isj_writer_deadline_projection_comparator import compare_source_specific_projection
from promoted_claim_projection_validation import (
    build_source_neutral_projection,
    prove_projection_tamper_regressions,
    validate_source_neutral_projection,
)

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
    })
    return out


def build_writer_deadline_projection(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    *,
    expected_year: int = 2026,
) -> dict[str, Any]:
    """Compatibility facade whose canonical producer is now source-neutral.

    The historical module path is retained for this bounded switch increment so the
    orchestrator and downstream artifacts do not move at the same time. The actual
    projection is produced by ``build_source_neutral_projection``. The ISJ-specific
    logic survives only as an independent comparison guard and cannot grant authority.
    """
    generic = build_source_neutral_projection(
        fact_kernel,
        fact_integrity,
        identity_prefix=COMPATIBILITY_IDENTITY_PREFIX,
    )
    generic.update({
        "canonical_writer_projection_builder_path": "SOURCE_NEUTRAL_RUNTIME_FACADE",
        "canonical_writer_projection_runtime_facade": True,
        "compatibility_cli_path_retained": True,
        "source_specific_builder_canonical_producer": False,
        "source_specific_builder_comparison_only": True,
        "source_specific_builder_retirement_performed": False,
    })
    if generic.get("state") != "WRITER_PROJECTION_VERIFIED_SHADOW":
        return generic

    try:
        comparison = compare_source_specific_projection(
            fact_kernel,
            fact_integrity,
            generic,
            expected_year=expected_year,
        )
        if comparison.get("status") != "PASS_SHADOW":
            return _blocked_from(
                generic,
                "source_specific_comparator_failed",
                str(comparison.get("detail") or comparison.get("reason") or "comparison blocked"),
            )
        projection_id = str(generic.get("writer_projection_evidence_id") or "")
        if comparison.get("writer_projection_evidence_id") != projection_id:
            return _blocked_from(generic, "source_specific_comparator_identity_mismatch", "projection identity diverged")

        independent = validate_source_neutral_projection(fact_kernel, fact_integrity, generic)
        if independent.get("status") != "PASS_SHADOW":
            return _blocked_from(
                generic,
                "source_neutral_projection_validation_failed",
                str(independent.get("detail") or independent.get("reason") or "validation blocked"),
            )
        if independent.get("writer_projection_evidence_id") != projection_id:
            return _blocked_from(generic, "source_neutral_projection_validation_identity_mismatch", "projection identity diverged")

        tamper_passed = prove_projection_tamper_regressions(fact_kernel, fact_integrity, generic)
        if tamper_passed != 4:
            return _blocked_from(generic, "source_neutral_projection_tamper_proof_incomplete", f"passed={tamper_passed}")

        generic.update({
            "source_specific_comparator_status": "PASS_SHADOW",
            "source_specific_comparator_identity_equivalent": True,
            "source_specific_comparator_lineage_equivalent": bool(comparison.get("source_specific_lineage_equivalent")),
            "source_specific_comparator_authority_flags_equivalent": bool(comparison.get("source_specific_authority_flags_equivalent")),
            "source_specific_comparator": comparison,
            "source_neutral_projection_validation_status": "PASS_SHADOW",
            "source_neutral_projection_tamper_regressions_passed": tamper_passed,
            "retirement_candidate": "isj_writer_deadline_projection_source_specific_builder",
            "retirement_candidate_proof_only": True,
            "retirement_performed": False,
            "truth_rule": (
                str(generic.get("truth_rule") or "")
                + " The canonical producer for this artifact is now the source-neutral promoted-claim builder. "
                + "The ISJ-specific implementation is retained only as an independent switch-comparison guard; it is not the canonical producer and has not been retired in this increment."
            ),
        })
        return generic
    except Exception as exc:
        return _blocked_from(generic, "writer_projection_runtime_facade_failed", f"{type(exc).__name__}:{exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build fail-closed promoted-claim writer projection through the Core v2 source-neutral runtime facade")
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--fact-kernel-integrity", required=True)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build_writer_deadline_projection(
        json.loads(Path(args.fact_kernel).read_text(encoding="utf-8")),
        json.loads(Path(args.fact_kernel_integrity).read_text(encoding="utf-8")),
        expected_year=args.year,
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result.get("state"),
        "registration_deadline": result.get("registration_deadline"),
        "writer_projection_evidence_id": result.get("writer_projection_evidence_id"),
        "canonical_writer_projection_builder_path": result.get("canonical_writer_projection_builder_path"),
        "source_specific_comparator_status": result.get("source_specific_comparator_status"),
        "source_neutral_projection_tamper_regressions_passed": result.get("source_neutral_projection_tamper_regressions_passed", 0),
        "source_specific_builder_canonical_producer": result.get("source_specific_builder_canonical_producer", False),
        "source_specific_builder_retirement_performed": result.get("source_specific_builder_retirement_performed", False),
        "article_projection_allowed": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("state") == "WRITER_PROJECTION_VERIFIED_SHADOW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
