#!/usr/bin/env python3
"""Evidence-first ISJ Vâlcea education reference adapter.

Consumes only the official ISJ Vâlcea homepage and emits bounded references
for a small set of current-cycle education surfaces visible on that first-party
index. The adapter does not follow links or documents. A link destination is
retained only when it is itself on the approved ISJ host; otherwise the official
homepage anchor remains the sole admitted evidence.

This is reference intelligence, not operational truth. A homepage anchor does
not establish that an admission window, enrollment period, competition,
staffing action, programme or procedure is open/current. The adapter does not
extract pupils, parents, candidates, teachers or employees; does not parse
results/lists; does not persist state; does not promote to Fact Kernel; does not
invoke Writer; does not publish; and does not infer photo rights.
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
from datetime import date, datetime, timezone
from typing import Any, Optional
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

SOURCE_ID = "signal-isj-valcea-education-home-references"
TAXONOMY_VERSION = "2026-08-31.1"
SOURCE_NAME = "Inspectoratul Școlar Județean Vâlcea — homepage"
SOURCE_TIER = "T1_GOVERNMENT_FIRST_PARTY"
CANONICAL_HOST = "www.isjvalcea.ro"
ALLOWED_HOSTS = {"isjvalcea.ro", "www.isjvalcea.ro"}
INDEX_PATH = "/"
MAX_RESPONSE_BYTES = 2_500_000
TIMEOUT_SECONDS = 15
USER_AGENT = "CIVORA-ValceaClar-ISJ/1.0 (+evidence-first; contact via repository)"

PLACEHOLDER_TERMS = (
    "enable javascript",
    "access denied",
    "captcha",
    "service unavailable",
    "temporarily unavailable",
    "verify you are human",
)

# Intentionally narrow. Add a new class only after observing a stable,
# first-party homepage label and adding a regression fixture.
SIGNAL_PATTERNS = (
    (
        "DIRECTOR_COMPETITION_REFERENCE",
        re.compile(r"^concurs directori(?:\s+(20\d{2}))?$", re.I),
    ),
    (
        "MERIT_GRANT_REFERENCE",
        re.compile(r"^gradatii de merit(?:\s+(20\d{2}))?$", re.I),
    ),
    (
        "ADMISSION_BROCHURE_REFERENCE",
        re.compile(r"^brosura admitere\s+(20\d{2})\s*[-–]\s*(20\d{2})$", re.I),
    ),
    (
        "PRIMARY_ENROLLMENT_REFERENCE",
        re.compile(r"^inscriere invatamant primar\s+(20\d{2})\s*[-–]\s*(20\d{2})$", re.I),
    ),
    (
        "PRESCHOOL_ENROLLMENT_REFERENCE",
        re.compile(
            r"^inscrierea in invatamantul anteprescolar si prescolar pentru anul scolar\s+"
            r"(20\d{2})\s*[-–]\s*(20\d{2})$",
            re.I,
        ),
    ),
    (
        "HEALTHY_MEAL_PROGRAM_REFERENCE",
        re.compile(r"^programul national masa sanatoasa$", re.I),
    ),
    (
        "STAFF_MOBILITY_REFERENCE",
        re.compile(r"^mobilitate\s*[-–]\s*titularizare\s*[-–]\s*resurse umane$", re.I),
    ),
)


@dataclass(frozen=True)
class Anchor:
    href: str
    text: str


@dataclass(frozen=True)
class EducationReference:
    signal_class: str
    title: str
    declared_cycle: Optional[str]
    target_scope: str
    first_party_target_url: Optional[str]
    review_state: str
    hold_reason: Optional[str]


@dataclass(frozen=True)
class ISJEducationState:
    source_id: str
    taxonomy_version: str
    source_name: str
    source_tier: str
    source_url: str
    payload_sha256: str
    state: str
    hold_reason: Optional[str]
    as_of_date: str
    references: tuple[EducationReference, ...]
    reference_scope: str = "ISJ_VALCEA_HOME_INDEX_METADATA_ONLY"
    linked_page_fetch_allowed: bool = False
    linked_document_fetch_allowed: bool = False
    result_or_candidate_list_parse_allowed: bool = False
    person_identity_extraction_allowed: bool = False
    admission_window_currentness_inference_allowed: bool = False
    enrollment_window_currentness_inference_allowed: bool = False
    competition_currentness_inference_allowed: bool = False
    staffing_currentness_inference_allowed: bool = False
    programme_currentness_inference_allowed: bool = False
    legal_or_procedural_currentness_inference_allowed: bool = False
    school_performance_inference_allowed: bool = False
    breaking_news_promotion_allowed: bool = False
    inferred_photo_rights_allowed: bool = False
    persistence_allowed: bool = False
    fact_kernel_promotion_allowed: bool = False
    writer_allowed: bool = False
    public_projection_allowed: bool = False
    publication_authority: str = "NONE"


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", clean(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _path(value: str) -> str:
    path = re.sub(r"/+", "/", unquote(value or "/"))
    if not path.startswith("/"):
        path = "/" + path
    return path


def validate_index_url(url: str) -> str:
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
        or path != INDEX_PATH
    ):
        raise ValueError(f"off-surface ISJ index refused: {url}")
    return urlunsplit(("https", CANONICAL_HOST, INDEX_PATH, "", ""))


def normalize_first_party_target(index_url: str, href: str) -> Optional[str]:
    try:
        parsed = urlsplit(urljoin(index_url, clean(href)))
    except ValueError:
        return None
    host = (parsed.hostname or "").casefold()
    path = _path(parsed.path)
    if (
        parsed.scheme.casefold() != "https"
        or host not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return None
    return urlunsplit(("https", CANONICAL_HOST, path, "", ""))


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise ValueError(f"redirect refused: {newurl}")


def fetch_html(url: str, timeout: float = TIMEOUT_SECONDS) -> tuple[str, str, bytes]:
    canonical = validate_index_url(url)
    opener = build_opener(NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(
        canonical,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"},
    )
    with opener.open(request, timeout=timeout) as response:
        final_url = validate_index_url(response.geturl())
        content_type = clean(response.headers.get("Content-Type", "")).casefold()
        if "text/html" not in content_type:
            raise ValueError(f"non-HTML source refused: {content_type or 'unknown'}")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("response exceeds size cap")
        charset = response.headers.get_content_charset() or "utf-8"
    return final_url, body.decode(charset, errors="replace"), body


class HomeParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.page_parts: list[str] = []
        self.title_parts: list[str] = []
        self.title_depth = 0
        self.href: Optional[str] = None
        self.link_parts: list[str] = []
        self.anchors: list[Anchor] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "title":
            self.title_depth += 1
        if tag == "a":
            values = {k.casefold(): v for k, v in attrs if k and v}
            self.href = clean(values.get("href"))
            self.link_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.SKIP and self.skip:
            self.skip -= 1
            return
        if self.skip:
            return
        if tag == "a" and self.href is not None:
            text = clean(" ".join(self.link_parts))
            if text:
                self.anchors.append(Anchor(self.href, text))
            self.href = None
            self.link_parts = []
        if tag == "title" and self.title_depth:
            self.title_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        value = clean(data)
        if not value:
            return
        self.page_parts.append(value)
        if self.title_depth:
            self.title_parts.append(value)
        if self.href is not None:
            self.link_parts.append(value)

    def page_text(self) -> str:
        return clean(" ".join(self.page_parts))

    def page_title(self) -> str:
        return clean(" ".join(self.title_parts))


def placeholder_present(text: str) -> bool:
    value = fold(text[:5000])
    return any(term in value for term in PLACEHOLDER_TERMS)


def source_identity_present(text: str, page_title: str) -> bool:
    value = fold(f"{page_title} {text[:8000]}")
    return (
        "inspectoratul scolar judetean valcea" in value
        and "ramnicu valcea" in value
        and ("bulevardul nicolae balcescu" in value or "isj valcea" in value)
    )


def classify_title(title: str) -> tuple[Optional[str], Optional[str]]:
    value = fold(title)
    for signal_class, pattern in SIGNAL_PATTERNS:
        match = pattern.fullmatch(value)
        if not match:
            continue
        years = [part for part in match.groups() if part]
        if len(years) == 2:
            start, end = map(int, years)
            if end != start + 1:
                return signal_class, "INVALID_CYCLE"
            return signal_class, f"{start}-{end}"
        if len(years) == 1:
            return signal_class, years[0]
        return signal_class, None
    return None, None


def make_reference(index_url: str, anchor: Anchor, as_of: date) -> EducationReference:
    signal_class, declared_cycle = classify_title(anchor.text)
    if signal_class is None:
        raise AssertionError("unclassified anchor passed to make_reference")

    if declared_cycle == "INVALID_CYCLE":
        return EducationReference(
            signal_class=signal_class,
            title=clean(anchor.text),
            declared_cycle=None,
            target_scope="HELD",
            first_party_target_url=None,
            review_state="HOLD",
            hold_reason="recognized ISJ anchor contains a non-consecutive academic cycle",
        )

    if declared_cycle:
        start_year = int(declared_cycle[:4])
        # A reference may legitimately be posted before its cycle starts, but a
        # homepage claim more than one calendar year ahead is held as drift.
        if start_year > as_of.year + 1:
            return EducationReference(
                signal_class=signal_class,
                title=clean(anchor.text),
                declared_cycle=None,
                target_scope="HELD",
                first_party_target_url=None,
                review_state="HOLD",
                hold_reason="recognized ISJ anchor declares an implausibly future cycle",
            )

    target = normalize_first_party_target(index_url, anchor.href)
    return EducationReference(
        signal_class=signal_class,
        title=clean(anchor.text),
        declared_cycle=declared_cycle,
        target_scope="FIRST_PARTY_TARGET" if target else "INDEX_ONLY_TARGET_NOT_ADMITTED",
        first_party_target_url=target,
        review_state="REFERENCE_ONLY",
        hold_reason=None,
    )


def extract_state(
    source_url: str,
    html_text: str,
    payload: bytes,
    as_of: date,
) -> ISJEducationState:
    canonical = validate_index_url(source_url)
    parser = HomeParser()
    parser.feed(html_text)
    text = parser.page_text()
    title = parser.page_title()

    if placeholder_present(text):
        raise ValueError("placeholder/challenge page refused")
    if not source_identity_present(text, title):
        raise ValueError("ISJ Vâlcea homepage identity not present")

    found: dict[str, EducationReference] = {}
    conflicts: list[EducationReference] = []
    for anchor in parser.anchors:
        signal_class, _ = classify_title(anchor.text)
        if signal_class is None:
            continue
        ref = make_reference(canonical, anchor, as_of)
        previous = found.get(signal_class)
        if previous is None:
            found[signal_class] = ref
        elif previous != ref:
            conflicts.append(
                EducationReference(
                    signal_class=signal_class,
                    title=clean(anchor.text),
                    declared_cycle=None,
                    target_scope="HELD",
                    first_party_target_url=None,
                    review_state="HOLD",
                    hold_reason="same ISJ signal class has conflicting homepage anchors",
                )
            )

    references = list(found.values()) + conflicts
    references.sort(key=lambda item: item.signal_class)
    passed = any(item.review_state == "REFERENCE_ONLY" for item in references)

    if not references:
        state = "HOLD"
        hold_reason = "no bounded ISJ Vâlcea education homepage references found"
    elif not passed:
        state = "HOLD"
        hold_reason = "all bounded ISJ Vâlcea education references are held"
    else:
        state = "PASS"
        hold_reason = None

    return ISJEducationState(
        source_id=SOURCE_ID,
        taxonomy_version=TAXONOMY_VERSION,
        source_name=SOURCE_NAME,
        source_tier=SOURCE_TIER,
        source_url=canonical,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        state=state,
        hold_reason=hold_reason,
        as_of_date=as_of.isoformat(),
        references=tuple(references),
    )


def validate_boundaries(state: ISJEducationState) -> None:
    forbidden_true = (
        "linked_page_fetch_allowed",
        "linked_document_fetch_allowed",
        "result_or_candidate_list_parse_allowed",
        "person_identity_extraction_allowed",
        "admission_window_currentness_inference_allowed",
        "enrollment_window_currentness_inference_allowed",
        "competition_currentness_inference_allowed",
        "staffing_currentness_inference_allowed",
        "programme_currentness_inference_allowed",
        "legal_or_procedural_currentness_inference_allowed",
        "school_performance_inference_allowed",
        "breaking_news_promotion_allowed",
        "inferred_photo_rights_allowed",
        "persistence_allowed",
        "fact_kernel_promotion_allowed",
        "writer_allowed",
        "public_projection_allowed",
    )
    for field in forbidden_true:
        if getattr(state, field):
            raise AssertionError(f"boundary drift: {field}=true")
    if state.publication_authority != "NONE":
        raise AssertionError("publication authority drift")
    for ref in state.references:
        if ref.review_state == "HOLD":
            if ref.declared_cycle is not None or ref.first_party_target_url is not None:
                raise AssertionError("held ISJ reference leaks promoted metadata")


def run_self_test() -> None:
    sample = """
    <html>
      <head><title>ISJ VÂLCEA</title></head>
      <body>
        <h1>INSPECTORATUL ȘCOLAR JUDEȚEAN VÂLCEA</h1>
        <p>Bulevardul Nicolae Bălcescu Nr. 30, Râmnicu Vâlcea</p>
        <a href="/institutie/directori-2026">CONCURS DIRECTORI 2026</a>
        <a href="https://www.google.com/url?q=https://example.invalid">
          MOBILITATE - TITULARIZARE - RESURSE UMANE
        </a>
        <a href="/elevi/gradatii">GRADAȚII DE MERIT 2026</a>
        <a href="/elevi/admitere">BROSURA ADMITERE 2026 - 2027</a>
        <a href="/elevi/primar">Înscriere învățământ primar 2026-2027</a>
        <a href="/elevi/prescolar">
          ÎNSCRIEREA ÎN ÎNVĂȚĂMÂNTUL ANTEPREȘCOLAR ȘI PREȘCOLAR
          PENTRU ANUL ȘCOLAR 2026-2027
        </a>
        <a href="/elevi/masa-sanatoasa">PROGRAMUL NAȚIONAL MASĂ SĂNĂTOASĂ</a>
        <a href="/misc">Un link necunoscut</a>
      </body>
    </html>
    """
    state = extract_state(
        "https://isjvalcea.ro/",
        sample,
        sample.encode(),
        date(2026, 8, 31),
    )
    validate_boundaries(state)
    assert state.state == "PASS"
    assert len(state.references) == 7
    refs = {ref.signal_class: ref for ref in state.references}
    assert refs["ADMISSION_BROCHURE_REFERENCE"].declared_cycle == "2026-2027"
    assert refs["PRIMARY_ENROLLMENT_REFERENCE"].declared_cycle == "2026-2027"
    assert refs["PRESCHOOL_ENROLLMENT_REFERENCE"].declared_cycle == "2026-2027"
    assert refs["DIRECTOR_COMPETITION_REFERENCE"].declared_cycle == "2026"
    assert refs["STAFF_MOBILITY_REFERENCE"].target_scope == "INDEX_ONLY_TARGET_NOT_ADMITTED"
    assert refs["STAFF_MOBILITY_REFERENCE"].first_party_target_url is None
    assert refs["HEALTHY_MEAL_PROGRAM_REFERENCE"].declared_cycle is None

    no_identity = sample.replace("INSPECTORATUL ȘCOLAR JUDEȚEAN VÂLCEA", "Portal generic")
    no_identity = no_identity.replace("ISJ VÂLCEA", "Portal generic")
    try:
        extract_state("https://www.isjvalcea.ro/", no_identity, no_identity.encode(), date(2026, 8, 31))
    except ValueError as exc:
        assert "identity" in str(exc)
    else:
        raise AssertionError("identity drift must fail closed")

    placeholder = sample.replace(
        "<h1>INSPECTORATUL ȘCOLAR JUDEȚEAN VÂLCEA</h1>",
        "<h1>INSPECTORATUL ȘCOLAR JUDEȚEAN VÂLCEA</h1><p>Verify you are human</p>",
    )
    try:
        extract_state("https://www.isjvalcea.ro/", placeholder, placeholder.encode(), date(2026, 8, 31))
    except ValueError as exc:
        assert "placeholder" in str(exc)
    else:
        raise AssertionError("challenge page must fail closed")

    bad_cycle = sample.replace("BROSURA ADMITERE 2026 - 2027", "BROSURA ADMITERE 2026 - 2029")
    bad_state = extract_state(
        "https://www.isjvalcea.ro/",
        bad_cycle,
        bad_cycle.encode(),
        date(2026, 8, 31),
    )
    bad_ref = next(r for r in bad_state.references if r.signal_class == "ADMISSION_BROCHURE_REFERENCE")
    assert bad_ref.review_state == "HOLD"
    assert bad_ref.declared_cycle is None
    validate_boundaries(bad_state)

    future = sample.replace("CONCURS DIRECTORI 2026", "CONCURS DIRECTORI 2029")
    future_state = extract_state(
        "https://www.isjvalcea.ro/",
        future,
        future.encode(),
        date(2026, 8, 31),
    )
    future_ref = next(r for r in future_state.references if r.signal_class == "DIRECTOR_COMPETITION_REFERENCE")
    assert future_ref.review_state == "HOLD"
    validate_boundaries(future_state)

    duplicate = sample.replace(
        '<a href="/elevi/admitere">BROSURA ADMITERE 2026 - 2027</a>',
        '<a href="/elevi/admitere">BROSURA ADMITERE 2026 - 2027</a>'
        '<a href="/other/admitere">BROSURA ADMITERE 2026 - 2027</a>',
    )
    duplicate_state = extract_state(
        "https://www.isjvalcea.ro/",
        duplicate,
        duplicate.encode(),
        date(2026, 8, 31),
    )
    assert any(
        r.signal_class == "ADMISSION_BROCHURE_REFERENCE" and r.review_state == "HOLD"
        for r in duplicate_state.references
    )

    for bad_url in (
        "http://www.isjvalcea.ro/",
        "https://evil.example/",
        "https://www.isjvalcea.ro/?x=1",
        "https://www.isjvalcea.ro/#fragment",
        "https://www.isjvalcea.ro/isj-valcea",
    ):
        try:
            validate_index_url(bad_url)
        except ValueError:
            pass
        else:
            raise AssertionError(f"off-surface URL should be refused: {bad_url}")

    print("ISJ Vâlcea education homepage adapter self-test: PASS")


def parse_as_of(value: str) -> date:
    return date.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url", default="https://www.isjvalcea.ro/")
    parser.add_argument("--as-of", type=parse_as_of, default=None)
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        return 0

    as_of = args.as_of or datetime.now(timezone.utc).date()
    canonical, html_text, payload = fetch_html(args.source_url)
    state = extract_state(canonical, html_text, payload, as_of)
    validate_boundaries(state)
    rendered = json.dumps(asdict(state), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered)
    else:
        print(rendered, end="")
    return 0 if state.state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
