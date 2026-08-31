#!/usr/bin/env python3
"""Fail-closed references for CJ Vâlcea executive-disposition registers.

Only the official Monitorul Oficial Local index page is read. Linked register
files are never followed, and an index row is never treated as proof of the
content, legal effect, current validity, amendment/repeal status, or
implementation of any individual executive disposition.
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

SOURCE_ID = "signal-cj-valcea-executive-disposition-register-reference"
TAXONOMY_VERSION = "2026-08-31.1"
SOURCE_NAME = "Consiliul Județean Vâlcea — Dispozițiile autorității executive"
SOURCE_TIER = "T1_OFFICIAL_COUNTY_COUNCIL_FIRST_PARTY"
CANONICAL_HOST = "cjvalcea.ro"
SOURCE_PATH = "/monitorul-oficial-local/dispozitiile-autoritatii-executive/"
SOURCE_URL = f"https://{CANONICAL_HOST}{SOURCE_PATH}"
MAX_RESPONSE_BYTES = 2_500_000
TIMEOUT_SECONDS = 15
MAX_REFERENCES = 8
USER_AGENT = "CIVORA-ValceaClar-CJValceaExecutiveRegisters/1.0 (+evidence-first; contact via repository)"
IDENTITY_MARKERS = (
    "dispozitiile autoritatii executive",
    "actele administrative emise de presedintele consiliului judetean",
    "registrul pentru evidenta",
)
PLACEHOLDER_TERMS = (
    "access denied", "captcha", "checking your browser", "cloudflare",
    "enable javascript", "please wait", "service unavailable",
    "temporarily unavailable", "verify you are human",
)
YEAR_RE = re.compile(r"^(20\d{2})$")


@dataclass(frozen=True)
class ExecutiveDispositionRegisterReference:
    kind: str
    year: int
    title: str
    file_label_present: bool
    canonical_index_url: str
    evidence_sha256: str


@dataclass(frozen=True)
class CJValceaExecutiveDispositionRegisterState:
    source_id: str
    taxonomy_version: str
    source_name: str
    source_tier: str
    source_url: str
    source_payload_sha256: str
    as_of_date: str
    state: str
    hold_reason: Optional[str]
    references: tuple[ExecutiveDispositionRegisterReference, ...]
    reference_scope: str = "FIRST_PARTY_EXECUTIVE_DISPOSITION_REGISTER_INDEX_REFERENCE_ONLY"
    attached_file_follow_allowed: bool = False
    attached_document_body_fetch_allowed: bool = False
    individual_disposition_extraction_allowed: bool = False
    person_or_personal_data_extraction_allowed: bool = False
    legal_effect_inference_allowed: bool = False
    current_validity_inference_allowed: bool = False
    amendment_status_inference_allowed: bool = False
    repeal_status_inference_allowed: bool = False
    implementation_status_inference_allowed: bool = False
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
        or path != SOURCE_PATH
    ):
        raise ValueError(f"off-surface CJ Vâlcea executive-disposition source refused: {url}")
    return urlunsplit(("https", CANONICAL_HOST, SOURCE_PATH, "", ""))


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
            raise ValueError(f"non-HTML CJ source refused: {content_type or 'unknown'}")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds size cap")
        charset = response.headers.get_content_charset() or "utf-8"
    return final_url, body.decode(charset, errors="replace"), body


class RegisterTableParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.in_row = 0
        self.in_cell = 0
        self.cell_parts: list[str] = []
        self.row_cells: list[str] = []
        self.rows: list[tuple[str, ...]] = []
        self.visible_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "tr":
            self.in_row += 1
            if self.in_row == 1:
                self.row_cells = []
        elif tag in {"td", "th"} and self.in_row:
            self.in_cell += 1
            if self.in_cell == 1:
                self.cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            if self.skip:
                self.skip -= 1
            return
        if self.skip:
            return
        if tag in {"td", "th"} and self.in_cell:
            if self.in_cell == 1:
                self.row_cells.append(clean(" ".join(self.cell_parts)))
                self.cell_parts = []
            self.in_cell -= 1
        elif tag == "tr" and self.in_row:
            if self.in_row == 1 and self.row_cells:
                self.rows.append(tuple(self.row_cells))
                self.row_cells = []
            self.in_row -= 1

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        value = clean(data)
        if not value:
            return
        self.visible_parts.append(value)
        if self.in_cell:
            self.cell_parts.append(value)

    def visible_text(self) -> str:
        return clean(" ".join(self.visible_parts))


def classify_register(title: str) -> Optional[str]:
    value = fold(title)
    if "registrul pentru evidenta proiectelor" in value and "dispoziti" in value:
        return "COUNTY_EXECUTIVE_DRAFT_DISPOSITION_REGISTER_REFERENCE"
    if "registrul pentru evidenta" in value and "dispoziti" in value:
        return "COUNTY_EXECUTIVE_DISPOSITION_REGISTER_REFERENCE"
    return None


def _hold(
    source_url: str,
    digest: str,
    as_of: date,
    reason: str,
) -> CJValceaExecutiveDispositionRegisterState:
    return CJValceaExecutiveDispositionRegisterState(
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
) -> CJValceaExecutiveDispositionRegisterState:
    canonical = validate_source_url(source_url)
    digest = hashlib.sha256(payload).hexdigest()
    parser = RegisterTableParser()
    try:
        parser.feed(html_text)
    except Exception as exc:
        return _hold(canonical, digest, as_of, f"html_parse_error:{type(exc).__name__}")

    visible = parser.visible_text()
    folded_visible = fold(visible)
    if any(term in folded_visible[:10000] for term in PLACEHOLDER_TERMS):
        return _hold(canonical, digest, as_of, "placeholder_or_challenge_page")
    if not all(marker in folded_visible for marker in IDENTITY_MARKERS):
        return _hold(canonical, digest, as_of, "cj_valcea_executive_disposition_identity_missing")

    refs: list[ExecutiveDispositionRegisterReference] = []
    seen: set[tuple[str, int, str]] = set()
    for cells in parser.rows:
        if len(cells) < 2:
            continue
        year_match = YEAR_RE.match(clean(cells[0]))
        if not year_match:
            continue
        year = int(year_match.group(1))
        if year != as_of.year:
            continue
        title = clean(cells[1])
        kind = classify_register(title)
        if not kind:
            continue
        file_label_present = len(cells) >= 3 and any(
            token in fold(cells[2]) for token in ("vizualizare", "descarcare")
        )
        key = (kind, year, title)
        if key in seen:
            continue
        seen.add(key)
        evidence = (
            f"kind={kind}|year={year}|title={title}|"
            f"file_label_present={file_label_present}|index={canonical}"
        )
        refs.append(
            ExecutiveDispositionRegisterReference(
                kind=kind,
                year=year,
                title=title,
                file_label_present=file_label_present,
                canonical_index_url=canonical,
                evidence_sha256=hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
            )
        )

    refs.sort(key=lambda item: (item.kind, item.title))
    if not refs:
        return _hold(canonical, digest, as_of, "current_year_executive_register_references_missing")

    kinds = {item.kind for item in refs}
    expected = {
        "COUNTY_EXECUTIVE_DRAFT_DISPOSITION_REGISTER_REFERENCE",
        "COUNTY_EXECUTIVE_DISPOSITION_REGISTER_REFERENCE",
    }
    if not expected.issubset(kinds):
        return _hold(canonical, digest, as_of, "current_year_executive_register_pair_incomplete")

    return CJValceaExecutiveDispositionRegisterState(
        source_id=SOURCE_ID,
        taxonomy_version=TAXONOMY_VERSION,
        source_name=SOURCE_NAME,
        source_tier=SOURCE_TIER,
        source_url=canonical,
        source_payload_sha256=digest,
        as_of_date=as_of.isoformat(),
        state="REFERENCE_READY",
        hold_reason=None,
        references=tuple(refs[:MAX_REFERENCES]),
    )


def run_live(
    *,
    as_of: date,
    source_url: str = SOURCE_URL,
) -> CJValceaExecutiveDispositionRegisterState:
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
    identity: str = (
        "Dispozițiile autorității executive — "
        "Actele administrative emise de președintele Consiliului Județean — "
        "Registrul pentru evidența"
    ),
    year: str = "2026",
    include_draft: bool = True,
    include_adopted: bool = True,
) -> str:
    rows: list[str] = []
    if include_draft:
        rows.append(
            f"<tr><td>{year}</td><td>Registrul pentru evidența proiectelor "
            "Dispozițiilor Președintelui Consiliului Județean Vâlcea</td>"
            "<td><a href='https://example.invalid/draft.xlsx'>Vizualizare</a></td></tr>"
        )
    if include_adopted:
        rows.append(
            f"<tr><td>{year}</td><td>Registrul pentru evidența "
            "Dispozițiilor Președintelui Consiliului Județean Vâlcea</td>"
            "<td><a href='https://example.invalid/adopted.xlsx'>Vizualizare</a></td></tr>"
        )
    return (
        "<html><body><h1>" + identity + "</h1>"
        "<table><tr><th>AN</th><th>DENUMIRE</th><th>FIȘIER</th></tr>"
        + "".join(rows)
        + "</table></body></html>"
    )


def self_test() -> None:
    as_of = date(2026, 8, 31)
    html_ok = _synthetic()
    state = build_state(html_ok, html_ok.encode("utf-8"), as_of=as_of)
    assert state.state == "REFERENCE_READY"
    assert state.hold_reason is None
    assert len(state.references) == 2
    assert {r.kind for r in state.references} == {
        "COUNTY_EXECUTIVE_DRAFT_DISPOSITION_REGISTER_REFERENCE",
        "COUNTY_EXECUTIVE_DISPOSITION_REGISTER_REFERENCE",
    }
    assert all(r.year == 2026 for r in state.references)
    assert all(r.file_label_present for r in state.references)
    assert all(len(r.evidence_sha256) == 64 for r in state.references)
    assert state.attached_file_follow_allowed is False
    assert state.attached_document_body_fetch_allowed is False
    assert state.individual_disposition_extraction_allowed is False
    assert state.legal_effect_inference_allowed is False
    assert state.current_validity_inference_allowed is False
    assert state.persistence_allowed is False
    assert state.fact_kernel_promotion_allowed is False
    assert state.writer_allowed is False
    assert state.public_projection_allowed is False
    assert state.publication_authority == "NONE"

    wrong_year = _synthetic(year="2025")
    held = build_state(wrong_year, wrong_year.encode("utf-8"), as_of=as_of)
    assert held.state == "HOLD"
    assert held.hold_reason == "current_year_executive_register_references_missing"

    incomplete = _synthetic(include_adopted=False)
    held = build_state(incomplete, incomplete.encode("utf-8"), as_of=as_of)
    assert held.state == "HOLD"
    assert held.hold_reason == "current_year_executive_register_pair_incomplete"

    no_identity = _synthetic(identity="Unrelated page")
    held = build_state(no_identity, no_identity.encode("utf-8"), as_of=as_of)
    assert held.state == "HOLD"
    assert held.hold_reason == "cj_valcea_executive_disposition_identity_missing"

    challenged = "<html><body>Captcha verify you are human " + _synthetic() + "</body></html>"
    held = build_state(challenged, challenged.encode("utf-8"), as_of=as_of)
    assert held.state == "HOLD"
    assert held.hold_reason == "placeholder_or_challenge_page"

    for bad in (
        "http://cjvalcea.ro/monitorul-oficial-local/dispozitiile-autoritatii-executive/",
        "https://www.cjvalcea.ro/monitorul-oficial-local/dispozitiile-autoritatii-executive/",
        "https://cjvalcea.ro/monitorul-oficial-local/dispozitiile-autoritatii-executive/?x=1",
        "https://cjvalcea.ro/monitorul-oficial-local/",
        "https://example.com/monitorul-oficial-local/dispozitiile-autoritatii-executive/",
    ):
        try:
            validate_source_url(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected off-surface URL refusal: {bad}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--as-of", default=date.today().isoformat())
    args = parser.parse_args()

    if args.self_test:
        self_test()
        print("ok")
        return 0

    if not args.live:
        parser.error("choose --self-test or --live")

    as_of = date.fromisoformat(args.as_of)
    state = run_live(as_of=as_of)
    print(json.dumps(asdict(state), ensure_ascii=False, indent=2))
    return 0 if state.state == "REFERENCE_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
