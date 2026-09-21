from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from orchestrator import bounded_cycle_plan, _article_truth_stage_ownership_snapshot
from validate_promoted_claim_article_integrity_equivalence import validate_equivalence as validate_integrity_equivalence
from validate_promoted_claim_article_truth_equivalence_run91 import validate_equivalence


SOURCE_NEUTRAL_CLI = "valcea-clar/core_v2/promoted_claim_article_truth.py"
SOURCE_NEUTRAL_INTEGRITY = "valcea-clar/core_v2/promoted_claim_article_integrity.py"
RETAINED_GATE = "valcea-clar/core_v2/isj_article_deadline_claim_gate.py"
RETAINED_VALIDATOR = "valcea-clar/core_v2/validate_isj_article_deadline_claim_gate.py"
RETAINED_INTEGRITY = "valcea-clar/core_v2/isj_article_integrity.py"


def _load(path: str | Path) -> dict[str, Any]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise TypeError(f"expected_json_object:{path}")
    return doc


def _validate_canonical_switch() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="core-v2-article-truth-switch-plan-") as raw_tmp:
        plan = bounded_cycle_plan(Path(raw_tmp), live=False)
    by_name = {stage.name: stage for stage in plan}
    names = [stage.name for stage in plan]

    gate = by_name["isj_article_deadline_claim_gate"]
    validation = by_name["isj_article_deadline_claim_validation"]
    integrity = by_name["isj_article_integrity"]
    writer_index = names.index("promoted_claim_writer")
    gate_index = names.index(gate.name)
    validation_index = names.index(validation.name)
    integrity_index = names.index(integrity.name)

    assert len(plan) == 42
    assert gate.argv[1] == SOURCE_NEUTRAL_CLI
    assert gate.argv[2:4] == ("--mode", "gate")
    assert validation.argv[1] == SOURCE_NEUTRAL_CLI
    assert validation.argv[2:4] == ("--mode", "validate")
    assert gate.output is not None and gate.output.name == "valcea-core-v2-isj-article-deadline-claim.json"
    assert validation.output is not None and validation.output.name == "valcea-core-v2-isj-article-deadline-claim-validation.json"
    assert integrity.argv[1] == SOURCE_NEUTRAL_INTEGRITY
    assert integrity.output is not None and integrity.output.name == "valcea-core-v2-isj-article-integrity-shadow.json"
    assert (gate_index, validation_index, integrity_index) == (
        writer_index + 1,
        writer_index + 2,
        writer_index + 3,
    )
    assert "--gate" in validation.argv
    assert str(gate.output) in validation.argv
    assert "--prove-tamper" in validation.argv
    joined = "\n".join(" ".join(stage.argv) for stage in plan)
    assert RETAINED_GATE not in joined
    assert RETAINED_VALIDATOR not in joined
    assert RETAINED_INTEGRITY not in joined

    ownership = _article_truth_stage_ownership_snapshot(plan)
    assert ownership.get("status") == "PASS_SHADOW"
    assert ownership.get("canonical_article_truth_runtime_switched") is True
    assert ownership.get("canonical_article_integrity_runtime_switched") is True
    assert ownership.get("canonical_stage_definitions_switched") is True
    assert ownership.get("retained_implementations_runtime_dependency") is False
    assert ownership.get("retained_implementations_regression_only") is True
    assert ownership.get("retained_implementations_retirement_eligible") is False
    assert ownership.get("retirement_authority") == "NONE"
    assert ownership.get("publication_authority") == "NONE"
    assert ownership.get("acceptance_ready") is False

    return {
        "canonical_stage_count": len(plan),
        "canonical_gate_stage_name": gate.name,
        "canonical_validation_stage_name": validation.name,
        "canonical_integrity_stage_name": integrity.name,
        "canonical_gate_module": gate.argv[1],
        "canonical_validation_module": validation.argv[1],
        "canonical_integrity_module": integrity.argv[1],
        "canonical_gate_mode": gate.argv[3],
        "canonical_validation_mode": validation.argv[3],
        "canonical_gate_artifact": gate.output.name,
        "canonical_validation_artifact": validation.output.name,
        "canonical_integrity_artifact": integrity.output.name,
        "canonical_order_writer_gate_validation_integrity_preserved": True,
        "retained_gate_runtime_dependency": False,
        "retained_validator_runtime_dependency": False,
        "retained_integrity_runtime_dependency": False,
        "retained_implementations_regression_only": True,
        "retained_implementations_retirement_eligible": False,
        "retirement_authority": "NONE",
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the canonical source-neutral article-truth and integrity switches plus semantic parity"
    )
    parser.add_argument("--fact-kernel", required=True)
    parser.add_argument("--fact-kernel-integrity", required=True)
    parser.add_argument("--writer-consumption", required=True)
    parser.add_argument("--writer-consumption-validation", required=True)
    parser.add_argument("--canonical-gate", required=True)
    parser.add_argument("--canonical-validation", required=True)
    parser.add_argument("--canonical-article", required=True)
    parser.add_argument("--canonical-integrity", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    fact_kernel = _load(args.fact_kernel)
    fact_integrity = _load(args.fact_kernel_integrity)
    canonical_article = _load(args.canonical_article)
    canonical_integrity = _load(args.canonical_integrity)

    report = validate_equivalence(
        fact_kernel,
        fact_integrity,
        _load(args.writer_consumption),
        _load(args.writer_consumption_validation),
        _load(args.canonical_gate),
        _load(args.canonical_validation),
        canonical_article,
        canonical_integrity,
    )
    switch = _validate_canonical_switch()
    integrity_facade = validate_integrity_equivalence(
        fact_kernel,
        fact_integrity,
        canonical_article,
        canonical_integrity,
    )

    report.update(switch)
    report["article_integrity_facade_equivalence"] = integrity_facade
    report["schema_version"] = "core-v2-promoted-claim-article-truth-integrity-post-switch-shadow.v3"
    report["status"] = "PASS_SHADOW"
    report["canonical_runtime_switched"] = True
    report["canonical_stage_definitions_switched"] = True
    report["article_integrity_facade_built"] = True
    report["article_integrity_facade_equivalent"] = integrity_facade.get("json_semantic_equivalent") is True
    report["article_integrity_facade_canonical_runtime_switched"] = True
    report["article_integrity_facade_tamper_regressions_passed"] = integrity_facade.get("fail_closed_tamper_regressions_passed")
    report["retained_implementations_retirement_eligible"] = False
    report["retirement_authority"] = "NONE"
    report["publication_authority"] = "NONE"
    report["acceptance_ready"] = False
    report["site_publish_allowed"] = False
    report["social_publish_allowed"] = False
    report["truth_rule"] = (
        "The canonical article-truth gate and validation stages execute the source-neutral promoted_claim_article_truth CLI "
        "one-for-one, and the canonical article-integrity stage executes the source-neutral promoted_claim_article_integrity "
        "facade one-for-one. Exact artifacts and writer->gate->validation->integrity order are preserved. Semantic parity remains "
        "bound to retained deterministic ISJ implementations, with the same article-claim evidence identity, 5/5 preprojection "
        "and 3/3 projected tamper regressions, downstream 3 verified / 0 fabricated, plus 3/3 independent integrity tamper "
        "regressions. Retained components remain KEEP regression-only and not retirement-eligible. No publication, acceptance, "
        "merge, deploy, Meta-write, public-projection or retirement authority is granted."
    )

    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "canonical_runtime_switched": True,
        "canonical_stage_definitions_switched": True,
        "canonical_stage_count": switch["canonical_stage_count"],
        "article_deadline_claim_evidence_id": report["article_deadline_claim_evidence_id"],
        "tamper_regressions_passed": report["tamper_regressions_passed"],
        "projected_tamper_regressions_passed": report["projected_tamper_regressions_passed"],
        "downstream_verified_claim_count": report["downstream_verified_claim_count"],
        "downstream_fabricated_claim_count": report["downstream_fabricated_claim_count"],
        "article_integrity_facade_equivalent": report["article_integrity_facade_equivalent"],
        "article_integrity_facade_tamper_regressions_passed": report["article_integrity_facade_tamper_regressions_passed"],
        "article_integrity_facade_canonical_runtime_switched": True,
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
