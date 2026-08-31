#!/usr/bin/env python3
"""Fail-closed references for Râmnicu Vâlcea Local Council adopted decisions.

Only the official current-year Domino index is read. Individual decision files are
never followed. A discovered reference is metadata only and is never treated as
proof that a decision is currently in force, unchanged, implemented, or otherwise
legally effective.
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
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

SOURCE_ID = "signal-ramnicu-valcea-local-council-decision-reference"
TAXONOMY_VERSION = "2026-09-01.1"
SOURCE_NAME = "Municipiul Râmnicu Vâlcea — Hotărâri ale Consiliului Local 2026"
SOURCE_TIER = "T1_OFFICIAL_MUNICIPALITY_FIRST_PARTY"
CANONICAL_HOST = "dm.primariavl.ro"
SOURCE_PATH = "/dm/2026/hotarari.nsf/vwHotarariByAn"
SOURCE_QUERY = "openview"
SOURCE_URL = f"https://{CANONICAL_HOST}{SOURCE_PATH}?{SOURCE_QUERY}"
DECISION_PATH_PREFIX = "/dm/2026/hotarari.nsf/"
MAX_RESPONSE_BYTES = 4_000_000
TIMEOUT_SECONDS = 15
MAX_REFERENCES = 256
USER_AGENT = "CIVORA-ValceaClar-RamnicuValceaCLDecisions/1.0 (+evidence-first; contact via repository)"
PLACEHOLDER_TERMS = (
    "access denied", "captcha", "checking your browser", "cloudflare",
    "enable javascript", "please wait", "service unavailable",
    "temporarily unavailable", "verify you are human",
)
NUMBER_RE = re.compile(r"\bhot[aăâ]r(?:a|â|ă)rea?\s*(?:nr\.?\s*)?(\d{1,4})\b", re.IGNORECASE)
PLAIN_NUMBER_RE = re.compile(r"^\s*(\d{1,4})\s*$")
DATE_DMY_RE = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](20\d{2})\b")
DATE_TEXT_RE = re.compile(
    r"\b(\d{1,2})\s+(ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|"
    r"septembrie|octombrie|noiembrie|decembrie)\s+(20\d{2})\b",
    re.IGNORECASE,
)
MONTHS = {
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4, "mai": 5, "iunie": 6,
    "iulie": 7, "august": 8, "septembrie": 9, "octombrie": 10, "noiembrie": 11, "decembrie": 12,
}


@dataclass(frozen=True)
class LocalCouncilDecisionReference:
    kind: str
    decision_number: int
    decision_date: str
    title_hint: str
    document_reference_url: str
    document_reference_unfollowed: bool
    canonical_index_url: str
    evidence_sha256: str


@dataclass(frozen=True)
class RamnicuValceaLocalCouncilDecisionState:
    source_id: str
    taxonomy_version: str
    source_name: str
    source_tier: str
    source_url: str
    source_payload_sha256: str
    as_of_date: str
    state: str
    hold_reason: Optional[str]
    references: tuple[LocalCouncilDecisionReference, ...]
    reference_scope: str = "FIRST_PARTY_LOCAL_COUNCIL_ADOPTED_DECISION_REFERENCE_ONLY"
    decision_document_follow_allowed: bool = False
    decision_document_body_fetch_allowed: bool = False
    person_or_personal_data_extraction_allowed: bool = False
    monetary_value_extraction_allowed: bool = False
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


def validate_source_url(url: str) -> str:
    parsed = urlsplit(clean(url))
    host = (parsed.hostname or "").casefold()
    query = parsed.query.casefold()
    if (
        parsed.scheme.casefold() != "https"
        or host != CANONICAL_HOST
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.path != SOURCE_PATH
        or query != SOURCE_QUERY
        or parsed.fragment
    ):
        raise ValueError(f"off-surface Râmnicu Vâlcea Local Council source refused: {url}")
    return urlunsplit(("https", CANONICAL_HOST, SOURCE_PATH, SOURCE_QUERY, ""))


def validate_decision_reference(base_url: str, href: str) -> str:
    absolute = urljoin(base_url, clean(href))
    parsed = urlsplit(absolute)
    host = (parsed.hostname or "").casefold()
    decoded_path = unquote(parsed.path)
    path_folded = decoded_path.casefold()
    if (
        parsed.scheme.casefold() != "https"
        or host != CANONICAL_HOST
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not path_folded.startswith(DECISION_PATH_PREFIX.casefold())
        or "/$file/" not in path_folded
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"off-surface decision reference refused: {absolute}")
    return urlunsplit(("https", CANONICAL_HOST, parsed.path, "", ""))


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
            raise ValueError(f"non-HTML source refused: {content_type or 'unknown'}")
        payload = response.read(MAX_RESPONSE_BYTES + 1)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds size cap")
        charset = response.headers.get_content_charset() or "utf-8"
    return final_url, payload.decode(charset, errors="replace"), payload


class IndexParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.in_row = 0
        self.row_parts: list[str] = []
        self.row_links: list[tuple[str, str]] = []
        self.rows: list[tuple[str, tuple[tuple[str, str], ...]]] = []
        self.current_href: Optional[str] = None
        self.current_anchor_parts: list[str] = []
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
                self.row_parts = []
                self.row_links = []
        elif tag == "a":
            attr_map = {clean(k).casefold(): clean(v) for k, v in attrs}
            self.current_href = attr_map.get("href")
            self.current_anchor_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            if self.skip:
                self.skip -= 1
            return
        if self.skip:
            return
        if tag == "a" and self.current_href is not None:
            self.row_links.append((self.current_href, clean(" ".join(self.current_anchor_parts))))
            self.current_href = None
            self.current_anchor_parts = []
        elif tag == "tr" and self.in_row:
            if self.in_row == 1 and (self.row_parts or self.row_links):
                self.rows.append((clean(" ".join(self.row_parts)), tuple(self.row_links)))
                self.row_parts = []
                self.row_links = []
            self.in_row -= 1

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        value = clean(data)
        if not value:
            return
        self.visible_parts.append(value)
        if self.in_row:
            self.row_parts.append(value)
        if self.current_href is not None:
            self.current_anchor_parts.append(value)

    def visible_text(self) -> str:
        return clean(" ".join(self.visible_parts))


def parse_number(*values: str) -> Optional[int]:
    for value in values:
        folded = fold(unquote(value))
        match = NUMBER_RE.search(folded)
        if match:
            number = int(match.group(1))
            if number > 0:
                return number
    for value in values:
        match = PLAIN_NUMBER_RE.match(clean(value))
        if match and int(match.group(1)) > 0:
            return int(match.group(1))
    return None


def parse_date(*values: str) -> Optional[str]:
    for value in values:
        text = fold(unquote(value))
        match = DATE_DMY_RE.search(text)
        if match:
            day, month, year = map(int, match.groups())
            try:
                return datetime(year, month, day).date().isoformat()
            except ValueError:
                pass
        match = DATE_TEXT_RE.search(text)
        if match:
            day = int(match.group(1))
            month = MONTHS[match.group(2).casefold()]
            year = int(match.group(3))
            try:
                return datetime(year, month, day).date().isoformat()
            except ValueError:
                pass
    return None


def title_hint(row_text: str, anchor_text: str, href: str, number: int) -> str:
    candidates = [clean(row_text), clean(anchor_text)]
    path_name = unquote(urlsplit(href).path.rsplit("/", 1)[-1])
    path_name = re.sub(r"\.(?:pdf|html?|docx?)$", "", path_name, flags=re.IGNORECASE)
    path_name = clean(path_name.replace("_", " ").replace("-", " "))
    candidates.append(path_name)
    for candidate in candidates:
        if len(candidate) >= 12:
            return candidate[:500]
    return f"Hotărârea Consiliului Local nr. {number} — titlu neverificat"


def _hold(source_url: str, digest: str, as_of: date, reason: str) -> RamnicuValceaLocalCouncilDecisionState:
    return RamnicuValceaLocalCouncilDecisionState(
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


def build_state(html_text: str, payload: bytes, *, as_of: date, source_url: str = SOURCE_URL) -> RamnicuValceaLocalCouncilDecisionState:
    canonical = validate_source_url(source_url)
    digest = hashlib.sha256(payload).hexdigest()
    parser = IndexParser()
    try:
        parser.feed(html_text)
    except Exception as exc:
        return _hold(canonical, digest, as_of, f"html_parse_error:{type(exc).__name__}")

    visible = parser.visible_text()
    folded_visible = fold(visible)
    if any(term in folded_visible[:10000] for term in PLACEHOLDER_TERMS):
        return _hold(canonical, digest, as_of, "placeholder_or_challenge_page")
    if str(as_of.year) not in visible:
        return _hold(canonical, digest, as_of, "current_year_archive_missing")

    refs: list[LocalCouncilDecisionReference] = []
    seen: set[tuple[int, str, str]] = set()
    for row_text, links in parser.rows:
        for href, anchor_text in links:
            try:
                document_url = validate_decision_reference(canonical, href)
            except ValueError:
                continue
            decision_number = parse_number(row_text, anchor_text, document_url)
            decision_date = parse_date(row_text, anchor_text, document_url)
            if decision_number is None or decision_date is None:
                continue
            if not decision_date.startswith(f"{as_of.year}-"):
                continue
            hint = title_hint(row_text, anchor_text, document_url, decision_number)
            key = (decision_number, decision_date, document_url)
            if key in seen:
                continue
            seen.add(key)
            evidence = (
                "kind=LOCAL_COUNCIL_ADOPTED_DECISION_REFERENCE|"
                f"decision_number={decision_number}|decision_date={decision_date}|"
                f"title_hint={hint}|document_reference_url={document_url}|index={canonical}"
            )
            refs.append(LocalCouncilDecisionReference(
                kind="LOCAL_COUNCIL_ADOPTED_DECISION_REFERENCE",
                decision_number=decision_number,
                decision_date=decision_date,
                title_hint=hint,
                document_reference_url=document_url,
                document_reference_unfollowed=True,
                canonical_index_url=canonical,
                evidence_sha256=hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
            ))

    refs.sort(key=lambda item: (item.decision_date, item.decision_number, item.document_reference_url), reverse=True)
    if not refs:
        return _hold(canonical, digest, as_of, "current_year_local_council_decision_references_missing")

    return RamnicuValceaLocalCouncilDecisionState(
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


def run_live(*, as_of: date, source_url: str = SOURCE_URL) -> RamnicuValceaLocalCouncilDecisionState:
    canonical = validate_source_url(source_url)
    try:
        _, text, payload = fetch_source(canonical)
    except Exception as exc:
        return _hold(canonical, hashlib.sha256(b"").hexdigest(), as_of, f"fetch_error:{type(exc).__name__}")
    return build_state(text, payload, as_of=as_of, source_url=canonical)


def _synthetic(rows: str = "", year: str = "2026") -> str:
    default_rows = r"""
      <tr><td>305</td><td>14.08.2026</td><td>Hotărârea nr.305 privind modificarea unei hotărâri anterioare</td>
      <td><a href="/dm/2026/hotarari.nsf/vwHotarariByAn/ABC123/$FILE/hotarirea%20305%20-%2014%20august%202026%20-%20modificare.htm">Vizualizare</a></td></tr>
      <tr><td>304</td><td>07.08.2026</td><td>Hotărârea nr.304 privind un serviciu public local</td>
      <td><a href="/dm/2026/hotarari.nsf/vwHotarariByAn/DEF456/$FILE/304.serviciu%20public.pdf">Vizualizare</a></td></tr>
    """
    return f"""<html><body><h1>Hotărâri Consiliul Local Râmnicu Vâlcea {year}</h1>
    <table>{rows or default_rows}</table></body></html>"""


def self_test() -> None:
    as_of = date(2026, 9, 1)
    html_text = _synthetic()
    state = build_state(html_text, html_text.encode(), as_of=as_of)
    assert state.state == "REFERENCE_READY", state
    assert [r.decision_number for r in state.references] == [305, 304]
    assert all(r.document_reference_unfollowed for r in state.references)
    assert state.publication_authority == "NONE"
    assert state.fact_kernel_promotion_allowed is False
    assert state.writer_allowed is False
    assert state.public_projection_allowed is False
    assert state.decision_document_body_fetch_allowed is False
    assert state.inferred_photo_rights_allowed is False

    dup = r"""
      <tr><td>305</td><td>14.08.2026</td><td>Hotărârea nr.305 privind test</td>
      <td><a href="/dm/2026/hotarari.nsf/vwHotarariByAn/ABC123/$FILE/hotarirea%20305%20-%2014%20august%202026.htm">Vizualizare</a></td></tr>
      <tr><td>305</td><td>14.08.2026</td><td>Hotărârea nr.305 privind test</td>
      <td><a href="/dm/2026/hotarari.nsf/vwHotarariByAn/ABC123/$FILE/hotarirea%20305%20-%2014%20august%202026.htm">Vizualizare</a></td></tr>
    """
    deduped = build_state(_synthetic(dup), _synthetic(dup).encode(), as_of=as_of)
    assert len(deduped.references) == 1

    old_year_html = _synthetic(year="2025").replace("2026", "2025")
    old_year = build_state(old_year_html, old_year_html.encode(), as_of=as_of)
    assert old_year.state == "HOLD"

    challenge = "<html><body>Verify you are human 2026</body></html>"
    held = build_state(challenge, challenge.encode(), as_of=as_of)
    assert held.state == "HOLD"

    bad_link = r"""
      <tr><td>305</td><td>14.08.2026</td><td>Hotărârea nr.305</td>
      <td><a href="https://example.com/dm/2026/hotarari.nsf/ABC/$FILE/x.pdf">Vizualizare</a></td></tr>
    """
    bad = build_state(_synthetic(bad_link), _synthetic(bad_link).encode(), as_of=as_of)
    assert bad.state == "HOLD"

    for bad_source in (
        "http://dm.primariavl.ro/dm/2026/hotarari.nsf/vwHotarariByAn?openview",
        "https://evil.example/dm/2026/hotarari.nsf/vwHotarariByAn?openview",
        "https://dm.primariavl.ro/dm/2025/hotarari.nsf/vwHotarariByAn?openview",
        "https://dm.primariavl.ro/dm/2026/hotarari.nsf/vwHotarariByAn?other",
    ):
        try:
            validate_source_url(bad_source)
        except ValueError:
            pass
        else:
            raise AssertionError(f"bad source accepted: {bad_source}")

    print("ramnicu_valcea_local_council_decision_reference_adapter self-test: OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--as-of", default=date.today().isoformat())
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date()
    if not args.live:
        raise SystemExit("use --live for bounded first-party fetch or --self-test")
    state = run_live(as_of=as_of)
    print(json.dumps(asdict(state), ensure_ascii=False, indent=2))
    return 0 if state.state == "REFERENCE_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
