from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from prod_activation_gate import REQUIRED_EXTERNAL_KEYS, evaluate_repository_activation


HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "PROD_ACTIVATION_MANIFEST_DRAFT.json"
SERVER_LOGGING = HERE / "SERVER_LOGGING_BINDING_DRAFT.json"


class ProdLoggingGateSplitTests(unittest.TestCase):
    def test_provider_profile_is_frozen_but_live_account_binding_remains_open(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        evidence = manifest["required_external_or_operational_evidence"]

        self.assertIn("provider_server_logging_profile", REQUIRED_EXTERNAL_KEYS)
        self.assertIn("account_server_logging_binding", REQUIRED_EXTERNAL_KEYS)
        self.assertNotIn("server_logging_profile", REQUIRED_EXTERNAL_KEYS)

        provider = evidence["provider_server_logging_profile"]
        self.assertEqual(provider["status"], "FROZEN")
        self.assertEqual(provider["reference"], "SERVER_LOGGING_BINDING_DRAFT.json")
        self.assertEqual(
            provider["sha256"],
            hashlib.sha256(SERVER_LOGGING.read_bytes()).hexdigest(),
        )

        account = evidence["account_server_logging_binding"]
        self.assertEqual(account["status"], "OPEN")
        self.assertIsNone(account["reference"])
        self.assertIsNone(account["sha256"])

        ready, errors = evaluate_repository_activation()
        self.assertFalse(ready)
        self.assertIn("external_evidence_not_frozen:account_server_logging_binding", errors)
        self.assertNotIn("external_evidence_not_frozen:provider_server_logging_profile", errors)


if __name__ == "__main__":
    unittest.main()
