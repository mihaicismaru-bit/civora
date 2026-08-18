#!/usr/bin/env python3
"""Resolve embedded official DocManager attachments for Council Fact Kernels.

The municipality's Lotus/DocManager pages can expose their real `$FILE` HTML
attachment through non-anchor attributes (for example iframe/object/input/form
metadata). The base verifier intentionally follows only canonical official links;
this adapter broadens only that *HTML extraction surface* while preserving the
same host, document UNID, semantic verification and 100% evidence gates.

JavaScript is never executed. No cross-host URL, unrelated Lotus document or
non-HTML attachment is admitted.
"""
from __future__ import annotations

import html
import re
import sys
import urllib.parse
from html.parser import HTMLParser

import council_docmanager_row_resolver as row_resolver
import council_watch_rm_valcea as council

_BASE_PARSE_LINKS = council.parse_links
LOTUS_UNID_RE = row_resolver.LOTUS_UNID_RE
EMBEDDED_ATTRS = {
    "href",
    "src",
    "data",
    "action",
    "formaction",
    "onclick",
    "value",
    "data-href",
    "data-url",
    "data-link",
    "data-target",
    "data-document",
}
QUOTED_TARGET = re.compile(r"(?P<q>['\"])(?P<target>[^'\"]*\$FILE[^'\"]+)(?P=q)", re.I)


class EmbeddedTargetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            return
        for raw_name, raw_value in attrs:
            name = str(raw_name or "").lower()
            value = str(raw_value or "").strip()
            if not value:
                continue
            if name in EMBEDDED_ATTRS or name.startswith("data-"):
                self.values.append(value)


def _document_unid(url: str) -> str | None:
    # Lotus `$FILE` URLs can contain both a 32-hex view/design token and the
    # actual document UNID. The document identity is the final 32-hex token
    # before the attachment tail, whereas OpenDocument URLs contain only it.
    matches = list(LOTUS_UNID_RE.finditer(urllib.parse.unquote(str(url or ""))))
    return matches[-1].group("unid").upper() if matches else None


def _eligible_attachment(base_url: str, candidate: str) -> str | None:
    url = council.canonical_url(base_url, candidate)
    if not url or not row_resolver.is_lotus_document_url(url):
        return None
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
    low = path.lower()
    if "$file" not in low or not low.endswith((".htm", ".html")):
        return None
    base_unid = _document_unid(base_url)
    candidate_unid = _document_unid(url)
    if base_unid and candidate_unid != base_unid:
        return None
    return url


def _value_candidates(value: str) -> list[str]:
    decoded = urllib.parse.unquote(html.unescape(str(value or ""))).strip()
    if not decoded:
        return []
    candidates: list[str] = []
    if "$file" in decoded.lower() and not decoded.lower().lstrip().startswith("javascript:"):
        candidates.append(decoded)
    for match in QUOTED_TARGET.finditer(decoded):
        candidates.append(match.group("target"))
    # Preserve the row resolver's bounded literal extraction as a final exact
    # fallback for compact attributes that contain no spaces.
    for match in row_resolver.LOTUS_LITERAL_TARGET.finditer(decoded):
        candidates.append(match.group("target"))
    return list(dict.fromkeys(candidates))


def embedded_attachment_links(page_url: str, body: str) -> list[dict[str, str]]:
    parser = EmbeddedTargetParser()
    parser.feed(body)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in parser.values:
        for candidate in _value_candidates(value):
            url = _eligible_attachment(page_url, candidate)
            if not url or url in seen:
                continue
            seen.add(url)
            rows.append({"url": url, "text": ""})
            if len(rows) >= 8:
                return rows
    return rows


def structural_parse_links(page_url: str, body: str) -> list[dict[str, str]]:
    rows = list(_BASE_PARSE_LINKS(page_url, body))
    seen = {str(row.get("url") or "") for row in rows}
    for row in embedded_attachment_links(page_url, body):
        if row["url"] not in seen:
            rows.append(row)
            seen.add(row["url"])
    return rows


def install() -> None:
    row_resolver.install()
    council.parse_links = structural_parse_links


def self_test() -> None:
    unid = "0123456789ABCDEF0123456789ABCDEF"
    other = "11111111111111111111111111111111"
    base_url = council.canonical_url(
        council.ADOPTED_VIEW,
        f"/dm/2026/hotarari.nsf/vwHotarariByAn/{unid}?OpenDocument",
    )
    assert base_url
    body = f"""
    <html><body>
      <iframe src="/dm/2026/hotarari.nsf/93b6e47af3dd4c36c2257ad3003c531b/{unid}/$FILE/hotarirea 302 - 23 iulie 2026 - test.htm"></iframe>
      <object data="/dm/2026/hotarari.nsf/93b6e47af3dd4c36c2257ad3003c531b/{unid}/$FILE/hotarirea 302 - copie.html"></object>
      <input onclick="window.location='/dm/2026/hotarari.nsf/93b6e47af3dd4c36c2257ad3003c531b/{unid}/$FILE/hotarirea 302 - oficial.htm'" />
      <input value="/dm/2026/hotarari.nsf/93b6e47af3dd4c36c2257ad3003c531b/{other}/$FILE/unrelated.htm" />
      <img src="https://example.test/not-official.htm" />
    </body></html>
    """
    links = embedded_attachment_links(base_url, body)
    urls = [row["url"] for row in links]
    assert len(urls) == 3
    assert all(_document_unid(url) == unid for url in urls)
    assert all("$FILE" in urllib.parse.unquote(url) for url in urls)
    assert not any(other.lower() in url.lower() for url in urls)
    combined = structural_parse_links(base_url, body)
    assert {row["url"] for row in combined}.issuperset(urls)
    print("VÂLCEA CLAR DocManager embedded attachment resolver self-test: PASS")


def main() -> int:
    if "--resolver-self-test" in sys.argv[1:]:
        # Keep the legacy resolver's contract test isolated from this module's
        # parse-link monkeypatch. Only after it passes do we test the broadened
        # extraction surface in the same short-lived process.
        row_resolver.self_test()
        self_test()
        return 0
    install()
    return row_resolver.main()


if __name__ == "__main__":
    raise SystemExit(main())
