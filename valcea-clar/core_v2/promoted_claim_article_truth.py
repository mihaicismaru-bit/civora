from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from isj_article_deadline_claim_gate import (
    build_article_deadline_claim_gate as build_retained_article_claim_gate,
)
from validate_isj_article_deadline_claim_gate import (
    project_validated_deadline_claim as project_retained_validated_claim,
    prove_projected_tamper_regressions as prove_retained_projected_tamper_regressions,
    prove_tamper_regressions as prove_retained_tamper_regressions,
    validate as validate_retained_article_claim_gate,
    validate_projected_article as validate_retained_projected_article,
)

RETAINED_GATE_IMPLEMENTATION = "valcea-clar/core_v2/isj_article_deadline_claim_gate.py"
RETAINED_VALIDATOR_IMPLEMENTATION = "valcea-clar/core_v2/validate_isj_article_deadline_claim_gate.py"
RUNTIME_FACADE_MODE = "CORE_V2_SOURCE_NEUTRAL_PROMOTED_CLAIM_ARTICLE_TRUTH_FACADE"
SOURCE_NEUTRAL_CLI_MODE = "CORE_V2_SOURCE_NEUTRAL_PROMOTED_CLAIM_ARTICLE_TRUTH_CLI"


def _require_non_authorizing(doc: dict[str, Any], label: str) -> None:
    if doc.get("publication_authority") != "NONE":
        raise ValueError(f"{label}_publication_boundary_violation")
    if doc.get("acceptance_ready") is not False:
        raise ValueError(f"{label}_acceptance_boundary_violation")
    if doc.get("site_publish_allowed") is not False or doc.get("social_publish_allowed") is not False:
        raise ValueError(f"{label}_publication_path_boundary_violation")
    if int(doc.get("fabricated_claim_count") or 0) != 0:
        raise ValueError(f"{label}_fabricated_claim_count_nonzero")


def build_promoted_claim_article_truth_gate(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    writer_consumption: dict[str, Any],
    writer_consumption_validation: dict[str, Any],
    article_report: dict[str, Any],
) -> dict[str, Any]:
    """Source-neutral facade around the retained deterministic article claim gate.

    During the controlled migration this function returns the retained gate document
    unchanged. The compatibility evidence namespace (including
    ``article_deadline_claim_evidence_id``) is intentionally preserved until a
    separately validated runtime switch. No publication, acceptance, projection,
    deployment or retirement authority is created here.
    """
    result = build_retained_article_claim_gate(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        article_report,
    )
    if not isinstance(result, dict):
        raise TypeError("article_truth_facade_retained_gate_returned_non_object")
    _require_non_authorizing(result, "article_truth_facade_gate")
    if result.get("canonical_article_mutation_allowed") is not False:
        raise ValueError("article_truth_facade_gate_canonical_mutation_boundary_violation")
    if result.get("article_projection_allowed") is not False:
        raise ValueError("article_truth_facade_gate_projection_boundary_violation")
    return result


def validate_promoted_claim_article_truth_gate(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    writer_consumption: dict[str, Any],
    writer_consumption_validation: dict[str, Any],
    article_report: dict[str, Any],
    gate: dict[str, Any],
) -> dict[str, Any]:
    result = validate_retained_article_claim_gate(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        article_report,
        gate,
    )
    if not isinstance(result, dict):
        raise TypeError("article_truth_facade_retained_validation_returned_non_object")
    _require_non_authorizing(result, "article_truth_facade_validation")
    if result.get("canonical_article_mutation_allowed") is not False:
        raise ValueError("article_truth_facade_validation_canonical_mutation_boundary_violation")
    if result.get("article_projection_allowed") is not False:
        raise ValueError("article_truth_facade_validation_projection_boundary_violation")
    return result


def project_promoted_claim_article_shadow(
    article_report: dict[str, Any],
    gate: dict[str, Any],
    validation_summary: dict[str, Any],
) -> dict[str, Any]:
    result = project_retained_validated_claim(article_report, gate, validation_summary)
    if not isinstance(result, dict):
        raise TypeError("article_truth_facade_retained_projection_returned_non_object")
    _require_non_authorizing(result, "article_truth_facade_projected_article")
    if result.get("article_projection_allowed") is not False:
        raise ValueError("article_truth_facade_projected_article_authority_violation")
    return result


def validate_promoted_claim_projected_article(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    writer_consumption: dict[str, Any],
    writer_consumption_validation: dict[str, Any],
    projected_article: dict[str, Any],
    gate: dict[str, Any],
) -> dict[str, Any]:
    result = validate_retained_projected_article(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        projected_article,
        gate,
    )
    if not isinstance(result, dict):
        raise TypeError("article_truth_facade_retained_projected_validation_returned_non_object")
    _require_non_authorizing(result, "article_truth_facade_projected_validation")
    if result.get("article_projection_allowed") is not False:
        raise ValueError("article_truth_facade_projected_validation_authority_violation")
    return result


