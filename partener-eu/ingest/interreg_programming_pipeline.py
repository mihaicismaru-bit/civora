#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

PARSER_VERSION = "INTERREG_PROGRAMMING_PIPELINE_V1"
RECONCILIATION_VERSION = "INTERREG_PROGRAMMING_RECONCILIATION_V1"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "partener-eu" / "ingest" / "interreg_programming_pipeline_registry.json"

ALLOWED_OBSERVATION_STATES = {"PROPOSAL", "CONSULTATION", "PROGRAMMING_PROCESS"}
TRANSIENT_HTTP_STATUSES = frozenset({202, 408, 425, 429, 500, 502, 503, 504})
_CERTIFICATE_ERROR_MARKERS = (
    "certificate verify failed",
    "certificate_verify_failed",
    "ssl: certificate",
)
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


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _fingerprint(value: Any) -> str:
    return _sha256(_canonical_json(value))


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in text)


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


def _certificate_failure(exc: BaseException) -> bool:
    text = str(exc).casefold()
    return any(marker in text for marker in _CERTIFICATE_ERROR_MARKERS)


def _degraded_probe(
    *,
    requested_url: str,
    health_state: str,
    attempt_count: int,
    max_attempts: int,
    retryable_failure_count: int,
    retry_exhausted: bool,
    attempt_history: list[dict[str, Any]],
    error: str | None,
    final_url: str | None = None,
    http_status: int | None = None,
    content_type: str | None = None,
    raw: bytes | None = None,
    missing_marker_groups: list[list[str]] | None = None,
) -> dict[str, Any]:
    return {
        "health_state": health_state,
        "lkg_required": True,
        "requested_url": requested_url,
        "final_url": final_url,
        "http_status": http_status,
        "content_type": content_type,
        "raw_sha256": _sha256(raw) if raw is not None else None,
        "raw_size_bytes": len(raw) if raw is not None else 0,
        "missing_marker_groups": missing_marker_groups or [],
        "attempt_count": attempt_count,
        "max_attempts": max_attempts,
        "retryable_failure_count": retryable_failure_count,
        "retry_exhausted": retry_exhausted,
        "attempt_history": attempt_history,
        "error": error,
    }


