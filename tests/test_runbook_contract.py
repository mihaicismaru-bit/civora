import unittest

from civora.cli import build_parser


class OperatorRunbookContractTests(unittest.TestCase):
    REQUIRED_COMMANDS = {
        "health",
        "dead-letters",
        "resolve-dead-letter",
        "recovery-events",
        "transaction",
        "resolution-audit",
        "editorial-consistency",
        "editorial-story",
        "authorized-story",
        "approval-cases",
        "approval-case",
        "decide-approval",
        "resume-approved",
    }

    def test_runbook_commands_are_registered_in_primary_cli(self):
        parser = build_parser()
        subparser_actions = [
            action for action in parser._actions
            if action.__class__.__name__ == "_SubParsersAction"
        ]
        self.assertEqual(len(subparser_actions), 1)
        available = set(subparser_actions[0].choices)
        self.assertTrue(
            self.REQUIRED_COMMANDS.issubset(available),
            self.REQUIRED_COMMANDS - available,
        )

    def test_primary_cli_retains_documented_exit_code_contract(self):
        from civora import cli

        self.assertEqual(cli.EXIT_OK, 0)
        self.assertEqual(cli.EXIT_UNHEALTHY, 2)
        self.assertEqual(cli.EXIT_ERROR, 3)

    def test_remediation_cli_retains_documented_exit_code_contract(self):
        from civora import remediation_cli

        self.assertEqual(remediation_cli.EXIT_OK, 0)
        self.assertEqual(remediation_cli.EXIT_ACTION_REQUIRED, 2)
        self.assertEqual(remediation_cli.EXIT_ERROR, 3)


if __name__ == "__main__":
    unittest.main()