def prove_promoted_claim_article_truth_tamper_regressions(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    writer_consumption: dict[str, Any],
    writer_consumption_validation: dict[str, Any],
    article_report: dict[str, Any],
    gate: dict[str, Any],
) -> int:
    return prove_retained_tamper_regressions(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        article_report,
        gate,
    )


def prove_promoted_claim_projected_tamper_regressions(
    fact_kernel: dict[str, Any],
    fact_integrity: dict[str, Any],
    writer_consumption: dict[str, Any],
    writer_consumption_validation: dict[str, Any],
    projected_article: dict[str, Any],
    gate: dict[str, Any],
) -> int:
    return prove_retained_projected_tamper_regressions(
        fact_kernel,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
        projected_article,
        gate,
    )


def _load(path: str) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise TypeError(f"expected_json_object:{path}")
    return doc


def _write(path: str, doc: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run_gate_cli(args: argparse.Namespace) -> dict[str, Any]:
    gate = build_promoted_claim_article_truth_gate(
        _load(args.fact_kernel),
        _load(args.fact_kernel_integrity),
        _load(args.writer_consumption),
        _load(args.writer_consumption_validation),
        _load(args.article),
    )
    _write(args.output, gate)
    return {
        "state": gate.get("state"),
        "registration_deadline": gate.get("registration_deadline"),
        "shadow_article_claim_integrity_passed": gate.get("shadow_article_claim_integrity_passed", False),
        "canonical_article_mutation_allowed": False,
        "article_projection_allowed": False,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }


def _run_validate_cli(args: argparse.Namespace) -> dict[str, Any]:
    if not args.gate:
        raise ValueError("validate_mode_requires_gate")

    fact_kernel = _load(args.fact_kernel)
    fact_integrity = _load(args.fact_kernel_integrity)
    consumption = _load(args.writer_consumption)
    consumption_validation = _load(args.writer_consumption_validation)
    article_path = Path(args.article)
    article = _load(args.article)
    gate = _load(args.gate)

    summary = validate_promoted_claim_article_truth_gate(
        fact_kernel,
        fact_integrity,
        consumption,
        consumption_validation,
        article,
        gate,
    )
    tamper = prove_promoted_claim_article_truth_tamper_regressions(
        fact_kernel,
        fact_integrity,
        consumption,
        consumption_validation,
        article,
        gate,
    ) if args.prove_tamper else 0

    projected = project_promoted_claim_article_shadow(article, gate, summary)
    projected_summary = validate_promoted_claim_projected_article(
        fact_kernel,
        fact_integrity,
        consumption,
        consumption_validation,
        projected,
        gate,
    )
    projected_tamper = prove_promoted_claim_projected_tamper_regressions(
        fact_kernel,
        fact_integrity,
        consumption,
        consumption_validation,
        projected,
        gate,
    ) if args.prove_tamper else 0

    article_path.write_text(json.dumps(projected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out = {
        **summary,
        "status": "PASS_SHADOW",
        "shadow_article_projection_applied": True,
        "article_contains_registration_deadline": True,
        "canonical_claim_count": projected_summary["canonical_claim_count"],
        "canonical_promoted_claim_count": 1,
        "tamper_regressions_passed": tamper,
        "projected_tamper_regressions_passed": projected_tamper,
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "canonical_article_mutation_allowed": False,
        "article_projection_allowed": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "truth_rule": (
            "The independent validator rebinds the pending deadline claim to the exact writer-consumption "
            "and promoted FactKernel evidence chain before applying a shadow-only canonical article projection; "
            "the projected article is independently revalidated and grants no delivery, merge or deployment authority."
        ),
    }
    _write(args.output, out)
    return {
        "status": out["status"],
        "article_deadline_claim_evidence_id": out["article_deadline_claim_evidence_id"],
        "canonical_claim_count": out["canonical_claim_count"],
        "article_contains_registration_deadline": True,
        "tamper_regressions_passed": tamper,
        "projected_tamper_regressions_passed": projected_tamper,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Source-neutral Core v2 promoted-claim article-truth CLI. "
            "This migration facade preserves retained gate/validator semantics and grants no publication authority."
        )
    )
    parser.add_argument("--mode", choices=("gate", "validate"), required=True)
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--fact-kernel-integrity", required=True)
    parser.add_argument("--writer-consumption", required=True)
    parser.add_argument("--writer-consumption-validation", required=True)
    parser.add_argument("--article", required=True)
    parser.add_argument("--gate")
    parser.add_argument("--prove-tamper", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if args.mode == "gate":
        summary = _run_gate_cli(args)
    else:
        summary = _run_validate_cli(args)

    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
