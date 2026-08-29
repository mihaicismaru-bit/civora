#!/usr/bin/env python3
"""Deterministic, non-persistent ISU Vâlcea incident identity and revision state.

Consumes evidence-first snapshots emitted by the existing ISU Vâlcea
``comunicate-de-presa`` and ``stiri-locale`` adapters. It deduplicates exact
official article identities, preserves ordered metadata revisions, and links
cross-surface incident reports only on deterministic evidence.

Publication dates remain report metadata, never incident time or live state.
This module grants no persistence, Fact Kernel, Writer, breaking-news, public
projection, media-reuse, or publication authority.
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
from urllib.parse import unquote, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

BUCHAREST = ZoneInfo("Europe/Bucharest")
HOST = "isuvl.igsu.ro"
INCIDENT_CLASS = "PUBLIC_SAFETY_INCIDENT_REPORT"
ALLOWED_CLASSES = {
    INCIDENT_CLASS,
    "PUBLIC_SAFETY_ACTIVITY_SUMMARY",
    "PUBLIC_SAFETY_ADVISORY",
    "EMERGENCY_EXERCISE",
    "CIVIL_PROTECTION_REFERENCE",
    "HOLD",
}
SOURCES = {
    "signal-isu-valcea-comunicate": {
        "kind": "PUBLIC_SAFETY_OFFICIAL_REPORTS",
        "source_url": "https://isuvl.igsu.ro/comunicate-de-presa",
        "signal_prefix": "isu-safety-",
        "article_prefixes": ("/comunicate-de-presa/", "/stiri-locale/"),
    },
    "signal-isu-valcea-stiri-locale": {
        "kind": "PUBLIC_SAFETY_OFFICIAL_LOCAL_NEWS",
        "source_url": "https://isuvl.igsu.ro/stiri-locale",
        "signal_prefix": "isu-local-",
        "article_prefixes": ("/stiri-locale/",),
    },
}
REQUIRED_FALSE = (
    "article_body_ingest_allowed",
    "current_incident_claim_allowed",
    "casualty_count_inference_allowed",
    "medical_inference_allowed",
    "person_level_data_extraction_allowed",
    "media_public_reuse_allowed",
    "public_projection",
    "auto_publication",
    "persistence_allowed",
    "fact_kernel_authority",
)


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", clean_text(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalized_title(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", fold(value)).strip()


def parse_observed_at(value: Any) -> datetime:
    text = clean_text(value)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("snapshot observed_at requires an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("snapshot observed_at requires an offset-aware timestamp")
    return parsed.astimezone(BUCHAREST)


def parse_as_of(value: Any) -> datetime:
    return parse_observed_at(value)


def canonical_article_url(value: Any, *, source_id: str) -> str:
    text = clean_text(value)
    parsed = urlsplit(text)
    if (
        parsed.scheme.casefold() != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() != HOST
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("ISU thread state requires a canonical official HTTPS article URL")
    path = re.sub(r"/+", "/", unquote(parsed.path or "/"))
    prefixes = SOURCES[source_id]["article_prefixes"]
    if not any(path.startswith(prefix) for prefix in prefixes):
        raise ValueError("ISU thread state refuses article URL outside the source surface")
    return urlunsplit(("https", HOST, path, parsed.query, ""))


def parse_publication_date(signal: dict[str, Any]) -> date:
    values = signal.get("publication_dates")
    if signal.get("publication_date_status") != "EXPLICIT_INDEX_METADATA":
        raise ValueError("incident reports require explicit publication-date metadata")
    if not isinstance(values, list) or len(values) != 1:
        raise ValueError("incident reports require exactly one publication date")
    try:
        return date.fromisoformat(clean_text(values[0]))
    except ValueError as exc:
        raise ValueError("publication date requires YYYY-MM-DD") from exc


def public_fingerprint(signal: dict[str, Any]) -> str:
    payload = {key: value for key, value in signal.items() if not key.startswith("_")}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def validate_signal(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("ISU thread-state signals must be objects")

    source_id = clean_text(raw.get("source_id"))
    spec = SOURCES.get(source_id)
    if spec is None:
        raise ValueError("ISU thread state accepts only the two canonical ISU Vâlcea sources")
    if raw.get("source_kind") != spec["kind"]:
        raise ValueError("ISU thread state refuses source-kind drift")
    if raw.get("source_url") != spec["source_url"] or raw.get("final_url") != spec["source_url"]:
        raise ValueError("ISU thread state refuses source/final URL drift")

    signal_id = clean_text(raw.get("signal_id"))
    prefix = spec["signal_prefix"]
    if not re.fullmatch(re.escape(prefix) + r"[0-9a-f]{20}", signal_id):
        raise ValueError("ISU thread state requires a canonical signal_id")

    signal_class = clean_text(raw.get("signal_class")).upper()
    if signal_class not in ALLOWED_CLASSES:
        raise ValueError("ISU thread state refuses unknown signal_class")

    if raw.get("publication_authority") != "NONE":
        raise ValueError("ISU thread state refuses publication-authority drift")
    if any(raw.get(field) is not False for field in REQUIRED_FALSE):
        raise ValueError("ISU thread state refuses authority or safety-boundary drift")
    if raw.get("publication_date_is_not_live_status") is not True:
        raise ValueError("ISU thread state requires publication-date/live-status separation")

    title = clean_text(raw.get("title"))
    if not title:
        raise ValueError("ISU thread state requires a title")
    article_url = canonical_article_url(raw.get("article_url"), source_id=source_id)

    publication_date = None
    if signal_class == INCIDENT_CLASS:
        publication_date = parse_publication_date(raw)

    out = dict(raw)
    out.update(
        {
            "_source_id": source_id,
            "_signal_id": signal_id,
            "_signal_class": signal_class,
            "_title": title,
            "_title_key": normalized_title(title),
            "_article_url": article_url,
            "_publication_date": publication_date,
            "_fingerprint": public_fingerprint(raw),
        }
    )
    return out


def validate_snapshot(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("ISU thread-state snapshots must be objects")
    observed_at = parse_observed_at(raw.get("observed_at"))
    sha = clean_text(raw.get("source_content_sha256"))
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("snapshot source_content_sha256 requires SHA-256")
    signals_raw = raw.get("signals")
    if not isinstance(signals_raw, list):
        raise ValueError("snapshot signals must be a list")

    signals: dict[str, dict[str, Any]] = {}
    source_ids: set[str] = set()
    for item in signals_raw:
        signal = validate_signal(item)
        source_ids.add(signal["_source_id"])
        prior = signals.get(signal["_signal_id"])
        if prior is not None and prior["_fingerprint"] != signal["_fingerprint"]:
            raise ValueError("snapshot reuses signal_id with conflicting payload")
        signals[signal["_signal_id"]] = signal
    if len(source_ids) > 1:
        raise ValueError("snapshot must contain exactly one ISU source surface")
    source_id = next(iter(source_ids), clean_text(raw.get("source_id")))
    if source_id not in SOURCES:
        raise ValueError("empty snapshot requires canonical source_id")
    if raw.get("source_id") not in (None, "", source_id):
        raise ValueError("snapshot source_id conflicts with contained signals")
    return {
        "observed_at": observed_at,
        "source_content_sha256": sha,
        "source_id": source_id,
        "signals": signals,
    }


def prepare_snapshots(raw_snapshots: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_snapshots, list) or not raw_snapshots:
        raise ValueError("snapshots must be a non-empty list")
    validated = [validate_snapshot(item) for item in raw_snapshots]

    by_source_time: dict[tuple[str, datetime], str] = {}
    by_source_sha: dict[tuple[str, str], dict[str, Any]] = {}
    for snapshot in validated:
        time_key = (snapshot["source_id"], snapshot["observed_at"])
        prior_sha = by_source_time.get(time_key)
        if prior_sha is not None and prior_sha != snapshot["source_content_sha256"]:
            raise ValueError("same source observed_at has conflicting content hashes")
        by_source_time[time_key] = snapshot["source_content_sha256"]

        sha_key = (snapshot["source_id"], snapshot["source_content_sha256"])
        prior = by_source_sha.get(sha_key)
        if prior is None or snapshot["observed_at"] < prior["observed_at"]:
            by_source_sha[sha_key] = snapshot

    return sorted(
        by_source_sha.values(),
        key=lambda item: (item["observed_at"], item["source_id"], item["source_content_sha256"]),
    )


def revision_rows(observations: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obs in observations:
        grouped[obs["signal"]["_source_id"]].append(obs)

    rows: list[dict[str, Any]] = []
    has_revision = False
    for source_id in sorted(grouped):
        items = sorted(grouped[source_id], key=lambda x: x["observed_at"])
        unique: list[dict[str, Any]] = []
        last_fp = None
        seen_at: dict[datetime, str] = {}
        for item in items:
            fp = item["signal"]["_fingerprint"]
            prior = seen_at.get(item["observed_at"])
            if prior is not None and prior != fp:
                raise ValueError("same article/source observed_at has conflicting metadata revisions")
            seen_at[item["observed_at"]] = fp
            if fp == last_fp:
                continue
            unique.append(item)
            last_fp = fp
        has_revision = has_revision or len(unique) > 1
        rows.append(
            {
                "source_id": source_id,
                "revision_count": len(unique),
                "revision_state": "ORDERED_METADATA_REVISION" if len(unique) > 1 else "UNCHANGED_METADATA",
                "first_observed_at": unique[0]["observed_at"].isoformat(),
                "last_observed_at": unique[-1]["observed_at"].isoformat(),
                "signal_ids": [item["signal"]["_signal_id"] for item in unique],
                "titles": [item["signal"]["_title"] for item in unique],
                "publication_dates": [
                    item["signal"]["_publication_date"].isoformat() for item in unique
                ],
            }
        )
    return rows, has_revision


def thread_id(seed: str) -> str:
    return "isu-incident-thread-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def build_state(raw_snapshots: Any, *, as_of: str) -> dict[str, Any]:
    snapshots = prepare_snapshots(raw_snapshots)
    as_of_dt = parse_as_of(as_of)

    observations: list[dict[str, Any]] = []
    skipped_non_incident = 0
    for snapshot in snapshots:
        if snapshot["observed_at"] > as_of_dt:
            raise ValueError("as_of precedes an included snapshot observation")
        for signal in snapshot["signals"].values():
            if signal["_signal_class"] != INCIDENT_CLASS:
                skipped_non_incident += 1
                continue
            observations.append({"observed_at": snapshot["observed_at"], "signal": signal})

    by_url: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obs in observations:
        by_url[obs["signal"]["_article_url"]].append(obs)

    url_records: dict[str, dict[str, Any]] = {}
    for url, items in by_url.items():
        revisions, has_revision = revision_rows(items)
        dates = sorted(
            {
                obs["signal"]["_publication_date"].isoformat()
                for obs in items
                if obs["signal"]["_publication_date"] is not None
            }
        )
        titles = sorted({obs["signal"]["_title_key"] for obs in items})
        sources = sorted({obs["signal"]["_source_id"] for obs in items})
        url_records[url] = {
            "url": url,
            "observations": items,
            "revisions": revisions,
            "has_revision": has_revision,
            "publication_dates": dates,
            "title_keys": titles,
            "sources": sources,
            "date_conflict": len(dates) != 1,
        }

    parent = {url: url for url in url_records}

    def find(url: str) -> str:
        while parent[url] != url:
            parent[url] = parent[parent[url]]
            url = parent[url]
        return url

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    # Same canonical URL is already one record. Cross-URL links require exact
    # normalized title + exact report publication date, with at most one URL
    # candidate per source surface. No fuzzy title, place, or time inference.
    signatures: dict[tuple[str, str], list[str]] = defaultdict(list)
    for url, record in url_records.items():
        if record["date_conflict"] or len(record["title_keys"]) != 1:
            continue
        signatures[(record["publication_dates"][0], record["title_keys"][0])].append(url)

    ambiguous_urls: set[str] = set()
    for urls in signatures.values():
        if len(urls) < 2:
            continue
        per_source: dict[str, set[str]] = defaultdict(set)
        for url in urls:
            for source in url_records[url]["sources"]:
                per_source[source].add(url)
        if any(len(values) > 1 for values in per_source.values()) or len(urls) > len(SOURCES):
            ambiguous_urls.update(urls)
            continue
        for url in urls[1:]:
            union(urls[0], url)

    groups: dict[str, list[str]] = defaultdict(list)
    for url in sorted(url_records):
        groups[find(url)].append(url)

    threads: list[dict[str, Any]] = []
    for _, urls in sorted(groups.items()):
        records = [url_records[url] for url in sorted(urls)]
        all_dates = sorted({value for record in records for value in record["publication_dates"]})
        all_sources = sorted({source for record in records for source in record["sources"]})
        identity_ambiguous = any(url in ambiguous_urls for url in urls)
        date_conflict = len(all_dates) != 1
        report_date = date.fromisoformat(all_dates[0]) if not date_conflict else None

        if identity_ambiguous:
            identity_state = "HOLD_AMBIGUOUS_EXACT_SIGNATURE"
            identity_basis = "NONE"
        elif len(urls) > 1:
            identity_state = "LINKED_CROSS_SURFACE"
            identity_basis = "EXACT_NORMALIZED_TITLE_AND_PUBLICATION_DATE_UNIQUE_PER_SURFACE"
        elif len(all_sources) > 1:
            identity_state = "DEDUPED_CROSS_SURFACE"
            identity_basis = "SAME_CANONICAL_OFFICIAL_ARTICLE_URL"
        else:
            identity_state = "SINGLE_SURFACE_THREAD"
            identity_basis = "SAME_CANONICAL_OFFICIAL_ARTICLE_URL"

        if date_conflict:
            freshness_state = "HOLD_CONFLICTING_PUBLICATION_DATE"
            report_age_days = None
        else:
            report_age_days = (as_of_dt.date() - report_date).days
            freshness_state = (
                "HOLD_FUTURE_PUBLICATION_DATE"
                if report_age_days < 0
                else "REPORT_PUBLISHED_SOURCE_RECHECK_REQUIRED"
            )

        threads.append(
            {
                "thread_id": thread_id("|".join(sorted(urls))),
                "signal_class": INCIDENT_CLASS,
                "identity_state": identity_state,
                "identity_basis": identity_basis,
                "article_urls": sorted(urls),
                "source_ids": all_sources,
                "publication_date": report_date.isoformat() if report_date else None,
                "report_age_days": report_age_days,
                "freshness_state": freshness_state,
                "has_ordered_metadata_revision": any(record["has_revision"] for record in records),
                "revisions": [row for record in records for row in record["revisions"]],
                "current_incident_claim_allowed": False,
                "breaking_status_claim_allowed": False,
                "incident_time_inference_allowed": False,
                "publication_date_is_not_incident_time": True,
                "publication_date_is_not_live_status": True,
                "source_recheck_required": True,
                "persistence_allowed": False,
                "fact_kernel_authority": False,
                "public_projection": False,
                "publication_authority": "NONE",
            }
        )

    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR ISU incident thread state",
        "as_of": as_of_dt.isoformat(),
        "snapshot_count": len(snapshots),
        "incident_observation_count": len(observations),
        "skipped_non_incident_observation_count": skipped_non_incident,
        "thread_count": len(threads),
        "threads": threads,
        "policy": {
            "signal_only": True,
            "current_incident_claim_allowed": False,
            "breaking_status_claim_allowed": False,
            "incident_time_inference_allowed": False,
            "publication_date_is_not_incident_time": True,
            "publication_date_is_not_live_status": True,
            "fuzzy_cross_surface_linking_allowed": False,
            "source_recheck_required": True,
            "persistence_allowed": False,
            "fact_kernel_authority": False,
            "public_projection": False,
            "publication_authority": "NONE",
        },
    }


def _signal(
    source_id: str,
    *,
    suffix: str,
    url: str,
    title: str,
    published: str,
    signal_class: str = INCIDENT_CLASS,
) -> dict[str, Any]:
    spec = SOURCES[source_id]
    return {
        "signal_id": spec["signal_prefix"] + (suffix * 20)[:20],
        "source_id": source_id,
        "source_name": "test",
        "source_url": spec["source_url"],
        "final_url": spec["source_url"],
        "source_tier": "T1",
        "source_kind": spec["kind"],
        "article_url": url,
        "title": title,
        "signal_class": signal_class,
        "publication_dates": [published],
        "publication_date_status": "EXPLICIT_INDEX_METADATA",
        "summary_excerpt": title,
        "article_body_ingest_allowed": False,
        "current_incident_claim_allowed": False,
        "publication_date_is_not_live_status": True,
        "casualty_count_inference_allowed": False,
        "medical_inference_allowed": False,
        "person_level_data_extraction_allowed": False,
        "media_candidates": [],
        "media_public_reuse_allowed": False,
        "publication_authority": "NONE",
        "public_projection": False,
        "auto_publication": False,
        "persistence_allowed": False,
        "fact_kernel_authority": False,
    }


def _snapshot(source_id: str, observed: str, sha_char: str, signals: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "observed_at": observed,
        "source_id": source_id,
        "source_content_sha256": sha_char * 64,
        "signals": signals,
    }


def self_test() -> int:
    press = "signal-isu-valcea-comunicate"
    local = "signal-isu-valcea-stiri-locale"
    shared_url = "https://isuvl.igsu.ro/stiri-locale/incendiu-autocar-762"
    s1 = _signal(
        press, suffix="a", url=shared_url,
        title="Incendiu autocar în municipiul Râmnicu Vâlcea", published="2026-08-22"
    )
    s2 = _signal(
        local, suffix="b", url=shared_url,
        title="Incendiu autocar în municipiul Râmnicu Vâlcea", published="2026-08-22"
    )
    state = build_state(
        [
            _snapshot(press, "2026-08-22T12:00:00+03:00", "a", [s1]),
            _snapshot(local, "2026-08-22T12:05:00+03:00", "b", [s2]),
        ],
        as_of="2026-08-29T22:00:00+03:00",
    )
    assert state["thread_count"] == 1
    assert state["threads"][0]["identity_state"] == "DEDUPED_CROSS_SURFACE"
    assert state["threads"][0]["report_age_days"] == 7
    assert state["threads"][0]["current_incident_claim_allowed"] is False

    revised = dict(s2)
    revised["title"] = "Incendiu autocar în municipiul Râmnicu Vâlcea — actualizare"
    revised["signal_id"] = SOURCES[local]["signal_prefix"] + "c" * 20
    state = build_state(
        [
            _snapshot(local, "2026-08-22T12:05:00+03:00", "c", [s2]),
            _snapshot(local, "2026-08-22T13:05:00+03:00", "d", [revised]),
        ],
        as_of="2026-08-29T22:00:00+03:00",
    )
    assert state["threads"][0]["has_ordered_metadata_revision"] is True

    other_url = "https://isuvl.igsu.ro/comunicate-de-presa/incendiu-autocar-valcea-900"
    same_title = _signal(
        press, suffix="d", url=other_url,
        title="Incendiu autocar în municipiul Râmnicu Vâlcea", published="2026-08-22"
    )
    state = build_state(
        [
            _snapshot(press, "2026-08-22T12:00:00+03:00", "e", [same_title]),
            _snapshot(local, "2026-08-22T12:05:00+03:00", "f", [s2]),
        ],
        as_of="2026-08-29T22:00:00+03:00",
    )
    assert state["thread_count"] == 1
    assert state["threads"][0]["identity_state"] == "LINKED_CROSS_SURFACE"

    duplicate_press = _signal(
        press, suffix="e",
        url="https://isuvl.igsu.ro/comunicate-de-presa/incendiu-autocar-valcea-901",
        title="Incendiu autocar în municipiul Râmnicu Vâlcea", published="2026-08-22",
    )
    state = build_state(
        [
            _snapshot(press, "2026-08-22T12:00:00+03:00", "1", [same_title, duplicate_press]),
            _snapshot(local, "2026-08-22T12:05:00+03:00", "2", [s2]),
        ],
        as_of="2026-08-29T22:00:00+03:00",
    )
    assert state["thread_count"] == 3
    assert all(t["identity_state"] == "HOLD_AMBIGUOUS_EXACT_SIGNATURE" for t in state["threads"])

    future = _signal(
        local, suffix="f",
        url="https://isuvl.igsu.ro/stiri-locale/incendiu-test-999",
        title="Incendiu test", published="2026-09-01",
    )
    state = build_state(
        [_snapshot(local, "2026-08-29T20:00:00+03:00", "3", [future])],
        as_of="2026-08-29T22:00:00+03:00",
    )
    assert state["threads"][0]["freshness_state"] == "HOLD_FUTURE_PUBLICATION_DATE"

    non_incident = _signal(
        local, suffix="1",
        url="https://isuvl.igsu.ro/stiri-locale/exercitiu-test-998",
        title="Exercițiu test", published="2026-08-29", signal_class="EMERGENCY_EXERCISE",
    )
    state = build_state(
        [_snapshot(local, "2026-08-29T20:00:00+03:00", "4", [non_incident])],
        as_of="2026-08-29T22:00:00+03:00",
    )
    assert state["thread_count"] == 0
    assert state["skipped_non_incident_observation_count"] == 1

    drift = dict(s2)
    drift["publication_authority"] = "AUTO"
    try:
        build_state(
            [_snapshot(local, "2026-08-22T12:05:00+03:00", "5", [drift])],
            as_of="2026-08-29T22:00:00+03:00",
        )
        raise AssertionError("authority drift should fail")
    except ValueError:
        pass

    changed_same_time = dict(revised)
    try:
        build_state(
            [
                _snapshot(local, "2026-08-22T12:05:00+03:00", "6", [s2]),
                _snapshot(local, "2026-08-22T12:05:00+03:00", "7", [changed_same_time]),
            ],
            as_of="2026-08-29T22:00:00+03:00",
        )
        raise AssertionError("same source/time changed snapshot should fail")
    except ValueError:
        pass

    print("ISU incident thread-state self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--input", help="JSON file containing {'snapshots': [...]} or a snapshot list")
    parser.add_argument("--as-of", help="Offset-aware ISO timestamp used only for objective report age")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if not args.input or not args.as_of:
        parser.error("--input and --as-of are required unless --self-test is used")
    with open(args.input, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    snapshots = payload.get("snapshots") if isinstance(payload, dict) else payload
    print(json.dumps(build_state(snapshots, as_of=args.as_of), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
