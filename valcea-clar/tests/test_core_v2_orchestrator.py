import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

import test_core_v2_orchestrator_run94 as frozen
from orchestrator import (
    bounded_cycle_plan,
    _article_truth_stage_ownership_snapshot,
    _article_integrity_stage_ownership_snapshot,
    _owned_article_truth_stages,
    _LEGACY_PLAN,
)


class BoundedOrchestratorPlanTest(frozen.BoundedOrchestratorPlanTest):
    def test_neutral_writer_article_truth_chain_uses_only_prior_shadow_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            workdir = Path(temp)
            plan = bounded_cycle_plan(workdir, live=True)

        by_name = {stage.name: stage for stage in plan}
        names = [stage.name for stage in plan]
        fact_kernel = by_name["isj_fact_kernel"]
        fact_integrity = by_name["isj_fact_kernel_integrity"]
        consumption = by_name["promoted_claim_writer_consumption"]
        consumption_validation = by_name["promoted_claim_writer_consumption_validation"]
        writer = by_name["promoted_claim_writer"]
        gate = by_name["isj_article_deadline_claim_gate"]
        validation = by_name["isj_article_deadline_claim_validation"]
        integrity = by_name["isj_article_integrity"]

        self.assertEqual(len(plan), 42)
        self.assertEqual(writer.argv[1], "valcea-clar/core_v2/promoted_claim_writer.py")
        for stage in (gate, validation):
            self.assertEqual(stage.argv[1], "valcea-clar/core_v2/promoted_claim_article_truth.py")
            self.assertIn(str(fact_kernel.output), stage.argv)
            self.assertIn(str(fact_integrity.output), stage.argv)
            self.assertIn(str(consumption.output), stage.argv)
            self.assertIn(str(consumption_validation.output), stage.argv)
            self.assertIn(str(writer.output), stage.argv)
            self.assertNotIn("--live", stage.argv)

        self.assertEqual(integrity.argv[1], "valcea-clar/core_v2/promoted_claim_article_integrity.py")
        self.assertIn(str(fact_kernel.output), integrity.argv)
        self.assertIn(str(fact_integrity.output), integrity.argv)
        self.assertIn(str(writer.output), integrity.argv)
        self.assertNotIn("--live", integrity.argv)
        self.assertEqual(integrity.output, workdir / "valcea-core-v2-isj-article-integrity-shadow.json")

        writer_index = names.index("promoted_claim_writer")
        gate_index = names.index("isj_article_deadline_claim_gate")
        validation_index = names.index("isj_article_deadline_claim_validation")
        integrity_index = names.index("isj_article_integrity")
        self.assertEqual((gate_index, validation_index, integrity_index), (writer_index + 1, writer_index + 2, writer_index + 3))

    def test_retained_article_truth_implementations_remain_regression_components(self):
        with tempfile.TemporaryDirectory() as temp:
            workdir = Path(temp)
            frozen_by_name = {stage.name: stage for stage in _LEGACY_PLAN(workdir, live=False)}
            retained_by_name = {stage.name: stage for stage in _owned_article_truth_stages(workdir)}
            canonical_plan = bounded_cycle_plan(workdir, live=False)

        old_consumption = "valcea-core-v2-isj-writer-deadline-consumption.json"
        new_consumption = "valcea-core-v2-promoted-claim-writer-consumption.json"
        old_validation = "valcea-core-v2-isj-writer-deadline-consumption-validation.json"
        new_validation = "valcea-core-v2-promoted-claim-writer-consumption-validation.json"

        def normalized(stage):
            argv = tuple(
                str(token).replace(old_validation, new_validation).replace(old_consumption, new_consumption)
                for token in stage.argv
            )
            output = (
                str(stage.output).replace(old_validation, new_validation).replace(old_consumption, new_consumption)
                if stage.output is not None else None
            )
            return stage.name, argv, output

        for name in (
            "isj_article_deadline_claim_gate",
            "isj_article_deadline_claim_validation",
            "isj_article_integrity",
        ):
            self.assertEqual(normalized(frozen_by_name[name]), normalized(retained_by_name[name]))

        report = _article_truth_stage_ownership_snapshot(canonical_plan)
        self.assertEqual(report["status"], "PASS_SHADOW")
        self.assertEqual(report["canonical_stage_count"], 42)
        self.assertEqual(report["canonical_stage_ownership"], "CORE_V2_ORCHESTRATOR_DIRECT_DEFINITION")
        self.assertTrue(report["canonical_article_truth_runtime_switched"])
        self.assertTrue(report["canonical_article_integrity_runtime_switched"])
        self.assertTrue(report["canonical_stage_definitions_switched"])
        self.assertTrue(report["retained_implementations_regression_only"])
        self.assertFalse(report["retained_implementations_runtime_dependency"])
        self.assertFalse(report["retained_implementations_retirement_eligible"])
        self.assertFalse(report["retirement_eligible"])
        self.assertFalse(report["retirement_performed"])
        self.assertEqual(report["retirement_authority"], "NONE")
        self.assertEqual(report["publication_authority"], "NONE")
        self.assertFalse(report["acceptance_ready"])

        integrity = _article_integrity_stage_ownership_snapshot(canonical_plan)
        self.assertEqual(integrity["status"], "PASS_SHADOW")
        self.assertTrue(integrity["canonical_runtime_switched"])
        self.assertTrue(integrity["source_neutral_facade_present_in_canonical_plan"])
        self.assertFalse(integrity["retained_integrity_runtime_dependency"])
        self.assertTrue(integrity["retained_integrity_regression_component"])
        self.assertFalse(integrity["retained_integrity_retirement_eligible"])
        self.assertEqual(integrity["publication_authority"], "NONE")
        self.assertFalse(integrity["acceptance_ready"])

    def test_source_neutral_article_truth_cli_is_canonical_one_for_one_switch(self):
        with tempfile.TemporaryDirectory() as temp:
            workdir = Path(temp)
            plan = bounded_cycle_plan(workdir, live=False)

        by_name = {stage.name: stage for stage in plan}
        names = [stage.name for stage in plan]
        gate = by_name["isj_article_deadline_claim_gate"]
        validation = by_name["isj_article_deadline_claim_validation"]
        integrity = by_name["isj_article_integrity"]

        fact_kernel = workdir / "valcea-core-v2-isj-fact-kernel-shadow.json"
        fact_integrity = workdir / "valcea-core-v2-isj-fact-kernel-integrity-shadow.json"
        consumption = workdir / "valcea-core-v2-promoted-claim-writer-consumption.json"
        consumption_validation = workdir / "valcea-core-v2-promoted-claim-writer-consumption-validation.json"
        article = workdir / "valcea-core-v2-isj-article-shadow.json"
        claim = workdir / "valcea-core-v2-isj-article-deadline-claim.json"
        claim_validation = workdir / "valcea-core-v2-isj-article-deadline-claim-validation.json"
        integrity_output = workdir / "valcea-core-v2-isj-article-integrity-shadow.json"
        truth_cli = "valcea-clar/core_v2/promoted_claim_article_truth.py"
        integrity_cli = "valcea-clar/core_v2/promoted_claim_article_integrity.py"

        expected_gate_argv = (
            sys.executable, truth_cli, "--mode", "gate",
            "--fact-kernel", str(fact_kernel),
            "--fact-kernel-integrity", str(fact_integrity),
            "--writer-consumption", str(consumption),
            "--writer-consumption-validation", str(consumption_validation),
            "--article", str(article),
            "--output", str(claim),
        )
        expected_validation_argv = (
            sys.executable, truth_cli, "--mode", "validate",
            "--fact-kernel", str(fact_kernel),
            "--fact-kernel-integrity", str(fact_integrity),
            "--writer-consumption", str(consumption),
            "--writer-consumption-validation", str(consumption_validation),
            "--article", str(article),
            "--gate", str(claim),
            "--prove-tamper",
            "--output", str(claim_validation),
        )
        expected_integrity_argv = (
            sys.executable, integrity_cli,
            "--fact-kernel", str(fact_kernel),
            "--fact-kernel-integrity", str(fact_integrity),
            "--article", str(article),
            "--output", str(integrity_output),
        )

        self.assertEqual(len(plan), 42)
        self.assertEqual(gate.argv, expected_gate_argv)
        self.assertEqual(validation.argv, expected_validation_argv)
        self.assertEqual(integrity.argv, expected_integrity_argv)
        self.assertEqual(gate.output, claim)
        self.assertEqual(validation.output, claim_validation)
        self.assertEqual(integrity.output, integrity_output)

        writer_index = names.index("promoted_claim_writer")
        gate_index = names.index("isj_article_deadline_claim_gate")
        validation_index = names.index("isj_article_deadline_claim_validation")
        integrity_index = names.index("isj_article_integrity")
        self.assertEqual((gate_index, validation_index, integrity_index), (writer_index + 1, writer_index + 2, writer_index + 3))

        canonical_joined = "\n".join(" ".join(stage.argv) for stage in plan)
        self.assertIn(truth_cli, canonical_joined)
        self.assertIn(integrity_cli, canonical_joined)
        self.assertNotIn("valcea-clar/core_v2/isj_article_deadline_claim_gate.py", canonical_joined)
        self.assertNotIn("valcea-clar/core_v2/validate_isj_article_deadline_claim_gate.py", canonical_joined)
        self.assertNotIn("valcea-clar/core_v2/isj_article_integrity.py", canonical_joined)


if __name__ == "__main__":
    unittest.main()
