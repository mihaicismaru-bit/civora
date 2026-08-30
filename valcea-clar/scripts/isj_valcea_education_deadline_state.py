#!/usr/bin/env python3
"""Fail-closed education process-date normalization for ISJ Vâlcea signals.

Consumes only already-normalized ISJ education signal dictionaries. It may extract a
process date/window when the visible official label binds a date to an explicit
education-process semantic. Publication/label dates are kept separate and never
become deadline/open/closed/current claims by clock comparison.

No network fetch, document-body fetch, persistence, Fact Kernel promotion, Writer,
public projection or publication authority.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

SOURCE_ID = "signal-isj-valcea-education-notices"
EXPECTED_TAXONOMY_VERSION = "2026-08-30.1"
STATE_VERSION = "2026-08-30.1"

ALLOWED_SIGNAL_CLASSES = {
    "PRESCHOOL_ENROLMENT_NOTICE",
    "SECONDARY_ADMISSION_NOTICE",
    "TEACHER_EXAM_NOTICE",
    "SCHOOL_MANAGEMENT_NOTICE",
    "MERIT_GRANT_NOTICE",
    "SCHOOL_CALENDAR_NOTICE",
    "SUMMER_PRESCHOOL_SERVICE_REFERENCE",
    "EDUCATION_DOCUMENT_REFERENCE",
}
SENSITIVE_OR_HELD_PREFIXES = ("HOLD",)

DATE_TOKEN = r"(?P<d>[0-3]?\d)[./-](?P<m>[01]?\d)[./-](?P<y>20\d{2})"
DATE_TOKEN_2 = r"(?P<d2>[0-3]?\d)[./-](?P<m2>[01]?\d)[./-](?P<y2>20\d{2})"

WINDOW_PATTERNS = (
    ("APPLICATION_WINDOW", re.compile(
        rf"\b(?:perioada|intervalul)\s+(?:de\s+)?(?:inscriere|înscriere|depunere|transmitere|completare)[^0-9]{{0,45}}{DATE_TOKEN}\s*(?:-|–|—|pana la|până la|si|și)\s*{DATE_TOKEN_2}",
        re.IGNORECASE,
    )),
    ("APPLICATION_WINDOW", re.compile(
        rf"\b(?:inscrierile|înscrierile|depunerea\s+(?:cererilor|dosarelor))[^0-9]{{0,45}}(?:intre|între|in perioada|în perioada)[^0-9]{{0,20}}{DATE_TOKEN}\s*(?:-|–|—|si|și|pana la|până la)\s*{DATE_TOKEN_2}",
        re.IGNORECASE,
    )),
    ("CONTESTATION_WINDOW", re.compile(
        rf"\b(?:contestatii|contestații)[^0-9]{{0,50}}(?:intre|între|in perioada|în perioada|perioada)[^0-9]{{0,20}}{DATE_TOKEN}\s*(?:-|–|—|si|și|pana la|până la)\s*{DATE_TOKEN_2}",
        re.IGNORECASE,
    )),
    ("SERVICE_PERIOD", re.compile(
        rf"\b(?:program|functionare|funcționare|serviciu|gradinite|grădinițe)[^0-9]{{0,65}}(?:in perioada|în perioada|perioada)[^0-9]{{0,20}}{DATE_TOKEN}\s*(?:-|–|—|si|și|pana la|până la)\s*{DATE_TOKEN_2}",
        re.IGNORECASE,
    )),
)

POINT_PATTERNS = (
    ("APPLICATION_DEADLINE", re.compile(
        rf"\b(?:termen(?:ul)?(?:\s+limita|\s+limită)?|data\s+limita|data\s+limită|pana\s+la|până\s+la)[^0-9]{{0,45}}(?:inscrier|înscrier|depuner|transmiter|complet)|"
        rf"\b(?:inscrier|înscrier|depuner|transmiter|complet)[^0-9]{{0,60}}(?:termen(?:ul)?|data\s+limita|data\s+limită|pana\s+la|până\s+la)[^0-9]{{0,20}}{DATE_TOKEN}",
        re.IGNORECASE,
    )),
    ("EXAM_DATE", re.compile(
        rf"\b(?:proba|examenul|examen|proba\s+scrisa|proba\s+scrisă)[^0-9]{{0,55}}(?:la\s+data\s+de|din|:)?[^0-9]{{0,12}}{DATE_TOKEN}",
        re.IGNORECASE,
    )),
    ("RESULT_PUBLICATION_DATE", re.compile(
        rf"\b(?:afisarea|afișarea|publicarea)[^0-9]{{0,35}}(?:rezultatelor|rezultate)[^0-9]{{0,35}}{DATE_TOKEN}",
        re.IGNORECASE,
    )),
    ("CONTESTATION_DEADLINE", re.compile(
        rf"\b(?:contestatii|contestații)[^0-9]{{0,55}}(?:termen(?:ul)?|data\s+limita|data\s+limită|pana\s+la|până\s+la)[^0-9]{{0,20}}{DATE_TOKEN}",
        re.IGNORECASE,
    )),
)

DEADLINE_FIRST = re.compile(
    rf"\b(?:termen(?:ul)?(?:\s+limita|\s+limită)?|data\s+limita|data\s+limită|pana\s+la|până\s+la)[^0-9]{{0,15}}{DATE_TOKEN}[^.;:]{{0,55}}\b(?:inscrier|înscrier|depuner|transmiter|complet)",
    re.IGNORECASE,
)

DATE_ANY_RE = re.compile(r"\b([0-3]?\d)[./-]([01]?\d)[./-](20\d{2})\b")


@dataclass(frozen=True)
class EducationProcessDateState:
    state_version: str
    source_id: str
    source_taxonomy_version: str
    source_signal_class: str
    source_payload_sha256: str
    source_document_url_sha256: Optional[str]
    school_year: Optional[str]
    state: str
    hold_reason: Optional[str]
    process_kind: Optional[str]
    process_date: Optional[str]
    window_start_date: Optional[str]
    window_end_date: Optional[str]
    date_semantics: Optional[str]
    source_label_date: Optional[str]
    publication_date: Optional[str]
    as_of_date: str
    days_until_process_date: Optional[int]
    clock_relation: Optional[str]
    process_current_status_claim_allowed: bool = False
    publication_date_as_process_date_allowed: bool = False
    source_label_date_as_process_date_allowed: bool = False
    document_body_fetch_allowed: bool = False
    persistence_allowed: bool = False
    fact_kernel_promotion_allowed: bool = False
    writer_allowed: bool = False
    public_projection_allowed: bool = False


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", clean(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def parse_iso_date(value: Any) -> Optional[dt.date]:
    text = clean(value)
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


def _date_from_match(match: re.Match[str], suffix: str = "") -> dt.date:
    d = int(match.group(f"d{suffix}"))
    m = int(match.group(f"m{suffix}"))
    y = int(match.group(f"y{suffix}"))
    return dt.date(y, m, d)


def _state_hold(signal: dict[str, Any], as_of: dt.date, reason: str) -> EducationProcessDateState:
    return EducationProcessDateState(
        state_version=STATE_VERSION,
        source_id=clean(signal.get("source_id")) or SOURCE_ID,
        source_taxonomy_version=clean(signal.get("taxonomy_version")),
        source_signal_class=clean(signal.get("signal_class")),
        source_payload_sha256=clean(signal.get("payload_sha256")),
        source_document_url_sha256=clean(signal.get("document_url_sha256")) or None,
        school_year=clean(signal.get("school_year")) or None,
        state="HOLD",
        hold_reason=reason,
        process_kind=None,
        process_date=None,
        window_start_date=None,
        window_end_date=None,
        date_semantics=None,
        source_label_date=clean(signal.get("explicit_date")) or None,
        publication_date=clean(signal.get("publication_date")) or None,
        as_of_date=as_of.isoformat(),
        days_until_process_date=None,
        clock_relation=None,
    )


def _assert_source_boundaries(signal: dict[str, Any]) -> Optional[str]:
    if clean(signal.get("source_id")) != SOURCE_ID:
        return "SOURCE_ID_DRIFT"
    if clean(signal.get("taxonomy_version")) != EXPECTED_TAXONOMY_VERSION:
        return "SOURCE_TAXONOMY_DRIFT"
    signal_class = clean(signal.get("signal_class"))
    if signal_class.startswith(SENSITIVE_OR_HELD_PREFIXES):
        return "HELD_OR_SENSITIVE_SOURCE_SIGNAL"
    if signal_class not in ALLOWED_SIGNAL_CLASSES:
        return "UNSUPPORTED_SOURCE_SIGNAL_CLASS"
    if signal.get("hold_reason") not in (None, ""):
        return "UPSTREAM_SIGNAL_HELD"
    for flag in (
        "current_status_claim_allowed",
        "freshness_claim_allowed",
        "person_fact_extraction_allowed",
        "sensitive_result_projection_allowed",
        "document_body_fetch_allowed",
        "persistence_allowed",
        "fact_kernel_promotion_allowed",
        "writer_allowed",
        "public_projection_allowed",
    ):
        if signal.get(flag) is not False:
            return f"UPSTREAM_BOUNDARY_DRIFT_{flag.upper()}"
    if not re.fullmatch(r"[0-9a-f]{64}", clean(signal.get("payload_sha256"))):
        return "INVALID_SOURCE_PAYLOAD_SHA256"
    return None


def _extract_candidates(label: str) -> list[tuple[str, Optional[dt.date], Optional[dt.date], Optional[dt.date], str]]:
    candidates: list[tuple[str, Optional[dt.date], Optional[dt.date], Optional[dt.date], str]] = []
    for kind, pattern in WINDOW_PATTERNS:
        for match in pattern.finditer(label):
            try:
                start = _date_from_match(match)
                end = _date_from_match(match, "2")
            except ValueError:
                continue
            candidates.append((kind, None, start, end, "EXPLICIT_VISIBLE_LABEL_PROCESS_WINDOW"))

    for kind, pattern in POINT_PATTERNS:
        for match in pattern.finditer(label):
            if match.groupdict().get("d") is None:
                continue
            try:
                point = _date_from_match(match)
            except ValueError:
                continue
            candidates.append((kind, point, None, None, "EXPLICIT_VISIBLE_LABEL_PROCESS_DATE"))

    for match in DEADLINE_FIRST.finditer(label):
        try:
            point = _date_from_match(match)
        except ValueError:
            continue
        candidates.append(("APPLICATION_DEADLINE", point, None, None, "EXPLICIT_VISIBLE_LABEL_PROCESS_DATE"))

    dedup: dict[tuple[str, Optional[dt.date], Optional[dt.date], Optional[dt.date]], tuple[str, Optional[dt.date], Optional[dt.date], Optional[dt.date], str]] = {}
    for candidate in candidates:
        dedup[candidate[:4]] = candidate
    return list(dedup.values())


def normalize_signal(signal: dict[str, Any], as_of: dt.date) -> EducationProcessDateState:
    boundary_error = _assert_source_boundaries(signal)
    if boundary_error:
        return _state_hold(signal, as_of, boundary_error)

    publication_raw = clean(signal.get("publication_date"))
    if publication_raw:
        publication = parse_iso_date(publication_raw)
        if publication is None:
            return _state_hold(signal, as_of, "INVALID_PUBLICATION_DATE")
        if publication > as_of:
            return _state_hold(signal, as_of, "FUTURE_PUBLICATION_DATE")
    else:
        publication = None

    source_label_date_raw = clean(signal.get("explicit_date"))
    if source_label_date_raw and parse_iso_date(source_label_date_raw) is None:
        return _state_hold(signal, as_of, "INVALID_SOURCE_LABEL_DATE")

    label = clean(signal.get("label"))
    if not label:
        return _state_hold(signal, as_of, "NO_VISIBLE_LABEL_FOR_PROCESS_DATE")

    candidates = _extract_candidates(label)
    if not candidates:
        if DATE_ANY_RE.search(label) or source_label_date_raw:
            return _state_hold(signal, as_of, "DATE_WITHOUT_EXPLICIT_PROCESS_SEMANTICS")
        return _state_hold(signal, as_of, "NO_EXPLICIT_PROCESS_DATE")

    if len(candidates) != 1:
        return _state_hold(signal, as_of, "AMBIGUOUS_OR_MULTIPLE_PROCESS_DATES")

    kind, point, start, end, semantics = candidates[0]
    if start and end and end < start:
        return _state_hold(signal, as_of, "PROCESS_WINDOW_END_BEFORE_START")

    anchor = point or start
    assert anchor is not None
    delta = (anchor - as_of).days
    relation = "BEFORE_DATE" if delta > 0 else ("ON_DATE" if delta == 0 else "AFTER_DATE")

    return EducationProcessDateState(
        state_version=STATE_VERSION,
        source_id=SOURCE_ID,
        source_taxonomy_version=EXPECTED_TAXONOMY_VERSION,
        source_signal_class=clean(signal.get("signal_class")),
        source_payload_sha256=clean(signal.get("payload_sha256")),
        source_document_url_sha256=clean(signal.get("document_url_sha256")) or None,
        school_year=clean(signal.get("school_year")) or None,
        state="PROCESS_DATE_NORMALIZED_REVIEW_REQUIRED",
        hold_reason=None,
        process_kind=kind,
        process_date=point.isoformat() if point else None,
        window_start_date=start.isoformat() if start else None,
        window_end_date=end.isoformat() if end else None,
        date_semantics=semantics,
        source_label_date=source_label_date_raw or None,
        publication_date=publication.isoformat() if publication else None,
        as_of_date=as_of.isoformat(),
        days_until_process_date=delta,
        clock_relation=relation,
    )


def normalize_signals(signals: list[dict[str, Any]], as_of: dt.date) -> list[EducationProcessDateState]:
    return [normalize_signal(signal, as_of) for signal in signals]


def _base_signal(label: Optional[str], **overrides: Any) -> dict[str, Any]:
    signal: dict[str, Any] = {
        "source_id": SOURCE_ID,
        "taxonomy_version": EXPECTED_TAXONOMY_VERSION,
        "signal_class": "PRESCHOOL_ENROLMENT_NOTICE",
        "payload_sha256": "a" * 64,
        "document_url_sha256": "b" * 64,
        "school_year": "2026-2027",
        "label": label,
        "explicit_date": None,
        "hold_reason": None,
        "current_status_claim_allowed": False,
        "freshness_claim_allowed": False,
        "person_fact_extraction_allowed": False,
        "sensitive_result_projection_allowed": False,
        "document_body_fetch_allowed": False,
        "persistence_allowed": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "public_projection_allowed": False,
    }
    signal.update(overrides)
    return signal


def _assert_fail_closed(state: EducationProcessDateState) -> None:
    assert state.process_current_status_claim_allowed is False
    assert state.publication_date_as_process_date_allowed is False
    assert state.source_label_date_as_process_date_allowed is False
    assert state.document_body_fetch_allowed is False
    assert state.persistence_allowed is False
    assert state.fact_kernel_promotion_allowed is False
    assert state.writer_allowed is False
    assert state.public_projection_allowed is False


def self_test() -> None:
    as_of = dt.date(2026, 8, 30)

    deadline = normalize_signal(
        _base_signal("Înscriere învățământ preșcolar — termen limită 10.09.2026"),
        as_of,
    )
    assert deadline.state == "PROCESS_DATE_NORMALIZED_REVIEW_REQUIRED"
    assert deadline.process_kind == "APPLICATION_DEADLINE"
    assert deadline.process_date == "2026-09-10"
    assert deadline.days_until_process_date == 11
    assert deadline.clock_relation == "BEFORE_DATE"
    _assert_fail_closed(deadline)

    window = normalize_signal(
        _base_signal("Perioada de înscriere 01.09.2026 - 05.09.2026"),
        as_of,
    )
    assert window.process_kind == "APPLICATION_WINDOW"
    assert window.window_start_date == "2026-09-01"
    assert window.window_end_date == "2026-09-05"
    _assert_fail_closed(window)

    exam = normalize_signal(
        _base_signal("Definitivat — proba scrisă la data de 14.07.2027", signal_class="TEACHER_EXAM_NOTICE"),
        as_of,
    )
    assert exam.process_kind == "EXAM_DATE"
    assert exam.process_date == "2027-07-14"

    unlabeled_date = normalize_signal(
        _base_signal("Calendar admitere 10.09.2026", explicit_date="2026-09-10"),
        as_of,
    )
    assert unlabeled_date.state == "HOLD"
    assert unlabeled_date.hold_reason == "DATE_WITHOUT_EXPLICIT_PROCESS_SEMANTICS"

    publication_separation = normalize_signal(
        _base_signal(
            "Înscriere — termen limită 10.09.2026",
            explicit_date="2026-08-28",
            publication_date="2026-08-29",
        ),
        as_of,
    )
    assert publication_separation.process_date == "2026-09-10"
    assert publication_separation.source_label_date == "2026-08-28"
    assert publication_separation.publication_date == "2026-08-29"

    future_publication = normalize_signal(
        _base_signal(
            "Înscriere — termen limită 10.09.2026",
            publication_date="2026-08-31",
        ),
        as_of,
    )
    assert future_publication.state == "HOLD"
    assert future_publication.hold_reason == "FUTURE_PUBLICATION_DATE"

    sensitive = normalize_signal(
        _base_signal(
            None,
            signal_class="HOLD_SENSITIVE_EDUCATION_RESULT_REFERENCE",
            hold_reason="PERSON_LEVEL_OR_RESULT_DOCUMENT_REVIEW_REQUIRED",
        ),
        as_of,
    )
    assert sensitive.state == "HOLD"
    assert sensitive.hold_reason == "HELD_OR_SENSITIVE_SOURCE_SIGNAL"

    ambiguous = normalize_signal(
        _base_signal("Înscriere termen limită 10.09.2026; examen la data de 12.09.2026"),
        as_of,
    )
    assert ambiguous.state == "HOLD"
    assert ambiguous.hold_reason == "AMBIGUOUS_OR_MULTIPLE_PROCESS_DATES"

    reversed_window = normalize_signal(
        _base_signal("Perioada de înscriere 05.09.2026 - 01.09.2026"),
        as_of,
    )
    assert reversed_window.state == "HOLD"
    assert reversed_window.hold_reason == "PROCESS_WINDOW_END_BEFORE_START"

    boundary_drift = normalize_signal(
        _base_signal("Înscriere termen limită 10.09.2026", public_projection_allowed=True),
        as_of,
    )
    assert boundary_drift.state == "HOLD"
    assert boundary_drift.hold_reason == "UPSTREAM_BOUNDARY_DRIFT_PUBLIC_PROJECTION_ALLOWED"

    taxonomy_drift = normalize_signal(
        _base_signal("Înscriere termen limită 10.09.2026", taxonomy_version="2099-drift"),
        as_of,
    )
    assert taxonomy_drift.state == "HOLD"
    assert taxonomy_drift.hold_reason == "SOURCE_TAXONOMY_DRIFT"

    print("ISJ education process-date fail-closed self-test: PASS")


def load_input(path: Optional[str]) -> list[dict[str, Any]]:
    if path:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        value = json.load(__import__("sys").stdin)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("input must be a JSON array of signal objects")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", help="JSON array of already-normalized ISJ education signals")
    parser.add_argument("--as-of", help="YYYY-MM-DD; required for deterministic temporal metadata")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    if not args.as_of:
        parser.error("--as-of is required outside --self-test")
    as_of = parse_iso_date(args.as_of)
    if as_of is None:
        parser.error("--as-of must be YYYY-MM-DD")

    states = normalize_signals(load_input(args.input), as_of)
    print(json.dumps([asdict(state) for state in states], ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
