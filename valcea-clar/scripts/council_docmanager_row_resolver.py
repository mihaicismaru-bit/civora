#!/usr/bin/env python3
"""Structural resolver for Râmnicu Vâlcea DocManager HCL view rows.

The live DocManager diagnostic proved that the adopted-HCL view contains 305
rows and 304 per-row images, but zero `<a>` links. Lotus therefore carries the
document navigation in row element attributes rather than anchors. This module
associates those attributes with the exact HCL row identity and admits only
Lotus document UNIDs on the official host.

Security/editorial boundaries:
- only links canonicalized by council_watch_rm_valcea are admitted;
- only URLs containing a Lotus 32-hex document UNID are eligible;
- a bare 32-hex token may be expanded only inside an exactly parsed HCL row;
- only decision number + date pairs already requested by the kernel are mapped;
- no fuzzy matching and no cross-host crawling;
- document semantics and the 100% evidence requirement remain in the base
  Council Fact Kernel Builder.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import urllib.parse
from html.parser import HTMLParser
from typing import Any

import council_fact_kernel as base
import council_watch_rm_valcea as council

_BASE_DECISION_ATTACHMENTS = base.decision_attachments
_LAST_STATS: dict[str, int] = {}

ROW_ENTRY = re.compile(
    rf"\b2026\s+(?P<number>\d{{1,4}})\s+hotarirea\s+(?P=number)\s*-\s*"
    rf"(?P<day>[0-3]?\d)\s+(?P<month>{council.MONTH_PATTERN})\s+2026\s*-\s*"
    rf"(?P<title>.+?)\s*$",
    re.I,
)
LOTUS_DOCUMENT_PATH = re.compile(
    r"^/dm/2026/hotarari\.nsf/(?:[^/]+/)?[0-9a-f]{32}(?:/|$)",
    re.I,
)
LOTUS_UNID = re.compile(r"(?<![0-9a-f])([0-9a-f]{32})(?![0-9a-f])", re.I)
LOTUS_PATH_IN_ATTRIBUTE = re.compile(
    r"(?:https?://dm\.primariavl\.ro)?(/dm/2026/hotarari\.nsf/[A-Za-z0-9_.$%?=&/+-]+)",
    re.I,
)


class RowParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, Any]] = []
        self._depth = 0
        self._parts: list[str] = []
        self._hrefs: list[str] = []
        self._attributes: list[tuple[str, str, str]] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        low = tag.lower()
        if low in {"script", "style", "noscript"}:
            self._skip += 1
        if low == "tr":
            if self._depth == 0:
                self._parts = []
                self._hrefs = []
                self._attributes = []
            self._depth += 1
        if self._depth:
            for key, raw_value in attrs:
                value = str(raw_value or "").strip()
                if not value or len(value) > 4000:
                    continue
                key_low = str(key or "").lower()
                if key_low == "href":
                    self._hrefs.append(value)
                # Keep attributes in memory only for exact-row URL/UNID
                # extraction. No raw attribute values are persisted by runtime.
                self._attributes.append((low, key_low, value))
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
                self.rows.append({
                    "text": text,
                    "hrefs": list(dict.fromkeys(self._hrefs)),
                    "attributes": list(self._attributes),
                })
                self._parts = []
                self._hrefs = []
                self._attributes = []

    def handle_data(self, data: str) -> None:
        if self._depth and not self._skip:
            self._parts.append(data)


def is_lotus_document_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    path = urllib.parse.unquote(parsed.path)
    return parsed.netloc.lower() == "dm.primariavl.ro" and bool(LOTUS_DOCUMENT_PATH.match(path))


def url_from_unid(register_url: str, unid: str) -> str | None:
    token = str(unid or "").upper()
    if not re.fullmatch(r"[0-9A-F]{32}", token):
        return None
    candidate = urllib.parse.urljoin(
        register_url,
        f"/dm/2026/hotarari.nsf/vwHotarariByAn/{token}?OpenDocument",
    )
    canonical = council.canonical_url(register_url, candidate)
    return canonical if canonical and is_lotus_document_url(canonical) else None


def attribute_document_urls(register_url: str, attributes: list[tuple[str, str, str]]) -> list[str]:
    """Extract official Lotus document candidates from exact-row attributes."""
    direct: list[str] = []
    expanded: list[str] = []
    for _tag, _key, raw_value in attributes:
        value = html.unescape(urllib.parse.unquote(str(raw_value or "")))
        for match in LOTUS_PATH_IN_ATTRIBUTE.finditer(value):
            candidate = urllib.parse.urljoin(register_url, match.group(1))
            canonical = council.canonical_url(register_url, candidate)
            if canonical and is_lotus_document_url(canonical):
                direct.append(canonical)
        for match in LOTUS_UNID.finditer(value):
            candidate = url_from_unid(register_url, match.group(1))
            if candidate:
                expanded.append(candidate)
    return list(dict.fromkeys(direct + expanded))[:8]


def table_row_links(register_url: str, register_body: str) -> list[dict[str, Any]]:
    parser = RowParser()
    parser.feed(register_body)
    rows: list[dict[str, Any]] = []
    parsed_hcl_rows = 0
    rows_with_attr_candidate = 0
    for row in parser.rows:
        text = str(row.get("text") or "")
        match = ROW_ENTRY.search(text)
        if not match:
            continue
        parsed_hcl_rows += 1
        day = council.iso_date(int(match.group("day")), match.group("month"))
        if not day:
            continue
        canonical: list[str] = []
        for href in row.get("hrefs") or []:
            url = council.canonical_url(register_url, str(href))
            if url and is_lotus_document_url(url):
                canonical.append(url)
        attr_urls = attribute_document_urls(register_url, row.get("attributes") or [])
        if attr_urls:
            rows_with_attr_candidate += 1
            canonical.extend(attr_urls)
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
    _LAST_STATS.update({
        "table_rows_total": len(parser.rows),
        "hcl_rows_parsed": parsed_hcl_rows,
        "hcl_rows_with_attribute_document_candidate": rows_with_attr_candidate,
        "hcl_rows_with_document_url": len(rows),
    })
    return rows


def structural_decision_attachments(register_url: str, register_body: str, requested: list[dict[str, Any]]) -> dict[int, str]:
    out = dict(_BASE_DECISION_ATTACHMENTS(register_url, register_body, requested))
    base_resolved = len(out)
    wanted = {
        (int(row.get("decision_number") or 0), str(row.get("decision_date") or ""))
        for row in requested
    }
    structural_resolved = 0
    for row in table_row_links(register_url, register_body):
        key = (int(row["decision_number"]), str(row["decision_date"]))
        if key in wanted and key[0] not in out:
            out[key[0]] = str(row["url"])
            structural_resolved += 1
    _LAST_STATS.update({
        "requested": len(wanted),
        "base_resolved": base_resolved,
        "structural_resolved": structural_resolved,
        "resolved_total": len(out),
    })
    return out


def install() -> None:
    base.decision_attachments = structural_decision_attachments


def self_test() -> int:
    unid = "0123456789ABCDEF0123456789ABCDEF"
    second_unid = "FEDCBA9876543210FEDCBA9876543210"
    mock = f"""
    <table>
      <tr><td><img src="/icons/vwicn073.gif" onclick="window.location='/dm/2026/hotarari.nsf/vwHotarariByAn/{unid}?OpenDocument'">2026</td>
          <td>304</td><td>hotarirea 304 - 23 iulie 2026 - acordare autorizatie anuala de functionare slot machine pentru jocuri de noroc CARADUNE SRL strada Lucian Blaga nr 1A</td></tr>
      <tr><td><img src="/icons/vwicn073.gif" data-unid="{second_unid}">2026</td>
          <td>303</td><td>hotarirea 303 - 23 iulie 2026 - acordare autorizatie anuala de functionare pentru jocuri de noroc CARADUNE SRL strada Florilor nr 22</td></tr>
      <tr><td><img src="/icons/vwicn073.gif">2026</td>
          <td>299</td><td>hotarirea 299 - 23 iulie 2026 - aprobare raport activitate</td></tr>
    </table>
    """
    parsed = table_row_links(council.ADOPTED_VIEW, mock)
    assert len(parsed) == 2
    assert parsed[0]["decision_number"] == 304
    assert parsed[1]["decision_number"] == 303
    assert is_lotus_document_url(parsed[0]["url"])
    assert unid in parsed[0]["url"]
    assert second_unid in parsed[1]["url"]
    assert not is_lotus_document_url(council.ADOPTED_VIEW + "&Start=20")
    assert len(attribute_document_urls(council.ADOPTED_VIEW, [("img", "src", "/icons/vwicn073.gif")])) == 0
    requested = [
        {"decision_number": 304, "decision_date": "2026-07-23", "title": "x"},
        {"decision_number": 303, "decision_date": "2026-07-23", "title": "y"},
    ]
    resolved = structural_decision_attachments(council.ADOPTED_VIEW, mock, requested)
    assert set(resolved) == {303, 304}
    assert _LAST_STATS["resolved_total"] == 2
    install()
    assert structural_decision_attachments(council.ADOPTED_VIEW, mock, requested) == resolved
    print("VÂLCEA CLAR DocManager attribute/UNID resolver self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--resolver-self-test", action="store_true")
    args, _ = parser.parse_known_args()
    if args.resolver_self_test:
        return self_test()
    install()
    result = base.main()
    if _LAST_STATS:
        print(json.dumps({"docmanager_row_resolver": _LAST_STATS}, ensure_ascii=False))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
