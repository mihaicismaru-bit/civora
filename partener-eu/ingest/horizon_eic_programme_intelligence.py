#!/usr/bin/env python3
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

PARSER_VERSION = "HORIZON_EIC_PROGRAMME_INTELLIGENCE_V1"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "partener-eu" / "ingest" / "horizon_eic_programme_intelligence_registry.json"

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
ALLOWED_OBSERVATION_STATES = {
    "PROGRAMME_INTELLIGENCE",
    "PROGRAMMING_PIPELINE",
    "CALL_INDEX_DISCOVERY",
}
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
    if data.get("schema_version") != "1.0":
        raise ValueError("unsupported Horizon/EIC programme registry schema")
    if data.get("registry_id") != "HORIZON_EIC_PROGRAMME_INTELLIGENCE_REGISTRY_V1":
        raise ValueError("unexpected Horizon/EIC programme registry id")
    if data.get("source_family") != "EU_DIRECT":
        raise ValueError("Horizon/EIC source family drift")
    if set(data.get("programme_families") or []) != {"Horizon Europe", "European Innovation Council"}:
        raise ValueError("Horizon/EIC programme family registry drift")
    checked = date.fromisoformat(str(data.get("evidence_checked_date") or ""))
    if checked > datetime.now(timezone.utc).date():
        raise ValueError("registry evidence_checked_date is in the future")

    policy = data.get("policy") or {}
    if policy.get("market_intelligence_only") is not True or policy.get("publication_effect") != "NONE":
        raise ValueError("Horizon/EIC market-intelligence policy drift")
    for key in MATERIAL_FLAGS:
        if policy.get(key) is not False:
            raise ValueError(f"Horizon/EIC registry became authorizing: {key}")
    for key in (
        "exact_call_or_topic_identifier_required",
        "current_official_exact_endpoint_required",
        "semantic_reconciliation_required",
        "field_scoped_material_admission_required",
    ):
        if policy.get(key) is not True:
            raise ValueError(f"Horizon/EIC material-admission requirement relaxed: {key}")

    sources = data.get("sources") or []
    if len(sources) != 4:
        raise ValueError("Horizon/EIC registry must contain exactly four bounded official sources")
    ids: set[str] = set()
    programme_counts = {"Horizon Europe": 0, "European Innovation Council": 0}
    for source in sources:
        source_id = str(source.get("id") or "")
        if not source_id or source_id in ids:
            raise ValueError("duplicate or empty Horizon/EIC source id")
        ids.add(source_id)
        programme = str(source.get("programme_family") or "")
        if programme not in programme_counts:
            raise ValueError(f"unexpected programme family for {source_id}: {programme}")
        programme_counts[programme] += 1
        state = str(source.get("observation_state") or "")
        if state not in ALLOWED_OBSERVATION_STATES:
            raise ValueError(f"authorizing or unsupported observation state for {source_id}: {state}")
        if source.get("material_fact_use") is not False:
            raise ValueError(f"source became material-authorizing: {source_id}")
        if not source.get("authority_class"):
            raise ValueError(f"authority class missing for {source_id}")
        _validate_https_url(
            str(source.get("authority_url") or ""),
            hosts=list(source.get("allowed_hosts") or []),
            path_prefixes=list(source.get("allowed_path_prefixes") or []),
        )
        groups = source.get("required_marker_groups") or []
        if not groups or any(not isinstance(group, list) or not group for group in groups):
            raise ValueError(f"required marker groups missing for {source_id}")
        if not source.get("market_signals") or not source.get("applicant_fit_tags"):
            raise ValueError(f"market/applicant intelligence missing for {source_id}")
    if set(programme_counts.values()) != {2}:
        raise ValueError("expected two bounded sources per Horizon/EIC programme family")
    return data, _sha256(raw)


def _normalise_source_text(raw: bytes) -> str:
    decoded = html.unescape(raw.decode("utf-8", errors="ignore"))
    decoded = re.sub(r"<[^>]+>", " ", decoded)
    return re.sub(r"\s+", " ", decoded).casefold()


