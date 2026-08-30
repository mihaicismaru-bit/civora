#!/usr/bin/env python3
"""Evidence-first SJU Vâlcea hospital reference adapter.

Reads only the Ministry of Health registry page dedicated to Spitalul Județean de
Urgență Vâlcea and emits review-required structural/service references. It does
not infer current appointment availability, waiting times, bed availability,
on-call staffing, emergency load, opening hours, patient facts, or medical advice.

No persistence, Fact Kernel authority, Writer/public projection, linked-document
fetch, form submission, or photo-rights inference.
"""
from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
import re
import ssl
import sys
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Optional
from urllib.parse import unquote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

SOURCE_ID = "signal-sju-valcea-ms-hospital-reference"
TAXONOMY_VERSION = "2026-08-30.1"
SOURCE_NAME = "Spitalul Județean de Urgență Vâlcea — registru Ministerul Sănătății"
SOURCE_TIER = "T1"
CANONICAL_HOST = "www.ms.ro"
ALLOWED_HOSTS = {"www.ms.ro", "ms.ro"}
CANONICAL_PATH = "/ro/unitati-sanitare/spitalul-judetean-de-urgenta-valcea/"
SOURCE_URL = f"https://{CANONICAL_HOST}{CANONICAL_PATH}"
MAX_RESPONSE_BYTES = 2_500_000
TIMEOUT_SECONDS = 15
USER_AGENT = "CIVORA-ValceaClar-SJUReference/1.0 (+evidence-first; contact via repository)"
MAX_SIGNALS = 80

PLACEHOLDER_TERMS = (
    "enable javascript",
    "access denied",
    "verify you are human",
    "service unavailable",
    "temporarily unavailable",
    "captcha",
)
IDENTITY_TERMS = (
    "spitalul judetean de urgenta valcea",
    "spitalul judeţean de urgenţă valcea",
)
REGION_END_TERMS = (
    "alte unitati din valcea",
    "detalii spital",
)
SENSITIVE_TERMS = (
    "cnp",
    "lista pacient",
    "lista de pacient",
    "nume pacient",
    "prenume pacient",
    "foaie de observatie",
    "dosar medical",
    "rezultate analize pacient",
    "diagnostic individual",
)

SERVICE_RULES = (
    ("OUTPATIENT_SPECIALTY_REFERENCE", ("ambulatoriu de specialitate",)),
    ("LABORATORY_SERVICE_REFERENCE", ("laborator analize medicale",)),
    ("IMAGING_AND_NUCLEAR_MEDICINE_REFERENCE", ("laborator radiologie", "medicina nucleara")),
    ("EMERGENCY_AND_CRITICAL_CARE_REFERENCE", ("ati", "ustacc")),
    ("CARDIOVASCULAR_SERVICE_REFERENCE", ("cardiologie", "chirurgie vasculara")),
    ("NEUROLOGY_AND_NEUROSURGERY_REFERENCE", ("neurologie", "neurochirurgie")),
    ("PEDIATRIC_SERVICE_REFERENCE", ("pediatrie", "psihiatrie pediatrica", "neonatologie")),
    ("SURGICAL_SERVICE_REFERENCE", ("chirurgie generala", "urologie", "ortopedie")),
    ("ONCOLOGY_AND_HEMATOLOGY_REFERENCE", ("oncologie medicala", "hematologie")),
    ("OBSTETRICS_GYNECOLOGY_REFERENCE", ("ginecologie", "obstetrica ginecologie")),
    ("INFECTIOUS_DISEASE_SERVICE_REFERENCE", ("boli infectioase",)),
    ("REHABILITATION_SERVICE_REFERENCE", ("reabilitare medicala", "recuperare medicala", "rmfb")),
    ("PSYCHIATRY_SERVICE_REFERENCE", ("psihiatrie",)),
)

LOCATION_PATTERNS = (
    ("CALEA_LUI_TRAIAN_201", re.compile(r"calea lui traian\s*,?\s*(?:nr\.?\s*)?201\b", re.I)),
    ("GENERAL_MAGHERU_54", re.compile(r"(?:general|g-?ral)\s+magheru\s*,?\s*(?:nr\.?\s*)?54\b", re.I)),
    ("REMUS_BELLU_3", re.compile(r"remus bellu\s*,?\s*(?:nr\.?\s*)?3\b", re.I)),
    ("CALEA_LUI_TRAIAN_126", re.compile(r"calea lui traian\s*,?\s*(?:nr\.?\s*)?126\b", re.I)),
)
PHONE_RE = re.compile(r"\b0\d{2,3}[\s./-]?\d{3}[\s./-]?\d{3}\b")
BED_RE = re.compile(r"\b(\d{2,4})\s+paturi\b", re.I)


