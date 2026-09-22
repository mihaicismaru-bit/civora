from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from audit_result_contract import AuditResult, AuditResultContractViolation
from orchestrator import bounded_cycle_plan as canonical_bounded_cycle_plan
from orchestrator_run70 import bounded_cycle_plan as frozen_bounded_cycle_plan
from promoted_claim_auditor import audit_documents


EXPECTED_STAGE_NAME = "core_v2_external_audit"
EXPECTED_MODULE = "valcea-clar/core_v2/promoted_claim_audit_result.py"
EXPECTED_OUTPUT_NAME = "valcea-core-v2-audit-result.json"
RECONCILIATION_CANDIDATE = "isj_promoted_claim_contract_validation"
RECONCILIATION_CANDIDATE_OUTPUT = "valcea-core-v2-isj-promoted-claim-contract-validation.json"
REQUIRED_EXTERNAL_INPUTS = (
    "valcea-core-v2-shadow-candidates.json",
    "valcea-core-v2-site-readback.json",
    "valcea-core-v2-visual-readback.json",
    "valcea-core-v2-meta-readback.json",
    "valcea-core-v2-instagram-visual-identity.json",
    "valcea-core-v2-shadow-transactions.json",
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected object document: {path}")
    return value


def _expect_contract_failure(document: dict[str, Any], label: str) -> str:
    try:
        AuditResult.from_external_auditor_document(document)
    except AuditResultContractViolation:
        return label
    raise RuntimeError(f"tamper_not_rejected:{label}")


def _output_name(stage: Any) -> str | None:
    if stage.output is None:
        return None
    return stage.output.name


def _downstream_consumers(plan: tuple[Any, ...], index: int) -> list[str]:
    output = plan[index].output
    if output is None:
        return []
    needle = str(output)
    return [stage.name for stage in plan[index + 1 :] if needle in stage.argv]


def _audit_slot_feasibility(plan: tuple[Any, ...]) -> dict[str, Any]:
    """Prove whether the external audit can replace one canonical slot safely.

    This is intentionally stricter than merely finding a stage with no downstream
    consumer. The external audit consumes independently produced public-site,
    visual, Meta and transaction evidence. A safe one-for-one replacement must
    therefore have every required input available from earlier canonical stages,
    preserve the 42-stage count, and not discard an output still consumed by a
    later stage. We do not merge evidence producers into the auditor.
    """
    if len(plan) != 42:
        raise RuntimeError(f"canonical_stage_count_changed:{len(plan)}")

    produced_names = {_output_name(stage) for stage in plan if _output_name(stage) is not None}
    missing_from_canonical_plan = [name for name in REQUIRED_EXTERNAL_INPUTS if name not in produced_names]

    stage_rows: list[dict[str, Any]] = []
    exact_slots: list[str] = []
    available_before: set[str] = set()
    for index, stage in enumerate(plan):
        downstream = _downstream_consumers(plan, index)
        required_inputs_available = all(name in available_before for name in REQUIRED_EXTERNAL_INPUTS)
        output_name = _output_name(stage)
        output_unconsumed = not downstream
        output_identity_equivalent = output_name == EXPECTED_OUTPUT_NAME
        exact = required_inputs_available and output_unconsumed and output_identity_equivalent
        if exact:
            exact_slots.append(stage.name)
        stage_rows.append(
            {
                "index": index,
                "name": stage.name,
                "output": output_name,
                "downstream_consumers": downstream,
                "required_external_inputs_available_before_stage": required_inputs_available,
                "output_identity_equivalent_to_audit_result": output_identity_equivalent,
                "exact_one_for_one_external_audit_slot": exact,
            }
        )
        if output_name is not None:
            available_before.add(output_name)

    if exact_slots:
        raise RuntimeError(f"unexpected_exact_external_audit_slot:{exact_slots}")
    if len(missing_from_canonical_plan) != len(REQUIRED_EXTERNAL_INPUTS):
        raise RuntimeError(
            "external_evidence_partially_entered_canonical_plan_without_explicit_reconciliation:"
            + ",".join(missing_from_canonical_plan)
        )

    by_name = {stage.name: (index, stage) for index, stage in enumerate(plan)}
    if RECONCILIATION_CANDIDATE not in by_name:
        raise RuntimeError("reconciliation_candidate_missing")
    candidate_index, candidate = by_name[RECONCILIATION_CANDIDATE]
    candidate_consumers = _downstream_consumers(plan, candidate_index)
    candidate_output = _output_name(candidate)
    if candidate_output != RECONCILIATION_CANDIDATE_OUTPUT:
        raise RuntimeError("reconciliation_candidate_output_changed")
    if candidate_consumers:
        raise RuntimeError(f"reconciliation_candidate_has_downstream_consumers:{candidate_consumers}")

    last_stage = plan[-1]
    if last_stage.name != "shadow_site_package":
        raise RuntimeError("canonical_terminal_shadow_site_package_changed")

    return {
        "schema_version": "core-v2-external-audit-slot-feasibility.v1",
        "status": "PASS_SHADOW",
        "slot_feasibility": "NO_EXACT_ONE_FOR_ONE_SLOT",
        "canonical_stage_count": len(plan),
        "exact_replacement_slots": exact_slots,
        "required_external_inputs": list(REQUIRED_EXTERNAL_INPUTS),
        "external_inputs_produced_inside_canonical_plan": [],
        "external_inputs_missing_from_canonical_plan": missing_from_canonical_plan,
        "evidence_producers_must_remain_independent": True,
        "audit_stage_switch_allowed_this_increment": False,
        "forty_third_stage_allowed": False,
        "reconciliation_required_before_integration": True,
        "reconciliation_candidate": {
            "stage": candidate.name,
            "index": candidate_index,
            "output": candidate_output,
            "downstream_consumers": candidate_consumers,
            "reason": (
                "This validation stage has no in-plan downstream consumer and is the safest bounded candidate to move "
                "to CI-only regression coverage when deliberately freeing a runtime slot. Moving it does not by itself "
                "make external evidence available; site/visual/Meta/transaction evidence must still enter orchestrator "
                "ownership before the audit can become a real golden-path stage."
            ),
            "runtime_switch_performed": False,
            "retirement_authority": "NONE",
        },
        "terminal_stage": last_stage.name,
        "architecture_conclusion": (
            "The current 42-stage canonical cycle ends before independent public-site, visual, Meta and transaction "
            "readbacks are produced. Therefore no existing slot can be replaced one-for-one by core_v2_external_audit "
            "without either losing an existing artifact or consuming evidence that does not yet exist. Do not shoehorn "
            "the auditor into the pre-evidence cycle and do not add a 43rd stage. First reconcile a redundant validation "
            "slot to CI-only coverage, then move the independent external evidence producer sequence under the single "
            "orchestrator ahead of the audit."
        ),
        "stage_analysis": stage_rows,
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "cutover_authority": "NONE",
        "retirement_authority": "NONE",
    }


def validate(base: Path, repo: Path) -> dict[str, Any]:
    paths = {
        "candidates": base / "valcea-core-v2-shadow-candidates.json",
        "site_readback": base / "valcea-core-v2-site-readback.json",
        "visual_readback": base / "valcea-core-v2-visual-readback.json",
        "meta_readback": base / "valcea-core-v2-meta-readback.json",
        "instagram_identity": base / "valcea-core-v2-instagram-visual-identity.json",
        "transactions": base / "valcea-core-v2-shadow-transactions.json",
    }
    for name, path in paths.items():
        if not path.exists():
            raise RuntimeError(f"audit_result_equivalence_missing_input:{name}:{path}")

    raw = {name: _load(path) for name, path in paths.items()}
    external = audit_documents(
        raw["candidates"],
        raw["site_readback"],
        raw["visual_readback"],
        raw["meta_readback"],
        raw["instagram_identity"],
        raw["transactions"],
    )
    expected = AuditResult.from_external_auditor_document(external).as_dict()

    with tempfile.TemporaryDirectory(prefix="valcea-core-v2-audit-result-") as td:
        output = Path(td) / EXPECTED_OUTPUT_NAME
        argv = [
            sys.executable,
            str(repo / EXPECTED_MODULE),
            "--candidates", str(paths["candidates"]),
            "--site-readback", str(paths["site_readback"]),
            "--visual-readback", str(paths["visual_readback"]),
            "--meta-readback", str(paths["meta_readback"]),
            "--instagram-identity", str(paths["instagram_identity"]),
            "--transactions", str(paths["transactions"]),
            "--output", str(output),
        ]
        subprocess.run(argv, cwd=repo, check=True, capture_output=True, text=True)
        observed = _load(output)
    if observed != expected:
        raise RuntimeError("audit_result_cli_semantic_equivalence_drifted")

    frozen_plan = frozen_bounded_cycle_plan(base, live=False)
    plan = canonical_bounded_cycle_plan(base, live=False)
    if len(frozen_plan) != 42 or len(plan) != 42:
        raise RuntimeError(f"canonical_stage_count_changed:frozen={len(frozen_plan)}:canonical={len(plan)}")
    if any(stage.name == EXPECTED_STAGE_NAME for stage in plan):
        raise RuntimeError("audit_result_stage_was_switched_in_same_increment")
    if any(EXPECTED_MODULE in stage.argv for stage in plan):
        raise RuntimeError("audit_result_module_was_switched_in_same_increment")

    proposed_argv = (
        sys.executable,
        EXPECTED_MODULE,
        "--candidates", str(paths["candidates"]),
        "--site-readback", str(paths["site_readback"]),
        "--visual-readback", str(paths["visual_readback"]),
        "--meta-readback", str(paths["meta_readback"]),
        "--instagram-identity", str(paths["instagram_identity"]),
        "--transactions", str(paths["transactions"]),
        "--output", str(base / EXPECTED_OUTPUT_NAME),
    )
    if proposed_argv[1] != EXPECTED_MODULE or proposed_argv[-1] != str(base / EXPECTED_OUTPUT_NAME):
        raise RuntimeError("proposed_stage_boundary_drifted")

    if expected.get("publication_authority") != "NONE":
        raise RuntimeError("audit_result_publication_authority_changed")
    if expected.get("acceptance_ready") is not False:
        raise RuntimeError("audit_result_acceptance_boundary_changed")
    if expected.get("cutover_authority") != "NONE" or expected.get("retirement_authority") != "NONE":
        raise RuntimeError("audit_result_cutover_or_retirement_boundary_changed")

    tamper: list[str] = []
    doc = copy.deepcopy(external)
    doc["publication_authority"] = "PRODUCTION"
    tamper.append(_expect_contract_failure(doc, "publication_authority"))

    doc = copy.deepcopy(external)
    doc["acceptance_ready"] = True
    tamper.append(_expect_contract_failure(doc, "acceptance_ready"))

    doc = copy.deepcopy(external)
    doc["metrics"]["photo_coverage"] = 1.5
    tamper.append(_expect_contract_failure(doc, "impossible_photo_coverage"))

    doc = copy.deepcopy(external)
    doc["external_truth_complete"] = True
    if doc.get("external_truth_complete") == external.get("external_truth_complete"):
        doc["metrics"]["truth_complete_transactions"] = int(doc["metrics"].get("candidate_count") or 0)
    tamper.append(_expect_contract_failure(doc, "false_external_truth_complete"))

    doc = copy.deepcopy(external)
    if not doc.get("rows"):
        doc["metrics"]["stories_published"] = int(doc["metrics"].get("candidate_count") or 0) + 1
    else:
        doc["rows"][0]["site_published_external"] = not bool(doc["rows"][0].get("site_published_external"))
    tamper.append(_expect_contract_failure(doc, "row_metric_mismatch"))

    slot = _audit_slot_feasibility(plan)
    metrics = expected["metrics"]
    report = {
        "schema_version": "core-v2-audit-result-stage-equivalence.v2",
        "status": "PASS_SHADOW",
        "canonical_stage_count": len(plan),
        "frozen_reference_stage_count": len(frozen_plan),
        "runtime_switched": False,
        "proposed_stage": {
            "name": EXPECTED_STAGE_NAME,
            "argv": list(proposed_argv),
            "output": str(base / EXPECTED_OUTPUT_NAME),
        },
        "slot_feasibility": slot,
        "audit_result_schema_version": expected["schema_version"],
        "external_truth_complete": expected["external_truth_complete"],
        "external_blocked_story_count": expected["external_blocked_story_count"],
        "candidate_count": metrics["candidate_count"],
        "stories_published": metrics["stories_published"],
        "photo_verified_count": metrics["photo_verified_count"],
        "facebook_delivered_receipt_bound": metrics["facebook_delivered_receipt_bound"],
        "instagram_delivered_receipt_bound": metrics["instagram_delivered_receipt_bound"],
        "truth_complete_transactions": metrics["truth_complete_transactions"],
        "duplicates": metrics["duplicates"],
        "fabricated_claims": metrics["fabricated_claims"],
        "unresolved_material_signals": metrics["unresolved_material_signals"],
        "manual_intervention": metrics["manual_intervention"],
        "tamper_regressions": tamper,
        "tamper_regression_count": len(tamper),
        "publication_authority": expected["publication_authority"],
        "acceptance_ready": expected["acceptance_ready"],
        "cutover_authority": expected["cutover_authority"],
        "retirement_authority": expected["retirement_authority"],
    }
    if len(tamper) != 5:
        raise RuntimeError("audit_result_tamper_regression_count_changed")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="CI-only Core v2 AuditResult stage-definition/CLI and slot-feasibility proof")
    parser.add_argument("--base", default="/tmp")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--output", default="/tmp/valcea-core-v2-audit-result-stage-equivalence.json")
    args = parser.parse_args()
    report = validate(Path(args.base), Path(args.repo).resolve())
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
