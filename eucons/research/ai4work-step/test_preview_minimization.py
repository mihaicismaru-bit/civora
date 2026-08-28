from __future__ import annotations

import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from build_research_pages import build


class _ControlScanner(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forbidden: list[str] = []
        self.select_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = tag.lower()
        attr_map = {k.lower(): (v or "").lower() for k, v in attrs}
        if tag_l == "textarea":
            self.forbidden.append("textarea")
        elif tag_l == "input":
            input_type = attr_map.get("type", "text")
            if input_type in {
                "text",
                "email",
                "tel",
                "url",
                "search",
                "password",
                "number",
                "date",
                "datetime-local",
            }:
                self.forbidden.append(f"input:{input_type}")
        elif tag_l == "select":
            self.select_count += 1


class PreviewMinimizationTests(unittest.TestCase):
    def test_fail_closed_pages_contain_only_controlled_analytical_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            result = build(target)
            self.assertEqual(result["status"], "PASS_FAIL_CLOSED")
            self.assertFalse(result["production_enabled"])
            self.assertFalse(result["test_twin_evidence_eligible"])
            self.assertEqual(
                result["endpoint"],
                "https://api.eucons.ro/research/ai4work/v1/submit",
            )
            pages = sorted(target.rglob("index.html"))
            self.assertEqual(len(pages), 3)
            self.assertTrue((target / "assets" / "ai4work-research.js").is_file())

            total_selects = 0
            for page in pages:
                scanner = _ControlScanner()
                text = page.read_text(encoding="utf-8")
                scanner.feed(text)
                self.assertEqual(
                    scanner.forbidden,
                    [],
                    msg=f"free-text/direct-entry control present in {page}: {scanner.forbidden}",
                )
                self.assertIn('name="robots" content="noindex,nofollow"', text)
                total_selects += scanner.select_count

            self.assertGreater(total_selects, 0, "expected controlled select inputs in questionnaire previews")

    def test_boolean_is_rendered_for_json_boolean_serialization_not_da_nu_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            build(target)
            adult = (target / "cercetare" / "ai4work-step" / "adulti" / "index.html").read_text(encoding="utf-8")
            self.assertIn('data-question-id="Q07" data-question-type="boolean"', adult)
            self.assertIn('name="Q07" value="true"', adult)
            self.assertIn('name="Q07" value="false"', adult)
            self.assertNotIn('name="Q07" value="da"', adult)
            self.assertNotIn('name="Q07" value="nu"', adult)

    def test_disabled_ui_cannot_submit_even_if_client_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            build(target)
            adult = (target / "cercetare" / "ai4work-step" / "adulti" / "index.html").read_text(encoding="utf-8")
            self.assertIn('data-collection-enabled="false"', adult)
            self.assertIn('data-ai4work-submit disabled', adult)
            self.assertIn('/assets/ai4work-research.js', adult)


if __name__ == "__main__":
    unittest.main()
