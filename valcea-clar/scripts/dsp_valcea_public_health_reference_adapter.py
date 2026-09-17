#!/usr/bin/env python3
"""Evidence-first DSP Vâlcea public-health reference adapter.

Reads one official DSP Vâlcea public-health index and exposes bounded first-party
references for newsroom review. The adapter is deliberately reference-only: it
never treats a campaign title, recommendation heading, document link or index
presence as proof of a current health alert, disease incidence, risk level,
medical recommendation, service availability or publication-ready fact.
"""
from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
import re
import ssl
import sys
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Optional
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

SOURCE_ID = "signal-dsp-valcea-public-health-references"
TAXONOMY_VERSION = "2026-09-01.1"
SOURCE_NAME = "DSP Vâlcea — promovarea sănătății"
SOURCE_TIER = "T1_OFFICIAL_PUBLIC_HEALTH_AUTHORITY_FIRST_PARTY"
SOURCE_URL = "https://dspvalcea.ro/documente-utile/promovarea-sanatatii.php"
CANONICAL_HOST = "dspvalcea.ro"
ALLOWED_HOSTS = {"dspvalcea.ro", "www.dspvalcea.ro"}
ROOT_PATH = "/documente-utile/promovarea-sanatatii.php"
MAX_RESPONSE_BYTES = 2_500_000
MAX_REFERENCES = 24
TIMEOUT_SECONDS = 15
USER_AGENT = "CIVORA-ValceaClar-DSPValcea/1.0 (+evidence-first; contact via repository)"

IDENTITY_MARKERS = (
    "directia de sanatate publica valcea",
    "dsp valcea",
)
PUBLIC_HEALTH_TITLE_MARKERS = (
    "maternitat",
    "canicula",
    "temperatur",
    "tutun",
    "nicotin",
    "vaccin",
    "campani",
    "sanatat",
    "preven",
    "screening",
    "gripa",
    "rujeol",
    "hepat",
    "igien",
    "aliment",
    "apa potabila",
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
READ_MORE_LABELS = {
    "citeste mai mult",
    "detalii",
    "mai multe detalii",
    "vezi detalii",
}
YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


@dataclass(frozen=True)
class PublicHealthReference:
    kind: str
    canonical_url: str
    title: str
    explicit_year: Optional[int]
    evidence_sha256: str


@dataclass(frozen=True)
class DSPValceaReferenceState:
    source_id: str
    taxonomy_version: str
    source_name: str
    source_tier: str
    source_url: str
    source_payload_sha256: str
    state: str
    hold_reason: Optional[str]
    references: tuple[PublicHealthReference, ...]
    reference_scope: str = "FIRST_PARTY_PUBLIC_HEALTH_REFERENCE_ONLY"
    title_or_index_presence_is_current_health_alert: bool = False
    article_body_fetch_allowed: bool = False
    document_body_fetch_allowed: bool = False
    disease_incidence_extraction_allowed: bool = False
    case_count_extraction_allowed: bool = False
    risk_level_inference_allowed: bool = False
    medical_advice_inference_allowed: bool = False
    service_availability_inference_allowed: bool = False
    campaign_currentness_inference_allowed: bool = False
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


def normalized_path(value: str) -> str:
    path = re.sub(r"/+", "/", unquote(value or "/"))
    if not path.startswith("/"):
        path = "/" + path
    return path


def validate_first_party_url(url: str) -> tuple[str, str]:
    parsed = urlsplit(clean(url))
    host = (parsed.hostname or "").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or host not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.port not in (None, 443)
    ):
        raise ValueError(f"off-surface DSP Vâlcea URL refused: {url}")
    return host, normalized_path(parsed.path)


def validate_source_url(url: str) -> str:
    parsed = urlsplit(clean(url))
    _, path = validate_first_party_url(url)
    if path != ROOT_PATH or parsed.query:
        raise ValueError(f"non-index DSP Vâlcea URL refused: {url}")
    return urlunsplit(("https", CANONICAL_HOST, ROOT_PATH, "", ""))


def normalize_reference_url(value: str, *, base_url: str = SOURCE_URL) -> str:
    joined = urljoin(base_url, clean(value))
    parsed = urlsplit(joined)
    _, path = validate_first_party_url(joined)
    # Query strings on first-party document/content links are preserved only
    # when they do not alter host/path authority. Tracking-only fragments are
    # always stripped. The exact index itself is not emitted as a child ref.
    if path == ROOT_PATH and not parsed.query:
        raise ValueError("source index is not a child reference")
    if path in {"/", "/index.php", "/contact.php"}:
        raise ValueError(f"non-content DSP Vâlcea path refused: {value}")
    return urlunsplit(("https", CANONICAL_HOST, path, parsed.query, ""))


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise ValueError(f"redirect refused: {newurl}")


