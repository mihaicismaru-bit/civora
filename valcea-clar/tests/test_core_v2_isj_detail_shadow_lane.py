import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from isj_detail_shadow_lane import verify_isj_details


class IsjDetailShadowLaneTest(unittest.TestCase):
    @staticmethod
    def report(document_url: str):
        return {
            "publication_authority": "NONE",
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "rows": [
                {
                    "state": "MATERIAL_SIGNAL_SHADOW",
                    "signal_id": "isj-example",
                    "label": "DEFINITIVAT 2026 - VALIDARE 18.09.2026",
                    "document_url": document_url,
                }
            ],
        }

    def test_first_party_detail_is_hashed_but_stays_non_authorizing(self):
        calls = []

        def fetcher(url):
            calls.append(url)
            return (
                b"<html><title>ISJ Valcea</title><body>Definitivat 18.09.2026. Calendar validare.</body></html>",
                url,
                "text/html",
            )

        def extractor(body, label):
            self.assertIn(b"Definitivat", body)
            self.assertIn("VALIDARE", label)
            return "ISJ Valcea", "18.09.2026", ("Definitivat 18.09.2026. Calendar validare.",)

        result = verify_isj_details(
            self.report("https://www.isjvalcea.ro/files/definitivat.html"),
            fetcher=fetcher,
            html_extractor=extractor,
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["detail_evidence_shadow_count"], 1)
        self.assertEqual(result["blocked_count"], 0)
        row = result["rows"][0]
        self.assertEqual(row["state"], "DETAIL_EVIDENCE_SHADOW")
        self.assertTrue(row["detail_readback_verified"])
        self.assertEqual(len(row["detail_sha256"]), 64)
        self.assertTrue(row["evidence_id"].startswith("isj-detail-"))
        self.assertFalse(row["material_fact_use"])
        self.assertFalse(row["fact_kernel_promotion_allowed"])
        self.assertFalse(row["writer_allowed"])
        self.assertFalse(result["acceptance_ready"])

    def test_external_document_host_is_blocked_without_fetch(self):
        called = False

        def fetcher(url):
            nonlocal called
            called = True
            raise AssertionError("external target must not be fetched")

        result = verify_isj_details(
            self.report("https://drive.google.com/file/d/example"),
            fetcher=fetcher,
            html_extractor=lambda *_: (None, None, ()),
        )
        self.assertFalse(called)
        self.assertEqual(result["detail_evidence_shadow_count"], 0)
        self.assertEqual(result["blocked_count"], 1)
        self.assertEqual(result["rows"][0]["reason"], "official_detail_not_first_party_https")
        self.assertFalse(result["rows"][0]["detail_fetch_attempted"])

    def test_upstream_promotion_boundary_violation_fails_closed(self):
        payload = self.report("https://www.isjvalcea.ro/files/a.pdf")
        payload["writer_allowed"] = True
        with self.assertRaises(ValueError):
            verify_isj_details(payload, fetcher=lambda _: (b"x", "https://www.isjvalcea.ro/files/a.pdf", "application/pdf"), html_extractor=lambda *_: (None, None, ()))

    def test_non_material_rows_do_not_trigger_detail_fetch(self):
        payload = self.report("https://www.isjvalcea.ro/files/a.pdf")
        payload["rows"][0]["state"] = "NO_STORY"
        result = verify_isj_details(payload, fetcher=lambda _: (_ for _ in ()).throw(AssertionError("must not fetch")), html_extractor=lambda *_: (None, None, ()))
        self.assertEqual(result["selected_material_signal_count"], 0)
        self.assertEqual(result["detail_evidence_shadow_count"], 0)
        self.assertEqual(result["blocked_count"], 0)


if __name__ == "__main__":
    unittest.main()
