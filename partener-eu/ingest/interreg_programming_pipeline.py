#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

PARSER_VERSION = "INTERREG_PROGRAMMING_PIPELINE_V1"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "partener-eu" / "ingest" / "interreg_programming_pipeline_registry.json"

ALLOWED_OBSERVATION_STATES = {"PROPOSAL", "CONSULTATION", "PROGRAMMING_PROCESS"}
MISSING_FOR_CALL_CONFIRMATION = [
    "exact_call_or_topic_identifier",
    "current_official_exact_call_endpoint",
    "explicit_current_official_call_status",
    "call_specific_deadline_budget_eligibility_and_geography",
    "semantic_reconciliation",
]
MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _parse_date(value: str | None) -> date | None:
    if value in (None, ""):
        return None
    return date.fromisoformat(str(value))


def _parse_observed_at(value: str | None) -> datetime:
    if value:
        if not value.endswith("Z"):
            raise ValueError("observed_at must be RFC3339 UTC-Z")
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        if parsed.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        return parsed.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _validate_url(url: str, allowed_hosts: list[str], path_prefixes: list[str]) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        raise ValueError(f"non-HTTPS authority URL: {url}")
    if host not in {item.lower() for item in allowed_hosts}:
        raise ValueError(f"authority host not allowlisted: {host}")
    if path_prefixes and not any((parsed.path or "/").startswith(prefix) for prefix in path_prefixes):
        raise ValueError(f"authority path outside allowlist: {parsed.path}")


def load_registry(path: Path = DEFAULT_REGISTRY) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    if data.get("schema_version") != "1.0":
        raise ValueError("unsupported programming-pipeline registry schema")
    if data.get("registry_id") != "INTERREG_PROGRAMMING_PIPELINE_REGISTRY_V1":
        raise ValueError("unexpected programming-pipeline registry id")
    if data.get("programme_period") != "2028-2034":
        raise ValueError("unexpected programming period")
    checked = _parse_date(data.get("evidence_checked_date"))
    if checked is None:
        raise ValueError("evidence_checked_date is required")

    policy = data.get("policy") or {}
    for key in MATERIAL_FLAGS:
        if policy.get(key) is not False:
            raise ValueError(f"registry policy became authorizing: {key}")
    if policy.get("market_intelligence_only") is not True or policy.get("publication_effect") != "NONE":
        raise ValueError("registry programming policy drift")

    sources = data.get("sources") or []
    if not sources:
        raise ValueError("programming-pipeline registry is empty")
    ids = [row.get("id") for row in sources]
    if len(ids) != len(set(ids)) or any(not item for item in ids):
        raise ValueError("duplicate or empty programming source id")

    for row in sources:
        state = row.get("observation_state")
        if state not in ALLOWED_OBSERVATION_STATES:
            raise ValueError(f"forbidden programming observation state: {state}")
        if "OPEN" in str(state).upper() or "CALL" in str(state).upper():
            raise ValueError(f"programming observation cannot encode call state: {state}")
        if not row.get("programme_ids") or not row.get("programme_family"):
            raise ValueError(f"programme mapping incomplete: {row.get('id')}")
        if not row.get("authority_class") or not row.get("signal_basis"):
            raise ValueError(f"authority metadata incomplete: {row.get('id')}")
        _validate_url(
            str(row.get("authority_url") or ""),
            list(row.get("allowed_hosts") or []),
            list(row.get("allowed_path_prefixes") or []),
        )
        start = _parse_date(row.get("consultation_start_date"))
        end = _parse_date(row.get("consultation_end_date"))
        published = _parse_date(row.get("source_published_date"))
        if start and end and end < start:
            raise ValueError(f"consultation end before start: {row.get('id')}")
        if row.get("observation_state") == "CONSULTATION" and not (start or end or published):
            raise ValueError(f"consultation lacks dated evidence: {row.get('id')}")
        groups = row.get("required_markers") or []
        if not groups or any(not isinstance(group, list) or not group for group in groups):
            raise ValueError(f"required marker groups missing: {row.get('id')}")
        supporting = row.get("supporting_authority_url")
        if supporting:
            parsed = urlparse(supporting)
            if parsed.scheme != "https":
                raise ValueError(f"supporting authority URL must be HTTPS: {row.get('id')}")
    return data, _sha256(raw)


