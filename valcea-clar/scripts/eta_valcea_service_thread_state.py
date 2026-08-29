#!/usr/bin/env python3
"""Build deterministic, non-persistent ETA Vâlcea service-update thread state.

The threader consumes evidence-first signals emitted by eta_valcea_signal_adapter.py.
It deduplicates immutable signals, threads revisions of the same official notice, and
conservatively links distinct notices only when both explicitly name the same route
and their effective windows overlap/are adjacent. Freshness is a newsroom recheck
signal, never a live-status claim.

No persistence, Fact Kernel, Writer, public projection, or publication authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

SOURCE_ID = "signal-eta-valcea"
SOURCE_KIND = "PUBLIC_TRANSPORT"
ALLOWED_CLASSES = {"SERVICE_ALERT", "SCHEDULE_CHANGE", "FARE_OR_ACCESS_CHANGE", "HOLD"}
THREADABLE_CLASSES = {"SERVICE_ALERT", "SCHEDULE_CHANGE"}
BUCHAREST = ZoneInfo("Europe/Bucharest")
ROUTE_RE = re.compile(r"\btrase(?:u|ul)\s*(?:nr\.?\s*)?([0-9]{1,3}[A-Z]?)\b", re.IGNORECASE)
RESOLUTION_RE = re.compile(
    r"\b(?:reluar(?:e|ea)|reluat[ăa]?|restabil(?:ire|it[ăa]?)|normal(?:izare|izat[ăa]?)|"
    r"încheier(?:e|ea)|incheier(?:e|ea))\b",
    re.IGNORECASE,
)
UPDATE_RE = re.compile(
    r"\b(?:modific(?:are|at[ăa]?)|prelung(?:ire|it[ăa]?)|suspend(?:are|at[ăa]?)|"
    r"devia(?:re|t[ăa]?)|reluar(?:e|ea)|reluat[ăa]?)\b",
    re.IGNORECASE,
)


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", clean_text(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _parse_iso_date(value: Any, field: str, *, required: bool = False) -> date | None:
    text = clean_text(value)
    if not text:
        if required:
            raise ValueError(f"{field} requires ISO date")
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field} requires YYYY-MM-DD") from exc


def _parse_as_of(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(clean_text(value))
    except ValueError as exc:
        raise ValueError("as_of requires an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("as_of requires an offset-aware timestamp")
    return parsed.astimezone(BUCHAREST)


def _official_notice_url(value: Any) -> str:
    text = clean_text(value)
    if not re.fullmatch(r"https://eta-bus\.ro/comunicate/[^/?#]+", text):
        raise ValueError("ETA threader requires canonical official notice URL")
    return text


def _signal_fingerprint(signal: dict[str, Any]) -> str:
    return json.dumps(signal, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _logical_thread_id(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    return "eta-service-thread-" + digest


def _extract_routes(title: str) -> tuple[str, ...]:
    routes = {match.group(1).upper() for match in ROUTE_RE.finditer(clean_text(title))}
    return tuple(sorted(routes))


def _boundaries_ok(boundaries: Any) -> bool:
    if not isinstance(boundaries, dict):
        return False
    expected = {
        "lifecycle": "SIGNAL_ONLY",
        "publication_authority": "NONE",
        "public_projection": False,
        "auto_publication": False,
        "persistence_authority": "NONE",
        "fact_kernel_authority": "NONE",
        "writer_authority": "NONE",
        "live_status_claim_allowed": False,
        "static_timetable_is_live_status": False,
    }
    return all(boundaries.get(key) == value for key, value in expected.items())


def validate_signal(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("ETA thread input signals must be objects")
    source = raw.get("source")
    if not isinstance(source, dict) or source.get("id") != SOURCE_ID or source.get("kind") != SOURCE_KIND:
        raise ValueError("ETA threader accepts only canonical ETA Vâlcea signals")
    if not _boundaries_ok(raw.get("boundaries")):
        raise ValueError("ETA threader refuses authority or lifecycle boundary drift")

    signal_id = clean_text(raw.get("signal_id"))
    if not re.fullmatch(r"eta-[0-9a-f]{24}", signal_id):
        raise ValueError("ETA threader requires canonical signal_id")
    article_url = _official_notice_url(raw.get("article_url"))
    title = clean_text(raw.get("title"))
    if not title:
        raise ValueError("ETA threader requires title")

    classification = clean_text(raw.get("classification")).upper()
    if classification not in ALLOWED_CLASSES:
        raise ValueError("ETA threader refuses unknown classification")

    evidence = raw.get("evidence")
    if not isinstance(evidence, dict):
        raise ValueError("ETA threader requires evidence")
    evidence_sha = clean_text(evidence.get("content_sha256"))
    if not re.fullmatch(r"[0-9a-f]{64}", evidence_sha):
        raise ValueError("ETA threader requires SHA-256 evidence")
    if evidence.get("source_url") != article_url or evidence.get("source_host") != "eta-bus.ro":
        raise ValueError("ETA threader refuses evidence URL/host mismatch")

    start = _parse_iso_date(raw.get("effective_start"), "effective_start")
    end = _parse_iso_date(raw.get("effective_end"), "effective_end")
    if end and not start:
        raise ValueError("ETA threader refuses effective_end without effective_start")
    if start and end and end < start:
        raise ValueError("ETA threader refuses inverted effective window")

    cms_raw = clean_text(raw.get("cms_published_at"))
    cms_date: date | None = None
    if cms_raw:
        try:
            cms_date = date.fromisoformat(cms_raw[:10])
        except ValueError as exc:
            raise ValueError("cms_published_at requires ISO date/timestamp") from exc

    out = dict(raw)
    out.update(
        {
            "signal_id": signal_id,
            "article_url": article_url,
            "title": title,
            "classification": classification,
            "_start": start,
            "_end": end,
            "_cms_date": cms_date,
            "_routes": _extract_routes(title),
            "_resolution_hint": bool(RESOLUTION_RE.search(title)),
            "_update_hint": bool(UPDATE_RE.search(title)),
        }
    )
    return out


def _windows_touch(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Require explicit windows and at most one day of separation."""
    ls, le = left["_start"], left["_end"] or left["_start"]
    rs, re_ = right["_start"], right["_end"] or right["_start"]
    if not ls or not rs:
        return False
    assert le is not None and re_ is not None
    return not (le + timedelta(days=1) < rs or re_ + timedelta(days=1) < ls)


