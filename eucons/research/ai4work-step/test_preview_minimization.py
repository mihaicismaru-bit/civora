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
    def test_preview_contains_only_controlled_analytical_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            result = build(target)
            self.assertEqual(result["status"], "PASS_PREVIEW_ONLY")
            pages = sorted(target.rglob("index.html"))
            self.assertEqual(len(pages), 3)

            total_selects = 0
            for page in pages:
                scanner = _ControlScanner()
                scanner.feed(page.read_text(encoding="utf-8"))
                self.assertEqual(
                    scanner.forbidden,
                    [],
                    msg=f"free-text/direct-entry control present in {page}: {scanner.forbidden}",
                )
                total_selects += scanner.select_count

            self.assertGreater(total_selects, 0, "expected controlled select inputs in questionnaire previews")


if __name__ == "__main__":
    unittest.main()