def _probe(
    row: dict[str, Any],
    *,
    timeout: float,
    max_attempts: int = 3,
    retry_backoff_seconds: float = 0.25,
) -> dict[str, Any]:
    requested_url = row["authority_url"]
    request = Request(
        requested_url,
        headers={
            "User-Agent": "PARTENER.EU-InterregProgrammingWatch/1.0 (+https://partener.eu)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.1",
        },
        method="GET",
    )
    attempt_history: list[dict[str, Any]] = []
    retryable_failure_count = 0

    for attempt in range(1, max_attempts + 1):
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

            if status in TRANSIENT_HTTP_STATUSES:
                retryable_failure_count += 1
                attempt_history.append({
                    "attempt": attempt,
                    "kind": "TRANSIENT_HTTP_STATUS",
                    "http_status": status,
                })
                if attempt < max_attempts:
                    if retry_backoff_seconds:
                        time.sleep(retry_backoff_seconds * (2 ** (attempt - 1)))
                    continue
                return _degraded_probe(
                    requested_url=requested_url,
                    health_state="DEGRADED_TRANSIENT_EXHAUSTED",
                    attempt_count=attempt,
                    max_attempts=max_attempts,
                    retryable_failure_count=retryable_failure_count,
                    retry_exhausted=True,
                    attempt_history=attempt_history,
                    error=f"transient HTTP status {status} after {attempt} attempts",
                    final_url=final_url,
                    http_status=status,
                    content_type=content_type,
                    raw=raw,
                )

            if status != 200:
                attempt_history.append({
                    "attempt": attempt,
                    "kind": "NON_RETRYABLE_HTTP_STATUS",
                    "http_status": status,
                })
                return _degraded_probe(
                    requested_url=requested_url,
                    health_state="DEGRADED",
                    attempt_count=attempt,
                    max_attempts=max_attempts,
                    retryable_failure_count=retryable_failure_count,
                    retry_exhausted=False,
                    attempt_history=attempt_history,
                    error=f"unexpected HTTP status {status}",
                    final_url=final_url,
                    http_status=status,
                    content_type=content_type,
                    raw=raw,
                )

            text = raw.decode("utf-8", errors="ignore")
            folded = re.sub(r"\s+", " ", text).casefold()
            missing_groups: list[list[str]] = []
            for group in row.get("required_markers") or []:
                if not any(str(marker).casefold() in folded for marker in group):
                    missing_groups.append(group)
            if missing_groups:
                return _degraded_probe(
                    requested_url=requested_url,
                    health_state="DEGRADED_MARKER_MISMATCH",
                    attempt_count=attempt,
                    max_attempts=max_attempts,
                    retryable_failure_count=retryable_failure_count,
                    retry_exhausted=False,
                    attempt_history=attempt_history,
                    error=None,
                    final_url=final_url,
                    http_status=status,
                    content_type=content_type,
                    raw=raw,
                    missing_marker_groups=missing_groups,
                )
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
                "attempt_count": attempt,
                "max_attempts": max_attempts,
                "retryable_failure_count": retryable_failure_count,
                "retry_exhausted": False,
                "attempt_history": attempt_history,
                "error": None,
            }
        except HTTPError as exc:
            status = int(exc.code)
            retryable = status in TRANSIENT_HTTP_STATUSES
            attempt_history.append({
                "attempt": attempt,
                "kind": "HTTP_ERROR",
                "http_status": status,
                "retryable": retryable,
            })
            if retryable:
                retryable_failure_count += 1
            if retryable and attempt < max_attempts:
                if retry_backoff_seconds:
                    time.sleep(retry_backoff_seconds * (2 ** (attempt - 1)))
                continue
            return _degraded_probe(
                requested_url=requested_url,
                health_state="DEGRADED_TRANSIENT_EXHAUSTED" if retryable else "DEGRADED",
                attempt_count=attempt,
                max_attempts=max_attempts,
                retryable_failure_count=retryable_failure_count,
                retry_exhausted=retryable and attempt >= max_attempts,
                attempt_history=attempt_history,
                error=f"{type(exc).__name__}: {exc}",
                http_status=status,
            )
        except (URLError, TimeoutError, OSError) as exc:
            retryable = not _certificate_failure(exc)
            attempt_history.append({
                "attempt": attempt,
                "kind": type(exc).__name__,
                "http_status": getattr(exc, "code", None),
                "retryable": retryable,
            })
            if retryable:
                retryable_failure_count += 1
            if retryable and attempt < max_attempts:
                if retry_backoff_seconds:
                    time.sleep(retry_backoff_seconds * (2 ** (attempt - 1)))
                continue
            return _degraded_probe(
                requested_url=requested_url,
                health_state="DEGRADED_TRANSIENT_EXHAUSTED" if retryable else "DEGRADED",
                attempt_count=attempt,
                max_attempts=max_attempts,
                retryable_failure_count=retryable_failure_count,
                retry_exhausted=retryable and attempt >= max_attempts,
                attempt_history=attempt_history,
                error=f"{type(exc).__name__}: {exc}",
                http_status=getattr(exc, "code", None),
            )
        except ValueError as exc:
            attempt_history.append({
                "attempt": attempt,
                "kind": "POLICY_OR_VALIDATION_ERROR",
                "http_status": None,
                "retryable": False,
            })
            return _degraded_probe(
                requested_url=requested_url,
                health_state="DEGRADED",
                attempt_count=attempt,
                max_attempts=max_attempts,
                retryable_failure_count=retryable_failure_count,
                retry_exhausted=False,
                attempt_history=attempt_history,
                error=f"{type(exc).__name__}: {exc}",
            )

    raise AssertionError("bounded probe loop exited unexpectedly")


def _row_semantic_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": row.get("source_id"),
        "programme_ids": list(row.get("programme_ids") or []),
        "programme": row.get("programme"),
        "programme_family": row.get("programme_family"),
        "source_family": row.get("source_family"),
        "programme_period": row.get("programme_period"),
        "authority_class": row.get("authority_class"),
        "authority_url": row.get("authority_url"),
        "supporting_authority_url": row.get("supporting_authority_url"),
        "observation_state": row.get("observation_state"),
        "signal_basis": row.get("signal_basis"),
        "source_published_date": row.get("source_published_date"),
        "consultation_start_date": row.get("consultation_start_date"),
        "consultation_end_date": row.get("consultation_end_date"),
        "consultation_lifecycle": row.get("consultation_lifecycle"),
    }