def _probe_source(source: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    url = str(source["authority_url"])
    request = Request(
        url,
        headers={
            "User-Agent": "PARTENER.EU-HorizonEICProgrammeIntelligence/1.0 (+https://partener.eu)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.1",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = int(getattr(response, "status", 200))
            final_url = str(response.geturl())
            content_type = str(response.headers.get("Content-Type", ""))
        _validate_https_url(
            final_url,
            hosts=list(source.get("allowed_hosts") or []),
            path_prefixes=list(source.get("allowed_path_prefixes") or []),
        )
        folded = _normalise_source_text(raw)
        missing: list[list[str]] = []
        for group in source.get("required_marker_groups") or []:
            if not any(str(marker).casefold() in folded for marker in group):
                missing.append(group)
        if status != 200 or missing:
            return {
                "health_state": "DEGRADED_MARKER_MISMATCH" if status == 200 else "DEGRADED_HTTP",
                "lkg_required": True,
                "requested_url": url,
                "final_url": final_url,
                "http_status": status,
                "content_type": content_type,
                "raw_sha256": _sha256(raw),
                "raw_size_bytes": len(raw),
                "missing_marker_groups": missing,
                "error": None if status == 200 else f"unexpected HTTP status {status}",
            }
        return {
            "health_state": "HEALTHY",
            "lkg_required": False,
            "requested_url": url,
            "final_url": final_url,
            "http_status": status,
            "content_type": content_type,
            "raw_sha256": _sha256(raw),
            "raw_size_bytes": len(raw),
            "missing_marker_groups": [],
            "error": None,
        }
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        return {
            "health_state": "DEGRADED_TRANSPORT",
            "lkg_required": True,
            "requested_url": url,
            "final_url": None,
            "http_status": getattr(exc, "code", None),
            "content_type": None,
            "raw_sha256": None,
            "raw_size_bytes": 0,
            "missing_marker_groups": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def _fit_score(*, fit_tags: list[str], market_signals: list[str], healthy: int, total: int) -> float:
    applicant_breadth = min(1.0, len(set(fit_tags)) / 8.0)
    instrument_breadth = min(1.0, len(set(market_signals)) / 8.0)
    health_ratio = healthy / total if total else 0.0
    return round(0.45 * applicant_breadth + 0.35 * instrument_breadth + 0.20 * health_ratio, 3)


def acquire(
    *,
    run_id: str,
    observed_at: str | None = None,
    registry_path: Path = DEFAULT_REGISTRY,
    live: bool = False,
    timeout: float = 12.0,
) -> dict[str, Any]:
    registry, registry_sha256 = load_registry(registry_path)
    now = _parse_observed_at(observed_at)
    fetched_at = now.isoformat().replace("+00:00", "Z")

    sources: list[dict[str, Any]] = []
    for source in registry["sources"]:
        health = _probe_source(source, timeout=timeout) if live else {
            "health_state": "NOT_PROBED",
            "lkg_required": False,
            "requested_url": source["authority_url"],
            "final_url": None,
            "http_status": None,
            "content_type": None,
            "raw_sha256": None,
            "raw_size_bytes": 0,
            "missing_marker_groups": [],
            "error": None,
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
        }
        sources.append({
            **semantic_basis,
            "source_semantic_fingerprint": _fingerprint(semantic_basis),
            "material_fact_use": False,
            "fetched_at": fetched_at,
            "source_health": health,
        })

    healthy_count = sum(1 for row in sources if row["source_health"]["health_state"] == "HEALTHY")
    degraded_count = sum(1 for row in sources if str(row["source_health"]["health_state"]).startswith("DEGRADED"))
    source_health_state = "NOT_PROBED" if not live else ("HEALTHY" if degraded_count == 0 else "DEGRADED")

    programme_intelligence: list[dict[str, Any]] = []
    for programme in registry["programme_families"]:
        rows = [row for row in sources if row["programme_family"] == programme]
        fit_tags = sorted({tag for row in rows for tag in row["applicant_fit_tags"]})
        market_signals = sorted({signal for row in rows for signal in row["market_signals"]})
        pipeline_signals = sorted({signal for row in rows for signal in row["pipeline_signals"]})
        healthy = sum(1 for row in rows if row["source_health"]["health_state"] == "HEALTHY")
        degraded = sum(1 for row in rows if str(row["source_health"]["health_state"]).startswith("DEGRADED"))
        observation_states = sorted({row["observation_state"] for row in rows})
        programme_intelligence.append({
            "programme_family": programme,
            "source_ids": [row["source_id"] for row in rows],
            "observation_states": observation_states,
            "market_signals": market_signals,
            "applicant_fit_tags": fit_tags,
            "pipeline_signals": pipeline_signals,
            "healthy_source_count": healthy,
            "degraded_source_count": degraded,
            "fit_score": _fit_score(
                fit_tags=fit_tags,
                market_signals=market_signals,
                healthy=healthy,
                total=len(rows),
            ),
            "fit_score_is_not_eligibility": True,
            "market_intelligence_only": True,
        })

    semantic_basis = {
        "source_family": "EU_DIRECT",
        "programme_intelligence": programme_intelligence,
        "source_semantic_fingerprints": [row["source_semantic_fingerprint"] for row in sources],
    }
    flags = {key: False for key in MATERIAL_FLAGS}
    policy = registry["policy"]
    return {
        "schema": "PARTENER_EU_HORIZON_EIC_PROGRAMME_INTELLIGENCE_V1",
        "schema_version": "1.0",
        "adapter_id": PARSER_VERSION,
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
        "fetched_at": fetched_at,
        "registry_sha256": registry_sha256,
        "registry_evidence_checked_date": registry["evidence_checked_date"],
        "source_family": "EU_DIRECT",
        "programme_families": list(registry["programme_families"]),
        "authority_class": "OFFICIAL_PROGRAMME_AND_PROGRAMMING_INTELLIGENCE",
        "observation_state": "MARKET_AND_PROGRAMMING_INTELLIGENCE",
        "source_count": len(sources),
        "healthy_source_count": healthy_count,
        "degraded_source_count": degraded_count,
        "source_health_state": source_health_state,
        "lkg_required": bool(degraded_count),
        "sources": sources,
        "programme_intelligence": programme_intelligence,
        "semantic_fingerprint": _fingerprint(semantic_basis),
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
            "Horizon Europe and EIC gateways, work programmes and opportunity indexes are market/programming "
            "intelligence only. Labels, calendars, budgets, applicant-fit scores and programme signals cannot "
            "authorize OPEN, deadlines, budgets or eligibility without an exact current official call/topic "
            "identity, fresh exact authority, semantic reconciliation and field-scoped material admission."
        ),
        "rollback": "Discard this programme-intelligence receipt; no canonical call state is mutated.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Acquire official Horizon Europe/EIC market and programming intelligence without authorizing call facts.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--observed-at")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = acquire(
        run_id=args.run_id,
        observed_at=args.observed_at,
        registry_path=args.registry,
        live=args.live,
        timeout=args.timeout,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
