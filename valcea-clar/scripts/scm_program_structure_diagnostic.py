#!/usr/bin/env python3
"""Bounded structural diagnostic for the official SCM Râmnicu Vâlcea program page.

This tool has no publication authority. It records only parser-relevant HTML
structure and boolean fixture markers so the production parser can be repaired
without persisting or republishing third-party page content.
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://scmramnicuvalcea.ro/program/"
OUTPUT = ROOT / "editorial" / "scm_program_structure.json"
USER_AGENT = "Mozilla/5.0 VÂLCEA-CLAR/1.0 (+https://valceaclar.ro/)"
MAX_BODY_BYTES = 2_000_000
EXPECTED = {"data-date", "data-time", "data-home", "data-away"}


def fetch_html() -> str:
    request = Request(SOURCE_URL, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with urlopen(request, timeout=15, context=ssl.create_default_context()) as response:
        body = response.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            raise ValueError("SCM program diagnostic response exceeds bounded body limit")
        charset = response.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace")


class StructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.table_count = 0
        self.row_count = 0
        self.in_row = False
        self.row_tokens: set[str] = set()
        self.row_profiles: Counter[tuple[str, ...]] = Counter()
        self.class_tokens: Counter[str] = Counter()
        self.startdate_content_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {str(k): str(v or "") for k, v in attrs}
        if tag == "table":
            self.table_count += 1
        if tag == "tr":
            self.row_count += 1
            self.in_row = True
            self.row_tokens = set()
        classes = [token for token in attr.get("class", "").split() if token]
        for token in classes:
            if token.startswith("data-") or token.startswith("sp-"):
                self.class_tokens[token] += 1
                if self.in_row and token.startswith("data-"):
                    self.row_tokens.add(token)
        if tag == "td" and attr.get("itemprop") == "startDate" and attr.get("content"):
            self.startdate_content_count += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr" and self.in_row:
            if self.row_tokens:
                self.row_profiles[tuple(sorted(self.row_tokens))] += 1
            self.in_row = False
            self.row_tokens = set()


def diagnose(html: str) -> dict:
    parser = StructureParser()
    parser.feed(html)
    folded = re.sub(r"\s+", " ", html).casefold()
    profiles = [
        {"classes": list(profile), "rows": count, "event_like": EXPECTED.issubset(set(profile))}
        for profile, count in parser.row_profiles.most_common(12)
    ]
    return {
        "schema_version": "1.0",
        "instance_id": "valcea",
        "source_url": SOURCE_URL,
        "publication_authority": "NONE",
        "diagnostic_scope": "HTML_STRUCTURE_ONLY",
        "body_bytes": len(html.encode("utf-8")),
        "table_count": parser.table_count,
        "row_count": parser.row_count,
        "startdate_content_count": parser.startdate_content_count,
        "class_tokens": dict(sorted(parser.class_tokens.items())),
        "row_profiles": profiles,
        "event_like_row_count": sum(row["rows"] for row in profiles if row["event_like"]),
        "markers": {
            "program_heading": ">program<" in folded or "program" in folded,
            "fixture_date_2026_08_22": "22 aug" in folded,
            "fixture_opponent_fc_bacau": "fc bacau" in folded or "fc bacău" in folded,
            "stadionul_municipal": "stadionul municipal" in folded,
        },
    }


def self_test() -> int:
    html = '''<table class="custom"><tr><td class="data-date">22 aug., 2026</td><td class="data-time">11:00</td><td class="data-home">CSM Ramnicu Valcea</td><td class="data-away">FC Bacau</td><td class="data-venue">Stadionul Municipal</td></tr></table>'''
    report = diagnose(html)
    assert report["table_count"] == 1
    assert report["event_like_row_count"] == 1
    assert report["markers"]["fixture_date_2026_08_22"] is True
    assert report["markers"]["fixture_opponent_fc_bacau"] is True
    print("VÂLCEA CLAR SCM program structure diagnostic self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    report = diagnose(fetch_html())
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
