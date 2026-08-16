#!/usr/bin/env python3
"""Native/free observed-metrics transport for LOCAL NEWS OS.

This module is the network-boundary companion to ``observed_metrics_collector``.
It deliberately does not make analytics an editorial gate: it may read a runtime
credential, fetch native observed counters for an already-confirmed publication,
and hand the provider payload to the durable collector. Publication itself never
waits on this transport.

The first verified transport profile is Meta Graph for Facebook Pages and
Instagram professional media. The contract is intentionally conservative:
- only CHANNEL_CONFIG-declared native/free metric sources are eligible;
- only PUBLISHED records with remote publication proof are queried;
- a runtime access attestation must say the corresponding platform is ready;
- credential values are accepted only at the network boundary and never returned,
  persisted, logged, put in URLs, or included in fingerprints;
- each metric is requested independently so an unavailable metric cannot erase a
  valid direct observation from the same publication;
- provider values are not added, estimated, inferred, or synthesized here;
- only direct Graph ``data`` entries whose ``name`` exactly matches the requested
  metric are passed to ``observed_metrics_collector``;
- auth/permission failures fail closed for collection, transient failures request
  a later retry, and unsupported metrics are skipped;
- every analytics failure leaves ``publication_blocked`` false.

No paid scheduler, paid analytics service, or paid content API is used.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

import observed_metrics_collector

SCHEMA_VERSION = "1.0"
TRANSPORT_ID = "local-news-os-native-metrics-transport"
DEFAULT_GRAPH_VERSION = "v26.0"

# Deliberately small, direct-observation profiles. New metrics require their own
# tested increment rather than silently broadening the optimizer input surface.
META_PROFILES: dict[str, dict[str, Any]] = {
    "facebook": {
        "source": "meta_graph_api",
        "metric_candidates": ("post_impressions", "post_impressions_unique"),
        "ready_key": "facebook_ready",
    },
    "instagram": {
        "source": "instagram_graph_api",
        "metric_candidates": ("reach", "saved"),
        "ready_key": "instagram_ready",
    },
}

ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
TRANSIENT_META_CODES = {1, 2, 4, 17, 32, 613}
AUTH_META_CODES = {10, 190, 200}
UNSUPPORTED_META_CODES = {100}

HttpGet = Callable[[str, dict[str, str]], tuple[int, dict[str, Any]]]


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _iso(value: str) -> dt.datetime:
    text = _clean(value)
    if not text:
        raise ValueError("timestamp is required")
    parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def credential_env_name(credentials_ref: Any) -> str:
    """Return only the GitHub Actions secret *name*, never a secret value."""
    raw = _clean(credentials_ref)
    prefix = "github-actions-secret:"
    if not raw.startswith(prefix):
        raise ValueError("METRICS_TRANSPORT_REQUIRES_GITHUB_ACTIONS_SECRET_REF")
    name = raw[len(prefix):].strip()
    if not ENV_NAME_RE.fullmatch(name):
        raise ValueError("INVALID_CREDENTIAL_ENV_NAME")
    return name


def _access_verified(platform: str, attestation: dict[str, Any]) -> tuple[bool, list[str]]:
    blocks: list[str] = []
    if not isinstance(attestation, dict):
        return False, ["MISSING_ACCESS_ATTESTATION"]
    status = _clean(attestation.get("status")).upper()
    if status not in {"VALID", "VERIFIED"}:
        blocks.append("UNVERIFIED_NATIVE_ACCESS")
    if attestation.get("secret_material_persisted") is True:
        blocks.append("SECRET_MATERIAL_PERSISTED")
    profile = META_PROFILES.get(platform)
    if not profile:
        blocks.append("UNSUPPORTED_METRICS_TRANSPORT")
    else:
        ready_key = _clean(profile.get("ready_key"))
        generic_ready = attestation.get("verified_metrics_access") is True
        platform_ready = bool(ready_key and attestation.get(ready_key) is True)
        if not (generic_ready or platform_ready):
            blocks.append("PLATFORM_ACCESS_NOT_READY")
    return not blocks, sorted(set(blocks))


def build_transport_plan(
    channel: dict[str, Any],
    publication: dict[str, Any],
    access_attestation: dict[str, Any],
    *,
    graph_version: str = DEFAULT_GRAPH_VERSION,
) -> dict[str, Any]:
    """Build a secret-free, deterministic plan for one native metrics fetch."""
    if not isinstance(channel, dict) or not isinstance(publication, dict):
        raise TypeError("channel and publication must be mappings")
    platform = _clean(channel.get("platform")).lower()
    blocks: list[str] = []
    profile = META_PROFILES.get(platform)
    if not profile:
        blocks.append("UNSUPPORTED_METRICS_TRANSPORT")
    if channel.get("zero_paid_dependency") is not True:
        blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")
    metrics = channel.get("metrics") if isinstance(channel.get("metrics"), dict) else {}
    if metrics.get("observed_only") is not True:
        blocks.append("OBSERVED_ONLY_REQUIRED")
    source = _clean(profile.get("source")) if profile else ""
    declared_sources = {_clean(item) for item in metrics.get("sources", []) if _clean(item)} if isinstance(metrics.get("sources"), list) else set()
    if source and source not in declared_sources:
        blocks.append("UNDECLARED_METRIC_SOURCE")

    descriptor = observed_metrics_collector.validate_publication_descriptor(channel, publication)
    blocks.extend(descriptor.get("hard_blocks", []))
    access_ok, access_blocks = _access_verified(platform, access_attestation)
    if not access_ok:
        blocks.extend(access_blocks)

    try:
        env_name = credential_env_name(channel.get("credentials_ref"))
    except ValueError as exc:
        env_name = ""
        blocks.append(str(exc))

    version = _clean(graph_version)
    if not re.fullmatch(r"v\d{1,3}\.\d{1,2}", version):
        blocks.append("INVALID_GRAPH_VERSION")

    if blocks:
        return {
            "schema_version": SCHEMA_VERSION,
            "transport_id": TRANSPORT_ID,
            "status": "HOLD_TRANSPORT",
            "hard_blocks": sorted(set(blocks)),
            "publication_blocked": False,
            "plan": None,
        }

    remote_id = _clean(publication.get("remote_publication_id"))
    plan = {
        "schema_version": SCHEMA_VERSION,
        "transport_id": TRANSPORT_ID,
        "instance_id": _clean(channel.get("instance_id")),
        "channel_id": _clean(channel.get("channel_id")),
        "platform": platform,
        "source": source,
        "remote_publication_id": remote_id,
        "publication_id": _clean(publication.get("publication_id")),
        "graph_version": version,
        "metric_candidates": list(profile["metric_candidates"]),
        "credential_env_name": env_name,
        "network_boundary": "native_free_api",
        "guards": {
            "observed_only": True,
            "credential_value_in_plan": False,
            "credential_in_url": False,
            "raw_provider_payload_persisted_by_transport": False,
            "publication_blocked_by_analytics": False,
            "zero_paid_dependency": True,
        },
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "transport_id": TRANSPORT_ID,
        "status": "TRANSPORT_PLANNED",
        "hard_blocks": [],
        "publication_blocked": False,
        "plan": plan,
    }


def _graph_url(plan: dict[str, Any], metric_name: str) -> str:
    remote_id = urllib.parse.quote(_clean(plan.get("remote_publication_id")), safe="_-")
    version = urllib.parse.quote(_clean(plan.get("graph_version")), safe=".")
    metric = urllib.parse.quote(metric_name, safe="_")
    return f"https://graph.facebook.com/{version}/{remote_id}/insights?metric={metric}"


def _meta_error(payload: dict[str, Any]) -> tuple[int | None, str]:
    error = payload.get("error") if isinstance(payload, dict) and isinstance(payload.get("error"), dict) else {}
    raw_code = error.get("code")
    try:
        code = int(raw_code) if raw_code is not None else None
    except (TypeError, ValueError):
        code = None
    message = _clean(error.get("message"))
    return code, message


def _classify_failure(status_code: int, payload: dict[str, Any]) -> str:
    code, _ = _meta_error(payload)
    if status_code in {401, 403} or code in AUTH_META_CODES:
        return "AUTH_BLOCKED"
    if status_code == 429 or status_code >= 500 or code in TRANSIENT_META_CODES:
        return "RETRY_LATER"
    if status_code == 400 or code in UNSUPPORTED_META_CODES:
        return "UNSUPPORTED_METRIC"
    return "PROVIDER_ERROR"


def _exact_metric_entries(payload: dict[str, Any], requested_metric: str) -> list[dict[str, Any]]:
    """Keep provider entries verbatim except for dropping unrelated names."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    result: list[dict[str, Any]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if _clean(entry.get("name")).lower() != requested_metric.lower():
            continue
        # The durable collector performs the scalar-value check and all normalization.
        result.append(_clone(entry))
    return result


