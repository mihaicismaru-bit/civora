import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from orchestrator import (
    bounded_cycle_plan,
    _writer_consumption_dependency_snapshot,
    _article_truth_stage_ownership_snapshot,
    _promoted_claim_contract_stage_ownership_snapshot,
    _owned_article_truth_stages,
    _owned_promoted_claim_contract_stages,
    _LEGACY_PLAN,
)


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

    def test_owned_article_truth_definitions_match_frozen_run70_semantics(self):
        with tempfile.TemporaryDirectory() as temp:
            workdir = Path(temp)
            frozen_by_name = {stage.name: stage for stage in _LEGACY_PLAN(workdir, live=False)}
            owned_by_name = {stage.name: stage for stage in _owned_article_truth_stages(workdir)}
            canonical_plan = bounded_cycle_plan(workdir, live=False)

        old_consumption = "valcea-core-v2-isj-writer-deadline-consumption.json"
        new_consumption = "valcea-core-v2-promoted-claim-writer-consumption.json"
        old_validation = "valcea-core-v2-isj-writer-deadline-consumption-validation.json"
        new_validation = "valcea-core-v2-promoted-claim-writer-consumption-validation.json"

        def normalized(stage):
            argv = tuple(
                str(token)
                .replace(old_validation, new_validation)
                .replace(old_consumption, new_consumption)
                for token in stage.argv
            )
            output = (
                str(stage.output)
                .replace(old_validation, new_validation)
                .replace(old_consumption, new_consumption)
                if stage.output is not None
                else None
            )
            return stage.name, argv, output

        for name in (
            "isj_article_deadline_claim_gate",
            "isj_article_deadline_claim_validation",
            "isj_article_integrity",
        ):
            self.assertIn(name, frozen_by_name)
            self.assertIn(name, owned_by_name)
            self.assertEqual(normalized(frozen_by_name[name]), normalized(owned_by_name[name]))

        validation = owned_by_name["isj_article_deadline_claim_validation"]
        self.assertIn("--prove-tamper", validation.argv)
        report = _article_truth_stage_ownership_snapshot(canonical_plan)
        self.assertEqual(report["status"], "PASS_SHADOW")
        self.assertEqual(report["canonical_stage_count"], 42)
        self.assertEqual(report["canonical_stage_ownership"], "CORE_V2_ORCHESTRATOR_DIRECT_DEFINITION")
        self.assertFalse(report["frozen_run70_article_truth_placeholder_definitions_consumed"])
        self.assertTrue(report["source_specific_truth_modules_retained"])
        self.assertTrue(report["source_specific_truth_stage_names_retained"])
        self.assertTrue(report["artifact_identities_retained"])
        self.assertFalse(report["retirement_eligible"])
        self.assertFalse(report["retirement_performed"])
        self.assertEqual(report["publication_authority"], "NONE")
        self.assertFalse(report["acceptance_ready"])

    def test_source_neutral_article_truth_cli_stage_definition_equivalence_before_switch(self):
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
        source_neutral_cli = "valcea-clar/core_v2/promoted_claim_article_truth.py"

        proposed_gate_argv = (
            sys.executable,
            source_neutral_cli,
            "--mode", "gate",
            "--fact-kernel", str(fact_kernel),
            "--fact-kernel-integrity", str(fact_integrity),
            "--writer-consumption", str(consumption),
            "--writer-consumption-validation", str(consumption_validation),
            "--article", str(article),
            "--output", str(claim),
        )
        proposed_validation_argv = (
            sys.executable,
            source_neutral_cli,
            "--mode", "validate",
            "--fact-kernel", str(fact_kernel),
            "--fact-kernel-integrity", str(fact_integrity),
            "--writer-consumption", str(consumption),
            "--writer-consumption-validation", str(consumption_validation),
            "--article", str(article),
            "--gate", str(claim),
            "--prove-tamper",
            "--output", str(claim_validation),
        )

        def option_contract(argv, *, ignore_mode=False):
            pairs = []
            index = 2
            while index < len(argv):
                token = argv[index]
                if token == "--prove-tamper":
                    pairs.append((token, True))
                    index += 1
                    continue
                self.assertTrue(token.startswith("--"), f"unexpected positional token: {token}")
                self.assertLess(index + 1, len(argv), f"missing value for {token}")
                value = argv[index + 1]
                if not (ignore_mode and token == "--mode"):
                    pairs.append((token, value))
                index += 2
            return tuple(pairs)

        self.assertEqual(len(plan), 42)
        self.assertEqual(gate.name, "isj_article_deadline_claim_gate")
        self.assertEqual(validation.name, "isj_article_deadline_claim_validation")
        self.assertEqual(gate.argv[1], "valcea-clar/core_v2/isj_article_deadline_claim_gate.py")
        self.assertEqual(validation.argv[1], "valcea-clar/core_v2/validate_isj_article_deadline_claim_gate.py")
        self.assertNotEqual(gate.argv[1], source_neutral_cli)
        self.assertNotEqual(validation.argv[1], source_neutral_cli)
        self.assertEqual(gate.output, claim)
        self.assertEqual(validation.output, claim_validation)

        self.assertEqual(option_contract(gate.argv), option_contract(proposed_gate_argv, ignore_mode=True))
        self.assertEqual(option_contract(validation.argv), option_contract(proposed_validation_argv, ignore_mode=True))
        self.assertEqual(proposed_gate_argv[2:4], ("--mode", "gate"))
        self.assertEqual(proposed_validation_argv[2:4], ("--mode", "validate"))
        self.assertIn("--gate", proposed_validation_argv)
        self.assertIn(str(claim), proposed_validation_argv)
        self.assertIn("--prove-tamper", proposed_validation_argv)
        self.assertNotIn("--live", proposed_gate_argv)
        self.assertNotIn("--live", proposed_validation_argv)

        writer_index = names.index("promoted_claim_writer")
        gate_index = names.index("isj_article_deadline_claim_gate")
        validation_index = names.index("isj_article_deadline_claim_validation")
        integrity_index = names.index("isj_article_integrity")
        self.assertEqual(gate_index, writer_index + 1)
        self.assertEqual(validation_index, gate_index + 1)
        self.assertEqual(integrity_index, validation_index + 1)
        self.assertEqual(integrity.output, workdir / "valcea-core-v2-isj-article-integrity-shadow.json")

        canonical_joined = "\n".join(" ".join(stage.argv) for stage in plan)
        self.assertNotIn(source_neutral_cli, canonical_joined)
        ownership = _article_truth_stage_ownership_snapshot(plan)
        self.assertEqual(ownership["status"], "PASS_SHADOW")
        self.assertEqual(ownership["canonical_stage_count"], 42)
        self.assertEqual(ownership["publication_authority"], "NONE")
        self.assertFalse(ownership["acceptance_ready"])
        self.assertFalse(ownership["retirement_eligible"])
        self.assertFalse(ownership["retirement_performed"])

    def test_owned_promoted_claim_contract_definitions_match_frozen_run70_semantics(self):
        with tempfile.TemporaryDirectory() as temp:
            workdir = Path(temp)
            frozen_by_name = {stage.name: stage for stage in _LEGACY_PLAN(workdir, live=False)}
            owned_by_name = {stage.name: stage for stage in _owned_promoted_claim_contract_stages(workdir)}
            canonical_plan = bounded_cycle_plan(workdir, live=False)

        old_validation = "valcea-core-v2-isj-writer-deadline-consumption-validation.json"
        new_validation = "valcea-core-v2-promoted-claim-writer-consumption-validation.json"

        def normalized(stage):
            argv = tuple(str(token).replace(old_validation, new_validation) for token in stage.argv)
            output = str(stage.output).replace(old_validation, new_validation) if stage.output is not None else None
            return stage.name, argv, output

        for name in ("isj_promoted_claim_contract", "isj_promoted_claim_contract_validation"):
            self.assertIn(name, frozen_by_name)
            self.assertIn(name, owned_by_name)
            self.assertEqual(normalized(frozen_by_name[name]), normalized(owned_by_name[name]))

        validation = owned_by_name["isj_promoted_claim_contract_validation"]
        self.assertIn("--prove-tamper", validation.argv)
        report = _promoted_claim_contract_stage_ownership_snapshot(canonical_plan)
        self.assertEqual(report["status"], "PASS_SHADOW")
        self.assertEqual(report["canonical_stage_count"], 42)
        self.assertEqual(report["canonical_stage_ownership"], "CORE_V2_ORCHESTRATOR_DIRECT_DEFINITION")
        self.assertFalse(report["frozen_run70_promoted_claim_contract_placeholder_definitions_consumed"])
        self.assertTrue(report["source_specific_contract_modules_retained"])
        self.assertTrue(report["source_specific_contract_stage_names_retained"])
        self.assertTrue(report["artifact_identities_retained"])
        self.assertTrue(report["lineage_inputs_retained"])
        self.assertFalse(report["retirement_eligible"])
        self.assertFalse(report["retirement_performed"])
        self.assertEqual(report["publication_authority"], "NONE")
        self.assertFalse(report["acceptance_ready"])


if __name__ == "__main__":
    unittest.main()
