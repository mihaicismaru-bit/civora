from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Iterable
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from clar_core.contracts import SourceItem


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
        elif tag in {"p", "br", "li", "h1", "h2", "h3"} and not self._skip:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        elif tag in {"p", "li"} and not self._skip:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        value = html.unescape("".join(self.parts))
        lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
        return "\n".join(line for line in lines if line)


def html_to_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value or "")
    return parser.text()


def _fetch(url: str, timeout: int = 20) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": "CLAR-Core/1.0 (+local-news-public-interest; contact=editorial)",
            "Accept": "application/rss+xml, application/xml, text/xml, text/html;q=0.9, */*;q=0.8",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _published(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError, OverflowError):
        return None


class WordPressFeedDiscoverer:
    """Discover SourceItems from a WordPress/RSS feed.

    The adapter is site-agnostic. Site identity, feed URL, and limits are
    provided by instance configuration. It prefers full ``content:encoded``
    text and falls back to the RSS description.
    """

    def __init__(self, *, source_id: str, feed_url: str, max_items: int = 12) -> None:
        self.source_id = source_id
        self.feed_url = feed_url
        self.max_items = max_items

    def __call__(self) -> Iterable[SourceItem]:
        payload = _fetch(self.feed_url)
        root = ET.fromstring(payload)
        now = datetime.now(timezone.utc)
        items = root.findall("./channel/item")[: self.max_items]
        for node in items:
            title = (node.findtext("title") or "").strip()
            link = (node.findtext("link") or "").strip()
            if not title or not link:
                continue
            encoded = node.findtext("{http://purl.org/rss/1.0/modules/content/}encoded")
            description = node.findtext("description") or ""
            body = html_to_text(encoded or description)
            yield SourceItem(
                source_id=self.source_id,
                canonical_url=link,
                title=html.unescape(title),
                discovered_at=now,
                published_at=_published(node.findtext("pubDate")),
                body_text=body or None,
                source_type="official",
                metadata={"feed_url": self.feed_url, "adapter": "wordpress_rss"},
            )
