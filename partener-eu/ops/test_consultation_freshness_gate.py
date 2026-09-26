#!/usr/bin/env python3
import datetime as dt
import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).with_name("build_public_static_pages.py")
SPEC = importlib.util.spec_from_file_location("build_public_static_pages", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

CLOCK = dt.datetime(2026, 9, 26, 6, 30, tzinfo=dt.timezone.utc)


def consultation(deadline, deadline_confidence="CONFIRMED"):
    return {
        "id": "fixture-consultation",
        "status": "PUBLIC_CONSULTATION",
        "publicationState": "PUBLISHABLE",
        "quickFacts": [
            {"label": "Status", "value": "PUBLIC_CONSULTATION", "confidence": "CONFIRMED"},
            {"label": "Termen", "value": deadline, "confidence": deadline_confidence},
        ],
        "sections": [
            {"title": "Ce trebuie făcut acum", "items": ["Trimite observații în consultare."]}
        ],
    }


class ConsultationFreshnessGateTest(unittest.TestCase):
    def test_expired_consultation_fails_closed_to_review(self):
        dossier = consultation("8 septembrie 2026")
        self.assertFalse(MODULE.current_consultation(dossier, CLOCK))
        rendered = MODULE.fail_closed_render_dossier(dossier, CLOCK)
        self.assertEqual(rendered["status"], "REVIEW")
        self.assertEqual(rendered["decision"], "VERIFY")
        self.assertEqual(dossier["status"], "PUBLIC_CONSULTATION")

    def test_unknown_deadline_cannot_be_active_consultation(self):
        dossier = consultation("Neconfirmat")
        self.assertFalse(MODULE.current_consultation(dossier, CLOCK))
        rendered = MODULE.fail_closed_render_dossier(dossier, CLOCK)
        self.assertEqual(rendered["status"], "REVIEW")

    def test_confirmed_future_consultation_remains_active(self):
        dossier = consultation("29 septembrie 2026")
        self.assertTrue(MODULE.current_consultation(dossier, CLOCK))
        self.assertIs(MODULE.fail_closed_render_dossier(dossier, CLOCK), dossier)


if __name__ == "__main__":
    unittest.main()
