#!/usr/bin/env python3
"""Bounded CFR Craiova DOCX scope validator for VÂLCEA CLAR.

Consumes reference-only metadata emitted by
`cfr_craiova_speed_restriction_reference_adapter.py`, selects the newest
reference deterministically, and may fetch/parse only that first-party CFR DOCX
to answer one narrow question: does the document explicitly mention a known
Vâlcea rail anchor?

A positive scope match is still reference-only. This module never extracts or
publishes speed values, kilometre positions, operational state, train impact,
delay, timetable changes, or "active now" claims.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import ssl
import sys
import unicodedata
import zipfile
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Optional
from urllib.parse import unquote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from xml.etree import ElementTree as ET

SOURCE_ID = "scope-cfr-srcf-craiova-valcea-bulletin-docx"
TAXONOMY_VERSION = "2026-08-31.1"
SOURCE_NAME = "CNCF CFR SA — SRCF Craiova bulletin Vâlcea scope validator"
SOURCE_TIER = "T1_OFFICIAL_RAIL_INFRASTRUCTURE"

UPSTREAM_SOURCE_ID = "reference-cfr-srcf-craiova-speed-restriction-bulletins"
UPSTREAM_TAXONOMY_VERSION = "2026-08-31.1"
UPSTREAM_REFERENCE_CLASS = "CFR_CRAIOVA_SPEED_RESTRICTION_BULLETIN_REFERENCE"

HOST = "cfr.ro"
DOCUMENT_PREFIX = "/wp-content/uploads/"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MAX_DOWNLOAD_BYTES = 8_000_000
MAX_ZIP_ENTRIES = 128
MAX_TOTAL_UNCOMPRESSED_BYTES = 18_000_000
MAX_ENTRY_UNCOMPRESSED_BYTES = 8_000_000
MAX_DOCUMENT_XML_BYTES = 7_000_000
TIMEOUT_SECONDS = 20
USER_AGENT = "CIVORA-ValceaClar-CFR-ValceaScope/1.0 (+evidence-first; contact via repository)"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CONTENT_TYPES_MAIN = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)

ANCHOR_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("RAMNICU_VALCEA", re.compile(r"\b(?:ramnicu|rm\.?)\s+valcea\b")),
    ("RAURENI", re.compile(r"\braureni\b")),
    ("BUJORENI_VALCEA", re.compile(r"\bbujoreni\s+valcea\b")),
    ("CALIMANESTI", re.compile(r"\bcalimanesti\b")),
    ("LOTRU", re.compile(r"\blotru\b")),
    ("COZIA", re.compile(r"\bcozia\b")),
)
LINE_201_RE = re.compile(r"\b(?:linia|linie|l\.?)\s*(?:nr\.?\s*)?201\b")
IDENTITY_TERMS = ("cfr", "craiova")


@dataclass(frozen=True)
class ScopeSignal:
    signal_id: str
    source_id: str
    taxonomy_version: str
    source_name: str
    source_tier: str
    upstream_source_id: str
    upstream_taxonomy_version: str
    upstream_signal_id: Optional[str]
    review_status: str
    scope_state: str
    period_start: Optional[str]
    period_end: Optional[str]
    document_url: Optional[str]
    document_sha256: Optional[str]
    document_text_sha256: Optional[str]
    matched_anchors: tuple[str, ...]
    line_201_mentioned: bool
    evidence_excerpt: str
    hold_reason: Optional[str]
    publication_authority: str = "NONE"
    scope_confirmation_only: bool = True
    speed_restriction_details_extracted: bool = False
    current_operational_status_inferred: bool = False
    delay_or_timetable_impact_inferred: bool = False
    train_specific_impact_inferred: bool = False
    breaking_news_promotion_allowed: bool = False
    inferred_photo_rights_allowed: bool = False
    persistence_allowed: bool = False
    fact_kernel_promotion_allowed: bool = False
    writer_allowed: bool = False
    public_projection_allowed: bool = False


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise ValueError(f"redirect refused: {newurl}")


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", clean(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_iso(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(clean(value))
    except ValueError:
        return None


def normalize_document_url(value: str) -> str:
    parsed = urlsplit(clean(value))
    path = re.sub(r"/+", "/", unquote(parsed.path or "/"))
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != HOST
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not path.startswith(DOCUMENT_PREFIX)
        or not path.casefold().endswith(".docx")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"off-surface CFR DOCX refused: {value}")
    return urlunsplit(("https", HOST, path, "", ""))


def held(reason: str, evidence: str = "", upstream_signal_id: Optional[str] = None) -> ScopeSignal:
    token = hashlib.sha256(
        f"{SOURCE_ID}\0{reason}\0{upstream_signal_id or ''}\0{evidence}".encode()
    ).hexdigest()[:20]
    return ScopeSignal(
        signal_id=f"cfr-valcea-scope-{token}",
        source_id=SOURCE_ID,
        taxonomy_version=TAXONOMY_VERSION,
        source_name=SOURCE_NAME,
        source_tier=SOURCE_TIER,
        upstream_source_id=UPSTREAM_SOURCE_ID,
        upstream_taxonomy_version=UPSTREAM_TAXONOMY_VERSION,
        upstream_signal_id=upstream_signal_id,
        review_status="HOLD",
        scope_state="UNKNOWN_FAIL_CLOSED",
        period_start=None,
        period_end=None,
        document_url=None,
        document_sha256=None,
        document_text_sha256=None,
        matched_anchors=(),
        line_201_mentioned=False,
        evidence_excerpt=clean(evidence)[:600],
        hold_reason=reason,
    )


def validate_reference(reference: dict[str, Any]) -> tuple[dict[str, Any], str, date, date]:
    if clean(reference.get("source_id")) != UPSTREAM_SOURCE_ID:
        raise ValueError("UPSTREAM_SOURCE_ID_DRIFT")
    if clean(reference.get("taxonomy_version")) != UPSTREAM_TAXONOMY_VERSION:
        raise ValueError("UPSTREAM_TAXONOMY_DRIFT")
    if clean(reference.get("reference_class")) != UPSTREAM_REFERENCE_CLASS:
        raise ValueError("UPSTREAM_REFERENCE_CLASS_DRIFT")
    if clean(reference.get("review_status")) != "REFERENCE_ONLY":
        raise ValueError("UPSTREAM_REFERENCE_NOT_RELEASED")
    if clean(reference.get("scope_state")) != "REGIONAL_REFERENCE_ONLY":
        raise ValueError("UPSTREAM_SCOPE_STATE_DRIFT")
    if clean(reference.get("document_format")) != "DOCX_REFERENCE_ONLY":
        raise ValueError("UPSTREAM_DOCUMENT_FORMAT_DRIFT")

    start = parse_iso(reference.get("period_start"))
    end = parse_iso(reference.get("period_end"))
    if not start or not end or start > end:
        raise ValueError("INVALID_UPSTREAM_PERIOD")

    document_url = normalize_document_url(clean(reference.get("document_url")))
    if document_url != clean(reference.get("document_url")):
        raise ValueError("NON_CANONICAL_UPSTREAM_DOCUMENT_URL")
    signal_id = clean(reference.get("signal_id"))
    if not signal_id:
        raise ValueError("MISSING_UPSTREAM_SIGNAL_ID")
    return reference, document_url, start, end


def select_latest_reference(payload: dict[str, Any]) -> dict[str, Any]:
    if clean(payload.get("status")) != "PASS":
        raise ValueError("UPSTREAM_ENVELOPE_NOT_PASS")
    if clean(payload.get("source_id")) != UPSTREAM_SOURCE_ID:
        raise ValueError("UPSTREAM_ENVELOPE_SOURCE_DRIFT")
    if clean(payload.get("taxonomy_version")) != UPSTREAM_TAXONOMY_VERSION:
        raise ValueError("UPSTREAM_ENVELOPE_TAXONOMY_DRIFT")
    raw_references = payload.get("references")
    if not isinstance(raw_references, list) or not raw_references:
        raise ValueError("UPSTREAM_REFERENCES_MISSING")

    validated: list[tuple[date, date, str, dict[str, Any]]] = []
    seen_periods: set[tuple[date, date]] = set()
    seen_signals: set[str] = set()
    for raw in raw_references:
        if not isinstance(raw, dict):
            raise ValueError("UPSTREAM_REFERENCE_SHAPE_INVALID")
        ref, document_url, start, end = validate_reference(raw)
        period_key = (start, end)
        signal_id = clean(ref.get("signal_id"))
        if period_key in seen_periods:
            raise ValueError("DUPLICATE_UPSTREAM_PERIOD")
        if signal_id in seen_signals:
            raise ValueError("DUPLICATE_UPSTREAM_SIGNAL_ID")
        seen_periods.add(period_key)
        seen_signals.add(signal_id)
        validated.append((start, end, document_url, ref))

    validated.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return validated[0][3]


def fetch_docx(document_url: str) -> bytes:
    normalized = normalize_document_url(document_url)
    request = Request(
        normalized,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": DOCX_CONTENT_TYPE,
        },
    )
    opener = build_opener(
        NoRedirects(), HTTPSHandler(context=ssl.create_default_context())
    )
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        content_type = clean(response.headers.get("Content-Type", "")).casefold()
        media_type = content_type.split(";", 1)[0].strip()
        if media_type != DOCX_CONTENT_TYPE:
            raise ValueError(
                f"unexpected DOCX content type: {content_type or 'missing'}"
            )
        payload = response.read(MAX_DOWNLOAD_BYTES + 1)
        if len(payload) > MAX_DOWNLOAD_BYTES:
            raise ValueError("CFR DOCX exceeds bounded response size")
        return payload


def _safe_zip_name(name: str) -> bool:
    if not name or "\\" in name or name.startswith("/"):
        return False
    path = PurePosixPath(name)
    return not any(part in ("", ".", "..") for part in path.parts)


def extract_docx_paragraphs(payload: bytes) -> list[str]:
    if not payload or len(payload) > MAX_DOWNLOAD_BYTES:
        raise ValueError("DOCX_SIZE_OUT_OF_BOUNDS")
    stream = io.BytesIO(payload)
    if not zipfile.is_zipfile(stream):
        raise ValueError("NOT_A_DOCX_ZIP")
    stream.seek(0)

    with zipfile.ZipFile(stream) as archive:
        infos = archive.infolist()
        if not infos or len(infos) > MAX_ZIP_ENTRIES:
            raise ValueError("DOCX_ENTRY_COUNT_OUT_OF_BOUNDS")

        total_uncompressed = 0
        names: set[str] = set()
        for info in infos:
            if not _safe_zip_name(info.filename):
                raise ValueError("UNSAFE_DOCX_ZIP_PATH")
            if info.filename in names:
                raise ValueError("DUPLICATE_DOCX_ZIP_ENTRY")
            names.add(info.filename)
            if info.flag_bits & 0x1:
                raise ValueError("ENCRYPTED_DOCX_NOT_ALLOWED")
            if info.file_size > MAX_ENTRY_UNCOMPRESSED_BYTES:
                raise ValueError("DOCX_ENTRY_TOO_LARGE")
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_TOTAL_UNCOMPRESSED_BYTES:
                raise ValueError("DOCX_UNCOMPRESSED_SIZE_OUT_OF_BOUNDS")

        required = {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}
        if not required.issubset(names):
            raise ValueError("DOCX_REQUIRED_PART_MISSING")

        content_types = archive.read("[Content_Types].xml")
        if CONTENT_TYPES_MAIN.encode("ascii") not in content_types:
            raise ValueError("DOCX_MAIN_CONTENT_TYPE_MISSING")

        document_xml = archive.read("word/document.xml")
        if len(document_xml) > MAX_DOCUMENT_XML_BYTES:
            raise ValueError("DOCX_DOCUMENT_XML_TOO_LARGE")
        upper_xml = document_xml.upper()
        if b"<!DOCTYPE" in upper_xml or b"<!ENTITY" in upper_xml:
            raise ValueError("DOCX_XML_DTD_OR_ENTITY_REFUSED")

        try:
            root = ET.fromstring(document_xml)
        except ET.ParseError as exc:
            raise ValueError("DOCX_DOCUMENT_XML_INVALID") from exc

        paragraphs: list[str] = []
        for paragraph in root.iter(f"{{{W_NS}}}p"):
            parts = [
                node.text or ""
                for node in paragraph.iter(f"{{{W_NS}}}t")
                if node.text
            ]
            value = clean(" ".join(parts))
            if value:
                paragraphs.append(value)
        if not paragraphs:
            raise ValueError("DOCX_DOCUMENT_TEXT_EMPTY")
        return paragraphs


def classify_scope(reference: dict[str, Any], payload: bytes) -> ScopeSignal:
    ref, document_url, start, end = validate_reference(reference)
    paragraphs = extract_docx_paragraphs(payload)
    folded_paragraphs = [fold(item) for item in paragraphs]
    folded_text = "\n".join(folded_paragraphs)

    if not any(term in folded_text for term in IDENTITY_TERMS):
        return held(
            "DOCX_SOURCE_IDENTITY_DRIFT",
            " ".join(paragraphs[:8]),
            clean(ref.get("signal_id")),
        )

    matches: list[str] = []
    evidence = ""
    for anchor_name, pattern in ANCHOR_PATTERNS:
        for original, normalized in zip(paragraphs, folded_paragraphs):
            if pattern.search(normalized):
                matches.append(anchor_name)
                if not evidence:
                    evidence = original
                break

    unique_matches = tuple(dict.fromkeys(matches))
    line_201 = bool(LINE_201_RE.search(folded_text))
    scope_state = (
        "VALCEA_EXPLICIT_DOCUMENT_REFERENCE"
        if unique_matches
        else "REGIONAL_REFERENCE_ONLY"
    )
    review_status = (
        "SCOPE_CONFIRMED_REFERENCE_ONLY"
        if unique_matches
        else "REFERENCE_ONLY"
    )

    document_hash = sha256_bytes(payload)
    text_value = "\n".join(paragraphs)
    token = hashlib.sha256(
        (
            f"{SOURCE_ID}\0{clean(ref.get('signal_id'))}\0{document_hash}\0"
            f"{scope_state}\0{','.join(unique_matches)}"
        ).encode()
    ).hexdigest()[:20]

    return ScopeSignal(
        signal_id=f"cfr-valcea-scope-{token}",
        source_id=SOURCE_ID,
        taxonomy_version=TAXONOMY_VERSION,
        source_name=SOURCE_NAME,
        source_tier=SOURCE_TIER,
        upstream_source_id=UPSTREAM_SOURCE_ID,
        upstream_taxonomy_version=UPSTREAM_TAXONOMY_VERSION,
        upstream_signal_id=clean(ref.get("signal_id")),
        review_status=review_status,
        scope_state=scope_state,
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        document_url=document_url,
        document_sha256=document_hash,
        document_text_sha256=sha256_text(text_value),
        matched_anchors=unique_matches,
        line_201_mentioned=line_201,
        evidence_excerpt=clean(evidence)[:600],
        hold_reason=None,
    )


def envelope(signal: ScopeSignal) -> dict[str, Any]:
    status = "HOLD" if signal.review_status == "HOLD" else "PASS"
    return {
        "status": status,
        "source_id": SOURCE_ID,
        "taxonomy_version": TAXONOMY_VERSION,
        "source_name": SOURCE_NAME,
        "source_tier": SOURCE_TIER,
        "signal": asdict(signal),
        "safety": {
            "server_side_docx_fetch_allowed": True,
            "bounded_docx_body_parse_allowed": True,
            "scope_confirmation_only": True,
            "speed_restriction_details_extracted": False,
            "current_operational_status_inferred": False,
            "delay_or_timetable_impact_inferred": False,
            "train_specific_impact_inferred": False,
            "breaking_news_promotion_allowed": False,
            "inferred_photo_rights_allowed": False,
            "persistence_allowed": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "public_projection_allowed": False,
        },
    }


def _sample_reference(
    document_url: str = "https://cfr.ro/wp-content/uploads/2026/08/craiova-2.docx",
    period_start: str = "2026-09-01",
    period_end: str = "2026-09-10",
    signal_id: str = "cfr-craiova-fixture",
) -> dict[str, Any]:
    return {
        "signal_id": signal_id,
        "source_id": UPSTREAM_SOURCE_ID,
        "taxonomy_version": UPSTREAM_TAXONOMY_VERSION,
        "reference_class": UPSTREAM_REFERENCE_CLASS,
        "review_status": "REFERENCE_ONLY",
        "scope_state": "REGIONAL_REFERENCE_ONLY",
        "period_start": period_start,
        "period_end": period_end,
        "document_url": document_url,
        "document_format": "DOCX_REFERENCE_ONLY",
    }


def _make_docx(paragraphs: Iterable[str], identity: str = "Regionala CFR Craiova") -> bytes:
    all_paragraphs = [identity, *paragraphs]
    body = "".join(
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
        for text in all_paragraphs
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W_NS}"><w:body>{body}</w:body></w:document>'
    ).encode("utf-8")
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        f'<Override PartName="/word/document.xml" ContentType="{CONTENT_TYPES_MAIN}"/>'
        "</Types>"
    ).encode("utf-8")
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    ).encode("utf-8")

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document_xml)
    return output.getvalue()


def run_self_test() -> None:
    reference = _sample_reference()
    valcea_docx = _make_docx(
        [
            "Linia 201",
            "Interval Călimănești - Lotru",
            "Buletin pentru verificare internă.",
        ]
    )
    signal = classify_scope(reference, valcea_docx)
    assert signal.review_status == "SCOPE_CONFIRMED_REFERENCE_ONLY"
    assert signal.scope_state == "VALCEA_EXPLICIT_DOCUMENT_REFERENCE"
    assert set(signal.matched_anchors) == {"CALIMANESTI", "LOTRU"}
    assert signal.line_201_mentioned is True
    assert signal.current_operational_status_inferred is False
    assert signal.public_projection_allowed is False

    line_only = classify_scope(
        reference,
        _make_docx(["Linia 201", "Piatra Olt - Sibiu"]),
    )
    assert line_only.scope_state == "REGIONAL_REFERENCE_ONLY"
    assert line_only.line_201_mentioned is True
    assert not line_only.matched_anchors

    ramnicu = classify_scope(
        reference,
        _make_docx(["Stația Râmnicu Vâlcea"]),
    )
    assert ramnicu.matched_anchors == ("RAMNICU_VALCEA",)

    broad_county_only = classify_scope(
        reference,
        _make_docx(["Județul Vâlcea"]),
    )
    assert broad_county_only.scope_state == "REGIONAL_REFERENCE_ONLY"

    payload = {
        "status": "PASS",
        "source_id": UPSTREAM_SOURCE_ID,
        "taxonomy_version": UPSTREAM_TAXONOMY_VERSION,
        "references": [
            _sample_reference(
                "https://cfr.ro/wp-content/uploads/2026/08/craiova-1.docx",
                "2026-08-21",
                "2026-08-31",
                "cfr-craiova-fixture-prior",
            ),
            reference,
        ],
    }
    assert select_latest_reference(payload)["signal_id"] == "cfr-craiova-fixture"

    duplicate_period = dict(payload)
    duplicate_period["references"] = [reference, dict(reference)]
    try:
        select_latest_reference(duplicate_period)
    except ValueError as exc:
        assert str(exc) == "DUPLICATE_UPSTREAM_PERIOD"
    else:
        raise AssertionError("duplicate period must fail closed")

    off_host = dict(reference)
    off_host["document_url"] = "https://example.org/craiova.docx"
    try:
        validate_reference(off_host)
    except ValueError as exc:
        assert "off-surface CFR DOCX refused" in str(exc)
    else:
        raise AssertionError("off-host document must fail closed")

    drift = dict(reference)
    drift["taxonomy_version"] = "2026-08-30.9"
    try:
        validate_reference(drift)
    except ValueError as exc:
        assert str(exc) == "UPSTREAM_TAXONOMY_DRIFT"
    else:
        raise AssertionError("taxonomy drift must fail closed")

    identity_drift = classify_scope(
        reference,
        _make_docx(["Linia 201", "Călimănești - Lotru"], identity="Alt operator"),
    )
    assert identity_drift.review_status == "HOLD"
    assert identity_drift.hold_reason == "DOCX_SOURCE_IDENTITY_DRIFT"

    unsafe = io.BytesIO()
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("../word/document.xml", b"x")
    try:
        extract_docx_paragraphs(unsafe.getvalue())
    except ValueError as exc:
        assert str(exc) == "UNSAFE_DOCX_ZIP_PATH"
    else:
        raise AssertionError("unsafe ZIP path must fail closed")

    safety = envelope(signal)["safety"]
    assert safety["server_side_docx_fetch_allowed"] is True
    assert safety["bounded_docx_body_parse_allowed"] is True
    for key in (
        "speed_restriction_details_extracted",
        "current_operational_status_inferred",
        "delay_or_timetable_impact_inferred",
        "train_specific_impact_inferred",
        "breaking_news_promotion_allowed",
        "inferred_photo_rights_allowed",
        "persistence_allowed",
        "fact_kernel_promotion_allowed",
        "writer_allowed",
        "public_projection_allowed",
    ):
        assert safety[key] is False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--reference-json", type=Path)
    parser.add_argument("--docx-file", type=Path)
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        print(
            json.dumps(
                {"status": "PASS", "self_test": True, "source_id": SOURCE_ID},
                ensure_ascii=False,
            )
        )
        return 0

    if not args.reference_json:
        print(
            json.dumps(
                envelope(held("REFERENCE_JSON_REQUIRED", "Use --reference-json")),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    try:
        payload = json.loads(args.reference_json.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("UPSTREAM_ENVELOPE_SHAPE_INVALID")
        reference = select_latest_reference(payload)
        document_url = normalize_document_url(clean(reference.get("document_url")))
        docx_payload = (
            args.docx_file.read_bytes()
            if args.docx_file
            else fetch_docx(document_url)
        )
        output = envelope(classify_scope(reference, docx_payload))
    except Exception as exc:
        upstream_signal_id = None
        try:
            upstream_signal_id = clean(reference.get("signal_id"))  # type: ignore[name-defined]
        except Exception:
            pass
        output = envelope(held("FETCH_OR_SCOPE_PARSE_FAILURE", repr(exc), upstream_signal_id))

    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if output["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
