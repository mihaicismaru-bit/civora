import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from isj_materiality_shadow_lane import adjudicate_isj_detail, adjudicate_report


class IsjMaterialityShadowLaneTest(unittest.TestCase):
    @staticmethod
    def row(**overrides):
        item = {
            "state": "DETAIL_EVIDENCE_SHADOW",
            "signal_id": "isj-ref-example",
            "evidence_id": "isj-detail-example",
            "topic_class": "ADMISSIONS",
            "label": "Admitere în licee",
            "detail_url": "https://www.isjvalcea.ro/examene/admitere-in-licee",
            "detail_sha256": "a" * 64,
            "visible_title": "ISJ VÂLCEA - Admitere în licee",
            "explicit_date_text": None,
            "detail_readback_verified": True,
            "publication_authority": "NONE",
            "material_fact_use": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
        }
        item.update(overrides)
        return item

    def test_stale_visible_date_is_no_story(self):
        result = adjudicate_isj_detail(self.row(explicit_date_text="02.08.2024"), as_of=date(2026, 9, 18))
        self.assertEqual(result["state"], "NO_STORY")
        self.assertEqual(result["reason"], "stale_first_party_detail_page")

    def test_navigation_page_without_currentness_is_no_story(self):
        result = adjudicate_isj_detail(self.row(), as_of=date(2026, 9, 18))
        self.assertEqual(result["state"], "NO_STORY")
        self.assertEqual(result["reason"], "navigation_or_category_detail_not_news_by_itself")

    def test_current_year_category_without_material_event_blocks(self):
        result = adjudicate_isj_detail(
            self.row(
                topic_class="STAFFING_MANAGEMENT",
                label="concurs directori 2026",
                visible_title="ISJ VÂLCEA - concurs directori 2026",
            ),
            as_of=date(2026, 9, 18),
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "current_year_detail_without_explicit_material_event")
        self.assertTrue(result["embedded_file_or_notice_evidence_required"])

    def test_recent_visible_date_is_candidate_only_not_fact_kernel(self):
        result = adjudicate_isj_detail(
            self.row(explicit_date_text="18.09.2026", label="Admitere - anunț 18.09.2026"),
            as_of=date(2026, 9, 18),
        )
        self.assertEqual(result["state"], "MATERIAL_DETAIL_CANDIDATE_SHADOW")
        self.assertFalse(result["explicit_date_is_event_time"])
        self.assertTrue(result["field_level_evidence_required"])
        self.assertFalse(result["fact_kernel_promotion_allowed"])
        self.assertFalse(result["writer_allowed"])

    def test_sensitive_exam_result_surface_stays_blocked(self):
        result = adjudicate_isj_detail(
            self.row(topic_class="EXAMS_RESULTS", label="Definitivat", explicit_date_text=None),
            as_of=date(2026, 9, 18),
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "sensitive_exam_result_detail_requires_non_personal_field_level_review")
        self.assertFalse(result["sensitive_result_projection_allowed"])

    def test_promotion_boundary_violation_blocks(self):
        result = adjudicate_isj_detail(self.row(writer_allowed=True), as_of=date(2026, 9, 18))
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "detail_promotion_boundary_violation")

    def test_report_never_authorizes_downstream(self):
        report = adjudicate_report(
            [][0] if False else {"rows": [
                self.row(explicit_date_text="02.08.2024"),
                self.row(label="concurs directori 2026", visible_title="concurs directori 2026", topic_class="STAFFING_MANAGEMENT"),
                self.row(label="Învățământ primar", visible_title="ISJ VÂLCEA - Învățământ primar"),
            ]},
            as_of=date(2026, 9, 18),
        )
        self.assertEqual(report["detail_row_count"], 3)
        self.assertEqual(report["no_story_count"], 2)
        self.assertEqual(report["blocked_count"], 1)
        self.assertFalse(report["fact_kernel_promotion_allowed"])
        self.assertFalse(report["writer_allowed"])
        self.assertFalse(report["site_publish_allowed"])
        self.assertFalse(report["social_publish_allowed"])
        self.assertFalse(report["acceptance_ready"])


if __name__ == "__main__":
    unittest.main()
