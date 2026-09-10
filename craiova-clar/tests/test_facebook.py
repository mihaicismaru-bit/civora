from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from clar_core.contracts import PublicationReceipt, Story
from clar_core.social.facebook import FacebookPagePublisher, FacebookPublishError, format_caption


class _Headers(dict):
    def get(self, key, default=None):
        for actual, value in self.items():
            if actual.lower() == key.lower():
                return value
        return default


class _Response:
    def __init__(self, body: bytes, headers=None):
        self._body = body
        self.headers = _Headers(headers or {})
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False
    def read(self):
        return self._body


def _story() -> Story:
    return Story(
        story_id="story-1",
        slug="apa-oprita",
        section="UTILITĂȚI",
        headline="Apa va fi oprită în Valea Roșie",
        dek="Întrerupere programată între 11:00 și 15:00.",
        paragraphs=("Text factual.",),
        source_urls=("https://example.invalid/source",),
        published_at=datetime(2026, 8, 19, 9, 0, tzinfo=timezone.utc),
        media_query="Valea Roșie",
        metadata={
            "media": {
                "asset_id": "commons-1",
                "image_url": "https://images.example/photo.jpg",
                "source_page": "https://commons.example/file",
                "creator": "Example Author",
                "license": "CC BY-SA 3.0",
                "license_url": "https://creativecommons.org/licenses/by-sa/3.0/",
                "rights_status": "VERIFIED_REUSABLE",
                "alt": "Imagine de arhivă",
                "caption": "Imagine de arhivă; nu reprezintă intervenția descrisă.",
            }
        },
    )


def _site_receipt(status="published_verified") -> PublicationReceipt:
    return PublicationReceipt(
        story_id="story-1",
        canonical_url="https://news.example/stiri/apa-oprita/",
        published_at=datetime(2026, 8, 19, 9, 5, tzinfo=timezone.utc),
        destination="static_site",
        status=status,
    )


class FacebookPublisherTest(unittest.TestCase):
    def test_requires_verified_public_site_first(self) -> None:
        with self.assertRaises(FacebookPublishError):
            format_caption(_story(), _site_receipt("rendered"))

    def test_caption_carries_canonical_link_and_context_credit(self) -> None:
        caption = format_caption(_story(), _site_receipt())
        self.assertIn("https://news.example/stiri/apa-oprita/", caption)
        self.assertIn("Example Author", caption)
        self.assertIn("CC BY-SA 3.0", caption)
        self.assertIn("nu reprezintă intervenția", caption)

    def test_post_is_read_back_before_verified_receipt(self) -> None:
        calls = []
        def fake_open(request, timeout=0):
            calls.append((request.get_method(), request.full_url, request.data))
            url = request.full_url
            if url == "https://images.example/photo.jpg":
                return _Response(b"\xff\xd8\xff" + b"x" * 2048, {"Content-Type": "image/jpeg"})
            if "/me?fields=id,name&access_token=" in url:
                return _Response(json.dumps({"id": "page-123", "name": "CRAIOVA CLAR"}).encode())
            if request.get_method() == "POST" and url.endswith("/page-123/photos"):
                self.assertNotIn(b"fixture-secret", request.data or b"")  # token is supplied below, not this sentinel
                return _Response(json.dumps({"post_id": "post-456"}).encode())
            if "/post-456?fields=id,permalink_url&access_token=" in url:
                return _Response(json.dumps({
                    "id": "post-456",
                    "permalink_url": "https://www.facebook.com/page/posts/post-456",
                }).encode())
            raise AssertionError(f"unexpected request: {request.get_method()} {url}")

        publisher = FacebookPagePublisher(
            page_id="page-123",
            access_token="token-for-test",
            graph_version="v26.0",
            request_fn=fake_open,
        )
        receipt = publisher(_story(), _site_receipt())
        self.assertEqual(receipt.status, "published_verified")
        self.assertEqual(receipt.external_id, "post-456")
        self.assertEqual(receipt.destination, "facebook_page")
        self.assertIn("facebook.com", receipt.metadata["permalink_url"])
        self.assertTrue(any(method == "POST" for method, _url, _body in calls))

    def test_failed_readback_never_claims_verified(self) -> None:
        def fake_open(request, timeout=0):
            url = request.full_url
            if url == "https://images.example/photo.jpg":
                return _Response(b"\xff\xd8\xff" + b"x" * 2048, {"Content-Type": "image/jpeg"})
            if "/me?fields=id,name&access_token=" in url:
                return _Response(json.dumps({"id": "page-123", "name": "CRAIOVA CLAR"}).encode())
            if request.get_method() == "POST" and url.endswith("/page-123/photos"):
                return _Response(json.dumps({"post_id": "post-456"}).encode())
            if "/post-456?fields=id,permalink_url&access_token=" in url:
                return _Response(json.dumps({"id": "post-456"}).encode())
            raise AssertionError(url)

        publisher = FacebookPagePublisher(
            page_id="page-123", access_token="token-for-test", graph_version="v26.0", request_fn=fake_open
        )
        receipt = publisher(_story(), _site_receipt())
        self.assertEqual(receipt.status, "submitted_unverified")
        self.assertEqual(receipt.external_id, "post-456")


if __name__ == "__main__":
    unittest.main()