def _can_cross_url_join(thread: dict[str, Any], signal: dict[str, Any]) -> bool:
    latest = thread["signals"][-1]
    if latest["article_url"] == signal["article_url"]:
        return True
    if latest["classification"] not in THREADABLE_CLASSES or signal["classification"] not in THREADABLE_CLASSES:
        return False
    if latest["classification"] != signal["classification"]:
        return False
    if not latest["_routes"] or latest["_routes"] != signal["_routes"]:
        return False
    if not _windows_touch(latest, signal):
        return False
    if latest["_cms_date"] == signal["_cms_date"] and latest["_start"] == signal["_start"]:
        return False
    return latest["_update_hint"] or signal["_update_hint"]


def _new_thread(signal: dict[str, Any]) -> dict[str, Any]:
    return {
        "logical_thread_id": _logical_thread_id(signal["article_url"]),
        "signals": [signal],
        "article_urls": {signal["article_url"]},
        "routes": set(signal["_routes"]),
    }


def _append(thread: dict[str, Any], signal: dict[str, Any]) -> None:
    thread["signals"].append(signal)
    thread["article_urls"].add(signal["article_url"])
    thread["routes"].update(signal["_routes"])


def _sort_key(signal: dict[str, Any]) -> tuple[date, date, str]:
    return (
        signal["_cms_date"] or date.min,
        signal["_start"] or date.min,
        signal["signal_id"],
    )


def _freshness(latest: dict[str, Any], as_of_date: date) -> tuple[str, int | None]:
    """Record objective source age without inventing a freshness policy threshold."""
    cms_date = latest["_cms_date"]
    if cms_date is None:
        return "SOURCE_DATE_UNKNOWN_RECHECK_REQUIRED", None
    age = (as_of_date - cms_date).days
    if age < 0:
        return "SOURCE_TIMESTAMP_IN_FUTURE_HOLD", age
    if latest["classification"] == "HOLD":
        return "HOLD_NOT_FRESHNESS_ELIGIBLE", age
    if age == 0:
        return "SOURCE_PUBLISHED_TODAY_RECHECK_REQUIRED", age
    return "SOURCE_AGE_RECORDED_RECHECK_REQUIRED", age