def _freshness(signal_date: date | None, observed_date: date) -> tuple[str, int | None]:
    if signal_date is None:
        return "DATED_SIGNAL_NOT_AVAILABLE", None
    age = (observed_date - signal_date).days
    if age < 0:
        return "FUTURE_SIGNAL_DATE_INVALID", age
    if age <= 60:
        return "CURRENT_60D", age
    if age <= 180:
        return "RECENT_180D", age
    return "OFFICIAL_BASELINE_OLDER_180D", age


def _consultation_lifecycle(row: dict[str, Any], observed_date: date) -> str:
    if row["observation_state"] != "CONSULTATION":
        return "NOT_A_CONSULTATION"
    start = _parse_date(row.get("consultation_start_date"))
    end = _parse_date(row.get("consultation_end_date"))
    if start and observed_date < start:
        return "BEFORE_WINDOW"
    if end and observed_date > end:
        return "AFTER_WINDOW"
    if start and end:
        return "IN_WINDOW"
    if end and observed_date <= end:
        return "END_KNOWN_START_NOT_STATED"
    if start and not end and observed_date >= start:
        return "WINDOW_END_NOT_STATED"
    return "WINDOW_BOUNDS_NOT_STATED"


def _watch_priority(state: str, lifecycle: str, freshness: str) -> int:
    if state == "CONSULTATION":
        base = {
            "IN_WINDOW": 100,
            "WINDOW_END_NOT_STATED": 90,
            "END_KNOWN_START_NOT_STATED": 85,
            "BEFORE_WINDOW": 80,
            "WINDOW_BOUNDS_NOT_STATED": 75,
            "AFTER_WINDOW": 60,
        }.get(lifecycle, 60)
    elif state == "PROGRAMMING_PROCESS":
        base = 70
    else:
        base = 50
    if freshness == "OFFICIAL_BASELINE_OLDER_180D":
        base -= 10
    if freshness == "FUTURE_SIGNAL_DATE_INVALID":
        return 0
    return max(base, 0)


