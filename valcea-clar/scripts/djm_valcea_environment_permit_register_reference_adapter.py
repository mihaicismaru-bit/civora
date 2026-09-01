#!/usr/bin/env python3
"""Evidence-first DJM Vâlcea environmental permit-register reference adapter.

Reads only the official Direcția Județeană de Mediu Vâlcea homepage and admits
only the explicit first-party reference to the environmental / integrated
environmental authorisation centralizer labelled as covering 01.08.2025 to
"prezent".

This adapter intentionally keeps the result at reference level. It never
fetches the register body and never turns the label "prezent" into proof that
any individual authorisation is currently valid, unchanged, in force or
otherwise reader-facing.
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
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

SOURCE_ID = "signal-djm-valcea-environment-permit-register-reference"
TAXONOMY_VERSION = "2026-08-31.1"
SOURCE_NAME = "Direcția Județeană de Mediu Vâlcea / Agenția Națională pentru Mediu și Arii Protejate"
SOURCE_TIER = "T1_OFFICIAL_ENVIRONMENT_AUTHORITY_FIRST_PARTY"
SOURCE_URL = "https://djmvl.anmap.gov.ro/"
CANONICAL_HOST = "djmvl.anmap.gov.ro"
ROOT_PATH = "/"
CURRENT_REGISTER_PATH = (
    "/centralizator-autorizatii-de-mediu-autorizatii-integrate-de-mediu-"
    "01-08-2025-prezent/"
)
COVERAGE_START = "2025-08-01"
MAX_RESPONSE_BYTES = 2_500_000
TIMEOUT_SECONDS = 15
USER_AGENT = "CIVORA-ValceaClar-DJMValcea/1.0 (+evidence-first; contact via repository)"

IDENTITY_MARKERS = (
    "djm valcea",
    "directia judeteana de mediu valcea",
)
AUTHORITY_MARKER = "agentia nationala pentru mediu si arii protejate"
REGISTER_LABEL_MARKERS = (
    "centralizator autorizatii de mediu",
    "autorizatii integrate de mediu",
    "01.08.2025",
    "prezent",
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


@dataclass(frozen=True)
class EnvironmentPermitRegisterReference:
    kind: str
    title: str
    coverage_start: str
    coverage_end_label: str
    canonical_index_url: str
    canonical_reference_url: str
    evidence_sha256: str


@dataclass(frozen=True)
class DJMValceaEnvironmentPermitRegisterState:
    source_id: str
    taxonomy_version: str
    source_name: str
    source_tier: str
    source_url: str
    source_payload_sha256: str
    as_of_date: str
    state: str
    hold_reason: Optional[str]
    references: tuple[EnvironmentPermitRegisterReference, ...]
    reference_scope: str = "FIRST_PARTY_REGISTER_REFERENCE_ONLY"
    register_body_fetch_allowed: bool = False
    individual_permit_extraction_allowed: bool = False
    permit_holder_or_person_extraction_allowed: bool = False
    project_or_location_extraction_allowed: bool = False
    permit_count_inference_allowed: bool = False
    current_validity_inference_allowed: bool = False
    current_regulatory_status_inference_allowed: bool = False
    legal_effect_inference_allowed: bool = False
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


def normalized_path(value: str, *, trailing_slash: bool = True) -> str:
    path = re.sub(r"/+", "/", unquote(value or "/"))
    if not path.startswith("/"):
        path = "/" + path
    if trailing_slash and not path.endswith("/"):
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
        raise ValueError(f"off-surface DJM Vâlcea source refused: {url}")
    return urlunsplit(("https", CANONICAL_HOST, ROOT_PATH, "", ""))


def validate_register_url(url: str, *, base_url: str = SOURCE_URL) -> str:
    absolute = urljoin(validate_source_url(base_url), clean(url))
    parsed = urlsplit(absolute)
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
        or path != CURRENT_REGISTER_PATH
    ):
        raise ValueError(f"off-surface DJM Vâlcea register refused: {url}")
    return urlunsplit(("https", CANONICAL_HOST, CURRENT_REGISTER_PATH, "", ""))


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
            raise ValueError("canonical source drift after fetch")
        content_type = clean(response.headers.get("Content-Type", "")).casefold()
        if "text/html" not in content_type:
            raise ValueError(f"non-HTML DJM source refused: {content_type or 'unknown'}")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds size cap")
        charset = response.headers.get_content_charset() or "utf-8"
    return final_url, body.decode(charset, errors="replace"), body


class HomepageParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.anchor_href: Optional[str] = None
        self.anchor_parts: list[str] = []
        self.anchors: list[tuple[str, str]] = []
        self.visible_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "a":
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
            if label and self.anchor_href:
                self.anchors.append((label, self.anchor_href))
            self.anchor_href = None
            self.anchor_parts = []

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        value = clean(data)
        if not value:
            return
        self.visible_parts.append(value)
        if self.anchor_href is not None:
            self.anchor_parts.append(value)

    def visible_text(self) -> str:
        return clean(" ".join(self.visible_parts))


def _identity_ok(visible_text: str) -> bool:
    folded = fold(visible_text)
    return any(marker in folded for marker in IDENTITY_MARKERS) and AUTHORITY_MARKER in folded


def _label_ok(label: str) -> bool:
    folded = fold(label)
    return all(marker in folded for marker in REGISTER_LABEL_MARKERS)


def _hold(
    source_url: str,
    digest: str,
    as_of: date,
    reason: str,
) -> DJMValceaEnvironmentPermitRegisterState:
    return DJMValceaEnvironmentPermitRegisterState(
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


def build_state(
    html_text: str,
    payload: bytes,
    *,
    as_of: date,
    source_url: str = SOURCE_URL,
) -> DJMValceaEnvironmentPermitRegisterState:
    canonical = validate_source_url(source_url)
    digest = hashlib.sha256(payload).hexdigest()
    parser = HomepageParser()
    try:
        parser.feed(html_text)
    except Exception as exc:
        return _hold(canonical, digest, as_of, f"html_parse_error:{type(exc).__name__}")

    visible = parser.visible_text()
    folded_visible = fold(visible)
    if any(term in folded_visible[:8000] for term in PLACEHOLDER_TERMS):
        return _hold(canonical, digest, as_of, "placeholder_or_challenge_page")
    if not _identity_ok(visible):
        return _hold(canonical, digest, as_of, "djm_valcea_identity_missing")

    matches: list[tuple[str, str]] = []
    malformed_candidate_count = 0
    for label, href in parser.anchors:
        if not _label_ok(label):
            continue
        try:
            target = validate_register_url(href, base_url=canonical)
        except ValueError:
            malformed_candidate_count += 1
            continue
        matches.append((clean(label), target))

    if malformed_candidate_count and not matches:
        return _hold(canonical, digest, as_of, "register_label_found_off_surface")
    if not matches:
        return _hold(canonical, digest, as_of, "current_register_reference_missing")

    unique = {(label, target) for label, target in matches}
    if len(unique) != 1:
        return _hold(canonical, digest, as_of, f"ambiguous_current_register_reference:{len(unique)}")

    label, target = next(iter(unique))
    evidence = (
        f"{clean(label)}|coverage_start={COVERAGE_START}|"
        "coverage_end_label=PRESENT_LABEL_ONLY|"
        f"index={canonical}|reference={target}"
    )
    reference = EnvironmentPermitRegisterReference(
        kind="ENVIRONMENTAL_PERMIT_REGISTER_REFERENCE",
        title=label,
        coverage_start=COVERAGE_START,
        coverage_end_label="PRESENT_LABEL_ONLY",
        canonical_index_url=canonical,
        canonical_reference_url=target,
        evidence_sha256=hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
    )
    return DJMValceaEnvironmentPermitRegisterState(
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


def run_live(
    *,
    as_of: date,
    source_url: str = SOURCE_URL,
) -> DJMValceaEnvironmentPermitRegisterState:
    canonical = validate_source_url(source_url)
    try:
        _, text, payload = fetch_source(canonical)
    except Exception as exc:
        return _hold(
            canonical,
            hashlib.sha256(b"").hexdigest(),
            as_of,
            f"fetch_error:{type(exc).__name__}",
        )
    return build_state(text, payload, as_of=as_of, source_url=canonical)


def _synthetic(
    *,
    label: str = "Centralizator autorizații de mediu / autorizații integrate de mediu 01.08.2025 – prezent",
    href: str = CURRENT_REGISTER_PATH,
    identity: str = "DJM Vâlcea",
    authority: str = "Agenția Națională pentru Mediu și Arii Protejate",
) -> str:
    return (
        "<!doctype html><html><body><main>"
        f"<h1>{identity}</h1><p>{authority}</p>"
        f'<a href="{href}">{label}</a>'
        "</main></body></html>"
    )


def self_test() -> None:
    as_of = date(2026, 8, 31)
    html = _synthetic()
    state = build_state(html, html.encode(), as_of=as_of)
    assert state.state == "REFERENCE_READY", state
    assert len(state.references) == 1
    ref = state.references[0]
    assert ref.kind == "ENVIRONMENTAL_PERMIT_REGISTER_REFERENCE"
    assert ref.coverage_start == "2025-08-01"
    assert ref.coverage_end_label == "PRESENT_LABEL_ONLY"
    assert ref.canonical_reference_url.endswith(CURRENT_REGISTER_PATH)
    assert state.register_body_fetch_allowed is False
    assert state.individual_permit_extraction_allowed is False
    assert state.permit_holder_or_person_extraction_allowed is False
    assert state.project_or_location_extraction_allowed is False
    assert state.permit_count_inference_allowed is False
    assert state.current_validity_inference_allowed is False
    assert state.current_regulatory_status_inference_allowed is False
    assert state.legal_effect_inference_allowed is False
    assert state.public_projection_allowed is False

    missing_identity = _synthetic(identity="Direcție regională")
    assert (
        build_state(missing_identity, missing_identity.encode(), as_of=as_of).hold_reason
        == "djm_valcea_identity_missing"
    )

    missing_authority = _synthetic(authority="Minister")
    assert (
        build_state(missing_authority, missing_authority.encode(), as_of=as_of).hold_reason
        == "djm_valcea_identity_missing"
    )

    wrong_label = _synthetic(label="Autorizații de mediu")
    assert (
        build_state(wrong_label, wrong_label.encode(), as_of=as_of).hold_reason
        == "current_register_reference_missing"
    )

    off_surface = _synthetic(href="https://example.org/centralizator/")
    assert (
        build_state(off_surface, off_surface.encode(), as_of=as_of).hold_reason
        == "register_label_found_off_surface"
    )

    wrong_path = _synthetic(href="/autorizatii/")
    assert (
        build_state(wrong_path, wrong_path.encode(), as_of=as_of).hold_reason
        == "register_label_found_off_surface"
    )

    duplicate = html.replace(
        "</main>",
        f'<a href="{CURRENT_REGISTER_PATH}">'
        "Centralizator autorizații de mediu / autorizații integrate de mediu 01.08.2025 – prezent"
        "</a></main>",
    )
    duplicate_state = build_state(duplicate, duplicate.encode(), as_of=as_of)
    assert duplicate_state.state == "REFERENCE_READY", duplicate_state
    assert len(duplicate_state.references) == 1

    ambiguous = html.replace(
        "</main>",
        '<a href="https://djmvl.anmap.gov.ro/centralizator-autorizatii-de-mediu-autorizatii-integrate-de-mediu-01-08-2025-prezent/">'
        "Centralizator autorizații de mediu / autorizații integrate de mediu 01.08.2025 – prezent (copie)"
        "</a></main>",
    )
    assert (
        build_state(ambiguous, ambiguous.encode(), as_of=as_of).hold_reason
        == "ambiguous_current_register_reference:2"
    )

    challenge = (
        "<html><body><h1>DJM Vâlcea</h1>"
        "<p>Agenția Națională pentru Mediu și Arii Protejate</p>"
        "<p>Please wait. Checking your browser.</p></body></html>"
    )
    assert (
        build_state(challenge, challenge.encode(), as_of=as_of).hold_reason
        == "placeholder_or_challenge_page"
    )

    assert validate_source_url("https://djmvl.anmap.gov.ro") == SOURCE_URL
    for bad in (
        "http://djmvl.anmap.gov.ro/",
        "https://anmap.gov.ro/",
        "https://djmvl.anmap.gov.ro/?x=1",
        "https://user@djmvl.anmap.gov.ro/",
    ):
        try:
            validate_source_url(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe source URL accepted: {bad}")

    assert validate_register_url(CURRENT_REGISTER_PATH).endswith(CURRENT_REGISTER_PATH)
    for bad in (
        "http://djmvl.anmap.gov.ro" + CURRENT_REGISTER_PATH,
        "https://djmvl.anmap.gov.ro/autorizatii/",
        "https://example.org" + CURRENT_REGISTER_PATH,
        CURRENT_REGISTER_PATH + "?download=1",
    ):
        try:
            validate_register_url(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe register URL accepted: {bad}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--as-of", default=date.today().isoformat())
    args = parser.parse_args()

    if args.self_test:
        self_test()
        print("DJM Vâlcea environment permit-register adapter self-test: PASS")
        return 0

    if args.live:
        state = run_live(as_of=date.fromisoformat(args.as_of))
        print(json.dumps(asdict(state), ensure_ascii=False, indent=2))
        return 0 if state.state == "REFERENCE_READY" else 2

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
