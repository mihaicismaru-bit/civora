#!/usr/bin/env python3
"""Evidence-first ITM Vâlcea public-information surface adapter.

The adapter reads only the official Inspectoratul Teritorial de Muncă Vâlcea
homepage and exposes a bounded set of first-party public-information surfaces
linked there. It does not crawl those surfaces or document bodies.

A linked source surface is reference intelligence only. It does not prove that
an announcement, campaign, statistic, legal obligation, enforcement action, or
workplace-safety condition is current. The adapter does not extract people,
personal data, sanctions, employer claims, images, or inferred photo rights;
does not persist state; does not promote to Fact Kernel; does not invoke Writer;
and does not publish.
"""
from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
import re
import ssl
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Optional
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

SOURCE_ID = "signal-itm-valcea-public-information-references"
TAXONOMY_VERSION = "2026-08-31.1"
SOURCE_NAME = "Inspectoratul Teritorial de Muncă Vâlcea — informații publice"
SOURCE_TIER = "T1_OFFICIAL_LABOUR_INSPECTION_FIRST_PARTY"
SOURCE_URL = "https://www.inspectiamuncii.ro/web/itm-valcea"
CANONICAL_HOST = "www.inspectiamuncii.ro"
ALLOWED_HOSTS = {"inspectiamuncii.ro", "www.inspectiamuncii.ro"}
ROOT_PATH = "/web/itm-valcea"
MAX_RESPONSE_BYTES = 2_500_000
TIMEOUT_SECONDS = 15
USER_AGENT = "CIVORA-ValceaClar-ITMValcea/1.0 (+evidence-first; contact via repository)"

SURFACES = {
    "/web/itm-valcea/anunturi": "ANNOUNCEMENT_INDEX_REFERENCE",
    "/web/itm-valcea/raport-anual-suport-de-studiu-si-cercetare": "ANNUAL_ACTIVITY_REPORT_INDEX_REFERENCE",
    "/web/itm-valcea/rapoarte-semestriale": "PERIODIC_REPORT_INDEX_REFERENCE",
    "/web/itm-valcea/statistici": "STATISTICS_INDEX_REFERENCE",
    "/web/itm-valcea/informatii-de-interes-public": "PUBLIC_INFORMATION_INDEX_REFERENCE",
    "/web/itm-valcea/formulare": "FORMS_INDEX_REFERENCE",
    "/web/itm-valcea/presa": "PRESS_INDEX_REFERENCE",
    "/web/itm-valcea/relatii-cu-publicul": "PUBLIC_RELATIONS_INDEX_REFERENCE",
}

IDENTITY_MARKERS = (
    "inspectoratul teritorial de munca valcea",
    "itm valcea",
    "itm - valcea",
)
PLACEHOLDER_TERMS = (
    "access denied",
    "captcha",
    "checking your browser",
    "enable javascript",
    "service unavailable",
    "temporarily unavailable",
    "verify you are human",
)


@dataclass(frozen=True)
class SurfaceReference:
    kind: str
    canonical_url: str
    link_text: str
    evidence_sha256: str


@dataclass(frozen=True)
class ITMValceaReferenceState:
    source_id: str
    taxonomy_version: str
    source_name: str
    source_tier: str
    source_url: str
    source_payload_sha256: str
    state: str
    hold_reason: Optional[str]
    references: tuple[SurfaceReference, ...]
    reference_scope: str = "FIRST_PARTY_PUBLIC_INFORMATION_SURFACE_REFERENCE_ONLY"
    subpage_fetch_allowed: bool = False
    document_body_fetch_allowed: bool = False
    person_or_personal_data_extraction_allowed: bool = False
    employer_or_sanction_claim_extraction_allowed: bool = False
    legal_obligation_currentness_inference_allowed: bool = False
    enforcement_currentness_inference_allowed: bool = False
    workplace_safety_currentness_inference_allowed: bool = False
    image_ingest_allowed: bool = False
    inferred_photo_rights_allowed: bool = False
    breaking_news_promotion_allowed: bool = False
    persistence_allowed: bool = False
    fact_kernel_promotion_allowed: bool = False
    writer_allowed: bool = False
    public_projection_allowed: bool = False
    publication_authority: str = "NONE"


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", clean(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _normalized_path(value: str) -> str:
    path = re.sub(r"/+", "/", unquote(value or "/"))
    if not path.startswith("/"):
        path = "/" + path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path


