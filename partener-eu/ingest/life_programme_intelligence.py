#!/usr/bin/env python3
"""Bounded official LIFE programme, market and programming intelligence.

This layer is deliberately non-authorizing. It observes CINEA programme,
call-index, applicant-support and multiannual-work-programme surfaces without
turning visible call labels, dates, budgets or eligibility text into canonical
material facts. Exact call/topic evidence remains a separate gate.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

PARSER_VERSION = "LIFE_PROGRAMME_INTELLIGENCE_V1_1"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "partener-eu" / "ingest" / "life_programme_intelligence_registry.json"
MAX_BODY_BYTES = 2 * 1024 * 1024

MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "closed_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
    "call_alert_authorized",
    "canonical_corpus_mutation",
)
ALLOWED_OBSERVATION_STATES = {"PROGRAMME_INTELLIGENCE", "CALL_INDEX_DISCOVERY", "PROGRAMMING_PIPELINE"}
MISSING_FOR_OPEN_CONFIRMATION = [
    "exact_call_or_topic_identifier",
    "current_official_exact_call_or_topic_endpoint",
    "explicit_current_official_call_status",
    "call_specific_deadline_budget_eligibility_and_participation_rules",
    "semantic_reconciliation",
    "field_scoped_material_admission",
]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _fingerprint(value: Any) -> str:
    return _sha256(_canonical_json(value))


def _parse_observed_at(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    if not value.endswith("Z"):
        raise ValueError("observed_at must be RFC3339 UTC-Z")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _validate_https_url(url: str, *, hosts: list[str], path_prefixes: list[str]) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        raise ValueError(f"non-HTTPS official URL: {url}")
    if host not in {str(item).lower() for item in hosts}:
        raise ValueError(f"official host not allowlisted: {host}")
    path = parsed.path or "/"
    if path_prefixes and not any(path.startswith(prefix) for prefix in path_prefixes):
        raise ValueError(f"official path outside allowlist: {path}")


def load_registry(path: Path = DEFAULT_REGISTRY) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    if data.get("schema_version") != "1.0" or data.get("registry_id") != "LIFE_PROGRAMME_INTELLIGENCE_REGISTRY_V1":
        raise ValueError("unsupported LIFE registry schema/id")
    if data.get("source_family") != "EU_DIRECT" or data.get("programme_families") != ["LIFE"]:
        raise ValueError("LIFE source/programme family drift")
    checked = date.fromisoformat(str(data.get("evidence_checked_date") or ""))
    if checked > datetime.now(timezone.utc).date():
        raise ValueError("registry evidence_checked_date is in the future")

    policy = data.get("policy") or {}
    if policy.get("market_intelligence_only") is not True or policy.get("publication_effect") != "NONE":
        raise ValueError("LIFE market-intelligence policy drift")
    for key in MATERIAL_FLAGS:
        if policy.get(key) is not False:
            raise ValueError(f"LIFE registry became authorizing: {key}")
    for key in (
        "exact_call_or_topic_identifier_required",
        "current_official_exact_endpoint_required",
        "semantic_reconciliation_required",
        "field_scoped_material_admission_required",
    ):
        if policy.get(key) is not True:
            raise ValueError(f"LIFE material-admission requirement relaxed: {key}")

    sources = data.get("sources") or []
    if len(sources) != 4:
        raise ValueError("LIFE registry must contain exactly four bounded official sources")
    ids: set[str] = set()
    states: set[str] = set()
    for source in sources:
        source_id = str(source.get("id") or "")
        if not source_id or source_id in ids:
            raise ValueError("duplicate or empty LIFE source id")
        ids.add(source_id)
        if source.get("programme_family") != "LIFE":
            raise ValueError(f"unexpected LIFE programme family for {source_id}")
        state = str(source.get("observation_state") or "")
        if state not in ALLOWED_OBSERVATION_STATES:
            raise ValueError(f"authorizing/unsupported LIFE observation state: {state}")
        states.add(state)
        if source.get("material_fact_use") is not False or not source.get("authority_class"):
            raise ValueError(f"LIFE source policy/authority drift: {source_id}")
        _validate_https_url(
            str(source.get("authority_url") or ""),
            hosts=list(source.get("allowed_hosts") or []),
            path_prefixes=list(source.get("allowed_path_prefixes") or []),
        )
        groups = source.get("required_marker_groups") or []
        if not groups or any(not isinstance(group, list) or not group for group in groups):
            raise ValueError(f"required LIFE marker groups missing: {source_id}")
        if not source.get("market_signals") or not source.get("applicant_fit_tags"):
            raise ValueError(f"LIFE market/applicant intelligence missing: {source_id}")
    if "CALL_INDEX_DISCOVERY" not in states or "PROGRAMMING_PIPELINE" not in states:
        raise ValueError("LIFE registry lost call-index or programming separation")
    return data, _sha256(raw)


def _normalise_source_text(raw: bytes) -> str:
    decoded = html.unescape(raw.decode("utf-8", errors="ignore"))
    decoded = re.sub(r"<script\b[^>]*>.*?</script>", " ", decoded, flags=re.I | re.S)
    decoded = re.sub(r"<style\b[^>]*>.*?</style>", " ", decoded, flags=re.I | re.S)
    decoded = re.sub(r"<[^>]+>", " ", decoded)
    return re.sub(r"\s+", " ", decoded).strip().casefold()


def _probe_source(source: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    url = str(source["authority_url"])
    request = Request(
        url,
        headers={
            "User-Agent": "PARTENER.EU-LIFEProgrammeIntelligence/1.1 (+https://partener.eu)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.1",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_BODY_BYTES + 1)
            status = int(getattr(response, "status", 200))
            final_url = str(response.geturl())
            content_type = str(response.headers.get("Content-Type", ""))
        _validate_https_url(
            final_url,
            hosts=list(source.get("allowed_hosts") or []),
            path_prefixes=list(source.get("allowed_path_prefixes") or []),
        )
        raw_hash = _sha256(raw)
        if len(raw) > MAX_BODY_BYTES:
            return {
                "health_state": "DEGRADED_OVERSIZE", "lkg_required": True,
                "requested_url": url, "final_url": final_url, "http_status": status,
                "content_type": content_type, "raw_sha256": raw_hash,
                "normalized_visible_text_sha256": None, "raw_size_bytes": len(raw),
                "missing_marker_groups": [],
                "error": f"response exceeded bounded {MAX_BODY_BYTES}-byte acquisition cap",
            }
        folded_type = content_type.casefold()
        if not any(token in folded_type for token in ("text/html", "application/xhtml+xml", "text/plain")):
            return {
                "health_state": "DEGRADED_CONTENT_TYPE", "lkg_required": True,
                "requested_url": url, "final_url": final_url, "http_status": status,
                "content_type": content_type, "raw_sha256": raw_hash,
                "normalized_visible_text_sha256": None, "raw_size_bytes": len(raw),
                "missing_marker_groups": [], "error": "unexpected content type for LIFE programme intelligence source",
            }
        folded = _normalise_source_text(raw)
        visible_hash = _sha256(folded.encode("utf-8"))
        missing = [
            group for group in source.get("required_marker_groups") or []
            if not any(str(marker).casefold() in folded for marker in group)
        ]
        if status != 200 or missing:
            return {
                "health_state": "DEGRADED_MARKER_MISMATCH" if status == 200 else "DEGRADED_HTTP",
                "lkg_required": True, "requested_url": url, "final_url": final_url,
                "http_status": status, "content_type": content_type, "raw_sha256": raw_hash,
                "normalized_visible_text_sha256": visible_hash, "raw_size_bytes": len(raw),
                "missing_marker_groups": missing,
                "error": None if status == 200 else f"unexpected HTTP status {status}",
            }
        return {
            "health_state": "HEALTHY", "lkg_required": False,
            "requested_url": url, "final_url": final_url, "http_status": status,
            "content_type": content_type, "raw_sha256": raw_hash,
            "normalized_visible_text_sha256": visible_hash, "raw_size_bytes": len(raw),
            "missing_marker_groups": [], "error": None,
        }
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        return {
            "health_state": "DEGRADED_TRANSPORT", "lkg_required": True,
            "requested_url": url, "final_url": None,
            "http_status": getattr(exc, "code", None), "content_type": None,
            "raw_sha256": None, "normalized_visible_text_sha256": None,
            "raw_size_bytes": 0, "missing_marker_groups": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def _fit_score(*, fit_tags: list[str], market_signals: list[str], healthy: int, total: int) -> float:
    applicant_breadth = min(1.0, len(set(fit_tags)) / 8.0)
    market_breadth = min(1.0, len(set(market_signals)) / 10.0)
    health_ratio = healthy / total if total else 0.0
    return round(0.45 * applicant_breadth + 0.35 * market_breadth + 0.20 * health_ratio, 3)


def acquire(*, run_id: str, observed_at: str | None = None, registry_path: Path = DEFAULT_REGISTRY,
            live: bool = False, timeout: float = 12.0) -> dict[str, Any]:
    registry, registry_sha256 = load_registry(registry_path)
    now = _parse_observed_at(observed_at)
    fetched_at = now.isoformat().replace("+00:00", "Z")

    sources: list[dict[str, Any]] = []
    for source in registry["sources"]:
        health = _probe_source(source, timeout=timeout) if live else {
            "health_state": "NOT_PROBED", "lkg_required": False,
            "requested_url": source["authority_url"], "final_url": None,
            "http_status": None, "content_type": None, "raw_sha256": None,
            "normalized_visible_text_sha256": None, "raw_size_bytes": 0,
            "missing_marker_groups": [], "error": None,
        }
        semantic_basis = {
            "source_id": source["id"],
            "programme_family": source["programme_family"],
            "authority_class": source["authority_class"],
            "authority_url": source["authority_url"],
            "observation_state": source["observation_state"],
            "market_signals": sorted(set(source.get("market_signals") or [])),
            "applicant_fit_tags": sorted(set(source.get("applicant_fit_tags") or [])),
            "pipeline_signals": sorted(set(source.get("pipeline_signals") or [])),
            "normalized_visible_text_sha256": health.get("normalized_visible_text_sha256"),
        }
        degraded = str(health.get("health_state") or "").startswith("DEGRADED")
        sources.append({
            **{k: semantic_basis[k] for k in semantic_basis if k != "normalized_visible_text_sha256"},
            "normalized_visible_text_sha256": health.get("normalized_visible_text_sha256"),
            "source_semantic_fingerprint": None if degraded else _fingerprint(semantic_basis),
            "material_fact_use": False,
            "fetched_at": fetched_at,
            "freshness_basis": "LIVE_FETCH_AT_RUN" if live else "NOT_PROBED",
            "source_health": health,
        })

    healthy_count = sum(1 for row in sources if row["source_health"]["health_state"] == "HEALTHY")
    degraded_count = sum(1 for row in sources if str(row["source_health"]["health_state"]).startswith("DEGRADED"))
    source_health_state = "NOT_PROBED" if not live else ("HEALTHY" if degraded_count == 0 else "DEGRADED")
    fit_tags = sorted({tag for row in sources for tag in row["applicant_fit_tags"]})
    market_signals = sorted({signal for row in sources for signal in row["market_signals"]})
    pipeline_signals = sorted({signal for row in sources for signal in row["pipeline_signals"]})
    programme_intelligence = {
        "programme_family": "LIFE",
        "source_ids": [row["source_id"] for row in sources],
        "observation_states": sorted({row["observation_state"] for row in sources}),
        "market_signals": market_signals,
        "applicant_fit_tags": fit_tags,
        "pipeline_signals": pipeline_signals,
        "healthy_source_count": healthy_count,
        "degraded_source_count": degraded_count,
        "fit_score": _fit_score(fit_tags=fit_tags, market_signals=market_signals, healthy=healthy_count, total=len(sources)),
        "fit_score_is_not_eligibility": True,
        "market_intelligence_only": True,
    }
    semantic_basis = {
        "source_family": "EU_DIRECT",
        "programme_intelligence": programme_intelligence,
        "source_semantic_fingerprints": [row["source_semantic_fingerprint"] for row in sources],
    }
    flags = {key: False for key in MATERIAL_FLAGS}
    policy = registry["policy"]
    result = {
        "schema": "PARTENER_EU_LIFE_PROGRAMME_INTELLIGENCE_V1",
        "schema_version": "1.0",
        "adapter_id": PARSER_VERSION,
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
        "fetched_at": fetched_at,
        "registry_sha256": registry_sha256,
        "registry_evidence_checked_date": registry["evidence_checked_date"],
        "source_family": "EU_DIRECT",
        "programme_families": ["LIFE"],
        "programme_id": "LIFE",
        "programme_family": "LIFE",
        "authority_class": "OFFICIAL_PROGRAMME_CALL_INDEX_APPLICANT_SUPPORT_AND_WORK_PROGRAMME_INTELLIGENCE",
        "observation_state": "MARKET_AND_PROGRAMMING_INTELLIGENCE",
        "source_count": len(sources),
        "healthy_source_count": healthy_count,
        "degraded_source_count": degraded_count,
        "source_health_state": source_health_state,
        "lkg_required": bool(degraded_count),
        "sources": sources,
        "programme_intelligence": [programme_intelligence],
        "semantic_fingerprint": None if degraded_count else _fingerprint(semantic_basis),
        "market_intelligence_only": True,
        "fit_scores_are_not_eligibility": True,
        **flags,
        "publication_effect": "NONE",
        "exact_call_or_topic_identifier_required": bool(policy["exact_call_or_topic_identifier_required"]),
        "current_official_exact_endpoint_required": bool(policy["current_official_exact_endpoint_required"]),
        "semantic_reconciliation_required": bool(policy["semantic_reconciliation_required"]),
        "field_scoped_material_admission_required": bool(policy["field_scoped_material_admission_required"]),
        "missing_for_open_confirmation": list(MISSING_FOR_OPEN_CONFIRMATION),
        "note": (
            "LIFE programme, applicant-support, work-programme and call-index surfaces are market/programming/discovery intelligence only. "
            "Normalized visible-content hashes make healthy semantic snapshots content-sensitive; degraded current evidence has no semantic fingerprint. "
            "OPEN requires an exact call/topic identifier and fresh exact official endpoint, followed by semantic reconciliation and field-scoped admission."
        ),
        "rollback": "Revert LIFE V1.1 content-sensitive fingerprinting; preserve source-health, checkpoint, replay and LKG evidence.",
    }
    validate_result(result)
    return result


def validate_result(result: dict[str, Any]) -> None:
    if result.get("schema") != "PARTENER_EU_LIFE_PROGRAMME_INTELLIGENCE_V1":
        raise ValueError("LIFE programme intelligence schema drift")
    if result.get("adapter_id") != PARSER_VERSION or result.get("parser_version") != PARSER_VERSION:
        raise ValueError("LIFE adapter/parser version drift")
    if result.get("source_family") != "EU_DIRECT" or result.get("programme_families") != ["LIFE"]:
        raise ValueError("LIFE source/programme family drift")
    if result.get("programme_id") != "LIFE" or result.get("programme_family") != "LIFE":
        raise ValueError("LIFE programme identity drift")
    if result.get("source_count") != 4 or len(result.get("sources") or []) != 4:
        raise ValueError("LIFE source-count drift")
    if result.get("market_intelligence_only") is not True or result.get("fit_scores_are_not_eligibility") is not True:
        raise ValueError("LIFE market/fit boundary drift")
    if result.get("publication_effect") != "NONE":
        raise ValueError("LIFE publication effect drift")
    for key in MATERIAL_FLAGS:
        if result.get(key) is not False:
            raise ValueError(f"LIFE result became authorizing: {key}")
    for key in (
        "exact_call_or_topic_identifier_required", "current_official_exact_endpoint_required",
        "semantic_reconciliation_required", "field_scoped_material_admission_required",
    ):
        if result.get(key) is not True:
            raise ValueError(f"LIFE material-admission requirement relaxed: {key}")
    if not set(MISSING_FOR_OPEN_CONFIRMATION).issubset(set(result.get("missing_for_open_confirmation") or [])):
        raise ValueError("LIFE missing-for-open contract drift")
    if not re.fullmatch(r"[0-9a-f]{64}", str(result.get("registry_sha256") or "")):
        raise ValueError("LIFE registry SHA invalid")

    rows = result.get("programme_intelligence") or []
    if len(rows) != 1 or rows[0].get("programme_family") != "LIFE":
        raise ValueError("LIFE programme intelligence row missing")
    if rows[0].get("market_intelligence_only") is not True or rows[0].get("fit_score_is_not_eligibility") is not True:
        raise ValueError("LIFE programme fit boundary drift")
    if not 0 <= float(rows[0].get("fit_score", -1)) <= 1:
        raise ValueError("invalid LIFE fit score")

    states = set()
    for source in result.get("sources") or []:
        state = source.get("observation_state")
        states.add(state)
        if state not in ALLOWED_OBSERVATION_STATES or source.get("material_fact_use") is not False:
            raise ValueError("LIFE source observation/material boundary drift")
        health = source.get("source_health") or {}
        health_state = str(health.get("health_state") or "")
        if health_state == "HEALTHY":
            for key in ("raw_sha256", "normalized_visible_text_sha256"):
                if not re.fullmatch(r"[0-9a-f]{64}", str(health.get(key) or "")):
                    raise ValueError(f"healthy LIFE source provenance incomplete: {key}")
            if not re.fullmatch(r"[0-9a-f]{64}", str(source.get("normalized_visible_text_sha256") or "")):
                raise ValueError("healthy LIFE source visible-content hash missing")
            if not re.fullmatch(r"[0-9a-f]{64}", str(source.get("source_semantic_fingerprint") or "")):
                raise ValueError("healthy LIFE source semantic fingerprint invalid")
            if health.get("lkg_required") is not False:
                raise ValueError("healthy LIFE source incorrectly requires LKG")
        elif health_state.startswith("DEGRADED"):
            if health.get("lkg_required") is not True:
                raise ValueError("degraded LIFE source lacks LKG requirement")
            if source.get("source_semantic_fingerprint") is not None:
                raise ValueError("degraded LIFE source emitted semantic fingerprint")
        elif health_state == "NOT_PROBED":
            if not re.fullmatch(r"[0-9a-f]{64}", str(source.get("source_semantic_fingerprint") or "")):
                raise ValueError("unprobed LIFE source semantic fingerprint invalid")
        else:
            raise ValueError(f"unexpected LIFE source-health state: {health_state}")
    if "CALL_INDEX_DISCOVERY" not in states or "PROGRAMMING_PIPELINE" not in states:
        raise ValueError("LIFE source states lost discovery/pipeline separation")

    if result.get("source_health_state") == "DEGRADED":
        if result.get("semantic_fingerprint") is not None:
            raise ValueError("degraded LIFE snapshot emitted semantic fingerprint")
    elif not re.fullmatch(r"[0-9a-f]{64}", str(result.get("semantic_fingerprint") or "")):
        raise ValueError("healthy/unprobed LIFE semantic fingerprint invalid")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--observed-at")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = acquire(run_id=args.run_id, observed_at=args.observed_at, registry_path=args.registry, live=args.live, timeout=args.timeout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "schema": result["schema"], "source_count": result["source_count"],
        "healthy_source_count": result["healthy_source_count"], "degraded_source_count": result["degraded_source_count"],
        "semantic_fingerprint": result["semantic_fingerprint"], "open_call_authorized": result["open_call_authorized"],
        "publication_effect": result["publication_effect"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
