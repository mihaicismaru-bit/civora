from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from clar_core.contracts import Story
from clar_core.media import MediaPackResolver
from clar_core.publishers.static_site import StaticSitePublisher


class MediaSelectionTest(unittest.TestCase):
    def _story(self) -> Story:
        return Story(
            story_id="story-1",
            slug="apa-oprita",
            section="UTILITĂȚI",
            headline="Apa va fi oprită în Valea Roșie",
            dek="O întrerupere programată afectează o zonă din oraș.",
            paragraphs=("Text factual.",),
            source_urls=("https://example.invalid/source",),
            published_at=datetime(2026, 8, 19, 9, 0, tzinfo=timezone.utc),
            media_query="Valea Roșie",
        )

    def test_context_asset_requires_verified_rights_and_is_labelled(self) -> None:
        assets = [
            {
                "asset_id": "blocked",
                "image_url": "https://example.invalid/blocked.jpg",
                "source_page": "https://example.invalid/blocked",
                "rights_status": "UNKNOWN",
                "specificity": "PLACE_DIRECT",
                "match_terms": ["Valea Roșie"],
                "locality_tags": ["Craiova"],
            },
            {
                "asset_id": "archive-craiova",
                "image_url": "https://upload.wikimedia.org/example.jpg",
                "source_page": "https://commons.wikimedia.org/wiki/File:Example.jpg",
                "creator": "Example Author",
                "license": "CC BY-SA 3.0",
                "license_url": "https://creativecommons.org/licenses/by-sa/3.0/",
                "rights_status": "VERIFIED_REUSABLE",
                "specificity": "CONTEXT_ARCHIVE",
                "usage_scope": ["site_article"],
                "locality_tags": ["Craiova"],
                "match_terms": ["Calea București"],
                "caption": "Imagine de arhivă din Craiova; nu reprezintă intervenția descrisă.",
            },
        ]
        enriched = MediaPackResolver(assets, context_terms=["Craiova"])(self._story())
        self.assertEqual(enriched.metadata["media_status"], "SELECTED_REAL_REUSABLE")
        self.assertEqual(enriched.metadata["media"]["asset_id"], "archive-craiova")
        self.assertIn("nu reprezintă", enriched.metadata["media"]["caption"])

    def test_no_safe_media_fails_closed(self) -> None:
        enriched = MediaPackResolver(
            [
                {
                    "asset_id": "unknown-rights",
                    "image_url": "https://example.invalid/a.jpg",
                    "source_page": "https://example.invalid/a",
                    "rights_status": "UNKNOWN",
                    "specificity": "PLACE_DIRECT",
                    "match_terms": ["Valea Roșie"],
                }
            ],
            context_terms=["Craiova"],
        )(self._story())
        self.assertEqual(enriched.metadata["media_status"], "NO_SAFE_MEDIA")
        self.assertNotIn("media", enriched.metadata)

    def test_static_page_emits_attribution_and_open_graph_image(self) -> None:
        story = MediaPackResolver(
            [
                {
                    "asset_id": "archive-craiova",
                    "image_url": "https://upload.wikimedia.org/example.jpg",
                    "source_page": "https://commons.wikimedia.org/wiki/File:Example.jpg",
                    "creator": "Example Author",
                    "license": "CC BY-SA 3.0",
                    "license_url": "https://creativecommons.org/licenses/by-sa/3.0/",
                    "rights_status": "VERIFIED_REUSABLE",
                    "specificity": "CONTEXT_ARCHIVE",
                    "usage_scope": ["site_article"],
                    "locality_tags": ["Craiova"],
                    "caption": "Imagine de arhivă din Craiova; nu reprezintă intervenția descrisă.",
                }
            ],
            context_terms=["Craiova"],
        )(self._story())
        with tempfile.TemporaryDirectory() as tmp:
            StaticSitePublisher(root=tmp, product_name="CRAIOVA CLAR", base_url="https://news.example")(story)
            page = (Path(tmp) / "stiri" / story.slug / "index.html").read_text(encoding="utf-8")
            self.assertIn('property="og:image"', page)
            self.assertIn("Example Author", page)
            self.assertIn("CC BY-SA 3.0", page)
            self.assertIn("nu reprezintă intervenția", page)


if __name__ == "__main__":
    unittest.main()
