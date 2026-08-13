import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "partener-eu-p11.yml"


class P11CITriggerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_validates_pull_requests_and_merged_main(self):
        self.assertIn("  push:\n    branches: [main]\n    paths:\n", self.workflow)
        self.assertIn("  pull_request:\n    branches: [main]\n    paths:\n", self.workflow)
        self.assertIn("  workflow_dispatch:\n", self.workflow)

    def test_quality_gate_changes_are_in_trigger_scope(self):
        trigger = "      - 'partener-eu/ops/quality_gate.py'"
        self.assertEqual(self.workflow.count(trigger), 2)

    def test_required_fail_closed_replays_remain_mandatory(self):
        required_commands = (
            "python partener-eu/p11/apply_resolutions.py --check",
            "python partener-eu/p11/build_public_projection.py --check",
            "python partener-eu/ops/quality_gate.py",
        )
        for command in required_commands:
            with self.subTest(command=command):
                self.assertIn(command, self.workflow)


if __name__ == "__main__":
    unittest.main()