def _effective_state(latest: dict[str, Any], as_of_date: date) -> str:
    start, end = latest["_start"], latest["_end"]
    if start is None:
        return "DATE_UNKNOWN_HOLD"
    if as_of_date < start:
        return "NOT_YET_EFFECTIVE"
    if end is not None and as_of_date > end:
        return "EXPLICIT_WINDOW_ENDED"
    if latest["_resolution_hint"]:
        return "RESOLUTION_REPORTED_RECHECK_REQUIRED"
    if end is not None:
        return "WITHIN_EXPLICIT_WINDOW_RECHECK_REQUIRED"
    return "OPEN_ENDED_RECHECK_REQUIRED"


def _render(thread: dict[str, Any], as_of_date: date) -> dict[str, Any]:
    signals = thread["signals"]
    latest = signals[-1]
    freshness, source_age_days = _freshness(latest, as_of_date)
    effective_state = _effective_state(latest, as_of_date)

    revisions: list[dict[str, Any]] = []
    for signal in signals:
        revisions.append(
            {
                "signal_id": signal["signal_id"],
                "article_url": signal["article_url"],
                "classification": signal["classification"],
                "cms_published_at": signal.get("cms_published_at"),
                "effective_start": signal.get("effective_start"),
                "effective_end": signal.get("effective_end"),
                "evidence_sha256": signal["evidence"]["content_sha256"],
                "resolution_hint": signal["_resolution_hint"],
            }
        )

    return {
        "logical_thread_id": thread["logical_thread_id"],
        "latest_signal_id": latest["signal_id"],
        "latest_title": latest["title"],
        "latest_classification": latest["classification"],
        "article_urls": sorted(thread["article_urls"]),
        "route_ids": sorted(thread["routes"]),
        "revision_count": len(signals),
        "revisions": revisions,
        "effective_state": effective_state,
        "source_freshness": freshness,
        "source_age_days": source_age_days,
        "resolution_reported": latest["_resolution_hint"],
        "current_status_claim_allowed": False,
        "reader_facing_eligible": False,
        "lifecycle": "INTERNAL_ETA_SERVICE_THREAD_NEEDS_SOURCE_RECHECK",
    }


def build_threads(signals: list[dict[str, Any]], *, as_of: str) -> dict[str, Any]:
    if not isinstance(signals, list):
        raise ValueError("ETA thread input requires a signals list")
    as_of_dt = _parse_as_of(as_of)
    as_of_date = as_of_dt.date()

    unique: dict[str, dict[str, Any]] = {}
    duplicate_signal_count = 0
    for raw in signals:
        signal = validate_signal(raw)
        existing = unique.get(signal["signal_id"])
        if existing is None:
            unique[signal["signal_id"]] = signal
            continue
        if _signal_fingerprint({k: v for k, v in existing.items() if not k.startswith("_")}) != _signal_fingerprint(
            {k: v for k, v in signal.items() if not k.startswith("_")}
        ):
            raise ValueError("ETA threader refuses conflicting reuse of signal_id")
        duplicate_signal_count += 1

    ordered = sorted(unique.values(), key=_sort_key)

    revision_dates: dict[tuple[str, date | None], str] = {}
    for signal in ordered:
        key = (signal["article_url"], signal["_cms_date"])
        prior = revision_dates.get(key)
        if prior is not None and prior != signal["signal_id"]:
            raise ValueError("ETA threader refuses same-URL revisions with ambiguous CMS-date ordering")
        revision_dates[key] = signal["signal_id"]

    threads: list[dict[str, Any]] = []
    for signal in ordered:
        exact = [thread for thread in threads if signal["article_url"] in thread["article_urls"]]
        if len(exact) == 1:
            _append(exact[0], signal)
            continue
        if len(exact) > 1:
            raise ValueError("ETA threader detected impossible duplicate article ownership")

        candidates = [thread for thread in threads if _can_cross_url_join(thread, signal)]
        if len(candidates) == 1:
            _append(candidates[0], signal)
        else:
            threads.append(_new_thread(signal))

    rendered = [_render(thread, as_of_date) for thread in threads]
    rendered.sort(
        key=lambda item: (
            item["revisions"][-1]["cms_published_at"] or "",
            item["latest_signal_id"],
        ),
        reverse=True,
    )
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR internal ETA service thread state",
        "as_of": as_of_dt.isoformat(),
        "signal_count": len(unique),
        "duplicate_signal_count": duplicate_signal_count,
        "thread_count": len(rendered),
        "threads": rendered,
        "policy": {
            "reader_facing_eligible": False,
            "publication_authority": "NONE",
            "public_projection": False,
            "auto_publication": False,
            "persistence_authority": "NONE",
            "fact_kernel_authority": "NONE",
            "writer_authority": "NONE",
            "current_status_claim_allowed": False,
            "static_timetable_is_live_status": False,
            "cross_url_linking": "SAME_CLASS_EXACT_ROUTE_SET_TOUCHING_WINDOWS_UPDATE_HINT_AND_ORDERABLE_DATES",
            "freshness_threshold_policy": "NONE_OBJECTIVE_SOURCE_AGE_ONLY",
            "source_recheck_required_before_current_status_claim": True,
        },
    }


