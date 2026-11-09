import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from orchestrator import (
    bounded_cycle_plan,
    _article_truth_stage_ownership_snapshot,
    _article_integrity_stage_ownership_snapshot,
    _promoted_claim_contract_stage_ownership_snapshot,
    _owned_promoted_claim_contract_stages,
    _fact_kernel_stage_ownership_snapshot,
    _promoted_claim_projection_stage_ownership_snapshot,
    _promoted_claim_consumption_stage_ownership_snapshot,
    _writer_stage_ownership_snapshot,
)


EXPECTED_STAGE_NAMES = [
    "apavil", "ipj", "isu", "municipal_reference", "municipal_document", "municipal_materiality",
    "municipal_fact_kernel", "municipal_writer", "cj_road", "eta", "isj", "isj_detail", "isj_materiality",
    "isj_embedded_notice", "isj_embedded_target", "isj_embedded_content", "isj_field_evidence",
    "isj_context_documents", "isj_calendar_field_evidence", "isj_calendar_scope_binding",
    "isj_calendar_scope_validation", "isj_registration_deadline_promotion",
    "isj_registration_deadline_promotion_validation", "isj_field_materiality",
    "isj_fact_kernel_deadline_promotion", "isj_fact_kernel_deadline_promotion_validation",
    "isj_fact_kernel", "isj_fact_kernel_integrity", "promoted_claim_writer_projection",
    "promoted_claim_projection_validation", "promoted_claim_writer_consumption",
    "promoted_claim_writer_consumption_validation", "promoted_claim_writer",
    "isj_article_deadline_claim_gate", "isj_article_deadline_claim_validation",
    "isj_article_integrity", "isj_promoted_claim_contract", "site_verified_article_ledger",
    "photo_truth", "site_visual_runtime_registry", "shadow_site_package",
]


class BoundedOrchestratorPlanTest(unittest.TestCase):
    def test_plan_is_single_ordered_read_only_41_stage_golden_path(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = bounded_cycle_plan(Path(temp), live=True)
        names = [stage.name for stage in plan]
        self.assertEqual(names, EXPECTED_STAGE_NAMES)
        self.assertEqual(len(names), 41)
        self.assertNotIn("isj_promoted_claim_contract_validation", names)
        self.assertNotIn("core_v2_external_audit", names)
        self.assertEqual(names[-1], "shadow_site_package")

        joined = "\n".join(" ".join(stage.argv) for stage in plan).lower()
        for forbidden in (
            "workflow_dispatch", "git push", "merge", "deploy",
            "facebook_publish", "instagram_publish", "manual-publish",
            "validate_isj_promoted_claim_contract_runtime.py",
            "valcea-core-v2-isj-promoted-claim-contract-validation.json",
        ):
            self.assertNotIn(forbidden, joined)
        self.assertIn("--external-probe", joined)
        self.assertIn("--live", joined)
        self.assertIn("--prove-tamper", joined)

    def test_writer_article_truth_contract_order_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            workdir = Path(temp)
            plan = bounded_cycle_plan(workdir, live=False)
        by_name = {stage.name: stage for stage in plan}
        names = [stage.name for stage in plan]

        writer = by_name["promoted_claim_writer"]
        gate = by_name["isj_article_deadline_claim_gate"]
        validation = by_name["isj_article_deadline_claim_validation"]
        integrity = by_name["isj_article_integrity"]
        contract = by_name["isj_promoted_claim_contract"]
        site_ledger = by_name["site_verified_article_ledger"]

        self.assertEqual(writer.argv[1], "valcea-clar/core_v2/promoted_claim_writer.py")
        self.assertEqual(gate.argv[1], "valcea-clar/core_v2/promoted_claim_article_truth.py")
        self.assertEqual(gate.argv[2:4], ("--mode", "gate"))
        self.assertEqual(validation.argv[1], "valcea-clar/core_v2/promoted_claim_article_truth.py")
        self.assertEqual(validation.argv[2:4], ("--mode", "validate"))
        self.assertEqual(integrity.argv[1], "valcea-clar/core_v2/promoted_claim_article_integrity.py")
        self.assertEqual(contract.argv[1], "valcea-clar/core_v2/isj_promoted_claim_contract_shadow_lane.py")

        writer_i = names.index(writer.name)
        gate_i = names.index(gate.name)
        validation_i = names.index(validation.name)
        integrity_i = names.index(integrity.name)
        contract_i = names.index(contract.name)
        site_i = names.index(site_ledger.name)
        self.assertEqual((gate_i, validation_i, integrity_i), (writer_i + 1, writer_i + 2, writer_i + 3))
        self.assertEqual(contract_i, integrity_i + 1)
        self.assertEqual(site_i, contract_i + 1)

    def test_contract_validator_is_retained_ci_only_and_absent_from_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            workdir = Path(temp)
            plan = bounded_cycle_plan(workdir, live=False)
            retained = {stage.name: stage for stage in _owned_promoted_claim_contract_stages(workdir)}

        names = [stage.name for stage in plan]
        joined = "\n".join(" ".join(stage.argv) for stage in plan)
        self.assertNotIn("isj_promoted_claim_contract_validation", names)
        self.assertNotIn("validate_isj_promoted_claim_contract_runtime.py", joined)
        self.assertNotIn("valcea-core-v2-isj-promoted-claim-contract-validation.json", joined)

        ci_stage = retained["isj_promoted_claim_contract_validation"]
        self.assertEqual(ci_stage.argv[1], "valcea-clar/core_v2/validate_isj_promoted_claim_contract_runtime.py")
        self.assertIn("--contract", ci_stage.argv)
        self.assertIn("--prove-tamper", ci_stage.argv)
        self.assertEqual(ci_stage.output.name, "valcea-core-v2-isj-promoted-claim-contract-validation.json")

        report = _promoted_claim_contract_stage_ownership_snapshot(plan)
        self.assertEqual(report["status"], "PASS_SHADOW")
        self.assertEqual(report["canonical_stage_count"], 41)
        self.assertTrue(report["runtime_extraction_performed"])
        self.assertTrue(report["ci_only_regression_retained"])
        self.assertFalse(report["runtime_validation_stage_present"])
        self.assertFalse(report["runtime_validation_module_present"])
        self.assertFalse(report["runtime_validation_artifact_referenced"])
        self.assertFalse(report["external_auditor_inserted"])
        self.assertEqual(report["publication_authority"], "NONE")
        self.assertFalse(report["acceptance_ready"])

    def test_migration_ownership_snapshots_remain_pass_shadow(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = bounded_cycle_plan(Path(temp), live=False)
        reports = (
            _fact_kernel_stage_ownership_snapshot(plan),
            _promoted_claim_projection_stage_ownership_snapshot(plan),
            _promoted_claim_consumption_stage_ownership_snapshot(plan),
            _writer_stage_ownership_snapshot(plan),
            _article_truth_stage_ownership_snapshot(plan),
            _article_integrity_stage_ownership_snapshot(plan),
        )
        for report in reports:
            self.assertEqual(report["status"], "PASS_SHADOW")
            self.assertEqual(report["canonical_stage_count"], 41)
            self.assertEqual(report["publication_authority"], "NONE")
            self.assertFalse(report["acceptance_ready"])


if __name__ == "__main__":
    unittest.main()