@dataclass(frozen=True)
class HospitalReferenceSignal:
    signal_id: str
    source_id: str
    taxonomy_version: str
    signal_class: str
    source_tier: str
    source_name: str
    source_url: str
    payload_sha256: str
    evidence_excerpt: str
    hold_reason: Optional[str]
    reference_label: Optional[str] = None
    reference_value: Optional[str] = None
    reference_scope: str = "HOSPITAL_REGISTRY_REFERENCE"
    publication_authority: str = "NONE"
    current_service_status_claim_allowed: bool = False
    appointment_availability_claim_allowed: bool = False
    bed_availability_claim_allowed: bool = False
    emergency_load_claim_allowed: bool = False
    on_call_staffing_claim_allowed: bool = False
    opening_hours_claim_allowed: bool = False
    patient_person_fact_extraction_allowed: bool = False
    medical_advice_allowed: bool = False
    linked_document_fetch_allowed: bool = False
    external_form_submission_allowed: bool = False
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


def _normalized_path(value: str) -> str:
    path = re.sub(r"/+", "/", unquote(value or "/"))
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path += "/"
    return path


def validate_source_url(url: str) -> str:
    parsed = urlsplit(clean(url))
    host = (parsed.hostname or "").casefold()
    path = _normalized_path(parsed.path)
    if (
        parsed.scheme.casefold() != "https"
        or host not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or path != CANONICAL_PATH
    ):
        raise ValueError(f"off-surface source refused: {url}")
    return urlunsplit(("https", CANONICAL_HOST, CANONICAL_PATH, "", ""))


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise ValueError(f"redirect refused: {newurl}")


