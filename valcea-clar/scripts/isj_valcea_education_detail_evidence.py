#!/usr/bin/env python3
"""Bounded first-party detail evidence for high-value ISJ Vâlcea references.

This verifier consumes the existing ISJ Vâlcea index-reference adapter, then reads
only allow-listed first-party detail/document targets for high-value education
items. A successful read proves only the identity and bytes observed at that URL;
it does not authorize admission capacity, exam results, vacancies, deadlines,
eligibility, school status, Fact Kernel writes, Editorial Writer use or publishing.
External document hosts remain discovery-only and are never fetched here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from isj_valcea_education_reference_adapter import (
    ALLOWED_SOURCE_HOSTS,
    build_live_receipt,
)

SCHEMA = "ISJ_VALCEA_EDUCATION_DETAIL_EVIDENCE_V1"
PARSER_VERSION = "ISJ_VALCEA_EDUCATION_DETAIL_EVIDENCE_2026_09_02"
SOURCE_FAMILY = "ISJ_VALCEA_EDUCATION"
AUTHORITY_CLASS = "FIRST_PARTY_COUNTY_EDUCATION_DETAIL_EVIDENCE"
OBSERVATION_STATE = "DETAIL_EVIDENCE_NON_AUTHORIZING"
HIGH_VALUE_TOPICS = {"ADMISSIONS", "EXAMS_RESULTS", "STAFFING_MANAGEMENT"}
MAX_DETAILS = 12
MAX_BYTES = 3_000_000
ALLOWED_CONTENT_TYPES = {
    "text/html",
    "text/plain",
    "application/pdf",
    "application/octet-stream",
}

NON_AUTHORIZING_FLAGS = {
    "material_fact_use": False,
    "admission_capacity_authorized": False,
    "exam_result_authorized": False,
    "current_vacancy_authorized": False,
    "deadline_authorized": False,
    "eligibility_authorized": False,
    "school_status_authorized": False,
    "same_item_dedupe_authorized": False,
    "breaking_authorized": False,
    "fact_kernel_write_authorized": False,
    "editorial_writer_authorized": False,
    "publication_authorized": False,
    "distribution_authorized": False,
    "runtime_persistence_authorized": False,
}


@dataclass(frozen=True)
class DetailEvidence:
    topic_class: str
    index_title: str
    detail_url: str
    detail_host: str
    content_type: str
    content_length: int
    detail_sha256: str
    index_evidence_sha256: str
    visible_title: str | None
    explicit_date_text: str | None
    evidence_fragments: tuple[str, ...]
    verification_state: str
    authority_class: str = AUTHORITY_CLASS
    observation_state: str = OBSERVATION_STATE
    parser_version: str = PARSER_VERSION


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._title = False
        self.title_parts: list[str] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if name in {"script", "style", "noscript", "svg"}:
            self._skip += 1
        if name == "title" and self._skip == 0:
            self._title = True

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name == "title":
            self._title = False
        if name in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = " ".join(data.split())
        if not text:
            return
        self.parts.append(text)
        if self._title:
            self.title_parts.append(text)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_first_party_target(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host not in ALLOWED_SOURCE_HOSTS:
        raise ValueError("detail_target_not_first_party_https")
    if parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError("detail_target_identity_invalid")
    return urlunsplit(("https", host, parts.path or "/", parts.query, ""))


def _validate_final_url(requested: str, final: str) -> str:
    expected = urlsplit(_canonical_first_party_target(requested))
    observed_url = _canonical_first_party_target(final)
    observed = urlsplit(observed_url)
    if observed.path != expected.path or observed.query != expected.query:
        raise RuntimeError("detail_redirect_changed_resource_identity")
    return observed_url


def _content_type(raw: str | None) -> str:
    return str(raw or "").split(";", 1)[0].strip().lower()


def _extract_html_evidence(body: bytes, index_title: str) -> tuple[str | None, str | None, tuple[str, ...]]:
    parser = VisibleTextParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    visible = " ".join(parser.parts)
    visible = " ".join(visible.split())
    title = " ".join(parser.title_parts).strip() or None

    date_match = re.search(
        r"\b(?:0?[1-9]|[12][0-9]|3[01])[.\-/](?:0?[1-9]|1[0-2])[.\-/](?:20\d{2})\b|"
        r"\b(?:20\d{2})[-/](?:0[1-9]|1[0-2])[-/](?:0[1-9]|[12][0-9]|3[01])\b",
        visible,
    )
    explicit_date = date_match.group(0) if date_match else None

    keywords = [token for token in re.findall(r"[A-Za-zĂÂÎȘȚăâîșț0-9-]{4,}", index_title) if len(token) >= 5]
    fragments: list[str] = []
    lowered = visible.casefold()
    for keyword in keywords[:8]:
        pos = lowered.find(keyword.casefold())
        if pos < 0:
            continue
        start = max(0, pos - 120)
        end = min(len(visible), pos + len(keyword) + 220)
        fragment = " ".join(visible[start:end].split())
        if fragment and fragment not in fragments:
            fragments.append(fragment[:420])
        if len(fragments) >= 4:
            break
    return title, explicit_date, tuple(fragments)


def _fetch_detail(url: str, timeout: float = 20.0) -> tuple[bytes, str, str]:
    canonical = _canonical_first_party_target(url)
    request = Request(canonical, headers={"User-Agent": "CIVORA-Valcea-Clar-Source-Reference/1.0"})
    context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        final_url = _validate_final_url(canonical, response.geturl())
        status = getattr(response, "status", 200)
        if status != 200:
            raise RuntimeError(f"detail_http_status:{status}")
        ctype = _content_type(response.headers.get("Content-Type"))
        if ctype not in ALLOWED_CONTENT_TYPES:
            raise RuntimeError(f"detail_content_type_not_allowlisted:{ctype or 'missing'}")
        body = response.read(MAX_BYTES + 1)
        if not body or len(body) > MAX_BYTES:
            raise RuntimeError("detail_body_empty_or_too_large")
        return body, final_url, ctype


def build_live_receipt(require_detail: bool = False) -> dict[str, Any]:
    index = build_live_receipt_index()
    candidates = [
        ref for ref in index["references"]
        if ref.get("topic_class") in HIGH_VALUE_TOPICS and ref.get("target_is_first_party") is True
    ][:MAX_DETAILS]

    details: list[DetailEvidence] = []
    holds: list[dict[str, str]] = []
    for ref in candidates:
        try:
            body, final_url, ctype = _fetch_detail(str(ref["target_url"]))
            visible_title: str | None = None
            explicit_date: str | None = None
            fragments: tuple[str, ...] = ()
            state = "FIRST_PARTY_BYTES_HASHED_CONTENT_NOT_INTERPRETED"
            if ctype in {"text/html", "text/plain"}:
                visible_title, explicit_date, fragments = _extract_html_evidence(body, str(ref["title"]))
                state = "FIRST_PARTY_TEXT_EVIDENCE_CAPTURED_NON_AUTHORIZING"
            details.append(DetailEvidence(
                topic_class=str(ref["topic_class"]),
                index_title=str(ref["title"]),
                detail_url=final_url,
                detail_host=(urlsplit(final_url).hostname or "").lower(),
                content_type=ctype,
                content_length=len(body),
                detail_sha256=_sha256(body),
                index_evidence_sha256=str(ref["evidence_sha256"]),
                visible_title=visible_title,
                explicit_date_text=explicit_date,
                evidence_fragments=fragments,
                verification_state=state,
            ))
        except (HTTPError, URLError, OSError, RuntimeError, ValueError) as exc:
            holds.append({
                "target_url": str(ref.get("target_url") or ""),
                "index_evidence_sha256": str(ref.get("evidence_sha256") or ""),
                "state": "HOLD_DETAIL_FETCH_FAILED_NON_AUTHORIZING",
                "reason": f"{type(exc).__name__}:{exc}",
            })

    if require_detail and not details:
        raise RuntimeError("no_first_party_high_value_detail_evidence_captured")

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "PASS",
        "source_family": SOURCE_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "coverage_note": "BOUNDED_HIGH_VALUE_FIRST_PARTY_DETAIL_VERIFICATION_NOT_EXHAUSTIVE",
        "index_run_id": index.get("run_id"),
        "index_reference_count": index.get("reference_count", 0),
        "eligible_first_party_detail_count": len(candidates),
        "detail_evidence_count": len(details),
        "detail_hold_count": len(holds),
        "details": [asdict(item) for item in details],
        "holds": holds,
        "interpretation": (
            "FIRST_PARTY_DETAIL_BYTES_AND_EXPLICIT_TEXT_ARE_EVIDENCE_CONTEXT_ONLY;"
            "MATERIAL_FIELDS_REQUIRE_SEPARATE_FIELD_LEVEL_VERIFICATION"
        ),
        **NON_AUTHORIZING_FLAGS,
    }
    stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["run_id"] = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]
    return payload


def build_live_receipt_index() -> dict[str, Any]:
    """Narrow wrapper kept separate so deterministic tests can reason about the boundary."""
    return build_live_receipt(require_reference=True)


def _self_test() -> None:
    good = _canonical_first_party_target("https://www.isjvalcea.ro/docs/test.pdf?x=1#fragment")
    assert good == "https://www.isjvalcea.ro/docs/test.pdf?x=1"
    assert _validate_final_url(good, good) == good
    try:
        _canonical_first_party_target("https://drive.google.com/file/d/x")
    except ValueError:
        pass
    else:
        raise AssertionError("external document host must never be fetched")
    try:
        _validate_final_url(good, "https://www.isjvalcea.ro/docs/other.pdf?x=1")
    except RuntimeError:
        pass
    else:
        raise AssertionError("resource-changing redirect must fail closed")

    html = (
        "<html><head><title>Admitere 2026 - ISJ Valcea</title></head><body>"
        "<script>Rezultate false 01.01.2099</script>"
        "Admitere liceu - publicat 02.09.2026. Locuri libere pentru etapa urmatoare."
        "</body></html>"
    ).encode()
    title, date_text, fragments = _extract_html_evidence(html, "Locuri libere admitere liceu 2026")
    assert title == "Admitere 2026 - ISJ Valcea"
    assert date_text == "02.09.2026"
    assert fragments
    assert all(value is False for value in NON_AUTHORIZING_FLAGS.values())
    print("ISJ Vâlcea education detail evidence self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--live-check", action="store_true")
    parser.add_argument("--require-detail", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.self_test:
        _self_test()
        return 0
    if not args.live_check:
        parser.error("use --self-test or --live-check")
    try:
        payload = build_live_receipt(require_detail=args.require_detail)
    except (HTTPError, URLError, OSError, RuntimeError, ValueError) as exc:
        print(f"HOLD_SOURCE_FETCH_FAILED:{type(exc).__name__}:{exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
