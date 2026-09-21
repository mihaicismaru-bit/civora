from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

import orchestrator
import orchestrator_run86
from validate_promoted_claim_article_integrity_stage_equivalence_run94 import (
    SOURCE_NEUTRAL_FACADE,
    RETAINED_IMPLEMENTATION,
    INTEGRITY_STAGE,
    INTEGRITY_ARTIFACT,
    FACT_KERNEL_ARTIFACT,
    FACT_INTEGRITY_ARTIFACT,
    ARTICLE_ARTIFACT,
    REPORT_ARTIFACT,
    EXPECTED_ARTICLE_CLAIM_ID,
    _load,
    _semantic_sha,
    _stage_semantics,
    _by_name,
    _assert_non_authorizing,
    _run_cli,
    _tamper_cases,
)


def _prove_stage_definition(base: Path) -> dict[str, Any]:
    canonical = orchestrator.bounded_cycle_plan(base, live=False)
    # Immutable RUN81 comparator. RUN86 captured this function reference before
    # later migration wrappers patched module-level bounded_cycle_plan seams.
    # orchestrator._LEGACY_PLAN is the older RUN70 comparator and therefore is
    # not the correct baseline for the post-RUN81 writer/article stage order.
    frozen81 = orchestrator_run86._BASE_PLAN(base, live=False)
    canonical_by_name = _by_name(canonical)
    frozen_by_name = _by_name(frozen81)
    canonical_names = [stage.name for stage in canonical]
    frozen_names = [stage.name for stage in frozen81]

    if len(canonical) != 42:
        raise RuntimeError(f"canonical_stage_count_changed:{len(canonical)}")
    if len(frozen81) != 42:
        raise RuntimeError(f"frozen_run81_stage_count_changed:{len(frozen81)}")
    if canonical_names != frozen_names:
        raise RuntimeError("canonical_stage_order_diverged_from_frozen_run81")

    integrity = canonical_by_name[INTEGRITY_STAGE]
    frozen_integrity = frozen_by_name[INTEGRITY_STAGE]
    if len(integrity.argv) < 2 or integrity.argv[1] != SOURCE_NEUTRAL_FACADE:
        raise RuntimeError("canonical_article_integrity_not_bound_to_source_neutral_facade")
    if len(frozen_integrity.argv) < 2 or frozen_integrity.argv[1] != RETAINED_IMPLEMENTATION:
        raise RuntimeError("frozen_run81_article_integrity_not_retained_implementation")
    if integrity.output is None or integrity.output.name != INTEGRITY_ARTIFACT:
        raise RuntimeError("canonical_article_integrity_output_changed")
    if frozen_integrity.output is None or frozen_integrity.output.name != INTEGRITY_ARTIFACT:
        raise RuntimeError("frozen_run81_article_integrity_output_changed")

    if _stage_semantics(integrity, base) != _stage_semantics(frozen_integrity, base):
        raise RuntimeError("source_neutral_integrity_stage_normalized_definition_not_equivalent_to_frozen_run81")

    required_flags = ("--fact-kernel", "--fact-kernel-integrity", "--article", "--output")
    for flag in required_flags:
        if integrity.argv.count(flag) != 1 or frozen_integrity.argv.count(flag) != 1:
            raise RuntimeError(f"integrity_stage_cli_flag_cardinality_changed:{flag}")

    joined = " ".join(str(token) for token in integrity.argv)
    for artifact in (FACT_KERNEL_ARTIFACT, FACT_INTEGRITY_ARTIFACT, ARTICLE_ARTIFACT):
        if artifact not in joined:
            raise RuntimeError(f"integrity_stage_lineage_artifact_missing:{artifact}")
    canonical_joined = "\n".join(" ".join(stage.argv) for stage in canonical)
    if SOURCE_NEUTRAL_FACADE not in canonical_joined:
        raise RuntimeError("source_neutral_integrity_facade_missing_from_canonical_plan")
    if RETAINED_IMPLEMENTATION in canonical_joined:
        raise RuntimeError("retained_integrity_implementation_still_runtime_dependency")

    writer_index = canonical_names.index("promoted_claim_writer")
    gate_index = canonical_names.index("isj_article_deadline_claim_gate")
    validation_index = canonical_names.index("isj_article_deadline_claim_validation")
    integrity_index = canonical_names.index(INTEGRITY_STAGE)
    if (gate_index, validation_index, integrity_index) != (writer_index + 1, writer_index + 2, writer_index + 3):
        raise RuntimeError("canonical_writer_gate_validation_integrity_order_changed")

    ownership = orchestrator._article_integrity_stage_ownership_snapshot(canonical)
    if ownership.get("status") != "PASS_SHADOW":
        raise RuntimeError("article_integrity_ownership_snapshot_not_pass_shadow")
    if ownership.get("canonical_runtime_switched") is not True:
        raise RuntimeError("article_integrity_ownership_does_not_record_switch")
    if ownership.get("retained_integrity_runtime_dependency") is not False:
        raise RuntimeError("retained_integrity_runtime_dependency_not_closed")
    if ownership.get("retained_integrity_retirement_eligible") is not False:
        raise RuntimeError("retained_integrity_retirement_boundary_changed")
    if ownership.get("publication_authority") != "NONE" or ownership.get("acceptance_ready") is not False:
        raise RuntimeError("article_integrity_ownership_authority_boundary_changed")

    return {
        "canonical_stage_count": 42,
        "canonical_stage_order_matches_frozen_run81": True,
        "frozen_run81_comparator_source": "orchestrator_run86._BASE_PLAN",
        "frozen_run81_comparator_immutable": True,
        "canonical_integrity_stage_name": integrity.name,
        "canonical_integrity_module": integrity.argv[1],
        "retained_integrity_module": frozen_integrity.argv[1],
        "canonical_integrity_artifact": integrity.output.name,
        "canonical_integrity_stage_normalized_definition_matches_frozen_run81": True,
        "source_neutral_normalized_stage_definition_equivalent": True,
        "canonical_order_writer_gate_validation_integrity_preserved": True,
        "canonical_runtime_switched": True,
        "source_neutral_facade_present_in_canonical_plan": True,
        "retained_implementation_runtime_dependency": False,
        "retained_implementation_regression_only": True,
        "retained_implementation_retirement_eligible": False,
    }


