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
from orchestrator_run70 import bounded_cycle_plan
from promoted_claim_auditor import audit_documents


EXPECTED_STAGE_NAME = "core_v2_external_audit"
EXPECTED_MODULE = "valcea-clar/core_v2/promoted_claim_audit_result.py"
EXPECTED_OUTPUT_NAME = "valcea-core-v2-audit-result.json"


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

    plan = bounded_cycle_plan(base, live=False)
    if len(plan) != 42:
        raise RuntimeError(f"canonical_stage_count_changed:{len(plan)}")
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

    metrics = expected["metrics"]
    report = {
        "schema_version": "core-v2-audit-result-stage-equivalence.v1",
        "status": "PASS_SHADOW",
        "canonical_stage_count": len(plan),
        "runtime_switched": False,
        "proposed_stage": {
            "name": EXPECTED_STAGE_NAME,
            "argv": list(proposed_argv),
            "output": str(base / EXPECTED_OUTPUT_NAME),
        },
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
    parser = argparse.ArgumentParser(description="CI-only Core v2 AuditResult stage-definition/CLI equivalence proof")
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
