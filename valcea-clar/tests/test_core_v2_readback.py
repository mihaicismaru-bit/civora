import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from build_shadow_candidate_ledger import _canonical_visual_binding
from external_readback import inspect_html
from materialize_shadow_receipts import materialize as materialize_receipts
from meta_readback import (
    _image_response_ok,
    _instagram_image_candidates,
    parse_meta_error_body,
    parse_meta_object,
)
from promoted_claim_auditor import audit_documents
from shadow_gate_report import build_report
from visual_readback import (
    _classify_visual_truth_failure,
    _effective_direct_source_status,
    inspect_provenance_asset,
)


class ExternalReadbackTest(unittest.TestCase):
    def test_site_readback_requires_route_canonical_and_newsarticle(self):
        html = """
        <html><head>
        <link rel="canonical" href="https://valceaclar.ro/stiri/test-story/">
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"NewsArticle","url":"https://valceaclar.ro/stiri/test-story/","headline":"Test"}
        </script>
        </head><body>ok</body></html>
        """
        result = inspect_html(
            html,
            requested_url="https://valceaclar.ro/stiri/test-story/",
            final_url="https://valceaclar.ro/stiri/test-story/",
            expected_story_id="test-story",
        )
        self.assertTrue(result["readback_ok"])
        self.assertEqual(result["newsarticle_count"], 1)

    def test_site_readback_rejects_wrong_canonical(self):
        html = """
        <html><head>
        <link rel="canonical" href="https://valceaclar.ro/stiri/other-story/">
        <script type="application/ld+json">{"@type":"NewsArticle"}</script>
        </head></html>
        """
        result = inspect_html(
            html,
            requested_url="https://valceaclar.ro/stiri/test-story/",
            final_url="https://valceaclar.ro/stiri/test-story/",
            expected_story_id="test-story",
        )
        self.assertFalse(result["readback_ok"])

    def test_meta_readback_requires_matching_remote_id_and_permalink(self):
        ok = parse_meta_object(
            "facebook",
            "123_456",
            {"id": "123_456", "permalink_url": "https://facebook.example/posts/456"},
        )
        self.assertTrue(ok["readback_ok"])
        self.assertTrue(ok["object_readback_ok"])
        bad = parse_meta_object(
            "facebook",
            "123_456",
            {"id": "999", "permalink_url": "https://facebook.example/posts/999"},
        )
        self.assertFalse(bad["readback_ok"])

    def test_instagram_readback_accepts_permalink_field(self):
        result = parse_meta_object(
            "instagram",
            "180000",
            {
                "id": "180000",
                "permalink": "https://instagram.example/p/abc",
                "media_type": "IMAGE",
                "media_url": "https://scontent.example/image.jpg",
            },
        )
        self.assertTrue(result["readback_ok"])
        self.assertTrue(result["object_readback_ok"])
        self.assertEqual(result["media_type"], "IMAGE")
        self.assertEqual(result["remote_media_url"], "https://scontent.example/image.jpg")
        self.assertEqual(result["publication_authority"], "NONE")

    def test_instagram_single_image_candidate_is_bounded(self):
        candidates = _instagram_image_candidates(
            {
                "id": "180000",
                "media_type": "IMAGE",
                "media_url": "https://scontent.example/image.jpg",
            }
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["location"], "parent")
        self.assertEqual(candidates[0]["remote_id"], "180000")

    def test_instagram_carousel_extracts_only_https_image_children(self):
        candidates = _instagram_image_candidates(
            {
                "id": "180parent",
                "media_type": "CAROUSEL_ALBUM",
                "children": {
                    "data": [
                        {"id": "1", "media_type": "IMAGE", "media_url": "https://scontent.example/one.jpg"},
                        {"id": "2", "media_type": "VIDEO", "media_url": "https://scontent.example/two.mp4"},
                        {"id": "3", "media_type": "IMAGE", "media_url": "http://insecure.example/three.jpg"},
                        {"id": "4", "media_type": "IMAGE", "media_url": "https://scontent.example/four.jpg"},
                    ]
                },
            }
        )
        self.assertEqual([row["remote_id"] for row in candidates], ["1", "4"])
        self.assertTrue(all(row["location"] == "carousel_child" for row in candidates))

    def test_instagram_non_image_media_does_not_manufacture_visual_truth(self):
        self.assertEqual(
            _instagram_image_candidates(
                {"id": "180video", "media_type": "VIDEO", "media_url": "https://scontent.example/video.mp4"}
            ),
            [],
        )
        self.assertEqual(
            _instagram_image_candidates(
                {"id": "180image", "media_type": "IMAGE", "media_url": ""}
            ),
            [],
        )

    def test_remote_media_truth_accepts_only_http_image_payload(self):
        self.assertTrue(_image_response_ok(200, "image/jpeg"))
        self.assertTrue(_image_response_ok(206, "image/webp"))
        self.assertFalse(_image_response_ok(200, "text/html"))
        self.assertFalse(_image_response_ok(302, "image/jpeg"))
        self.assertFalse(_image_response_ok(None, "image/jpeg"))

    def test_meta_error_body_keeps_diagnostic_without_token(self):
        detail = parse_meta_error_body(
            b'{"error":{"message":"Unsupported get request","type":"GraphMethodException","code":100,"error_subcode":33,"fbtrace_id":"abc"}}'
        )
        self.assertEqual(detail["error_code"], 100)
        self.assertEqual(detail["error_subcode"], 33)
        self.assertEqual(detail["error_type"], "GraphMethodException")
        self.assertEqual(detail["error_message"], "Unsupported get request")
        self.assertNotIn("access_token", detail)

    def test_commons_provenance_jsonld_binds_exact_direct_asset_and_license(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"ImageObject","contentUrl":"https://upload.wikimedia.org/wikipedia/commons/a/a8/CET_Govora_%28dinspre_nord-vest%29.JPG?utm_source=commons.wikimedia.org","license":"https://creativecommons.org/licenses/by-sa/3.0","name":"CET Govora"}
        </script>
        </head></html>
        """
        result = inspect_provenance_asset(
            html,
            expected_direct_url="https://upload.wikimedia.org/wikipedia/commons/a/a8/CET_Govora_%28dinspre_nord-vest%29.JPG",
        )
        self.assertTrue(result["asset_identity_ok"])
        self.assertTrue(result["license_present"])
        self.assertEqual(result["matching_imageobject_count"], 1)

    def test_commons_provenance_jsonld_rejects_wrong_asset(self):
        html = """
        <script type="application/ld+json">
        {"@type":"ImageObject","contentUrl":"https://upload.wikimedia.org/wikipedia/commons/x/x1/Other.JPG","license":"https://creativecommons.org/licenses/by/4.0"}
        </script>
        """
        result = inspect_provenance_asset(
            html,
            expected_direct_url="https://upload.wikimedia.org/wikipedia/commons/a/a8/CET_Govora_%28dinspre_nord-vest%29.JPG",
        )
        self.assertFalse(result["asset_identity_ok"])
        self.assertFalse(result["license_present"])

    def test_direct_429_fallback_is_narrow_to_verified_wikimedia_asset(self):
        ok, reason = _effective_direct_source_status(
            source_url="https://commons.wikimedia.org/wiki/File:CET_Govora_(dinspre_nord-vest).JPG",
            direct_source_url="https://upload.wikimedia.org/wikipedia/commons/a/a8/CET_Govora_%28dinspre_nord-vest%29.JPG",
            direct_source={"readback_ok": False, "rate_limited": True, "http_status": 429},
            provenance_asset={"asset_identity_ok": True, "license_present": True},
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "wikimedia_commons_source_page_identity_fallback_for_direct_429")

        bad, bad_reason = _effective_direct_source_status(
            source_url="https://example.com/source",
            direct_source_url="https://example.com/image.jpg",
            direct_source={"readback_ok": False, "rate_limited": True, "http_status": 429},
            provenance_asset={"asset_identity_ok": True, "license_present": True},
        )
        self.assertFalse(bad)
        self.assertIsNone(bad_reason)

    def test_visual_failure_classifies_reachable_article_without_approved_image_as_content_absence(self):
        state, domain = _classify_visual_truth_failure(
            internal_gate=True,
            article={"readback_ok": True},
            article_binding={"article_image_bound": False},
            public_image={"readback_ok": False},
            provenance_source={"readback_ok": True},
            direct_source_effective_ok=True,
        )
        self.assertEqual(state, "SITE_APPROVED_VISUAL_ABSENT")
        self.assertEqual(domain, "SITE_CONTENT")

    def test_visual_failure_keeps_site_transport_distinct_from_content_absence(self):
        state, domain = _classify_visual_truth_failure(
            internal_gate=True,
            article={"readback_ok": False},
            article_binding={"article_image_bound": False},
            public_image={"readback_ok": False},
            provenance_source={"readback_ok": True},
            direct_source_effective_ok=True,
        )
        self.assertEqual(state, "SITE_ARTICLE_TRANSPORT_FAILURE")
        self.assertEqual(domain, "SITE_TRANSPORT")

    def test_visual_failure_keeps_provenance_transport_distinct_from_site_absence(self):
        state, domain = _classify_visual_truth_failure(
            internal_gate=True,
            article={"readback_ok": True},
            article_binding={"article_image_bound": True},
            public_image={"readback_ok": True},
            provenance_source={"readback_ok": False},
            direct_source_effective_ok=False,
        )
        self.assertEqual(state, "PROVENANCE_SOURCE_TRANSPORT_FAILURE")
        self.assertEqual(domain, "PROVENANCE_TRANSPORT")

    def test_canonical_visual_binding_requires_same_asset_source_rights_and_verified_provenance(self):
        source_url = "https://commons.wikimedia.org/wiki/File:Expected.jpg"
        result = _canonical_visual_binding(
            expected_image_path="valcea-clar/social/photos/approved/expected.jpg",
            visual_source_url=source_url,
            visual_rights_basis="creative_commons",
            real_visual=True,
            manifest_image={
                "public_url": "https://valceaclar.ro/media/social/expected.jpg",
                "source_url": source_url,
                "rights_basis": "creative_commons",
                "provenance_status": "VERIFIED",
            },
        )
        self.assertEqual(result["canonical_site_visual_binding_state"], "CONSISTENT")
        self.assertTrue(result["canonical_site_image_bound"])
        self.assertTrue(result["canonical_site_visual_filename_match"])
        self.assertTrue(result["canonical_site_visual_source_match"])
        self.assertTrue(result["canonical_site_visual_rights_match"])
        self.assertTrue(result["canonical_site_visual_provenance_verified"])

    def test_canonical_visual_binding_detects_social_visual_present_but_site_unbound(self):
        result = _canonical_visual_binding(
            expected_image_path="valcea-clar/social/photos/approved/expected.jpg",
            visual_source_url="https://commons.wikimedia.org/wiki/File:Expected.jpg",
            visual_rights_basis="creative_commons",
            real_visual=True,
            manifest_image=None,
        )
        self.assertEqual(result["canonical_site_visual_binding_state"], "SOCIAL_VISUAL_PRESENT_SITE_UNBOUND")
        self.assertFalse(result["canonical_site_image_bound"])

    def test_canonical_visual_binding_detects_different_site_asset(self):
        source_url = "https://commons.wikimedia.org/wiki/File:Expected.jpg"
        result = _canonical_visual_binding(
            expected_image_path="valcea-clar/social/photos/approved/expected.jpg",
            visual_source_url=source_url,
            visual_rights_basis="creative_commons",
            real_visual=True,
            manifest_image={
                "public_url": "https://valceaclar.ro/media/social/other.jpg",
                "source_url": source_url,
                "rights_basis": "creative_commons",
                "provenance_status": "VERIFIED",
            },
        )
        self.assertEqual(result["canonical_site_visual_binding_state"], "SITE_BOUND_DIFFERENT_ASSET")
        self.assertFalse(result["canonical_site_visual_filename_match"])

    @staticmethod
    def _auditor_fixture():
        candidates = {
            "first_ten_candidate_ids": ["story-a", "story-b"],
            "rows": [
                {
                    "story_id": "story-a",
                    "canonical_url": "https://valceaclar.ro/stiri/story-a/",
                    "real_visual_internal_evidence": True,
                    "visual_rights_basis": "creative_commons",
                    "canonical_site_visual_binding_state": "CONSISTENT",
                    "facebook_remote_id_internal": "fb-a",
                    "instagram_remote_id_internal": "ig-a",
                },
                {
                    "story_id": "story-b",
                    "canonical_url": "https://valceaclar.ro/stiri/story-b/",
                    "real_visual_internal_evidence": True,
                    "visual_rights_basis": "creative_commons",
                    "canonical_site_visual_binding_state": "SOCIAL_VISUAL_PRESENT_SITE_UNBOUND",
                    "facebook_remote_id_internal": "fb-b",
                    "instagram_remote_id_internal": "ig-b",
                },
            ],
        }
        site = {
            "results": [
                {
                    "expected_story_id": story,
                    "http_status": 200,
                    "route_match": True,
                    "canonical_match": True,
                    "newsarticle_count": 1,
                    "newsarticle_story_match": True,
                    "readback_ok": True,
                    "canonical_url": f"https://valceaclar.ro/stiri/{story}/",
                }
                for story in ("story-a", "story-b")
            ]
        }
        visual_common = {
            "status": "PASS",
            "readback_ok": True,
            "internal_truth_gate": True,
            "rights_basis": "creative_commons",
            "canonical_site_image_bound": True,
            "canonical_site_visual_filename_match": True,
            "canonical_site_visual_source_match": True,
            "canonical_site_visual_rights_match": True,
            "canonical_site_visual_provenance_verified": True,
            "article": {"readback_ok": True},
            "article_binding": {"article_image_bound": True},
            "public_image": {"readback_ok": True},
            "provenance_source": {"readback_ok": True},
            "provenance_asset": {"asset_identity_ok": True, "license_present": True},
            "direct_source": {"readback_ok": True},
            "direct_source_effective_ok": True,
        }
        visual = {
            "results": [
                {"story_id": "story-a", "canonical_site_visual_binding_state": "CONSISTENT", **visual_common},
                {"story_id": "story-b", "canonical_site_visual_binding_state": "SOCIAL_VISUAL_PRESENT_SITE_UNBOUND", **visual_common},
            ]
        }
        meta = {
            "results": [
                {
                    "story_id": "story-a", "channel": "facebook", "remote_id": "fb-a", "observed_remote_id": "fb-a",
                    "object_readback_ok": False, "readback_ok": False, "status": "FAILED", "error_code": 10,
                },
                {
                    "story_id": "story-b", "channel": "facebook", "remote_id": "fb-b", "observed_remote_id": "fb-b",
                    "object_readback_ok": False, "readback_ok": False, "status": "FAILED", "error_code": 10,
                },
                {
                    "story_id": "story-a", "channel": "instagram", "remote_id": "ig-a", "observed_remote_id": "ig-a",
                    "object_readback_ok": True, "readback_ok": True, "status": "PASS",
                    "permalink": "https://instagram.example/p/a", "remote_visual_readback_ok": True,
                },
                {
                    "story_id": "story-b", "channel": "instagram", "remote_id": "ig-b", "observed_remote_id": "ig-b",
                    "object_readback_ok": True, "readback_ok": True, "status": "PASS",
                    "permalink": "https://instagram.example/p/b", "remote_visual_readback_ok": True,
                },
            ]
        }
        identity = {
            "results": [
                {
                    "story_id": "story-a", "identity_bound": True,
                    "identity_state": "APPROVED_VISUAL_MATCHED_REMOTE_IMAGE_UNIQUE",
                    "passing_candidate_count": 1, "matched_remote_id": "ig-image-a",
                },
                {
                    "story_id": "story-b", "identity_bound": False,
                    "identity_state": "NO_REMOTE_IMAGE_MATCHED_APPROVED_VISUAL",
                    "passing_candidate_count": 0, "matched_remote_id": None,
                },
            ]
        }
        transactions = {
            "rows": [
                {
                    "story_id": story,
                    "terminal_reason": "BLOCKED_EXTERNAL_DELIVERY_EVIDENCE",
                    "integrity": {"fabricated_claims": 0},
                }
                for story in ("story-a", "story-b")
            ]
        }
        return candidates, site, visual, meta, identity, transactions

    def test_independent_auditor_matches_canonical_external_semantics_and_stays_fail_closed(self):
        candidates, site, visual, meta, identity, transactions = self._auditor_fixture()
        audit = audit_documents(candidates, site, visual, meta, identity, transactions)
        receipts = materialize_receipts(candidates, site, visual, meta, identity)
        gate = build_report(candidates, receipts, transactions)

        receipt_rows = receipts["rows"]
        canonical_projection = {
            "stories_published": sum(
                1 for row in receipt_rows
                if row["receipts"]["site"]["status"] == "DELIVERED"
                and row["receipts"]["site"]["readback_ok"] is True
            ),
            "photo_verified_count": sum(
                1 for row in receipt_rows
                if row["receipts"]["visual"]["status"] == "VERIFIED"
                and row["receipts"]["visual"]["readback_ok"] is True
                and row["receipts"]["visual"]["canonical_site_visual_binding_state"] == "CONSISTENT"
            ),
            "facebook_delivered_receipt_bound": sum(
                1 for row in receipt_rows
                if row["receipts"]["facebook"]["status"] == "DELIVERED"
                and row["receipts"]["facebook"]["readback_ok"] is True
                and row["receipts"]["facebook"]["remote_id"]
                and row["receipts"]["facebook"]["receipt_id"]
            ),
            "instagram_delivered_receipt_bound": sum(
                1 for row in receipt_rows
                if row["receipts"]["instagram"]["status"] == "DELIVERED"
                and row["receipts"]["instagram"]["readback_ok"] is True
                and row["receipts"]["instagram"]["remote_id"]
                and row["receipts"]["instagram"]["receipt_id"]
                and row["receipts"]["instagram"]["remote_visual_readback_ok"] is True
                and row["receipts"]["instagram"]["remote_visual_identity_bound"] is True
                and row["receipts"]["visual"]["canonical_site_visual_binding_state"] == "CONSISTENT"
            ),
            "truth_complete_transactions": gate["truth_complete_count"],
        }
        auditor_projection = {
            key: audit["metrics"][key]
            for key in canonical_projection
        }
        self.assertEqual(auditor_projection, canonical_projection)
        self.assertEqual(auditor_projection["stories_published"], 2)
        self.assertEqual(auditor_projection["photo_verified_count"], 1)
        self.assertEqual(auditor_projection["facebook_delivered_receipt_bound"], 0)
        self.assertEqual(auditor_projection["instagram_delivered_receipt_bound"], 1)
        self.assertEqual(auditor_projection["truth_complete_transactions"], 0)
        self.assertEqual(audit["metrics"]["fabricated_claims"], 0)
        self.assertEqual(audit["metrics"]["unresolved_material_signals"], 0)
        self.assertEqual(audit["metrics"]["manual_intervention"], 0)
        self.assertFalse(audit["external_truth_complete"])
        self.assertFalse(audit["acceptance_ready"])
        self.assertEqual(audit["publication_authority"], "NONE")
        self.assertEqual(audit["cutover_authority"], "NONE")
        self.assertEqual(audit["retirement_authority"], "NONE")

    def test_independent_auditor_rejects_self_consistent_but_tampered_statuses(self):
        candidates, site, visual, meta, identity, transactions = self._auditor_fixture()

        tampered_site = copy.deepcopy(site)
        tampered_site["results"][0]["canonical_match"] = False
        tampered_site["results"][0]["readback_ok"] = True
        result = audit_documents(candidates, tampered_site, visual, meta, identity, transactions)
        self.assertEqual(result["metrics"]["stories_published"], 1)

        tampered_visual = copy.deepcopy(visual)
        tampered_visual["results"][0]["provenance_asset"]["asset_identity_ok"] = False
        tampered_visual["results"][0]["readback_ok"] = True
        result = audit_documents(candidates, site, tampered_visual, meta, identity, transactions)
        self.assertEqual(result["metrics"]["photo_verified_count"], 0)

        delivered_fb = copy.deepcopy(meta)
        delivered_fb["results"][0].update(
            {
                "object_readback_ok": True,
                "readback_ok": True,
                "status": "PASS",
                "permalink": "https://facebook.example/posts/a",
                "observed_remote_id": "wrong-id",
            }
        )
        result = audit_documents(candidates, site, visual, delivered_fb, identity, transactions)
        self.assertEqual(result["metrics"]["facebook_delivered_receipt_bound"], 0)

        ambiguous_identity = copy.deepcopy(identity)
        ambiguous_identity["results"][0].update(
            {"identity_bound": True, "passing_candidate_count": 2, "matched_remote_id": "ig-image-a"}
        )
        result = audit_documents(candidates, site, visual, meta, ambiguous_identity, transactions)
        self.assertEqual(result["metrics"]["instagram_delivered_receipt_bound"], 0)


if __name__ == "__main__":
    unittest.main()
