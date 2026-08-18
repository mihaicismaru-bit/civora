#!/usr/bin/env python3
"""Resolve embedded official DocManager attachments for Council Fact Kernels.

The municipality's Lotus/DocManager pages can expose their real `$FILE` HTML
attachment through non-anchor attributes (for example iframe/object/input/form
metadata) or as a literal URL inside inert JavaScript source. The base verifier
intentionally follows only canonical official links; this adapter broadens only
that *HTML extraction surface* while preserving the same host, document UNID,
semantic verification and 100% evidence gates.

JavaScript is never executed. Only bounded literal strings are inspected. No
cross-host URL, unrelated Lotus document or non-HTML attachment is admitted.
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
# Romanian official documents use several inflected forms. Keep this exact to
# annual authorizations only: autorizație anuală / autorizația anuală /
# autorizației anuale plus ASCII equivalents. It must not match a generic or
# temporary authorization.
ANNUAL_AUTH_RE_V2 = re.compile(
    r"\b(?:autoriza(?:t|ț)(?:ie|ia|iei)|autorizatie(?:a|i)?)\s+anual(?:a|ă|e)\b",
    re.I,
)
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
RAW_QUOTED_VALUE = re.compile(r"(?P<q>['\"])(?P<target>[^'\"]{1,2000})(?P=q)", re.S)
MAX_RAW_QUOTED_VALUES = 2000
MAX_ATTACHMENT_LINKS = 8


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


def raw_quoted_attachment_links(page_url: str, body: str) -> list[dict[str, str]]:
    """Read inert quoted `$FILE` literals from the raw page without executing JS.

    This catches Lotus pages that construct the viewer target in a script body
    instead of an element attribute. Every literal still has to pass the same
    official-host, Lotus-path, HTML-extension and exact-document-UNID checks.
    """
    text = html.unescape(str(body or ""))
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    inspected = 0
    for match in RAW_QUOTED_VALUE.finditer(text):
        inspected += 1
        if inspected > MAX_RAW_QUOTED_VALUES:
            break
        raw = match.group("target")
        decoded = urllib.parse.unquote(raw)
        if "$file" not in decoded.lower():
            continue
        for candidate in _value_candidates(raw):
            url = _eligible_attachment(page_url, candidate)
            if not url or url in seen:
                continue
            seen.add(url)
            rows.append({"url": url, "text": ""})
            if len(rows) >= MAX_ATTACHMENT_LINKS:
                return rows
    return rows


def embedded_attachment_links(page_url: str, body: str) -> list[dict[str, str]]:
    parser = EmbeddedTargetParser()
    parser.feed(body)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    def admit(url: str | None) -> bool:
        if not url or url in seen:
            return False
        seen.add(url)
        rows.append({"url": url, "text": ""})
        return len(rows) >= MAX_ATTACHMENT_LINKS

    for value in parser.values:
        for candidate in _value_candidates(value):
            if admit(_eligible_attachment(page_url, candidate)):
                return rows

    # Script bodies are deliberately not handled by HTMLParser above. Inspect
    # their literal strings only after normal attributes, never execute code.
    for row in raw_quoted_attachment_links(page_url, body):
        if admit(row["url"]):
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
    # Use the same morphology contract for cluster recognition and for semantic
    # verification of the official child document in this canonical live path.
    row_resolver.base.ANNUAL_AUTH_RE = ANNUAL_AUTH_RE_V2
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
      <script>
        var hiddenViewer = '/dm/2026/hotarari.nsf/93b6e47af3dd4c36c2257ad3003c531b/{unid}/%24FILE/hotarirea%20302%20-%20script.htm';
      </script>
      <input value="/dm/2026/hotarari.nsf/93b6e47af3dd4c36c2257ad3003c531b/{other}/$FILE/unrelated.htm" />
      <script>var wrong = '/dm/2026/hotarari.nsf/93b6e47af3dd4c36c2257ad3003c531b/{other}/$FILE/wrong.htm';</script>
      <img src="https://example.test/not-official.htm" />
    </body></html>
    """
    links = embedded_attachment_links(base_url, body)
    urls = [row["url"] for row in links]
    assert len(urls) == 4
    assert all(_document_unid(url) == unid for url in urls)
    assert all("$FILE" in urllib.parse.unquote(url) for url in urls)
    assert not any(other.lower() in url.lower() for url in urls)
    assert any("script.htm" in urllib.parse.unquote(url) for url in urls)
    combined = structural_parse_links(base_url, body)
    assert {row["url"] for row in combined}.issuperset(urls)

    for phrase in (
        "autorizație anuală",
        "autorizația anuală",
        "autorizației anuale",
        "autorizatie anuala",
        "autorizatia anuala",
        "autorizatiei anuale",
    ):
        assert ANNUAL_AUTH_RE_V2.search(phrase), phrase
    assert not ANNUAL_AUTH_RE_V2.search("autorizație temporară")
    assert not ANNUAL_AUTH_RE_V2.search("autorizația de construire")
    install()
    for phrase in ("autorizația anuală", "autorizației anuale"):
        assert row_resolver.base.ANNUAL_AUTH_RE.search(phrase), phrase
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
