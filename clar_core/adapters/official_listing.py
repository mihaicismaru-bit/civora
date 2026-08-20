from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from clar_core.contracts import SourceItem
from clar_core.adapters.wordpress_feed import html_to_text


_MONTHS = {
    "ianuarie": 1,
    "februarie": 2,
    "martie": 3,
    "aprilie": 4,
    "mai": 5,
    "iunie": 6,
    "iulie": 7,
    "august": 8,
    "septembrie": 9,
    "octombrie": 10,
    "noiembrie": 11,
    "decembrie": 12,
}
_DATE_RE = re.compile(
    r"\b([0-3]?\d)\s+(ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)\s+(20\d{2})\b",
    re.IGNORECASE,
)


def _fetch(url: str, timeout: int = 20) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "CLAR-Core/1.0 (+local-news-public-interest; contact=editorial)",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _published_from_text(text: str) -> datetime | None:
    match = _DATE_RE.search(text or "")
    if not match:
        return None
    day = int(match.group(1))
    month = _MONTHS.get(match.group(2).casefold())
    year = int(match.group(3))
    if not month:
        return None
    try:
        return datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None


class _ListingParser(HTMLParser):
    def __init__(self, *, base_url: str, link_prefixes: Iterable[str]) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.link_prefixes = tuple(link_prefixes)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag != "a":
            return
        values = {str(k): str(v or "") for k, v in attrs}
        href = values.get("href", "").strip()
        if not href:
            return
        absolute = urljoin(self.base_url, href)
        path = urlparse(absolute).path
        if self.link_prefixes and not any(path.startswith(prefix) for prefix in self.link_prefixes):
            return
        self._href = absolute
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._href is None:
            return
        title = re.sub(r"\s+", " ", " ".join(self._parts)).strip()
        if title:
            self.links.append((self._href, title))
        self._href = None
        self._parts = []


class OfficialListingDiscoverer:
    """Discover official HTML articles from a configurable listing page.

    The adapter carries no locality or institution-specific knowledge. The
    instance supplies the listing URL and accepted article path prefixes.
    Article text is fetched from the canonical URL and publication dates are
    parsed from Romanian long-form dates when present.
    """

    def __init__(
        self,
        *,
        source_id: str,
        listing_url: str,
        link_prefixes: Iterable[str],
        max_items: int = 10,
        max_age_hours: int | None = None,
    ) -> None:
        self.source_id = source_id
        self.listing_url = listing_url
        self.link_prefixes = tuple(link_prefixes)
        self.max_items = max_items
        self.max_age_hours = max_age_hours

    def __call__(self) -> Iterable[SourceItem]:
        listing_html = _fetch(self.listing_url)
        parser = _ListingParser(base_url=self.listing_url, link_prefixes=self.link_prefixes)
        parser.feed(listing_html)
        now = datetime.now(timezone.utc)
        emitted = 0
        seen_urls: set[str] = set()

        for canonical_url, title in parser.links:
            if canonical_url in seen_urls:
                continue
            seen_urls.add(canonical_url)
            try:
                article_html = _fetch(canonical_url)
            except Exception:
                continue
            body = html_to_text(article_html)
            published_at = _published_from_text(body)
            if self.max_age_hours is not None and published_at is not None:
                if now - published_at > timedelta(hours=self.max_age_hours):
                    continue
            yield SourceItem(
                source_id=self.source_id,
                canonical_url=canonical_url,
                title=title,
                discovered_at=now,
                published_at=published_at,
                body_text=body or None,
                source_type="official",
                metadata={
                    "listing_url": self.listing_url,
                    "adapter": "official_html_listing",
                },
            )
            emitted += 1
            if emitted >= self.max_items:
                break