def validate(base: Path) -> dict[str, Any]:
    base = Path(base)
    fact_kernel_path = base / FACT_KERNEL_ARTIFACT
    fact_integrity_path = base / FACT_INTEGRITY_ARTIFACT
    article_path = base / ARTICLE_ARTIFACT
    canonical_integrity_path = base / INTEGRITY_ARTIFACT
    for path in (fact_kernel_path, fact_integrity_path, article_path, canonical_integrity_path):
        if not path.is_file():
            raise RuntimeError(f"required_runtime_artifact_missing:{path}")

    stage_report = _prove_stage_definition(base)
    canonical_integrity = _load(canonical_integrity_path)
    article = _load(article_path)

    with tempfile.TemporaryDirectory(prefix="core-v2-integrity-stage-equivalence-") as raw_tmp:
        tmp = Path(raw_tmp)
        retained_rc, retained, _, retained_stderr = _run_cli(
            RETAINED_IMPLEMENTATION,
            fact_kernel=fact_kernel_path,
            fact_integrity=fact_integrity_path,
            article=article_path,
            output=tmp / "retained.json",
        )
        facade_rc, facade, _, facade_stderr = _run_cli(
            SOURCE_NEUTRAL_FACADE,
            fact_kernel=fact_kernel_path,
            fact_integrity=fact_integrity_path,
            article=article_path,
            output=tmp / "facade.json",
        )
        if retained_rc != 0:
            raise RuntimeError(f"retained_integrity_cli_positive_failed:{retained_stderr.strip()}")
        if facade_rc != 0:
            raise RuntimeError(f"source_neutral_integrity_cli_positive_failed:{facade_stderr.strip()}")
        if retained != facade or facade != canonical_integrity:
            raise RuntimeError("article_integrity_positive_cli_semantics_diverged")

        _assert_non_authorizing(retained, "retained")
        _assert_non_authorizing(facade, "facade")
        _assert_non_authorizing(canonical_integrity, "canonical")
        if facade.get("status") != "PASS_SHADOW" or facade.get("article_integrity_verified") is not True:
            raise RuntimeError("source_neutral_integrity_positive_not_pass_shadow")
        if int(facade.get("verified_article_count") or 0) != 1:
            raise RuntimeError("source_neutral_integrity_verified_article_count_changed")
        if int(facade.get("verified_claim_count") or 0) != 3:
            raise RuntimeError("source_neutral_integrity_verified_claim_count_changed")
        if int(facade.get("fabricated_claim_count") or 0) != 0:
            raise RuntimeError("source_neutral_integrity_fabricated_claim_count_nonzero")
        if facade.get("article_deadline_claim_evidence_id") != EXPECTED_ARTICLE_CLAIM_ID:
            raise RuntimeError("source_neutral_integrity_article_claim_evidence_id_changed")

        tamper_results: list[dict[str, Any]] = []
        for case_name, tampered_article in _tamper_cases(article):
            tampered_path = tmp / f"tampered-{case_name}.json"
            tampered_path.write_text(json.dumps(tampered_article, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            retained_tamper_rc, retained_tamper, _, _ = _run_cli(
                RETAINED_IMPLEMENTATION,
                fact_kernel=fact_kernel_path,
                fact_integrity=fact_integrity_path,
                article=tampered_path,
                output=tmp / f"retained-{case_name}.json",
            )
            facade_tamper_rc, facade_tamper, _, _ = _run_cli(
                SOURCE_NEUTRAL_FACADE,
                fact_kernel=fact_kernel_path,
                fact_integrity=fact_integrity_path,
                article=tampered_path,
                output=tmp / f"facade-{case_name}.json",
            )
            if retained_tamper_rc == 0 or facade_tamper_rc == 0:
                raise RuntimeError(f"article_integrity_tamper_did_not_fail_cli:{case_name}")
            if retained_tamper != facade_tamper:
                raise RuntimeError(f"article_integrity_tamper_semantics_diverged:{case_name}")
            if facade_tamper.get("status") != "BLOCKED" or facade_tamper.get("article_integrity_verified") is not False:
                raise RuntimeError(f"article_integrity_tamper_not_blocked:{case_name}")
            if int(facade_tamper.get("fabricated_claim_count") or 0) <= 0:
                raise RuntimeError(f"article_integrity_tamper_not_counted_as_fabricated:{case_name}")
            _assert_non_authorizing(facade_tamper, f"tamper:{case_name}")
            tamper_results.append({
                "case": case_name,
                "retained_exit_code": retained_tamper_rc,
                "facade_exit_code": facade_tamper_rc,
                "status": facade_tamper.get("status"),
                "fabricated_claim_count": int(facade_tamper.get("fabricated_claim_count") or 0),
                "semantic_sha256": _semantic_sha(facade_tamper),
            })

    report = {
        "schema_version": "core-v2-promoted-claim-article-integrity-post-switch-stage-equivalence-ci.v3",
        "status": "PASS_SHADOW",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "retirement_authority": "NONE",
        **stage_report,
        "positive_retained_cli_exit_code": retained_rc,
        "positive_facade_cli_exit_code": facade_rc,
        "retained_json_semantic_sha256": _semantic_sha(retained),
        "facade_json_semantic_sha256": _semantic_sha(facade),
        "canonical_json_semantic_sha256": _semantic_sha(canonical_integrity),
        "positive_cli_json_semantic_equivalent": True,
        "article_deadline_claim_evidence_id": facade.get("article_deadline_claim_evidence_id"),
        "verified_article_count": int(facade.get("verified_article_count") or 0),
        "verified_claim_count": int(facade.get("verified_claim_count") or 0),
        "fabricated_claim_count": int(facade.get("fabricated_claim_count") or 0),
        "projected_deadline_verified": facade.get("projected_deadline_verified") is True,
        "fail_closed_tamper_regressions_passed": len(tamper_results),
        "tamper_results": tamper_results,
        "retained_implementation_runtime_dependency": False,
        "retained_implementation_retirement_eligible": False,
        "source_neutral_facade_runtime_dependency": True,
        "canonical_switch_validated_by_this_proof": True,
        "truth_rule": (
            "Post-switch CI-only PASS_SHADOW proves that the canonical isj_article_integrity stage now executes the source-neutral "
            "facade one-for-one with the same normalized stage name, argv inputs, output artifact and 42-stage position as the "
            "immutable RUN81 comparator captured by orchestrator_run86._BASE_PLAN. The facade, retained verifier and canonical runtime artifact "
            "have exact positive JSON semantics and identical fail-closed CLI behavior under headline, evidence-identity and extra-claim tampering. "
            "The retained verifier is regression-only, not a canonical runtime dependency and not retirement-eligible. No publication, acceptance, "
            "merge, deploy, cutover or retirement authority is granted."
        ),
    }
    (base / REPORT_ARTIFACT).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="CI-only post-switch proof of source-neutral article-integrity stage-definition and CLI equivalence")
    parser.add_argument("--base", default="/tmp")
    parser.add_argument("--output")
    args = parser.parse_args()
    report = validate(Path(args.base))
    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "canonical_stage_count": report["canonical_stage_count"],
        "source_neutral_normalized_stage_definition_equivalent": report["source_neutral_normalized_stage_definition_equivalent"],
        "positive_cli_json_semantic_equivalent": report["positive_cli_json_semantic_equivalent"],
        "article_deadline_claim_evidence_id": report["article_deadline_claim_evidence_id"],
        "verified_claim_count": report["verified_claim_count"],
        "fabricated_claim_count": report["fabricated_claim_count"],
        "fail_closed_tamper_regressions_passed": report["fail_closed_tamper_regressions_passed"],
        "canonical_runtime_switched": True,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
