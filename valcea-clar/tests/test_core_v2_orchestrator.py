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
                "isj_context_documents", "isj_calendar_field_evidence", "isj_field_materiality", "isj_fact_kernel",
                "isj_fact_kernel_integrity", "isj_writer", "isj_article_integrity", "photo_truth", "shadow_site_package",
            ],
        )
        joined = "\n".join(" ".join(stage.argv) for stage in plan).lower()
        for forbidden in ("workflow_dispatch", "git push", "merge", "deploy", "facebook_publish", "instagram_publish", "manual-publish"):
            self.assertNotIn(forbidden, joined)
        self.assertIn("--external-probe", joined)
        self.assertIn("--live", joined)

    def test_non_live_plan_does_not_enable_source_network_reads(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = bounded_cycle_plan(Path(temp), live=False)
        source_stage_names = {"apavil", "ipj", "isu", "municipal_reference", "municipal_document", "cj_road", "eta", "isj", "isj_detail", "isj_embedded_notice", "isj_embedded_target", "isj_embedded_content", "isj_context_documents"}
        for stage in plan:
            if stage.name in source_stage_names:
                self.assertNotIn("--live", stage.argv)

    def test_isj_chain_consumes_only_prior_shadow_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = bounded_cycle_plan(Path(temp), live=True)
        by_name = {stage.name: stage for stage in plan}
        isj = by_name["isj"]; detail = by_name["isj_detail"]; materiality = by_name["isj_materiality"]
        embedded = by_name["isj_embedded_notice"]; targets = by_name["isj_embedded_target"]; content = by_name["isj_embedded_content"]
        fields = by_name["isj_field_evidence"]; context_docs = by_name["isj_context_documents"]; calendar_fields = by_name["isj_calendar_field_evidence"]
        field_materiality = by_name["isj_field_materiality"]; fact_kernel = by_name["isj_fact_kernel"]; fact_integrity = by_name["isj_fact_kernel_integrity"]
        writer = by_name["isj_writer"]; article_integrity = by_name["isj_article_integrity"]

        self.assertIn(str(isj.output), detail.argv); self.assertIn("--live", detail.argv)
        self.assertIn(str(detail.output), materiality.argv); self.assertNotIn("--live", materiality.argv)
        self.assertIn(str(detail.output), embedded.argv); self.assertIn(str(materiality.output), embedded.argv); self.assertIn("--live", embedded.argv)
        self.assertIn(str(embedded.output), targets.argv); self.assertIn("--live", targets.argv)
        self.assertIn(str(targets.output), content.argv); self.assertIn("--live", content.argv)
        self.assertIn(str(content.output), fields.argv); self.assertNotIn("--live", fields.argv)
        self.assertIn(str(targets.output), context_docs.argv); self.assertIn(str(fields.output), context_docs.argv); self.assertIn("2026", context_docs.argv); self.assertIn("--live", context_docs.argv)
        self.assertIn(str(context_docs.output), calendar_fields.argv); self.assertIn("2026", calendar_fields.argv); self.assertNotIn("--live", calendar_fields.argv)
        self.assertIn(str(fields.output), field_materiality.argv); self.assertIn(str(calendar_fields.output), field_materiality.argv); self.assertIn("2026", field_materiality.argv); self.assertNotIn("--live", field_materiality.argv)
        self.assertIn(str(field_materiality.output), fact_kernel.argv); self.assertIn(str(fields.output), fact_kernel.argv); self.assertIn(str(calendar_fields.output), fact_kernel.argv); self.assertNotIn("--live", fact_kernel.argv)
        self.assertIn(str(fact_kernel.output), fact_integrity.argv); self.assertNotIn("--live", fact_integrity.argv)
        self.assertIn(str(fact_kernel.output), writer.argv); self.assertIn(str(fact_integrity.output), writer.argv); self.assertNotIn("--live", writer.argv)
        self.assertIn(str(fact_kernel.output), article_integrity.argv); self.assertIn(str(fact_integrity.output), article_integrity.argv); self.assertIn(str(writer.output), article_integrity.argv); self.assertNotIn("--live", article_integrity.argv)

        names = [stage.name for stage in plan]
        chain = ["isj", "isj_detail", "isj_materiality", "isj_embedded_notice", "isj_embedded_target", "isj_embedded_content", "isj_field_evidence", "isj_context_documents", "isj_calendar_field_evidence", "isj_field_materiality", "isj_fact_kernel", "isj_fact_kernel_integrity", "isj_writer", "isj_article_integrity", "photo_truth"]
        for left, right in zip(chain, chain[1:]):
            self.assertLess(names.index(left), names.index(right))


if __name__ == "__main__":
    unittest.main()
