#!/usr/bin/env python3
"""Bounded first-party IPJ Vâlcea article-body evidence for VÂLCEA CLAR.

Only text inside an explicit article/content scope may become field evidence.
Navigation, headers, footers, sidebars and other page chrome are ignored even if
they contain police-related keywords. If an article body cannot be identified,
the detail stays fail-closed instead of falling back to whole-page text.
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

from ipj_valcea_public_safety_reference_adapter import (
    ALLOWED_HOSTS,
    SOURCE_URLS,
    build_receipt as build_index_receipt,
)

SCHEMA = "IPJ_VALCEA_PUBLIC_SAFETY_DETAIL_EVIDENCE_V1"
PARSER_VERSION = "IPJ_VALCEA_PUBLIC_SAFETY_DETAIL_EVIDENCE_2026_09_02_P0_ARTICLE_SCOPE"
SOURCE_FAMILY = "IPJ_VALCEA_PUBLIC_SAFETY"
AUTHORITY_CLASS = "FIRST_PARTY_COUNTY_POLICE_ARTICLE_DETAIL_EVIDENCE"
OBSERVATION_STATE = "POLICE_SOURCE_DETAIL_EVIDENCE_NON_AUTHORIZING"
SOURCE_ASSERTION_SCOPE = "POLICE_FIRST_PARTY_STATEMENT_ONLY_NOT_INDEPENDENT_VERIFICATION"
HIGH_VALUE_TOPICS = {"ROAD_SAFETY", "CRIME_INVESTIGATION", "ECONOMIC_CRIME", "PUBLIC_ORDER"}
MAX_DETAILS = 12
MAX_BYTES = 2_500_000
MAX_FIELD_EVIDENCE = 8
MAX_FRAGMENT_CHARS = 420
ALLOWED_CONTENT_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}
USER_AGENT = "CIVORA-Valcea-Clar-IPJ-Detail-Evidence/1.1"

NON_AUTHORIZING_FLAGS = {
    "material_fact_use": False,
    "independent_fact_verification_authorized": False,
    "incident_status_authorized": False,
    "suspect_status_authorized": False,
    "criminal_liability_authorized": False,
    "procedural_measure_as_guilt_authorized": False,
    "casualty_count_authorized": False,
    "sanction_count_authorized": False,
    "road_restriction_current_status_authorized": False,
    "investigation_status_authorized": False,
    "same_event_dedupe_authorized": False,
    "breaking_authorized": False,
    "fact_kernel_write_authorized": False,
    "editorial_writer_authorized": False,
    "publication_authorized": False,
    "distribution_authorized": False,
    "runtime_persistence_authorized": False,
}

TAG_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ALLEGATION_OR_SUSPICION", (
        "ar fi", "bănuit", "banuit", "suspect", "suspici", "presupus", "acuzat",
        "indicii", "cercetat pentru", "cercetată pentru", "cercetata pentru",
        "cercetat sub aspectul", "cercetată sub aspectul",
    )),
    ("PROCEDURAL_MEASURE", (
        "reținut", "retinut", "reținere", "retinere", "arest", "control judiciar",
        "perchezi", "mandat", "dosar penal", "măsură preventivă", "masura preventiva",
        "cercetările continuă", "cercetarile continua", "sesizat parchetul",
    )),
    ("ROAD_OR_PUBLIC_SAFETY_MEASURE", (
        "trafic", "circula", "restric", "rutier", "dn 7", "dn7", "filtru",
        "acțiune", "actiune", "control", "ordine publică", "ordine publica",
        "siguranță publică", "siguranta publica", "sancți", "sancti",
    )),
    ("POLICE_REPORTED_OBSERVATION", (
        "polițiștii au", "politistii au", "polițiștii din", "politistii din",
        "au depistat", "au identificat", "au oprit", "au constatat", "au intervenit",
        "a fost depistat", "a fost identificat", "în urma verificărilor", "in urma verificarilor",
    )),
)
ALLOWED_TAGS = {tag for tag, _ in TAG_RULES}
ROMANIAN_MONTHS = (
    "ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
    "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie",
)

SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "nav", "header", "footer", "aside", "form", "button"}
CONTENT_HINTS = {
    "article", "article-body", "article-content", "article-detail", "article-text",
    "news", "news-body", "news-content", "news-detail", "news-article",
    "stire", "stiri", "stire-content", "stire-detalii", "stire-text",
    "post-content", "entry-content", "content-article", "page-content",
}


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


class ArticleBodyParser(HTMLParser):
    """Collect title globally but evidence text only under explicit content roots."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool, bool]] = []
        self.skip_depth = 0
        self.scope_depth = 0
        self.scope_seen = False
        self.in_title = False
        self.title_parts: list[str] = []
        self.segments: list[str] = []

    @staticmethod
    def _starts_scope(tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        if tag in {"main", "article"}:
            return True
        if tag not in {"div", "section"}:
            return False
        values = " ".join(value or "" for key, value in attrs if key.lower() in {"id", "class", "role"}).casefold()
        tokens = {token for token in re.split(r"[^a-z0-9ăâîșşțţ_-]+", values) if token}
        if "article" in tokens or "main" in tokens:
            return True
        return any(hint in values for hint in CONTENT_HINTS)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        skip_start = name in SKIP_TAGS
        scope_start = False if self.skip_depth or skip_start else self._starts_scope(name, attrs)
        self.stack.append((name, skip_start, scope_start))
        if skip_start:
            self.skip_depth += 1
        if scope_start:
            self.scope_depth += 1
            self.scope_seen = True
        if name == "title" and not self.skip_depth:
            self.in_title = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Void/self-closing elements carry no material prose.
        return

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name == "title":
            self.in_title = False
        # HTML from institutional sites is not always perfectly nested. Pop back
        # to the matching tag and unwind any scope/skip state we entered.
        match = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == name:
                match = index
                break
        if match is None:
            return
        for _name, skip_start, scope_start in reversed(self.stack[match:]):
            if scope_start and self.scope_depth:
                self.scope_depth -= 1
            if skip_start and self.skip_depth:
                self.skip_depth -= 1
        del self.stack[match:]

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self.in_title:
            self.title_parts.append(text)
        if self.skip_depth or self.scope_depth <= 0:
            return
        self.segments.append(text)


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
    return tuple(tag for tag, needles in TAG_RULES if any(needle.casefold() in lowered for needle in needles))


def _split_candidate_fragments(segments: list[str]) -> list[str]:
    candidates: list[str] = []
    for segment in segments:
        for piece in re.split(r"(?<=[.!?])\s+|\s+[•|]\s+", segment):
            cleaned = " ".join(piece.split()).strip(" -–—")
            if 30 <= len(cleaned) <= 1200:
                candidates.append(cleaned)
    return candidates


def _evidence_from_segments(segments: list[str]) -> tuple[tuple[FieldEvidence, ...], dict[str, int]]:
    evidence: list[FieldEvidence] = []
    seen: set[str] = set()
    tag_counts: dict[str, int] = {}
    for fragment in _split_candidate_fragments(segments):
        tags = _tags_for_fragment(fragment)
        if not tags:
            continue
        excerpt = fragment[:MAX_FRAGMENT_CHARS]
        normalized = " ".join(excerpt.casefold().split())
        if normalized in seen:
            continue
        seen.add(normalized)
        basis = json.dumps(
            {"excerpt": excerpt, "epistemic_tags": tags, "source_assertion_scope": SOURCE_ASSERTION_SCOPE},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        evidence.append(FieldEvidence(excerpt, tags, _sha256_text(basis)))
        for tag in tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        if len(evidence) == MAX_FIELD_EVIDENCE:
            break
    return tuple(evidence), dict(sorted(tag_counts.items()))


def _extract_html_evidence(body: bytes) -> tuple[str | None, str | None, tuple[FieldEvidence, ...], dict[str, int]]:
    parser = ArticleBodyParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    if not parser.scope_seen or not parser.segments:
        raise RuntimeError("article_body_scope_not_found")
    article_text = " ".join(parser.segments)
    explicit_date = _find_explicit_date(article_text)
    evidence, tag_counts = _evidence_from_segments(parser.segments)
    visible_title = " ".join(parser.title_parts).strip() or None
    return visible_title, explicit_date, evidence, tag_counts


def _extract_plaintext_evidence(body: bytes) -> tuple[str | None, str | None, tuple[FieldEvidence, ...], dict[str, int]]:
    text = body.decode("utf-8", errors="replace")
    segments = [" ".join(line.split()) for line in text.splitlines() if " ".join(line.split())]
    evidence, tag_counts = _evidence_from_segments(segments)
    return None, _find_explicit_date(" ".join(segments)), evidence, tag_counts


def _fetch_detail(url: str, source_kind: str, timeout: float = 20.0) -> tuple[bytes, str, str]:
    canonical = _canonical_first_party_target(url, source_kind)
    request = Request(canonical, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,text/plain"})
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


def build_live_receipt() -> dict[str, Any]:
    index = build_index_receipt()
    if index.get("status") != "PASS":
        raise RuntimeError(f"index_receipt_not_pass:{index.get('status')}")
    candidates = [ref for ref in index.get("references", []) if ref.get("topic_class") in HIGH_VALUE_TOPICS][:MAX_DETAILS]
    details: list[DetailEvidence] = []
    holds: list[dict[str, str]] = []
    for ref in candidates:
        source_kind = str(ref.get("source_kind") or "")
        target_url = str(ref.get("target_url") or "")
        try:
            body, final_url, content_type = _fetch_detail(target_url, source_kind)
            extractor = _extract_plaintext_evidence if content_type == "text/plain" else _extract_html_evidence
            visible_title, explicit_date, field_evidence, tag_counts = extractor(body)
            if not field_evidence:
                raise RuntimeError("article_body_has_no_tagged_material_evidence")
            details.append(DetailEvidence(
                source_kind=source_kind,
                topic_class=str(ref.get("topic_class") or ""),
                index_title=str(ref.get("title") or ""),
                detail_url=final_url,
                detail_host=(urlsplit(final_url).hostname or "").lower(),
                content_type=content_type,
                content_length=len(body),
                detail_sha256=_sha256_bytes(body),
                index_evidence_sha256=str(ref.get("evidence_sha256") or ""),
                visible_title=visible_title,
                explicit_date_text=explicit_date,
                field_evidence=field_evidence,
                tag_counts=tag_counts,
                verification_state="POLICE_SOURCE_ARTICLE_BODY_EVIDENCE_CAPTURED_NON_AUTHORIZING",
            ))
        except (HTTPError, URLError, OSError, RuntimeError, ValueError) as exc:
            holds.append({
                "target_url": target_url,
                "index_evidence_sha256": str(ref.get("evidence_sha256") or ""),
                "state": "HOLD_DETAIL_FETCH_OR_ARTICLE_SCOPE_FAILED_NON_AUTHORIZING",
                "reason": f"{type(exc).__name__}:{exc}",
            })

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
        "coverage_note": "BOUNDED_HIGH_VALUE_FIRST_PARTY_POLICE_ARTICLE_BODY_VERIFICATION_NOT_EXHAUSTIVE",
        "index_run_id": index.get("run_id"),
        "index_reference_count": index.get("reference_count", 0),
        "eligible_detail_count": len(candidates),
        "detail_evidence_count": len(details),
        "detail_hold_count": len(holds),
        "details": [asdict(item) for item in details],
        "holds": holds,
        "limitations": {
            "police_statement_is_not_independent_verification": True,
            "police_allegation_is_not_criminal_liability": True,
            "procedural_measure_is_not_finding_of_guilt": True,
            "numeric_counts_require_separate_field_level_verification": True,
            "road_restriction_requires_current_status_verification": True,
            "article_body_scope_is_required": True,
            "whole_page_fallback_for_evidence_is_forbidden": True,
            "sample_is_bounded_and_non_exhaustive": True,
        },
        "interpretation": "ONLY_SCOPED_ARTICLE_BODY_TAGGED_POLICE_SOURCE_FRAGMENTS_ARE_EVIDENCE_CONTEXT;PAGE_CHROME_IS_EXCLUDED",
        **NON_AUTHORIZING_FLAGS,
    }
    stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["run_id"] = _sha256_text(stable)[:24]
    return payload


def _self_test() -> None:
    news = "NEWS"
    good = _canonical_first_party_target(
        "https://vl.politiaromana.ro/ro/stiri-si-media/stiri/acțiune-rutieră?x=1#fragment", news,
    )
    assert good == "https://vl.politiaromana.ro/ro/stiri-si-media/stiri/ac%C8%9Biune-rutier%C4%83?x=1"
    assert _validate_final_url(good, good, news) == good
    try:
        _canonical_first_party_target("https://politiaromana.ro/ro/stiri/test", news)
    except ValueError:
        pass
    else:
        raise AssertionError("external police host must not be promoted to IPJ detail authority")

    html = (
        "<html><head><title>IPJ Vâlcea - test</title></head><body>"
        "<header><nav><p>Polițiștii au control trafic și sancțiuni în meniu 1 ianuarie 2099.</p></nav></header>"
        "<main><article>"
        "<p>2 septembrie 2026</p>"
        "<p>Polițiștii au oprit un autoturism pentru verificări în trafic.</p>"
        "<p>Din verificări, conducătorul auto ar fi folosit un document necorespunzător.</p>"
        "<p>Persoana a fost reținută pentru 24 de ore, iar cercetările continuă.</p>"
        "<p>Traficul a fost restricționat temporar pe sectorul verificat.</p>"
        "</article></main>"
        "<aside><p>Polițiștii au identificat alte știri și acțiuni.</p></aside>"
        "</body></html>"
    ).encode("utf-8")
    title, date_text, field_evidence, tag_counts = _extract_html_evidence(html)
    assert title == "IPJ Vâlcea - test"
    assert date_text == "2 septembrie 2026"
    observed = " ".join(item.excerpt for item in field_evidence)
    assert "meniu" not in observed and "alte știri" not in observed
    observed_tags = {tag for item in field_evidence for tag in item.epistemic_tags}
    assert {"POLICE_REPORTED_OBSERVATION", "ALLEGATION_OR_SUSPICION", "PROCEDURAL_MEASURE", "ROAD_OR_PUBLIC_SAFETY_MEASURE"} <= observed_tags
    assert set(tag_counts) <= ALLOWED_TAGS
    assert all(re.fullmatch(r"[0-9a-f]{64}", item.evidence_sha256) for item in field_evidence)

    chrome_only = b"<html><body><nav><p>Politistii au control trafic si sanctiuni.</p></nav></body></html>"
    try:
        _extract_html_evidence(chrome_only)
    except RuntimeError as exc:
        assert str(exc) == "article_body_scope_not_found"
    else:
        raise AssertionError("whole-page fallback must remain fail-closed")
    assert all(value is False for value in NON_AUTHORIZING_FLAGS.values())
    print("IPJ Vâlcea article-body detail evidence self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded IPJ Vâlcea first-party article-body evidence")
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
