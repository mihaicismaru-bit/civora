import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from orchestrator import bounded_cycle_plan, _writer_consumption_dependency_snapshot


class BoundedOrchestratorPlanTest(unittest.TestCase):
    def test_plan_is_single_ordered_read_only_golden_path(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = bounded_cycle_plan(Path(temp), live=True)
        names = [stage.name for stage in plan]
        self.assertEqual(
            names,
            [
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
                "isj_article_integrity", "isj_promoted_claim_contract", "isj_promoted_claim_contract_validation",
                "site_verified_article_ledger", "photo_truth", "site_visual_runtime_registry", "shadow_site_package",
            ],
        )
        self.assertEqual(len(names), 42)
        self.assertNotIn("isj_writer", names)
        joined = "\n".join(" ".join(stage.argv) for stage in plan).lower()
        for forbidden in ("workflow_dispatch", "git push", "merge", "deploy", "facebook_publish", "instagram_publish", "manual-publish"):
            self.assertNotIn(forbidden, joined)
        self.assertIn("--external-probe", joined)
        self.assertIn("--live", joined)
        self.assertIn("--prove-tamper", joined)

        self.assertIn("promoted_claim_writer_projection.py", joined)
        self.assertIn("validate_promoted_claim_projection_runtime.py", joined)
        self.assertIn("valcea-core-v2-promoted-claim-writer-projection.json", joined)
        self.assertIn("valcea-core-v2-promoted-claim-projection-validation.json", joined)
        self.assertNotIn("isj_writer_deadline_projection_shadow_lane.py", joined)
        self.assertNotIn("validate_isj_writer_deadline_projection.py", joined)
        self.assertNotIn("valcea-core-v2-isj-writer-deadline-projection.json", joined)
        self.assertNotIn("valcea-core-v2-isj-writer-deadline-projection-validation.json", joined)

        self.assertIn("promoted_claim_writer_consumption.py", joined)
        self.assertIn("validate_promoted_claim_writer_consumption_runtime.py", joined)
        self.assertIn("valcea-core-v2-promoted-claim-writer-consumption.json", joined)
        self.assertIn("valcea-core-v2-promoted-claim-writer-consumption-validation.json", joined)
        self.assertNotIn("isj_writer_deadline_consumption_shadow_lane.py", joined)
        self.assertNotIn("validate_isj_writer_deadline_consumption.py", joined)
        self.assertNotIn("valcea-core-v2-isj-writer-deadline-consumption.json", joined)
        self.assertNotIn("valcea-core-v2-isj-writer-deadline-consumption-validation.json", joined)

    def test_non_live_plan_does_not_enable_source_network_reads(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = bounded_cycle_plan(Path(temp), live=False)
        source_stage_names = {
            "apavil", "ipj", "isu", "municipal_reference", "municipal_document", "cj_road", "eta", "isj",
            "isj_detail", "isj_embedded_notice", "isj_embedded_target", "isj_embedded_content", "isj_context_documents",
        }
        for stage in plan:
            if stage.name in source_stage_names:
                self.assertNotIn("--live", stage.argv)

    def test_neutral_consumption_chain_uses_only_prior_shadow_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = bounded_cycle_plan(Path(temp), live=True)
        by_name = {stage.name: stage for stage in plan}
        names = [stage.name for stage in plan]

        fact_kernel = by_name["isj_fact_kernel"]
        fact_integrity = by_name["isj_fact_kernel_integrity"]
        projection = by_name["promoted_claim_writer_projection"]
        projection_validation = by_name["promoted_claim_projection_validation"]
        consumption = by_name["promoted_claim_writer_consumption"]
        consumption_validation = by_name["promoted_claim_writer_consumption_validation"]
        writer = by_name["promoted_claim_writer"]
        article_gate = by_name["isj_article_deadline_claim_gate"]
        article_validation = by_name["isj_article_deadline_claim_validation"]
        promoted_contract = by_name["isj_promoted_claim_contract"]
        promoted_contract_validation = by_name["isj_promoted_claim_contract_validation"]

        for stage in (consumption, consumption_validation):
            self.assertIn(str(fact_kernel.output), stage.argv)
            self.assertIn(str(fact_integrity.output), stage.argv)
            self.assertIn(str(projection.output), stage.argv)
            self.assertIn(str(projection_validation.output), stage.argv)
            self.assertNotIn("--live", stage.argv)
        self.assertIn(str(consumption.output), consumption_validation.argv)
        self.assertIn("--prove-tamper", consumption_validation.argv)

        self.assertEqual(writer.name, "promoted_claim_writer")
        self.assertIn(str(fact_kernel.output), writer.argv)
        self.assertIn(str(fact_integrity.output), writer.argv)
        self.assertNotIn(str(projection.output), writer.argv)
        self.assertNotIn(str(projection_validation.output), writer.argv)
        self.assertIn("--writer-consumption", writer.argv)
        self.assertIn("--writer-consumption-validation", writer.argv)
        self.assertIn(str(consumption.output), writer.argv)
        self.assertIn(str(consumption_validation.output), writer.argv)

        for stage in (article_gate, article_validation):
            self.assertIn(str(fact_kernel.output), stage.argv)
            self.assertIn(str(fact_integrity.output), stage.argv)
            self.assertIn(str(consumption.output), stage.argv)
            self.assertIn(str(consumption_validation.output), stage.argv)
            self.assertIn(str(writer.output), stage.argv)
            self.assertNotIn("--live", stage.argv)
        self.assertIn(str(article_gate.output), article_validation.argv)
        self.assertIn("--prove-tamper", article_validation.argv)

        reusable_inputs = (
            by_name["isj_registration_deadline_promotion_validation"].output,
            by_name["isj_fact_kernel_deadline_promotion_validation"].output,
            fact_kernel.output,
            fact_integrity.output,
            projection_validation.output,
            consumption_validation.output,
            article_gate.output,
            article_validation.output,
            by_name["isj_article_integrity"].output,
        )
        for stage in (promoted_contract, promoted_contract_validation):
            for prior in reusable_inputs:
                self.assertIn(str(prior), stage.argv)
            self.assertNotIn("--live", stage.argv)
        self.assertIn(str(promoted_contract.output), promoted_contract_validation.argv)
        self.assertIn("--prove-tamper", promoted_contract_validation.argv)

        chain = [
            "isj_fact_kernel", "isj_fact_kernel_integrity", "promoted_claim_writer_projection",
            "promoted_claim_projection_validation", "promoted_claim_writer_consumption",
            "promoted_claim_writer_consumption_validation", "promoted_claim_writer", "isj_article_deadline_claim_gate",
            "isj_article_deadline_claim_validation", "isj_article_integrity", "isj_promoted_claim_contract",
            "isj_promoted_claim_contract_validation", "site_verified_article_ledger", "photo_truth",
            "site_visual_runtime_registry", "shadow_site_package",
        ]
        for left, right in zip(chain, chain[1:]):
            self.assertLess(names.index(left), names.index(right))

    def test_source_specific_writer_consumption_is_not_a_canonical_runtime_dependency(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = bounded_cycle_plan(Path(temp), live=False)
        report = _writer_consumption_dependency_snapshot(plan)
        self.assertEqual(report["status"], "PASS_SHADOW")
        self.assertEqual(report["canonical_stage_count"], 42)
        self.assertFalse(report["source_specific_runtime_dependency"])
        self.assertEqual(report["source_specific_runtime_references"], [])
        self.assertTrue(report["source_specific_regression_only"])
        self.assertTrue(report["source_specific_retirement_eligible"])
        self.assertFalse(report["source_specific_retirement_performed"])
        self.assertTrue(report["compatibility_identity_namespace_retained"])
        self.assertTrue(report["compatibility_writer_stage_name_retired"])
        self.assertEqual(report["canonical_writer_stage"], "promoted_claim_writer")
        self.assertEqual(report["canonical_writer_module"], "valcea-clar/core_v2/promoted_claim_writer.py")
        self.assertEqual(report["canonical_writer_consumption_module"], "valcea-clar/core_v2/promoted_claim_writer_consumption.py")
        self.assertEqual(report["canonical_writer_consumption_validation_module"], "valcea-clar/core_v2/validate_promoted_claim_writer_consumption_runtime.py")
        self.assertEqual(report["publication_authority"], "NONE")
        self.assertFalse(report["acceptance_ready"])


if __name__ == "__main__":
    unittest.main()
