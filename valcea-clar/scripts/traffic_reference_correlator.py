#!/usr/bin/env python3
"""Fail-closed cross-source traffic reference correlation for VÂLCEA CLAR newsroom intelligence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from itertools import product
from typing import Any

CONTENT_CONTRACT = "NEWSROOM_TRAFFIC_REFERENCE_CORRELATION_CANDIDATES_ONLY"
EXPECTED_CONTRACTS = {
    "infotrafic": "FIRST_PARTY_INFOTRAFIC_RECENT_VALCEA_REFERENCE_ONLY",
    "ipj": "FIRST_PARTY_POLICE_ROAD_TRAFFIC_NEWS_INDEX_REFERENCE_ONLY",
    "eta": "FIRST_PARTY_TRANSIT_ROUTE_DIRECTORY_REFERENCE_ONLY",
}

ROAD_RE = re.compile(r"\b(?:DN|DJ|DC|DE|A)\s*[- ]?\s*(\d{1,4}[A-Z]?)\b", re.IGNORECASE)
LOCALITIES = {
    "babeni": "BABENI",
    "baile govora": "BAILE GOVORA",
    "baile olanesti": "BAILE OLANESTI",
    "balcesti": "BALCESTI",
    "berbesti": "BERBESTI",
    "brezoi": "BREZOI",
    "bujoreni": "BUJORENI",
    "calimanesti": "CALIMANESTI",
    "daesti": "DAESTI",
    "dragasani": "DRAGASANI",
    "francesti": "FRANCESTI",
    "galicea": "GALICEA",
    "golesti": "GOLESTI",
    "horezu": "HOREZU",
    "malaia": "MALAIA",
    "mihaesti": "MIHAESTI",
    "ocnele mari": "OCNELE MARI",
    "pausesti maglasi": "PAUSESTI MAGLASI",
    "ramnicu valcea": "RAMNICU VALCEA",
    "rm valcea": "RAMNICU VALCEA",
    "salatrucel": "SALATRUCEL",
    "voineasa": "VOINEASA",
    "vladesti": "VLADESTI",
}

DISABLED_CAPABILITIES = [
    "same_incident_inference",
    "active_incident_inference",
    "active_traffic_disruption_inference",
    "current_road_state_inference",
    "eta_service_impact_inference",
    "realtime_arrival_inference",
    "breaking_news_promotion",
    "fact_kernel_mutation",
    "writer",
    "persistence",
    "public_projection",
    "image_ingest",
    "inferred_photo_rights",
]


class CorrelationInputError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def explicit_tokens(title: str) -> dict[str, list[str]]:
    normalized = normalize_text(title)
    roads = {
        f"{match.group(0)[:2].upper()}{match.group(1).upper()}" if match.group(0).strip().upper().startswith(("DN", "DJ", "DC", "DE"))
        else f"A{match.group(1).upper()}"
        for match in ROAD_RE.finditer(title)
    }
    localities = {
        canonical
        for needle, canonical in LOCALITIES.items()
        if re.search(rf"(?:^|\s){re.escape(needle)}(?:\s|$)", normalized)
    }
    return {"roads": sorted(roads), "localities": sorted(localities)}


def _require_reference_payload(payload: dict[str, Any], family: str) -> list[dict[str, Any]]:
    if payload.get("state") != "CLEAR":
        raise CorrelationInputError(f"{family} source is not CLEAR")
    if payload.get("content_contract") != EXPECTED_CONTRACTS[family]:
        raise CorrelationInputError(f"unexpected {family} content contract")
    refs = payload.get("references")
    if not isinstance(refs, list):
        raise CorrelationInputError(f"{family} references must be a list")
    safe: list[dict[str, Any]] = []
    for ref in refs:
        if not isinstance(ref, dict):
            raise CorrelationInputError(f"{family} reference is not an object")
        title = ref.get("title")
        url = ref.get("url")
        if not isinstance(title, str) or not title.strip() or len(title) > 500:
            raise CorrelationInputError(f"{family} reference title is invalid")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise CorrelationInputError(f"{family} reference URL is invalid")
        for flag in (
            "current_state_authorized",
            "active_status_authorized",
            "active_incident_authorized",
            "active_traffic_disruption_authorized",
            "current_service_state_authorized",
            "realtime_authorized",
        ):
            if ref.get(flag) is True:
                raise CorrelationInputError(f"{family} reference unexpectedly authorizes {flag}")
        safe.append(ref)
    return safe


def _rank(shared_roads: set[str], shared_localities: set[str]) -> tuple[int, str]:
    score = 35 + min(25, 20 * len(shared_roads)) + min(30, 25 * len(shared_localities))
    score = min(score, 90)
    if score >= 80:
        tier = "HIGH_REFERENCE_RELEVANCE"
    elif score >= 60:
        tier = "MEDIUM_REFERENCE_RELEVANCE"
    else:
        tier = "LOW_REFERENCE_RELEVANCE"
    return score, tier


def _candidate_key(left_url: str, right_url: str, roads: list[str], localities: list[str]) -> str:
    canonical = json.dumps(
        {
            "urls": sorted((left_url, right_url)),
            "roads": roads,
            "localities": localities,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(canonical)[:24]


def build_result(
    infotrafic_payload: dict[str, Any],
    ipj_payload: dict[str, Any],
    eta_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        infotrafic_refs = _require_reference_payload(infotrafic_payload, "infotrafic")
        ipj_refs = _require_reference_payload(ipj_payload, "ipj")
        eta_refs = _require_reference_payload(eta_payload, "eta") if eta_payload is not None else []
    except CorrelationInputError as exc:
        return {
            "state": "HOLD",
            "reason": "traffic_reference_correlation_input_rejected",
            "error": str(exc),
            "content_contract": CONTENT_CONTRACT,
            "candidate_count": 0,
            "candidates": [],
            "disabled_capabilities": DISABLED_CAPABILITIES,
        }

    candidates: list[dict[str, Any]] = []
    for infotrafic, ipj in product(infotrafic_refs, ipj_refs):
        left_tokens = explicit_tokens(str(infotrafic["title"]))
        right_tokens = explicit_tokens(str(ipj["title"]))
        shared_roads = set(left_tokens["roads"]) & set(right_tokens["roads"])
        shared_localities = set(left_tokens["localities"]) & set(right_tokens["localities"])
        if not shared_roads and not shared_localities:
            continue
        roads = sorted(shared_roads)
        localities = sorted(shared_localities)
        score, tier = _rank(shared_roads, shared_localities)
        transit_context: list[dict[str, Any]] = []
        if localities:
            for route in eta_refs:
                route_tokens = explicit_tokens(f"{route.get('title', '')} {route.get('route_description', '')}")
                matched = sorted(set(localities) & set(route_tokens["localities"]))
                if not matched:
                    continue
                transit_context.append(
                    {
                        "route_code": route.get("route_code"),
                        "url": route["url"],
                        "matched_localities": matched,
                        "service_impact_authorized": False,
                        "realtime_authorized": False,
                    }
                )
        candidates.append(
            {
                "candidate_key": _candidate_key(str(infotrafic["url"]), str(ipj["url"]), roads, localities),
                "relationship": "SHARED_EXPLICIT_TRAFFIC_REFERENCE_CONTEXT",
                "rank_score": score,
                "rank_tier": tier,
                "matched_roads": roads,
                "matched_localities": localities,
                "references": [
                    {"source_family": "INFOTRAFIC", "url": infotrafic["url"], "signal_type": infotrafic.get("signal_type")},
                    {"source_family": "IPJ_VALCEA", "url": ipj["url"], "signal_type": ipj.get("signal_type")},
                ],
                "transit_context": sorted(transit_context, key=lambda item: (str(item.get("route_code")), str(item["url"]))),
                "same_incident_authorized": False,
                "current_state_authorized": False,
                "breaking_news_authorized": False,
            }
        )

    candidates.sort(key=lambda item: (-int(item["rank_score"]), str(item["candidate_key"])))
    evidence = json.dumps(candidates, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "state": "CLEAR",
        "reason": "deterministic_cross_source_reference_correlation",
        "content_contract": CONTENT_CONTRACT,
        "evidence_claim": (
            "Candidates are linked only by explicit shared road codes and/or explicit allowlisted locality names in safe reference metadata. "
            "A candidate is not evidence that the references describe the same incident, a current disruption, or an ETA Bus service impact."
        ),
        "source_reference_counts": {
            "infotrafic": len(infotrafic_refs),
            "ipj": len(ipj_refs),
            "eta": len(eta_refs),
        },
        "candidate_count": len(candidates),
        "candidates": candidates,
        "evidence_sha256": sha256_bytes(evidence),
        "disabled_capabilities": DISABLED_CAPABILITIES,
    }


def _sample_payload(contract: str, references: list[dict[str, Any]]) -> dict[str, Any]:
    return {"state": "CLEAR", "content_contract": contract, "references": references}


def run_self_test() -> None:
    assert explicit_tokens("Trafic pe DN 7 la Călimănești") == {"roads": ["DN7"], "localities": ["CALIMANESTI"]}
    assert explicit_tokens("Vâlcea trafic rutier") == {"roads": [], "localities": []}
    assert explicit_tokens("DN64 Drăgășani") == {"roads": ["DN64"], "localities": ["DRAGASANI"]}

    infotrafic = _sample_payload(
        EXPECTED_CONTRACTS["infotrafic"],
        [
            {
                "title": "JUDEȚUL VÂLCEA: TRAFIC OPRIT PE DN 7 LA CĂLIMĂNEȘTI",
                "url": "https://politiaromana.ro/ro/info-trafic/a",
                "signal_type": "TRAFFIC_STOPPAGE_REFERENCE",
                "current_state_authorized": False,
                "active_incident_authorized": False,
                "active_traffic_disruption_authorized": False,
            },
            {
                "title": "JUDEȚUL VÂLCEA: TRAFIC ÎNGREUNAT PE DN 64 LA VLĂDEȘTI",
                "url": "https://politiaromana.ro/ro/info-trafic/b",
                "signal_type": "TRAFFIC_RESTRICTION_REFERENCE",
                "current_state_authorized": False,
            },
        ],
    )
    ipj = _sample_payload(
        EXPECTED_CONTRACTS["ipj"],
        [
            {
                "title": "ACCIDENT RUTIER PE DN7 ÎN CĂLIMĂNEȘTI",
                "url": "https://vl.politiaromana.ro/ro/stiri-si-media/stiri/a",
                "signal_type": "ROAD_ACCIDENT_REFERENCE",
                "current_state_authorized": False,
            },
            {
                "title": "SIGURANȚĂ RUTIERĂ PE DN 64 LA VLĂDEȘTI",
                "url": "https://vl.politiaromana.ro/ro/stiri-si-media/stiri/b",
                "signal_type": "ROAD_SAFETY_OPERATION_REFERENCE",
                "current_state_authorized": False,
            },
            {
                "title": "ACȚIUNE RUTIERĂ ÎN JUDEȚUL VÂLCEA",
                "url": "https://vl.politiaromana.ro/ro/stiri-si-media/stiri/c",
                "signal_type": "ROAD_ENFORCEMENT_REFERENCE",
                "current_state_authorized": False,
            },
        ],
    )
    eta = _sample_payload(
        EXPECTED_CONTRACTS["eta"],
        [
            {
                "title": "3 Dispecerat Nord - Vlădești",
                "route_description": "Dispecerat Nord - Vlădești",
                "route_code": "3",
                "url": "https://eta-bus.ro/t/3",
                "current_service_state_authorized": False,
                "realtime_authorized": False,
            }
        ],
    )
    result = build_result(infotrafic, ipj, eta)
    assert result["state"] == "CLEAR", result
    assert result["candidate_count"] == 2, result
    top = result["candidates"][0]
    assert top["rank_score"] == 80, top
    assert top["same_incident_authorized"] is False
    assert top["current_state_authorized"] is False
    assert top["breaking_news_authorized"] is False
    vladesti = next(item for item in result["candidates"] if "VLADESTI" in item["matched_localities"])
    assert vladesti["transit_context"][0]["route_code"] == "3", vladesti
    assert vladesti["transit_context"][0]["service_impact_authorized"] is False

    county_only = build_result(
        _sample_payload(EXPECTED_CONTRACTS["infotrafic"], [{"title": "Vâlcea trafic", "url": "https://politiaromana.ro/ro/info-trafic/x"}]),
        _sample_payload(EXPECTED_CONTRACTS["ipj"], [{"title": "Vâlcea rutier", "url": "https://vl.politiaromana.ro/ro/stiri-si-media/stiri/x"}]),
    )
    assert county_only["state"] == "CLEAR"
    assert county_only["candidate_count"] == 0, county_only

    unsafe = _sample_payload(
        EXPECTED_CONTRACTS["ipj"],
        [{"title": "DN7 Călimănești", "url": "https://vl.politiaromana.ro/ro/stiri-si-media/stiri/u", "active_incident_authorized": True}],
    )
    hold = build_result(infotrafic, unsafe)
    assert hold["state"] == "HOLD", hold
    assert hold["candidate_count"] == 0
    print("self-test: ok")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--infotrafic-json")
    parser.add_argument("--ipj-json")
    parser.add_argument("--eta-json")
    args = parser.parse_args(argv)
    if args.self_test:
        run_self_test()
        return 0
    if not args.infotrafic_json or not args.ipj_json:
        parser.error("--infotrafic-json and --ipj-json are required unless --self-test is used")

    def load(path: str) -> dict[str, Any]:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise CorrelationInputError("input JSON root must be an object")
        return value

    try:
        infotrafic = load(args.infotrafic_json)
        ipj = load(args.ipj_json)
        eta = load(args.eta_json) if args.eta_json else None
        result = build_result(infotrafic, ipj, eta)
    except (CorrelationInputError, OSError, json.JSONDecodeError) as exc:
        result = {
            "state": "HOLD",
            "reason": "traffic_reference_correlation_input_failed",
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
