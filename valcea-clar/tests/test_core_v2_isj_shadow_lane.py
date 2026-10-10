import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from isj_shadow_lane import adjudicate_isj_signal, verify_isj_signals


class IsjShadowLaneTest(unittest.TestCase):
    @staticmethod
    def signal(**overrides):
        row = {
            "signal_class": "TEACHER_EXAM_NOTICE",
            "source_url": "https://www.isjvalcea.ro/noutăți",
            "document_url": "https://www.isjvalcea.ro/files/anunt.pdf",
            "document_url_sha256": "a" * 64,
            "label": "DEFINITIVAT 2026 - VALIDARE 18.09.2026",
            "school_year": "2026-2027",
            "explicit_date": "2026-09-18",
            "explicit_date_semantics": "EXPLICIT_VISIBLE_LABEL_DATE_ONLY",
            "hold_reason": None,
            "publication_authority": "NONE",
            "current_status_claim_allowed": False,
            "freshness_claim_allowed": False,
            "person_fact_extraction_allowed": False,
            "sensitive_result_projection_allowed": False,
            "document_body_fetch_allowed": False,
            "inferred_photo_rights_allowed": False,
            "persistence_allowed": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "public_projection_allowed": False,
        }
        row.update(overrides)
        return row

    def test_recent_material_reference_crosses_only_signal_boundary(self):
        result = adjudicate_isj_signal(self.signal(), as_of=date(2026, 9, 18))
        self.assertEqual(result["state"], "MATERIAL_SIGNAL_SHADOW")
        self.assertEqual(result["currentness"], "RECENT_OR_UPCOMING_LABEL_DATE_ONLY")
        self.assertFalse(result["label_date_is_event_time"])
        self.assertTrue(result["document_body_required_for_fact_kernel"])
        self.assertFalse(result["fact_kernel_promotion_allowed"])
        self.assertFalse(result["writer_allowed"])
        self.assertFalse(result["social_publish_allowed"])

    def test_sensitive_result_reference_is_blocked(self):
        result = adjudicate_isj_signal(
            self.signal(
                signal_class="HOLD_SENSITIVE_EDUCATION_RESULT_REFERENCE",
                label=None,
                document_url=None,
                explicit_date=None,
                hold_reason="PERSON_LEVEL_OR_RESULT_DOCUMENT_REVIEW_REQUIRED",
            ),
            as_of=date(2026, 9, 18),
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "sensitive_or_person_level_education_result_requires_manual_review")
        self.assertFalse(result["person_fact_extraction_allowed"])
        self.assertFalse(result["sensitive_result_projection_allowed"])

    def test_static_form_is_no_story(self):
        result = adjudicate_isj_signal(
            self.signal(
                signal_class="PRESCHOOL_ENROLMENT_NOTICE",
                label="CERERE-TIP INSCRIERE PRESCOLAR 2026",
                explicit_date=None,
            ),
            as_of=date(2026, 9, 18),
        )
        self.assertEqual(result["state"], "NO_STORY")
        self.assertEqual(result["reason"], "static_education_reference_not_news_by_itself")

    def test_prior_school_year_is_no_story(self):
        result = adjudicate_isj_signal(
            self.signal(school_year="2025-2026", explicit_date=None, label="Calendar admitere 2025-2026"),
            as_of=date(2026, 9, 18),
        )
        self.assertEqual(result["state"], "NO_STORY")
        self.assertEqual(result["reason"], "school_year_not_current")

    def test_old_label_date_is_no_story(self):
        result = adjudicate_isj_signal(
            self.signal(explicit_date="2026-06-10", label="DEFINITIVAT 2026 - VALIDARE 10.06.2026"),
            as_of=date(2026, 9, 18),
        )
        self.assertEqual(result["state"], "NO_STORY")
        self.assertEqual(result["reason"], "explicit_label_date_stale_for_news")

    def test_current_school_year_without_currentness_blocks(self):
        result = adjudicate_isj_signal(
            self.signal(explicit_date=None, label="DEFINITIVAT 2026"),
            as_of=date(2026, 9, 18),
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "current_school_year_reference_without_explicit_currentness")

    def test_unverified_official_document_reference_blocks(self):
        result = adjudicate_isj_signal(
            self.signal(document_url=None, hold_reason="DOCUMENT_LINK_OFFICIAL_HOST_NOT_VERIFIED"),
            as_of=date(2026, 9, 18),
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "official_document_reference_not_verified")

    def test_source_boundary_violation_blocks(self):
        result = adjudicate_isj_signal(
            self.signal(writer_allowed=True),
            as_of=date(2026, 9, 18),
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "source_adapter_publication_boundary_violation")

    def test_summer_service_reference_expires_after_august(self):
        result = adjudicate_isj_signal(
            self.signal(
                signal_class="SUMMER_PRESCHOOL_SERVICE_REFERENCE",
                label="PLANIFICARE GRADINITE VACANTA DE VARA",
                explicit_date=None,
            ),
            as_of=date(2026, 9, 18),
        )
        self.assertEqual(result["state"], "NO_STORY")
        self.assertEqual(result["reason"], "seasonal_summer_service_reference_expired")

    def test_report_never_promotes_kernel_or_writer(self):
        report = verify_isj_signals(
            [
                self.signal(),
                self.signal(document_url_sha256="b" * 64, label="CERERE INSCRIERE PRESCOLAR 2026", signal_class="PRESCHOOL_ENROLMENT_NOTICE", explicit_date=None),
                self.signal(document_url_sha256="c" * 64, label="DEFINITIVAT 2026", explicit_date=None),
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
