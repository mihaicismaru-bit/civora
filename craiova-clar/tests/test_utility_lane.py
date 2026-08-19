from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from clar_core.contracts import SourceItem
from clar_core.publishers.static_site import StaticSitePublisher
from clar_core.verticals.utility import UtilityStoryComposer, WaterUtilityExtractor


class UtilityLaneTest(unittest.TestCase):
    def setUp(self) -> None:
        self.item = SourceItem(
            source_id="official-water-utility",
            canonical_url="https://example.invalid/official-notice",
            title="ANUNȚ ÎNTRERUPERE ALIMENTARE CU APĂ ÎN CARTIERUL CRAIOVEAN VALEA ROȘIE, JOI, 20 AUGUST",
            discovered_at=datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc),
            published_at=datetime(2026, 8, 19, 9, 0, tzinfo=timezone.utc),
            body_text=(
                "În vederea executării unor lucrări esențiale de reparații armături în zona PT1 Revoluției, "
                "se anunță întreruperea alimentării cu apă potabilă JOI, 20.08.2026, în intervalul orar 11.00-15.00. "
                "Afectați fiind: utilizatorii din zona cuprinsă în perimetrul străzilor Caracal – Henri Coandă – Împăratul Traian. "
                "Atenționăm utilizatorii că se pot produce modificări temporare ale calității apei din punct de vedere al turbidității, "
                "iar consumul trebuie evitat până la limpezire."
            ),
        )

    def test_extract_compose_render(self) -> None:
        packet = WaterUtilityExtractor(
            allowed_localities=["Craiova", "craiovean"], area_prefixes=["craiovean"]
        )(self.item)
        self.assertIsNotNone(packet)
        assert packet is not None
        self.assertEqual(packet.facts["event_date"], "2026-08-20")
        self.assertEqual(packet.facts["start_time"], "11:00")
        self.assertEqual(packet.facts["end_time"], "15:00")
        self.assertIn("VALEA ROȘIE", str(packet.facts["area_hint"]).upper())
        story = UtilityStoryComposer(product_name="CRAIOVA CLAR", source_name="Operatorul oficial")(packet)
        self.assertIsNotNone(story)
        assert story is not None
        self.assertIn("2026-08-20", story.headline)
        with tempfile.TemporaryDirectory() as tmp:
            receipt = StaticSitePublisher(root=tmp, product_name="CRAIOVA CLAR")(story)
            self.assertEqual(receipt.status, "rendered")
            self.assertTrue((Path(tmp) / "stiri" / story.slug / "index.html").exists())
            page = (Path(tmp) / "stiri" / story.slug / "index.html").read_text(encoding="utf-8")
            self.assertIn("application/ld+json", page)
            self.assertIn("Sursa oficială", page)

    def test_rejects_other_locality_when_scope_is_craiova(self) -> None:
        item = SourceItem(
            **{
                **self.item.__dict__,
                "title": "Întrerupere apă în Calafat",
                "body_text": "În Calafat, 20.08.2026, apa se întrerupe între 11.00-15.00.",
            }
        )
        self.assertIsNone(WaterUtilityExtractor(allowed_localities=["Craiova"])(item))


if __name__ == "__main__":
    unittest.main()
