#!/usr/bin/env python3
"""Bounded live traffic temporal-evidence flow for VÂLCEA CLAR newsroom intelligence."""

from __future__ import annotations

import argparse
import http.client
import json
import sys
from typing import Any

import infotrafic_valcea_recent_reference_adapter as infotrafic
import ipj_valcea_road_traffic_news_reference_adapter as ipj
import traffic_dossier_thread_candidate_engine as dossier
import traffic_explicit_temporal_evidence_adapter as temporal
import traffic_reference_correlator as correlator

CONTENT_CONTRACT = "NEWSROOM_TRAFFIC_TEMPORAL_EVIDENCE_FLOW_ONLY"
MAX_REFERENCES_PER_SOURCE = 4
MAX_LIVE_REFERENCES = MAX_REFERENCES_PER_SOURCE * 2

EXPECTED_CONTRACTS = {
    "INFOTRAFIC": infotrafic.CONTENT_CONTRACT,
    "IPJ_VALCEA": ipj.CONTENT_CONTRACT,
}

DISABLED_CAPABILITIES = [
    "local_timezone_inference",
    "same_incident_inference",
    "current_state_inference",
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


class FlowInputError(RuntimeError):
    pass


def _bounded_references(payload: dict[str, Any], family: str) -> list[dict[str, Any]]:
    if payload.get("state") != "CLEAR":
        raise FlowInputError(f"{family} reference source is not CLEAR")
    if payload.get("content_contract") != EXPECTED_CONTRACTS[family]:
        raise FlowInputError(f"unexpected {family} reference content contract")
    raw = payload.get("references")
    if not isinstance(raw, list) or len(raw) > 64:
        raise FlowInputError(f"{family} references are not a bounded list")

    safe: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise FlowInputError(f"{family} reference is not an object")
        title = item.get("title")
        url = item.get("url")
        if not isinstance(title, str) or not title.strip() or len(title) > 500:
            raise FlowInputError(f"{family} reference title is invalid")
        if not isinstance(url, str) or not url.startswith("https://") or len(url) > 1000:
            raise FlowInputError(f"{family} reference URL is invalid")
        temporal.canonical_reference_url(url)
        for flag in (
            "current_state_authorized",
            "active_status_authorized",
            "active_incident_authorized",
            "active_traffic_disruption_authorized",
            "current_service_state_authorized",
            "realtime_authorized",
        ):
            if item.get(flag) is True:
                raise FlowInputError(f"{family} reference unexpectedly authorizes {flag}")
        if url in seen:
            continue
        seen.add(url)
        safe.append(item)
        if len(safe) >= MAX_REFERENCES_PER_SOURCE:
            break
    return safe


def _bounded_payload(original: dict[str, Any], family: str, refs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "state": "CLEAR",
        "content_contract": EXPECTED_CONTRACTS[family],
        "references": refs,
        "source": original.get("source"),
        "disabled_capabilities": original.get("disabled_capabilities", []),
    }


def _require_temporal_payload(payload: dict[str, Any], allowed_urls: set[str]) -> dict[str, dict[str, Any]]:
    if payload.get("state") != "CLEAR":
        raise FlowInputError("temporal evidence source is not CLEAR")
    if payload.get("content_contract") != temporal.CONTENT_CONTRACT:
        raise FlowInputError("unexpected temporal evidence content contract")
    if payload.get("current_state_authorized") is True:
        raise FlowInputError("temporal evidence unexpectedly authorizes current state")
    if payload.get("active_incident_authorized") is True:
        raise FlowInputError("temporal evidence unexpectedly authorizes active incident")
    if payload.get("same_incident_authorized") is True:
        raise FlowInputError("temporal evidence unexpectedly authorizes same incident")
    if payload.get("breaking_news_authorized") is True or payload.get("publication_authorized") is True:
        raise FlowInputError("temporal evidence unexpectedly authorizes publication")

    raw = payload.get("entries")
    if not isinstance(raw, list) or len(raw) > MAX_LIVE_REFERENCES:
        raise FlowInputError("temporal evidence entries are not bounded")
    by_url: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise FlowInputError("temporal evidence entry is not an object")
        url = item.get("url")
        if not isinstance(url, str) or url not in allowed_urls:
            raise FlowInputError("temporal evidence escaped the selected reference set")
        if item.get("timestamp_authorized") is not True:
            raise FlowInputError("temporal evidence entry is not explicitly authorized")
        if item.get("basis") not in temporal.ALLOWED_TIMESTAMP_BASES:
            raise FlowInputError("temporal evidence basis is not allowlisted")
        if url in by_url and by_url[url] != item:
            raise FlowInputError("conflicting temporal evidence for selected URL")
        by_url[url] = item
    return by_url


def build_result(
    infotrafic_payload: dict[str, Any],
    ipj_payload: dict[str, Any],
    temporal_payload: dict[str, Any],
    fetch_failures: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    try:
        info_refs = _bounded_references(infotrafic_payload, "INFOTRAFIC")
        ipj_refs = _bounded_references(ipj_payload, "IPJ_VALCEA")
        selected = [("INFOTRAFIC", item) for item in info_refs] + [("IPJ_VALCEA", item) for item in ipj_refs]
        if not selected:
            raise FlowInputError("no bounded traffic references are available")
        selected_urls = {str(item["url"]) for _family, item in selected}
        authorized_by_url = _require_temporal_payload(temporal_payload, selected_urls)

        failures = fetch_failures or []
        if not isinstance(failures, list) or len(failures) > MAX_LIVE_REFERENCES:
            raise FlowInputError("fetch failure diagnostics are not bounded")
        failure_urls: set[str] = set()
        normalized_failures: list[dict[str, str]] = []
        for failure in failures:
            if not isinstance(failure, dict):
                raise FlowInputError("fetch failure diagnostic is not an object")
            family = str(failure.get("source_family", ""))
            url = str(failure.get("url", ""))
            error_class = str(failure.get("error_class", ""))
            if family not in EXPECTED_CONTRACTS or url not in selected_urls or not error_class or len(error_class) > 120:
                raise FlowInputError("fetch failure diagnostic is invalid")
            if url in authorized_by_url:
                raise FlowInputError("a URL cannot be both failed and temporally authorized")
            if url in failure_urls:
                continue
            failure_urls.add(url)
            normalized_failures.append(
                {"source_family": family, "url": url, "error_class": error_class}
            )

        source_by_url = {str(item["url"]): family for family, item in selected}
        authorized_counts = {"INFOTRAFIC": 0, "IPJ_VALCEA": 0}
        for url in authorized_by_url:
            authorized_counts[source_by_url[url]] += 1

        bounded_info = _bounded_payload(infotrafic_payload, "INFOTRAFIC", info_refs)
        bounded_ipj = _bounded_payload(ipj_payload, "IPJ_VALCEA", ipj_refs)
        correlation = correlator.build_result(bounded_info, bounded_ipj)
        if correlation.get("state") != "CLEAR":
            raise FlowInputError("bounded traffic correlation rejected selected references")

        thread_candidates = dossier.build_result(correlation, temporal_payload)
        if thread_candidates.get("state") != "CLEAR":
            raise FlowInputError("traffic dossier engine rejected explicit temporal evidence")

        for candidate in thread_candidates.get("candidates", []):
            for flag in (
                "same_incident_authorized",
                "current_state_authorized",
                "active_incident_authorized",
                "breaking_news_authorized",
                "publication_authorized",
                "eta_service_impact_authorized",
            ):
                if candidate.get(flag) is True:
                    raise FlowInputError(f"thread candidate unexpectedly authorizes {flag}")

        selected_count = len(selected)
        authorized_count = len(authorized_by_url)
        coverage_pct = round((authorized_count / selected_count) * 100, 1) if selected_count else 0.0
        return {
            "state": "CLEAR",
            "reason": "bounded_live_traffic_temporal_evidence_flow",
            "content_contract": CONTENT_CONTRACT,
            "evidence_claim": (
                "This read-only probe connects bounded first-party INFOTRAFIC and IPJ Valcea references to explicit "
                "offset-aware first-party temporal evidence, cross-source reference correlation, and dossier/thread "
                "candidate generation. Coverage is diagnostic only: it does not authorize current state, same-incident "
                "identity, breaking news, publication, or ETA impact."
            ),
            "selected_reference_count": selected_count,
            "selected_reference_counts": {
                "INFOTRAFIC": len(info_refs),
                "IPJ_VALCEA": len(ipj_refs),
            },
            "article_fetch_success_count": int(temporal_payload.get("requested_reference_count", 0)),
            "article_fetch_failure_count": len(normalized_failures),
            "temporal_authorized_count": authorized_count,
            "temporal_authorized_counts": authorized_counts,
            "temporal_coverage_percent": coverage_pct,
            "temporal_conflict_count": int(temporal_payload.get("conflict_count", 0)),
            "correlation_candidate_count": int(correlation.get("candidate_count", 0)),
            "thread_candidate_count": int(thread_candidates.get("candidate_count", 0)),
            "thread_candidates": thread_candidates.get("candidates", []),
            "skipped_missing_temporal_evidence": int(
                thread_candidates.get("skipped_missing_temporal_evidence", 0)
            ),
            "fetch_failures": sorted(
                normalized_failures, key=lambda item: (item["source_family"], item["url"])
            ),
            "current_state_authorized": False,
            "same_incident_authorized": False,
            "active_incident_authorized": False,
            "breaking_news_authorized": False,
            "publication_authorized": False,
            "eta_service_impact_authorized": False,
            "disabled_capabilities": DISABLED_CAPABILITIES,
        }
    except (FlowInputError, temporal.TemporalInputError, TypeError, ValueError) as exc:
        return {
            "state": "HOLD",
            "reason": "traffic_temporal_evidence_flow_input_rejected",
            "error": str(exc),
            "content_contract": CONTENT_CONTRACT,
            "selected_reference_count": 0,
            "temporal_authorized_count": 0,
            "correlation_candidate_count": 0,
            "thread_candidate_count": 0,
            "thread_candidates": [],
            "current_state_authorized": False,
            "same_incident_authorized": False,
            "active_incident_authorized": False,
            "breaking_news_authorized": False,
            "publication_authorized": False,
            "eta_service_impact_authorized": False,
            "disabled_capabilities": DISABLED_CAPABILITIES,
        }


def _collect_infotrafic() -> dict[str, Any]:
    pages: list[tuple[int, bytes]] = []
    unique_valcea: set[str] = set()
    observed = 0
    for page_number in range(1, infotrafic.MAX_SCAN_PAGES + 1):
        body = infotrafic.fetch_page(page_number)
        pages.append((page_number, body))
        refs, count = infotrafic.parse_page(page_number, body)
        observed += count
        unique_valcea.update(url for _title, url in refs)
        if len(unique_valcea) >= MAX_REFERENCES_PER_SOURCE and observed >= infotrafic.MIN_INDEX_REFERENCES:
            break
    return infotrafic.build_result(pages)


def _collect_live() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, str]]]:
    info_payload = _collect_infotrafic()
    ipj_payload = ipj.build_result(ipj.fetch_source())
    info_refs = _bounded_references(info_payload, "INFOTRAFIC")
    ipj_refs = _bounded_references(ipj_payload, "IPJ_VALCEA")
    selected = [("INFOTRAFIC", item) for item in info_refs] + [("IPJ_VALCEA", item) for item in ipj_refs]

    pages: list[tuple[str, bytes]] = []
    failures: list[dict[str, str]] = []
    for family, item in selected:
        url = str(item["url"])
        try:
            body, canonical = temporal.fetch_article(url)
            pages.append((canonical, body))
        except (temporal.TemporalInputError, OSError, http.client.HTTPException) as exc:
            failures.append(
                {
                    "source_family": family,
                    "url": url,
                    "error_class": type(exc).__name__,
                }
            )

    if pages:
        temporal_payload = temporal.build_result(pages)
    else:
        temporal_payload = {
            "state": "HOLD",
            "reason": "no_selected_traffic_article_fetch_succeeded",
            "content_contract": temporal.CONTENT_CONTRACT,
            "entries": [],
            "current_state_authorized": False,
            "active_incident_authorized": False,
            "same_incident_authorized": False,
            "breaking_news_authorized": False,
            "publication_authorized": False,
            "disabled_capabilities": temporal.DISABLED_CAPABILITIES,
        }
    return info_payload, ipj_payload, temporal_payload, failures


