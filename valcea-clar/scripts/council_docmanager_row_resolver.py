#!/usr/bin/env python3
"""Structural resolver for Râmnicu Vâlcea DocManager HCL view rows.

Lotus/DocManager can split year, decision number, title and navigation metadata
across separate cells/attributes in one table row. This module reconstructs an
exact row identity and extracts only literal official document targets. It then
delegates document semantics and publication eligibility to the existing strict
Council Fact Kernel Builder.

Security/editorial boundaries:
- only targets canonicalized by council_watch_rm_valcea are admitted;
- only URLs containing a Lotus 32-hex document UNID are eligible;
- JavaScript is never executed; only literal URL/path substrings are extracted;
- only rows that exactly parse as 2026 HCL entries are eligible;
- only requested decision-number + decision-date pairs are mapped;
- no fuzzy matching, no cross-host crawling, no inferred document identity;
- semantic verification and the 100% evidence requirement remain unchanged.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import urllib.parse
from html.parser import HTMLParser
from typing import Any, Iterable

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
LOTUS_UNID = r"[0-9a-f]{32}"
LOTUS_DOCUMENT_PATH = re.compile(
    rf"^/dm/2026/hotarari\.nsf/(?:[^/]+/)?{LOTUS_UNID}(?:/|$)",
    re.I,
)
# Extract only a literal official-path-shaped value from an attribute. This is
# deliberately not a JavaScript parser: executable expressions are ignored.
LOTUS_LITERAL_TARGET = re.compile(
    rf"(?P<target>(?:https?://[^\s\"'()<>]+)?/?dm/2026/hotarari\.nsf/"
    rf"(?:[^/\s\"'()<>]+/)?{LOTUS_UNID}(?:[/?][^\s\"'()<>]*)?)",
    re.I,
)
ROUTE_ATTRS = {"href", "onclick", "action", "formaction", "data-href", "data-url", "data-link", "data-target", "data-document"}


class RowParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, Any]] = []
        self._depth = 0
        self._parts: list[str] = []
        self._route_values: list[tuple[str, str]] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        low = tag.lower()
        if low in {"script", "style", "noscript"}:
            self._skip += 1
        if low == "tr":
            if self._depth == 0:
                self._parts = []
                self._route_values = []
            self._depth += 1

        if self._depth:
            for key, raw_value in attrs:
                name = str(key or "").lower()
                value = str(raw_value or "").strip()
                if not value:
                    continue
                # Known routing attributes are retained. A value attribute is
                # considered only if it visibly contains a Lotus/document token;
                # ordinary form data is never collected.
                if name in ROUTE_ATTRS or (
                    name == "value" and ("hotarari.nsf" in value.lower() or re.search(LOTUS_UNID, value, re.I))
                ):
                    self._route_values.append((name, value))

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
                    "route_values": list(dict.fromkeys(self._route_values)),
                })
                self._parts = []
                self._route_values = []

    def handle_data(self, data: str) -> None:
        if self._depth and not self._skip:
            self._parts.append(data)


def is_lotus_document_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    path = urllib.parse.unquote(parsed.path)
    return bool(LOTUS_DOCUMENT_PATH.match(path))


def literal_targets(register_url: str, values: Iterable[tuple[str, str]]) -> list[str]:
    """Extract literal Lotus document paths without executing any script."""
    targets: list[str] = []
    for _kind, raw in values:
        decoded = urllib.parse.unquote(html.unescape(str(raw)))
        for match in LOTUS_LITERAL_TARGET.finditer(decoded):
            literal = match.group("target")
            # Normalize optional missing leading slash for relative `dm/...`.
            if literal.lower().startswith("dm/"):
                literal = "/" + literal
            url = council.canonical_url(register_url, literal)
            if url and is_lotus_document_url(url):
                targets.append(url)
    return list(dict.fromkeys(targets))


def table_row_links(register_url: str, register_body: str) -> list[dict[str, Any]]:
    parser = RowParser()
    parser.feed(register_body)
    rows: list[dict[str, Any]] = []
    parsed_hcl_rows = 0
    hcl_rows_with_href = 0
    hcl_rows_with_javascript_href = 0
    hcl_rows_with_onclick = 0
    hcl_rows_with_data_link = 0
    hcl_rows_with_form_action = 0
    literal_doc_targets_found = 0

    for row in parser.rows:
        text = str(row.get("text") or "")
        match = ROW_ENTRY.search(text)
        if not match:
            continue
        parsed_hcl_rows += 1
        day = council.iso_date(int(match.group("day")), match.group("month"))
        if not day:
            continue

        values = [(str(name), str(value)) for name, value in row.get("route_values") or []]
        names = {name for name, _value in values}
        href_values = [value for name, value in values if name == "href"]
        if href_values:
            hcl_rows_with_href += 1
        if any(value.lower().lstrip().startswith("javascript:") for value in href_values):
            hcl_rows_with_javascript_href += 1
        if "onclick" in names:
            hcl_rows_with_onclick += 1
        if any(name.startswith("data-") for name in names):
            hcl_rows_with_data_link += 1
        if "action" in names or "formaction" in names:
            hcl_rows_with_form_action += 1

        canonical = literal_targets(register_url, values)
        literal_doc_targets_found += len(canonical)
        if not canonical:
            continue
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
        "hcl_rows_with_href": hcl_rows_with_href,
        "hcl_rows_with_javascript_href": hcl_rows_with_javascript_href,
        "hcl_rows_with_onclick": hcl_rows_with_onclick,
        "hcl_rows_with_data_link": hcl_rows_with_data_link,
        "hcl_rows_with_form_action": hcl_rows_with_form_action,
        "literal_doc_targets_found": literal_doc_targets_found,
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
    unid_href = "0123456789ABCDEF0123456789ABCDEF"
    unid_onclick = "11111111111111111111111111111111"
    unid_data = "22222222222222222222222222222222"
    mock = f"""
    <table>
      <tr><td><a href="/dm/2026/hotarari.nsf/vwHotarariByAn/{unid_href}?OpenDocument">2026</a></td>
          <td>304</td><td>hotarirea 304 - 23 iulie 2026 - acordare autorizatie anuala de functionare slot machine pentru jocuri de noroc CARADUNE SRL strada Lucian Blaga nr 1A</td></tr>
      <tr onclick="window.open('/dm/2026/hotarari.nsf/vwHotarariByAn/{unid_onclick}?OpenDocument')">
          <td>2026</td><td>303</td><td>hotarirea 303 - 23 iulie 2026 - acordare autorizatie anuala jocuri de noroc CARADUNE SRL</td></tr>
      <tr data-href="/dm/2026/hotarari.nsf/vwHotarariByAn/{unid_data}?OpenDocument">
          <td>2026</td><td>302</td><td>hotarirea 302 - 23 iulie 2026 - acordare autorizatie anuala jocuri de noroc SUPERBET RETAIL SA</td></tr>
      <tr onclick="doSomething(304)"><td><a href="javascript:openRow(304)">2026</a></td>
          <td>299</td><td>hotarirea 299 - 23 iulie 2026 - aprobare raport activitate</td></tr>
    </table>
    """
    parsed = table_row_links(council.ADOPTED_VIEW, mock)
    assert [row["decision_number"] for row in parsed] == [304, 303, 302]
    assert all(row["decision_date"] == "2026-07-23" for row in parsed)
    assert all(is_lotus_document_url(row["url"]) for row in parsed)
    assert _LAST_STATS["hcl_rows_with_onclick"] == 2
    assert _LAST_STATS["hcl_rows_with_data_link"] == 1
    assert _LAST_STATS["hcl_rows_with_javascript_href"] == 1
    assert _LAST_STATS["literal_doc_targets_found"] == 3

    requested = [
        {"decision_number": 304, "decision_date": "2026-07-23", "title": "x"},
        {"decision_number": 303, "decision_date": "2026-07-23", "title": "x"},
        {"decision_number": 302, "decision_date": "2026-07-23", "title": "x"},
    ]
    resolved = structural_decision_attachments(council.ADOPTED_VIEW, mock, requested)
    assert set(resolved) == {304, 303, 302}
    install()
    assert structural_decision_attachments(council.ADOPTED_VIEW, mock, requested) == resolved
    print("VÂLCEA CLAR DocManager literal-target resolver self-test: PASS")
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
