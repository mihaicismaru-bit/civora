from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from isj_writer_shadow_lane import compose_isj_article as compose_retained_writer

RETAINED_WRITER_IMPLEMENTATION = "valcea-clar/core_v2/isj_writer_shadow_lane.py"
RUNTIME_FACADE_MODE = "CORE_V2_SOURCE_NEUTRAL_WRITER_RUNTIME_FACADE"


def _require_non_authorizing_result(result: dict[str, Any]) -> None:
    if result.get("publication_authority") != "NONE":
        raise ValueError("writer_facade_publication_boundary_violation")
    if result.get("acceptance_ready") is not False:
        raise ValueError("writer_facade_acceptance_boundary_violation")
    if result.get("production_writer_ready") is not False:
        raise ValueError("writer_facade_production_writer_boundary_violation")
    if result.get("site_publish_allowed") is not False or result.get("social_publish_allowed") is not False:
        raise ValueError("writer_facade_publication_path_boundary_violation")
    if int(result.get("fabricated_claim_count") or 0) != 0:
        raise ValueError("writer_facade_fabricated_claim_count_nonzero")


def compose_promoted_claim_article(
    fact_kernel_report: dict[str, Any],
    fact_integrity: dict[str, Any],
    writer_consumption: dict[str, Any],
    writer_consumption_validation: dict[str, Any],
) -> dict[str, Any]:
    """Source-neutral runtime facade around the retained deterministic writer.

    This facade deliberately returns the retained writer document unchanged so the
    controlled migration can prove exact output/evidence identity. It owns the
    canonical runtime interface and authority checks; the retained ISJ writer stays
    a KEEP implementation detail until a source-neutral writer implementation is
    separately proven equivalent. No publication, deployment or acceptance
    authority is created here.
    """
    if not isinstance(writer_consumption, dict) or not isinstance(writer_consumption_validation, dict):
        raise ValueError("writer_facade_explicit_consumption_pair_required")

    result = compose_retained_writer(
        fact_kernel_report,
        fact_integrity,
        writer_consumption,
        writer_consumption_validation,
    )
    if not isinstance(result, dict):
        raise TypeError("writer_facade_retained_writer_returned_non_object")
    _require_non_authorizing_result(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compose a Core v2 shadow article through the source-neutral writer runtime facade. "
            "The explicit neutral consumption pair is mandatory and the retained writer implementation grants no publication authority."
        )
    )
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--fact-kernel-integrity", required=True)
    parser.add_argument("--writer-consumption", required=True)
    parser.add_argument("--writer-consumption-validation", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    fact_kernel_path = Path(args.fact_kernel)
    fact_integrity_path = Path(args.fact_kernel_integrity)
    consumption_path = Path(args.writer_consumption)
    validation_path = Path(args.writer_consumption_validation)
    for label, path in (
        ("fact_kernel", fact_kernel_path),
        ("fact_kernel_integrity", fact_integrity_path),
        ("writer_consumption", consumption_path),
        ("writer_consumption_validation", validation_path),
    ):
        if not path.is_file():
            raise SystemExit(f"explicit {label} input file is required")

    result = compose_promoted_claim_article(
        json.loads(fact_kernel_path.read_text(encoding="utf-8")),
        json.loads(fact_integrity_path.read_text(encoding="utf-8")),
        json.loads(consumption_path.read_text(encoding="utf-8")),
        json.loads(validation_path.read_text(encoding="utf-8")),
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result.get("state"),
        "article_count": result.get("article_count", 0),
        "shadow_writer_executed": result.get("shadow_writer_executed", False),
        "writer_consumes_deadline_projection": result.get("writer_consumes_deadline_projection", False),
        "rendered_promoted_claim_count": result.get("rendered_promoted_claim_count", 0),
        "article_contains_registration_deadline": result.get("article_contains_registration_deadline", False),
        "fabricated_claim_count": result.get("fabricated_claim_count", 0),
        "canonical_writer_runtime_facade": RUNTIME_FACADE_MODE,
        "retained_writer_implementation": RETAINED_WRITER_IMPLEMENTATION,
        "article_projection_allowed": False,
        "publication_authority": "NONE",
        "production_writer_ready": False,
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("state") != "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