def _sample_reference_payload(contract: str, family: str) -> dict[str, Any]:
    if family == "INFOTRAFIC":
        refs = [
            {
                "title": "JUDEȚUL VÂLCEA: TRAFIC OPRIT PE DN 7 LA CĂLIMĂNEȘTI",
                "url": "https://politiaromana.ro/ro/info-trafic/judetul-valcea-dn-7-calimanesti-test",
                "signal_type": "TRAFFIC_STOPPAGE_REFERENCE",
                "current_state_authorized": False,
                "active_incident_authorized": False,
            }
        ]
    else:
        refs = [
            {
                "title": "ACCIDENT RUTIER PE DN 7 LA CĂLIMĂNEȘTI",
                "url": "https://vl.politiaromana.ro/ro/stiri-si-media/stiri/accident-dn-7-calimanesti-test",
                "signal_type": "ROAD_ACCIDENT_REFERENCE",
                "current_state_authorized": False,
                "active_incident_authorized": False,
            }
        ]
    return {"state": "CLEAR", "content_contract": contract, "references": refs}


def run_self_test() -> None:
    info = _sample_reference_payload(infotrafic.CONTENT_CONTRACT, "INFOTRAFIC")
    police = _sample_reference_payload(ipj.CONTENT_CONTRACT, "IPJ_VALCEA")
    pages = [
        (
            info["references"][0]["url"],
            b'<html><head><meta property="article:published_time" content="2026-09-01T10:00:00+03:00"></head></html>',
        ),
        (
            police["references"][0]["url"],
            b'<html><head><meta itemprop="datePublished" content="2026-09-01T10:40:00+03:00"></head></html>',
        ),
    ]
    temporal_payload = temporal.build_result(pages)
    result = build_result(info, police, temporal_payload)
    assert result["state"] == "CLEAR", result
    assert result["selected_reference_count"] == 2, result
    assert result["temporal_authorized_count"] == 2, result
    assert result["temporal_coverage_percent"] == 100.0, result
    assert result["correlation_candidate_count"] == 1, result
    assert result["thread_candidate_count"] == 1, result
    assert result["thread_candidates"][0]["same_incident_authorized"] is False
    assert result["thread_candidates"][0]["breaking_news_authorized"] is False

    one_page = temporal.build_result([pages[0]])
    partial = build_result(
        info,
        police,
        one_page,
        [
            {
                "source_family": "IPJ_VALCEA",
                "url": police["references"][0]["url"],
                "error_class": "TimeoutError",
            }
        ],
    )
    assert partial["state"] == "CLEAR", partial
    assert partial["temporal_authorized_count"] == 1
    assert partial["article_fetch_failure_count"] == 1
    assert partial["thread_candidate_count"] == 0
    assert partial["skipped_missing_temporal_evidence"] == 1

    unsafe = _sample_reference_payload(ipj.CONTENT_CONTRACT, "IPJ_VALCEA")
    unsafe["references"][0]["active_incident_authorized"] = True
    held = build_result(info, unsafe, temporal_payload)
    assert held["state"] == "HOLD", held
    assert held["thread_candidate_count"] == 0
    assert held["breaking_news_authorized"] is False

    foreign_temporal = dict(temporal_payload)
    foreign_temporal["entries"] = [
        {
            "url": "https://politiaromana.ro/ro/info-trafic/foreign",
            "timestamp": "2026-09-01T10:00:00+03:00",
            "basis": "FIRST_PARTY_EXPLICIT_PUBLISHED_AT",
            "timestamp_authorized": True,
        }
    ]
    held_foreign = build_result(info, police, foreign_temporal)
    assert held_foreign["state"] == "HOLD", held_foreign
    print("self-test: ok")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        run_self_test()
        return 0

    try:
        info_payload, ipj_payload, temporal_payload, failures = _collect_live()
        result = build_result(info_payload, ipj_payload, temporal_payload, failures)
    except (
        FlowInputError,
        temporal.TemporalInputError,
        infotrafic.ExternalInputError,
        ipj.ExternalInputError,
        OSError,
        http.client.HTTPException,
    ) as exc:
        result = {
            "state": "HOLD",
            "reason": "traffic_temporal_evidence_live_collection_failed",
            "error": str(exc),
            "content_contract": CONTENT_CONTRACT,
            "selected_reference_count": 0,
            "temporal_authorized_count": 0,
            "correlation_candidate_count": 0,
            "thread_candidate_count": 0,
            "thread_candidates": [],
            "current_state_authorized": False,
            "same_incident_authorized": False,
            "active_incident_authorized": False,
            "breaking_news_authorized": False,
            "publication_authorized": False,
            "eta_service_impact_authorized": False,
            "disabled_capabilities": DISABLED_CAPABILITIES,
        }

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if result.get("state") == "CLEAR" else 2


if __name__ == "__main__":
    raise SystemExit(main())