def fetch_html(url: str = SOURCE_URL, timeout: float = TIMEOUT_SECONDS) -> tuple[str, str, bytes]:
    canonical = validate_source_url(url)
    opener = build_opener(NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(canonical, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
    with opener.open(request, timeout=timeout) as response:
        final_url = validate_source_url(response.geturl())
        content_type = (response.headers.get("Content-Type") or "").casefold()
        if "text/html" not in content_type:
            raise ValueError(f"non-HTML response refused: {content_type}")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds size cap")
        charset = response.headers.get_content_charset() or "utf-8"
    return final_url, body.decode(charset, errors="replace"), body


class BlockParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}
    BLOCKS = {"p", "div", "li", "h1", "h2", "h3", "h4", "section", "article", "br"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.current: list[str] = []
        self.blocks: list[str] = []

    def _flush(self) -> None:
        value = clean(" ".join(self.current))
        if value:
            self.blocks.append(value)
        self.current = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            self.skip += 1
            return
        if not self.skip and tag in self.BLOCKS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            if self.skip:
                self.skip -= 1
            return
        if not self.skip and tag in self.BLOCKS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        value = clean(data)
        if value:
            self.current.append(value)

    def close(self) -> None:
        super().close()
        self._flush()


def extract_hospital_region(html_text: str) -> str:
    parser = BlockParser()
    parser.feed(html_text)
    parser.close()
    blocks = parser.blocks
    start = None
    for idx, block in enumerate(blocks):
        if any(term in fold(block) for term in IDENTITY_TERMS):
            start = idx
            break
    if start is None:
        raise ValueError("hospital identity missing from source page")

    region: list[str] = []
    for block in blocks[start:]:
        folded = fold(block)
        if region and any(term in folded for term in REGION_END_TERMS):
            break
        region.append(block)
        if len(region) >= 80:
            break
    text = clean(" ".join(region))
    if len(text) < 120:
        raise ValueError("hospital registry region unexpectedly small")
    return text


def placeholder(text: str) -> bool:
    value = fold(text)[:6000]
    return any(term in value for term in PLACEHOLDER_TERMS)


def evidence_around(text: str, term: str, radius: int = 180) -> str:
    folded_text = fold(text)
    folded_term = fold(term)
    pos = folded_text.find(folded_term)
    if pos < 0:
        return clean(text)[:360]
    start = max(0, pos - radius)
    end = min(len(text), pos + len(term) + radius)
    return clean(text[start:end])[:420]


def deterministic_signal_id(signal_class: str, label: str) -> str:
    digest = hashlib.sha256(f"{signal_class}\0{label}".encode("utf-8")).hexdigest()[:20]
    return f"sjuvl-{signal_class.lower().replace('_', '-')}-{digest}"


def _signal(
    signal_class: str,
    payload_sha256: str,
    region: str,
    *,
    label: str,
    value: Optional[str] = None,
    evidence_term: Optional[str] = None,
    hold_reason: Optional[str] = None,
) -> HospitalReferenceSignal:
    return HospitalReferenceSignal(
        signal_id=deterministic_signal_id(signal_class, label),
        source_id=SOURCE_ID,
        taxonomy_version=TAXONOMY_VERSION,
        signal_class=signal_class,
        source_tier=SOURCE_TIER,
        source_name=SOURCE_NAME,
        source_url=SOURCE_URL,
        payload_sha256=payload_sha256,
        evidence_excerpt="" if hold_reason else evidence_around(region, evidence_term or label),
        hold_reason=hold_reason,
        reference_label=None if hold_reason else label,
        reference_value=None if hold_reason else value,
    )


def analyze(html_text: str, raw_payload: bytes, source_url: str = SOURCE_URL) -> list[HospitalReferenceSignal]:
    validate_source_url(source_url)
    if placeholder(html_text):
        raise ValueError("placeholder/challenge page refused")
    region = extract_hospital_region(html_text)
    folded = fold(region)
    payload_sha256 = hashlib.sha256(raw_payload).hexdigest()

    if any(term in folded for term in SENSITIVE_TERMS):
        return [
            _signal(
                "HOLD_SENSITIVE_PATIENT_REFERENCE",
                payload_sha256,
                region,
                label="sensitive-patient-material",
                hold_reason="PATIENT_IDENTIFIABLE_OR_CASE_SPECIFIC_MATERIAL",
            )
        ]

    signals: list[HospitalReferenceSignal] = []
    signals.append(
        _signal(
            "HOSPITAL_PROFILE_REFERENCE",
            payload_sha256,
            region,
            label="Spital Județean de Urgență Vâlcea",
            evidence_term="spital judetean",
        )
    )

    bed_match = BED_RE.search(region)
    if bed_match:
        signals.append(
            _signal(
                "HOSPITAL_REGISTERED_CAPACITY_REFERENCE",
                payload_sha256,
                region,
                label="registered-bed-count",
                value=bed_match.group(1),
                evidence_term=bed_match.group(0),
            )
        )

    for location_label, pattern in LOCATION_PATTERNS:
        match = pattern.search(folded)
        if match:
            signals.append(
                _signal(
                    "HOSPITAL_LOCATION_REFERENCE",
                    payload_sha256,
                    region,
                    label=location_label,
                    evidence_term=match.group(0),
                )
            )

    for signal_class, terms in SERVICE_RULES:
        hit = next((term for term in terms if fold(term) in folded), None)
        if not hit:
            continue
        signals.append(
            _signal(
                signal_class,
                payload_sha256,
                region,
                label=signal_class.removesuffix("_REFERENCE").lower(),
                evidence_term=hit,
            )
        )

    phone = PHONE_RE.search(region)
    if phone:
        normalized = re.sub(r"\D", "", phone.group(0))
        signals.append(
            _signal(
                "HOSPITAL_CONTACT_REFERENCE",
                payload_sha256,
                region,
                label="central-phone",
                value=normalized,
                evidence_term=phone.group(0),
            )
        )

    if len(signals) > MAX_SIGNALS:
        raise ValueError("signal count exceeds cap")
    if not signals:
        raise ValueError("no hospital references extracted")
    return signals


def serialize(signals: list[HospitalReferenceSignal]) -> str:
    return json.dumps([asdict(item) for item in signals], ensure_ascii=False, indent=2, sort_keys=True)


def self_test() -> None:
    sample = """<!doctype html><html><body>
    <nav>Ministerul Sănătății Pacienți Examene și concursuri</nav>
    <h1>Spitalul Judetean de Urgenta Valcea</h1>
    <p>Calea lui Traian nr. 201, Râmnicu Vâlcea, județul Vâlcea, România</p>
    <p>Spital Județean</p>
    <p>Spitalul Judetean de Urgenta Valcea are in structura un numar de 1353 paturi si patru locatii de primire/tratare a pacientilor.</p>
    <p>Locatia din str. Calea lui Traian, nr. 201: Medicina interna, Hematologie, Cardiologie (+ USTACC), Neurologie, Chirurgie Generala, Pediatrie, ATI, Ortopedie si Traumatologie, Urologie, Neurochirurgie, Chirurgie Vasculara, laborator analize medicale, laborator Radiologie, Medicina Nucleara, ambulatoriu de specialitate.</p>
    <p>Locatia din str. General Magheru, nr. 54: Boli infectioase, Oftalmologie, Neurologie si Psihiatrie Pediatrica, Dermatovenerologie, Medicina Fizica si Reabilitare Medicala, Psihiatrie, Endocrinologie.</p>
    <p>Locatia din str. Remus Bellu, nr. 3: Oncologie Medicala, Gastroenterologie, Geriatrie si Gerontologie, Obstetrica Ginecologie, Neonatologie.</p>
    <p>Locatia din str. Calea lui Traian, nr. 126: dispensar.</p>
    <p>Telefon: 0350/405951</p>
    <h2>Alte unități din Vâlcea</h2><p>Spitalul Orasenesc Horezu</p>
    </body></html>"""
    payload = sample.encode("utf-8")
    items = analyze(sample, payload)
    classes = {item.signal_class for item in items}
    required = {
        "HOSPITAL_PROFILE_REFERENCE",
        "HOSPITAL_REGISTERED_CAPACITY_REFERENCE",
        "HOSPITAL_LOCATION_REFERENCE",
        "OUTPATIENT_SPECIALTY_REFERENCE",
        "LABORATORY_SERVICE_REFERENCE",
        "IMAGING_AND_NUCLEAR_MEDICINE_REFERENCE",
        "HOSPITAL_CONTACT_REFERENCE",
    }
    assert required <= classes, classes
    locations = [item for item in items if item.signal_class == "HOSPITAL_LOCATION_REFERENCE"]
    assert len(locations) == 4, locations
    capacity = next(item for item in items if item.signal_class == "HOSPITAL_REGISTERED_CAPACITY_REFERENCE")
    assert capacity.reference_value == "1353"
    assert all(item.publication_authority == "NONE" for item in items)
    assert all(not item.current_service_status_claim_allowed for item in items)
    assert all(not item.appointment_availability_claim_allowed for item in items)
    assert all(not item.bed_availability_claim_allowed for item in items)
    assert all(not item.public_projection_allowed for item in items)

    sensitive = sample.replace(
        "Telefon: 0350/405951",
        "Lista pacient: Nume pacient; CNP 1234567890123",
    )
    held = analyze(sensitive, sensitive.encode("utf-8"))
    assert len(held) == 1
    assert held[0].signal_class == "HOLD_SENSITIVE_PATIENT_REFERENCE"
    assert held[0].evidence_excerpt == ""
    assert held[0].reference_label is None
    assert held[0].reference_value is None

    for bad in (
        "http://www.ms.ro/ro/unitati-sanitare/spitalul-judetean-de-urgenta-valcea/",
        "https://www.ms.ro/ro/unitati-sanitare/",
        "https://evil.example/ro/unitati-sanitare/spitalul-judetean-de-urgenta-valcea/",
        SOURCE_URL + "?preview=1",
    ):
        try:
            validate_source_url(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"bad source URL accepted: {bad}")

    try:
        analyze("<html><body>Ministerul Sănătății</body></html>", b"x")
    except ValueError as exc:
        assert "identity" in str(exc)
    else:
        raise AssertionError("identity-less source accepted")

    print(f"ok: {len(items)} SJU Vâlcea registry references; fail-closed invariants intact")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--source-url", default=SOURCE_URL)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    final_url, html_text, raw = fetch_html(args.source_url)
    signals = analyze(html_text, raw, final_url)
    print(serialize(signals))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        print(f"fail-closed: {exc}", file=sys.stderr)
        raise SystemExit(2)
