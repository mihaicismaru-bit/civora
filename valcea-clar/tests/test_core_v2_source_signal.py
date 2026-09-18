import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from eta_shadow_lane import (
    _load_eta_adapter,
    _scope_safe_classify_notice,
    adjudicate_eta_signal,
    verify_eta_signals,
)
from source_signal import normalize_canonical_candidate


class SourceSignalBoundaryTest(unittest.TestCase):
    def test_title_date_only_becomes_no_story(self):
        row = {
            "id": "sig-1",
            "headline": "Anunț",
            "paragraphs": [],
            "material_fact_gate": "HOLD_TITLE_DATE_ONLY",
            "reader_facing_copy_authorized": False,
            "sources": [{"name": "IPJ", "url": "https://example.org/x", "tier": "T1"}],
        }
        result = normalize_canonical_candidate("ipj_valcea", row)
        self.assertFalse(result.material_signal)
        self.assertEqual(result.terminal, "NO_STORY")
        self.assertIn("HOLD_TITLE_DATE_ONLY", result.reason)

    def test_full_material_candidate_crosses_signal_boundary_only(self):
        row = {
            "id": "sig-2",
            "headline": "Schimbare materială",
            "paragraphs": ["Detaliu verificat suficient pentru a continua spre kernel."],
            "material_fact_gate": "PASS",
            "reader_facing_copy_authorized": True,
            "confidence": 96,
            "sources": [{"name": "APAVIL", "url": "https://example.org/y", "tier": "T1"}],
        }
        result = normalize_canonical_candidate("apavil", row)
        self.assertTrue(result.material_signal)
        self.assertIsNone(result.terminal)
        self.assertEqual(result.confidence, 96)

    def test_nonpilot_source_fails_closed(self):
        row = {
            "id": "sig-x",
            "headline": "X",
            "paragraphs": ["x"],
            "material_fact_gate": "PASS",
            "sources": [{"url": "https://example.org/x"}],
        }
        with self.assertRaises(ValueError):
            normalize_canonical_candidate("unknown_source", row)


class EtaShadowSignalGateTest(unittest.TestCase):
    @staticmethod
    def signal(**overrides):
        row = {
            "signal_id": "eta-1",
            "article_url": "https://eta-bus.ro/comunicate/modificare-traseu",
            "title": "Modificare temporară traseu",
            "classification": "SCHEDULE_CHANGE",
            "effective_start": "2026-09-18",
            "effective_end": "2026-09-20",
            "effective_time": "08:00",
            "cms_published_at": "2026-09-17",
            "cms_timestamp_semantics": "EXPLICIT_VISIBLE_CMS_DATE",
            "evidence": {"content_sha256": "a" * 64, "source_url": "https://eta-bus.ro/comunicate/modificare-traseu"},
            "visual_candidate": {
                "source_url": "https://eta-bus.ro/images/notice.jpg",
                "provenance_url": "https://eta-bus.ro/comunicate/modificare-traseu",
                "rights_status": "UNKNOWN_REUSE_REQUIRES_EDITORIAL_CLEARANCE",
                "public_reuse_allowed": False,
            },
            "boundaries": {"publication_authority": "NONE", "live_status_claim_allowed": False},
        }
        row.update(overrides)
        return row

    def test_explicit_active_window_crosses_only_material_signal_boundary(self):
        result = adjudicate_eta_signal(self.signal(), as_of=date(2026, 9, 18))
        self.assertEqual(result["state"], "MATERIAL_SIGNAL_SHADOW")
        self.assertEqual(result["currentness"], "ACTIVE_EXPLICIT_WINDOW")
        self.assertEqual(result["photo_truth_status"], "BLOCKED_UNCLEARED_SOURCE_IMAGE")
        self.assertFalse(result["visual_candidate_promoted"])
        self.assertFalse(result["fact_kernel_promotion_allowed"])
        self.assertFalse(result["writer_allowed"])
        self.assertFalse(result["social_publish_allowed"])

    def test_expired_explicit_window_is_no_story(self):
        result = adjudicate_eta_signal(
            self.signal(effective_start="2026-09-10", effective_end="2026-09-12"),
            as_of=date(2026, 9, 18),
        )
        self.assertEqual(result["state"], "NO_STORY")
        self.assertEqual(result["reason"], "explicit_effective_window_expired")

    def test_old_open_ended_notice_blocks_live_inference(self):
        result = adjudicate_eta_signal(
            self.signal(effective_start="2026-08-01", effective_end=None),
            as_of=date(2026, 9, 18),
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "open_ended_operational_state_requires_fresh_reverification")
        self.assertEqual(result["currentness"], "UNPROVEN")

    def test_passenger_impact_without_effective_start_blocks(self):
        result = adjudicate_eta_signal(self.signal(effective_start=None, effective_end=None), as_of=date(2026, 9, 18))
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "passenger_impact_without_explicit_effective_start")

    def test_hold_notice_terminates_no_story(self):
        result = adjudicate_eta_signal(self.signal(classification="HOLD"), as_of=date(2026, 9, 18))
        self.assertEqual(result["state"], "NO_STORY")

    def test_scope_safe_classifier_ignores_unrelated_footer_sales_for_fare_notice(self):
        adapter = _load_eta_adapter()
        classification, reasons = _scope_safe_classify_notice(
            adapter,
            "Tarife de transport valabile începând cu data de 01/02/2026",
            "Bilet 1 călătorie 4 lei. Abonament lunar 130 lei. Footer: Anunț vânzare autovehicul. Licitație.",
        )
        self.assertEqual(classification, "FARE_OR_ACCESS_CHANGE")
        self.assertEqual(reasons, ["FARE_OR_PASSENGER_ACCESS_TERMS"])

    def test_scope_safe_classifier_ignores_unrelated_footer_sales_for_service_notice(self):
        adapter = _load_eta_adapter()
        classification, _reasons = _scope_safe_classify_notice(
            adapter,
            "Comunicat aplicație Skayo AVL",
            "În perioada 17.07.2026 – 20.07.2026 va fi realizat un upgrade major. "
            "Pot apărea anomalii temporare în afișarea informațiilor pe panouri. Footer: Anunț vânzare autoturism.",
        )
        self.assertEqual(classification, "SERVICE_ALERT")

    def test_irrelevant_notice_title_still_fails_closed(self):
        adapter = _load_eta_adapter()
        classification, reasons = _scope_safe_classify_notice(
            adapter,
            "Anunț vânzare autovehicul",
            "În footer există și cuvintele bilet, abonament și traseu.",
        )
        self.assertEqual(classification, "HOLD")
        self.assertEqual(reasons, ["NON_PASSENGER_OPERATIONAL_NOTICE"])

    def test_report_never_promotes_fact_kernel_or_writer(self):
        report = verify_eta_signals(
            [
                self.signal(),
                self.signal(signal_id="eta-2", classification="HOLD"),
                self.signal(signal_id="eta-3", effective_start="2026-08-01", effective_end=None),
            ],
            as_of=date(2026, 9, 18),
        )
        self.assertEqual(report["material_signal_shadow_count"], 1)
        self.assertEqual(report["no_story_count"], 1)
        self.assertEqual(report["blocked_count"], 1)
        self.assertFalse(report["fact_kernel_promotion_allowed"])
        self.assertFalse(report["writer_allowed"])
        self.assertFalse(report["acceptance_ready"])


if __name__ == "__main__":
    unittest.main()
