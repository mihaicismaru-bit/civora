#!/usr/bin/env python3
"""Fail-closed Ministry of Health registry references for Vâlcea public hospitals.

Reads only five exact Ministry of Health registry pages for public hospitals outside
SJU Vâlcea and emits review-required structural/service references. Registry text is
not current operational state: no appointment, bed, on-call, emergency-load,
opening-hours, patient-level, treatment, or medical-advice claims are authorized.

No persistence, Fact Kernel promotion, Writer/public projection, linked-document
fetch, external form submission, or photo-rights inference.
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

TAXONOMY_VERSION = "2026-08-30.1"
SOURCE_TIER = "T1"
CANONICAL_HOST = "www.ms.ro"
ALLOWED_HOSTS = {"www.ms.ro", "ms.ro"}
MAX_RESPONSE_BYTES = 2_500_000
TIMEOUT_SECONDS = 15
MAX_SIGNALS_PER_SOURCE = 48
USER_AGENT = "CIVORA-ValceaClar-HospitalNetwork/1.0 (+evidence-first; contact via repository)"

SOURCE_PROFILES = {
    "dragasani": {
        "source_id": "signal-ms-valcea-hospital-dragasani-reference",
        "source_name": 'Spitalul Municipal "Costache Nicolescu" Drăgășani — registru Ministerul Sănătății',
        "path": "/ro/unitati-sanitare/spitalul-municipal-costache-nicolescu-dragasani/",
        "identity_terms": ("costache nicolescu", "spitalul municipal dragasani"),
        "profile_label": 'Spitalul Municipal "Costache Nicolescu" Drăgășani',
        "locality_terms": ("dragasani",),
    },
    "horezu": {
        "source_id": "signal-ms-valcea-hospital-horezu-reference",
        "source_name": "Spitalul Orășenesc Horezu — registru Ministerul Sănătății",
        "path": "/ro/unitati-sanitare/spitalul-orasenesc-horezu/",
        "identity_terms": ("spitalul orasenesc horezu",),
        "profile_label": "Spitalul Orășenesc Horezu",
        "locality_terms": ("horezu",),
    },
    "brezoi": {
        "source_id": "signal-ms-valcea-hospital-brezoi-reference",
        "source_name": "Spitalul Orășenesc Brezoi — registru Ministerul Sănătății",
        "path": "/ro/unitati-sanitare/spitalul-orasenesc-brezoi/",
        "identity_terms": ("spitalul orasenesc brezoi",),
        "profile_label": "Spitalul Orășenesc Brezoi",
        "locality_terms": ("brezoi",),
    },
    "dragoesti": {
        "source_id": "signal-ms-valcea-hospital-dragoesti-reference",
        "source_name": "Spitalul de Psihiatrie Drăgoești — registru Ministerul Sănătății",
        "path": "/ro/unitati-sanitare/spitalul-de-psihiatrie-dragoesti/",
        "identity_terms": ("spitalul de psihiatrie dragoesti",),
        "profile_label": "Spitalul de Psihiatrie Drăgoești",
        "locality_terms": ("dragoesti",),
    },
    "mihaesti_pneumo": {
        "source_id": "signal-ms-valcea-hospital-mihaesti-pneumo-reference",
        "source_name": 'Spitalul de Pneumoftiziologie "Constantin Anastasatu" — registru Ministerul Sănătății',
        "path": "/ro/unitati-sanitare/spitalul-de-pneumoftiziologie-constantin-anastasatu/",
        "identity_terms": ("spitalul de pneumoftiziologie constantin anastasatu", "constantin anastasatu"),
        "profile_label": 'Spitalul de Pneumoftiziologie "Constantin Anastasatu" Mihăești',
        "locality_terms": ("mihaesti",),
    },
}

PLACEHOLDER_TERMS = (
    "enable javascript",
    "access denied",
    "verify you are human",
    "service unavailable",
    "temporarily unavailable",
    "captcha",
)
REGION_END_TERMS = ("alte unitati din valcea", "detalii spital", "contact")
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
    ("OUTPATIENT_SERVICE_REFERENCE", ("ambulatoriu integrat", "ambulatoriu de specialitate", "ambulatoriu")),
    ("LABORATORY_SERVICE_REFERENCE", ("laborator analize medicale", "laborator de analize medicale")),
    ("RADIOLOGY_IMAGING_SERVICE_REFERENCE", ("laborator radiologie", "radiologie si imagistica medicala")),
    ("INTERNAL_MEDICINE_SERVICE_REFERENCE", ("medicina interna",)),
    ("NEUROLOGY_SERVICE_REFERENCE", ("neurologie",)),
    ("GENERAL_SURGERY_SERVICE_REFERENCE", ("chirurgie generala",)),
    ("OBSTETRICS_GYNECOLOGY_SERVICE_REFERENCE", ("obstretica-ginecologie", "obstetrica ginecologie")),
    ("CRITICAL_CARE_SERVICE_REFERENCE", (" ati ", "ati,")),
    ("PEDIATRIC_SERVICE_REFERENCE", ("pediatrie",)),
    ("PSYCHIATRY_SERVICE_REFERENCE", ("psihiatrie",)),
    ("INFECTIOUS_DISEASE_SERVICE_REFERENCE", ("boli infectioase",)),
    ("PULMONOLOGY_SERVICE_REFERENCE", ("pneumologie", "pneumoftiziologie")),
)
BED_RE = re.compile(r"\b(?:numar(?:ul)?\s+de\s+)?(\d{2,4})\s+paturi\b", re.I)


@dataclass(frozen=True)
class HospitalNetworkReferenceSignal:
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
    hospital_key: Optional[str] = None
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


def source_url(profile: dict[str, Any]) -> str:
    return f"https://{CANONICAL_HOST}{profile['path']}"


def validate_source_url(url: str, profile: dict[str, Any]) -> str:
    parsed = urlsplit(clean(url))
    host = (parsed.hostname or "").casefold()
    path = _normalized_path(parsed.path)
    expected_path = _normalized_path(str(profile["path"]))
    if (
        parsed.scheme.casefold() != "https"
        or host not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or path != expected_path
    ):
        raise ValueError(f"off-surface source refused: {url}")
    return urlunsplit(("https", CANONICAL_HOST, expected_path, "", ""))


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise ValueError(f"redirect refused: {newurl}")


def fetch_html(profile: dict[str, Any], timeout: float = TIMEOUT_SECONDS) -> tuple[str, str, bytes]:
    canonical = validate_source_url(source_url(profile), profile)
    opener = build_opener(NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(canonical, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
    with opener.open(request, timeout=timeout) as response:
        final_url = validate_source_url(response.geturl(), profile)
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
        if not self.skip:
            value = clean(data)
            if value:
                self.current.append(value)

    def close(self) -> None:
        super().close()
        self._flush()


def extract_hospital_region(html_text: str, profile: dict[str, Any]) -> str:
    parser = BlockParser()
    parser.feed(html_text)
    parser.close()
    identities = tuple(fold(value) for value in profile["identity_terms"])
    start = None
    for idx, block in enumerate(parser.blocks):
        value = fold(block)
        if any(term in value for term in identities):
            start = idx
            break
    if start is None:
        raise ValueError("hospital identity missing from source page")

    region: list[str] = []
    for block in parser.blocks[start:]:
        value = fold(block)
        if region and any(term in value for term in REGION_END_TERMS):
            break
        region.append(block)
        if len(region) >= 72:
            break
    text = clean(" ".join(region))
    if len(text) < 80:
        raise ValueError("hospital registry region unexpectedly small")
    if not any(term in fold(text) for term in identities):
        raise ValueError("hospital identity missing from bounded registry region")
    return text


def placeholder(text: str) -> bool:
    value = fold(text)[:6000]
    return any(term in value for term in PLACEHOLDER_TERMS)


def evidence_around(text: str, term: str, radius: int = 170) -> str:
    folded_text = fold(text)
    folded_term = fold(term)
    pos = folded_text.find(folded_term)
    if pos < 0:
        return clean(text)[:360]
    start = max(0, pos - radius)
    end = min(len(text), pos + len(term) + radius)
    return clean(text[start:end])[:420]


def deterministic_signal_id(hospital_key: str, signal_class: str, label: str) -> str:
    digest = hashlib.sha256(f"{hospital_key}\0{signal_class}\0{label}".encode("utf-8")).hexdigest()[:20]
    return f"msvlh-{hospital_key}-{signal_class.lower().replace('_', '-')}-{digest}"


def make_signal(
    hospital_key: str,
    profile: dict[str, Any],
    signal_class: str,
    payload_sha256: str,
    region: str,
    *,
    label: str,
    value: Optional[str] = None,
    evidence_term: Optional[str] = None,
    hold_reason: Optional[str] = None,
) -> HospitalNetworkReferenceSignal:
    return HospitalNetworkReferenceSignal(
        signal_id=deterministic_signal_id(hospital_key, signal_class, label),
        source_id=str(profile["source_id"]),
        taxonomy_version=TAXONOMY_VERSION,
        signal_class=signal_class,
        source_tier=SOURCE_TIER,
        source_name=str(profile["source_name"]),
        source_url=source_url(profile),
        payload_sha256=payload_sha256,
        evidence_excerpt="" if hold_reason else evidence_around(region, evidence_term or label),
        hold_reason=hold_reason,
        hospital_key=None if hold_reason else hospital_key,
        reference_label=None if hold_reason else label,
        reference_value=None if hold_reason else value,
    )


def analyze(
    hospital_key: str,
    html_text: str,
    raw_payload: bytes,
    observed_source_url: Optional[str] = None,
) -> list[HospitalNetworkReferenceSignal]:
    if hospital_key not in SOURCE_PROFILES:
        raise ValueError(f"unknown hospital key: {hospital_key}")
    profile = SOURCE_PROFILES[hospital_key]
    validate_source_url(observed_source_url or source_url(profile), profile)
    if placeholder(html_text):
        raise ValueError("placeholder/challenge page refused")
    region = extract_hospital_region(html_text, profile)
    folded = f" {fold(region)} "
    payload_sha256 = hashlib.sha256(raw_payload).hexdigest()

    if any(term in folded for term in SENSITIVE_TERMS):
        return [
            make_signal(
                hospital_key,
                profile,
                "HOLD_SENSITIVE_PATIENT_REFERENCE",
                payload_sha256,
                region,
                label="sensitive-patient-material",
                hold_reason="PATIENT_IDENTIFIABLE_OR_CASE_SPECIFIC_MATERIAL",
            )
        ]

    signals: list[HospitalNetworkReferenceSignal] = [
        make_signal(
            hospital_key,
            profile,
            "HOSPITAL_PROFILE_REFERENCE",
            payload_sha256,
            region,
            label=str(profile["profile_label"]),
            evidence_term=str(profile["identity_terms"][0]),
        )
    ]

    locality_hit = next((term for term in profile["locality_terms"] if fold(term) in folded), None)
    if locality_hit:
        signals.append(
            make_signal(
                hospital_key,
                profile,
                "HOSPITAL_LOCATION_REFERENCE",
                payload_sha256,
                region,
                label=f"{hospital_key}-registered-locality",
                value=locality_hit,
                evidence_term=locality_hit,
            )
        )

    bed_match = BED_RE.search(region)
    if bed_match:
        signals.append(
            make_signal(
                hospital_key,
                profile,
                "HOSPITAL_REGISTERED_CAPACITY_REFERENCE",
                payload_sha256,
                region,
                label="registered-bed-count",
                value=bed_match.group(1),
                evidence_term=bed_match.group(0),
            )
        )

    for signal_class, terms in SERVICE_RULES:
        hit = next((term for term in terms if fold(term) in folded), None)
        if hit:
            signals.append(
                make_signal(
                    hospital_key,
                    profile,
                    signal_class,
                    payload_sha256,
                    region,
                    label=signal_class.removesuffix("_REFERENCE").lower(),
                    evidence_term=hit,
                )
            )

    if len(signals) > MAX_SIGNALS_PER_SOURCE:
        raise ValueError("signal count exceeds cap")
    return signals


def serialize(signals: list[HospitalNetworkReferenceSignal]) -> str:
    return json.dumps([asdict(item) for item in signals], ensure_ascii=False, indent=2, sort_keys=True)


def _sample(identity: str, locality: str, beds: int, services: str) -> str:
    return f"""<!doctype html><html><body>
    <nav>Ministerul Sănătății Unități sanitare</nav>
    <h1>{identity}</h1>
    <p>Strada Spitalului nr. 1, {locality}, județul Vâlcea</p>
    <p>{identity} are un numar de {beds} paturi in urmatoarele specialitati medicale: {services}.</p>
    <h2>Alte unități din Vâlcea</h2>
    <p>Spitalul Judetean de Urgenta Valcea</p>
    <h3>Detalii spital</h3>
    </body></html>"""


def self_test() -> None:
    fixtures = {
        "dragasani": _sample(
            'Spitalul Municipal "Costache Nicolescu" Dragasani', "Dragasani", 246,
            "Medicina Interna, Neurologie, Chirurgie Generala, Obstretica-Ginecologie, ATI, Pediatrie, Psihiatrie, Boli infectioase, Laborator analize medicale si Laborator radiologie",
        ),
        "horezu": _sample(
            "Spitalul Orasenesc Horezu", "Horezu", 160,
            "Medicina Interna, Neurologie, Chirurgie Generala, Obstretica-Ginecologie, ATI, Pediatrie, Psihiatrie, Boli infectioase, Laborator analize medicale si Laborator radiologie, Ambulatoriu de specialitate",
        ),
        "brezoi": _sample(
            "Spitalul Orasenesc Brezoi", "Brezoi", 67,
            "Medicina Interna, Neurologie, Chirurgie Generala, Obstretica-Ginecologie, ATI, Pediatrie, Psihiatrie, Boli infectioase, Laborator analize medicale, Laborator radiologie si Ambulatoriu integrat",
        ),
        "dragoesti": _sample(
            "Spitalul de psihiatrie Dragoesti", "Dragoesti", 125,
            "Psihiatrie, Laborator de analize medicale si ambulatoriu",
        ),
        "mihaesti_pneumo": _sample(
            'Spitalul de Pneumoftiziologie "Constantin Anastasatu"', "Mihaesti", 148,
            "Pneumologie, Laborator de analize medicale si ambulatoriu integrat",
        ),
    }
    for key, sample in fixtures.items():
        items = analyze(key, sample, sample.encode("utf-8"))
        classes = {item.signal_class for item in items}
        assert "HOSPITAL_PROFILE_REFERENCE" in classes, (key, classes)
        assert "HOSPITAL_LOCATION_REFERENCE" in classes, (key, classes)
        assert "HOSPITAL_REGISTERED_CAPACITY_REFERENCE" in classes, (key, classes)
        assert all(item.publication_authority == "NONE" for item in items)
        assert all(not item.current_service_status_claim_allowed for item in items)
        assert all(not item.appointment_availability_claim_allowed for item in items)
        assert all(not item.bed_availability_claim_allowed for item in items)
        assert all(not item.emergency_load_claim_allowed for item in items)
        assert all(not item.on_call_staffing_claim_allowed for item in items)
        assert all(not item.public_projection_allowed for item in items)

    held_source = fixtures["brezoi"].replace(
        "<h2>Alte unități din Vâlcea</h2>",
        "<p>Lista pacient: Nume pacient; CNP 1234567890123</p><h2>Alte unități din Vâlcea</h2>",
    )
    held = analyze("brezoi", held_source, held_source.encode("utf-8"))
    assert len(held) == 1
    assert held[0].signal_class == "HOLD_SENSITIVE_PATIENT_REFERENCE"
    assert held[0].evidence_excerpt == ""
    assert held[0].hospital_key is None
    assert held[0].reference_label is None
    assert held[0].reference_value is None

    profile = SOURCE_PROFILES["horezu"]
    for bad in (
        "http://www.ms.ro/ro/unitati-sanitare/spitalul-orasenesc-horezu/",
        "https://www.ms.ro/ro/unitati-sanitare/",
        "https://evil.example/ro/unitati-sanitare/spitalul-orasenesc-horezu/",
        source_url(profile) + "?preview=1",
        source_url(SOURCE_PROFILES["brezoi"]),
    ):
        try:
            validate_source_url(bad, profile)
        except ValueError:
            pass
        else:
            raise AssertionError(f"bad source URL accepted: {bad}")

    try:
        analyze("horezu", fixtures["brezoi"], fixtures["brezoi"].encode("utf-8"))
    except ValueError as exc:
        assert "identity" in str(exc)
    else:
        raise AssertionError("cross-hospital identity mismatch accepted")

    try:
        analyze("unknown", "<html></html>", b"x")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown hospital key accepted")

    print("ok: 5 Ministry hospital registry surfaces; fail-closed invariants intact")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--hospital", choices=tuple(SOURCE_PROFILES), default=None)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0

    keys = [args.hospital] if args.hospital else list(SOURCE_PROFILES)
    all_signals: list[HospitalNetworkReferenceSignal] = []
    for key in keys:
        profile = SOURCE_PROFILES[key]
        final_url, html_text, raw = fetch_html(profile)
        all_signals.extend(analyze(key, html_text, raw, final_url))
    print(serialize(all_signals))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        print(f"fail-closed: {exc}", file=sys.stderr)
        raise SystemExit(2)