def _fixture(
    suffix: str,
    *,
    title: str,
    classification: str = "SCHEDULE_CHANGE",
    cms: str = "2026-08-12",
    start: str | None = "2026-08-13",
    end: str | None = None,
    url_suffix: str | None = None,
    evidence_char: str = "a",
) -> dict[str, Any]:
    slug = url_suffix or suffix
    return {
        "schema_version": "1.0",
        "signal_id": "eta-" + hashlib.sha256(suffix.encode()).hexdigest()[:24],
        "source": {
            "id": SOURCE_ID,
            "name": "ETA S.A. Râmnicu Vâlcea",
            "tier": "T1",
            "kind": SOURCE_KIND,
            "canonical_url": "https://eta-bus.ro/comunicate",
        },
        "article_url": f"https://eta-bus.ro/comunicate/{slug}",
        "title": title,
        "classification": classification,
        "classification_reasons": [],
        "cms_published_at": cms,
        "cms_timestamp_semantics": "EXPLICIT_VISIBLE_CMS_DATE",
        "effective_start": start,
        "effective_end": end,
        "effective_time": None,
        "effective_semantics": "EXPLICIT_VISIBLE_EFFECTIVE_DATE" if start else None,
        "evidence": {
            "content_sha256": evidence_char * 64,
            "source_url": f"https://eta-bus.ro/comunicate/{slug}",
            "source_host": "eta-bus.ro",
        },
        "visual_candidate": None,
        "boundaries": {
            "lifecycle": "SIGNAL_ONLY",
            "publication_authority": "NONE",
            "public_projection": False,
            "auto_publication": False,
            "persistence_authority": "NONE",
            "fact_kernel_authority": "NONE",
            "writer_authority": "NONE",
            "live_status_claim_allowed": False,
            "static_timetable_is_live_status": False,
        },
    }


