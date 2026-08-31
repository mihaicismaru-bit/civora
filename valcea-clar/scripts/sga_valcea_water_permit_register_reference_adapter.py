#!/usr/bin/env python3
"""Evidence-first SGA Vâlcea water permit-register reference adapter.

Reads only the official ABA Olt SGA Vâlcea index that lists yearly references
to issued water-management permits/authorisations. The current-year entry is
kept as a reference-presence signal only. External targets are never fetched
or exposed as evidence of an individual permit, holder, project, location,
validity or current regulatory status.
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
from datetime import date
from typing import Any, Optional
from urllib.parse import unquote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

SOURCE_ID = "signal-sga-valcea-water-permit-register-reference"
TAXONOMY_VERSION = "2026-08-31.1"
SOURCE_NAME = "Sistemul de Gospodărire a Apelor Vâlcea / Administrația Bazinală de Apă Olt"
SOURCE_TIER = "T1_OFFICIAL_WATER_AUTHORITY_FIRST_PARTY"
SOURCE_URL = (
    "https://olt.rowater.ro/activitatea-institutiei/structuri/"
    "managementul-european-integrat-resurse-de-apa/avize-si-autorizatii/"
    "lista-avizelor-si-autorizatiilor-de-gospodarire-a-apelor-emise/sga-valcea/"
)
CANONICAL_HOST = "olt.rowater.ro"
ROOT_PATH = (
    "/activitatea-institutiei/structuri/managementul-european-integrat-resurse-de-apa/"
    "avize-si-autorizatii/lista-avizelor-si-autorizatiilor-de-gospodarire-a-apelor-emise/"
    "sga-valcea/"
)
MAX_RESPONSE_BYTES = 2_500_000
TIMEOUT_SECONDS = 15
USER_AGENT = "CIVORA-ValceaClar-SGAValcea/1.0 (+evidence-first; contact via repository)"

IDENTITY_MARKERS = (
    "sga valcea",
    "sistemul de gospodarire a apelor valcea",
)
REGISTER_LABEL_MARKERS = (
    "avize-autorizatii sga valcea",
    "avize autorizatii sga valcea",
)
PLACEHOLDER_TERMS = (
    "access denied",
    "captcha",
    "checking your browser",
    "cloudflare",
    "enable javascript",
    "please wait",
    "service unavailable",
    "temporarily unavailable",
    "verify you are human",
)
YEAR_RE = re.compile(r"^20\d{2}$")


@dataclass(frozen=True)
class WaterPermitRegisterReference:
    kind: str
    year: int
    title: str
    canonical_index_url: str
    target_scope: str
    external_target_present: bool
    evidence_sha256: str


@dataclass(frozen=True)
class SGAValceaWaterPermitRegisterState:
    source_id: str
    taxonomy_version: str
    source_name: str
    source_tier: str
    source_url: str
    source_payload_sha256: str
    as_of_date: str
    state: str
    hold_reason: Optional[str]
    references: tuple[WaterPermitRegisterReference, ...]
    reference_scope: str = "FIRST_PARTY_REGISTER_PRESENCE_REFERENCE_ONLY"
    external_target_fetch_allowed: bool = False
    external_target_url_projection_allowed: bool = False
    document_body_fetch_allowed: bool = False
    individual_permit_extraction_allowed: bool = False
    permit_holder_or_person_extraction_allowed: bool = False
    project_or_location_extraction_allowed: bool = False
    current_validity_inference_allowed: bool = False
    current_regulatory_status_inference_allowed: bool = False
    breaking_news_promotion_allowed: bool = False
    image_ingest_allowed: bool = False
    inferred_photo_rights_allowed: bool = False
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
    if not path.endswith("/"):
        path += "/"
    return path


def validate_source_url(url: str) -> str:
    parsed = urlsplit(clean(url))
    host = (parsed.hostname or "").casefold()
    path = normalized_path(parsed.path)
    if (
        parsed.scheme.casefold() != "https"
        or host != CANONICAL_HOST
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or path != ROOT_PATH
    ):
        raise ValueError(f"off-surface SGA Vâlcea source refused: {url}")
    return urlunsplit(("https", CANONICAL_HOST, ROOT_PATH, "", ""))


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
            raise ValueError("canonical source drift after fetch")
        content_type = clean(response.headers.get("Content-Type", "")).casefold()
        if "text/html" not in content_type:
            raise ValueError(f"non-HTML SGA source refused: {content_type or 'unknown'}")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds size cap")
        charset = response.headers.get_content_charset() or "utf-8"
    return final_url, body.decode(charset, errors="replace"), body


class RegisterIndexParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.capture_tag: Optional[str] = None
        self.capture_parts: list[str] = []
        self.anchor_href: Optional[str] = None
        self.anchor_parts: list[str] = []
        self.current_year: Optional[int] = None
        self.seen_sga_heading = False
        self.visible_parts: list[str] = []
        self.entries: list[tuple[int, str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag in {"h1", "h2", "h3", "h4"}:
            self.capture_tag = tag
            self.capture_parts = []
        if tag == "a" and self.seen_sga_heading and self.current_year is not None:
            values = {str(k).casefold(): v for k, v in attrs if k}
            self.anchor_href = clean(values.get("href"))
            self.anchor_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            if self.skip:
                self.skip -= 1
            return
        if self.skip:
            return
        if tag == "a" and self.anchor_href is not None:
            label = clean(" ".join(self.anchor_parts))
            if label:
                self.entries.append((self.current_year or 0, label, self.anchor_href))
            self.anchor_href = None
            self.anchor_parts = []
        if tag == self.capture_tag:
            value = clean(" ".join(self.capture_parts))
            folded = fold(value)
            if tag in {"h1", "h2", "h3"} and any(marker in folded for marker in IDENTITY_MARKERS):
                self.seen_sga_heading = True
                self.current_year = None
            elif self.seen_sga_heading and tag == "h4" and YEAR_RE.fullmatch(value):
                self.current_year = int(value)
            self.capture_tag = None
            self.capture_parts = []

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        value = clean(data)
        if not value:
            return
        self.visible_parts.append(value)
        if self.capture_tag is not None:
            self.capture_parts.append(value)
        if self.anchor_href is not None:
            self.anchor_parts.append(value)

    def visible_text(self) -> str:
        return clean(" ".join(self.visible_parts))


def _target_scope(href: str) -> tuple[str, bool]:
    parsed = urlsplit(clean(href))
    host = (parsed.hostname or "").casefold()
    if parsed.scheme.casefold() == "https" and host == CANONICAL_HOST:
        return "FIRST_PARTY_UNFOLLOWED", True
    if parsed.scheme.casefold() == "https" and host:
        return "EXTERNAL_UNFOLLOWED", True
    return "UNTRUSTED_TARGET_UNFOLLOWED", bool(clean(href))


def build_state(html_text: str, payload: bytes, *, as_of: date, source_url: str = SOURCE_URL) -> SGAValceaWaterPermitRegisterState:
    canonical = validate_source_url(source_url)
    digest = hashlib.sha256(payload).hexdigest()
    parser = RegisterIndexParser()
    try:
        parser.feed(html_text)
    except Exception as exc:
        return _hold(canonical, digest, as_of, f"html_parse_error:{type(exc).__name__}")

    visible = parser.visible_text()
    folded_visible = fold(visible)
    if any(term in folded_visible[:8000] for term in PLACEHOLDER_TERMS):
        return _hold(canonical, digest, as_of, "placeholder_or_challenge_page")
    if not parser.seen_sga_heading:
        return _hold(canonical, digest, as_of, "sga_valcea_identity_missing")

    current_year = as_of.year
    matches: list[tuple[str, str]] = []
    for year, label, href in parser.entries:
        if year != current_year:
            continue
        folded_label = fold(label)
        if any(marker in folded_label for marker in REGISTER_LABEL_MARKERS):
            matches.append((label, href))

    if not matches:
        return _hold(canonical, digest, as_of, f"current_year_register_reference_missing:{current_year}")
    unique = {(clean(label), clean(href)) for label, href in matches}
    if len(unique) != 1:
        return _hold(canonical, digest, as_of, f"ambiguous_current_year_register_reference:{len(unique)}")

    label, href = next(iter(unique))
    scope, target_present = _target_scope(href)
    evidence = f"{current_year}|{clean(label)}|{scope}|target_present={str(target_present).lower()}"
    reference = WaterPermitRegisterReference(
        kind="WATER_PERMIT_REGISTER_REFERENCE",
        year=current_year,
        title=clean(label),
        canonical_index_url=canonical,
        target_scope=scope,
        external_target_present=target_present,
        evidence_sha256=hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
    )
    return SGAValceaWaterPermitRegisterState(
        source_id=SOURCE_ID,
        taxonomy_version=TAXONOMY_VERSION,
        source_name=SOURCE_NAME,
        source_tier=SOURCE_TIER,
        source_url=canonical,
        source_payload_sha256=digest,
        as_of_date=as_of.isoformat(),
        state="REFERENCE_READY",
        hold_reason=None,
        references=(reference,),
    )


def _hold(source_url: str, digest: str, as_of: date, reason: str) -> SGAValceaWaterPermitRegisterState:
    return SGAValceaWaterPermitRegisterState(
        source_id=SOURCE_ID,
        taxonomy_version=TAXONOMY_VERSION,
        source_name=SOURCE_NAME,
        source_tier=SOURCE_TIER,
        source_url=source_url,
        source_payload_sha256=digest,
        as_of_date=as_of.isoformat(),
        state="HOLD",
        hold_reason=reason,
        references=(),
    )


def run_live(*, as_of: date, source_url: str = SOURCE_URL) -> SGAValceaWaterPermitRegisterState:
    canonical = validate_source_url(source_url)
    try:
        _, text, payload = fetch_source(canonical)
    except Exception as exc:
        return _hold(canonical, hashlib.sha256(b"").hexdigest(), as_of, f"fetch_error:{type(exc).__name__}")
    return build_state(text, payload, as_of=as_of, source_url=canonical)


def _synthetic(year: int, *, heading: str = "SGA VÂLCEA", label: str = "AVIZE-AUTORIZAȚII SGA VÂLCEA", href: str = "https://s.go.ro/example") -> str:
    return f"""<!doctype html><html><body><main><h1>{heading}</h1><h4>{year}</h4><ul><li><a href=\"{href}\">{label}</a></li></ul></main></body></html>"""


