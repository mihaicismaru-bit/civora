#!/usr/bin/env python3
"""Evidence-first ISJ Vâlcea education notice/reference adapter.

The official Inspectoratul Școlar Județean Vâlcea site exposes high-value public
education notices, calendars and document references. This adapter is deliberately
bounded: it extracts only explicit, page-visible notice/document labels from two
official surfaces and never promotes exam/result documents containing people into
reader-facing facts.

Source-only by design: no persistence, Fact Kernel promotion, Writer/public
projection, deployment changes, inferred document freshness or live-status authority.
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

SOURCE_ID = "signal-isj-valcea-education-notices"
TAXONOMY_VERSION = "2026-08-30.1"
SOURCE_NAME = "Inspectoratul Școlar Județean Vâlcea"
SOURCE_TIER = "T1"
ALLOWED_HOSTS = {"isjvalcea.ro", "www.isjvalcea.ro"}
CANONICAL_HOST = "www.isjvalcea.ro"
SURFACES = {
    "/noutăți": "EDUCATION_NEWS",
    "/elevi/inscriere-invatamant-prescolar": "PRESCHOOL_ENROLMENT",
}
MAX_RESPONSE_BYTES = 2_500_000
TIMEOUT_SECONDS = 15
USER_AGENT = "CIVORA-ValceaClar-ISJEducation/1.0 (+evidence-first; contact via repository)"
MAX_SIGNALS = 120
ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".odt"}

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
    "isj valcea",
    "inspectoratul scolar judetean valcea",
)

SENSITIVE_RESULT_TERMS = (
    "rezultate",
    "rezultate finale",
    "rezultate initiale",
    "tabel nominal",
    "repartizarea candidatilor",
    "punctajele candidatilor",
    "contestatii",
)

NOTICE_RULES = (
    ("PRESCHOOL_ENROLMENT_NOTICE", ("inscriere", "prescolar")),
    ("PRESCHOOL_ENROLMENT_NOTICE", ("inscriere", "anteprescolar")),
    ("SECONDARY_ADMISSION_NOTICE", ("admitere",)),
    ("TEACHER_EXAM_NOTICE", ("definitivat",)),
    ("TEACHER_EXAM_NOTICE", ("titularizare",)),
    ("SCHOOL_MANAGEMENT_NOTICE", ("directori",)),
    ("MERIT_GRANT_NOTICE", ("gradatii de merit",)),
    ("SCHOOL_CALENDAR_NOTICE", ("calendar",)),
    ("SUMMER_PRESCHOOL_SERVICE_REFERENCE", ("gradinite", "vacanta de vara")),
)

SCHOOL_YEAR_RE = re.compile(r"\b(20\d{2})\s*[-–—/]\s*(20\d{2})\b")
DATE_RE = re.compile(r"\b([0-3]?\d)[./-]([01]?\d)[./-](20\d{2})\b")


@dataclass(frozen=True)
class EducationSignal:
    source_id: str
    taxonomy_version: str
    signal_class: str
    source_tier: str
    source_name: str
    source_url: str
    payload_sha256: str
    evidence_excerpt: str
    hold_reason: Optional[str]
    surface: str
    label: Optional[str] = None
    document_url: Optional[str] = None
    document_url_sha256: Optional[str] = None
    school_year: Optional[str] = None
    explicit_date: Optional[str] = None
    explicit_date_semantics: Optional[str] = None
    reference_scope: str = "EDUCATION_PUBLIC_REFERENCE"
    publication_authority: str = "NONE"
    current_status_claim_allowed: bool = False
    freshness_claim_allowed: bool = False
    person_fact_extraction_allowed: bool = False
    sensitive_result_projection_allowed: bool = False
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


def _path(value: str) -> str:
    path = re.sub(r"/+", "/", unquote(value or "/"))
    if not path.startswith("/"):
        path = "/" + path
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return path


def validate_source_url(url: str) -> tuple[str, str]:
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
        or path not in SURFACES
    ):
        raise ValueError(f"off-surface source refused: {url}")
    return urlunsplit(("https", CANONICAL_HOST, path, "", "")), SURFACES[path]


def normalize_document_url(value: str, base_url: str) -> Optional[str]:
    text = clean(value)
    if not text:
        return None
    parsed = urlsplit(urljoin(base_url, text))
    host = (parsed.hostname or "").casefold()
    path = re.sub(r"/+", "/", unquote(parsed.path or "/"))
    suffix = "." + path.rsplit(".", 1)[-1].casefold() if "." in path.rsplit("/", 1)[-1] else ""
    if (
        parsed.scheme.casefold() != "https"
        or host not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
        or suffix not in ALLOWED_DOCUMENT_EXTENSIONS
    ):
        return None
    return urlunsplit(("https", CANONICAL_HOST, path, parsed.query, ""))


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise ValueError(f"redirect refused: {newurl}")


def fetch_html(url: str, timeout: float = TIMEOUT_SECONDS) -> tuple[str, str, bytes]:
    canonical, _ = validate_source_url(url)
    context = ssl.create_default_context()
    opener = build_opener(NoRedirects(), HTTPSHandler(context=context))
    request = Request(canonical, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
    with opener.open(request, timeout=timeout) as response:
        final_url, _ = validate_source_url(response.geturl())
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds size cap")
        charset = response.headers.get_content_charset() or "utf-8"
    return final_url, body.decode(charset, errors="replace"), body


class NoticeParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}
    BREAKS = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "section", "article"}

    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
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


def parse_document(html_text: str, page_url: str) -> tuple[str, list[tuple[str, str]]]:
    parser = NoticeParser(page_url)
    parser.feed(html_text)
    return parser.text(), parser.links


def placeholder(text: str) -> bool:
    value = fold(text)[:5000]
    return any(term in value for term in PLACEHOLDER_TERMS)


def identity_present(text: str) -> bool:
    value = fold(text)[:10000]
    return any(term in value for term in IDENTITY_TERMS)


def explicit_school_year(text: str) -> Optional[str]:
    matches = {f"{a}-{b}" for a, b in SCHOOL_YEAR_RE.findall(text)}
    return next(iter(matches)) if len(matches) == 1 else None


def explicit_date(text: str) -> tuple[Optional[str], Optional[str]]:
    matches = DATE_RE.findall(text)
    values: set[str] = set()
    for day, month, year in matches:
        try:
            d, m, y = int(day), int(month), int(year)
            if 1 <= m <= 12 and 1 <= d <= 31:
                values.add(f"{y:04d}-{m:02d}-{d:02d}")
        except ValueError:
            continue
    if len(values) == 1:
        return next(iter(values)), "EXPLICIT_VISIBLE_LABEL_DATE_ONLY"
    return None, None


def classify_label(label: str) -> str:
    value = fold(label)
    for signal_class, terms in NOTICE_RULES:
        if all(term in value for term in terms):
            return signal_class
    return "EDUCATION_DOCUMENT_REFERENCE"


def sensitive_label(label: str) -> bool:
    value = fold(label)
    return any(term in value for term in SENSITIVE_RESULT_TERMS)


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hold_signal(source_url: str, digest: str, surface: str, excerpt: str, reason: str) -> EducationSignal:
    return EducationSignal(
        source_id=SOURCE_ID,
        taxonomy_version=TAXONOMY_VERSION,
        signal_class="HOLD",
        source_tier=SOURCE_TIER,
        source_name=SOURCE_NAME,
        source_url=source_url,
        payload_sha256=digest,
        evidence_excerpt=clean(excerpt)[:900],
        hold_reason=reason,
        surface=surface,
    )


def build_signals(source_url: str, html_text: str, body: bytes) -> list[EducationSignal]:
    canonical, surface = validate_source_url(source_url)
    digest = hashlib.sha256(body).hexdigest()
    text, links = parse_document(html_text, canonical)

    if placeholder(text):
        return [hold_signal(canonical, digest, surface, text, "PLACEHOLDER_OR_INTERSTITIAL")]
    if not identity_present(text):
        return [hold_signal(canonical, digest, surface, text, "SOURCE_IDENTITY_NOT_EXPLICIT")]

    page_year = explicit_school_year(text)
    signals: list[EducationSignal] = []
    seen: set[tuple[str, str]] = set()

    for href, raw_label in links:
        label = clean(raw_label)
        if len(label) < 4:
            continue
        label_fold = fold(label)
        if not any(
            marker in label_fold
            for marker in (
                "inscriere", "admitere", "definitivat", "titularizare", "director",
                "gradatii", "gradatie", "calendar", "vacanta", "rezult", "contest",
                "repartizarea", "tabel", "brosura", "cerere", "anunt",
            )
        ):
            continue

        doc_url = normalize_document_url(href, canonical)
        identity = ("doc", doc_url) if doc_url else ("label", label_fold)
        if identity in seen:
            continue
        seen.add(identity)

        item_date, date_semantics = explicit_date(label)
        item_year = explicit_school_year(label) or page_year

        if sensitive_label(label):
            url_hash = _digest_text(doc_url) if doc_url else _digest_text(clean(href))
            signals.append(
                EducationSignal(
                    source_id=SOURCE_ID,
                    taxonomy_version=TAXONOMY_VERSION,
                    signal_class="HOLD_SENSITIVE_EDUCATION_RESULT_REFERENCE",
                    source_tier=SOURCE_TIER,
                    source_name=SOURCE_NAME,
                    source_url=canonical,
                    payload_sha256=digest,
                    evidence_excerpt="Sensitive education result/reference withheld from automatic projection.",
                    hold_reason="PERSON_LEVEL_OR_RESULT_DOCUMENT_REVIEW_REQUIRED",
                    surface=surface,
                    label=None,
                    document_url=None,
                    document_url_sha256=url_hash,
                    school_year=item_year,
                    explicit_date=item_date,
                    explicit_date_semantics=date_semantics,
                )
            )
            continue

        signal_class = classify_label(label)
        signals.append(
            EducationSignal(
                source_id=SOURCE_ID,
                taxonomy_version=TAXONOMY_VERSION,
                signal_class=signal_class,
                source_tier=SOURCE_TIER,
                source_name=SOURCE_NAME,
                source_url=canonical,
                payload_sha256=digest,
                evidence_excerpt=label[:900],
                hold_reason=None if doc_url else "DOCUMENT_LINK_OFFICIAL_HOST_NOT_VERIFIED",
                surface=surface,
                label=label,
                document_url=doc_url,
                document_url_sha256=_digest_text(doc_url) if doc_url else _digest_text(clean(href)),
                school_year=item_year,
                explicit_date=item_date,
                explicit_date_semantics=date_semantics,
            )
        )
        if len(signals) >= MAX_SIGNALS:
            break

    if not signals:
        return [hold_signal(canonical, digest, surface, text, "NO_RELEVANT_EXPLICIT_NOTICE_LABELS")]

    return signals


def run(url: str) -> list[EducationSignal]:
    canonical, _ = validate_source_url(url)
    final_url, html_text, body = fetch_html(canonical)
    return build_signals(final_url, html_text, body)


def _assert_fail_closed(signal: EducationSignal) -> None:
    assert signal.publication_authority == "NONE"
    assert signal.current_status_claim_allowed is False
    assert signal.freshness_claim_allowed is False
    assert signal.person_fact_extraction_allowed is False
    assert signal.sensitive_result_projection_allowed is False
    assert signal.document_body_fetch_allowed is False
    assert signal.inferred_photo_rights_allowed is False
    assert signal.persistence_allowed is False
    assert signal.fact_kernel_promotion_allowed is False
    assert signal.writer_allowed is False
    assert signal.public_projection_allowed is False


def self_test() -> None:
    canonical, surface = validate_source_url("https://isjvalcea.ro/nout%C4%83%C8%9Bi")
    assert canonical == "https://www.isjvalcea.ro/noutăți"
    assert surface == "EDUCATION_NEWS"

    for bad in (
        "http://www.isjvalcea.ro/nout%C4%83%C8%9Bi",
        "https://evil.example/nout%C4%83%C8%9Bi",
        "https://www.isjvalcea.ro/",
        "https://www.isjvalcea.ro/nout%C4%83%C8%9Bi?x=1",
    ):
        try:
            validate_source_url(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"off-surface URL accepted: {bad}")

    html = """
    <html><body>
      <h1>ISJ VÂLCEA</h1><h2>NOUTĂȚI</h2>
      <p>2026-2027</p>
      <a href="/files/Brosura-Admitere-2026.pdf">BROȘURĂ ADMITERE 2026-2027</a>
      <a href="/files/calendar-inscriere.pdf">Calendar înscriere preșcolar 2026-2027</a>
      <a href="/files/rezultate-definitivat.pdf">Rezultate Finale DEFINITIVAT 2026</a>
      <a href="https://drive.google.com/file/d/123/view">CONCURS DIRECTORI 2026</a>
      <a href="/about.pdf">Despre instituție</a>
    </body></html>
    """
    body = html.encode()
    signals = build_signals("https://www.isjvalcea.ro/noutăți", html, body)
    assert any(s.signal_class == "SECONDARY_ADMISSION_NOTICE" for s in signals)
    assert any(s.signal_class == "PRESCHOOL_ENROLMENT_NOTICE" for s in signals)
    sensitive = [s for s in signals if s.signal_class == "HOLD_SENSITIVE_EDUCATION_RESULT_REFERENCE"]
    assert len(sensitive) == 1
    assert sensitive[0].label is None and sensitive[0].document_url is None
    assert sensitive[0].document_url_sha256
    director = [s for s in signals if s.signal_class == "SCHOOL_MANAGEMENT_NOTICE"]
    assert len(director) == 1 and director[0].document_url is None
    assert director[0].hold_reason == "DOCUMENT_LINK_OFFICIAL_HOST_NOT_VERIFIED"
    assert all(s.school_year == "2026-2027" for s in signals if s.signal_class != "HOLD_SENSITIVE_EDUCATION_RESULT_REFERENCE")
    for signal in signals:
        _assert_fail_closed(signal)

    preschool = """
    <html><body>
      <h1>ISJ VÂLCEA</h1>
      <h2>Înscriere învățământ preșcolar</h2>
      <p>2026-2027</p>
      <a href="/docs/planificare-gradinite-vacanta.pdf">PLANIFICARE GRĂDINIȚE VACANȚA DE VARĂ</a>
      <a href="/docs/cerere-inscriere-prescolar-2026.pdf">CERERE ÎNSCRIERE PREȘCOLAR 2026</a>
    </body></html>
    """
    ps = build_signals(
        "https://www.isjvalcea.ro/elevi/inscriere-invatamant-prescolar",
        preschool,
        preschool.encode(),
    )
    assert any(s.signal_class == "SUMMER_PRESCHOOL_SERVICE_REFERENCE" for s in ps)
    assert any(s.signal_class == "PRESCHOOL_ENROLMENT_NOTICE" for s in ps)
    for signal in ps:
        _assert_fail_closed(signal)

    placeholder_html = "<html><body>ISJ VÂLCEA verify you are human</body></html>"
    hold = build_signals(
        "https://www.isjvalcea.ro/noutăți",
        placeholder_html,
        placeholder_html.encode(),
    )
    assert len(hold) == 1 and hold[0].signal_class == "HOLD"
    assert hold[0].hold_reason == "PLACEHOLDER_OR_INTERSTITIAL"

    wrong_identity = "<html><body><a href='/x.pdf'>Calendar admitere 2026</a></body></html>"
    hold2 = build_signals(
        "https://www.isjvalcea.ro/noutăți",
        wrong_identity,
        wrong_identity.encode(),
    )
    assert len(hold2) == 1 and hold2[0].hold_reason == "SOURCE_IDENTITY_NOT_EXPLICIT"

    assert normalize_document_url("https://evil.example/a.pdf", canonical) is None
    assert normalize_document_url("https://www.isjvalcea.ro/a.pdf", canonical)
    print("ISJ Vâlcea education notice fail-closed regressions: OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://www.isjvalcea.ro/nout%C4%83%C8%9Bi")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    try:
        signals = run(args.url)
    except Exception as exc:
        print(json.dumps({"status": "HOLD", "reason": type(exc).__name__, "detail": clean(exc)}, ensure_ascii=False))
        return 2

    print(json.dumps([asdict(signal) for signal in signals], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
