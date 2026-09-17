from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from clar_core.adapters.official_listing import OfficialListingDiscoverer
from clar_core.contracts import SourceItem
from clar_core.publishers.static_site import StaticSitePublisher
from clar_core.verticals.public_safety import PublicSafetyExtractor, PublicSafetyStoryComposer


OFFICIAL_BODY = """
04 august 2026
În cursul zilei de 03 august 2026, echipajele Inspectoratului pentru Situații de Urgență „Oltenia” al județului Dolj au intervenit pentru gestionarea a 55 de situații de urgență, dintre care 11 incendii de vegetație uscată și miriște, 5 alte situații de urgență și 39 de intervenții pentru acordarea primului ajutor calificat și asistenței medicale de urgență prin echipajele SMURD.
În urma acestor incendii au fost afectate peste 29 de hectare de vegetație uscată și miriște.
Trei dintre intervenții au constat în sprijinirea echipajelor Serviciului de Ambulanță Județean Dolj în municipiul Craiova.
Inspectoratul recomandă anunțarea imediată a oricărei situații de urgență la numărul unic 112.
"""


class PublicSafetyLaneTest(unittest.TestCase):
    def setUp(self) -> None:
        self.item = SourceItem(
            source_id="official-emergency-service",
            canonical_url="https://example.invalid/stiri-locale/misiuni-633",
            title="Misiuni din data de 03 august",
            discovered_at=datetime(2026, 8, 20, 6, 0, tzinfo=timezone.utc),
            published_at=datetime(2026, 8, 4, 0, 0, tzinfo=timezone.utc),
            body_text=OFFICIAL_BODY,
        )

    def test_extract_compose_render(self) -> None:
        packet = PublicSafetyExtractor(scope_terms=["Craiova", "Dolj"])(self.item)
        self.assertIsNotNone(packet)
        assert packet is not None
        self.assertEqual(packet.facts["event_date"], "2026-08-03")
        self.assertEqual(packet.facts["total_emergencies"], 55)
        self.assertEqual(packet.facts["vegetation_fires"], 11)
        self.assertEqual(packet.facts["smurd_interventions"], 39)
        self.assertEqual(packet.facts["other_emergencies"], 5)
        self.assertEqual(packet.facts["affected_hectares"], 29)

        story = PublicSafetyStoryComposer(product_name="CRAIOVA CLAR", source_name="ISU Dolj")(packet)
        self.assertIsNotNone(story)
        assert story is not None
        self.assertEqual(story.section, "SIGURANȚĂ PUBLICĂ")
        self.assertIn("55 de situații de urgență", story.headline)
        self.assertIn("3 august 2026", story.headline)
        self.assertIn("11 incendii", story.headline)

        with tempfile.TemporaryDirectory() as tmp:
            receipt = StaticSitePublisher(root=tmp, product_name="CRAIOVA CLAR")(story)
            self.assertEqual(receipt.status, "rendered")
            page = (Path(tmp) / "stiri" / story.slug / "index.html").read_text(encoding="utf-8")
            self.assertIn("Sursa oficială", page)
            self.assertIn("39 de intervenții", page)

    def test_rejects_unrelated_non_emergency_item(self) -> None:
        item = SourceItem(
            **{
                **self.item.__dict__,
                "title": "Bun venit în echipă!",
                "body_text": "ISU Dolj prezintă noii colegi și le urează succes.",
            }
        )
        self.assertIsNone(PublicSafetyExtractor(scope_terms=["Craiova", "Dolj"])(item))

    def test_official_listing_adapter_is_configurable_and_deduplicates(self) -> None:
        listing = """
        <html><body>
          <a href="/stiri-locale/misiuni-din-data-de-03-august-633">Misiuni din data de 03 august</a>
          <a href="/stiri-locale/misiuni-din-data-de-03-august-633">Misiuni din data de 03 august</a>
          <a href="/cariera/anunt">Anunț carieră</a>
        </body></html>
        """
        article = f"<html><main><h1>Misiuni din data de 03 august</h1><p>{OFFICIAL_BODY}</p></main></html>"

        def fake_fetch(url: str, timeout: int = 20) -> str:
            return listing if url == "https://example.invalid/stiri-locale" else article

        discover = OfficialListingDiscoverer(
            source_id="isu-test",
            listing_url="https://example.invalid/stiri-locale",
            link_prefixes=["/stiri-locale/"],
            max_items=5,
            max_age_hours=None,
        )
        with patch("clar_core.adapters.official_listing._fetch", side_effect=fake_fetch):
            items = list(discover())
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Misiuni din data de 03 august")
        self.assertEqual(items[0].published_at.date().isoformat(), "2026-08-04")
        self.assertIn("55 de situații", items[0].body_text or "")


if __name__ == "__main__":
    unittest.main()
