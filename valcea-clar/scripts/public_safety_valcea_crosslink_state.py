#!/usr/bin/env python3
"""Build fail-closed cross-source public-safety cross-link candidates for Vâlcea.

This layer is deliberately non-public and non-persistent. It consumes already-sanitized
IPJ/ISU signal records plus normalized INFOTRAFIC events and emits only review candidates.
It never merges identities, deduplicates across authorities, or transfers live/breaking
status from one source to another.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

BUCHAREST = ZoneInfo("Europe/Bucharest")

IPJ_SOURCE = "signal-ipj-valcea-stiri"
ISU_SOURCES = {"signal-isu-valcea-comunicate", "signal-isu-valcea-stiri-locale"}
INFOTRAFIC_SOURCE = "signal-infotrafic-valcea"

INCIDENT_CLASS = "PUBLIC_SAFETY_INCIDENT_REPORT"
INFOTRAFIC_KIND = "ROAD_TRAFFIC_ALERTS"
INFOTRAFIC_LIFECYCLE = "INTERNAL_TRAFFIC_EVENT_NEEDS_SOURCE_RECHECK"

ROAD_RE = re.compile(r"\b(?P<kind>DN|DJ|DC|A)\s*[- ]?\s*(?P<number>\d{1,4}[A-Z]?)\b", re.I)
LOCALITY_PATTERNS = [
    re.compile(
        r"\b(?:în|in)\s+(?:municipiul|orașul|orasul|localitatea|comuna|zona)\s+"
        r"(?P<name>[^,.;:–—-]{2,64}?)(?=\s+(?:pe|din|unde|iar|și|si)\b|[,.;:–—-]|$)",
        re.I,
    ),
    re.compile(
        r"\bpe\s+raza\s+(?:municipiului|orașului|orasului|localității|localitatii|comunei)\s+"
        r"(?P<name>[^,.;:–—-]{2,64}?)(?=\s+(?:pe|din|unde|iar|și|si)\b|[,.;:–—-]|$)",
        re.I,
    ),
]

COLLISION_HINTS = ("accident rutier", "eveniment rutier", "coliziune")
VEHICLE_FIRE_HINTS = (
    "incendiu autocar", "incendiu autoturism", "incendiu autovehicul",
    "autoturism in flacari", "autovehicul in flacari",
)
GENERIC_FIRE_HINTS = ("incendiu",)

EXPECTED_FALSE = (
    "current_incident_claim_allowed",
    "public_projection",
    "auto_publication",
)
EXPECTED_NONE_AUTHORITY = ("publication_authority",)


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", clean_text(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_road(text: str) -> str | None:
    match = ROAD_RE.search(text)
    if not match:
        return None
    return f"{match.group('kind').upper()}{match.group('number').upper()}"


def normalize_locality(text: str) -> str | None:
    for pattern in LOCALITY_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        value = clean_text(match.group("name")).strip(" -–—")
        if value:
            return fold(value)
    return None


def event_family(text: str) -> str | None:
    value = fold(text)
    if any(fold(hint) in value for hint in VEHICLE_FIRE_HINTS):
        return "VEHICLE_FIRE"
    if any(fold(hint) in value for hint in COLLISION_HINTS):
        return "ROAD_COLLISION"
    if any(fold(hint) in value for hint in GENERIC_FIRE_HINTS):
        return "FIRE"
    return None


def _single_publication_date(record: dict[str, Any]) -> str:
    values = record.get("publication_dates")
    if not isinstance(values, list) or len(values) != 1:
        raise ValueError("signal requires exactly one explicit publication date")
    value = clean_text(values[0])
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("signal publication date must be ISO calendar date") from exc


def _validate_url(url: str, host: str) -> str:
    parsed = urlsplit(clean_text(url))
    if (
        parsed.scheme.casefold() != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() != host
        or parsed.username
        or parsed.password
    ):
        raise ValueError(f"cross-link bridge refused non-canonical {host} URL")
    return clean_text(url)


def _require_nonpublic_authority(record: dict[str, Any]) -> None:
    for key in EXPECTED_FALSE:
        if record.get(key) is not False:
            raise ValueError(f"cross-link bridge refuses authority drift: {key}")
    for key in EXPECTED_NONE_AUTHORITY:
        if record.get(key) != "NONE":
            raise ValueError(f"cross-link bridge refuses authority drift: {key}")
    if record.get("fact_kernel_authority") not in (False, None):
        raise ValueError("cross-link bridge refuses fact-kernel authority")
    if record.get("persistence_allowed") not in (False, None):
        raise ValueError("cross-link bridge refuses persistence authority")


def _blocked(source: str, record_id: str, reason: str, locator: str = "") -> dict[str, Any]:
    return {
        "source_group": source,
        "record_id": record_id,
        "locator_sha256": _sha(locator) if locator else None,
        "reason": reason,
    }


def normalize_ipj(record: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if record.get("source_id") != IPJ_SOURCE:
        raise ValueError("IPJ lane accepts only the canonical IPJ Vâlcea source")
    rid = clean_text(record.get("signal_id"))
    if not rid.startswith("ipj-news-"):
        raise ValueError("IPJ lane requires canonical signal_id")
    signal_class = clean_text(record.get("signal_class"))
    if signal_class == "HOLD_SENSITIVE_PERSON_ALERT_REVIEW_REQUIRED":
        if record.get("article_url") is not None:
            raise ValueError("sensitive IPJ alert must not expose article_url")
        if record.get("title") != "[SENSITIVE_PERSON_ALERT_WITHHELD]":
            raise ValueError("sensitive IPJ alert must keep title withheld")
        return None, _blocked("IPJ", rid, "SENSITIVE_PERSON_ALERT_EXCLUDED_FROM_CROSSLINK")
    if signal_class != INCIDENT_CLASS:
        return None, _blocked("IPJ", rid, "NON_INCIDENT_SIGNAL_EXCLUDED")
    _require_nonpublic_authority(record)
    if record.get("publication_date_status") != "EXPLICIT_INDEX_METADATA":
        return None, _blocked("IPJ", rid, "PUBLICATION_DATE_NOT_EXPLICIT")
    url = _validate_url(clean_text(record.get("article_url")), "vl.politiaromana.ro")
    title = clean_text(record.get("title"))
    published = _single_publication_date(record)
    road = normalize_road(title)
    locality = normalize_locality(title)
    family = event_family(title)
    if not road or not locality or not family:
        return None, _blocked("IPJ", rid, "INSUFFICIENT_EXPLICIT_IDENTITY", url)
    return {
        "source_group": "IPJ",
        "record_id": rid,
        "locator": url,
        "report_date": published,
        "road": road,
        "locality": locality,
        "event_family": family,
    }, None


def normalize_isu(record: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    source_id = clean_text(record.get("source_id"))
    if source_id not in ISU_SOURCES:
        raise ValueError("ISU lane accepts only canonical ISU Vâlcea source surfaces")
    rid = clean_text(record.get("signal_id"))
    if not rid:
        raise ValueError("ISU lane requires signal_id")
    if record.get("signal_class") != INCIDENT_CLASS:
        return None, _blocked("ISU", rid, "NON_INCIDENT_SIGNAL_EXCLUDED")
    _require_nonpublic_authority(record)
    if record.get("publication_date_status") != "EXPLICIT_INDEX_METADATA":
        return None, _blocked("ISU", rid, "PUBLICATION_DATE_NOT_EXPLICIT")
    url = _validate_url(clean_text(record.get("article_url")), "isuvl.igsu.ro")
    title = clean_text(record.get("title"))
    published = _single_publication_date(record)
    road = normalize_road(title)
    locality = normalize_locality(title)
    family = event_family(title)
    if not road or not locality or not family:
        return None, _blocked("ISU", rid, "INSUFFICIENT_EXPLICIT_IDENTITY", url)
    return {
        "source_group": "ISU",
        "record_id": rid,
        "locator": url,
        "report_date": published,
        "road": road,
        "locality": locality,
        "event_family": family,
    }, None


def _parse_timestamp(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(clean_text(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("INFOTRAFIC source_timestamp must be ISO") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("INFOTRAFIC source_timestamp must be offset-aware")
    return parsed.astimezone(BUCHAREST)


def normalize_infotrafic(
    record: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if record.get("source_id") != INFOTRAFIC_SOURCE or record.get("source_kind") != INFOTRAFIC_KIND:
        raise ValueError("INFOTRAFIC lane accepts only canonical normalized Vâlcea events")
    rid = clean_text(record.get("event_id"))
    if not rid.startswith("traffic-event-"):
        raise ValueError("INFOTRAFIC lane requires canonical event_id")
    if record.get("lifecycle") != INFOTRAFIC_LIFECYCLE:
        raise ValueError("INFOTRAFIC lane requires canonical normalized-event lifecycle")
    if record.get("publication_authority") != "NONE":
        raise ValueError("INFOTRAFIC lane refuses publication-authorized input")
    if record.get("public_projection") is not False or record.get("auto_publication") is not False:
        raise ValueError("INFOTRAFIC lane refuses reader-facing input")
    url = _validate_url(clean_text(record.get("article_url")), "politiaromana.ro")
    road = clean_text(record.get("road")).upper()
    if not ROAD_RE.fullmatch(road):
        raise ValueError("INFOTRAFIC lane requires canonical road")
    locality_raw = record.get("locality")
    locality = fold(locality_raw) if locality_raw else None
    if not locality:
        return None, _blocked("INFOTRAFIC", rid, "NO_EXPLICIT_LOCALITY_FOR_CROSS_SOURCE_MATCH", url)
    report_date = _parse_timestamp(record.get("source_timestamp")).date().isoformat()
    return {
        "source_group": "INFOTRAFIC",
        "record_id": rid,
        "locator": url,
        "report_date": report_date,
        "road": road,
        "locality": locality,
        "event_family": "TRAFFIC_EVENT_UNSPECIFIED",
    }, None


def _identity_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return item["report_date"], item["road"], item["locality"]


def _candidate_id(key: tuple[str, str, str], record_ids: list[str]) -> str:
    raw = "\0".join([*key, *sorted(record_ids)])
    return "public-safety-crosslink-" + _sha(raw)[:24]


def _render_candidate(
    key: tuple[str, str, str], records: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    per_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        per_source[record["source_group"]].append(record)
    if len(per_source) < 2:
        return None, None
    if any(len(items) != 1 for items in per_source.values()):
        ids = sorted(record["record_id"] for record in records)
        return None, {
            "candidate_key_sha256": _sha("\0".join(key)),
            "record_ids": ids,
            "reason": "AMBIGUOUS_MULTIPLE_RECORDS_PER_SOURCE_FOR_EXACT_KEY",
        }

    known_families = {
        record["event_family"]
        for record in records
        if record["event_family"] != "TRAFFIC_EVENT_UNSPECIFIED"
    }
    if len(known_families) != 1:
        return None, {
            "candidate_key_sha256": _sha("\0".join(key)),
            "record_ids": sorted(record["record_id"] for record in records),
            "reason": "INCOMPATIBLE_OR_MISSING_EVENT_FAMILY",
        }

    ids = sorted(record["record_id"] for record in records)
    refs = [
        {
            "source_group": record["source_group"],
            "record_id": record["record_id"],
            "locator": record["locator"],
        }
        for record in sorted(records, key=lambda item: (item["source_group"], item["record_id"]))
    ]
    return {
        "candidate_id": _candidate_id(key, ids),
        "candidate_state": "CANDIDATE_FOR_EDITORIAL_CROSSLINK_RECHECK_REQUIRED",
        "report_date": key[0],
        "road": key[1],
        "locality_key": key[2],
        "event_family": next(iter(known_families)),
        "source_groups": sorted(per_source),
        "records": refs,
        "identity_basis": (
            "EXACT_REPORT_CALENDAR_DATE_PLUS_EXACT_ROAD_PLUS_EXACT_LOCALITY"
            "_WITH_COMPATIBLE_EXPLICIT_EVENT_FAMILY"
        ),
        "report_date_is_not_incident_time": True,
        "cross_source_identity_merge_allowed": False,
        "cross_source_dedupe_allowed": False,
        "live_status_transfer_allowed": False,
        "breaking_status_transfer_allowed": False,
        "current_incident_claim_allowed": False,
        "source_recheck_required": True,
        "reader_facing_eligible": False,
        "persistence_allowed": False,
        "fact_kernel_authority": False,
        "public_projection": False,
        "publication_authority": "NONE",
    }, None


def build_crosslinks(bundle: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        raise ValueError("cross-link input must be a JSON object")
    lanes = (
        ("ipj_signals", normalize_ipj),
        ("isu_signals", normalize_isu),
        ("infotrafic_events", normalize_infotrafic),
    )
    eligible: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], dict[str, Any]] = {}

    for lane_name, normalizer in lanes:
        values = bundle.get(lane_name, [])
        if not isinstance(values, list):
            raise ValueError(f"{lane_name} must be a list")
        for raw in values:
            if not isinstance(raw, dict):
                raise ValueError(f"{lane_name} entries must be objects")
            item, hold = normalizer(raw)
            if hold is not None:
                blocked.append(hold)
                continue
            assert item is not None
            identity = (item["source_group"], item["record_id"])
            previous = seen.get(identity)
            if previous is not None:
                if previous != item:
                    raise ValueError("cross-link bridge refuses conflicting reuse of a record id")
                continue
            seen[identity] = item
            eligible.append(item)

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in eligible:
        grouped[_identity_key(item)].append(item)

    candidates: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    for key, records in sorted(grouped.items()):
        candidate, hold = _render_candidate(key, records)
        if candidate is not None:
            candidates.append(candidate)
        if hold is not None:
            ambiguous.append(hold)

    candidates.sort(key=lambda item: (item["report_date"], item["candidate_id"]), reverse=True)
    blocked.sort(key=lambda item: (item["source_group"], item["record_id"], item["reason"]))
    ambiguous.sort(key=lambda item: (item["reason"], item["candidate_key_sha256"]))

    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR public-safety cross-source review candidates",
        "eligible_record_count": len(eligible),
        "candidate_count": len(candidates),
        "blocked_record_count": len(blocked),
        "ambiguous_group_count": len(ambiguous),
        "candidates": candidates,
        "blocked_records": blocked,
        "ambiguous_groups": ambiguous,
        "policy": {
            "reader_facing_eligible": False,
            "publication_authority": "NONE",
            "public_projection": False,
            "auto_publication": False,
            "persistence_allowed": False,
            "fact_kernel_authority": False,
            "cross_source_identity_merge_allowed": False,
            "cross_source_dedupe_allowed": False,
            "live_status_transfer_allowed": False,
            "breaking_status_transfer_allowed": False,
            "current_incident_claim_allowed": False,
            "report_date_is_not_incident_time": True,
            "fuzzy_matching_allowed": False,
            "source_recheck_required": True,
        },
    }


def _base_signal(source_id: str, rid: str, url: str, title: str, published: str) -> dict[str, Any]:
    return {
        "signal_id": rid,
        "source_id": source_id,
        "article_url": url,
        "title": title,
        "signal_class": INCIDENT_CLASS,
        "publication_dates": [published],
        "publication_date_status": "EXPLICIT_INDEX_METADATA",
        "current_incident_claim_allowed": False,
        "public_projection": False,
        "auto_publication": False,
        "publication_authority": "NONE",
        "fact_kernel_authority": False,
        "persistence_allowed": False,
    }


def self_test() -> int:
    ipj = _base_signal(
        IPJ_SOURCE,
        "ipj-news-" + "a" * 20,
        "https://vl.politiaromana.ro/ro/stiri/accident-dn7",
        "Accident rutier pe DN7 în localitatea Bujoreni",
        "2026-08-29",
    )
    isu = _base_signal(
        "signal-isu-valcea-stiri-locale",
        "isu-local-" + "b" * 20,
        "https://isuvl.igsu.ro/stiri-locale/accident-dn7",
        "Accident rutier pe DN 7 în localitatea Bujoreni",
        "2026-08-29",
    )
    state = build_crosslinks({"ipj_signals": [ipj], "isu_signals": [isu]})
    assert state["candidate_count"] == 1
    candidate = state["candidates"][0]
    assert candidate["source_groups"] == ["IPJ", "ISU"]
    assert candidate["cross_source_identity_merge_allowed"] is False
    assert candidate["live_status_transfer_allowed"] is False

    traffic = {
        "event_id": "traffic-event-" + "c" * 24,
        "source_id": INFOTRAFIC_SOURCE,
        "source_kind": INFOTRAFIC_KIND,
        "article_url": "https://politiaromana.ro/ro/info-trafic/accident-dn7",
        "source_timestamp": "2026-08-29T14:00:00+03:00",
        "road": "DN7",
        "locality": "Bujoreni",
        "lifecycle": INFOTRAFIC_LIFECYCLE,
        "publication_authority": "NONE",
        "public_projection": False,
        "auto_publication": False,
    }
    state = build_crosslinks(
        {"ipj_signals": [ipj], "isu_signals": [isu], "infotrafic_events": [traffic]}
    )
    assert state["candidate_count"] == 1
    assert state["candidates"][0]["source_groups"] == ["INFOTRAFIC", "IPJ", "ISU"]

    fire = dict(isu)
    fire["signal_id"] = "isu-local-" + "d" * 20
    fire["article_url"] = "https://isuvl.igsu.ro/stiri-locale/incendiu-dn7"
    fire["title"] = "Incendiu autoturism pe DN7 în localitatea Bujoreni"
    state = build_crosslinks({"ipj_signals": [ipj], "isu_signals": [fire]})
    assert state["candidate_count"] == 0
    assert state["ambiguous_group_count"] == 1
    assert state["ambiguous_groups"][0]["reason"] == "INCOMPATIBLE_OR_MISSING_EVENT_FAMILY"

    ipj2 = dict(ipj)
    ipj2["signal_id"] = "ipj-news-" + "e" * 20
    ipj2["article_url"] = "https://vl.politiaromana.ro/ro/stiri/alt-accident-dn7"
    state = build_crosslinks({"ipj_signals": [ipj, ipj2], "isu_signals": [isu]})
    assert state["candidate_count"] == 0
    assert state["ambiguous_groups"][0]["reason"] == "AMBIGUOUS_MULTIPLE_RECORDS_PER_SOURCE_FOR_EXACT_KEY"

    sensitive = dict(ipj)
    sensitive.update(
        {
            "signal_id": "ipj-news-" + "f" * 20,
            "signal_class": "HOLD_SENSITIVE_PERSON_ALERT_REVIEW_REQUIRED",
            "article_url": None,
            "title": "[SENSITIVE_PERSON_ALERT_WITHHELD]",
        }
    )
    state = build_crosslinks({"ipj_signals": [sensitive]})
    assert state["candidate_count"] == 0
    assert state["blocked_records"][0]["reason"] == "SENSITIVE_PERSON_ALERT_EXCLUDED_FROM_CROSSLINK"
    assert state["blocked_records"][0]["locator_sha256"] is None
    rendered = json.dumps(state, ensure_ascii=False)
    assert "SENSITIVE_PERSON_ALERT_WITHHELD" not in rendered

    no_locality = dict(traffic)
    no_locality["event_id"] = "traffic-event-" + "9" * 24
    no_locality["locality"] = None
    state = build_crosslinks({"infotrafic_events": [no_locality]})
    assert state["blocked_records"][0]["reason"] == "NO_EXPLICIT_LOCALITY_FOR_CROSS_SOURCE_MATCH"

    print("public-safety cross-link self-test: ok")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build fail-closed Vâlcea public-safety cross-source review candidates"
    )
    parser.add_argument("input", nargs="?", help="Bundle JSON path, or '-' for stdin")
    parser.add_argument("--output", default="-", help="Output JSON path, or '-' for stdout")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        raise SystemExit(self_test())
    if not args.input:
        parser.error("input is required unless --self-test is used")

    if args.input == "-":
        import sys
        bundle = json.load(sys.stdin)
    else:
        with open(args.input, "r", encoding="utf-8") as handle:
            bundle = json.load(handle)

    result = build_crosslinks(bundle)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output == "-":
        print(rendered, end="")
    else:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered)


if __name__ == "__main__":
    main()
