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
                "apavil",
                "ipj",
                "isu",
                "municipal_reference",
                "municipal_document",
                "municipal_materiality",
                "municipal_fact_kernel",
                "municipal_writer",
                "cj_road",
                "eta",
                "isj",
                "isj_detail",
                "isj_materiality",
                "isj_embedded_notice",
                "isj_embedded_target",
                "isj_embedded_content",
                "photo_truth",
                "shadow_site_package",
            ],
        )
        joined = "\n".join(" ".join(stage.argv) for stage in plan).lower()
        for forbidden in (
            "workflow_dispatch",
            "git push",
            "merge",
            "deploy",
            "facebook_publish",
            "instagram_publish",
            "manual-publish",
        ):
            self.assertNotIn(forbidden, joined)
        self.assertIn("--external-probe", joined)
        self.assertIn("--live", joined)

    def test_non_live_plan_does_not_enable_source_network_reads(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = bounded_cycle_plan(Path(temp), live=False)
        source_stage_names = {
            "apavil",
            "ipj",
            "isu",
            "municipal_reference",
            "municipal_document",
            "cj_road",
            "eta",
            "isj",
            "isj_detail",
            "isj_embedded_notice",
            "isj_embedded_target",
            "isj_embedded_content",
        }
        for stage in plan:
            if stage.name in source_stage_names:
                self.assertNotIn("--live", stage.argv)

    def test_isj_document_chain_consumes_only_prior_shadow_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = bounded_cycle_plan(Path(temp), live=True)
        by_name = {stage.name: stage for stage in plan}
        isj = by_name["isj"]
        detail = by_name["isj_detail"]
        materiality = by_name["isj_materiality"]
        embedded = by_name["isj_embedded_notice"]
        targets = by_name["isj_embedded_target"]
        content = by_name["isj_embedded_content"]
        self.assertIsNotNone(isj.output)
        self.assertIsNotNone(detail.output)
        self.assertIn("--input", detail.argv)
        self.assertIn(str(isj.output), detail.argv)
        self.assertIn("--live", detail.argv)
        self.assertIn("--input", materiality.argv)
        self.assertIn(str(detail.output), materiality.argv)
        self.assertNotIn("--live", materiality.argv)
        self.assertIn("--details", embedded.argv)
        self.assertIn(str(detail.output), embedded.argv)
        self.assertIn("--materiality", embedded.argv)
        self.assertIn(str(materiality.output), embedded.argv)
        self.assertIn("--live", embedded.argv)
        self.assertIn("--embedded", targets.argv)
        self.assertIn(str(embedded.output), targets.argv)
        self.assertIn("--live", targets.argv)
        self.assertIn("--targets", content.argv)
        self.assertIn(str(targets.output), content.argv)
        self.assertIn("--live", content.argv)
        names = [stage.name for stage in plan]
        self.assertLess(names.index("isj"), names.index("isj_detail"))
        self.assertLess(names.index("isj_detail"), names.index("isj_materiality"))
        self.assertLess(names.index("isj_materiality"), names.index("isj_embedded_notice"))
        self.assertLess(names.index("isj_embedded_notice"), names.index("isj_embedded_target"))
        self.assertLess(names.index("isj_embedded_target"), names.index("isj_embedded_content"))
        self.assertLess(names.index("isj_embedded_content"), names.index("photo_truth"))


if __name__ == "__main__":
    unittest.main()