def urllib_http_get(url: str, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
    """Minimal stdlib HTTP GET. Caller must put the credential in Authorization."""
    request = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            payload = json.loads(raw) if raw else {}
            return int(response.status), payload if isinstance(payload, dict) else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {}
        return int(exc.code), payload if isinstance(payload, dict) else {}
    except (urllib.error.URLError, TimeoutError, OSError):
        return 503, {"error": {"code": 2, "message": "native transport unavailable"}}


def fetch_provider_payload(
    plan: dict[str, Any],
    credential_value: str,
    *,
    http_get: HttpGet = urllib_http_get,
) -> dict[str, Any]:
    """Fetch direct observed entries without exposing or persisting the credential."""
    if not isinstance(plan, dict):
        raise TypeError("plan must be a mapping")
    token = _clean(credential_value)
    if not token:
        return {
            "status": "BLOCKED_AUTH",
            "hard_blocks": ["MISSING_RUNTIME_CREDENTIAL"],
            "publication_blocked": False,
            "provider_payload": None,
            "metric_issues": [],
        }
    candidates = plan.get("metric_candidates")
    if not isinstance(candidates, list) or not candidates:
        return {
            "status": "HOLD_TRANSPORT",
            "hard_blocks": ["NO_METRIC_CANDIDATES"],
            "publication_blocked": False,
            "provider_payload": None,
            "metric_issues": [],
        }

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "LOCAL-NEWS-OS-Metrics/1.0",
    }
    entries: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    for metric in candidates:
        metric_name = _clean(metric).lower()
        url = _graph_url(plan, metric_name)
        # Defense in depth: credentials must never migrate into the URL.
        if token in url or "access_token=" in url.lower():
            return {
                "status": "HOLD_TRANSPORT",
                "hard_blocks": ["CREDENTIAL_LEAK_IN_URL"],
                "publication_blocked": False,
                "provider_payload": None,
                "metric_issues": [],
            }
        try:
            status_code, payload = http_get(url, dict(headers))
        except Exception:
            status_code, payload = 503, {"error": {"code": 2, "message": "native transport unavailable"}}
        if not isinstance(payload, dict):
            payload = {}
        if not (200 <= int(status_code) < 300) or isinstance(payload.get("error"), dict):
            classification = _classify_failure(int(status_code), payload)
            if classification == "UNSUPPORTED_METRIC":
                issues.append({"metric": metric_name, "code": "UNSUPPORTED_OR_UNAVAILABLE"})
                continue
            if classification == "AUTH_BLOCKED":
                return {
                    "status": "BLOCKED_AUTH",
                    "hard_blocks": ["NATIVE_METRICS_AUTH_OR_PERMISSION_FAILURE"],
                    "publication_blocked": False,
                    "provider_payload": None,
                    "metric_issues": issues,
                }
            if classification == "RETRY_LATER":
                return {
                    "status": "RETRY_LATER",
                    "hard_blocks": [],
                    "publication_blocked": False,
                    "provider_payload": None,
                    "metric_issues": issues + [{"metric": metric_name, "code": "TRANSIENT_PROVIDER_FAILURE"}],
                }
            return {
                "status": "HOLD_TRANSPORT",
                "hard_blocks": ["NATIVE_METRICS_PROVIDER_FAILURE"],
                "publication_blocked": False,
                "provider_payload": None,
                "metric_issues": issues,
            }
        exact = _exact_metric_entries(payload, metric_name)
        if not exact:
            issues.append({"metric": metric_name, "code": "EMPTY_DIRECT_METRIC"})
            continue
        entries.extend(exact)

    if not entries:
        return {
            "status": "NO_OBSERVED_METRICS",
            "hard_blocks": [],
            "publication_blocked": False,
            "provider_payload": None,
            "metric_issues": issues,
        }
    return {
        "status": "OBSERVED_PAYLOAD_READY",
        "hard_blocks": [],
        "publication_blocked": False,
        "provider_payload": {"data": entries},
        "metric_issues": issues,
        "guards": {
            "provider_values_transformed": False,
            "credential_value_returned": False,
            "credential_in_url": False,
            "zero_paid_dependency": True,
        },
    }


