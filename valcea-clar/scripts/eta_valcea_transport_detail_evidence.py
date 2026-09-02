#!/usr/bin/env python3
"""Bounded first-party ETA Râmnicu Vâlcea transport detail evidence.

This verifier follows only allow-listed ETA S.A. communication URLs already
discovered by the ETA transport reference adapter. It hashes exact detail bytes
and captures bounded evidence fragments with explicit tags for service changes,
disruptions, fares, passenger entitlements, effective/validity windows and
operator-policy basis.

Every fragment remains an ETA first-party statement. It is source evidence, not
proof that a route, timetable, fare, entitlement, disruption or arrival state
is current. Historical notices remain date-bounded and never authorize Fact
Kernel writes, Editorial Writer use, publication, distribution or runtime
persistence.
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
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from eta_valcea_transport_reference_adapter import (
    ALLOWED_HOSTS,
    SOURCE_URL,
    build_receipt as build_index_receipt,
)

SCHEMA = "ETA_VALCEA_TRANSPORT_DETAIL_EVIDENCE_V1"
PARSER_VERSION = "ETA_VALCEA_TRANSPORT_DETAIL_EVIDENCE_2026_09_02"
SOURCE_FAMILY = "ETA_VALCEA_PUBLIC_TRANSPORT"
AUTHORITY_CLASS = "FIRST_PARTY_LOCAL_PUBLIC_TRANSPORT_OPERATOR_DETAIL_EVIDENCE"
OBSERVATION_STATE = "ETA_SOURCE_DETAIL_EVIDENCE_NON_AUTHORIZING"
SOURCE_ASSERTION_SCOPE = "ETA_FIRST_PARTY_STATEMENT_ONLY_CURRENTNESS_NOT_INFERRED"

HIGH_VALUE_TOPICS = {
    "ROUTE_CHANGE",
    "SERVICE_DISRUPTION",
    "EVENT_TRANSPORT",
    "FARE_TICKETING",
    "PASSENGER_ENTITLEMENT",
    "ACCESSIBILITY",
}
MAX_DETAILS = 10
MAX_BYTES = 2_500_000
MAX_FIELD_EVIDENCE = 12
MAX_FRAGMENT_CHARS = 520
ALLOWED_CONTENT_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}
USER_AGENT = "CIVORA-Valcea-Clar-ETA-Detail-Evidence/1.0"

NON_AUTHORIZING_FLAGS = {
    "material_fact_use": False,
    "independent_fact_verification_authorized": False,
    "route_service_current_authorized": False,
    "timetable_current_authorized": False,
    "fare_current_authorized": False,
    "ticketing_current_authorized": False,
    "passenger_entitlement_current_authorized": False,
    "service_disruption_current_authorized": False,
    "realtime_arrival_authorized": False,
    "policy_or_hcl_current_authorized": False,
    "same_event_dedupe_authorized": False,
    "breaking_authorized": False,
    "fact_kernel_write_authorized": False,
    "editorial_writer_authorized": False,
    "publication_authorized": False,
    "distribution_authorized": False,
    "runtime_persistence_authorized": False,
}

TAG_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "ROUTE_OR_STOP_CHANGE",
        (
            "deviere",
            "traseu modificat",
            "trasee modificate",
            "redirecțion",
            "redirection",
            "stație temporară",
            "statie temporara",
            "stația",
            "statia",
            "stații",
            "statii",
            "linia ",
            "liniei ",
        ),
    ),
    (
        "SERVICE_DISRUPTION_WINDOW",
        (
            "întrerup",
            "intrerup",
            "suspend",
            "nu vor circula",
            "nu circulă",
            "nu circula",
            "indisponibil",
            "mentenan",
            "upgrade",
            "anomalii",
            "temporar",
            "temporară",
            "temporara",
            "perioada ",
            "în perioada",
            "in perioada",
        ),
    ),
    (
        "FARE_OR_TICKETING",
        (
            "tarif",
            "bilet",
            "abonament",
            "supratax",
            "titlu de călătorie",
            "titlu de calatorie",
            "24pay",
            "24 pay",
            "card bancar",
            "validator",
            "plata cu sms",
            "plată cu sms",
            "portal on line",
            "portal online",
            "lei",
        ),
    ),
    (
        "PASSENGER_ENTITLEMENT",
        (
            "gratuit",
            "gratuitate",
            "reducere",
            "reduse 50%",
            "pensionar",
            "elev",
            "student",
            "62 de ani",
            "62 ani",
            "donator",
            "beneficia",
        ),
    ),
    (
        "EFFECTIVE_DATE_OR_VALIDITY_WINDOW",
        (
            "începând cu",
            "incepand cu",
            "valabil",
            "valabilitate",
            "publicat la",
            "în data de",
            "in data de",
            "în perioada",
            "in perioada",
            "începând din",
            "incepand din",
            "luna ",
        ),
    ),
    (
        "APPROVAL_OR_POLICY_BASIS",
        (
            "hotărâre de consiliu local",
            "hotarare de consiliu local",
            "hotărârea de consiliu local",
            "hotararea de consiliu local",
            "hcl ",
            "aprobat prin",
            "aprobată prin",
            "aprobata prin",
        ),
    ),
    (
        "ACCESSIBILITY_OR_BOARDING",
        (
            "dizabil",
            "deficienț",
            "deficient",
            "accesibil",
            "nevăzător",
            "nevazator",
            "rampă",
            "rampa",
            "îmbarcare",
            "imbarcare",
        ),
    ),
)
ALLOWED_TAGS = {tag for tag, _ in TAG_RULES} | {"REPORTED_NUMERIC_SERVICE_VALUE"}

NUMERIC_CONTEXT_NEEDLES = (
    "tarif",
    "bilet",
    "abonament",
    "lei",
    "călător",
    "calator",
    "traseu",
    "linie",
    "stați",
    "stati",
    "gratuit",
    "reduc",
    "pensionar",
    "valabil",
    "validator",
)

ROMANIAN_MONTH_PATTERN = (
    r"ian(?:uarie)?|feb(?:ruarie)?|mar(?:tie)?|apr(?:ilie)?|mai|"
    r"iun(?:ie)?|iul(?:ie)?|aug(?:ust)?|sep(?:tembrie)?|sept(?:embrie)?|"
    r"oct(?:ombrie)?|nov(?:iembrie)?|dec(?:embrie)?"
)


@dataclass(frozen=True)
class FieldEvidence:
    excerpt: str
    epistemic_tags: tuple[str, ...]
    evidence_sha256: str
    source_assertion_scope: str = SOURCE_ASSERTION_SCOPE


@dataclass(frozen=True)
class DetailEvidence:
    source_kind: str
    topic_class: str
    index_title: str
    detail_url: str
    detail_host: str
    content_type: str
    content_length: int
    detail_sha256: str
    index_evidence_sha256: str
    visible_title: str | None
    publication_date_text: str | None
    effective_date_text: str | None
    field_evidence: tuple[FieldEvidence, ...]
    tag_counts: dict[str, int]
    currentness_state: str
    verification_state: str
    authority_class: str = AUTHORITY_CLASS
    observation_state: str = OBSERVATION_STATE
    source_assertion_scope: str = SOURCE_ASSERTION_SCOPE
    parser_version: str = PARSER_VERSION


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.in_title = False
        self.h1_depth = 0
        self.tr_depth = 0
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.segments: list[str] = []
        self._row_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if name in {"script", "style", "noscript", "svg", "template"}:
            self.skip_depth += 1
        elif name == "title" and not self.skip_depth:
            self.in_title = True
        elif name == "h1" and not self.skip_depth:
            self.h1_depth += 1
        elif name == "tr" and not self.skip_depth:
            self.tr_depth += 1
            if self.tr_depth == 1:
                self._row_parts = []

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name == "title":
            self.in_title = False
        elif name == "h1" and self.h1_depth:
            self.h1_depth -= 1
        elif name == "tr" and self.tr_depth:
            if self.tr_depth == 1:
                row = " ".join(" ".join(self._row_parts).split())
                if row:
                    self.segments.append(row)
                self._row_parts = []
            self.tr_depth -= 1
        elif name in {"script", "style", "noscript", "svg", "template"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = " ".join(data.split())
        if not text:
            return
        self.segments.append(text)
        if self.in_title:
            self.title_parts.append(text)
        if self.h1_depth:
            self.h1_parts.append(text)
        if self.tr_depth:
            self._row_parts.append(text)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _expected_article_prefix() -> str:
    return urlsplit(SOURCE_URL).path.rstrip("/") + "/"


def _canonical_first_party_target(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host not in ALLOWED_HOSTS:
        raise ValueError("detail_target_not_first_party_https")
    if parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError("detail_target_identity_invalid")
    path = quote(parts.path or "/", safe="/%:@-._~!$&'()*+,;=")
    query = quote(parts.query, safe="=&;%:+,/?@-._~!$'()*")
    if not path.startswith(_expected_article_prefix()):
        raise ValueError("detail_target_outside_communications_section")
    if path.rstrip("/") == urlsplit(SOURCE_URL).path.rstrip("/"):
        raise ValueError("detail_target_is_index_not_article")
    return urlunsplit(("https", host, path, query, ""))


def _validate_final_url(requested: str, final: str) -> str:
    expected = urlsplit(_canonical_first_party_target(requested))
    observed_url = _canonical_first_party_target(final)
    observed = urlsplit(observed_url)
    if observed.path != expected.path or observed.query != expected.query:
        raise RuntimeError("detail_redirect_changed_resource_identity")
    return observed_url


def _find_publication_date(text: str) -> str | None:
    patterns = (
        rf"\bPublicat(?:ă)?\s+la:\s*(?:0?[1-9]|[12][0-9]|3[01])\s+(?:{ROMANIAN_MONTH_PATTERN})\s+20\d{{2}}\b",
        r"\bPublicat(?:ă)?\s+la:\s*(?:0?[1-9]|[12][0-9]|3[01])[.\-/](?:0?[1-9]|1[0-2])[.\-/]20\d{2}\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def _find_effective_date(text: str) -> str | None:
    patterns = (
        r"\b(?:începând|incepand)\s+cu\s+(?:data\s+de\s+)?(?:0?[1-9]|[12][0-9]|3[01])[.\-/](?:0?[1-9]|1[0-2])[.\-/]20\d{2}\b",
        rf"\b(?:începând|incepand)\s+(?:din|cu)\s+(?:luna\s+)?(?:{ROMANIAN_MONTH_PATTERN})\s+20\d{{2}}\b",
        r"\b(?:în|in)\s+perioada\s+(?:0?[1-9]|[12][0-9]|3[01])[.\-/](?:0?[1-9]|1[0-2])[.\-/]20\d{2}\s*[–—-]\s*(?:0?[1-9]|[12][0-9]|3[01])[.\-/](?:0?[1-9]|1[0-2])[.\-/]20\d{2}\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def _tags_for_fragment(fragment: str) -> tuple[str, ...]:
    lowered = fragment.casefold()
    tags: list[str] = []
    for tag, needles in TAG_RULES:
        if any(needle.casefold() in lowered for needle in needles):
            tags.append(tag)
    if re.search(r"\b\d[\d .,/%-]*\b", fragment) and any(
        needle.casefold() in lowered for needle in NUMERIC_CONTEXT_NEEDLES
    ):
        tags.append("REPORTED_NUMERIC_SERVICE_VALUE")
    return tuple(dict.fromkeys(tags))


def _split_candidate_fragments(segments: list[str]) -> list[str]:
    candidates: list[str] = []
    for segment in segments:
        for piece in re.split(r"(?<=[.!?])\s+|\s+[•|]\s+", segment):
            cleaned = " ".join(piece.split()).strip(" -–—")
            if 18 <= len(cleaned) <= 1800:
                candidates.append(cleaned)
    return candidates


def _extract_html_evidence(
    body: bytes,
    detail_sha256: str,
) -> tuple[str | None, str | None, str | None, tuple[FieldEvidence, ...], dict[str, int]]:
    parser = VisibleTextParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    h1 = " ".join(parser.h1_parts).strip()
    title = " ".join(parser.title_parts).strip()
    visible_title = h1 or title or None
    visible_text = " ".join(parser.segments)
    publication_date = _find_publication_date(visible_text)
    effective_date = _find_effective_date(visible_text)

    evidence: list[FieldEvidence] = []
    seen: set[str] = set()
    tag_counts: dict[str, int] = {}
    for fragment in _split_candidate_fragments(parser.segments):
        tags = _tags_for_fragment(fragment)
        if not tags:
            continue
        excerpt = fragment[:MAX_FRAGMENT_CHARS]
        normalized = " ".join(excerpt.casefold().split())
        if normalized in seen:
            continue
        seen.add(normalized)
        basis = json.dumps(
            {
                "detail_sha256": detail_sha256,
                "excerpt": excerpt,
                "epistemic_tags": tags,
                "source_assertion_scope": SOURCE_ASSERTION_SCOPE,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        evidence.append(
            FieldEvidence(
                excerpt=excerpt,
                epistemic_tags=tags,
                evidence_sha256=_sha256_text(basis),
            )
        )
        for tag in tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        if len(evidence) == MAX_FIELD_EVIDENCE:
            break
    return (
        visible_title,
        publication_date,
        effective_date,
        tuple(evidence),
        dict(sorted(tag_counts.items())),
    )


def _fetch_detail(url: str, timeout: float = 20.0) -> tuple[bytes, str, str]:
    canonical = _canonical_first_party_target(url)
    request = Request(
        canonical,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain",
        },
    )
    context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        final_url = _validate_final_url(canonical, response.geturl())
        status = getattr(response, "status", 200)
        if status != 200:
            raise RuntimeError(f"detail_http_status:{status}")
        content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise RuntimeError(f"detail_content_type_not_allowlisted:{content_type or 'missing'}")
        body = response.read(MAX_BYTES + 1)
        if not body or len(body) > MAX_BYTES:
            raise RuntimeError("detail_body_empty_or_too_large")
        normalized = body[:200_000].decode("utf-8", errors="replace").casefold()
        if "checking your browser" in normalized or "just a moment" in normalized:
            raise RuntimeError("detail_interstitial_detected")
        return body, final_url, content_type


def _eligible_reference(ref: dict[str, Any]) -> bool:
    if str(ref.get("source_kind") or "") != "COMMUNIQUES":
        return False
    return str(ref.get("topic_class") or "") in HIGH_VALUE_TOPICS


def _base_payload(status: str, index: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "status": status,
        "source_family": SOURCE_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "source_assertion_scope": SOURCE_ASSERTION_SCOPE,
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "coverage_note": "BOUNDED_FIRST_PARTY_ETA_TRANSPORT_COMMUNICATION_DETAIL_VERIFICATION_NOT_EXHAUSTIVE",
        "index_run_id": (index or {}).get("run_id"),
        "index_reference_count": (index or {}).get("reference_count", 0),
        "eligible_detail_count": 0,
        "detail_evidence_count": 0,
        "detail_hold_count": 0,
        "details": [],
        "holds": [],
        "limitations": {
            "eta_statement_is_not_independent_verification": True,
            "publication_or_effective_date_does_not_prove_current_status": True,
            "historical_notice_must_not_be_promoted_to_current_service_state": True,
            "route_or_stop_change_requires_current_detail_or_live_verification": True,
            "fare_or_ticketing_value_requires_current_detail_reconciliation": True,
            "passenger_entitlement_requires_current_policy_reconciliation": True,
            "service_disruption_requires_current_status_verification": True,
            "realtime_arrivals_require_separate_live_source": True,
            "sample_is_bounded_and_non_exhaustive": True,
        },
        "interpretation": (
            "DETAIL_BYTES_AND_TAGGED_ETA_SOURCE_FRAGMENTS_ARE_EVIDENCE_CONTEXT_ONLY;"
            "CURRENT_SERVICE_MATERIAL_FIELDS_REQUIRE_SEPARATE_RECONCILIATION_AND_CURRENTNESS_CHECKS"
        ),
        **NON_AUTHORIZING_FLAGS,
    }
    return payload


def build_live_receipt() -> dict[str, Any]:
    try:
        index = build_index_receipt()
    except (HTTPError, URLError, OSError, RuntimeError, ValueError) as exc:
        payload = _base_payload("HOLD_INDEX_FETCH_FAILED_NON_AUTHORIZING")
        payload["holds"] = [{
            "target_url": SOURCE_URL,
            "index_evidence_sha256": "",
            "state": "HOLD_INDEX_FETCH_FAILED_NON_AUTHORIZING",
            "reason": f"{type(exc).__name__}:{exc}",
        }]
        stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload["run_id"] = _sha256_text(stable)[:24]
        return payload

    if index.get("status") != "PASS":
        payload = _base_payload("HOLD_INDEX_NOT_PASS_NON_AUTHORIZING", index)
        payload["holds"] = [{
            "target_url": SOURCE_URL,
            "index_evidence_sha256": "",
            "state": "HOLD_INDEX_NOT_PASS_NON_AUTHORIZING",
            "reason": f"index_receipt_not_pass:{index.get('status')}",
        }]
        stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload["run_id"] = _sha256_text(stable)[:24]
        return payload

    candidates = [
        ref for ref in index.get("references", []) if _eligible_reference(ref)
    ][:MAX_DETAILS]

    details: list[DetailEvidence] = []
    holds: list[dict[str, str]] = []
    for ref in candidates:
        target_url = str(ref.get("target_url") or "")
        try:
            body, final_url, content_type = _fetch_detail(target_url)
            detail_hash = _sha256_bytes(body)
            (
                visible_title,
                publication_date,
                effective_date,
                field_evidence,
                tag_counts,
            ) = _extract_html_evidence(body, detail_hash)
            details.append(
                DetailEvidence(
                    source_kind=str(ref.get("source_kind") or ""),
                    topic_class=str(ref.get("topic_class") or ""),
                    index_title=str(ref.get("title") or ""),
                    detail_url=final_url,
                    detail_host=(urlsplit(final_url).hostname or "").lower(),
                    content_type=content_type,
                    content_length=len(body),
                    detail_sha256=detail_hash,
                    index_evidence_sha256=str(ref.get("evidence_sha256") or ""),
                    visible_title=visible_title,
                    publication_date_text=publication_date,
                    effective_date_text=effective_date,
                    field_evidence=field_evidence,
                    tag_counts=tag_counts,
                    currentness_state="CURRENTNESS_UNRESOLVED_REQUIRES_SEPARATE_VERIFICATION",
                    verification_state="ETA_SOURCE_TEXT_EVIDENCE_CAPTURED_NON_AUTHORIZING",
                )
            )
        except (HTTPError, URLError, OSError, RuntimeError, ValueError) as exc:
            holds.append(
                {
                    "target_url": target_url,
                    "index_evidence_sha256": str(ref.get("evidence_sha256") or ""),
                    "state": "HOLD_DETAIL_FETCH_FAILED_NON_AUTHORIZING",
                    "reason": f"{type(exc).__name__}:{exc}",
                }
            )

    if not candidates:
        status = "HOLD_NO_ELIGIBLE_DETAIL_REFERENCES"
    elif not details:
        status = "HOLD_NO_DETAIL_EVIDENCE"
    else:
        status = "PASS"

    payload = _base_payload(status, index)
    payload.update(
        {
            "eligible_detail_count": len(candidates),
            "detail_evidence_count": len(details),
            "detail_hold_count": len(holds),
            "details": [asdict(item) for item in details],
            "holds": holds,
        }
    )
    stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["run_id"] = _sha256_text(stable)[:24]
    return payload


def _self_test() -> None:
    good = _canonical_first_party_target(
        "https://eta-bus.ro/comunicate/deviere-traseu-în-centru?x=1#fragment"
    )
    assert good == "https://eta-bus.ro/comunicate/deviere-traseu-%C3%AEn-centru?x=1"
    assert _validate_final_url(good, good) == good

    for bad in (
        "https://example.invalid/comunicate/test",
        "http://eta-bus.ro/comunicate/test",
        "https://eta-bus.ro/trasee/test",
        "https://eta-bus.ro/comunicate",
    ):
        try:
            _canonical_first_party_target(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe ETA detail target accepted: {bad}")

    try:
        _validate_final_url(
            good,
            "https://eta-bus.ro/comunicate/alta-resursa?x=1",
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("resource-changing redirect must fail closed")

    html = (
        "<html><head><title>ETA test</title></head><body>"
        "<script>Tarif inventat 999 lei, valabil la 1 ianuarie 2099.</script>"
        "<h1>Tarife și călătorii gratuite</h1>"
        "<p>Publicat la: 30 Ian 2026</p>"
        "<p>Tarife de transport valabile începând cu data de 01/02/2026.</p>"
        "<table><tr><td>Bilet 1 călătorie</td><td>4.00 lei</td></tr></table>"
        "<p>Locuitorii cu vârsta peste 62 de ani beneficiază de 20 de călătorii gratuite pe lună.</p>"
        "<p>Tariful pentru bilete a fost aprobat prin Hotărâre de Consiliu Local în data de 29.01.2026.</p>"
        "<p>În perioada 17.07.2026 – 20.07.2026 va avea loc un upgrade; pot apărea anomalii temporare.</p>"
        "<p>Linia 5 va avea traseu modificat și stație temporară în centru.</p>"
        "</body></html>"
    ).encode("utf-8")
    detail_hash = _sha256_bytes(html)
    (
        title,
        publication_date,
        effective_date,
        field_evidence,
        tag_counts,
    ) = _extract_html_evidence(html, detail_hash)
    assert title == "Tarife și călătorii gratuite"
    assert publication_date == "Publicat la: 30 Ian 2026"
    assert effective_date == "începând cu data de 01/02/2026"
    observed_tags = {tag for item in field_evidence for tag in item.epistemic_tags}
    assert {
        "ROUTE_OR_STOP_CHANGE",
        "SERVICE_DISRUPTION_WINDOW",
        "FARE_OR_TICKETING",
        "PASSENGER_ENTITLEMENT",
        "EFFECTIVE_DATE_OR_VALIDITY_WINDOW",
        "APPROVAL_OR_POLICY_BASIS",
        "REPORTED_NUMERIC_SERVICE_VALUE",
    } <= observed_tags
    assert set(tag_counts) <= ALLOWED_TAGS
    assert all(re.fullmatch(r"[0-9a-f]{64}", item.evidence_sha256) for item in field_evidence)
    assert all("999 lei" not in item.excerpt for item in field_evidence)
    assert all(value is False for value in NON_AUTHORIZING_FLAGS.values())
    assert _eligible_reference({"source_kind": "COMMUNIQUES", "topic_class": "FARE_TICKETING"})
    assert not _eligible_reference({"source_kind": "COMMUNIQUES", "topic_class": "OPERATOR_OTHER"})
    assert not _eligible_reference({"source_kind": "OTHER", "topic_class": "FARE_TICKETING"})
    print("ETA Vâlcea transport detail evidence self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded ETA Vâlcea first-party transport detail evidence")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--live-check", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return 0
    if not args.live_check:
        parser.error("use --self-test or --live-check")

    payload = build_live_receipt()
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
