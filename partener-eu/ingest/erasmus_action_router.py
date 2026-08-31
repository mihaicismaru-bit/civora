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

PARSER_VERSION = "ERASMUS_ACTION_ROUTER_V1"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "partener-eu" / "ingest" / "erasmus_action_router_registry.json"

MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
)
MISSING_FOR_OPEN_CONFIRMATION = [
    "exact_action_or_call_identifier",
    "current_official_exact_action_or_call_endpoint",
    "explicit_current_official_action_or_call_status",
    "action_specific_deadline_budget_eligibility_and_participation_rules",
    "semantic_reconciliation",
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
        raise ValueError("unsupported Erasmus action-router registry schema")
    if data.get("registry_id") != "ERASMUS_ACTION_ROUTER_REGISTRY_V1":
        raise ValueError("unexpected Erasmus action-router registry id")
    if data.get("programme_family") != "Erasmus+" or data.get("source_family") != "EU_DIRECT":
        raise ValueError("Erasmus programme/source boundary drift")
    checked = date.fromisoformat(str(data.get("evidence_checked_date") or ""))
    if checked > datetime.now(timezone.utc).date():
        raise ValueError("registry evidence_checked_date is in the future")

    policy = data.get("policy") or {}
    if policy.get("market_intelligence_only") is not True or policy.get("publication_effect") != "NONE":
        raise ValueError("Erasmus router policy drift")
    for key in MATERIAL_FLAGS:
        if policy.get(key) is not False:
            raise ValueError(f"Erasmus router registry became authorizing: {key}")

    sources = data.get("evidence_sources") or []
    if not sources:
        raise ValueError("Erasmus router evidence source registry is empty")
    ids: set[str] = set()
    for source in sources:
        source_id = str(source.get("id") or "")
        if not source_id or source_id in ids:
            raise ValueError("duplicate or empty Erasmus evidence source id")
        ids.add(source_id)
        if not source.get("authority_class"):
            raise ValueError(f"authority class missing for {source_id}")
        _validate_https_url(
            str(source.get("authority_url") or ""),
            hosts=list(source.get("allowed_hosts") or []),
            path_prefixes=list(source.get("allowed_path_prefixes") or []),
        )
        groups = source.get("required_marker_groups") or []
        if not groups or any(not isinstance(group, list) or not group for group in groups):
            raise ValueError(f"required markers missing for {source_id}")

    modes = data.get("management_modes") or {}
    expected = {"CENTRALISED_EACEA", "DECENTRALISED_NATIONAL_AGENCY"}
    if set(modes) != expected:
        raise ValueError("Erasmus management-mode registry drift")
    for mode_name, mode in modes.items():
        if mode.get("registration_identifier_kind") not in {"PIC", "OID"}:
            raise ValueError(f"invalid registration identifier for {mode_name}")
        if mode.get("exact_action_endpoint_required") is not True:
            raise ValueError(f"exact action endpoint requirement relaxed for {mode_name}")
        if mode.get("exact_call_or_topic_identifier_required") is not True:
            raise ValueError(f"exact action identifier requirement relaxed for {mode_name}")
        if mode.get("semantic_reconciliation_required") is not True:
            raise ValueError(f"semantic reconciliation requirement relaxed for {mode_name}")
        gateway = str(mode.get("application_gateway_url") or "")
        parsed = urlparse(gateway)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() != str(mode.get("gateway_host") or "").lower():
            raise ValueError(f"application gateway drift for {mode_name}")
        basis = set(mode.get("route_basis_source_ids") or [])
        if not basis or not basis.issubset(ids):
            raise ValueError(f"route basis source drift for {mode_name}")
    return data, _sha256(raw)


def _probe_source(source: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    url = str(source["authority_url"])
    request = Request(
        url,
        headers={
            "User-Agent": "PARTENER.EU-ErasmusActionRouter/1.0 (+https://partener.eu)",
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
        if status != 200:
            return {
                "health_state": "DEGRADED",
                "lkg_required": True,
                "requested_url": url,
                "final_url": final_url,
                "http_status": status,
                "content_type": content_type,
                "raw_sha256": _sha256(raw),
                "raw_size_bytes": len(raw),
                "missing_marker_groups": [],
                "error": f"unexpected HTTP status {status}",
            }
        folded = re.sub(r"\s+", " ", raw.decode("utf-8", errors="ignore")).casefold()
        missing: list[list[str]] = []
        for group in source.get("required_marker_groups") or []:
            if not any(str(marker).casefold() in folded for marker in group):
                missing.append(group)
        if missing:
            return {
                "health_state": "DEGRADED_MARKER_MISMATCH",
                "lkg_required": True,
                "requested_url": url,
                "final_url": final_url,
                "http_status": status,
                "content_type": content_type,
                "raw_sha256": _sha256(raw),
                "raw_size_bytes": len(raw),
                "missing_marker_groups": missing,
                "error": None,
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
            "health_state": "DEGRADED",
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


def resolve(
    *,
    management_mode: str,
    run_id: str,
    action_reference_hint: str | None = None,
    observed_at: str | None = None,
    registry_path: Path = DEFAULT_REGISTRY,
    live: bool = False,
    timeout: float = 10.0,
) -> dict[str, Any]:
    registry, registry_sha256 = load_registry(registry_path)
    now = _parse_observed_at(observed_at)
    mode_name = str(management_mode or "").strip().upper()
    modes = registry["management_modes"]
    if mode_name not in modes:
        raise ValueError(f"unsupported Erasmus management mode: {management_mode!r}")
    mode = modes[mode_name]

    hint = str(action_reference_hint or "").strip() or None
    if hint and len(hint) > 180:
        raise ValueError("action_reference_hint too long")

    sources_by_id = {source["id"]: source for source in registry["evidence_sources"]}
    evidence: list[dict[str, Any]] = []
    for source_id in mode["route_basis_source_ids"]:
        source = sources_by_id[source_id]
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
        evidence.append({
            "source_id": source_id,
            "authority_class": source["authority_class"],
            "authority_url": source["authority_url"],
            "fetched_at": now.isoformat().replace("+00:00", "Z"),
            "source_health": health,
        })

    healthy_count = sum(1 for row in evidence if row["source_health"]["health_state"] == "HEALTHY")
    degraded_count = sum(1 for row in evidence if str(row["source_health"]["health_state"]).startswith("DEGRADED"))
    if not live:
        health_state = "NOT_PROBED"
    elif degraded_count:
        health_state = "DEGRADED"
    else:
        health_state = "HEALTHY"

    route_payload = {
        "management_mode": mode_name,
        "route_owner": mode["route_owner"],
        "route_class": mode["route_class"],
        "registration_identifier_kind": mode["registration_identifier_kind"],
        "application_gateway_url": mode["application_gateway_url"],
        "exact_action_endpoint_required": True,
        "exact_call_or_topic_identifier_required": True,
        "semantic_reconciliation_required": True,
    }

    return {
        "schema_version": "1.0",
        "adapter_id": PARSER_VERSION,
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
        "fetched_at": now.isoformat().replace("+00:00", "Z"),
        "registry_sha256": registry_sha256,
        "registry_evidence_checked_date": registry["evidence_checked_date"],
        "source_family": "EU_DIRECT",
        "programme_family": "Erasmus+",
        "authority_class": "OFFICIAL_ERASMUS_APPLICATION_ROUTE_INTELLIGENCE",
        "observation_state": "APPLICATION_ROUTE_INTELLIGENCE",
        "management_mode": mode_name,
        "action_reference_hint": hint,
        "action_reference_hint_authority": "DISCOVERY_HINT_ONLY_NOT_CALL_IDENTIFIER" if hint else None,
        "route": route_payload,
        "route_semantic_fingerprint": _fingerprint(route_payload),
        "evidence_source_count": len(evidence),
        "healthy_evidence_source_count": healthy_count,
        "degraded_evidence_source_count": degraded_count,
        "source_health_state": health_state,
        "evidence": evidence,
        "market_intelligence_only": True,
        "material_fact_use": False,
        "open_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "publication_effect": "NONE",
        "exact_action_endpoint_required": True,
        "exact_call_or_topic_identifier_required": True,
        "semantic_reconciliation_required": True,
        "missing_for_open_confirmation": list(MISSING_FOR_OPEN_CONFIRMATION),
        "note": (
            "This adapter routes Erasmus+ application management only. Programme guides, programme pages, "
            "route guidance and action-reference hints cannot authorize OPEN, deadline, budget or eligibility."
        ),
        "rollback": "Discard this route-intelligence receipt; no canonical call state is mutated.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve the official Erasmus+ application route without authorizing call facts.")
    parser.add_argument("--management-mode", required=True, choices=["CENTRALISED_EACEA", "DECENTRALISED_NATIONAL_AGENCY"])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--action-reference-hint")
    parser.add_argument("--observed-at")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = resolve(
        management_mode=args.management_mode,
        run_id=args.run_id,
        action_reference_hint=args.action_reference_hint,
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
