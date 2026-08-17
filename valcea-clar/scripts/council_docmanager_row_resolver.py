#!/usr/bin/env python3
"""Structural resolver for Râmnicu Vâlcea DocManager HCL view rows.

Lotus/DocManager can split the year, decision number, title and link across
separate cells in the same table row. Anchor-only parsing loses that
association. This module reconstructs it at `<tr>` scope and then delegates the
existing Fact Kernel Builder unchanged.

Security/editorial boundaries:
- only links canonicalized by council_watch_rm_valcea are admitted;
- only rows that exactly parse as 2026 HCL entries are eligible;
- only decision number + date pairs already requested by the kernel are mapped;
- no fuzzy title matching and no cross-host crawling;
- document semantics and the 100% evidence requirement remain in the base
  Council Fact Kernel Builder.
"""
from __future__ import annotations

import argparse
import html
import re
from html.parser import HTMLParser
from typing import Any

import council_fact_kernel as base
import council_watch_rm_valcea as council

_BASE_DECISION_ATTACHMENTS = base.decision_attachments

ROW_ENTRY = re.compile(
    rf"\b2026\s+(?P<number>\d{{1,4}})\s+hotarirea\s+(?P=number)\s*-\s*"
    rf"(?P<day>[0-3]?\d)\s+(?P<month>{council.MONTH_PATTERN})\s+2026\s*-\s*"
    rf"(?P<title>.+?)\s*$",
    re.I,
)


class RowParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, Any]] = []
        self._depth = 0
        self._parts: list[str] = []
        self._hrefs: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        low = tag.lower()
        if low in {"script", "style", "noscript"}:
            self._skip += 1
        if low == "tr":
            if self._depth == 0:
                self._parts = []
                self._hrefs = []
            self._depth += 1
        if self._depth and low == "a":
            values = {k.lower(): (v or "") for k, v in attrs}
            href = values.get("href")
            if href:
                self._hrefs.append(href)
        if self._depth and low in {"td", "th", "br", "p", "div"}:
            self._parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        low = tag.lower()
        if low in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        if low == "tr" and self._depth:
            self._depth -= 1
            if self._depth == 0:
                text = html.unescape(" ".join(self._parts)).replace("\u00a0", " ")
                text = re.sub(r"\s+", " ", text).strip()
                self.rows.append({"text": text, "hrefs": list(dict.fromkeys(self._hrefs))})
                self._parts = []
                self._hrefs = []

    def handle_data(self, data: str) -> None:
        if self._depth and not self._skip:
            self._parts.append(data)


def table_row_links(register_url: str, register_body: str) -> list[dict[str, Any]]:
    parser = RowParser()
    parser.feed(register_body)
    rows: list[dict[str, Any]] = []
    for row in parser.rows:
        text = str(row.get("text") or "")
        match = ROW_ENTRY.search(text)
        if not match:
            continue
        day = council.iso_date(int(match.group("day")), match.group("month"))
        if not day:
            continue
        canonical: list[str] = []
        for href in row.get("hrefs") or []:
            url = council.canonical_url(register_url, str(href))
            if url:
                canonical.append(url)
        if not canonical:
            continue
        canonical = list(dict.fromkeys(canonical))
        canonical.sort(
            key=lambda url: (
                0 if "$file" in url.lower() else 1 if "opendocument" in url.lower() else 2,
                len(url),
            )
        )
        rows.append({
            "decision_number": int(match.group("number")),
            "decision_date": day,
            "title": re.sub(r"\s+", " ", match.group("title")).strip(" -"),
            "url": canonical[0],
            "link_count": len(canonical),
        })
    return rows


def structural_decision_attachments(register_url: str, register_body: str, requested: list[dict[str, Any]]) -> dict[int, str]:
    out = dict(_BASE_DECISION_ATTACHMENTS(register_url, register_body, requested))
    wanted = {
        (int(row.get("decision_number") or 0), str(row.get("decision_date") or ""))
        for row in requested
    }
    for row in table_row_links(register_url, register_body):
        key = (int(row["decision_number"]), str(row["decision_date"]))
        if key in wanted and key[0] not in out:
            out[key[0]] = str(row["url"])
    return out


def install() -> None:
    base.decision_attachments = structural_decision_attachments


def self_test() -> int:
    mock = """
    <table>
      <tr><td><a href="/dm/2026/hotarari.nsf/vwHotarariByAn/ABC?OpenDocument">2026</a></td>
          <td>304</td><td>hotarirea 304 - 23 iulie 2026 - acordare autorizatie anuala de functionare slot machine pentru jocuri de noroc CARADUNE SRL strada Lucian Blaga nr 1A</td></tr>
      <tr><td>2026</td><td>299</td><td>hotarirea 299 - 23 iulie 2026 - aprobare raport activitate</td></tr>
    </table>
    """
    parsed = table_row_links(council.ADOPTED_VIEW, mock)
    assert len(parsed) == 1
    assert parsed[0]["decision_number"] == 304
    assert parsed[0]["decision_date"] == "2026-07-23"
    requested = [{
        "decision_number": 304,
        "decision_date": "2026-07-23",
        "title": "acordare autorizatie anuala de functionare slot machine pentru jocuri de noroc CARADUNE SRL strada Lucian Blaga nr 1A",
    }]
    resolved = structural_decision_attachments(council.ADOPTED_VIEW, mock, requested)
    assert 304 in resolved and "ABC" in resolved[304]
    install()
    assert structural_decision_attachments(council.ADOPTED_VIEW, mock, requested) == resolved
    print("VÂLCEA CLAR DocManager table-row resolver self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--resolver-self-test", action="store_true")
    args, _ = parser.parse_known_args()
    if args.resolver_self_test:
        return self_test()
    install()
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