def _validate_first_party_url(url: str) -> tuple[str, str]:
    parsed = urlsplit(clean(url))
    host = (parsed.hostname or "").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or host not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.port not in (None, 443)
    ):
        raise ValueError(f"off-surface ITM Vâlcea URL refused: {url}")
    return host, _normalized_path(parsed.path)


def validate_source_url(url: str) -> str:
    _, path = _validate_first_party_url(url)
    if path != ROOT_PATH:
        raise ValueError(f"non-home ITM Vâlcea URL refused: {url}")
    return urlunsplit(("https", CANONICAL_HOST, ROOT_PATH, "", ""))


def normalize_surface_url(value: str, *, base_url: str = SOURCE_URL) -> str:
    joined = urljoin(base_url, clean(value))
    _, path = _validate_first_party_url(joined)
    if path not in SURFACES:
        raise ValueError(f"unapproved ITM Vâlcea surface refused: {value}")
    return urlunsplit(("https", CANONICAL_HOST, path, "", ""))


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise ValueError(f"redirect refused: {newurl}")


def fetch_source(url: str = SOURCE_URL) -> tuple[str, str, bytes]:
    canonical = validate_source_url(url)
    opener = build_opener(NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(
        canonical,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"},
    )
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        final_url = validate_source_url(response.geturl())
        if final_url != canonical:
            raise ValueError("canonical URL drift after fetch")
        content_type = clean(response.headers.get("Content-Type", "")).casefold()
        if "text/html" not in content_type:
            raise ValueError(f"non-HTML source refused: {content_type or 'unknown'}")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds size cap")
        charset = response.headers.get_content_charset() or "utf-8"
    return final_url, body.decode(charset, errors="replace"), body


class SurfaceParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.skip = 0
        self.page_parts: list[str] = []
        self.href: Optional[str] = None
        self.link_parts: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "a":
            values = {k.casefold(): v for k, v in attrs if k and v is not None}
            raw_href = clean(values.get("href"))
            try:
                self.href = normalize_surface_url(raw_href, base_url=self.page_url)
            except (TypeError, ValueError):
                self.href = None
            self.link_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            if self.skip:
                self.skip -= 1
            return
        if self.skip:
            return
        if tag == "a":
            if self.href:
                self.links.append((self.href, clean(" ".join(self.link_parts))))
            self.href = None
            self.link_parts = []

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        text = clean(data)
        if not text:
            return
        self.page_parts.append(text)
        if self.href:
            self.link_parts.append(text)


def build_state(html_text: str, *, source_url: str = SOURCE_URL, raw_bytes: Optional[bytes] = None) -> ITMValceaReferenceState:
    canonical_source = validate_source_url(source_url)
    payload = raw_bytes if raw_bytes is not None else html_text.encode("utf-8")
    payload_sha = hashlib.sha256(payload).hexdigest()
    parser = SurfaceParser(canonical_source)
    parser.feed(html_text)
    page_text = fold(" ".join(parser.page_parts))

    if any(term in page_text for term in PLACEHOLDER_TERMS):
        return ITMValceaReferenceState(
            SOURCE_ID, TAXONOMY_VERSION, SOURCE_NAME, SOURCE_TIER, canonical_source,
            payload_sha, "HOLD", "PLACEHOLDER_OR_ACCESS_CHALLENGE", (),
        )
    if not any(marker in page_text for marker in IDENTITY_MARKERS):
        return ITMValceaReferenceState(
            SOURCE_ID, TAXONOMY_VERSION, SOURCE_NAME, SOURCE_TIER, canonical_source,
            payload_sha, "HOLD", "SOURCE_IDENTITY_NOT_CONFIRMED", (),
        )

    by_url: dict[str, set[str]] = {}
    for url, text in parser.links:
        by_url.setdefault(url, set()).add(clean(text))

    references: list[SurfaceReference] = []
    for url in sorted(by_url):
        path = _normalized_path(urlsplit(url).path)
        texts = sorted(t for t in by_url[url] if t)
        link_text = texts[0] if texts else ""
        evidence = f"{SURFACES[path]}|{url}|{link_text}".encode("utf-8")
        references.append(
            SurfaceReference(
                kind=SURFACES[path],
                canonical_url=url,
                link_text=link_text,
                evidence_sha256=hashlib.sha256(evidence).hexdigest(),
            )
        )

    if not references:
        return ITMValceaReferenceState(
            SOURCE_ID, TAXONOMY_VERSION, SOURCE_NAME, SOURCE_TIER, canonical_source,
            payload_sha, "HOLD", "NO_APPROVED_SOURCE_SURFACES_DISCOVERED", (),
        )

    return ITMValceaReferenceState(
        SOURCE_ID, TAXONOMY_VERSION, SOURCE_NAME, SOURCE_TIER, canonical_source,
        payload_sha, "REFERENCE_ONLY", None, tuple(references),
    )


def run_self_test() -> None:
    fixture = """
    <html><head><title>ITM - Vâlcea</title></head><body>
      <h1>Inspectoratul Teritorial de Muncă Vâlcea</h1>
      <a href="/web/itm-valcea/anunturi">Anunțuri</a>
      <a href="https://inspectiamuncii.ro/web/itm-valcea/statistici">Statistici</a>
      <a href="/web/itm-valcea/formulare">Formulare</a>
      <a href="/web/itm-valcea/anunturi">Anunțuri duplicate</a>
      <a href="https://example.com/web/itm-valcea/presa">extern</a>
      <a href="/web/itm-cluj/anunturi">alt județ</a>
      <a href="/web/itm-valcea/necunoscut">necunoscut</a>
    </body></html>
    """
    state = build_state(fixture)
    assert state.state == "REFERENCE_ONLY"
    assert state.hold_reason is None
    assert [r.kind for r in state.references] == [
        "ANNOUNCEMENT_INDEX_REFERENCE",
        "FORMS_INDEX_REFERENCE",
        "STATISTICS_INDEX_REFERENCE",
    ]
    assert len(state.references) == 3
    assert all(r.canonical_url.startswith("https://www.inspectiamuncii.ro/web/itm-valcea/") for r in state.references)
    assert state.publication_authority == "NONE"
    assert not state.subpage_fetch_allowed
    assert not state.document_body_fetch_allowed
    assert not state.fact_kernel_promotion_allowed
    assert not state.public_projection_allowed

    deterministic = build_state(fixture)
    assert asdict(state) == asdict(deterministic)

    missing_identity = build_state('<html><body><a href="/web/itm-valcea/anunturi">Anunțuri</a></body></html>')
    assert missing_identity.state == "HOLD"
    assert missing_identity.hold_reason == "SOURCE_IDENTITY_NOT_CONFIRMED"

    empty = build_state('<html><body><h1>Inspectoratul Teritorial de Muncă Vâlcea</h1></body></html>')
    assert empty.state == "HOLD"
    assert empty.hold_reason == "NO_APPROVED_SOURCE_SURFACES_DISCOVERED"

    challenged = build_state('<html><body><h1>ITM Vâlcea</h1><p>Verify you are human</p></body></html>')
    assert challenged.state == "HOLD"
    assert challenged.hold_reason == "PLACEHOLDER_OR_ACCESS_CHALLENGE"

    assert normalize_surface_url("https://inspectiamuncii.ro/web/itm-valcea/presa") == "https://www.inspectiamuncii.ro/web/itm-valcea/presa"
    for refused in (
        "http://www.inspectiamuncii.ro/web/itm-valcea/anunturi",
        "https://dspvalcea.ro/web/itm-valcea/anunturi",
        "https://www.inspectiamuncii.ro/web/itm-cluj/anunturi",
        "https://www.inspectiamuncii.ro/web/itm-valcea/anunturi?x=1",
    ):
        try:
            normalize_surface_url(refused)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected refusal for {refused}")

    print("ITM Vâlcea public-information reference adapter self-test: OK")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url", default=SOURCE_URL)
    parser.add_argument("--input", help="Read HTML from a local file instead of the network")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        return 0

    if args.input:
        with open(args.input, "rb") as handle:
            body = handle.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("input exceeds size cap")
        html_text = body.decode("utf-8", errors="replace")
        state = build_state(html_text, source_url=args.source_url, raw_bytes=body)
    else:
        final_url, html_text, body = fetch_source(args.source_url)
        state = build_state(html_text, source_url=final_url, raw_bytes=body)

    print(json.dumps(asdict(state), ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if state.state == "REFERENCE_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