def collect_and_materialize(
    channel: dict[str, Any],
    publication: dict[str, Any],
    access_attestation: dict[str, Any],
    credential_value: str,
    *,
    now: str,
    http_get: HttpGet = urllib_http_get,
    existing_store: dict[str, Any] | None = None,
    existing_snapshot: dict[str, Any] | None = None,
    graph_version: str = DEFAULT_GRAPH_VERSION,
    ttl_hours: int = 72,
    min_samples: int = 3,
) -> dict[str, Any]:
    """Execute native transport then reuse the durable collector unchanged."""
    planned = build_transport_plan(
        channel, publication, access_attestation, graph_version=graph_version
    )
    if planned.get("status") != "TRANSPORT_PLANNED":
        return planned
    plan = planned["plan"]
    fetched = fetch_provider_payload(plan, credential_value, http_get=http_get)
    if fetched.get("status") != "OBSERVED_PAYLOAD_READY":
        result = _clone(fetched)
        result.update({
            "schema_version": SCHEMA_VERSION,
            "transport_id": TRANSPORT_ID,
            "instance_id": plan.get("instance_id"),
            "channel_id": plan.get("channel_id"),
            "platform": plan.get("platform"),
        })
        return result

    now_dt = _iso(now)
    published_dt = _iso(_clean(publication.get("published_at")))
    if now_dt < published_dt:
        return {
            "schema_version": SCHEMA_VERSION,
            "transport_id": TRANSPORT_ID,
            "status": "HOLD_TRANSPORT",
            "hard_blocks": ["OBSERVATION_PRECEDES_PUBLICATION"],
            "publication_blocked": False,
        }
    observed_at = now_dt.isoformat().replace("+00:00", "Z")
    window_start = published_dt.isoformat().replace("+00:00", "Z")
    bundle = observed_metrics_collector.materialize_bundle(
        channel,
        publication,
        fetched["provider_payload"],
        source=plan["source"],
        observed_at=observed_at,
        collected_at=observed_at,
        window_start_at=window_start,
        window_end_at=observed_at,
        now=observed_at,
        existing_store=existing_store,
        existing_snapshot=existing_snapshot,
        ttl_hours=ttl_hours,
        min_samples=min_samples,
    )
    result = {
        "schema_version": SCHEMA_VERSION,
        "transport_id": TRANSPORT_ID,
        "status": "COLLECTED_AND_MATERIALIZED" if not bundle.get("hard_blocks") else "HOLD_OBSERVATION",
        "instance_id": plan.get("instance_id"),
        "channel_id": plan.get("channel_id"),
        "platform": plan.get("platform"),
        "source": plan.get("source"),
        "metric_issues": fetched.get("metric_issues", []),
        "publication_blocked": False,
        "materialization": bundle,
        "guards": {
            "credential_value_returned": False,
            "raw_provider_payload_persisted_by_transport": False,
            "publication_blocked_by_analytics": False,
            "zero_paid_dependency": True,
        },
    }
    return result


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_optional(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return _load_object(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channel", type=Path)
    parser.add_argument("publication", type=Path)
    parser.add_argument("access_attestation", type=Path)
    parser.add_argument("--now", required=True)
    parser.add_argument("--graph-version", default=DEFAULT_GRAPH_VERSION)
    parser.add_argument("--existing-store", type=Path)
    parser.add_argument("--existing-snapshot", type=Path)
    parser.add_argument("--persist-root", type=Path)
    parser.add_argument("--dry-plan", action="store_true")
    args = parser.parse_args()

    channel = _load_object(args.channel)
    publication = _load_object(args.publication)
    attestation = _load_object(args.access_attestation)
    planned = build_transport_plan(channel, publication, attestation, graph_version=args.graph_version)
    if args.dry_plan or planned.get("status") != "TRANSPORT_PLANNED":
        print(json.dumps(planned, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if planned.get("status") == "TRANSPORT_PLANNED" else 2

    env_name = planned["plan"]["credential_env_name"]
    credential = os.environ.get(env_name, "")
    result = collect_and_materialize(
        channel,
        publication,
        attestation,
        credential,
        now=args.now,
        existing_store=_load_optional(args.existing_store),
        existing_snapshot=_load_optional(args.existing_snapshot),
        graph_version=args.graph_version,
    )
    materialization = result.get("materialization")
    if args.persist_root and isinstance(materialization, dict) and not materialization.get("hard_blocks"):
        materialization["persistence_result"] = observed_metrics_collector.persist_bundle(args.persist_root, materialization)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if result.get("status") in {"COLLECTED_AND_MATERIALIZED", "NO_OBSERVED_METRICS", "RETRY_LATER"}:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
