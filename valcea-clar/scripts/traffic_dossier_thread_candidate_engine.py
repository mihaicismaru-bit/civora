#!/usr/bin/env python3
"""Fail-closed traffic dossier/thread candidates for VÂLCEA CLAR newsroom review."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from typing import Any

CONTENT_CONTRACT = "NEWSROOM_TRAFFIC_DOSSIER_THREAD_CANDIDATES_ONLY"
EXPECTED_CORRELATION_CONTRACT = "NEWSROOM_TRAFFIC_REFERENCE_CORRELATION_CANDIDATES_ONLY"
TEMPORAL_EVIDENCE_CONTRACT = "NEWSROOM_TRAFFIC_EXPLICIT_TEMPORAL_EVIDENCE_ONLY"
MAX_WINDOW_SECONDS = 6 * 60 * 60
MAX_CORRELATION_CANDIDATES = 256
MAX_TEMPORAL_ENTRIES = 512
MAX_OUTPUT_CANDIDATES = 128

ALLOWED_TIMESTAMP_BASES = {
    "FIRST_PARTY_EXPLICIT_DATETIME",
    "FIRST_PARTY_EXPLICIT_PUBLISHED_AT",
    "FIRST_PARTY_EXPLICIT_UPDATED_AT",
}

DISABLED_CAPABILITIES = [
    "same_incident_inference",
    "active_incident_inference",
    "active_traffic_disruption_inference",
    "current_road_state_inference",
    "eta_service_impact_inference",
    "realtime_arrival_inference",
    "breaking_news_promotion",
    "automatic_dossier_promotion",
    "fact_kernel_mutation",
    "writer",
    "persistence",
    "public_projection",
    "image_ingest",
    "inferred_photo_rights",
]


class ThreadInputError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _aware_iso8601(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip() or len(value) > 80:
        raise ThreadInputError("temporal evidence timestamp is invalid")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ThreadInputError("temporal evidence timestamp is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ThreadInputError("temporal evidence timestamp must include an explicit UTC offset")
    return parsed


def _require_correlation_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("state") != "CLEAR":
        raise ThreadInputError("correlation source is not CLEAR")
    if payload.get("content_contract") != EXPECTED_CORRELATION_CONTRACT:
        raise ThreadInputError("unexpected correlation content contract")
    raw = payload.get("candidates")
    if not isinstance(raw, list) or len(raw) > MAX_CORRELATION_CANDIDATES:
        raise ThreadInputError("correlation candidates must be a bounded list")

    safe: list[dict[str, Any]] = []
    for candidate in raw:
        if not isinstance(candidate, dict):
            raise ThreadInputError("correlation candidate is not an object")
        for flag in ("same_incident_authorized", "current_state_authorized", "breaking_news_authorized"):
            if candidate.get(flag) is True:
                raise ThreadInputError(f"correlation candidate unexpectedly authorizes {flag}")
        references = candidate.get("references")
        if not isinstance(references, list) or len(references) < 2 or len(references) > 8:
            raise ThreadInputError("correlation candidate references are invalid")
        families: set[str] = set()
        urls: set[str] = set()
        for ref in references:
            if not isinstance(ref, dict):
                raise ThreadInputError("correlation reference is not an object")
            family = ref.get("source_family")
            url = ref.get("url")
            if not isinstance(family, str) or not family.strip() or len(family) > 80:
                raise ThreadInputError("correlation source family is invalid")
            if not isinstance(url, str) or not url.startswith("https://") or len(url) > 1000:
                raise ThreadInputError("correlation URL is invalid")
            families.add(family)
            urls.add(url)
        if len(families) < 2 or len(urls) < 2:
            raise ThreadInputError("thread candidates require at least two distinct source families and URLs")

        roads = candidate.get("matched_roads", [])
        localities = candidate.get("matched_localities", [])
        if not isinstance(roads, list) or not isinstance(localities, list):
            raise ThreadInputError("correlation anchors are invalid")
        roads = sorted({item for item in roads if isinstance(item, str) and item.strip()})
        localities = sorted({item for item in localities if isinstance(item, str) and item.strip()})
        if not roads and not localities:
            raise ThreadInputError("correlation candidate has no explicit anchor")
        safe.append(
            {
                "candidate_key": str(candidate.get("candidate_key", "")),
                "rank_score": int(candidate.get("rank_score", 0)),
                "matched_roads": roads,
                "matched_localities": localities,
                "references": references,
                "transit_context": candidate.get("transit_context", []),
            }
        )
    return safe


def _require_temporal_evidence(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if payload.get("state") != "CLEAR":
        raise ThreadInputError("temporal evidence source is not CLEAR")
    if payload.get("content_contract") != TEMPORAL_EVIDENCE_CONTRACT:
        raise ThreadInputError("unexpected temporal evidence content contract")
    raw = payload.get("entries")
    if not isinstance(raw, list) or len(raw) > MAX_TEMPORAL_ENTRIES:
        raise ThreadInputError("temporal evidence entries must be a bounded list")

    by_url: dict[str, dict[str, Any]] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise ThreadInputError("temporal evidence entry is not an object")
        url = entry.get("url")
        basis = entry.get("basis")
        if not isinstance(url, str) or not url.startswith("https://") or len(url) > 1000:
            raise ThreadInputError("temporal evidence URL is invalid")
        if basis not in ALLOWED_TIMESTAMP_BASES:
            raise ThreadInputError("temporal evidence basis is not allowlisted")
        if entry.get("timestamp_authorized") is not True:
            raise ThreadInputError("temporal evidence timestamp is not explicitly authorized")
        parsed = _aware_iso8601(entry.get("timestamp"))
        normalized = parsed.isoformat()
        canonical = {"url": url, "timestamp": normalized, "basis": basis}
        existing = by_url.get(url)
        if existing is not None and existing != canonical:
            raise ThreadInputError("conflicting temporal evidence for the same URL")
        by_url[url] = canonical
    return by_url


def _anchor_key(candidate: dict[str, Any]) -> str:
    roads = ",".join(candidate["matched_roads"])
    localities = ",".join(candidate["matched_localities"])
    return f"roads={roads}|localities={localities}"


def _thread_id(anchor_key: str, refs: list[dict[str, Any]], first_at: str, last_at: str) -> str:
    canonical = json.dumps(
        {
            "anchor_key": anchor_key,
            "urls": sorted(str(item["url"]) for item in refs),
            "first_at": first_at,
            "last_at": last_at,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(canonical)[:24]


def _rank(base_score: int, span_seconds: int, source_count: int, reference_count: int) -> tuple[int, str]:
    proximity_bonus = 15 if span_seconds <= 60 * 60 else 10 if span_seconds <= 3 * 60 * 60 else 5
    diversity_bonus = min(10, max(0, source_count - 2) * 5)
    reference_bonus = min(5, max(0, reference_count - 2))
    score = min(95, max(0, base_score) + proximity_bonus + diversity_bonus + reference_bonus)
    if score >= 85:
        tier = "HIGH_EDITORIAL_REVIEW_PRIORITY"
    elif score >= 70:
        tier = "MEDIUM_EDITORIAL_REVIEW_PRIORITY"
    else:
        tier = "LOW_EDITORIAL_REVIEW_PRIORITY"
    return score, tier


def build_result(correlation_payload: dict[str, Any], temporal_payload: dict[str, Any]) -> dict[str, Any]:
    try:
        correlations = _require_correlation_payload(correlation_payload)
        temporal = _require_temporal_evidence(temporal_payload)
    except (ThreadInputError, TypeError, ValueError) as exc:
        return {
            "state": "HOLD",
            "reason": "traffic_thread_candidate_input_rejected",
            "error": str(exc),
            "content_contract": CONTENT_CONTRACT,
            "candidate_count": 0,
            "candidates": [],
            "disabled_capabilities": DISABLED_CAPABILITIES,
        }

    grouped: dict[str, list[dict[str, Any]]] = {}
    skipped_missing_temporal = 0
    for candidate in correlations:
        urls = {str(ref["url"]) for ref in candidate["references"]}
        if any(url not in temporal for url in urls):
            skipped_missing_temporal += 1
            continue
        grouped.setdefault(_anchor_key(candidate), []).append(candidate)

    output: list[dict[str, Any]] = []
    skipped_outside_window = 0
    for anchor_key, group in sorted(grouped.items()):
        refs_by_url: dict[str, dict[str, Any]] = {}
        transit_by_key: dict[str, dict[str, Any]] = {}
        roads: set[str] = set()
        localities: set[str] = set()
        base_score = 0
        source_families: set[str] = set()

        for candidate in group:
            roads.update(candidate["matched_roads"])
            localities.update(candidate["matched_localities"])
            base_score = max(base_score, int(candidate["rank_score"]))
            for ref in candidate["references"]:
                url = str(ref["url"])
                source_families.add(str(ref["source_family"]))
                refs_by_url[url] = {
                    "source_family": ref["source_family"],
                    "url": url,
                    "signal_type": ref.get("signal_type"),
                    "explicit_timestamp": temporal[url]["timestamp"],
                    "timestamp_basis": temporal[url]["basis"],
                }
            transit = candidate.get("transit_context")
            if isinstance(transit, list):
                for item in transit:
                    if not isinstance(item, dict):
                        continue
                    url = item.get("url")
                    if not isinstance(url, str) or not url.startswith("https://"):
                        continue
                    key = f"{item.get('route_code')}|{url}"
                    transit_by_key[key] = {
                        "route_code": item.get("route_code"),
                        "url": url,
                        "matched_localities": sorted(
                            item.get("matched_localities", [])
                            if isinstance(item.get("matched_localities"), list)
                            else []
                        ),
                        "service_impact_authorized": False,
                        "realtime_authorized": False,
                    }

        refs = sorted(refs_by_url.values(), key=lambda item: (str(item["source_family"]), str(item["url"])))
        if len(refs) < 2 or len(source_families) < 2:
            continue
        parsed_times = [_aware_iso8601(item["explicit_timestamp"]) for item in refs]
        first = min(parsed_times)
        last = max(parsed_times)
        span_seconds = int((last - first).total_seconds())
        if span_seconds < 0 or span_seconds > MAX_WINDOW_SECONDS:
            skipped_outside_window += 1
            continue

        score, tier = _rank(base_score, span_seconds, len(source_families), len(refs))
        first_at = first.isoformat()
        last_at = last.isoformat()
        output.append(
            {
                "thread_candidate_id": _thread_id(anchor_key, refs, first_at, last_at),
                "relationship": "SHARED_EXPLICIT_ANCHOR_WITHIN_EXPLICIT_TIME_WINDOW",
                "anchor_key": anchor_key,
                "matched_roads": sorted(roads),
                "matched_localities": sorted(localities),
                "explicit_time_window": {
                    "first_at": first_at,
                    "last_at": last_at,
                    "span_seconds": span_seconds,
                    "max_allowed_span_seconds": MAX_WINDOW_SECONDS,
                },
                "rank_score": score,
                "rank_tier": tier,
                "references": refs,
                "transit_context": sorted(
                    transit_by_key.values(), key=lambda item: (str(item.get("route_code")), str(item["url"]))
                ),
                "editorial_review_required": True,
                "same_incident_authorized": False,
                "current_state_authorized": False,
                "active_incident_authorized": False,
                "breaking_news_authorized": False,
                "publication_authorized": False,
                "eta_service_impact_authorized": False,
            }
        )

    output.sort(key=lambda item: (-int(item["rank_score"]), str(item["thread_candidate_id"])))
    output = output[:MAX_OUTPUT_CANDIDATES]
    evidence = json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "state": "CLEAR",
        "reason": "deterministic_explicit_time_bounded_traffic_thread_candidates",
        "content_contract": CONTENT_CONTRACT,
        "evidence_claim": (
            "A thread candidate exists only when safe cross-source correlation references share explicit anchors and every "
            "included reference has allowlisted, explicitly authorized first-party temporal evidence within six hours. "
            "It is an editorial review queue item, not evidence of the same incident, current disruption, or ETA impact."
        ),
        "correlation_candidate_count": len(correlations),
        "temporal_evidence_count": len(temporal),
        "skipped_missing_temporal_evidence": skipped_missing_temporal,
        "skipped_outside_time_window": skipped_outside_window,
        "candidate_count": len(output),
        "candidates": output,
        "evidence_sha256": sha256_bytes(evidence),
        "current_state_authorized": False,
        "breaking_news_authorized": False,
        "publication_authorized": False,
        "disabled_capabilities": DISABLED_CAPABILITIES,
    }


def _sample_correlation(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {"state": "CLEAR", "content_contract": EXPECTED_CORRELATION_CONTRACT, "candidates": candidates}


def _sample_temporal(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {"state": "CLEAR", "content_contract": TEMPORAL_EVIDENCE_CONTRACT, "entries": entries}


def run_self_test() -> None:
    correlation = _sample_correlation(
        [
            {
                "candidate_key": "a",
                "rank_score": 80,
                "matched_roads": ["DN7"],
                "matched_localities": ["CALIMANESTI"],
                "references": [
                    {
                        "source_family": "INFOTRAFIC",
                        "url": "https://politiaromana.ro/ro/info-trafic/a",
                        "signal_type": "TRAFFIC_STOPPAGE_REFERENCE",
                    },
                    {
                        "source_family": "IPJ_VALCEA",
                        "url": "https://vl.politiaromana.ro/ro/stiri-si-media/stiri/a",
                        "signal_type": "ROAD_ACCIDENT_REFERENCE",
                    },
                ],
                "transit_context": [],
                "same_incident_authorized": False,
                "current_state_authorized": False,
                "breaking_news_authorized": False,
            }
        ]
    )
    temporal = _sample_temporal(
        [
            {
                "url": "https://politiaromana.ro/ro/info-trafic/a",
                "timestamp": "2026-09-01T10:00:00+03:00",
                "basis": "FIRST_PARTY_EXPLICIT_DATETIME",
                "timestamp_authorized": True,
            },
            {
                "url": "https://vl.politiaromana.ro/ro/stiri-si-media/stiri/a",
                "timestamp": "2026-09-01T11:20:00+03:00",
                "basis": "FIRST_PARTY_EXPLICIT_PUBLISHED_AT",
                "timestamp_authorized": True,
            },
        ]
    )
    result = build_result(correlation, temporal)
    assert result["state"] == "CLEAR", result
    assert result["candidate_count"] == 1, result
    thread = result["candidates"][0]
    assert thread["explicit_time_window"]["span_seconds"] == 4800, thread
    assert thread["rank_score"] == 90, thread
    assert thread["editorial_review_required"] is True
    assert thread["same_incident_authorized"] is False
    assert thread["current_state_authorized"] is False
    assert thread["active_incident_authorized"] is False
    assert thread["breaking_news_authorized"] is False
    assert thread["publication_authorized"] is False
    assert thread["eta_service_impact_authorized"] is False

    missing = build_result(correlation, _sample_temporal(temporal["entries"][:1]))
    assert missing["state"] == "CLEAR", missing
    assert missing["candidate_count"] == 0, missing
    assert missing["skipped_missing_temporal_evidence"] == 1

    outside = _sample_temporal(
        [
            temporal["entries"][0],
            {
                "url": "https://vl.politiaromana.ro/ro/stiri-si-media/stiri/a",
                "timestamp": "2026-09-01T17:00:01+03:00",
                "basis": "FIRST_PARTY_EXPLICIT_DATETIME",
                "timestamp_authorized": True,
            },
        ]
    )
    too_far = build_result(correlation, outside)
    assert too_far["state"] == "CLEAR", too_far
    assert too_far["candidate_count"] == 0, too_far
    assert too_far["skipped_outside_time_window"] == 1

    unsafe_correlation = json.loads(json.dumps(correlation))
    unsafe_correlation["candidates"][0]["same_incident_authorized"] = True
    hold = build_result(unsafe_correlation, temporal)
    assert hold["state"] == "HOLD", hold

    naive = _sample_temporal(
        [
            {
                "url": "https://politiaromana.ro/ro/info-trafic/a",
                "timestamp": "2026-09-01T10:00:00",
                "basis": "FIRST_PARTY_EXPLICIT_DATETIME",
                "timestamp_authorized": True,
            }
        ]
    )
    hold = build_result(correlation, naive)
    assert hold["state"] == "HOLD", hold
    print("self-test: ok")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--correlation-json")
    parser.add_argument("--temporal-evidence-json")
    args = parser.parse_args(argv)

    if args.self_test:
        run_self_test()
        return 0
    if not args.correlation_json or not args.temporal_evidence_json:
        parser.error("--correlation-json and --temporal-evidence-json are required unless --self-test is used")

    def load(path: str) -> dict[str, Any]:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ThreadInputError("input JSON root must be an object")
        return value

    try:
        correlation = load(args.correlation_json)
        temporal = load(args.temporal_evidence_json)
        result = build_result(correlation, temporal)
    except (ThreadInputError, OSError, json.JSONDecodeError) as exc:
        result = {
            "state": "HOLD",
            "reason": "traffic_thread_candidate_input_failed",
            "error": str(exc),
            "content_contract": CONTENT_CONTRACT,
            "candidate_count": 0,
            "candidates": [],
            "disabled_capabilities": DISABLED_CAPABILITIES,
        }

    json.dump(result, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if result["state"] == "CLEAR" else 2


if __name__ == "__main__":
    raise SystemExit(main())
