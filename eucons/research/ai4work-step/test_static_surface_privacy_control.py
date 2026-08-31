from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from build_research_pages import build
from static_surface_privacy_control import ALLOWED_RESEARCH_API, run_control, validate_page


class StaticSurfacePrivacyControlTests(unittest.TestCase):
    def test_current_candidate_has_only_first_party_submission_egress(self) -> None:
        result = run_control()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["classification"], "CONTROL_ONLY_NOT_EVIDENCE")
        self.assertEqual(result["allowed_network_egress"], [ALLOWED_RESEARCH_API])
        self.assertEqual(result["browser_storage_hits"], [])
        self.assertTrue(result["recruitment_channel_fragment_scrubbed"])
        self.assertTrue(result["post_accept_form_state_cleared"])
        self.assertTrue(result["post_accept_channel_cleared"])
        self.assertFalse(result["test_twin_evidence_eligible"])
        for page in result["pages"].values():
            self.assertEqual(page["external_assets"], 0)
            self.assertEqual(page["tracker_hits"], [])
            self.assertEqual(page["referrer_policy"], "no-referrer")
            self.assertEqual(page["robots"], "noindex,nofollow")

    def test_external_tracking_asset_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            build(target)
            adult = target / "cercetare" / "ai4work-step" / "adulti" / "index.html"
            text = adult.read_text(encoding="utf-8")
            adult.write_text(
                text.replace("</head>", '<script src="https://www.googletagmanager.com/gtag/js"></script></head>'),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                validate_page(adult, expect_form=True)

    def test_endpoint_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            build(target)
            employer = target / "cercetare" / "ai4work-step" / "angajatori" / "index.html"
            text = employer.read_text(encoding="utf-8")
            employer.write_text(
                text.replace(ALLOWED_RESEARCH_API, "https://crm.eucons.ro/research/submit"),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                validate_page(employer, expect_form=True)

    def test_browser_tracking_storage_is_rejected(self) -> None:
        control_source = (Path(__file__).resolve().parent / "static_surface_privacy_control.py").read_text(encoding="utf-8")
        self.assertIn('"document.cookie"', control_source)
        self.assertIn('"localstorage"', control_source)
        self.assertIn('"sessionstorage"', control_source)
        self.assertIn('"indexeddb"', control_source)
        self.assertIn('"navigator.sendbeacon"', control_source)

    def test_recruitment_channel_fragment_is_captured_once_then_scrubbed(self) -> None:
        client_source = (Path(__file__).resolve().parent / "research_form.js").read_text(encoding="utf-8")
        self.assertIn("let recruitmentChannel = (() => {", client_source)
        self.assertIn("globalThis.history.replaceState", client_source)
        self.assertIn("const channelId = () => recruitmentChannel;", client_source)
        self.assertNotIn("localStorage", client_source)
        self.assertNotIn("sessionStorage", client_source)
        self.assertNotIn("indexedDB", client_source)

    def test_accepted_submission_clears_in_page_analytical_and_channel_state(self) -> None:
        client_source = (Path(__file__).resolve().parent / "research_form.js").read_text(encoding="utf-8")
        self.assertIn("const clearAcceptedClientState = (form) => {", client_source)
        self.assertIn("retryState.delete(form);", client_source)
        self.assertIn("recruitmentChannel = null;", client_source)
        self.assertIn("form.reset();", client_source)
        self.assertIn("clearAcceptedClientState(form);", client_source)


if __name__ == "__main__":
    unittest.main()
