#!/usr/bin/env python3
"""Evidence-first Casa Corpului Didactic Vâlcea public professional-development adapter.

The official CCD Vâlcea homepage exposes useful service windows, training notices,
methodical-event references and professional-development material. This adapter is
deliberately bounded to the official homepage and only emits review-required source
signals from page-visible text/links.

Source-only by design: no persistence, Fact Kernel promotion, Writer/public
projection, deployment changes, inferred freshness/current status or photo rights.
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
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

SOURCE_ID = "signal-ccd-valcea-professional-development"
TAXONOMY_VERSION = "2026-08-30.1"
SOURCE_NAME = "Casa Corpului Didactic Vâlcea"
SOURCE_TIER = "T1"
CANONICAL_HOST = "ccdvl.ro"
ALLOWED_HOSTS = {"ccdvl.ro", "www.ccdvl.ro"}
ALLOWED_PATHS = {"/"}
MAX_RESPONSE_BYTES = 2_500_000
TIMEOUT_SECONDS = 15
USER_AGENT = "CIVORA-ValceaClar-CCDValcea/1.0 (+evidence-first; contact via repository)"
MAX_SIGNALS = 100

PLACEHOLDER_TERMS = (
    "enable javascript",
    "access denied",
    "captcha",
    "service unavailable",
    "temporarily unavailable",
    "cloudflare",
    "verify you are human",
)

IDENTITY_TERMS = (
    "casa corpului didactic valcea",
    "ccd valcea",
)

SENSITIVE_TERMS = (
    "rezultate selectie",
    "rezultate selecție",
    "rezultate finale",
    "lista candidat",
    "lista candida",
    "punctaj",
    "contestatii",
    "contestații",
)

SERVICE_WINDOW_TERMS = (
    "ridice adeverintele",
    "ridice adeverințele",
    "adeverintele aferente",
    "adeverințele aferente",
    "program:",
    "intervalul orar",
)

TRAINING_NEEDS_TERMS = (
    "chestionar",
    "nevoilor de formare",
    "nevoi de formare",
    "oferta de formare continua",
    "oferta de formare continuă",
)

TRAINING_SCHEDULE_TERMS = (
    "graficul de desfasurare",
    "graficul de desfășurare",
    "programele de formare",
    "activitatilor metodice",
    "activităților metodice",
)

METHODICAL_EVENT_TERMS = (
    "simpozion",
    "atelier",
    "masa rotunda",
    "masă rotundă",
    "conferinta",
    "conferință",
    "workshop",
    "activitate metodica",
    "activitate metodică",
)

PROFESSIONAL_DEVELOPMENT_TERMS = (
    "formare",
    "curs",
    "cadre didactice",
    "profesori",
    "metodic",
    "metodică",
    "mentor",
    "coaching",
)

DATE_NUMERIC_RE = re.compile(r"\b([0-3]?\d)[./-]([01]?\d)[./-](20\d{2})\b")
YEAR_RANGE_RE = re.compile(r"\b(20\d{2})\s*[-–—/]\s*(20\d{2})\b")
CLOCK_RE = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b")
DAY_RANGE_MONTH_RE = re.compile(
    r"\b([0-3]?\d)\s*[-–—]\s*([0-3]?\d)\s+"
    r"(ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)\s+"
    r"(20\d{2})\b",
    re.IGNORECASE,
)
CROSS_MONTH_RANGE_RE = re.compile(
    r"\b([0-3]?\d)\s+"
    r"(ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)"
    r"\s*[-–—]\s*([0-3]?\d)\s+"
    r"(ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)\s+"
    r"(20\d{2})\b",
    re.IGNORECASE,
)
DAY_MONTH_RE = re.compile(
    r"\b([0-3]?\d)\s+"
    r"(ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)\s+"
    r"(20\d{2})\b",
    re.IGNORECASE,
)
MONTHS = {
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


@dataclass(frozen=True)
class CCDSignal:
    source_id: str
    taxonomy_version: str
    signal_class: str
    source_tier: str
    source_name: str
    source_url: str
    payload_sha256: str
    evidence_excerpt: str
    hold_reason: Optional[str]
    label: Optional[str] = None
    reference_url: Optional[str] = None
    reference_url_sha256: Optional[str] = None
    school_year: Optional[str] = None
    explicit_start_date: Optional[str] = None
    explicit_end_date: Optional[str] = None
    explicit_time: Optional[str] = None
    date_semantics: Optional[str] = None
    reference_scope: str = "EDUCATION_PROFESSIONAL_DEVELOPMENT_REFERENCE"
    publication_authority: str = "NONE"
    current_status_claim_allowed: bool = False
    freshness_claim_allowed: bool = False
    person_fact_extraction_allowed: bool = False
    sensitive_result_projection_allowed: bool = False
    external_form_submission_allowed: bool = False
    document_body_fetch_allowed: bool = False
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


def canonical_source_url(url: str) -> str:
    parsed = urlsplit(clean(url))
    host = (parsed.hostname or "").casefold()
    path = re.sub(r"/+", "/", parsed.path or "/")
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    if (
        parsed.scheme.casefold() != "https"
        or host not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or path not in ALLOWED_PATHS
    ):
        raise ValueError(f"off-surface source refused: {url}")
    return urlunsplit(("https", CANONICAL_HOST, "/", "", ""))


def normalize_reference_url(value: str, base_url: str) -> Optional[str]:
    text = clean(value)
    if not text:
        return None
    parsed = urlsplit(urljoin(base_url, text))
    host = (parsed.hostname or "").casefold()
    if parsed.scheme.casefold() != "https" or host not in ALLOWED_HOSTS or parsed.username or parsed.password:
        return None
    path = re.sub(r"/+", "/", parsed.path or "/")
    return urlunsplit(("https", CANONICAL_HOST, path, parsed.query, ""))


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise ValueError(f"redirect refused: {newurl}")


def fetch_html(url: str, timeout: float = TIMEOUT_SECONDS) -> tuple[str, str, bytes]:
    canonical = canonical_source_url(url)
    context = ssl.create_default_context()
    opener = build_opener(NoRedirects(), HTTPSHandler(context=context))
    request = Request(canonical, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
    with opener.open(request, timeout=timeout) as response:
        final_url = canonical_source_url(response.geturl())
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds size cap")
        charset = response.headers.get_content_charset() or "utf-8"
    return final_url, body.decode(charset, errors="replace"), body


class HomepageParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}
    BREAKS = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "article", "section"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts: list[str] = []
        self.anchor_href: Optional[str] = None
        self.anchor_parts: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag in self.BREAKS:
            self.parts.append("\n")
        if tag == "a" and self.anchor_href is None:
            self.anchor_href = clean(dict(attrs).get("href") or "")
            self.anchor_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.SKIP and self.skip:
            self.skip -= 1
            return
        if self.skip:
            return
        if tag == "a" and self.anchor_href is not None:
            self.links.append((self.anchor_href, clean(" ".join(self.anchor_parts))))
            self.anchor_href = None
            self.anchor_parts = []
        if tag in self.BREAKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        value = clean(data)
        if not value:
            return
        self.parts.append(value)
        if self.anchor_href is not None:
            self.anchor_parts.append(value)

    def text(self) -> str:
        value = " ".join(self.parts)
        value = re.sub(r"[ \t\r\f\v]+", " ", value)
        value = re.sub(r"\s*\n\s*", "\n", value)
        return value.strip()


def parse_document(html_text: str) -> tuple[str, list[tuple[str, str]]]:
    parser = HomepageParser()
    parser.feed(html_text)
    return parser.text(), parser.links


def placeholder(text: str) -> bool:
    value = fold(text)[:5000]
    return any(term in value for term in PLACEHOLDER_TERMS)


def identity_present(text: str) -> bool:
    value = fold(text)[:12000]
    return any(fold(term) in value for term in IDENTITY_TERMS)


def classify(text: str) -> tuple[str, Optional[str]]:
    value = fold(text)
    if any(fold(term) in value for term in SENSITIVE_TERMS):
        return "HOLD_SENSITIVE_PROFESSIONAL_SELECTION_REFERENCE", "sensitive selection/result reference"
    if all(fold(term) in value for term in ("adeverin", "ridic")) or any(
        fold(term) in value for term in SERVICE_WINDOW_TERMS
    ):
        return "PROFESSIONAL_DEVELOPMENT_SERVICE_WINDOW", None
    if any(fold(term) in value for term in TRAINING_NEEDS_TERMS):
        return "TRAINING_NEEDS_SURVEY_NOTICE", None
    if any(fold(term) in value for term in TRAINING_SCHEDULE_TERMS):
        return "TRAINING_AND_METHODICAL_SCHEDULE_REFERENCE", None
    if any(fold(term) in value for term in METHODICAL_EVENT_TERMS):
        return "METHODICAL_EVENT_REFERENCE", None
    if any(fold(term) in value for term in PROFESSIONAL_DEVELOPMENT_TERMS):
        return "PROFESSIONAL_DEVELOPMENT_REFERENCE", None
    return "HOLD_UNCLASSIFIED_CCD_REFERENCE", "no bounded taxonomy match"


def school_year(text: str) -> Optional[str]:
    matches = {f"{a}-{b}" for a, b in YEAR_RANGE_RE.findall(text)}
    return next(iter(matches)) if len(matches) == 1 else None


def explicit_dates(text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    folded = fold(text)
    cross_ranges = list(CROSS_MONTH_RANGE_RE.finditer(folded))
    if len(cross_ranges) == 1:
        m = cross_ranges[0]
        start_day, start_month = int(m.group(1)), MONTHS[m.group(2)]
        end_day, end_month, year = int(m.group(3)), MONTHS[m.group(4)], int(m.group(5))
        if 1 <= start_day <= 31 and 1 <= end_day <= 31 and start_month <= end_month:
            return (
                f"{year:04d}-{start_month:02d}-{start_day:02d}",
                f"{year:04d}-{end_month:02d}-{end_day:02d}",
                "EXPLICIT_TEXTUAL_DATE_RANGE",
            )
    ranges = list(DAY_RANGE_MONTH_RE.finditer(folded))
    if len(ranges) == 1:
        m = ranges[0]
        start_day, end_day = int(m.group(1)), int(m.group(2))
        month, year = MONTHS[m.group(3)], int(m.group(4))
        if 1 <= start_day <= end_day <= 31:
            return (
                f"{year:04d}-{month:02d}-{start_day:02d}",
                f"{year:04d}-{month:02d}-{end_day:02d}",
                "EXPLICIT_TEXTUAL_DATE_RANGE",
            )
    textual = set()
    for m in DAY_MONTH_RE.finditer(fold(text)):
        day, month, year = int(m.group(1)), MONTHS[m.group(2)], int(m.group(3))
        if 1 <= day <= 31:
            textual.add(f"{year:04d}-{month:02d}-{day:02d}")
    numeric = set()
    for day, month, year in DATE_NUMERIC_RE.findall(text):
        d, m, y = int(day), int(month), int(year)
        if 1 <= d <= 31 and 1 <= m <= 12:
            numeric.add(f"{y:04d}-{m:02d}-{d:02d}")
    values = textual | numeric
    if len(values) == 1:
        value = next(iter(values))
        return value, value, "EXPLICIT_SINGLE_DATE"
    return None, None, None


def explicit_time(text: str) -> Optional[str]:
    values = {f"{int(h):02d}:{int(m):02d}" for h, m in CLOCK_RE.findall(text)}
    return next(iter(values)) if len(values) == 1 else None


def evidence_chunks(text: str, links: list[tuple[str, str]]) -> list[tuple[str, Optional[str]]]:
    chunks: list[tuple[str, Optional[str]]] = []
    seen: set[str] = set()
    lines = [clean(line) for line in text.splitlines() if clean(line)]
    for line in lines:
        value = fold(line)
        if not any(
            fold(term) in value
            for term in (
                *SERVICE_WINDOW_TERMS,
                *TRAINING_NEEDS_TERMS,
                *TRAINING_SCHEDULE_TERMS,
                *METHODICAL_EVENT_TERMS,
                *PROFESSIONAL_DEVELOPMENT_TERMS,
                *SENSITIVE_TERMS,
            )
        ):
            continue
        key = hashlib.sha256(value.encode("utf-8")).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        chunks.append((line[:1200], None))
        if len(chunks) >= MAX_SIGNALS:
            break

    for href, label in links:
        label_clean = clean(label)
        value = fold(label_clean)
        if not label_clean or not any(
            fold(term) in value
            for term in (
                *TRAINING_NEEDS_TERMS,
                *TRAINING_SCHEDULE_TERMS,
                *METHODICAL_EVENT_TERMS,
                *PROFESSIONAL_DEVELOPMENT_TERMS,
                *SENSITIVE_TERMS,
                "adeverinte",
                "adeverințe",
            )
        ):
            continue
        key = hashlib.sha256((value + "\0" + href).encode("utf-8")).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        chunks.append((label_clean[:1200], href))
        if len(chunks) >= MAX_SIGNALS:
            break
    return chunks


def build_signals(page_url: str, html_text: str, body: bytes) -> list[CCDSignal]:
    canonical = canonical_source_url(page_url)
    text, links = parse_document(html_text)
    if placeholder(text):
        raise ValueError("placeholder/challenge page refused")
    if not identity_present(text):
        raise ValueError("CCD Vâlcea source identity not present")

    payload_sha = hashlib.sha256(body).hexdigest()
    signals: list[CCDSignal] = []
    for excerpt, raw_href in evidence_chunks(text, links):
        signal_class, hold = classify(excerpt)
        ref_url = normalize_reference_url(raw_href, canonical) if raw_href else None
        if raw_href and not ref_url:
            hold = hold or "off-host or non-HTTPS reference withheld"
        start, end, semantics = explicit_dates(excerpt)
        ref_hash = hashlib.sha256(clean(raw_href).encode("utf-8")).hexdigest() if raw_href else None
        public_ref = None if signal_class.startswith("HOLD_SENSITIVE") else ref_url
        public_label = None if signal_class.startswith("HOLD_SENSITIVE") else excerpt[:300]

        signals.append(
            CCDSignal(
                source_id=SOURCE_ID,
                taxonomy_version=TAXONOMY_VERSION,
                signal_class=signal_class,
                source_tier=SOURCE_TIER,
                source_name=SOURCE_NAME,
                source_url=canonical,
                payload_sha256=payload_sha,
                evidence_excerpt=excerpt[:900] if not signal_class.startswith("HOLD_SENSITIVE") else "[WITHHELD_SENSITIVE_REFERENCE]",
                hold_reason=hold,
                label=public_label,
                reference_url=public_ref,
                reference_url_sha256=ref_hash,
                school_year=school_year(excerpt),
                explicit_start_date=start,
                explicit_end_date=end,
                explicit_time=explicit_time(excerpt),
                date_semantics=semantics,
            )
        )
    return signals


def self_test() -> None:
    assert canonical_source_url("https://ccdvl.ro/") == "https://ccdvl.ro/"
    assert canonical_source_url("https://www.ccdvl.ro") == "https://ccdvl.ro/"
    for bad in (
        "http://ccdvl.ro/",
        "https://evil.example/",
        "https://ccdvl.ro/contact/",
        "https://ccdvl.ro/?x=1",
        "https://user:pass@ccdvl.ro/",
    ):
        try:
            canonical_source_url(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected refusal: {bad}")

    sample = """
    <html><body>
      <header>Casa Corpului Didactic Vâlcea</header>
      <article><h2>ANUNȚ</h2><p>Casa Corpului Didactic Vâlcea invită cadrele didactice să ridice
      adeverințele aferente cursurilor de formare și activităților desfășurate în anul școlar
      2025–2026. Perioada: 31 august – 4 septembrie 2026 Program: luni–vineri, 11:30–14:00.</p></article>
      <article><h2>Chestionar pentru analiza nevoilor de formare profesională anul școlar 2026–2027</h2></article>
      <article><a href="https://ccdvl.ro/grafic-iunie/">Graficul de desfășurare al programelor de formare și al activităților metodice – iunie 2026</a></article>
      <article><h2>Simpozion Național CCD Vâlcea – 26 martie 2026, ora 15:00</h2></article>
      <article><a href="https://ccdvl.ro/rezultate-selectie/">Rezultate selecție formatori - lista candidaților și punctaje</a></article>
    </body></html>
    """
    signals = build_signals("https://ccdvl.ro/", sample, sample.encode())
    classes = {s.signal_class for s in signals}
    assert "PROFESSIONAL_DEVELOPMENT_SERVICE_WINDOW" in classes
    assert "TRAINING_NEEDS_SURVEY_NOTICE" in classes
    assert "TRAINING_AND_METHODICAL_SCHEDULE_REFERENCE" in classes
    assert "METHODICAL_EVENT_REFERENCE" in classes
    assert "HOLD_SENSITIVE_PROFESSIONAL_SELECTION_REFERENCE" in classes

    service = next(s for s in signals if s.signal_class == "PROFESSIONAL_DEVELOPMENT_SERVICE_WINDOW")
    assert service.explicit_start_date == "2026-08-31"
    assert service.explicit_end_date == "2026-09-04"
    assert service.school_year == "2025-2026"
    assert service.current_status_claim_allowed is False
    assert service.public_projection_allowed is False

    sensitive = next(s for s in signals if s.signal_class == "HOLD_SENSITIVE_PROFESSIONAL_SELECTION_REFERENCE")
    assert sensitive.label is None
    assert sensitive.reference_url is None
    assert sensitive.evidence_excerpt == "[WITHHELD_SENSITIVE_REFERENCE]"

    assert normalize_reference_url("https://ccdvl.ro/post/", "https://ccdvl.ro/") == "https://ccdvl.ro/post/"
    assert normalize_reference_url("https://forms.gle/example", "https://ccdvl.ro/") is None

    bad_identity = "<html><body>Training calendar</body></html>"
    try:
        build_signals("https://ccdvl.ro/", bad_identity, bad_identity.encode())
    except ValueError as exc:
        assert "identity" in str(exc)
    else:
        raise AssertionError("identity gate must fail closed")

    challenge = "<html><body>Casa Corpului Didactic Vâlcea CAPTCHA verify you are human</body></html>"
    try:
        build_signals("https://ccdvl.ro/", challenge, challenge.encode())
    except ValueError as exc:
        assert "placeholder" in str(exc)
    else:
        raise AssertionError("challenge page must fail closed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://ccdvl.ro/")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        print("ccd_valcea_professional_development_signal_adapter self-test: OK")
        return 0

    final_url, html_text, body = fetch_html(args.url)
    signals = build_signals(final_url, html_text, body)
    print(json.dumps([asdict(signal) for signal in signals], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
