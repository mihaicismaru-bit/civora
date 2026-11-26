import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from site_verified_article_ledger import build_ledger  # noqa: E402


def _blank(source_kind=None):
    doc = {
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "rows": [],
    }
    if source_kind:
        doc["source_kind"] = source_kind
    return doc


def _package(headline="Headline"):
    return {"headline": headline, "dek": "Dek", "body": "Body"}


class VerifiedArticleLedgerTest(unittest.TestCase):
    def test_public_safety_uses_photo_truth_stable_id(self):
        url = "https://example.test/ipj/story"
        ipj = _blank("ipj")
        ipj["rows"] = [{
            "state": "VERIFIED_WRITTEN_SHADOW", "publication_authority": "NONE",
            "fact_kernel": {"source_url": url}, "article_package": _package(),
            "integrity": {"status": "PASS", "fabricated_claims": 0},
        }]
        report = build_ledger(ipj=ipj, isu=_blank("isu"), municipal=_blank(), isj_article={**_blank(), "state": "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY", "articles": []}, isj_integrity={**_blank(), "status": "PASS_SHADOW", "article_truth_state": "VERIFIED_WRITTEN_SHADOW", "article_integrity_verified": True, "fabricated_claim_count": 0, "verified_article_count": 0, "verified_candidates": []})
        expected = hashlib.sha256(f"ipj\n{url}".encode("utf-8")).hexdigest()[:24]
        self.assertEqual(report["rows"][0]["article_id"], expected)
        self.assertEqual(report["article_count"], 1)
        self.assertFalse(report["site_publish_allowed"])

    def test_municipal_nested_verified_article_is_normalized(self):
        municipal = _blank()
        municipal["rows"] = [{"state": "VERIFIED_WRITTEN_SHADOW", "articles": [{
            "article_id": "municipal-1", "state": "VERIFIED_WRITTEN_SHADOW", "publication_authority": "NONE",
            "fact_kernel": {"source_url": "https://example.test/hcl"}, "article_package": _package("HCL"),
            "integrity": {"status": "PASS", "fabricated_claims": 0, "body_fully_controlled": True},
        }]}]
        report = build_ledger(ipj=_blank("ipj"), isu=_blank("isu"), municipal=municipal, isj_article={**_blank(), "state": "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY", "articles": []}, isj_integrity={**_blank(), "status": "PASS_SHADOW", "article_truth_state": "VERIFIED_WRITTEN_SHADOW", "article_integrity_verified": True, "fabricated_claim_count": 0, "verified_article_count": 0, "verified_candidates": []})
        self.assertEqual(report["rows"][0]["article_id"], "municipal-1")
        self.assertEqual(report["source_article_counts"], {"municipal": 1})

    def test_isj_requires_independent_integrity_candidate(self):
        writer = {**_blank(), "state": "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY", "articles": [{
            "article_id": "isj-1", "fact_kernel": {"source_url": "https://example.test/isj"}, "article_package": _package("ISJ")
        }]}
        integrity = {**_blank(), "status": "PASS_SHADOW", "article_truth_state": "VERIFIED_WRITTEN_SHADOW", "article_integrity_verified": True, "fabricated_claim_count": 0, "verified_article_count": 1, "verified_candidates": [{"article_id": "isj-1", "source_url": "https://example.test/isj", "headline": "ISJ"}]}
        report = build_ledger(ipj=_blank("ipj"), isu=_blank("isu"), municipal=_blank(), isj_article=writer, isj_integrity=integrity)
        self.assertEqual(report["rows"][0]["article_id"], "isj-1")
        bad = dict(integrity)
        bad["verified_candidates"] = []
        with self.assertRaisesRegex(ValueError, "cardinality"):
            build_ledger(ipj=_blank("ipj"), isu=_blank("isu"), municipal=_blank(), isj_article=writer, isj_integrity=bad)

    def test_publication_authority_escape_fails_closed(self):
        ipj = _blank("ipj")
        ipj["publication_authority"] = "LIVE"
        with self.assertRaisesRegex(ValueError, "publication_authority"):
            build_ledger(ipj=ipj, isu=_blank("isu"), municipal=_blank(), isj_article={**_blank(), "state": "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY", "articles": []}, isj_integrity={**_blank(), "status": "PASS_SHADOW", "article_truth_state": "VERIFIED_WRITTEN_SHADOW", "article_integrity_verified": True, "fabricated_claim_count": 0, "verified_article_count": 0, "verified_candidates": []})

    def test_conflicting_duplicate_id_fails_closed(self):
        municipal = _blank()
        municipal["rows"] = [{"state": "VERIFIED_WRITTEN_SHADOW", "articles": [
            {"article_id": "dup", "state": "VERIFIED_WRITTEN_SHADOW", "publication_authority": "NONE", "fact_kernel": {"source_url": "https://a"}, "article_package": _package("A"), "integrity": {"status": "PASS", "fabricated_claims": 0, "body_fully_controlled": True}},
            {"article_id": "dup", "state": "VERIFIED_WRITTEN_SHADOW", "publication_authority": "NONE", "fact_kernel": {"source_url": "https://b"}, "article_package": _package("B"), "integrity": {"status": "PASS", "fabricated_claims": 0, "body_fully_controlled": True}},
        ]}]
        with self.assertRaisesRegex(ValueError, "conflicting verified article identity"):
            build_ledger(ipj=_blank("ipj"), isu=_blank("isu"), municipal=municipal, isj_article={**_blank(), "state": "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY", "articles": []}, isj_integrity={**_blank(), "status": "PASS_SHADOW", "article_truth_state": "VERIFIED_WRITTEN_SHADOW", "article_integrity_verified": True, "fabricated_claim_count": 0, "verified_article_count": 0, "verified_candidates": []})


if __name__ == "__main__":
    unittest.main()
