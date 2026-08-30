#!/usr/bin/env python3
"""Evidence-first SAJ Vâlcea workforce/reference adapter for Posturi.gov.ro.

Consumes only Romanian Government public-job pages that explicitly identify
Serviciul de Ambulanță Județean Vâlcea. Emits bounded newsroom references for
recruitment notices and explicitly named station/substation structures.

This adapter does not infer current ambulance availability, response capacity,
staffing levels, dispatch status, crew location, patient/caller facts, medical
advice, or employment outcomes. It does not follow/download linked documents,
persist state, promote facts, invoke Writer, publish, or infer photo rights.
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
from urllib.parse import unquote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

SOURCE_ID = "signal-posturi-gov-ro-saj-valcea-workforce"
TAXONOMY_VERSION = "2026-08-30.1"
SOURCE_NAME = "Posturi.gov.ro — Serviciul de Ambulanță Județean Vâlcea"
SOURCE_TIER = "T1_GOVERNMENT"
CANONICAL_HOST = "posturi.gov.ro"
ALLOWED_HOSTS = {"posturi.gov.ro", "www.posturi.gov.ro"}
ALLOWED_PATH_PREFIX = "/joburi/"
MAX_RESPONSE_BYTES = 2_000_000
TIMEOUT_SECONDS = 15
USER_AGENT = "CIVORA-ValceaClar-SAJ/1.0 (+evidence-first; contact via repository)"

IDENTITY_TERMS = (
    "serviciul de ambulanta judetean valcea",
    "serviciul de ambulanta judetean valcea valcea",
)
RECRUITMENT_TERMS = ("organizeaza concurs", "post vacant", "posturi vacante")
RESULT_OR_CANDIDATE_TERMS = (
    "cod candidat",
    "lista candidatilor",
    "lista candidati",
    "rezultatele selectiei dosarelor",
    "rezultatul selectiei dosarelor",
    "rezultatul probei scrise",
    "rezultatul final al concursului",
)
PLACEHOLDER_TERMS = (
    "enable javascript",
    "access denied",
    "captcha",
    "service unavailable",
    "temporarily unavailable",
    "cloudflare",
    "verify you are human",
)
DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
DATE_RO_RE = re.compile(r"\b([0-3]?\d)[./-]([01]?\d)[./-](20\d{2})\b")
PUBLISHED_RE = re.compile(r"\bpublicat\s+pe\s+(20\d{2}-\d{2}-\d{2})\b", re.I)
DEADLINE_RE = re.compile(r"\btermen\s+(20\d{2}-\d{2}-\d{2})\b", re.I)
STRUCTURE_PATTERNS = (
    ("CENTRAL_STATION_RM_VALCEA", re.compile(r"\bsta(?:t|ț)(?:ia|ie)\s+central[aă]\s+rm\.?\s*v[âa]lcea\b", re.I)),
    ("SUBSTATION_HOREZU", re.compile(r"\bsubsta(?:t|ț)(?:ia|ie)\s+(?:de\s+)?ambulan(?:t|ț)[aă]\s+horezu\b", re.I)),
    ("SUBSTATION_DRAGASANI", re.compile(r"\bsubsta(?:t|ț)(?:ia|ie)\s+(?:de\s+)?ambulan(?:t|ț)[aă]\s+dr[aă]g[aă][sș]ani\b", re.I)),
    ("SUBSTATION_BREZOI", re.compile(r"\bsubsta(?:t|ț)(?:ia|ie)\s+(?:de\s+)?ambulan(?:t|ț)[aă]\s+brezoi\b", re.I)),
    (
        "EMERGENCY_ASSISTED_TRANSPORT_COMPARTMENT",
        re.compile(
            r"\bcompartiment(?:ul)?\s+de\s+asisten(?:t|ț)[aă]\s+medical[aă]\s+de\s+urgen(?:t|ț)[aă]\s+[sș]i\s+transport\s+sanitar\s+asistat\b",
            re.I,
        ),
    ),
)
WEBSITE_RE = re.compile(r"\b(?:https?://)?(?:www\.)?(ambulantavalcea\.ro)(?:/[\w./?=&%-]*)?\b", re.I)


@dataclass(frozen=True)
class SAJWorkforceSignal:
    source_id: str
    taxonomy_version: str
    signal_class: str
    source_tier: str
    source_name: str
    source_url: str
    payload_sha256: str
    evidence_excerpt: str
    hold_reason: Optional[str]
    title: Optional[str] = None
    publication_date: Optional[str] = None
    application_deadline: Optional[str] = None
    explicit_dates: tuple[str, ...] = ()
    structures: tuple[str, ...] = ()
    institution_website_reference: Optional[str] = None
    reference_scope: str = "SAJ_VALCEA_WORKFORCE_REFERENCE"
    publication_authority: str = "NONE"
    current_ambulance_availability_claim_allowed: bool = False
    response_capacity_inference_allowed: bool = False
    staffing_level_inference_allowed: bool = False
    dispatch_status_inference_allowed: bool = False
    crew_location_inference_allowed: bool = False
    patient_or_caller_fact_extraction_allowed: bool = False
    applicant_or_employee_identity_extraction_allowed: bool = False
    employment_outcome_inference_allowed: bool = False
    medical_advice_allowed: bool = False
    linked_document_fetch_allowed: bool = False
    inferred_photo_rights_allowed: bool = False
    persistence_allowed: bool = False
    fact_kernel_promotion_allowed: bool = False
    writer_allowed: bool = False
    public_projection_allowed: bool = False


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", clean(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _path(value: str) -> str:
    path = re.sub(r"/+", "/", unquote(value or "/"))
    if not path.startswith("/"):
        path = "/" + path
    return path


def validate_source_url(url: str) -> str:
    parsed = urlsplit(clean(url))
    host = (parsed.hostname or "").casefold()
    path = _path(parsed.path)
    if (
        parsed.scheme.casefold() != "https"
        or host not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not path.startswith(ALLOWED_PATH_PREFIX)
        or path == ALLOWED_PATH_PREFIX
    ):
        raise ValueError(f"off-surface source refused: {url}")
    return urlunsplit(("https", CANONICAL_HOST, path, "", ""))


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise ValueError(f"redirect refused: {newurl}")


def fetch_html(url: str, timeout: float = TIMEOUT_SECONDS) -> tuple[str, str, bytes]:
    canonical = validate_source_url(url)
    opener = build_opener(NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(canonical, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
    with opener.open(request, timeout=timeout) as response:
        final_url = validate_source_url(response.geturl())
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds size cap")
        charset = response.headers.get_content_charset() or "utf-8"
    return final_url, body.decode(charset, errors="replace"), body


class VisibleTextParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}
    BREAKS = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "article", "section"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts: list[str] = []
        self.h1_depth = 0
        self.h1_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag in self.BREAKS:
            self.parts.append("\n")
        if tag == "h1":
            self.h1_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.SKIP and self.skip:
            self.skip -= 1
            return
        if self.skip:
            return
        if tag == "h1" and self.h1_depth:
            self.h1_depth -= 1
        if tag in self.BREAKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        value = clean(data)
        if not value:
            return
        self.parts.append(value)
        if self.h1_depth:
            self.h1_parts.append(value)

    def text(self) -> str:
        value = " ".join(self.parts)
        value = re.sub(r"[ \t\r\f\v]+", " ", value)
        value = re.sub(r"\s*\n\s*", "\n", value)
        return value.strip()

    def title(self) -> Optional[str]:
        value = clean(" ".join(self.h1_parts))
        return value or None


def parse_html(html_text: str) -> tuple[str, Optional[str]]:
    parser = VisibleTextParser()
    parser.feed(html_text)
    return parser.text(), parser.title()


def identity_present(text: str) -> bool:
    value = fold(text)
    return any(term in value for term in IDENTITY_TERMS)


def placeholder(text: str) -> bool:
    value = fold(text)[:5000]
    return any(term in value for term in PLACEHOLDER_TERMS)


def normalize_iso_date(value: str) -> Optional[str]:
    match = DATE_RE.fullmatch(clean(value))
    if not match:
        return None
    year, month, day = map(int, match.groups())
    if year < 2020 or not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def explicit_dates(text: str) -> tuple[str, ...]:
    values: set[str] = set()
    for year, month, day in DATE_RE.findall(text):
        value = normalize_iso_date(f"{year}-{month}-{day}")
        if value:
            values.add(value)
    for day, month, year in DATE_RO_RE.findall(text):
        d, m, y = int(day), int(month), int(year)
        if 1 <= d <= 31 and 1 <= m <= 12:
            values.add(f"{y:04d}-{m:02d}-{d:02d}")
    return tuple(sorted(values))


def extract_structures(text: str) -> tuple[str, ...]:
    return tuple(name for name, pattern in STRUCTURE_PATTERNS if pattern.search(text))


def institution_website_reference(text: str) -> Optional[str]:
    return "https://ambulantavalcea.ro/" if WEBSITE_RE.search(text) else None


def classify(text: str) -> tuple[str, Optional[str]]:
    value = fold(text)
    if any(term in value for term in RESULT_OR_CANDIDATE_TERMS):
        return "HOLD_SAJ_CANDIDATE_OR_RESULT_MATERIAL", "candidate/result material is outside bounded workforce-reference lane"
    if not any(term in value for term in RECRUITMENT_TERMS):
        return "HOLD_UNCLASSIFIED_SAJ_REFERENCE", "no explicit SAJ recruitment notice markers"
    return "SAJ_PUBLIC_RECRUITMENT_NOTICE_REFERENCE", None


def extract_signal(source_url: str, html_text: str, payload: bytes) -> SAJWorkforceSignal:
    canonical = validate_source_url(source_url)
    text, title = parse_html(html_text)
    if placeholder(text):
        raise ValueError("placeholder/challenge page refused")
    if not identity_present(text):
        raise ValueError("SAJ Vâlcea source identity not present")

    signal_class, hold_reason = classify(text)
    held = signal_class.startswith("HOLD_")
    dates = explicit_dates(text)
    pub_match = PUBLISHED_RE.search(text)
    deadline_match = DEADLINE_RE.search(text)
    publication_date = normalize_iso_date(pub_match.group(1)) if pub_match else None
    application_deadline = normalize_iso_date(deadline_match.group(1)) if deadline_match else None
    structures = extract_structures(text)
    website = institution_website_reference(text)

    if held:
        return SAJWorkforceSignal(
            source_id=SOURCE_ID,
            taxonomy_version=TAXONOMY_VERSION,
            signal_class=signal_class,
            source_tier=SOURCE_TIER,
            source_name=SOURCE_NAME,
            source_url=canonical,
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            evidence_excerpt="HELD_CANDIDATE_OR_UNCLASSIFIED_SAJ_REFERENCE",
            hold_reason=hold_reason,
        )

    evidence = clean(text)[:650]
    return SAJWorkforceSignal(
        source_id=SOURCE_ID,
        taxonomy_version=TAXONOMY_VERSION,
        signal_class=signal_class,
        source_tier=SOURCE_TIER,
        source_name=SOURCE_NAME,
        source_url=canonical,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        evidence_excerpt=evidence,
        hold_reason=None,
        title=title,
        publication_date=publication_date,
        application_deadline=application_deadline,
        explicit_dates=dates,
        structures=structures,
        institution_website_reference=website,
    )


def validate_boundaries(signal: SAJWorkforceSignal) -> None:
    forbidden_true = (
        "current_ambulance_availability_claim_allowed",
        "response_capacity_inference_allowed",
        "staffing_level_inference_allowed",
        "dispatch_status_inference_allowed",
        "crew_location_inference_allowed",
        "patient_or_caller_fact_extraction_allowed",
        "applicant_or_employee_identity_extraction_allowed",
        "employment_outcome_inference_allowed",
        "medical_advice_allowed",
        "linked_document_fetch_allowed",
        "inferred_photo_rights_allowed",
        "persistence_allowed",
        "fact_kernel_promotion_allowed",
        "writer_allowed",
        "public_projection_allowed",
    )
    for field in forbidden_true:
        if getattr(signal, field):
            raise AssertionError(f"boundary drift: {field}=true")
    if signal.publication_authority != "NONE":
        raise AssertionError("publication authority drift")
    if signal.signal_class.startswith("HOLD_"):
        if (
            signal.title
            or signal.publication_date
            or signal.application_deadline
            or signal.explicit_dates
            or signal.structures
            or signal.institution_website_reference
        ):
            raise AssertionError("held signal leaks candidate/result-adjacent metadata")
        if signal.evidence_excerpt != "HELD_CANDIDATE_OR_UNCLASSIFIED_SAJ_REFERENCE":
            raise AssertionError("held signal leaks raw evidence")


def run_self_test() -> None:
    sample = """
    <html><body>
      <h1>Șofer autosanitară II (3 posturi)</h1>
      <p>Publicat pe 2026-08-27 · Termen 2026-09-25</p>
      <p>Serviciul de Ambulanță Județean Vâlcea, cu sediul în Rm. Vâlcea,
      organizează concurs pentru ocuparea unor posturi vacante.</p>
      <p>COMPARTIMENT/STRUCTURĂ: Stația centrală Rm. Vâlcea – Compartiment de
      asistență medicală de urgență și transport sanitar asistat</p>
      <p>Informații suplimentare se pot obține de pe website: ambulantavalcea.ro.</p>
    </body></html>
    """
    url = "https://posturi.gov.ro/joburi/sofer-autosanitara-ii-3-posturi/"
    signal = extract_signal(url, sample, sample.encode())
    assert signal.signal_class == "SAJ_PUBLIC_RECRUITMENT_NOTICE_REFERENCE"
    assert signal.publication_date == "2026-08-27"
    assert signal.application_deadline == "2026-09-25"
    assert "CENTRAL_STATION_RM_VALCEA" in signal.structures
    assert "EMERGENCY_ASSISTED_TRANSPORT_COMPARTMENT" in signal.structures
    assert signal.institution_website_reference == "https://ambulantavalcea.ro/"
    validate_boundaries(signal)

    result_sample = """
    <html><body><h1>Rezultat concurs</h1>
    <p>Serviciul de Ambulanță Județean Vâlcea</p>
    <p>Rezultatul final al concursului. Cod candidat 1234.</p>
    </body></html>
    """
    held = extract_signal("https://posturi.gov.ro/joburi/rezultat-saj-valcea/", result_sample, result_sample.encode())
    assert held.signal_class == "HOLD_SAJ_CANDIDATE_OR_RESULT_MATERIAL"
    validate_boundaries(held)

    try:
        validate_source_url("https://posturi.gov.ro/oras/ramnicu-valcea/")
    except ValueError:
        pass
    else:
        raise AssertionError("non-job index accepted")
    try:
        validate_source_url("https://evil.example/joburi/saj/")
    except ValueError:
        pass
    else:
        raise AssertionError("off-host source accepted")
    print("SAJ Vâlcea workforce-reference self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        run_self_test()
        return 0
    if not args.url:
        parser.error("--url is required unless --self-test")
    final_url, html_text, payload = fetch_html(args.url)
    signal = extract_signal(final_url, html_text, payload)
    validate_boundaries(signal)
    print(json.dumps(asdict(signal), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
