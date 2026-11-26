from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from build_research_pages import build


class Article13RenderedLegalBasisLabelTests(unittest.TestCase):
    def test_rendered_notice_uses_approved_legitimate_interest_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            result = build(target)
            self.assertEqual(result["status"], "PASS_FAIL_CLOSED")
            adult = target / "cercetare" / "ai4work-step" / "adulti" / "index.html"
            employer = target / "cercetare" / "ai4work-step" / "angajatori" / "index.html"
            for page in (adult, employer):
                text = page.read_text(encoding="utf-8")
                self.assertIn("Interes legitim urmărit:", text)
                self.assertNotIn("Interes legitim propus, dacă acesta este temeiul final:", text)


if __name__ == "__main__":
    unittest.main()