def _probe(row: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    requested_url = row["authority_url"]
    request = Request(
        requested_url,
        headers={
            "User-Agent": "PARTENER.EU-InterregProgrammingWatch/1.0 (+https://partener.eu)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.1",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            final_url = response.geturl()
            status = int(getattr(response, "status", 200))
            content_type = str(response.headers.get("Content-Type", ""))
        _validate_url(
            final_url,
            list(row.get("allowed_hosts") or []),
            list(row.get("allowed_path_prefixes") or []),
        )
        text = raw.decode("utf-8", errors="ignore")
        folded = re.sub(r"\s+", " ", text).casefold()
        missing_groups: list[list[str]] = []
        for group in row.get("required_markers") or []:
            if not any(str(marker).casefold() in folded for marker in group):
                missing_groups.append(group)
        if status != 200:
            raise ValueError(f"unexpected HTTP status {status}")
        if missing_groups:
            return {
                "health_state": "DEGRADED_MARKER_MISMATCH",
                "lkg_required": True,
                "requested_url": requested_url,
                "final_url": final_url,
                "http_status": status,
                "content_type": content_type,
                "raw_sha256": _sha256(raw),
                "raw_size_bytes": len(raw),
                "missing_marker_groups": missing_groups,
                "error": None,
            }
        return {
            "health_state": "HEALTHY",
            "lkg_required": False,
            "requested_url": requested_url,
            "final_url": final_url,
            "http_status": status,
            "content_type": content_type,
            "raw_sha256": _sha256(raw),
            "raw_size_bytes": len(raw),
            "missing_marker_groups": [],
            "error": None,
        }
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        return {
            "health_state": "DEGRADED",
            "lkg_required": True,
            "requested_url": requested_url,
            "final_url": None,
            "http_status": getattr(exc, "code", None),
            "content_type": None,
            "raw_sha256": None,
            "raw_size_bytes": 0,
            "missing_marker_groups": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def resolve(
    *,
    run_id: str,
    registry_path: Path = DEFAULT_REGISTRY,
    observed_at: str | None = None,
    live: bool = False,
    timeout: float = 10.0,
) -> dict[str, Any]:
    registry, registry_sha256 = load_registry(registry_path)
    now = _parse_observed_at(observed_at)
    observed_date = now.date()
    checked_date = _parse_date(registry["evidence_checked_date"])
    assert checked_date is not None
    checked_age = (observed_date - checked_date).days
    if checked_age < 0:
        raise ValueError("registry evidence_checked_date is in the future")
    registry_freshness_state = "CURRENT_CHECK_30D" if checked_age <= 30 else "STALE_CHECK_GT_30D"

    rows: list[dict[str, Any]] = []
    for source in registry["sources"]:
        signal_date = (
            _parse_date(source.get("source_published_date"))
            or _parse_date(source.get("consultation_start_date"))
            or _parse_date(source.get("consultation_end_date"))
        )
        freshness_state, source_age_days = _freshness(signal_date, observed_date)
        if freshness_state == "FUTURE_SIGNAL_DATE_INVALID":
            raise ValueError(f"future signal date for {source['id']}")
        lifecycle = _consultation_lifecycle(source, observed_date)
        probe = _probe(source, timeout=timeout) if live else {
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
        row = {
            "source_id": source["id"],
            "programme_ids": list(source["programme_ids"]),
            "programme": source["programme"],
            "programme_family": source["programme_family"],
            "source_family": "INTERREG",
            "programme_period": registry["programme_period"],
            "authority_class": source["authority_class"],
            "authority_url": source["authority_url"],
            "supporting_authority_url": source.get("supporting_authority_url"),
            "observation_state": source["observation_state"],
            "signal_basis": source["signal_basis"],
            "source_published_date": source.get("source_published_date"),
            "consultation_start_date": source.get("consultation_start_date"),
            "consultation_end_date": source.get("consultation_end_date"),
            "consultation_lifecycle": lifecycle,
            "freshness_state": freshness_state,
            "source_age_days": source_age_days,
            "watch_priority": _watch_priority(source["observation_state"], lifecycle, freshness_state),
            "source_health": probe,
            "market_intelligence_only": True,
            "material_fact_use": False,
            "open_call_authorized": False,
            "deadline_authorized": False,
            "budget_authorized": False,
            "eligibility_authorized": False,
            "publish_authorized": False,
            "distribution_authorized": False,
            "publication_effect": "NONE",
            "missing_for_open_confirmation": list(MISSING_FOR_CALL_CONFIRMATION),
        }
        rows.append(row)

    rows.sort(key=lambda row: (-row["watch_priority"], row["source_id"]))
    healthy = sum(1 for row in rows if row["source_health"]["health_state"] == "HEALTHY")
    degraded = sum(1 for row in rows if str(row["source_health"]["health_state"]).startswith("DEGRADED"))
    aggregate_health = "NOT_PROBED" if not live else ("HEALTHY" if degraded == 0 else "DEGRADED")
    return {
        "schema_version": "1.0",
        "adapter_id": PARSER_VERSION,
        "run_id": run_id,
        "fetched_at": now.isoformat().replace("+00:00", "Z"),
        "registry_sha256": registry_sha256,
        "registry_evidence_checked_date": registry["evidence_checked_date"],
        "registry_check_age_days": checked_age,
        "registry_freshness_state": registry_freshness_state,
        "source_family": "INTERREG",
        "programme_period": registry["programme_period"],
        "observation_state": "PROGRAMMING_PIPELINE",
        "source_count": len(rows),
        "healthy_source_count": healthy,
        "degraded_source_count": degraded,
        "health_state": aggregate_health,
        "watchlist": rows,
        "market_intelligence_only": True,
        "material_fact_use": False,
        "open_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "publication_effect": "NONE",
        "missing_for_open_confirmation": list(MISSING_FOR_CALL_CONFIRMATION),
        "note": "PROGRAMMING/PROPOSAL/CONSULTATION evidence is a watch signal only and cannot become OPEN_CALL or authorize any material call fact.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a fail-closed Interreg 2028-2034 programming watch from bounded official sources."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--observed-at")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = resolve(
        run_id=args.run_id,
        registry_path=args.registry,
        observed_at=args.observed_at,
        live=args.live,
        timeout=args.timeout,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
