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
        source_stage_names = {"apavil", "ipj", "isu", "municipal_reference", "municipal_document", "cj_road", "eta", "isj"}
        for stage in plan:
            if stage.name in source_stage_names:
                self.assertNotIn("--live", stage.argv)


if __name__ == "__main__":
    unittest.main()
