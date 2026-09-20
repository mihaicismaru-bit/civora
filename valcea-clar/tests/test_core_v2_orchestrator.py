import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from orchestrator import bounded_cycle_plan


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
                "isj_fact_kernel", "isj_fact_kernel_integrity", "isj_writer_deadline_projection",
                "isj_writer_deadline_projection_validation", "isj_writer_deadline_consumption",
                "isj_writer_deadline_consumption_validation", "isj_writer", "isj_article_integrity",
                "site_verified_article_ledger", "photo_truth", "site_visual_runtime_registry", "shadow_site_package",
            ],
        )
        self.assertEqual(len(names), 38)
        joined = "\n".join(" ".join(stage.argv) for stage in plan).lower()
        for forbidden in ("workflow_dispatch", "git push", "merge", "deploy", "facebook_publish", "instagram_publish", "manual-publish"):
            self.assertNotIn(forbidden, joined)
        self.assertIn("--external-probe", joined)
        self.assertIn("--live", joined)
        self.assertIn("--prove-tamper", joined)

    def test_non_live_plan_does_not_enable_source_network_reads(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = bounded_cycle_plan(Path(temp), live=False)
        source_stage_names = {"apavil", "ipj", "isu", "municipal_reference", "municipal_document", "cj_road", "eta", "isj", "isj_detail", "isj_embedded_notice", "isj_embedded_target", "isj_embedded_content", "isj_context_documents"}
        for stage in plan:
            if stage.name in source_stage_names:
                self.assertNotIn("--live", stage.argv)

    def test_isj_chain_and_site_ledger_consume_only_prior_shadow_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = bounded_cycle_plan(Path(temp), live=True)
        by_name = {stage.name: stage for stage in plan}
        isj = by_name["isj"]; detail = by_name["isj_detail"]; materiality = by_name["isj_materiality"]
        embedded = by_name["isj_embedded_notice"]; targets = by_name["isj_embedded_target"]; content = by_name["isj_embedded_content"]
        fields = by_name["isj_field_evidence"]; context_docs = by_name["isj_context_documents"]; calendar_fields = by_name["isj_calendar_field_evidence"]
        calendar_scope = by_name["isj_calendar_scope_binding"]; calendar_scope_validation = by_name["isj_calendar_scope_validation"]
        deadline_promotion = by_name["isj_registration_deadline_promotion"]; deadline_validation = by_name["isj_registration_deadline_promotion_validation"]
        field_materiality = by_name["isj_field_materiality"]
        fact_deadline_promotion = by_name["isj_fact_kernel_deadline_promotion"]
        fact_deadline_validation = by_name["isj_fact_kernel_deadline_promotion_validation"]
        fact_kernel = by_name["isj_fact_kernel"]; fact_integrity = by_name["isj_fact_kernel_integrity"]
        writer_projection = by_name["isj_writer_deadline_projection"]
        writer_projection_validation = by_name["isj_writer_deadline_projection_validation"]
        writer_consumption = by_name["isj_writer_deadline_consumption"]
        writer_consumption_validation = by_name["isj_writer_deadline_consumption_validation"]
        writer = by_name["isj_writer"]; article_integrity = by_name["isj_article_integrity"]
        ledger = by_name["site_verified_article_ledger"]; photo = by_name["photo_truth"]
        hydrated_registry = by_name["site_visual_runtime_registry"]; site = by_name["shadow_site_package"]
        ipj = by_name["ipj"]; isu = by_name["isu"]; municipal = by_name["municipal_writer"]

        self.assertIn(str(isj.output), detail.argv); self.assertIn("--live", detail.argv)
        self.assertIn(str(detail.output), materiality.argv); self.assertNotIn("--live", materiality.argv)
        self.assertIn(str(detail.output), embedded.argv); self.assertIn(str(materiality.output), embedded.argv); self.assertIn("--live", embedded.argv)
        self.assertIn(str(embedded.output), targets.argv); self.assertIn("--live", targets.argv)
        self.assertIn(str(targets.output), content.argv); self.assertIn("--live", content.argv)
        self.assertIn(str(content.output), fields.argv); self.assertNotIn("--live", fields.argv)
        self.assertIn(str(targets.output), context_docs.argv); self.assertIn(str(fields.output), context_docs.argv); self.assertIn("2026", context_docs.argv); self.assertIn("--live", context_docs.argv)
        self.assertIn(str(context_docs.output), calendar_fields.argv); self.assertIn("2026", calendar_fields.argv); self.assertNotIn("--live", calendar_fields.argv)
        self.assertIn(str(context_docs.output), calendar_scope.argv); self.assertIn(str(calendar_fields.output), calendar_scope.argv); self.assertNotIn("--live", calendar_scope.argv)
        self.assertIn(str(context_docs.output), calendar_scope_validation.argv); self.assertIn(str(calendar_fields.output), calendar_scope_validation.argv); self.assertIn(str(calendar_scope.output), calendar_scope_validation.argv); self.assertIn("--prove-tamper", calendar_scope_validation.argv)
        self.assertIn(str(calendar_scope.output), deadline_promotion.argv); self.assertIn(str(calendar_scope_validation.output), deadline_promotion.argv)
        self.assertIn(str(calendar_scope.output), deadline_validation.argv); self.assertIn(str(calendar_scope_validation.output), deadline_validation.argv); self.assertIn(str(deadline_promotion.output), deadline_validation.argv); self.assertIn("--prove-tamper", deadline_validation.argv)
        self.assertIn(str(fields.output), field_materiality.argv); self.assertIn(str(calendar_fields.output), field_materiality.argv); self.assertIn(str(deadline_promotion.output), field_materiality.argv); self.assertIn(str(deadline_validation.output), field_materiality.argv)
        self.assertIn(str(field_materiality.output), fact_deadline_promotion.argv); self.assertIn(str(deadline_promotion.output), fact_deadline_promotion.argv); self.assertIn(str(deadline_validation.output), fact_deadline_promotion.argv)
        self.assertIn(str(field_materiality.output), fact_deadline_validation.argv); self.assertIn(str(deadline_promotion.output), fact_deadline_validation.argv); self.assertIn(str(deadline_validation.output), fact_deadline_validation.argv); self.assertIn(str(fact_deadline_promotion.output), fact_deadline_validation.argv); self.assertIn("--prove-tamper", fact_deadline_validation.argv)
        self.assertNotIn(str(fact_deadline_promotion.output), fact_kernel.argv); self.assertNotIn(str(fact_deadline_validation.output), fact_kernel.argv)
        self.assertIn(str(field_materiality.output), fact_kernel.argv); self.assertIn(str(fields.output), fact_kernel.argv); self.assertIn(str(calendar_fields.output), fact_kernel.argv)
        self.assertIn(str(fact_kernel.output), fact_integrity.argv)
        self.assertIn(str(fact_kernel.output), writer_projection.argv); self.assertIn(str(fact_integrity.output), writer_projection.argv); self.assertNotIn("--live", writer_projection.argv)
        self.assertIn(str(fact_kernel.output), writer_projection_validation.argv); self.assertIn(str(fact_integrity.output), writer_projection_validation.argv); self.assertIn(str(writer_projection.output), writer_projection_validation.argv); self.assertIn("--prove-tamper", writer_projection_validation.argv)

        for stage in (writer_consumption, writer_consumption_validation):
            self.assertIn(str(fact_kernel.output), stage.argv)
            self.assertIn(str(fact_integrity.output), stage.argv)
            self.assertIn(str(writer_projection.output), stage.argv)
            self.assertIn(str(writer_projection_validation.output), stage.argv)
            self.assertNotIn("--live", stage.argv)
        self.assertIn(str(writer_consumption.output), writer_consumption_validation.argv)
        self.assertIn("--prove-tamper", writer_consumption_validation.argv)

        self.assertIn(str(fact_kernel.output), writer.argv); self.assertIn(str(fact_integrity.output), writer.argv)
        self.assertNotIn(str(writer_projection.output), writer.argv); self.assertNotIn(str(writer_projection_validation.output), writer.argv)
        self.assertNotIn(str(writer_consumption.output), writer.argv); self.assertNotIn(str(writer_consumption_validation.output), writer.argv)
        self.assertIn(str(fact_kernel.output), article_integrity.argv); self.assertIn(str(fact_integrity.output), article_integrity.argv); self.assertIn(str(writer.output), article_integrity.argv)

        self.assertIn(str(ipj.output), ledger.argv); self.assertIn(str(isu.output), ledger.argv); self.assertIn(str(municipal.output), ledger.argv); self.assertIn(str(writer.output), ledger.argv); self.assertIn(str(article_integrity.output), ledger.argv)
        self.assertNotIn("--live", ledger.argv)
        self.assertIn(f"isj={article_integrity.output}", photo.argv)
        self.assertIn(str(photo.output), hydrated_registry.argv)
        self.assertIn("valcea-clar/core_v2/visual_registry.json", hydrated_registry.argv)
        self.assertNotIn("--live", hydrated_registry.argv)
        self.assertIn(str(ledger.output), site.argv)
        self.assertIn(str(hydrated_registry.output), site.argv)
        self.assertNotIn(str(municipal.output), site.argv)

        names = [stage.name for stage in plan]
        chain = [
            "isj", "isj_detail", "isj_materiality", "isj_embedded_notice", "isj_embedded_target",
            "isj_embedded_content", "isj_field_evidence", "isj_context_documents", "isj_calendar_field_evidence",
            "isj_calendar_scope_binding", "isj_calendar_scope_validation", "isj_registration_deadline_promotion",
            "isj_registration_deadline_promotion_validation", "isj_field_materiality",
            "isj_fact_kernel_deadline_promotion", "isj_fact_kernel_deadline_promotion_validation",
            "isj_fact_kernel", "isj_fact_kernel_integrity", "isj_writer_deadline_projection",
            "isj_writer_deadline_projection_validation", "isj_writer_deadline_consumption",
            "isj_writer_deadline_consumption_validation", "isj_writer", "isj_article_integrity",
            "site_verified_article_ledger", "photo_truth", "site_visual_runtime_registry", "shadow_site_package",
        ]
        for left, right in zip(chain, chain[1:]):
            self.assertLess(names.index(left), names.index(right))


if __name__ == "__main__":
    unittest.main()
