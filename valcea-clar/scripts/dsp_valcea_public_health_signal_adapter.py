#!/usr/bin/env python3
"""Evidence-first DSP Vâlcea public-health signal adapter.

Bounded to the official DSP Vâlcea public homepage. Emits review-required
references for explicit public-health campaigns, guidance and public-facing
institutional schedule information while holding person-sensitive health material.

No persistence, Fact Kernel promotion, Writer/public projection, form submission,
document-body fetch, current outbreak/service claims, medical advice, individual
case inference or photo-rights inference.
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

SOURCE_ID = "signal-dsp-valcea-public-health"
TAXONOMY_VERSION = "2026-08-30.1"
SOURCE_NAME = "Direcția de Sănătate Publică Vâlcea"
SOURCE_TIER = "T1"
CANONICAL_HOST = "www.aspjvalcea.ro"
ALLOWED_HOSTS = {"aspjvalcea.ro", "www.aspjvalcea.ro"}
SURFACES = {
    "/": "DSP_HOME",
}
MAX_RESPONSE_BYTES = 2_500_000
TIMEOUT_SECONDS = 15
USER_AGENT = "CIVORA-ValceaClar-DSP/1.0 (+evidence-first; contact via repository)"
MAX_SIGNALS = 120

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
    "directia de sanatate publica valcea",
    "dsp valcea",
)
SENSITIVE_TERMS = (
    "lista pacient",
    "lista de pacient",
    "nume pacient",
    "prenume pacient",
    "cnp",
    "foaie de observatie",
    "dosar medical",
    "fisa medicala",
    "rezultat analize",
    "rezultate analize",
    "diagnostic individual",
    "caz clinic individual",
    "ancheta epidemiologica individuala",
)
RULES = (
    ("MENTAL_HEALTH_PROMOTION_CAMPAIGN_REFERENCE", ("sanatatii mintale",)),
    ("RESPIRATORY_HEALTH_PROMOTION_CAMPAIGN_REFERENCE", ("romania respira curat",)),
    (
        "HEALTHY_LIFESTYLE_PROMOTION_CAMPAIGN_REFERENCE",
        ("alimentatiei sanatoase", "activitatii fizice"),
    ),
    ("SCHOOL_MEDICINE_GUIDANCE_REFERENCE", ("socului anafilactic", "medicina scolara")),
    ("MATERNAL_HEALTH_INFORMATION_REFERENCE", ("ingrijire gravide",)),
    ("PUBLIC_HEALTH_SERVICE_HOURS_REFERENCE", ("program de lucru cu publicul",)),
    ("PUBLIC_HEALTH_CAMPAIGN_REFERENCE", ("campania",)),
)
DATE_NUMERIC_RE = re.compile(r"\b([0-3]?\d)[./-]([01]?\d)[./-](20\d{2})\b")
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
class DSPSignal:
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
    reference_url: Optional[str] = None
    reference_url_sha256: Optional[str] = None
    explicit_dates: tuple[str, ...] = ()
    date_semantics: Optional[str] = None
    reference_scope: str = "PUBLIC_HEALTH_PUBLIC_REFERENCE"
    publication_authority: str = "NONE"
    current_status_claim_allowed: bool = False
    current_outbreak_claim_allowed: bool = False
    service_availability_claim_allowed: bool = False
    medical_advice_allowed: bool = False
    individual_case_inference_allowed: bool = False
    patient_person_fact_extraction_allowed: bool = False
    sensitive_health_projection_allowed: bool = False
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
    return urlunsplit(("https", CANONICAL_HOST, "/", "", "")), SURFACES[path]


def normalize_reference_url(value: str, base_url: str) -> Optional[str]:
    text = clean(value)
    if not text:
        return None
    parsed = urlsplit(urljoin(base_url, text))
    host = (parsed.hostname or "").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or host not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
    ):
        return None
    path = re.sub(r"/+", "/", unquote(parsed.path or "/"))
    return urlunsplit(("https", CANONICAL_HOST, path, parsed.query, ""))


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise ValueError(f"redirect refused: {newurl}")


def fetch_html(url: str, timeout: float = TIMEOUT_SECONDS) -> tuple[str, str, bytes]:
    canonical, _ = validate_source_url(url)
    opener = build_opener(NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(canonical, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
    with opener.open(request, timeout=timeout) as response:
        final_url, _ = validate_source_url(response.geturl())
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds size cap")
        charset = response.headers.get_content_charset() or "utf-8"
    return final_url, body.decode(charset, errors="replace"), body


class PageParser(html.parser.HTMLParser):
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
    parser = PageParser()
    parser.feed(html_text)
    return parser.text(), parser.links


def placeholder(text: str) -> bool:
    value = fold(text)[:5000]
    return any(term in value for term in PLACEHOLDER_TERMS)


def identity_present(text: str) -> bool:
    value = fold(text)[:12000]
    return any(fold(term) in value for term in IDENTITY_TERMS)


def explicit_dates(text: str) -> tuple[str, ...]:
    values: set[str] = set()
    folded = fold(text)
    for match in DAY_MONTH_RE.finditer(folded):
        day, month_name, year = int(match.group(1)), match.group(2), int(match.group(3))
        month = MONTHS[month_name]
        if 1 <= day <= 31:
            values.add(f"{year:04d}-{month:02d}-{day:02d}")
    for day, month, year in DATE_NUMERIC_RE.findall(text):
        d, m, y = int(day), int(month), int(year)
        if 1 <= d <= 31 and 1 <= m <= 12:
            values.add(f"{y:04d}-{m:02d}-{d:02d}")
    return tuple(sorted(values))


def classify(text: str) -> tuple[str, Optional[str]]:
    value = fold(text)
    if any(fold(term) in value for term in SENSITIVE_TERMS):
        return "HOLD_SENSITIVE_HEALTH_PERSON_REFERENCE", "person-sensitive health material"
    for signal_class, required in RULES:
        if all(fold(term) in value for term in required):
            return signal_class, None
    return "HOLD_UNCLASSIFIED_DSP_REFERENCE", "no bounded taxonomy match"


def excerpt_for(text: str, label: str, limit: int = 420) -> str:
    source = clean(text)
    needle = clean(label)
    if needle:
        idx = fold(source).find(fold(needle))
        if idx >= 0:
            start = max(0, idx - 120)
            return clean(source[start:start + limit])
    return source[:limit]


def make_signal(
    *,
    source_url: str,
    surface: str,
    payload_sha256: str,
    evidence: str,
    label: Optional[str],
    reference_url: Optional[str],
) -> DSPSignal:
    classified_text = " ".join(x for x in (label, evidence) if x)
    signal_class, hold_reason = classify(classified_text)
    dates = explicit_dates(classified_text)
    held = signal_class.startswith("HOLD_")
    safe_label = None if held else label
    safe_url = None if held else reference_url
    safe_url_hash = hashlib.sha256(reference_url.encode()).hexdigest() if reference_url else None
    safe_excerpt = (
        "HELD_SENSITIVE_OR_UNCLASSIFIED_HEALTH_REFERENCE"
        if held
        else clean(evidence)[:500]
    )
    return DSPSignal(
        source_id=SOURCE_ID,
        taxonomy_version=TAXONOMY_VERSION,
        signal_class=signal_class,
        source_tier=SOURCE_TIER,
        source_name=SOURCE_NAME,
        source_url=source_url,
        payload_sha256=payload_sha256,
        evidence_excerpt=safe_excerpt,
        hold_reason=hold_reason,
        surface=surface,
        label=safe_label,
        reference_url=safe_url,
        reference_url_sha256=safe_url_hash,
        explicit_dates=() if held else dates,
        date_semantics="EXPLICIT_PAGE_VISIBLE_DATE_ONLY" if dates and not held else None,
    )


def extract_signals(source_url: str, html_text: str, payload: bytes) -> list[DSPSignal]:
    canonical, surface = validate_source_url(source_url)
    text, links = parse_document(html_text)
    if placeholder(text):
        raise ValueError("placeholder/challenge page refused")
    if not identity_present(text):
        raise ValueError("DSP Vâlcea source identity not present")
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    signals: list[DSPSignal] = []

    # Bounded visible chunks prevent unrelated sensitive material elsewhere on the page
    # from contaminating a safe public-health campaign reference.
    seen_chunks: set[tuple[str, str]] = set()
    for chunk in (clean(part) for part in text.split("\n")):
        if len(chunk) < 20:
            continue
        signal_class, _ = classify(chunk)
        if signal_class == "HOLD_UNCLASSIFIED_DSP_REFERENCE":
            continue
        key = (signal_class, hashlib.sha256(chunk.encode()).hexdigest())
        if key in seen_chunks:
            continue
        seen_chunks.add(key)
        signals.append(
            make_signal(
                source_url=canonical,
                surface=surface,
                payload_sha256=payload_sha256,
                evidence=chunk[:1200],
                label=None,
                reference_url=None,
            )
        )
        if len(signals) >= MAX_SIGNALS:
            return signals

    seen_links: set[tuple[str, str]] = set()
    for href, label in links:
        label = clean(label)
        if not label:
            continue
        ref = normalize_reference_url(href, canonical)
        key = (label, ref or "")
        if key in seen_links:
            continue
        seen_links.add(key)
        local_evidence = excerpt_for(text, label)
        signal_class, _ = classify(" ".join((label, local_evidence)))
        if signal_class == "HOLD_UNCLASSIFIED_DSP_REFERENCE":
            continue
        signals.append(
            make_signal(
                source_url=canonical,
                surface=surface,
                payload_sha256=payload_sha256,
                evidence=local_evidence,
                label=label,
                reference_url=ref,
            )
        )
        if len(signals) >= MAX_SIGNALS:
            break
    return signals


def validate_boundaries(signal: DSPSignal) -> None:
    forbidden_true = (
        "current_status_claim_allowed",
        "current_outbreak_claim_allowed",
        "service_availability_claim_allowed",
        "medical_advice_allowed",
        "individual_case_inference_allowed",
        "patient_person_fact_extraction_allowed",
        "sensitive_health_projection_allowed",
        "external_form_submission_allowed",
        "document_body_fetch_allowed",
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
        if signal.label or signal.reference_url or signal.explicit_dates:
            raise AssertionError("held signal leaks sensitive reference/date")
        if signal.evidence_excerpt != "HELD_SENSITIVE_OR_UNCLASSIFIED_HEALTH_REFERENCE":
            raise AssertionError("held signal leaks raw health evidence")


def run_self_test() -> None:
    sample = """
    <html><body>
      <h1>Direcția de Sănătate Publică Vâlcea</h1>
      <div>Campania de promovare a sănătății mintale</div>
      <div>Campanie națională "România respiră curat"</div>
      <div>Campania de promovare a alimentației sănătoase și activității fizice</div>
      <div>Ghid de lucru privind managementul șocului anafilactic în cabinetul de medicină școlară</div>
      <div>Broșură îngrijire gravide</div>
      <div>PROGRAM DE LUCRU CU PUBLICUL Luni – Joi 08:00 - 16:30 Vineri 08:00 - 14:00</div>
      <a href="/campanii/sanatate-mintala.php">Campania de promovare a sănătății mintale</a>
      <a href="/cazuri/lista-pacienti.php">Lista pacienți CNP rezultate analize</a>
      <a href="https://forms.example/appointment">Programare externă</a>
    </body></html>
    """
    url = "https://www.aspjvalcea.ro/"
    signals = extract_signals(url, sample, sample.encode())
    classes = {item.signal_class for item in signals}
    assert "MENTAL_HEALTH_PROMOTION_CAMPAIGN_REFERENCE" in classes
    assert "RESPIRATORY_HEALTH_PROMOTION_CAMPAIGN_REFERENCE" in classes
    assert "HEALTHY_LIFESTYLE_PROMOTION_CAMPAIGN_REFERENCE" in classes
    assert "SCHOOL_MEDICINE_GUIDANCE_REFERENCE" in classes
    assert "MATERNAL_HEALTH_INFORMATION_REFERENCE" in classes
    assert "PUBLIC_HEALTH_SERVICE_HOURS_REFERENCE" in classes
    held = [item for item in signals if item.signal_class == "HOLD_SENSITIVE_HEALTH_PERSON_REFERENCE"]
    assert held
    assert all(
        item.label is None
        and item.reference_url is None
        and item.explicit_dates == ()
        and item.evidence_excerpt == "HELD_SENSITIVE_OR_UNCLASSIFIED_HEALTH_REFERENCE"
        for item in held
    )
    for item in signals:
        validate_boundaries(item)

    assert classify("Campania de promovare a sănătății mintale")[0] == "MENTAL_HEALTH_PROMOTION_CAMPAIGN_REFERENCE"
    assert classify("Lista pacienți CNP rezultate analize")[0] == "HOLD_SENSITIVE_HEALTH_PERSON_REFERENCE"
    assert validate_source_url("https://aspjvalcea.ro/")[0] == "https://www.aspjvalcea.ro/"
    try:
        validate_source_url("https://evil.example/")
    except ValueError:
        pass
    else:
        raise AssertionError("off-surface host accepted")
    try:
        validate_source_url("https://dspvalcea.ro/")
    except ValueError:
        pass
    else:
        raise AssertionError("legacy DSP host accepted")
    try:
        validate_source_url("https://www.aspjvalcea.ro/interes/solicitari-informatii-legea544.php")
    except ValueError:
        pass
    else:
        raise AssertionError("off-surface source path accepted")
    assert normalize_reference_url("https://forms.example/appointment", url) is None
    assert normalize_reference_url("https://dspvalcea.ro/campanii/sanatate-mintala.php", url) is None
    assert normalize_reference_url("/campanii/sanatate-mintala.php", url) == (
        "https://www.aspjvalcea.ro/campanii/sanatate-mintala.php"
    )
    print("DSP Vâlcea public-health self-test: PASS")


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
    signals = extract_signals(final_url, html_text, payload)
    for signal in signals:
        validate_boundaries(signal)
    print(json.dumps([asdict(item) for item in signals], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())