def self_test() -> None:
    first = _fixture("rev1", title="Modificare temporară program traseu 5", url_suffix="program-traseu-5")
    second = _fixture(
        "rev2",
        title="Prelungire modificare program traseu 5",
        cms="2026-08-14",
        start="2026-08-13",
        end="2026-08-16",
        url_suffix="program-traseu-5",
        evidence_char="b",
    )
    result = build_threads([second, first, first], as_of="2026-08-15T10:00:00+03:00")
    assert result["thread_count"] == 1
    assert result["duplicate_signal_count"] == 1
    thread = result["threads"][0]
    assert thread["revision_count"] == 2
    assert thread["effective_state"] == "WITHIN_EXPLICIT_WINDOW_RECHECK_REQUIRED"
    assert thread["current_status_claim_allowed"] is False

    start_notice = _fixture(
        "route7-start",
        title="Suspendare temporară traseu 7",
        cms="2026-08-20",
        start="2026-08-21",
        end="2026-08-22",
    )
    extension = _fixture(
        "route7-extension",
        title="Prelungire suspendare traseu 7",
        cms="2026-08-22",
        start="2026-08-22",
        end="2026-08-24",
    )
    linked = build_threads([start_notice, extension], as_of="2026-08-23T09:00:00+03:00")
    assert linked["thread_count"] == 1
    assert linked["threads"][0]["article_urls"] == sorted(
        [start_notice["article_url"], extension["article_url"]]
    )

    later = _fixture(
        "route7-later",
        title="Modificare traseu 7",
        cms="2026-09-20",
        start="2026-09-21",
        end="2026-09-21",
    )
    separated = build_threads([start_notice, later], as_of="2026-09-20T09:00:00+03:00")
    assert separated["thread_count"] == 2

    route8 = _fixture(
        "route8",
        title="Prelungire suspendare traseu 8",
        cms="2026-08-22",
        start="2026-08-22",
        end="2026-08-24",
    )
    assert build_threads([start_notice, route8], as_of="2026-08-23T09:00:00+03:00")["thread_count"] == 2

    expired = build_threads([extension], as_of="2026-08-25T09:00:00+03:00")["threads"][0]
    assert expired["effective_state"] == "EXPLICIT_WINDOW_ENDED"
    assert expired["current_status_claim_allowed"] is False

    open_alert = _fixture(
        "service-open",
        title="Întrerupere temporară serviciu informare",
        classification="SERVICE_ALERT",
        cms="2026-08-01",
        start="2026-08-01",
    )
    stale = build_threads([open_alert], as_of="2026-08-05T09:00:00+03:00")["threads"][0]
    assert stale["effective_state"] == "OPEN_ENDED_RECHECK_REQUIRED"
    assert stale["source_freshness"] == "SOURCE_AGE_RECORDED_RECHECK_REQUIRED"
    assert stale["source_age_days"] == 4

    resolved = _fixture(
        "route9-resume",
        title="Reluare circulație traseu 9",
        cms="2026-08-10",
        start="2026-08-10",
        end="2026-08-10",
    )
    resolved_thread = build_threads([resolved], as_of="2026-08-10T14:00:00+03:00")["threads"][0]
    assert resolved_thread["resolution_reported"] is True
    assert resolved_thread["effective_state"] == "RESOLUTION_REPORTED_RECHECK_REQUIRED"
    assert resolved_thread["reader_facing_eligible"] is False

    unknown = _fixture(
        "unknown-date",
        title="Informare întrerupere temporară serviciu",
        classification="SERVICE_ALERT",
        cms="2026-08-29",
        start=None,
    )
    unknown_thread = build_threads([unknown], as_of="2026-08-29T09:00:00+03:00")["threads"][0]
    assert unknown_thread["effective_state"] == "DATE_UNKNOWN_HOLD"

    ambiguous_a = _fixture(
        "amb-a",
        title="Modificare traseu 4",
        cms="2026-08-29",
        url_suffix="traseu-4",
        evidence_char="c",
    )
    ambiguous_b = _fixture(
        "amb-b",
        title="Prelungire modificare traseu 4",
        cms="2026-08-29",
        url_suffix="traseu-4",
        evidence_char="d",
    )
    try:
        build_threads([ambiguous_a, ambiguous_b], as_of="2026-08-29T09:00:00+03:00")
        raise AssertionError("same-day same-URL revision ambiguity must fail")
    except ValueError:
        pass

    bad = _fixture("bad", title="Modificare traseu 3")
    bad["boundaries"]["public_projection"] = True
    try:
        build_threads([bad], as_of="2026-08-29T09:00:00+03:00")
        raise AssertionError("public projection drift must fail")
    except ValueError:
        pass

    bad_host = _fixture("bad-host", title="Modificare traseu 3")
    bad_host["evidence"]["source_host"] = "example.org"
    try:
        build_threads([bad_host], as_of="2026-08-29T09:00:00+03:00")
        raise AssertionError("evidence host drift must fail")
    except ValueError:
        pass

    print("ETA service thread state self-test: OK")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--input", help="JSON file containing a list of ETA signals")
    ap.add_argument("--as-of", help="offset-aware ISO timestamp")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.input or not args.as_of:
        ap.error("--input and --as-of are required unless --self-test is used")
    with open(args.input, "r", encoding="utf-8") as fh:
        signals = json.load(fh)
    print(json.dumps(build_threads(signals, as_of=args.as_of), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