def fetch_source(url: str = SOURCE_URL) -> tuple[str, str, bytes]:
    canonical = validate_source_url(url)
    opener = build_opener(NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(canonical, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
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


class PublicHealthIndexParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}
    HEADING_TAGS = {"h1", "h2", "h3", "h4"}

    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.skip = 0
        self.heading_tag: Optional[str] = None
        self.heading_parts: list[str] = []
        self.last_heading = ""
        self.href: Optional[str] = None
        self.link_parts: list[str] = []
        self.page_parts: list[str] = []
        self.references: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag in self.HEADING_TAGS:
            self.heading_tag = tag
            self.heading_parts = []
            return
        if tag == "a":
            values = {k.casefold(): v for k, v in attrs if k and v is not None}
            raw_href = clean(values.get("href"))
            try:
                self.href = normalize_reference_url(raw_href, base_url=self.page_url)
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
        if tag == self.heading_tag:
            self.last_heading = clean(" ".join(self.heading_parts))
            self.heading_tag = None
            self.heading_parts = []
            return
        if tag == "a":
            if self.href:
                label = clean(" ".join(self.link_parts))
                title = self.last_heading if fold(label) in READ_MORE_LABELS and self.last_heading else label
                if title:
                    self.references.append((self.href, title))
            self.href = None
            self.link_parts = []

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        text = clean(data)
        if not text:
            return
        self.page_parts.append(text)
        if self.heading_tag:
            self.heading_parts.append(text)
        if self.href:
            self.link_parts.append(text)


def is_public_health_reference_title(title: str) -> bool:
    value = fold(title)
    return any(marker in value for marker in PUBLIC_HEALTH_TITLE_MARKERS)


def classify_reference(title: str) -> str:
    value = fold(title)
    if "maternitat" in value:
        return "MATERNITY_SYSTEM_REFERENCE"
    if "canicula" in value or "temperatur" in value:
        return "HEAT_HEALTH_REFERENCE"
    if "tutun" in value or "nicotin" in value:
        return "TOBACCO_NICOTINE_PREVENTION_REFERENCE"
    if "vaccin" in value:
        return "VACCINATION_REFERENCE"
    if "campani" in value:
        return "PUBLIC_HEALTH_CAMPAIGN_REFERENCE"
    return "PUBLIC_HEALTH_REFERENCE"


def explicit_year(title: str) -> Optional[int]:
    values = {int(value) for value in YEAR_RE.findall(title)}
    if len(values) != 1:
        return None
    return next(iter(values))


def parse_source(page_url: str, html_text: str, body: bytes) -> DSPValceaReferenceState:
    canonical = validate_source_url(page_url)
    payload_sha = hashlib.sha256(body).hexdigest()
    parser = PublicHealthIndexParser(canonical)
    parser.feed(html_text)
    parser.close()
    page_text = fold(" ".join(parser.page_parts))

    if any(term in page_text for term in PLACEHOLDER_TERMS):
        return DSPValceaReferenceState(
            SOURCE_ID, TAXONOMY_VERSION, SOURCE_NAME, SOURCE_TIER, canonical,
            payload_sha, "HOLD_SOURCE_DEGRADED", "placeholder_or_challenge_page", tuple()
        )
    if not any(marker in page_text for marker in IDENTITY_MARKERS):
        return DSPValceaReferenceState(
            SOURCE_ID, TAXONOMY_VERSION, SOURCE_NAME, SOURCE_TIER, canonical,
            payload_sha, "HOLD_SOURCE_IDENTITY_UNVERIFIED", "official_identity_marker_missing", tuple()
        )

    dedup: dict[str, PublicHealthReference] = {}
    for url, title in parser.references:
        normalized_title = clean(title)
        if not normalized_title or not is_public_health_reference_title(normalized_title):
            continue
        key = f"{url}\n{normalized_title.casefold()}"
        if key in dedup:
            continue
        evidence_sha = hashlib.sha256(f"{payload_sha}\n{url}\n{normalized_title}".encode("utf-8")).hexdigest()
        dedup[key] = PublicHealthReference(
            kind=classify_reference(normalized_title),
            canonical_url=url,
            title=normalized_title,
            explicit_year=explicit_year(normalized_title),
            evidence_sha256=evidence_sha,
        )
        if len(dedup) >= MAX_REFERENCES:
            break

    references = tuple(dedup.values())
    if not references:
        return DSPValceaReferenceState(
            SOURCE_ID, TAXONOMY_VERSION, SOURCE_NAME, SOURCE_TIER, canonical,
            payload_sha, "HOLD_NO_BOUNDED_REFERENCES", "no_first_party_public_health_references", tuple()
        )
    return DSPValceaReferenceState(
        SOURCE_ID, TAXONOMY_VERSION, SOURCE_NAME, SOURCE_TIER, canonical,
        payload_sha, "REFERENCE_READY_NON_AUTHORIZING", None, references
    )


def _capability_values(state: DSPValceaReferenceState) -> list[bool]:
    return [
        state.title_or_index_presence_is_current_health_alert,
        state.article_body_fetch_allowed,
        state.document_body_fetch_allowed,
        state.disease_incidence_extraction_allowed,
        state.case_count_extraction_allowed,
        state.risk_level_inference_allowed,
        state.medical_advice_inference_allowed,
        state.service_availability_inference_allowed,
        state.campaign_currentness_inference_allowed,
        state.image_ingest_allowed,
        state.inferred_photo_rights_allowed,
        state.breaking_news_promotion_allowed,
        state.persistence_allowed,
        state.fact_kernel_promotion_allowed,
        state.writer_allowed,
        state.public_projection_allowed,
    ]


def self_test() -> int:
    html_ok = """
    <html><body>
      <header>Direcția de Sănătate Publică Vâlcea</header>
      <h2>Niveluri de ierarhizare ale maternităților din județul Vâlcea - 2026</h2>
      <a href="/files/maternitati-2026.pdf">Niveluri de ierarhizare ale maternităților din județul Vâlcea - 2026</a>
      <h2>Recomandări în caz de caniculă</h2>
      <a href="/documente-utile/canicula.php">Citește mai mult</a>
      <h2>Campania națională de prevenire a consumului de tutun și a produselor cu nicotină - 2026</h2>
      <a href="https://dspvalcea.ro/documente-utile/tutun-2026.php">Citește mai mult</a>
      <a href="https://example.com/offsite">Citește mai mult</a>
    </body></html>
    """
    body = html_ok.encode("utf-8")
    state = parse_source(SOURCE_URL, html_ok, body)
    assert state.state == "REFERENCE_READY_NON_AUTHORIZING", state
    assert len(state.references) == 3, state.references
    kinds = {ref.kind for ref in state.references}
    assert "MATERNITY_SYSTEM_REFERENCE" in kinds, kinds
    assert "HEAT_HEALTH_REFERENCE" in kinds, kinds
    assert "TOBACCO_NICOTINE_PREVENTION_REFERENCE" in kinds, kinds
    maternity = next(ref for ref in state.references if ref.kind == "MATERNITY_SYSTEM_REFERENCE")
    assert maternity.explicit_year == 2026, maternity
    assert all(ref.canonical_url.startswith("https://dspvalcea.ro/") for ref in state.references)
    assert not any(_capability_values(state)), state
    assert state.publication_authority == "NONE"

    placeholder = "<html><body>Direcția de Sănătate Publică Vâlcea verify you are human</body></html>"
    degraded = parse_source(SOURCE_URL, placeholder, placeholder.encode())
    assert degraded.state == "HOLD_SOURCE_DEGRADED", degraded
    assert not degraded.references

    wrong_identity = "<html><body><h2>Recomandări în caz de caniculă</h2><a href='/x'>detalii</a></body></html>"
    held = parse_source(SOURCE_URL, wrong_identity, wrong_identity.encode())
    assert held.state == "HOLD_SOURCE_IDENTITY_UNVERIFIED", held

    try:
        validate_source_url("https://example.com/documente-utile/promovarea-sanatatii.php")
    except ValueError:
        pass
    else:
        raise AssertionError("off-site source must fail closed")

    try:
        normalize_reference_url("http://dspvalcea.ro/documente-utile/x.php")
    except ValueError:
        pass
    else:
        raise AssertionError("non-HTTPS child reference must fail closed")

    print(json.dumps({"source_id": SOURCE_ID, "self_test": "PASS", "cases": 5}, ensure_ascii=False))
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only DSP Vâlcea public-health reference adapter")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--source-url", default=SOURCE_URL)
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()
    try:
        final_url, html_text, body = fetch_source(args.source_url)
        state = parse_source(final_url, html_text, body)
    except Exception as exc:
        state = DSPValceaReferenceState(
            SOURCE_ID,
            TAXONOMY_VERSION,
            SOURCE_NAME,
            SOURCE_TIER,
            validate_source_url(args.source_url),
            "",
            "HOLD_SOURCE_FETCH_FAILED",
            f"{type(exc).__name__}: {clean(exc)}",
            tuple(),
        )
    print(json.dumps(asdict(state), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if state.state == "REFERENCE_READY_NON_AUTHORIZING" else 2


if __name__ == "__main__":
    sys.exit(main())
