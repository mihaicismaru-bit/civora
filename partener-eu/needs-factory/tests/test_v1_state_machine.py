import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.civora_provider import CivoraCommandProvider
from adapters.semantic_provider import CommandNeedDecisionProvider
from core.v1_state_machine import plan_needs_analysis, resume_needs_analysis


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


class NeedsFactoryV1StateMachineTests(unittest.TestCase):
    def _load_json(self, path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    def test_plan_blocks_then_resume_reaches_noncanonical_dape_handoff(self):
        intake = self._load_json(FIXTURES / "research_intake_synthetic.json")
        resume_fixture = self._load_json(FIXTURES / "primary_research_resume.json")
        research_profile = self._load_json(ROOT / intake["profile"])
        synthesis_policy = self._load_json(ROOT / "profiles" / "peo_ipt_need_synthesis.json")

        discovery_provider = CivoraCommandProvider(
            [sys.executable, str(FIXTURES / "fake_civora_provider.py")]
        )
        semantic_provider = CommandNeedDecisionProvider(
            [sys.executable, str(FIXTURES / "fake_semantic_need_provider.py")]
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            plan = plan_needs_analysis(
                intake["project_input"],
                intake["call_record"],
                research_profile,
                discovery_provider,
                historical_cutoff=intake["historical_cutoff"],
                research_pack_dir=tmp_root / "research_pack",
            )

            self.assertEqual(plan["state"], "BLOCKED_RESEARCH")
            self.assertEqual(plan["phase"], "PLAN")
            self.assertTrue(plan["research_pack_manifest"])
            self.assertTrue((tmp_root / "research_pack" / "PRIMARY_RESEARCH_PACK.zip").exists())
            self.assertNotIn("NF07_NEED_DISCOVERY", set(plan["run_manifest"]["closed_checkpoints"]))
            self.assertTrue(any(gap.get("gap_type") == "population_snapshot" for gap in plan["evidence_gaps"]["gaps"]))

            result = resume_needs_analysis(
                plan,
                resume_fixture["resolved_population_snapshot"],
                resume_fixture["raw_responses"],
                synthesis_policy,
                semantic_provider,
                output_root=tmp_root / "release",
            )

            self.assertEqual(result["state"], "HANDOFF_READY_NOT_CANONICAL")
            self.assertEqual(result["phase"], "RESUME")
            self.assertNotEqual(result["predecessor_run_id"], result["successor_run_id"])
            self.assertTrue(result["population_validation"]["valid"])
            self.assertEqual(result["semantic_decisions"]["state"], "READY_FOR_RANKING")
            self.assertFalse(result["ranked_needs"]["blocked"])
            self.assertTrue(result["release_gate"]["ready_for_narrative"])

            final_dir = tmp_root / "release" / "final"
            self.assertTrue((final_dir / "ANALIZA_NEVOI.docx").exists())
            self.assertTrue((final_dir / "FINAL_PACKAGE.zip").exists())

            handoff = result["dape_handoff"]
            self.assertEqual(handoff["state"], "HANDOFF_READY_NOT_CANONICAL")
            self.assertFalse(handoff["canonical"])
            self.assertTrue(handoff["host_action_required"])
            self.assertEqual(handoff["artifact_count"], 7)
            dape_dir = tmp_root / "release" / "dape_checkpoint"
            for artifact in handoff["artifacts"]:
                self.assertTrue((dape_dir / artifact).exists(), artifact)

            self.assertIn("NF12_PACKAGE", set(result["run_manifest"]["closed_checkpoints"]))
            self.assertEqual(result["run_manifest"]["checkpoint_status"]["NF09_CAUSAL_MODEL"], "NOT_REQUIRED")
            self.assertEqual(result["run_manifest"]["checkpoint_status"]["NF10_INTERVENTION_TRACEABILITY"], "NOT_REQUIRED")

    def test_invalid_primary_research_never_reaches_semantic_or_release(self):
        intake = self._load_json(FIXTURES / "research_intake_synthetic.json")
        resume_fixture = self._load_json(FIXTURES / "primary_research_resume.json")
        research_profile = self._load_json(ROOT / intake["profile"])
        synthesis_policy = self._load_json(ROOT / "profiles" / "peo_ipt_need_synthesis.json")
        discovery_provider = CivoraCommandProvider(
            [sys.executable, str(FIXTURES / "fake_civora_provider.py")]
        )
        semantic_provider = CommandNeedDecisionProvider(
            [sys.executable, str(FIXTURES / "fake_semantic_need_provider.py")]
        )

        broken_population = dict(resume_fixture["resolved_population_snapshot"])
        broken_population["eligible_population_n"] = 999

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            plan = plan_needs_analysis(
                intake["project_input"],
                intake["call_record"],
                research_profile,
                discovery_provider,
                historical_cutoff=intake["historical_cutoff"],
            )
            result = resume_needs_analysis(
                plan,
                broken_population,
                resume_fixture["raw_responses"],
                synthesis_policy,
                semantic_provider,
                output_root=tmp_root,
            )

            self.assertEqual(result["state"], "BLOCKED_RESEARCH_VALIDATION")
            self.assertFalse(result["research_resolution"]["valid"])
            self.assertNotIn("NF07_NEED_DISCOVERY", set(result["run_manifest"]["closed_checkpoints"]))
            self.assertFalse((tmp_root / "final" / "ANALIZA_NEVOI.docx").exists())
            self.assertFalse((tmp_root / "dape_checkpoint" / "CHECKPOINT_MANIFEST.json").exists())


if __name__ == "__main__":
    unittest.main()
