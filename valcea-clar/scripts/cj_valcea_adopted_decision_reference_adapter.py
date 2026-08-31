#!/usr/bin/env python3
"""Fail-closed references for CJ Vâlcea adopted county-council decisions.

Only the official current-year index is read. Attached files are never followed,
and an index row is never treated as proof that an act is currently in force,
unamended, unrepealed, executable, or otherwise legally effective.
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

SOURCE_ID = "signal-cj-valcea-adopted-decision-reference"
TAXONOMY_VERSION = "2026-08-31.1"
SOURCE_NAME = "Consiliul Județean Vâlcea — Hotărârile Autorității Deliberative 2026"
SOURCE_TIER = "T1_OFFICIAL_COUNTY_COUNCIL_FIRST_PARTY"
CANONICAL_HOST = "cjvalcea.ro"
SOURCE_PATH = "/monitorul-oficial-local/hotararile-autoritatii-deliberative/2026-hotararile-autoritatii-deliberative/"
SOURCE_URL = f"https://{CANONICAL_HOST}{SOURCE_PATH}"
MAX_RESPONSE_BYTES = 3_500_000
TIMEOUT_SECONDS = 15
MAX_REFERENCES = 256
USER_AGENT = "CIVORA-ValceaClar-CJValceaDecisions/1.0 (+evidence-first; contact via repository)"
IDENTITY_MARKERS = (
    "hotararile autoritatii deliberative",
    "actele administrative adoptate",
    "consiliul judetean valcea",
)
PLACEHOLDER_TERMS = (
    "access denied", "captcha", "checking your browser", "cloudflare",
    "enable javascript", "please wait", "service unavailable",
    "temporarily unavailable", "verify you are human",
)
DATE_RE = re.compile(r"\b(\d{2})[.](\d{2})[.](20\d{2})\b")
NUMBER_RE = re.compile(r"^\s*(\d{1,4})\s*$")


@dataclass(frozen=True)
class CountyCouncilAdoptedDecisionReference:
    kind: str
    decision_number: int
    decision_date: str
    title: str
    topic: str
    attached_file_label_present: bool
    canonical_index_url: str
    evidence_sha256: str


@dataclass(frozen=True)
class CJValceaAdoptedDecisionState:
    source_id: str
    taxonomy_version: str
    source_name: str
    source_tier: str
    source_url: str
    source_payload_sha256: str
    as_of_date: str
    state: str
    hold_reason: Optional[str]
    references: tuple[CountyCouncilAdoptedDecisionReference, ...]
    reference_scope: str = "FIRST_PARTY_ADOPTED_DECISION_INDEX_REFERENCE_ONLY"
    attached_file_follow_allowed: bool = False
    attached_document_body_fetch_allowed: bool = False
    person_or_personal_data_extraction_allowed: bool = False
    legal_effect_inference_allowed: bool = False
    current_validity_inference_allowed: bool = False
    amendment_status_inference_allowed: bool = False
    repeal_status_inference_allowed: bool = False
    implementation_status_inference_allowed: bool = False
    monetary_value_extraction_allowed: bool = False
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
        raise ValueError(f"off-surface CJ Vâlcea adopted-decision source refused: {url}")
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


class DecisionTableParser(html.parser.HTMLParser):
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


def parse_decision_number(value: str) -> Optional[int]:
    match = NUMBER_RE.match(clean(value))
    if not match:
        return None
    number = int(match.group(1))
    return number if number > 0 else None


def classify_topic(title: str) -> str:
    value = fold(title)
    if any(term in value for term in ("spital", "sanatate", "medical", "neonatolog", "psihiatr")):
        return "HEALTH"
    if any(term in value for term in ("asistenta sociala", "serviciul social", "varstnic", "dgaspc", "dezinstitutional")):
        return "SOCIAL_SERVICES"
    if any(term in value for term in ("buget", "venituri si cheltuieli", "excedent", "financ", "fondul salari")):
        return "BUDGET_FINANCE"
    if any(term in value for term in ("organigrama", "stat de functii", "comisie", "administrator", "consiliul de administratie", "regulament de organizare", "numirea unui membru")):
        return "GOVERNANCE_ORGANIZATION"
    if any(term in value for term in ("drum", "reabilit", "moderniz", "investiti", "documentatie tehnico-economica", "studiu de fezabilitate")):
        return "INFRASTRUCTURE_INVESTMENT"
    if any(term in value for term in ("teatru", "muze", "bibliotec", "cultur")):
        return "CULTURE"
    if any(term in value for term in ("evidenta persoanelor", "servicii publice locale", "paza valcea")):
        return "PUBLIC_SERVICES"
    if any(term in value for term in ("domeniul public", "domeniul privat", "inventar", "concesiune", "administrare a unui bun")):
        return "PUBLIC_ASSETS"
    return "GENERAL_COUNCIL_DECISION"


def _hold(source_url: str, digest: str, as_of: date, reason: str) -> CJValceaAdoptedDecisionState:
    return CJValceaAdoptedDecisionState(
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
) -> CJValceaAdoptedDecisionState:
    canonical = validate_source_url(source_url)
    digest = hashlib.sha256(payload).hexdigest()
    parser = DecisionTableParser()
    try:
        parser.feed(html_text)
    except Exception as exc:
        return _hold(canonical, digest, as_of, f"html_parse_error:{type(exc).__name__}")

    visible = parser.visible_text()
    folded_visible = fold(visible)
    if any(term in folded_visible[:10000] for term in PLACEHOLDER_TERMS):
        return _hold(canonical, digest, as_of, "placeholder_or_challenge_page")
    if not all(marker in folded_visible for marker in IDENTITY_MARKERS):
        return _hold(canonical, digest, as_of, "cj_valcea_adopted_decision_identity_missing")
    if str(as_of.year) not in visible:
        return _hold(canonical, digest, as_of, "current_year_archive_missing")

    refs: list[CountyCouncilAdoptedDecisionReference] = []
    seen: set[tuple[int, str, str]] = set()
    for cells in parser.rows:
        if len(cells) < 3:
            continue
        decision_number = parse_decision_number(cells[0])
        decision_date = parse_date_label(cells[1])
        title = clean(cells[2])
        folded_title = fold(title)
        if decision_number is None or not decision_date:
            continue
        if not decision_date.startswith(f"{as_of.year}-"):
            continue
        if not folded_title.startswith("hotarare"):
            continue
        key = (decision_number, decision_date, title)
        if key in seen:
            continue
        seen.add(key)
        attached_file_label_present = len(cells) >= 4 and "vizualizare" in fold(cells[3])
        topic = classify_topic(title)
        evidence = (
            "kind=COUNTY_COUNCIL_ADOPTED_DECISION_REFERENCE|"
            f"decision_number={decision_number}|decision_date={decision_date}|"
            f"topic={topic}|title={title}|attached_file_label_present={attached_file_label_present}|"
            f"index={canonical}"
        )
        refs.append(
            CountyCouncilAdoptedDecisionReference(
                kind="COUNTY_COUNCIL_ADOPTED_DECISION_REFERENCE",
                decision_number=decision_number,
                decision_date=decision_date,
                title=title,
                topic=topic,
                attached_file_label_present=attached_file_label_present,
                canonical_index_url=canonical,
                evidence_sha256=hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
            )
        )

    refs.sort(key=lambda item: (item.decision_date, item.decision_number, item.title), reverse=True)
    if not refs:
        return _hold(canonical, digest, as_of, "current_year_adopted_decision_references_missing")

    return CJValceaAdoptedDecisionState(
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


def run_live(*, as_of: date, source_url: str = SOURCE_URL) -> CJValceaAdoptedDecisionState:
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
    identity: str = "Hotărârile Autorității Deliberative — Consiliul Județean Vâlcea — Actele administrative adoptate",
    year: str = "2026",
    rows: str = "",
) -> str:
    default_rows = """
      <tr><th>NR. HCJ</th><th>DATA HCJ</th><th>DENUMIRE HCJ</th><th>FIȘIER</th></tr>
      <tr><td>168</td><td>26.08.2026</td><td>Hotărâre privind numirea unui membru provizoriu în Consiliul de Administrație al Regiei Autonome Județene de Drumuri și Poduri Vâlcea</td><td><a href='/file-168.pdf'>Vizualizare</a></td></tr>
      <tr><td>167</td><td>26.08.2026</td><td>Hotărâre privind aprobarea proiectului Centrul de Sănătate Mintală și pentru Prevenirea Adicțiilor Vâlcea și a cheltuielilor legate de implementare</td><td>Vizualizare</td></tr>
      <tr><td>166</td><td>26.08.2025</td><td>Hotărâre privind un proiect vechi</td><td>Vizualizare</td></tr>
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
    assert state.references[0].decision_number == 168
    assert state.references[0].decision_date == "2026-08-26"
    assert state.references[0].topic == "GOVERNANCE_ORGANIZATION"
    assert state.references[0].attached_file_label_present is True
    assert state.references[1].decision_number == 167
    assert state.references[1].topic == "HEALTH"
    assert state.attached_file_follow_allowed is False
    assert state.attached_document_body_fetch_allowed is False
    assert state.legal_effect_inference_allowed is False
    assert state.current_validity_inference_allowed is False
    assert state.amendment_status_inference_allowed is False
    assert state.repeal_status_inference_allowed is False
    assert state.implementation_status_inference_allowed is False
    assert state.public_projection_allowed is False

    duplicate_rows = """
      <tr><td>167</td><td>26.08.2026</td><td>Hotărâre privind aprobarea unui proiect de sănătate</td><td>Vizualizare</td></tr>
      <tr><td>167</td><td>26.08.2026</td><td>Hotărâre privind aprobarea unui proiect de sănătate</td><td>Vizualizare</td></tr>
    """
    deduped = _synthetic(rows=duplicate_rows)
    deduped_state = build_state(deduped, deduped.encode(), as_of=as_of)
    assert len(deduped_state.references) == 1

    missing_identity = _synthetic(identity="Arhivă publică Consiliul Județean Vâlcea")
    assert (
        build_state(missing_identity, missing_identity.encode(), as_of=as_of).hold_reason
        == "cj_valcea_adopted_decision_identity_missing"
    )

    rows_2025 = "<tr><td>1</td><td>23.01.2025</td><td>Hotărâre privind un buget</td><td>Vizualizare</td></tr>"
    missing_year = _synthetic(year="2025", rows=rows_2025)
    assert (
        build_state(missing_year, missing_year.encode(), as_of=as_of).hold_reason
        == "current_year_archive_missing"
    )

    no_rows = _synthetic(
        rows="<tr><td>168</td><td>26.08.2026</td><td>Comunicat general al Consiliului Județean Vâlcea</td><td>Vizualizare</td></tr>"
    )
    assert (
        build_state(no_rows, no_rows.encode(), as_of=as_of).hold_reason
        == "current_year_adopted_decision_references_missing"
    )

    challenge = "<html><body>Hotărârile Autorității Deliberative Consiliul Județean Vâlcea Actele administrative adoptate 2026 verify you are human</body></html>"
    assert (
        build_state(challenge, challenge.encode(), as_of=as_of).hold_reason
        == "placeholder_or_challenge_page"
    )

    for bad in (
        "http://cjvalcea.ro/monitorul-oficial-local/hotararile-autoritatii-deliberative/2026-hotararile-autoritatii-deliberative/",
        "https://www.cjvalcea.ro/monitorul-oficial-local/hotararile-autoritatii-deliberative/2026-hotararile-autoritatii-deliberative/",
        "https://cjvalcea.ro/monitorul-oficial-local/hotararile-autoritatii-deliberative/2025-hotararile-autoritatii-deliberative/",
        "https://cjvalcea.ro/monitorul-oficial-local/hotararile-autoritatii-deliberative/2026-hotararile-autoritatii-deliberative/?x=1",
        "https://example.org/monitorul-oficial-local/hotararile-autoritatii-deliberative/2026-hotararile-autoritatii-deliberative/",
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