def _row_transport_payload(row: dict[str, Any]) -> dict[str, Any]:
    health = row.get("source_health") or {}
    return {
        "health_state": health.get("health_state"),
        "lkg_required": health.get("lkg_required"),
        "requested_url": health.get("requested_url"),
        "final_url": health.get("final_url"),
        "http_status": health.get("http_status"),
        "content_type": health.get("content_type"),
        "raw_sha256": health.get("raw_sha256"),
        "missing_marker_groups": health.get("missing_marker_groups") or [],
    }


def _attach_row_fingerprints(row: dict[str, Any]) -> None:
    row["semantic_fingerprint"] = _fingerprint(_row_semantic_payload(row))
    row["transport_fingerprint"] = _fingerprint(_row_transport_payload(row))


def _aggregate_fingerprint(rows: list[dict[str, Any]], field: str) -> str:
    return _fingerprint(
        [[row["source_id"], row[field]] for row in sorted(rows, key=lambda item: item["source_id"])]
    )


def resolve(
    *,
    run_id: str,
    registry_path: Path = DEFAULT_REGISTRY,
    observed_at: str | None = None,
    live: bool = False,
    timeout: float = 10.0,
    max_attempts: int = 3,
    retry_backoff_seconds: float = 0.25,
) -> dict[str, Any]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    if retry_backoff_seconds < 0:
        raise ValueError("retry_backoff_seconds must be >= 0")
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
        probe = _probe(
            source,
            timeout=timeout,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
        ) if live else {
            "health_state": "NOT_PROBED",
            "lkg_required": False,
            "requested_url": source["authority_url"],
            "final_url": None,
            "http_status": None,
            "content_type": None,
            "raw_sha256": None,
            "raw_size_bytes": 0,
            "missing_marker_groups": [],
            "attempt_count": 0,
            "max_attempts": max_attempts,
            "retryable_failure_count": 0,
            "retry_exhausted": False,
            "attempt_history": [],
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
        _attach_row_fingerprints(row)
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
        "snapshot_semantic_fingerprint": _aggregate_fingerprint(rows, "semantic_fingerprint"),
        "snapshot_transport_fingerprint": _aggregate_fingerprint(rows, "transport_fingerprint"),
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


def _validate_snapshot(snapshot: dict[str, Any], *, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(snapshot, dict):
        raise ValueError(f"{label}: snapshot must be an object")
    if snapshot.get("adapter_id") != PARSER_VERSION:
        raise ValueError(f"{label}: unexpected adapter id")
    if snapshot.get("source_family") != "INTERREG" or snapshot.get("programme_period") != "2028-2034":
        raise ValueError(f"{label}: source/programme boundary drift")
    if snapshot.get("observation_state") != "PROGRAMMING_PIPELINE":
        raise ValueError(f"{label}: observation state drift")
    if snapshot.get("market_intelligence_only") is not True or snapshot.get("publication_effect") != "NONE":
        raise ValueError(f"{label}: programming policy drift")
    for key in MATERIAL_FLAGS:
        if snapshot.get(key) is not False:
            raise ValueError(f"{label}: snapshot became authorizing: {key}")
    rows = snapshot.get("watchlist")
    if not isinstance(rows, list) or len(rows) != snapshot.get("source_count"):
        raise ValueError(f"{label}: source inventory mismatch")
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"{label}: watch row must be object")
        source_id = row.get("source_id")
        if not isinstance(source_id, str) or not source_id or source_id in by_id:
            raise ValueError(f"{label}: duplicate/missing source id {source_id!r}")
        if row.get("observation_state") not in ALLOWED_OBSERVATION_STATES:
            raise ValueError(f"{label}: forbidden programming state for {source_id}")
        if row.get("market_intelligence_only") is not True or row.get("publication_effect") != "NONE":
            raise ValueError(f"{label}: row policy drift for {source_id}")
        for key in MATERIAL_FLAGS:
            if row.get(key) is not False:
                raise ValueError(f"{label}: row became authorizing for {source_id}: {key}")
        semantic = _fingerprint(_row_semantic_payload(row))
        transport = _fingerprint(_row_transport_payload(row))
        stored_semantic = row.get("semantic_fingerprint")
        stored_transport = row.get("transport_fingerprint")
        if stored_semantic is not None and stored_semantic != semantic:
            raise ValueError(f"{label}: semantic fingerprint mismatch for {source_id}")
        if stored_transport is not None and stored_transport != transport:
            raise ValueError(f"{label}: transport fingerprint mismatch for {source_id}")
        by_id[source_id] = row
    return by_id


def _lkg_reference(
    current_row: dict[str, Any] | None,
    previous_row: dict[str, Any] | None,
    previous_snapshot: dict[str, Any] | None,
) -> tuple[str, dict[str, Any] | None]:
    if current_row is None:
        return "NOT_APPLICABLE_SOURCE_REMOVED", None
    health = current_row.get("source_health") or {}
    if not str(health.get("health_state") or "").startswith("DEGRADED"):
        return "NOT_REQUIRED_CURRENT_SOURCE_USABLE", None
    if previous_row is None or previous_snapshot is None:
        return "REQUIRED_REFERENCE_UNAVAILABLE", None
    previous_health = previous_row.get("source_health") or {}
    if previous_health.get("health_state") != "HEALTHY" or not _is_sha256(previous_health.get("raw_sha256")):
        return "REQUIRED_REFERENCE_UNAVAILABLE", None
    return "REFERENCE_AVAILABLE_FROM_PREVIOUS_HEALTHY_SNAPSHOT", {
        "source_id": previous_row.get("source_id"),
        "authority_url": previous_row.get("authority_url"),
        "previous_run_id": previous_snapshot.get("run_id"),
        "previous_fetched_at": previous_snapshot.get("fetched_at"),
        "raw_sha256": previous_health.get("raw_sha256"),
        "use_constraint": "LAST_KNOWN_GOOD_EVIDENCE_REFERENCE_ONLY_NO_CURRENT_MATERIAL_FACT",
    }


def reconcile_snapshots(
    current: dict[str, Any],
    previous: dict[str, Any] | None = None,
    *,
    reconciled_at: str | None = None,
) -> dict[str, Any]:
    current_by_id = _validate_snapshot(current, label="current")
    previous_by_id = _validate_snapshot(previous, label="previous") if previous is not None else {}
    when = _parse_observed_at(reconciled_at)

    changes: list[dict[str, Any]] = []
    semantic_change_count = 0
    transport_change_count = 0
    source_inventory_change_count = 0
    lkg_reference_available_count = 0
    lkg_reference_missing_count = 0

    all_ids = sorted(set(current_by_id) | set(previous_by_id))
    for source_id in all_ids:
        current_row = current_by_id.get(source_id)
        previous_row = previous_by_id.get(source_id)
        if current_row is None:
            semantic_changed = True
            transport_changed = False
            source_inventory_changed = True
            change_kind = "SOURCE_REMOVED"
        elif previous_row is None:
            semantic_changed = previous is not None
            transport_changed = previous is not None
            source_inventory_changed = previous is not None
            change_kind = "BASELINE_SOURCE" if previous is None else "SOURCE_ADDED"
        else:
            semantic_changed = _fingerprint(_row_semantic_payload(current_row)) != _fingerprint(
                _row_semantic_payload(previous_row)
            )
            transport_changed = _fingerprint(_row_transport_payload(current_row)) != _fingerprint(
                _row_transport_payload(previous_row)
            )
            source_inventory_changed = False
            if semantic_changed and transport_changed:
                change_kind = "SEMANTIC_AND_TRANSPORT_CHANGE"
            elif semantic_changed:
                change_kind = "SEMANTIC_CHANGE"
            elif transport_changed:
                change_kind = "TRANSPORT_OR_CONTENT_CHANGE"
            else:
                change_kind = "NO_CHANGE"

        if semantic_changed:
            semantic_change_count += 1
        if transport_changed:
            transport_change_count += 1
        if source_inventory_changed:
            source_inventory_change_count += 1

        lkg_status, lkg_reference = _lkg_reference(current_row, previous_row, previous)
        if lkg_status == "REFERENCE_AVAILABLE_FROM_PREVIOUS_HEALTHY_SNAPSHOT":
            lkg_reference_available_count += 1
        elif lkg_status == "REQUIRED_REFERENCE_UNAVAILABLE":
            lkg_reference_missing_count += 1

        changes.append({
            "source_id": source_id,
            "change_kind": change_kind,
            "source_inventory_changed": source_inventory_changed,
            "semantic_changed": semantic_changed,
            "transport_or_content_changed": transport_changed,
            "current_semantic_fingerprint": (
                _fingerprint(_row_semantic_payload(current_row)) if current_row is not None else None
            ),
            "previous_semantic_fingerprint": (
                _fingerprint(_row_semantic_payload(previous_row)) if previous_row is not None else None
            ),
            "current_transport_fingerprint": (
                _fingerprint(_row_transport_payload(current_row)) if current_row is not None else None
            ),
            "previous_transport_fingerprint": (
                _fingerprint(_row_transport_payload(previous_row)) if previous_row is not None else None
            ),
            "current_observation_state": current_row.get("observation_state") if current_row else None,
            "previous_observation_state": previous_row.get("observation_state") if previous_row else None,
            "current_consultation_lifecycle": (
                current_row.get("consultation_lifecycle") if current_row else None
            ),
            "previous_consultation_lifecycle": (
                previous_row.get("consultation_lifecycle") if previous_row else None
            ),
            "current_source_health": (
                (current_row.get("source_health") or {}).get("health_state") if current_row else None
            ),
            "previous_source_health": (
                (previous_row.get("source_health") or {}).get("health_state") if previous_row else None
            ),
            "lkg_status": lkg_status,
            "lkg_reference": lkg_reference,
            "market_intelligence_only": True,
            "material_fact_use": False,
            "open_call_authorized": False,
            "publish_authorized": False,
            "distribution_authorized": False,
        })

    if previous is None:
        reconciliation_state = "BASELINE_CAPTURED_NO_PREVIOUS_SNAPSHOT"
    elif semantic_change_count or source_inventory_change_count:
        reconciliation_state = "PIPELINE_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
    elif transport_change_count:
        reconciliation_state = "TRANSPORT_OR_CONTENT_DRIFT_ONLY"
    else:
        reconciliation_state = "NO_CHANGE"

    pipeline_watch_candidate = previous is not None and bool(
        semantic_change_count or source_inventory_change_count
    )
    source_health_watch_candidate = previous is not None and bool(transport_change_count)
    return {
        "schema_version": "1.0",
        "adapter_id": RECONCILIATION_VERSION,
        "reconciled_at": when.isoformat().replace("+00:00", "Z"),
        "source_family": "INTERREG",
        "programme_period": "2028-2034",
        "current_run_id": current.get("run_id"),
        "current_fetched_at": current.get("fetched_at"),
        "current_snapshot_sha256": _fingerprint(current),
        "current_registry_sha256": current.get("registry_sha256"),
        "previous_run_id": previous.get("run_id") if previous else None,
        "previous_fetched_at": previous.get("fetched_at") if previous else None,
        "previous_snapshot_sha256": _fingerprint(previous) if previous else None,
        "previous_registry_sha256": previous.get("registry_sha256") if previous else None,
        "registry_changed": bool(
            previous is not None and current.get("registry_sha256") != previous.get("registry_sha256")
        ),
        "reconciliation_state": reconciliation_state,
        "pipeline_semantic_reconciliation_status": "PASS",
        "source_count_current": len(current_by_id),
        "source_count_previous": len(previous_by_id) if previous is not None else None,
        "semantic_change_count": semantic_change_count,
        "transport_or_content_change_count": transport_change_count,
        "source_inventory_change_count": source_inventory_change_count,
        "lkg_reference_available_count": lkg_reference_available_count,
        "lkg_reference_missing_count": lkg_reference_missing_count,
        "changes": changes,
        "pipeline_watch_candidate": pipeline_watch_candidate,
        "pipeline_watch_label_required": "PROGRAMARE_VIITOARE_PIPELINE" if pipeline_watch_candidate else None,
        "source_health_watch_candidate": source_health_watch_candidate,
        "call_alert_authorized": False,
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
        "note": (
            "Semantic or transport change in PROGRAMMING_PIPELINE may create an internal/watch brief "
            "candidate only. It never authorizes OPEN_CALL, material call facts, publication or distribution."
        ),
        "rollback": (
            "Discard this reconciliation receipt and retain the immutable current/previous evidence snapshots; "
            "no canonical call state is mutated."
        ),
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
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--retry-backoff-seconds", type=float, default=0.25)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--previous-snapshot", type=Path)
    parser.add_argument("--reconciliation-output", type=Path)
    args = parser.parse_args()
    result = resolve(
        run_id=args.run_id,
        registry_path=args.registry,
        observed_at=args.observed_at,
        live=args.live,
        timeout=args.timeout,
        max_attempts=args.max_attempts,
        retry_backoff_seconds=args.retry_backoff_seconds,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")

    if args.reconciliation_output:
        previous = None
        if args.previous_snapshot:
            previous = json.loads(args.previous_snapshot.read_text(encoding="utf-8"))
        receipt = reconcile_snapshots(result, previous)
        args.reconciliation_output.parent.mkdir(parents=True, exist_ok=True)
        args.reconciliation_output.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
