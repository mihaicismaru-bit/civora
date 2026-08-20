from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence
from urllib.parse import urlsplit, urlunsplit

from adapters.civora_provider import DiscoveryProvider


DEFAULT_SOURCE_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / "ingest" / "state" / "source_registry_health.json"
)


class PartenerSourceRegistryError(RuntimeError):
    """Raised when the canonical PARTENER.EU source-health snapshot is unusable."""


def _parse_utc(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
    except ValueError:
        return text.rstrip("/")
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if not scheme or not host:
        return text.rstrip("/")
    port = parts.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def load_source_registry(path: Path | str = DEFAULT_SOURCE_REGISTRY_PATH) -> Dict[str, Any]:
    registry_path = Path(path)
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PartenerSourceRegistryError(f"source_registry_unreadable:{registry_path}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
        raise PartenerSourceRegistryError("source_registry_missing_sources_list")
    if not payload.get("observed_at"):
        raise PartenerSourceRegistryError("source_registry_missing_observed_at")
    return payload


def _registry_snapshot_failures(
    registry: Mapping[str, Any],
    *,
    now: Optional[datetime] = None,
    max_age_hours: float = 6.0,
) -> list[str]:
    failures: list[str] = []
    observed_at = _parse_utc(registry.get("observed_at"))
    if observed_at is None:
        return ["registry_observed_at_invalid"]
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    age_seconds = (current - observed_at).total_seconds()
    if age_seconds < -300:
        failures.append("registry_snapshot_from_future")
    if age_seconds > max_age_hours * 3600:
        failures.append("registry_snapshot_stale")
    return failures


def _match_registry_source(
    receipt: Mapping[str, Any], registry: Mapping[str, Any]
) -> Optional[Mapping[str, Any]]:
    sources = [item for item in registry.get("sources", []) if isinstance(item, Mapping)]
    explicit_id = str(receipt.get("source_registry_id") or "").strip()
    if explicit_id:
        return next((item for item in sources if str(item.get("id")) == explicit_id), None)

    candidate_urls = {
        _normalize_url(receipt.get("final_url")),
        _normalize_url(receipt.get("source_url")),
    }
    candidate_urls.discard("")
    if not candidate_urls:
        return None
    for item in sources:
        registry_urls = {
            _normalize_url(item.get("final_url")),
            _normalize_url(item.get("url")),
        }
        registry_urls.discard("")
        if candidate_urls.intersection(registry_urls):
            return item
    return None


def reconcile_receipt_with_source_registry(
    receipt: Mapping[str, Any],
    registry: Mapping[str, Any],
    *,
    now: Optional[datetime] = None,
    max_registry_age_hours: float = 6.0,
) -> Dict[str, Any]:
    """Reconcile provider claims against PARTENER.EU's canonical source-health snapshot.

    The provider remains responsible for discovery and document-level provenance.
    This gate only authorizes whether a returned receipt may proceed to Needs Factory
    evidence validation. Unknown, stale, quarantined, low-quality or
    reconciliation-pending sources fail closed.
    """

    output = dict(receipt)
    failures = _registry_snapshot_failures(
        registry, now=now, max_age_hours=max_registry_age_hours
    )
    source = _match_registry_source(receipt, registry)
    registry_provenance: Dict[str, Any] = {}
    if source is None:
        failures.append("unregistered_source")
        output["source_registry_id"] = None
    else:
        output["source_registry_id"] = source.get("id")
        if source.get("health") != "PASS" or source.get("ok") is not True:
            failures.append("registry_health_not_pass")
        if source.get("quarantined") is True:
            failures.append("registry_source_quarantined")
        if source.get("content_quality_ok") is not True:
            failures.append("registry_content_quality_not_ok")
        if source.get("resolution_task_required") is True:
            failures.append("registry_resolution_required")
        if source.get("material_fact_use") is True and source.get("semantic_hash_changed") is True:
            failures.append("material_fact_reconciliation_required")
        registry_provenance = {
            "registry_url": source.get("url"),
            "registry_final_url": source.get("final_url"),
            "registry_tier": source.get("tier"),
            "registry_class": source.get("class"),
            "registry_raw_sha256": source.get("raw_sha256"),
            "registry_semantic_sha256": source.get("semantic_sha256"),
        }

    failures = sorted(set(failures))
    if failures:
        output["health"] = "FAIL"
        output["quarantined"] = True
        output["material_fact_state"] = "BLOCKED_BY_PARTENER_SOURCE_GATE"
    else:
        output["health"] = "PASS"
        output["quarantined"] = False
        output["material_fact_state"] = "PARTENER_REGISTRY_VERIFIED"

    output["source_registry_gate"] = {
        "schema_version": "nf.partener_source_gate.v0.1",
        "registry_schema_version": registry.get("schema_version"),
        "registry_observed_at": registry.get("observed_at"),
        "source_registry_id": output.get("source_registry_id"),
        "valid": not failures,
        "failures": failures,
        "policy": "fail_closed_no_unregistered_or_unhealthy_evidence",
        **registry_provenance,
    }
    return output


class PartenerSourceGateProvider:
    """DiscoveryProvider decorator backed by PARTENER.EU's live source registry.

    It deliberately does not crawl or discover anything itself, preserving the
    existing CIVORA/PARTENER control plane. Provider exceptions are not swallowed.
    """

    def __init__(
        self,
        provider: DiscoveryProvider,
        *,
        registry_path: Path | str = DEFAULT_SOURCE_REGISTRY_PATH,
        max_registry_age_hours: float = 6.0,
        now_provider: Optional[Callable[[], datetime]] = None,
    ) -> None:
        if max_registry_age_hours <= 0:
            raise ValueError("max_registry_age_hours must be positive")
        self.provider = provider
        self.registry_path = Path(registry_path)
        self.max_registry_age_hours = max_registry_age_hours
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self.registry = load_source_registry(self.registry_path)

    def discover(self, task: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        receipts = self.provider.discover(task)
        now = self.now_provider()
        return [
            reconcile_receipt_with_source_registry(
                receipt,
                self.registry,
                now=now,
                max_registry_age_hours=self.max_registry_age_hours,
            )
            for receipt in receipts
        ]