def self_test() -> None:
    as_of = date(2026, 8, 31)
    html = _synthetic(2026)
    state = build_state(html, html.encode(), as_of=as_of)
    assert state.state == "REFERENCE_READY", state
    assert len(state.references) == 1
    ref = state.references[0]
    assert ref.kind == "WATER_PERMIT_REGISTER_REFERENCE"
    assert ref.year == 2026
    assert ref.target_scope == "EXTERNAL_UNFOLLOWED"
    assert ref.external_target_present is True
    assert not hasattr(ref, "target_url")
    assert state.external_target_fetch_allowed is False
    assert state.document_body_fetch_allowed is False
    assert state.individual_permit_extraction_allowed is False
    assert state.current_validity_inference_allowed is False
    assert state.public_projection_allowed is False

    old = _synthetic(2025)
    assert build_state(old, old.encode(), as_of=as_of).hold_reason == "current_year_register_reference_missing:2026"

    missing_identity = _synthetic(2026, heading="ABA Olt")
    assert build_state(missing_identity, missing_identity.encode(), as_of=as_of).hold_reason == "sga_valcea_identity_missing"

    wrong_label = _synthetic(2026, label="Anunț general")
    assert build_state(wrong_label, wrong_label.encode(), as_of=as_of).hold_reason == "current_year_register_reference_missing:2026"

    duplicate = html.replace("</ul>", '<li><a href="https://s.go.ro/other">AVIZE-AUTORIZAȚII SGA VÂLCEA</a></li></ul>')
    assert build_state(duplicate, duplicate.encode(), as_of=as_of).hold_reason == "ambiguous_current_year_register_reference:2"

    challenge = "<html><body><h1>SGA VÂLCEA</h1><p>Please wait. Checking your browser.</p></body></html>"
    assert build_state(challenge, challenge.encode(), as_of=as_of).hold_reason == "placeholder_or_challenge_page"

    first_party = _synthetic(2026, href=SOURCE_URL)
    assert build_state(first_party, first_party.encode(), as_of=as_of).references[0].target_scope == "FIRST_PARTY_UNFOLLOWED"

    untrusted = _synthetic(2026, href="javascript:alert(1)")
    uref = build_state(untrusted, untrusted.encode(), as_of=as_of).references[0]
    assert uref.target_scope == "UNTRUSTED_TARGET_UNFOLLOWED"
    assert uref.external_target_present is True

    for bad in (
        "http://olt.rowater.ro" + ROOT_PATH,
        "https://evil.example" + ROOT_PATH,
        SOURCE_URL + "?x=1",
        SOURCE_URL + "#frag",
        "https://olt.rowater.ro/sga-valcea/",
    ):
        try:
            validate_source_url(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"off-surface source accepted: {bad}")

    print("sga_valcea_water_permit_register_reference_adapter self-test: OK")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-url", default=SOURCE_URL)
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0
    try:
        as_of = date.fromisoformat(args.as_of)
    except ValueError as exc:
        raise SystemExit(f"invalid --as-of date: {args.as_of}") from exc
    state = run_live(as_of=as_of, source_url=args.source_url)
    print(json.dumps(asdict(state), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
