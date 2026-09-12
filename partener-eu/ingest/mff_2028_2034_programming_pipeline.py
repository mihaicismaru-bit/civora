#!/usr/bin/env python3
"""Canonical, fail-closed MFF 2028-2034 programming intelligence.

Only official EU programming/proposal authorities are observed. This adapter
never authorizes a funding-call status, deadline, budget, eligibility,
publication, distribution, alert, or canonical opportunity mutation.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import pathlib
import re
import ssl
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any, Callable, Mapping

SCHEMA = "PARTENER_EU_MFF_2028_2034_PROGRAMMING_PIPELINE_V2"
PARSER_VERSION = "MFF_2028_2034_PROGRAMMING_PIPELINE_V2"
REGISTRY_SCHEMA = "PARTENER_EU_MFF_2028_2034_PROGRAMMING_PIPELINE_REGISTRY_V2"
SOURCE_FAMILY = "PROGRAMMING_PIPELINE"
PROGRAMME_FAMILY = "MFF_2028_2034"
PROGRAMME_PERIOD = "2028-2034"
ALLOWED_STATES = {"PROPOSAL", "CONSULTATION", "PLANNED", "PROGRAMMING_PROCESS"}
MAX_BYTES = 3_000_000
MATERIAL_FLAGS = (
    "material_fact_use", "open_call_authorized", "closed_call_authorized",
    "deadline_authorized", "budget_authorized", "eligibility_authorized",
    "publish_authorized", "distribution_authorized", "call_alert_authorized",
    "canonical_corpus_mutation",
)
MISSING_FOR_OPEN = (
    "exact_call_or_topic_identifier",
    "current_official_exact_call_endpoint",
    "explicit_current_official_call_status",
    "same_identity_semantic_reconciliation",
    "field_scoped_material_admission",
)


class VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style", "noscript", "svg"}:
            self.suppressed += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript", "svg"}:
            self.suppressed = max(0, self.suppressed - 1)

    def handle_data(self, data: str) -> None:
        if not self.suppressed:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("MFF timestamps must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def normal(value: str) -> str:
    text = html.unescape(value or "").casefold()
    return re.sub(r"\s+", " ", text).strip()


def visible_text(raw: bytes) -> str:
    parser = VisibleText()
    parser.feed(raw.decode("utf-8", errors="replace"))
    return normal(" ".join(parser.parts))


def _allowed_hosts(source: Mapping[str, Any]) -> set[str]:
    return {str(x).casefold() for x in source.get("allowed_hosts") or []}


def load_registry(path: pathlib.Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    registry = json.loads(raw.decode("utf-8"))
    if registry.get("schema") != REGISTRY_SCHEMA:
        raise ValueError("MFF programming registry schema drift")
    if registry.get("source_family") != SOURCE_FAMILY or registry.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("MFF programming registry family drift")
    if registry.get("programme_period") != PROGRAMME_PERIOD:
        raise ValueError("MFF programming registry period drift")
    checked = dt.date.fromisoformat(str(registry.get("evidence_checked_date") or ""))
    if checked > dt.datetime.now(dt.timezone.utc).date():
        raise ValueError("MFF registry evidence date is in the future")
    policy = registry.get("policy") or {}
    if policy.get("market_intelligence_only") is not True or policy.get("fit_is_not_eligibility") is not True:
        raise ValueError("MFF registry market-intelligence boundary drift")
    for flag in MATERIAL_FLAGS:
        if policy.get(flag) is not False:
            raise ValueError(f"MFF registry attempted material authorization: {flag}")
    for key in (
        "exact_call_or_topic_identifier_required_for_open",
        "current_official_exact_call_endpoint_required_for_open",
        "semantic_reconciliation_required_for_material_change",
        "field_scoped_material_admission_required",
    ):
        if policy.get(key) is not True:
            raise ValueError(f"MFF registry relaxed hard gate: {key}")
    sources = registry.get("sources") or []
    if len(sources) < 8:
        raise ValueError("MFF programming coverage unexpectedly small")
    ids: set[str] = set()
    for source in sources:
        sid = str(source.get("source_id") or "")
        if not sid or sid in ids:
            raise ValueError("MFF source identity missing or duplicate")
        ids.add(sid)
        if source.get("observation_state") not in ALLOWED_STATES:
            raise ValueError(f"MFF source observation state is not programming-only: {sid}")
        parsed = urllib.parse.urlparse(str(source.get("authority_url") or ""))
        hosts = _allowed_hosts(source)
        if parsed.scheme != "https" or not hosts or (parsed.hostname or "").casefold() not in hosts:
            raise ValueError(f"MFF official authority drift: {sid}")
        if not source.get("authority_class") or not source.get("semantic_basis"):
            raise ValueError(f"MFF source provenance metadata missing: {sid}")
        if not source.get("markers_all") or not source.get("markers_any"):
            raise ValueError(f"MFF source marker policy missing: {sid}")
        if not source.get("market_signals") or not source.get("applicant_fit_tags") or not source.get("geography_tags"):
            raise ValueError(f"MFF market/fit/geography intelligence missing: {sid}")
    return registry, sha256_bytes(raw)


def default_fetch(url: str, timeout: float = 25.0) -> tuple[bytes, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "PARTENER.EU-MFFProgramming/2.0 (+https://partener.eu)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.1",
            "Accept-Language": "en",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
        raw = response.read(MAX_BYTES + 1)
        meta = {
            "requested_url": url,
            "final_url": str(response.geturl()),
            "status": int(getattr(response, "status", 200) or 200),
            "content_type": str(response.headers.get("Content-Type") or ""),
        }
    if len(raw) > MAX_BYTES:
        raise ValueError("official MFF programming source exceeded bounded size")
    return raw, meta


def classify_failure(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}".casefold()
    if "certificate verify failed" in text:
        return "TLS_CERTIFICATE_VERIFY_FAILED"
    if "timed out" in text or "timeout" in text:
        return "TIMEOUT"
    if "http error" in text or "httperror" in text:
        return "HTTP_ERROR"
    if isinstance(exc, ValueError):
        return "VALIDATION_ERROR"
    return "TRANSPORT_ERROR"


def verify_markers(text: str, source: Mapping[str, Any]) -> None:
    hay = normal(text)
    missing_all = [str(x) for x in source.get("markers_all") or [] if normal(str(x)) not in hay]
    any_group = [normal(str(x)) for x in source.get("markers_any") or []]
    if missing_all:
        raise ValueError(f"{source['source_id']} missing required markers: {missing_all}")
    if any_group and not any(marker in hay for marker in any_group):
        raise ValueError(f"{source['source_id']} missing any-of marker group")


def romania_relevance_score(source: Mapping[str, Any]) -> float:
    geography = set(source.get("geography_tags") or [])
    fit = set(source.get("applicant_fit_tags") or [])
    score = 0.45
    if "ROMANIA" in fit:
        score += 0.15
    if "ROMANIA_RELEVANT" in geography:
        score += 0.15
    if "ROMANIA_HIGH_RELEVANCE" in geography:
        score += 0.25
    if "INTERREG_RELEVANT" in geography:
        score += 0.10
    return round(min(1.0, score), 2)


def acquire(
    registry: Mapping[str, Any], *, run_id: str, fetched_at: str | None = None,
    fetcher: Callable[[str], tuple[bytes, dict[str, Any]]] = default_fetch,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    observed = fetched_at or utc_now()
    parse_time(observed)
    rows: list[dict[str, Any]] = []
    raw_by_id: dict[str, bytes] = {}
    for source in registry.get("sources") or []:
        sid = str(source["source_id"])
        url = str(source["authority_url"])
        base: dict[str, Any] = {
            "source_id": sid,
            "programme": source["programme"],
            "programme_tags": list(source.get("programme_tags") or []),
            "authority_class": source["authority_class"],
            "authority_url": url,
            "observation_state": source["observation_state"],
            "legislative_identifier": source.get("legislative_identifier"),
            "procedure_identifier": source.get("procedure_identifier"),
            "semantic_basis": source["semantic_basis"],
            "market_signals": sorted(set(source.get("market_signals") or [])),
            "applicant_fit_tags": sorted(set(source.get("applicant_fit_tags") or [])),
            "geography_tags": sorted(set(source.get("geography_tags") or [])),
            "romania_relevance_score": romania_relevance_score(source),
            "fit_is_not_eligibility": True,
            "market_intelligence_only": True,
            "fetched_at": observed,
            "missing_for_open_confirmation": list(MISSING_FOR_OPEN),
            "publication_effect": "NONE",
        }
        for flag in MATERIAL_FLAGS:
            base[flag] = False
        try:
            raw, meta = fetcher(url)
            final_url = str(meta.get("final_url") or url)
            host = (urllib.parse.urlparse(final_url).hostname or "").casefold()
            content_type = str(meta.get("content_type") or "")
            if int(meta.get("status") or 0) != 200:
                raise ValueError(f"{sid} returned non-200 authority response")
            if host not in _allowed_hosts(source):
                raise ValueError(f"{sid} redirected outside official authority")
            if not any(token in content_type.casefold() for token in ("html", "text/plain")):
                raise ValueError(f"{sid} unexpected content type: {content_type}")
            text = visible_text(raw)
            verify_markers(text, source)
            raw_hash = sha256_bytes(raw)
            visible_hash = sha256_bytes(text.encode("utf-8"))
            semantic_basis = {
                "source_id": sid,
                "programme": source["programme"],
                "programme_tags": sorted(set(source.get("programme_tags") or [])),
                "authority_class": source["authority_class"],
                "authority_url": url,
                "observation_state": source["observation_state"],
                "legislative_identifier": source.get("legislative_identifier"),
                "procedure_identifier": source.get("procedure_identifier"),
                "market_signals": sorted(set(source.get("market_signals") or [])),
                "applicant_fit_tags": sorted(set(source.get("applicant_fit_tags") or [])),
                "geography_tags": sorted(set(source.get("geography_tags") or [])),
                "normalized_visible_text_sha256": visible_hash,
            }
            row = {
                **base,
                "source_health": "HEALTHY",
                "lkg_required": False,
                "requested_url": str(meta.get("requested_url") or url),
                "final_url": final_url,
                "http_status": int(meta.get("status") or 200),
                "content_type": content_type,
                "raw_size_bytes": len(raw),
                "raw_sha256": raw_hash,
                "normalized_visible_text_sha256": visible_hash,
                "source_semantic_fingerprint": sha256_json(semantic_basis),
                "error_type": None,
                "error": None,
            }
            raw_by_id[sid] = raw
        except Exception as exc:
            row = {
                **base,
                "source_health": "DEGRADED",
                "lkg_required": True,
                "requested_url": url,
                "final_url": None,
                "http_status": None,
                "content_type": None,
                "raw_size_bytes": 0,
                "raw_sha256": None,
                "normalized_visible_text_sha256": None,
                "source_semantic_fingerprint": None,
                "error_type": classify_failure(exc),
                "error": f"{type(exc).__name__}: {exc}",
            }
        rows.append(row)

    healthy = sum(row["source_health"] == "HEALTHY" for row in rows)
    degraded = len(rows) - healthy
    source_health_state = "HEALTHY" if degraded == 0 else "DEGRADED"
    semantic_basis = {
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "programme_period": PROGRAMME_PERIOD,
        "source_semantic_fingerprints": [row["source_semantic_fingerprint"] for row in rows],
        "observation_states": sorted({row["observation_state"] for row in rows}),
        "market_signals": sorted({x for row in rows for x in row["market_signals"]}),
        "applicant_fit_tags": sorted({x for row in rows for x in row["applicant_fit_tags"]}),
        "geography_tags": sorted({x for row in rows for x in row["geography_tags"]}),
    }
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "programme_period": PROGRAMME_PERIOD,
        "authority_class": "OFFICIAL_EU_PROGRAMMING_AUTHORITIES",
        "observation_state": "PROGRAMMING_PIPELINE",
        "run_id": run_id,
        "fetched_at": observed,
        "registry_sha256": sha256_json(registry),
        "source_count": len(rows),
        "healthy_source_count": healthy,
        "degraded_source_count": degraded,
        "source_health_state": source_health_state,
        "sources": rows,
        "semantic_fingerprint": sha256_json(semantic_basis) if degraded == 0 else None,
        "market_signals": semantic_basis["market_signals"],
        "applicant_fit_tags": semantic_basis["applicant_fit_tags"],
        "geography_tags": semantic_basis["geography_tags"],
        "fit_is_not_eligibility": True,
        "market_intelligence_only": True,
        "lkg_required": degraded > 0,
        "missing_for_open_confirmation": list(MISSING_FOR_OPEN),
        "publication_effect": "NONE",
    }
    for flag in MATERIAL_FLAGS:
        result[flag] = False
    validate_snapshot(result, registry=registry)
    return result, raw_by_id


def identity(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_family": snapshot.get("source_family"),
        "programme_family": snapshot.get("programme_family"),
        "programme_period": snapshot.get("programme_period"),
        "source_inventory": sorted(
            (
                str(row.get("source_id") or ""),
                str(row.get("authority_url") or ""),
                str(row.get("observation_state") or ""),
            )
            for row in snapshot.get("sources") or []
        ),
    }


def validate_snapshot(snapshot: Mapping[str, Any], *, registry: Mapping[str, Any] | None = None) -> None:
    if snapshot.get("schema") != SCHEMA or snapshot.get("parser_version") != PARSER_VERSION:
        raise ValueError("MFF canonical snapshot schema/parser drift")
    if snapshot.get("source_family") != SOURCE_FAMILY or snapshot.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("MFF canonical snapshot family drift")
    if snapshot.get("programme_period") != PROGRAMME_PERIOD or snapshot.get("observation_state") != "PROGRAMMING_PIPELINE":
        raise ValueError("MFF canonical programme/observation drift")
    rows = snapshot.get("sources") or []
    if not rows or len(rows) != int(snapshot.get("source_count") or 0):
        raise ValueError("MFF canonical source count drift")
    if registry is not None:
        expected = sorted((x["source_id"], x["authority_url"], x["observation_state"]) for x in registry.get("sources") or [])
        if identity(snapshot)["source_inventory"] != expected:
            raise ValueError("MFF canonical source identity differs from registry")
    healthy = sum(row.get("source_health") == "HEALTHY" for row in rows)
    degraded = len(rows) - healthy
    if healthy != int(snapshot.get("healthy_source_count") or 0) or degraded != int(snapshot.get("degraded_source_count") or 0):
        raise ValueError("MFF canonical source health accounting drift")
    expected_state = "HEALTHY" if degraded == 0 else "DEGRADED"
    if snapshot.get("source_health_state") != expected_state or snapshot.get("lkg_required") is not (degraded > 0):
        raise ValueError("MFF canonical aggregate health/LKG drift")
    for row in rows:
        if row.get("observation_state") not in ALLOWED_STATES:
            raise ValueError("MFF canonical source crossed programming-only boundary")
        if row.get("source_health") == "HEALTHY":
            if row.get("http_status") != 200 or row.get("lkg_required") is not False:
                raise ValueError("healthy MFF source receipt inconsistent")
            for key in ("raw_sha256", "normalized_visible_text_sha256", "source_semantic_fingerprint"):
                if not re.fullmatch(r"[0-9a-f]{64}", str(row.get(key) or "")):
                    raise ValueError(f"healthy MFF source missing {key}")
        elif row.get("source_health") == "DEGRADED":
            if row.get("lkg_required") is not True or row.get("source_semantic_fingerprint") is not None:
                raise ValueError("degraded MFF source weakened fail-closed state")
        else:
            raise ValueError("unexpected MFF source health state")
        if row.get("fit_is_not_eligibility") is not True or row.get("market_intelligence_only") is not True:
            raise ValueError("MFF source fit/market boundary weakened")
        for flag in MATERIAL_FLAGS:
            if row.get(flag) is not False:
                raise ValueError(f"MFF source attempted authorization: {flag}")
    if degraded == 0:
        if not re.fullmatch(r"[0-9a-f]{64}", str(snapshot.get("semantic_fingerprint") or "")):
            raise ValueError("healthy MFF snapshot semantic fingerprint missing")
    elif snapshot.get("semantic_fingerprint") is not None:
        raise ValueError("degraded MFF snapshot emitted semantic fingerprint")
    if snapshot.get("fit_is_not_eligibility") is not True or snapshot.get("market_intelligence_only") is not True:
        raise ValueError("MFF aggregate market boundary weakened")
    if snapshot.get("publication_effect") != "NONE":
        raise ValueError("MFF snapshot crossed publication boundary")
    for flag in MATERIAL_FLAGS:
        if snapshot.get(flag) is not False:
            raise ValueError(f"MFF snapshot attempted authorization: {flag}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", required=True, type=pathlib.Path)
    ap.add_argument("--output-dir", required=True, type=pathlib.Path)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--fetched-at")
    args = ap.parse_args()
    registry, _ = load_registry(args.registry)
    snapshot, raws = acquire(registry, run_id=args.run_id, fetched_at=args.fetched_at)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "mff-2028-2034-programming-pipeline.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    raw_dir = args.output_dir / "raw"
    raw_dir.mkdir(exist_ok=True)
    for sid, raw in raws.items():
        (raw_dir / f"{sid}.html").write_bytes(raw)
    print(json.dumps({
        "source_count": snapshot["source_count"],
        "healthy_source_count": snapshot["healthy_source_count"],
        "degraded_source_count": snapshot["degraded_source_count"],
        "source_health_state": snapshot["source_health_state"],
        "semantic_fingerprint": snapshot["semantic_fingerprint"],
        "open_call_authorized": False,
        "publication_effect": "NONE",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
