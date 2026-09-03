#!/usr/bin/env python3
"""PARTENER.EU read-only Interreg 2028-2034 programming watch.

This adapter forward-ports only still-relevant official programming evidence from the
older Interreg lane. PROGRAMMING/PROPOSAL/CONSULTATION observations are never call
facts. Transport failures preserve evidence boundaries and may reference a validated
same-identity previous healthy receipt as LKG evidence only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

SCHEMA = "PARTENER_EU_INTERREG_FUTURE_PROGRAMMING_WATCH_V1"
RECONCILIATION_SCHEMA = "PARTENER_EU_INTERREG_FUTURE_PROGRAMMING_RECONCILIATION_V1"
PARSER_VERSION = "INTERREG_FUTURE_PROGRAMMING_WATCH_V1"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "partener-eu" / "ingest" / "interreg_future_programming_registry.json"
ALLOWED_STATES = {"PROPOSAL", "CONSULTATION", "PROGRAMMING_PROCESS"}
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
MISSING_FOR_OPEN = [
    "exact_call_or_topic_identifier",
    "current_official_exact_call_endpoint",
    "explicit_current_official_call_status",
    "same_identity_semantic_reconciliation",
    "call_specific_deadline_budget_eligibility_and_geography",
    "field_scoped_material_admission",
]


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fingerprint(value: Any) -> str:
    return _sha(_canonical(value))


def _utc(value: str | None = None) -> datetime:
    if value:
        if not value.endswith("Z"):
            raise ValueError("timestamp must be RFC3339 UTC-Z")
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _validate_url(url: str, hosts: list[str], prefixes: list[str]) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"non-HTTPS authority URL: {url}")
    if (parsed.hostname or "").lower() not in {h.lower() for h in hosts}:
        raise ValueError(f"authority host outside allowlist: {url}")
    if prefixes and not any((parsed.path or "/").startswith(prefix) for prefix in prefixes):
        raise ValueError(f"authority path outside allowlist: {url}")


def _false_boundary(obj: Mapping[str, Any], label: str) -> None:
    if obj.get("market_intelligence_only") is not True or obj.get("publication_effect") != "NONE":
        raise ValueError(f"{label}: market-intelligence boundary drift")
    for flag in MATERIAL_FLAGS:
        if obj.get(flag) is not False:
            raise ValueError(f"{label}: authorizing drift on {flag}")


def load_registry(path: Path = DEFAULT_REGISTRY) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    if data.get("schema_version") != "1.0" or data.get("registry_id") != "PARTENER_EU_INTERREG_FUTURE_PROGRAMMING_REGISTRY_V1":
        raise ValueError("future-programming registry schema/id mismatch")
    if data.get("source_family") != "INTERREG" or data.get("programme_period") != "2028-2034":
        raise ValueError("future-programming registry family/period mismatch")
    if _date(data.get("evidence_checked_date")) is None:
        raise ValueError("registry evidence_checked_date required")
    _false_boundary(data.get("policy") or {}, "registry policy")
    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("future-programming source registry empty")
    seen: set[str] = set()
    for row in sources:
        if not isinstance(row, dict):
            raise ValueError("registry source must be object")
        sid = str(row.get("id") or "")
        if not sid or sid in seen:
            raise ValueError("registry source id missing/duplicate")
        seen.add(sid)
        if row.get("observation_state") not in ALLOWED_STATES:
            raise ValueError(f"{sid}: forbidden observation state")
        if "OPEN" in str(row.get("observation_state")).upper() or "CALL" in str(row.get("observation_state")).upper():
            raise ValueError(f"{sid}: programming state encoded call semantics")
        if not row.get("programme_ids") or not row.get("programme_family") or not row.get("authority_class"):
            raise ValueError(f"{sid}: incomplete programme/authority metadata")
        _validate_url(str(row.get("authority_url") or ""), list(row.get("allowed_hosts") or []), list(row.get("allowed_path_prefixes") or []))
        supporting = row.get("supporting_authority_url")
        if supporting and urlparse(str(supporting)).scheme != "https":
            raise ValueError(f"{sid}: supporting authority must be HTTPS")
        groups = row.get("required_markers")
        if not isinstance(groups, list) or not groups or any(not isinstance(g, list) or not g for g in groups):
            raise ValueError(f"{sid}: required marker groups missing")
        start, end = _date(row.get("consultation_start_date")), _date(row.get("consultation_end_date"))
        if start and end and end < start:
            raise ValueError(f"{sid}: consultation end before start")
    return data, _sha(raw)


def _lifecycle(row: Mapping[str, Any], observed: date) -> str:
    if row.get("observation_state") != "CONSULTATION":
        return "NOT_A_CONSULTATION"
    start, end = _date(row.get("consultation_start_date")), _date(row.get("consultation_end_date"))
    if start and observed < start:
        return "BEFORE_WINDOW"
    if end and observed > end:
        return "AFTER_WINDOW"
    if start and end:
        return "IN_WINDOW"
    if end:
        return "END_KNOWN_START_NOT_STATED"
    if start:
        return "WINDOW_END_NOT_STATED"
    return "WINDOW_BOUNDS_NOT_STATED"


def _fetch(row: Mapping[str, Any], timeout: float) -> dict[str, Any]:
    requested = str(row["authority_url"])
    req = Request(
        requested,
        headers={
            "User-Agent": "PARTENER.EU-InterregFutureProgramming/1.0 (+https://partener.eu)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.1",
        },
        method="GET",
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read()
            status = int(getattr(response, "status", 200))
            final_url = response.geturl()
            content_type = str(response.headers.get("Content-Type", ""))
        _validate_url(final_url, list(row.get("allowed_hosts") or []), list(row.get("allowed_path_prefixes") or []))
        if status != 200:
            return {
                "health_state": "DEGRADED",
                "requested_url": requested,
                "final_url": final_url,
                "http_status": status,
                "content_type": content_type,
                "raw_sha256": _sha(raw),
                "raw_size_bytes": len(raw),
                "missing_marker_groups": [],
                "error_type": "HTTP_STATUS",
                "error": f"unexpected HTTP status {status}",
            }
        folded = re.sub(r"\s+", " ", raw.decode("utf-8", errors="ignore")).casefold()
        missing = [group for group in row.get("required_markers") or [] if not any(str(marker).casefold() in folded for marker in group)]
        if missing:
            return {
                "health_state": "DEGRADED_MARKER_MISMATCH",
                "requested_url": requested,
                "final_url": final_url,
                "http_status": status,
                "content_type": content_type,
                "raw_sha256": _sha(raw),
                "raw_size_bytes": len(raw),
                "missing_marker_groups": missing,
                "error_type": "SEMANTIC_MARKER_MISMATCH",
                "error": None,
            }
        return {
            "health_state": "HEALTHY",
            "requested_url": requested,
            "final_url": final_url,
            "http_status": status,
            "content_type": content_type,
            "raw_sha256": _sha(raw),
            "raw_size_bytes": len(raw),
            "missing_marker_groups": [],
            "error_type": None,
            "error": None,
        }
    except HTTPError as exc:
        return {
            "health_state": "DEGRADED",
            "requested_url": requested,
            "final_url": None,
            "http_status": int(exc.code),
            "content_type": None,
            "raw_sha256": None,
            "raw_size_bytes": 0,
            "missing_marker_groups": [],
            "error_type": "HTTP_ERROR",
            "error": f"HTTPError: {exc}",
        }
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        text = str(exc).casefold()
        failure = "TLS_CERTIFICATE_VERIFY_FAILED" if "certificate verify failed" in text or "certificate_verify_failed" in text else type(exc).__name__.upper()
        return {
            "health_state": "DEGRADED",
            "requested_url": requested,
            "final_url": None,
            "http_status": None,
            "content_type": None,
            "raw_sha256": None,
            "raw_size_bytes": 0,
            "missing_marker_groups": [],
            "error_type": failure,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _semantic_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "source_id", "programme_ids", "programme", "programme_family", "programme_period",
        "authority_class", "authority_url", "supporting_authority_url", "observation_state",
        "projection_eligible", "signal_basis", "source_published_date", "consultation_start_date",
        "consultation_end_date", "consultation_lifecycle",
    )
    return {key: row.get(key) for key in keys}


def _transport_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    health = row.get("source_health") or {}
    return {key: health.get(key) for key in (
        "health_state", "requested_url", "final_url", "http_status", "content_type",
        "raw_sha256", "missing_marker_groups", "error_type",
    )}


def build_snapshot(*, run_id: str, observed_at: str | None = None, registry_path: Path = DEFAULT_REGISTRY, timeout: float = 12.0) -> dict[str, Any]:
    registry, registry_hash = load_registry(registry_path)
    now = _utc(observed_at)
    rows: list[dict[str, Any]] = []
    for spec in registry["sources"]:
        row = {
            "source_id": spec["id"],
            "source_family": "INTERREG",
            "programme_ids": list(spec["programme_ids"]),
            "programme": spec["programme"],
            "programme_family": spec["programme_family"],
            "programme_period": "2028-2034",
            "authority_class": spec["authority_class"],
            "authority_url": spec["authority_url"],
            "supporting_authority_url": spec.get("supporting_authority_url"),
            "observation_state": spec["observation_state"],
            "projection_eligible": spec.get("projection_eligible") is True,
            "signal_basis": spec["signal_basis"],
            "source_published_date": spec.get("source_published_date"),
            "consultation_start_date": spec.get("consultation_start_date"),
            "consultation_end_date": spec.get("consultation_end_date"),
            "consultation_lifecycle": _lifecycle(spec, now.date()),
            "source_health": _fetch(spec, timeout),
            "market_intelligence_only": True,
            "material_fact_use": False,
            "open_call_authorized": False,
            "closed_call_authorized": False,
            "deadline_authorized": False,
            "budget_authorized": False,
            "eligibility_authorized": False,
            "publish_authorized": False,
            "distribution_authorized": False,
            "call_alert_authorized": False,
            "canonical_corpus_mutation": False,
            "publication_effect": "NONE",
            "missing_for_open_confirmation": list(MISSING_FOR_OPEN),
        }
        row["semantic_fingerprint"] = _fingerprint(_semantic_payload(row))
        row["transport_fingerprint"] = _fingerprint(_transport_payload(row))
        rows.append(row)
    rows.sort(key=lambda r: r["source_id"])
    healthy = sum(1 for row in rows if (row["source_health"] or {}).get("health_state") == "HEALTHY")
    output = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
        "fetched_at": now.isoformat().replace("+00:00", "Z"),
        "source_family": "INTERREG",
        "programme_family": "INTERREG_FUTURE_PROGRAMMING",
        "programme_period": "2028-2034",
        "authority_class": "OFFICIAL_EU_AND_PROGRAMME_AUTHORITIES",
        "observation_state": "PROGRAMMING_PIPELINE",
        "registry_sha256": registry_hash,
        "registry_evidence_checked_date": registry["evidence_checked_date"],
        "source_count": len(rows),
        "healthy_source_count": healthy,
        "degraded_source_count": len(rows) - healthy,
        "source_health": "HEALTHY" if healthy == len(rows) else "DEGRADED",
        "coverage_complete": healthy == len(rows),
        "watchlist": rows,
        "market_intelligence_only": True,
        "material_fact_use": False,
        "open_call_authorized": False,
        "closed_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "call_alert_authorized": False,
        "canonical_corpus_mutation": False,
        "publication_effect": "NONE",
        "missing_for_open_confirmation": list(MISSING_FOR_OPEN),
    }
    output["semantic_fingerprint"] = _fingerprint([[r["source_id"], r["semantic_fingerprint"]] for r in rows])
    output["transport_fingerprint"] = _fingerprint([[r["source_id"], r["transport_fingerprint"]] for r in rows])
    validate_snapshot(output)
    return output


def validate_snapshot(snapshot: Mapping[str, Any]) -> None:
    if snapshot.get("schema") != SCHEMA or snapshot.get("parser_version") != PARSER_VERSION:
        raise ValueError("future-programming snapshot schema/parser mismatch")
    if snapshot.get("source_family") != "INTERREG" or snapshot.get("programme_period") != "2028-2034":
        raise ValueError("future-programming snapshot family/period drift")
    if snapshot.get("observation_state") != "PROGRAMMING_PIPELINE":
        raise ValueError("future-programming top-level observation drift")
    _false_boundary(snapshot, "future-programming snapshot")
    rows = snapshot.get("watchlist")
    if not isinstance(rows, list) or len(rows) != snapshot.get("source_count") or not rows:
        raise ValueError("future-programming source inventory mismatch")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("future-programming row must be object")
        sid = str(row.get("source_id") or "")
        if not sid or sid in seen:
            raise ValueError("future-programming source id missing/duplicate")
        seen.add(sid)
        if row.get("observation_state") not in ALLOWED_STATES:
            raise ValueError(f"{sid}: forbidden observation state")
        _false_boundary(row, f"future-programming row {sid}")
        if row.get("semantic_fingerprint") != _fingerprint(_semantic_payload(row)):
            raise ValueError(f"{sid}: semantic fingerprint mismatch")
        if row.get("transport_fingerprint") != _fingerprint(_transport_payload(row)):
            raise ValueError(f"{sid}: transport fingerprint mismatch")
        if not set(MISSING_FOR_OPEN).issubset(set(row.get("missing_for_open_confirmation") or [])):
            raise ValueError(f"{sid}: missing-for-open boundary weakened")
    if snapshot.get("semantic_fingerprint") != _fingerprint([[r["source_id"], r["semantic_fingerprint"]] for r in rows]):
        raise ValueError("future-programming aggregate semantic fingerprint mismatch")
    if snapshot.get("transport_fingerprint") != _fingerprint([[r["source_id"], r["transport_fingerprint"]] for r in rows]):
        raise ValueError("future-programming aggregate transport fingerprint mismatch")


def reconcile(current: Mapping[str, Any], previous: Mapping[str, Any] | None, *, reconciled_at: str | None = None) -> dict[str, Any]:
    validate_snapshot(current)
    if previous is not None:
        validate_snapshot(previous)
    current_rows = {row["source_id"]: row for row in current["watchlist"]}
    previous_rows = {row["source_id"]: row for row in previous["watchlist"]} if previous else {}
    changes: list[dict[str, Any]] = []
    semantic_changes = transport_changes = inventory_changes = lkg_available = lkg_missing = 0
    pipeline_evidence_changes = 0
    for sid in sorted(set(current_rows) | set(previous_rows)):
        cur, prev = current_rows.get(sid), previous_rows.get(sid)
        if cur is None or prev is None:
            inventory_changed = previous is not None
            semantic_changed = previous is not None
            transport_changed = previous is not None
            kind = "SOURCE_REMOVED" if cur is None else ("SOURCE_ADDED" if previous is not None else "BASELINE_SOURCE")
        else:
            inventory_changed = False
            semantic_changed = cur["semantic_fingerprint"] != prev["semantic_fingerprint"]
            transport_changed = cur["transport_fingerprint"] != prev["transport_fingerprint"]
            kind = "SEMANTIC_AND_TRANSPORT_CHANGE" if semantic_changed and transport_changed else "SEMANTIC_CHANGE" if semantic_changed else "TRANSPORT_OR_CONTENT_CHANGE" if transport_changed else "NO_CHANGE"
        semantic_changes += int(semantic_changed)
        transport_changes += int(transport_changed)
        inventory_changes += int(inventory_changed)
        current_healthy = cur is not None and (cur.get("source_health") or {}).get("health_state") == "HEALTHY"
        pipeline_watch_evidence_usable = bool(current_healthy and (semantic_changed or inventory_changed))
        pipeline_evidence_changes += int(pipeline_watch_evidence_usable)
        lkg_status, lkg_reference = "NOT_REQUIRED_CURRENT_SOURCE_USABLE", None
        if cur is not None and (cur.get("source_health") or {}).get("health_state") != "HEALTHY":
            lkg_status = "REQUIRED_REFERENCE_UNAVAILABLE"
            if prev is not None and (prev.get("source_health") or {}).get("health_state") == "HEALTHY":
                same_identity = all(cur.get(key) == prev.get(key) for key in ("source_id", "programme_family", "authority_url"))
                if same_identity and (prev.get("source_health") or {}).get("raw_sha256"):
                    lkg_status = "REFERENCE_AVAILABLE_FROM_PREVIOUS_HEALTHY_SAME_IDENTITY"
                    lkg_reference = {
                        "source_id": sid,
                        "authority_url": prev.get("authority_url"),
                        "previous_run_id": previous.get("run_id"),
                        "previous_fetched_at": previous.get("fetched_at"),
                        "raw_sha256": prev["source_health"].get("raw_sha256"),
                        "use_constraint": "EVIDENCE_REFERENCE_ONLY_NEVER_CURRENT_CALL_OR_PROGRAMMING_TRUTH",
                    }
                    lkg_available += 1
                else:
                    lkg_missing += 1
            else:
                lkg_missing += 1
        changes.append({
            "source_id": sid,
            "change_kind": kind,
            "source_inventory_changed": inventory_changed,
            "semantic_changed": semantic_changed,
            "transport_or_content_changed": transport_changed,
            "pipeline_watch_evidence_usable": pipeline_watch_evidence_usable,
            "lkg_status": lkg_status,
            "lkg_reference": lkg_reference,
            "market_intelligence_only": True,
            "material_fact_use": False,
            "open_call_authorized": False,
            "publish_authorized": False,
            "distribution_authorized": False,
            "call_alert_authorized": False,
            "publication_effect": "NONE",
        })
    if previous is None:
        state = "BASELINE_CAPTURED_NON_AUTHORIZING"
    elif semantic_changes or inventory_changes:
        state = "PIPELINE_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING" if pipeline_evidence_changes else "PIPELINE_SEMANTIC_CHANGE_CURRENT_SOURCE_UNUSABLE_NON_AUTHORIZING"
    elif transport_changes:
        state = "TRANSPORT_OR_CONTENT_DRIFT_ONLY"
    else:
        state = "NO_CHANGE"
    output = {
        "schema": RECONCILIATION_SCHEMA,
        "parser_version": PARSER_VERSION,
        "reconciled_at": _utc(reconciled_at).isoformat().replace("+00:00", "Z"),
        "source_family": "INTERREG",
        "programme_period": "2028-2034",
        "current_run_id": current.get("run_id"),
        "previous_run_id": previous.get("run_id") if previous else None,
        "current_snapshot_sha256": _fingerprint(current),
        "previous_snapshot_sha256": _fingerprint(previous) if previous else None,
        "reconciliation_state": state,
        "semantic_change_count": semantic_changes,
        "transport_or_content_change_count": transport_changes,
        "source_inventory_change_count": inventory_changes,
        "pipeline_evidence_change_count": pipeline_evidence_changes,
        "lkg_reference_available_count": lkg_available,
        "lkg_reference_missing_count": lkg_missing,
        "pipeline_watch_candidate": previous is not None and bool(pipeline_evidence_changes),
        "source_health_watch_candidate": previous is not None and bool(transport_changes),
        "changes": changes,
        "market_intelligence_only": True,
        "material_fact_use": False,
        "open_call_authorized": False,
        "closed_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "call_alert_authorized": False,
        "canonical_corpus_mutation": False,
        "publication_effect": "NONE",
        "missing_for_open_confirmation": list(MISSING_FOR_OPEN),
        "rollback": "Discard reconciliation output and retain immutable source snapshots/history; no canonical call state is mutated.",
    }
    _false_boundary(output, "future-programming reconciliation")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--observed-at")
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--reconciliation-output", type=Path, required=True)
    args = parser.parse_args()
    current = build_snapshot(run_id=args.run_id, observed_at=args.observed_at, registry_path=args.registry, timeout=args.timeout)
    previous = json.loads(args.previous.read_text(encoding="utf-8")) if args.previous and args.previous.exists() else None
    receipt = reconcile(current, previous)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.reconciliation_output.parent.mkdir(parents=True, exist_ok=True)
    args.reconciliation_output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
