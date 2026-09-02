#!/usr/bin/env python3
"""Bounded first-party ISU Vâlcea detail evidence for VÂLCEA CLAR.

This verifier follows only allow-listed first-party ISU Vâlcea article URLs
already discovered by the emergency reference adapter. It hashes the exact
detail bytes and captures small evidence-bound fragments with explicit source
assertion tags. Those tags separate what ISU reports observing, response
actions, numeric/casualty statements, stated causes/origins and public
protection warnings/restrictions.

Every captured fragment remains an ISU first-party statement, not independent
verification. Detail evidence never authorizes material facts, breaking-news
status, Fact Kernel writes, Editorial Writer use, publication or distribution.
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

from isu_valcea_emergency_reference_adapter import (
    ALLOWED_HOSTS,
    SOURCE_URLS,
    build_receipt as build_index_receipt,
)

SCHEMA = "ISU_VALCEA_EMERGENCY_DETAIL_EVIDENCE_V1"
PARSER_VERSION = "ISU_VALCEA_EMERGENCY_DETAIL_EVIDENCE_2026_09_02"
SOURCE_FAMILY = "ISU_VALCEA_EMERGENCY"
AUTHORITY_CLASS = "FIRST_PARTY_COUNTY_EMERGENCY_ARTICLE_DETAIL_EVIDENCE"
OBSERVATION_STATE = "ISU_SOURCE_DETAIL_EVIDENCE_NON_AUTHORIZING"
SOURCE_ASSERTION_SCOPE = "ISU_FIRST_PARTY_STATEMENT_ONLY_NOT_INDEPENDENT_VERIFICATION"

HIGH_VALUE_TOPICS = {
    "ROAD_RESCUE",
    "FIRE",
    "WEATHER_HAZARD",
    "MEDICAL_EMERGENCY",
    "CIVIL_PROTECTION",
    "PREVENTION",
}
MAX_DETAILS = 12
MAX_BYTES = 2_500_000
MAX_FIELD_EVIDENCE = 10
MAX_FRAGMENT_CHARS = 480
ALLOWED_CONTENT_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}
USER_AGENT = "CIVORA-Valcea-Clar-ISU-Detail-Evidence/1.0"

NON_AUTHORIZING_FLAGS = {
    "material_fact_use": False,
    "independent_fact_verification_authorized": False,
    "incident_status_authorized": False,
    "incident_cause_authorized": False,
    "casualty_count_authorized": False,
    "affected_person_count_authorized": False,
    "intervention_count_authorized": False,
    "resource_count_authorized": False,
    "road_restriction_current_status_authorized": False,
    "weather_warning_current_status_authorized": False,
    "shelter_capacity_authorized": False,
    "medical_service_availability_authorized": False,
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
        "ISU_REPORTED_OBSERVATION",
        (
            "au constatat",
            "a fost găsit",
            "a fost gasit",
            "a fost găsită",
            "a fost gasita",
            "se afla",
            "s-a produs",
            "s-a propagat",
            "incendiul se manifesta",
            "incendiul s-a manifestat",
            "au identificat",
            "au observat",
            "au fost implica",
        ),
    ),
    (
        "RESPONSE_ACTION",
        (
            "s-au deplasat",
            "s-au mobilizat",
            "au intervenit",
            "s-a intervenit",
            "au acționat",
            "au actionat",
            "au evacuat",
            "au stins",
            "au lichidat",
            "au localizat",
            "au acordat",
            "au transportat",
            "au descarcerat",
            "s-a procedat",
            "au asigurat",
            "asigură măsuri",
            "asigura masuri",
            "echipajele operative",
            "forțe din cadrul",
            "forte din cadrul",
        ),
    ),
    (
        "REPORTED_AFFECTED_OR_CASUALTY",
        (
            "victim",
            "decedat",
            "decedată",
            "decedata",
            "rănit",
            "ranit",
            "rănită",
            "ranita",
            "încarcerat",
            "incarcerat",
            "blocată",
            "blocata",
            "asistate",
            "asistată",
            "asistata",
            "evaluate medical",
            "evaluată medical",
            "evaluata medical",
            "transportate la",
            "transportată la",
            "transportata la",
            "autoevacuat",
        ),
    ),
    (
        "REPORTED_CAUSE_OR_ORIGIN",
        (
            "cauza probabilă",
            "cauza probabila",
            "cauza incendiului",
            "cauza producerii",
            "sursa probabilă",
            "sursa probabila",
            "sursă de aprindere",
            "sursa de aprindere",
            "scurtcircuit",
            "foc deschis",
            "efect termic",
            "mijloc de încălzire",
            "mijloc de incalzire",
            "coș de fum",
            "cos de fum",
        ),
    ),
    (
        "PUBLIC_PROTECTION_WARNING_OR_RESTRICTION",
        (
            "cod roșu",
            "cod rosu",
            "cod portocaliu",
            "cod galben",
            "avertizare",
            "atenționare",
            "atentionare",
            "ro-alert",
            "restric",
            "evitați",
            "evitati",
            "recomandăm",
            "recomandam",
            "recomandă",
            "recomanda",
            "nu utilizați",
            "nu utilizati",
            "nu folosiți",
            "nu folositi",
            "evacuare",
            "adăpostire",
            "adapostire",
            "protecție civilă",
            "protectie civila",
        ),
    ),
)
ALLOWED_TAGS = {tag for tag, _ in TAG_RULES} | {"REPORTED_NUMERIC_COUNT"}

COUNT_CONTEXT_NEEDLES = (
    "misiun",
    "interven",
    "persoan",
    "victim",
    "pompier",
    "echipaj",
    "autospecial",
    "ambulan",
    "incendi",
    "adăpost",
    "adapost",
    "capacitate",
    "exerci",
    "smurd",
)

ROMANIAN_MONTHS = (
    "ianuarie",
    "februarie",
    "martie",
    "aprilie",
    "mai",
    "iunie",
    "iulie",
    "august",
    "septembrie",
    "octombrie",
    "noiembrie",
    "decembrie",
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
    explicit_date_text: str | None
    field_evidence: tuple[FieldEvidence, ...]
    tag_counts: dict[str, int]
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
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.segments: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if name in {"script", "style", "noscript", "svg", "template"}:
            self.skip_depth += 1
        elif name == "title" and not self.skip_depth:
            self.in_title = True
        elif name == "h1" and not self.skip_depth:
            self.h1_depth += 1

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name == "title":
            self.in_title = False
        elif name == "h1" and self.h1_depth:
            self.h1_depth -= 1
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


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _expected_article_prefix(source_kind: str) -> str:
    try:
        return urlsplit(SOURCE_URLS[source_kind]).path.rstrip("/") + "/"
    except KeyError as exc:
        raise ValueError("unknown_source_kind") from exc


def _canonical_first_party_target(url: str, source_kind: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host not in ALLOWED_HOSTS:
        raise ValueError("detail_target_not_first_party_https")
    if parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError("detail_target_identity_invalid")
    path = quote(parts.path or "/", safe="/%:@-._~!$&'()*+,;=")
    query = quote(parts.query, safe="=&;%:+,/?@-._~!$'()*")
    if not path.startswith(_expected_article_prefix(source_kind)):
        raise ValueError("detail_target_outside_source_section")
    return urlunsplit(("https", host, path, query, ""))


def _validate_final_url(requested: str, final: str, source_kind: str) -> str:
    expected = urlsplit(_canonical_first_party_target(requested, source_kind))
    observed_url = _canonical_first_party_target(final, source_kind)
    observed = urlsplit(observed_url)
    if observed.path != expected.path or observed.query != expected.query:
        raise RuntimeError("detail_redirect_changed_resource_identity")
    return observed_url


def _find_explicit_date(text: str) -> str | None:
    numeric = re.search(
        r"\b(?:0?[1-9]|[12][0-9]|3[01])[.\-/](?:0?[1-9]|1[0-2])[.\-/]20\d{2}\b|"
        r"\b20\d{2}[-/](?:0[1-9]|1[0-2])[-/](?:0[1-9]|[12][0-9]|3[01])\b",
        text,
    )
    if numeric:
        return numeric.group(0)
    months = "|".join(ROMANIAN_MONTHS)
    textual = re.search(rf"\b(?:0?[1-9]|[12][0-9]|3[01])\s+(?:{months})\s+20\d{{2}}\b", text, re.IGNORECASE)
    return textual.group(0) if textual else None


def _tags_for_fragment(fragment: str) -> tuple[str, ...]:
    lowered = fragment.casefold()
    tags: list[str] = []
    for tag, needles in TAG_RULES:
        if any(needle.casefold() in lowered for needle in needles):
            tags.append(tag)
    if re.search(r"\b\d[\d .]*\b", fragment) and any(needle in lowered for needle in COUNT_CONTEXT_NEEDLES):
        tags.append("REPORTED_NUMERIC_COUNT")
    return tuple(dict.fromkeys(tags))


def _split_candidate_fragments(segments: list[str]) -> list[str]:
    candidates: list[str] = []
    for segment in segments:
        for piece in re.split(r"(?<=[.!?])\s+|\s+[•|]\s+", segment):
            cleaned = " ".join(piece.split()).strip(" -–—")
            if 30 <= len(cleaned) <= 1400:
                candidates.append(cleaned)
    return candidates


def _extract_html_evidence(
    body: bytes,
    detail_sha256: str,
) -> tuple[str | None, str | None, tuple[FieldEvidence, ...], dict[str, int]]:
    parser = VisibleTextParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    h1 = " ".join(parser.h1_parts).strip()
    title = " ".join(parser.title_parts).strip()
    visible_title = h1 or title or None
    visible_text = " ".join(parser.segments)
    explicit_date = _find_explicit_date(visible_text)

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
    return visible_title, explicit_date, tuple(evidence), dict(sorted(tag_counts.items()))


def _fetch_detail(url: str, source_kind: str, timeout: float = 20.0) -> tuple[bytes, str, str]:
    canonical = _canonical_first_party_target(url, source_kind)
    request = Request(
        canonical,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain",
        },
    )
    context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        final_url = _validate_final_url(canonical, response.geturl(), source_kind)
        if getattr(response, "status", 200) != 200:
            raise RuntimeError(f"detail_http_status:{getattr(response, 'status', 0)}")
        content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise RuntimeError(f"detail_content_type_not_allowlisted:{content_type or 'missing'}")
        body = response.read(MAX_BYTES + 1)
        if not body or len(body) > MAX_BYTES:
            raise RuntimeError("detail_body_empty_or_too_large")
        return body, final_url, content_type


def _eligible_reference(ref: dict[str, Any]) -> bool:
    source_kind = str(ref.get("source_kind") or "")
    topic = str(ref.get("topic_class") or "")
    return source_kind == "COMMUNIQUES" or topic in HIGH_VALUE_TOPICS


def build_live_receipt() -> dict[str, Any]:
    index = build_index_receipt()
    if index.get("status") != "PASS":
        raise RuntimeError(f"index_receipt_not_pass:{index.get('status')}")
    candidates = [ref for ref in index.get("references", []) if _eligible_reference(ref)][:MAX_DETAILS]

    details: list[DetailEvidence] = []
    holds: list[dict[str, str]] = []
    for ref in candidates:
        source_kind = str(ref.get("source_kind") or "")
        target_url = str(ref.get("target_url") or "")
        try:
            body, final_url, content_type = _fetch_detail(target_url, source_kind)
            detail_hash = _sha256_bytes(body)
            visible_title, explicit_date, field_evidence, tag_counts = _extract_html_evidence(body, detail_hash)
            details.append(
                DetailEvidence(
                    source_kind=source_kind,
                    topic_class=str(ref.get("topic_class") or ""),
                    index_title=str(ref.get("title") or ""),
                    detail_url=final_url,
                    detail_host=(urlsplit(final_url).hostname or "").lower(),
                    content_type=content_type,
                    content_length=len(body),
                    detail_sha256=detail_hash,
                    index_evidence_sha256=str(ref.get("evidence_sha256") or ""),
                    visible_title=visible_title,
                    explicit_date_text=explicit_date,
                    field_evidence=field_evidence,
                    tag_counts=tag_counts,
                    verification_state="ISU_SOURCE_TEXT_EVIDENCE_CAPTURED_NON_AUTHORIZING",
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

    status = "PASS" if details else "HOLD_NO_DETAIL_EVIDENCE"
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "status": status,
        "source_family": SOURCE_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "source_assertion_scope": SOURCE_ASSERTION_SCOPE,
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "coverage_note": "BOUNDED_FIRST_PARTY_ISU_INCIDENT_AND_COMMUNIQUE_DETAIL_VERIFICATION_NOT_EXHAUSTIVE",
        "index_run_id": index.get("run_id"),
        "index_reference_count": index.get("reference_count", 0),
        "eligible_detail_count": len(candidates),
        "detail_evidence_count": len(details),
        "detail_hold_count": len(holds),
        "details": [asdict(item) for item in details],
        "holds": holds,
        "limitations": {
            "isu_statement_is_not_independent_verification": True,
            "reported_casualty_or_affected_counts_require_field_level_reconciliation": True,
            "reported_cause_requires_explicit_source_wording_and_independent_context_for_publication": True,
            "reported_intervention_or_resource_counts_are_not_live_service_capacity": True,
            "warning_or_restriction_requires_separate_current_status_verification": True,
            "shelter_capacity_requires_separate_current_material_verification": True,
            "sample_is_bounded_and_non_exhaustive": True,
        },
        "interpretation": (
            "DETAIL_BYTES_AND_TAGGED_ISU_SOURCE_FRAGMENTS_ARE_EVIDENCE_CONTEXT_ONLY;"
            "MATERIAL_FIELDS_REQUIRE_SEPARATE_RECONCILIATION_AND_CURRENTNESS_CHECKS"
        ),
        **NON_AUTHORIZING_FLAGS,
    }
    stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["run_id"] = _sha256_text(stable)[:24]
    return payload


def _self_test() -> None:
    news = "LOCAL_NEWS"
    good = _canonical_first_party_target(
        "https://isuvl.igsu.ro/stiri-locale/incendiu-în-gospodărie-123?x=1#fragment",
        news,
    )
    assert good == "https://isuvl.igsu.ro/stiri-locale/incendiu-%C3%AEn-gospod%C4%83rie-123?x=1"
    assert _validate_final_url(good, good, news) == good

    try:
        _canonical_first_party_target("https://igsu.ro/stiri/test", news)
    except ValueError:
        pass
    else:
        raise AssertionError("external IGSU host must not be promoted to ISU Vâlcea detail authority")

    try:
        _canonical_first_party_target("https://isuvl.igsu.ro/comunicate-de-presa/test", news)
    except ValueError:
        pass
    else:
        raise AssertionError("cross-section detail identity must fail closed")

    try:
        _validate_final_url(
            good,
            "https://isuvl.igsu.ro/stiri-locale/alta-resursa-999?x=1",
            news,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("resource-changing redirect must fail closed")

    html = (
        "<html><head><title>ISU Vâlcea - test</title></head><body>"
        "<script>Au intervenit 999 de echipaje la 1 ianuarie 2099.</script>"
        "<h1>Accident rutier în localitatea Test</h1>"
        "<p>2 septembrie 2026</p>"
        "<p>Echipajele operative sosite la fața locului au constatat că două autoturisme erau implicate.</p>"
        "<p>S-au deplasat 3 echipaje, care au descarcerat o persoană și au acordat primul ajutor.</p>"
        "<p>Au fost evaluate medical 5 persoane, iar o victimă a fost transportată la spital.</p>"
        "<p>Cauza probabilă a incendiului a fost un scurtcircuit electric.</p>"
        "<p>ISU recomandă populației să evite zona pe durata restricțiilor.</p>"
        "</body></html>"
    ).encode("utf-8")
    detail_hash = _sha256_bytes(html)
    title, date_text, field_evidence, tag_counts = _extract_html_evidence(html, detail_hash)
    assert title == "Accident rutier în localitatea Test"
    assert date_text == "2 septembrie 2026"
    observed_tags = {tag for item in field_evidence for tag in item.epistemic_tags}
    assert {
        "ISU_REPORTED_OBSERVATION",
        "RESPONSE_ACTION",
        "REPORTED_AFFECTED_OR_CASUALTY",
        "REPORTED_CAUSE_OR_ORIGIN",
        "PUBLIC_PROTECTION_WARNING_OR_RESTRICTION",
        "REPORTED_NUMERIC_COUNT",
    } <= observed_tags
    assert set(tag_counts) <= ALLOWED_TAGS
    assert all(re.fullmatch(r"[0-9a-f]{64}", item.evidence_sha256) for item in field_evidence)
    assert all(value is False for value in NON_AUTHORIZING_FLAGS.values())
    assert _eligible_reference({"source_kind": "COMMUNIQUES", "topic_class": "EMERGENCY_OTHER"})
    assert _eligible_reference({"source_kind": "LOCAL_NEWS", "topic_class": "ROAD_RESCUE"})
    assert not _eligible_reference({"source_kind": "LOCAL_NEWS", "topic_class": "EMERGENCY_OTHER"})
    print("ISU Vâlcea emergency detail evidence self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded ISU Vâlcea first-party emergency detail evidence")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--live-check", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return 0
    if not args.live_check:
        parser.error("use --self-test or --live-check")
    try:
        payload = build_live_receipt()
    except (HTTPError, URLError, OSError, RuntimeError, ValueError) as exc:
        print(f"HOLD_SOURCE_FETCH_FAILED:{type(exc).__name__}:{exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
