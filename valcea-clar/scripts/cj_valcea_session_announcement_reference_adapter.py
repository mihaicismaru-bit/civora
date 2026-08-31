#!/usr/bin/env python3
"""Fail-closed references for CJ Vâlcea county-council session announcements.

Only the official announcement index is read. Attached files are never followed,
and an announcement is never treated as proof that a session is still scheduled,
unchanged, held, quorate, valid, or legally effective.
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
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import unquote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

SOURCE_ID = "signal-cj-valcea-session-announcement-reference"
TAXONOMY_VERSION = "2026-08-31.1"
SOURCE_NAME = "Consiliul Județean Vâlcea — Anunțuri ședințe"
SOURCE_TIER = "T1_OFFICIAL_COUNTY_COUNCIL_FIRST_PARTY"
CANONICAL_HOST = "cjvalcea.ro"
SOURCE_PATH = "/monitorul-oficial-local/alte-documente/anunturi-sedinte/"
SOURCE_URL = f"https://{CANONICAL_HOST}{SOURCE_PATH}"
MAX_RESPONSE_BYTES = 2_500_000
TIMEOUT_SECONDS = 15
MAX_REFERENCES = 64
USER_AGENT = "CIVORA-ValceaClar-CJValceaSessions/1.0 (+evidence-first; contact via repository)"
IDENTITY_MARKERS = ("anunturi sedinte", "consiliul judetean valcea")
PLACEHOLDER_TERMS = (
    "access denied", "captcha", "checking your browser", "cloudflare",
    "enable javascript", "please wait", "service unavailable",
    "temporarily unavailable", "verify you are human",
)
DATE_RE = re.compile(r"\b(\d{2})[.](\d{2})[.](20\d{2})\b")


@dataclass(frozen=True)
class CountyCouncilSessionAnnouncementReference:
    kind: str
    session_type: str
    session_date: str
    announcement_date: str
    title: str
    canonical_index_url: str
    evidence_sha256: str


@dataclass(frozen=True)
class CJValceaSessionAnnouncementState:
    source_id: str
    taxonomy_version: str
    source_name: str
    source_tier: str
    source_url: str
    source_payload_sha256: str
    as_of_date: str
    state: str
    hold_reason: Optional[str]
    references: tuple[CountyCouncilSessionAnnouncementReference, ...]
    reference_scope: str = "FIRST_PARTY_SESSION_ANNOUNCEMENT_INDEX_REFERENCE_ONLY"
    attached_file_follow_allowed: bool = False
    attached_document_body_fetch_allowed: bool = False
    person_or_personal_data_extraction_allowed: bool = False
    session_still_scheduled_inference_allowed: bool = False
    cancellation_status_inference_allowed: bool = False
    session_held_inference_allowed: bool = False
    quorum_or_vote_inference_allowed: bool = False
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
        raise ValueError(f"off-surface CJ Vâlcea session source refused: {url}")
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


class SessionTableParser(html.parser.HTMLParser):
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


def parse_date_label(value: str) -> Optional[str]:
    match = DATE_RE.search(clean(value))
    if not match:
        return None
    day, month, year = map(int, match.groups())
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return None


def classify_session(title: str) -> str:
    value = fold(title)
    if "sedinta extraordinara" in value:
        return "EXTRAORDINARY"
    if "sedinta ordinara" in value:
        return "ORDINARY"
    return "UNSPECIFIED"


def _hold(source_url: str, digest: str, as_of: date, reason: str) -> CJValceaSessionAnnouncementState:
    return CJValceaSessionAnnouncementState(
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
) -> CJValceaSessionAnnouncementState:
    canonical = validate_source_url(source_url)
    digest = hashlib.sha256(payload).hexdigest()
    parser = SessionTableParser()
    try:
        parser.feed(html_text)
    except Exception as exc:
        return _hold(canonical, digest, as_of, f"html_parse_error:{type(exc).__name__}")

    visible = parser.visible_text()
    folded_visible = fold(visible)
    if any(term in folded_visible[:8000] for term in PLACEHOLDER_TERMS):
        return _hold(canonical, digest, as_of, "placeholder_or_challenge_page")
    if not all(marker in folded_visible for marker in IDENTITY_MARKERS):
        return _hold(canonical, digest, as_of, "cj_valcea_session_identity_missing")
    if str(as_of.year) not in visible:
        return _hold(canonical, digest, as_of, "current_year_archive_missing")

    refs: list[CountyCouncilSessionAnnouncementReference] = []
    seen: set[tuple[str, str, str]] = set()
    for cells in parser.rows:
        if len(cells) < 3:
            continue
        session_date = parse_date_label(cells[0])
        announcement_date = parse_date_label(cells[1])
        title = clean(cells[2])
        folded_title = fold(title)
        if not session_date or not announcement_date:
            continue
        if "consiliului judetean valcea" not in folded_title or "sedinta" not in folded_title:
            continue
        if not (
            session_date.startswith(f"{as_of.year}-")
            and announcement_date.startswith(f"{as_of.year}-")
        ):
            continue
        key = (session_date, announcement_date, title)
        if key in seen:
            continue
        seen.add(key)
        session_type = classify_session(title)
        evidence = (
            "kind=COUNTY_COUNCIL_SESSION_ANNOUNCEMENT_REFERENCE|"
            f"session_type={session_type}|session_date={session_date}|"
            f"announcement_date={announcement_date}|title={title}|index={canonical}"
        )
        refs.append(
            CountyCouncilSessionAnnouncementReference(
                kind="COUNTY_COUNCIL_SESSION_ANNOUNCEMENT_REFERENCE",
                session_type=session_type,
                session_date=session_date,
                announcement_date=announcement_date,
                title=title,
                canonical_index_url=canonical,
                evidence_sha256=hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
            )
        )

    refs.sort(key=lambda item: (item.session_date, item.announcement_date, item.title), reverse=True)
    if not refs:
        return _hold(canonical, digest, as_of, "current_year_session_references_missing")

    return CJValceaSessionAnnouncementState(
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


def run_live(*, as_of: date, source_url: str = SOURCE_URL) -> CJValceaSessionAnnouncementState:
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
    identity: str = "Anunțuri ședințe — Consiliul Județean Vâlcea",
    year: str = "2026",
    rows: str = "",
) -> str:
    default_rows = """
      <tr><th>DATA ȘEDINȚEI</th><th>DATA AFIȘĂRII</th><th>DENUMIRE ANUNȚ ȘEDINȚĂ</th><th>FIȘIER</th></tr>
      <tr><td>26.08.2026</td><td>20.08.2026</td><td>Anunț privind ședința ordinară a Consiliului Județean Vâlcea din data de 26 august 2026, ora 10.00</td><td><a href='/file.pdf'>Vizualizare</a></td></tr>
      <tr><td>11.08.2026</td><td>07.08.2026</td><td>Anunț privind ședința extraordinară a Consiliului Județean Vâlcea din data de 11 august 2026, ora 10.00</td><td>Vizualizare</td></tr>
    """
    return (
        f"<!doctype html><html><body><h1>{identity}</h1><div>{year}</div>"
        f"<table>{rows or default_rows}</table></body></html>"
    )


def self_test() -> None:
    as_of = date(2026, 8, 31)
    html = _synthetic()
    state = build_state(html, html.encode(), as_of=as_of)
    assert state.state == "REFERENCE_READY", state
    assert len(state.references) == 2
    assert state.references[0].session_date == "2026-08-26"
    assert state.references[0].session_type == "ORDINARY"
    assert state.references[1].session_type == "EXTRAORDINARY"
    assert state.attached_file_follow_allowed is False
    assert state.attached_document_body_fetch_allowed is False
    assert state.session_still_scheduled_inference_allowed is False
    assert state.cancellation_status_inference_allowed is False
    assert state.session_held_inference_allowed is False
    assert state.legal_effect_inference_allowed is False
    assert state.public_projection_allowed is False

    missing_identity = _synthetic(identity="Arhivă publică")
    assert (
        build_state(missing_identity, missing_identity.encode(), as_of=as_of).hold_reason
        == "cj_valcea_session_identity_missing"
    )

    rows_2025 = "<tr><td>26.08.2025</td><td>20.08.2025</td><td>Anunț privind ședința Consiliului Județean Vâlcea</td></tr>"
    missing_year = _synthetic(year="2025", rows=rows_2025)
    assert (
        build_state(missing_year, missing_year.encode(), as_of=as_of).hold_reason
        == "current_year_archive_missing"
    )

    no_rows = _synthetic(
        rows="<tr><td>26.08.2026</td><td>20.08.2026</td><td>Comunicat general Consiliul Județean Vâlcea</td></tr>"
    )
    assert (
        build_state(no_rows, no_rows.encode(), as_of=as_of).hold_reason
        == "current_year_session_references_missing"
    )

    challenge = "<html><body>Anunțuri ședințe Consiliul Județean Vâlcea 2026 verify you are human</body></html>"
    assert (
        build_state(challenge, challenge.encode(), as_of=as_of).hold_reason
        == "placeholder_or_challenge_page"
    )

    for bad in (
        "http://cjvalcea.ro/monitorul-oficial-local/alte-documente/anunturi-sedinte/",
        "https://www.cjvalcea.ro/monitorul-oficial-local/alte-documente/anunturi-sedinte/",
        "https://cjvalcea.ro/monitorul-oficial-local/alte-documente/minute-sedinte/",
        "https://cjvalcea.ro/monitorul-oficial-local/alte-documente/anunturi-sedinte/?x=1",
        "https://example.org/monitorul-oficial-local/alte-documente/anunturi-sedinte/",
    ):
        try:
            validate_source_url(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"off-surface URL accepted: {bad}")


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
    as_of = date.fromisoformat(args.as_of)
    if not args.live:
        parser.error("use --live or --self-test")
    state = run_live(as_of=as_of)
    print(json.dumps(asdict(state), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if state.state == "REFERENCE_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
