#!/usr/bin/env python3
"""Fail-closed official watch for EU-direct programming under the 2028-2034 MFF.

Commission/EUR-Lex programming and legislative-proposal evidence only. Nothing
in this layer can authorize OPEN/CLOSED, deadline, budget, eligibility,
publication, distribution, alerts, or canonical opportunity mutation.
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
import unicodedata
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any, Callable, Mapping

SCHEMA = "PARTENER_EU_EU_DIRECT_MFF_2028_2034_PROGRAMMING_WATCH_V1"
PARSER_VERSION = "EU_DIRECT_MFF_2028_2034_PROGRAMMING_WATCH_V1"
RECONCILIATION_SCHEMA = "PARTENER_EU_EU_DIRECT_MFF_2028_2034_PROGRAMMING_RECONCILIATION_V1"
SOURCE_FAMILY = "PROGRAMMING_PIPELINE"
PROGRAMME_FAMILY = "EU_DIRECT_2028_2034"
PROGRAMME_PERIOD = "2028-2034"
ALLOWED_HOSTS = {"commission.europa.eu", "eur-lex.europa.eu"}
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


class TextProbe(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style", "noscript"}:
            self.suppressed += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript"}:
            self.suppressed = max(0, self.suppressed - 1)

    def handle_data(self, data: str) -> None:
        if not self.suppressed:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def normal(value: str) -> str:
    text = html.unescape(value or "").casefold()
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


def html_text(raw: bytes) -> str:
    probe = TextProbe()
    probe.feed(raw.decode("utf-8", errors="replace"))
    return " ".join(probe.parts)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def load_registry(path: pathlib.Path) -> dict[str, Any]:
    registry = json.loads(path.read_text(encoding="utf-8"))
    if registry.get("schema") != "PARTENER_EU_EU_DIRECT_MFF_2028_2034_PROGRAMMING_REGISTRY_V1":
        raise ValueError("MFF registry schema drift")
    if registry.get("source_family") != SOURCE_FAMILY or registry.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("MFF registry family drift")
    if registry.get("programme_period") != PROGRAMME_PERIOD:
        raise ValueError("MFF registry period drift")
    policy = registry.get("policy") or {}
    for flag in MATERIAL_FLAGS:
        if policy.get(flag) is not False:
            raise ValueError(f"MFF registry attempted material authorization: {flag}")
    required_true = (
        "exact_call_or_topic_identifier_required_for_open",
        "current_official_exact_call_endpoint_required_for_open",
        "semantic_reconciliation_required_for_material_change",
        "field_scoped_material_admission_required",
    )
    if not all(policy.get(key) is True for key in required_true):
        raise ValueError("MFF registry relaxed a hard admission requirement")
    sources = registry.get("sources")
    if not isinstance(sources, list) or len(sources) < 4:
        raise ValueError("MFF registry coverage unexpectedly small")
    ids: set[str] = set()
    for source in sources:
        sid = str(source.get("source_id") or "")
        if not sid or sid in ids:
            raise ValueError("MFF registry source identity missing/duplicate")
        ids.add(sid)
        parsed = urllib.parse.urlparse(str(source.get("authority_url") or ""))
        if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in ALLOWED_HOSTS:
            raise ValueError(f"MFF registry authority drift: {sid}")
        if source.get("observation_state") not in {"PROPOSAL", "CONSULTATION", "PLANNED", "PROGRAMMING_PROCESS"}:
            raise ValueError(f"MFF registry illegal observation state: {sid}")
    return registry


def default_fetch(url: str, timeout: float = 30.0) -> tuple[bytes, dict[str, Any]]:
    req = urllib.request.Request(url, headers={
        "User-Agent": "PARTENER.EU-programming-watch/1.0 (+https://partener.eu)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en",
    })
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as response:
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("official programming source exceeds bounded size")
        meta = {
            "requested_url": url,
            "final_url": str(response.geturl()),
            "status": int(getattr(response, "status", 200) or 200),
            "content_type": str(response.headers.get("Content-Type") or ""),
        }
    if meta["status"] != 200:
        raise ValueError(f"official programming source returned HTTP {meta['status']}")
    return raw, meta


def classify_failure(exc: Exception) -> str:
    msg = f"{type(exc).__name__}: {exc}".casefold()
    if "certificate verify failed" in msg:
        return "TLS_CERTIFICATE_VERIFY_FAILED"
    if "timed out" in msg or "timeout" in msg:
        return "TIMEOUT"
    if "http error" in msg or "httperror" in msg:
        return "HTTP_ERROR"
    if isinstance(exc, ValueError):
        return "VALIDATION_ERROR"
    return "TRANSPORT_ERROR"


def verify_markers(text: str, source: Mapping[str, Any]) -> None:
    hay = normal(text)
    missing = [x for x in source.get("markers_all", []) if normal(str(x)) not in hay]
    any_markers = [normal(str(x)) for x in source.get("markers_any", [])]
    if missing:
        raise ValueError(f"{source['source_id']} missing required markers: {missing}")
    if any_markers and not any(x in hay for x in any_markers):
        raise ValueError(f"{source['source_id']} missing any-of marker group")


def procedure_state(text: str) -> str:
    hay = normal(text)
    ongoing = ("ongoing", "en cours", "in corso", "laufend", "in behandeling", "w toku", "em curso", "în curs")
    completed = ("completed", "terminée", "concluso", "abgeschlossen", "zakończona", "concluído", "finalizată")
    if any(marker in hay for marker in ongoing):
        return "ONGOING"
    if any(marker in hay for marker in completed):
        return "COMPLETED"
    return "UNKNOWN_NON_AUTHORIZING"


def collect(
    registry: Mapping[str, Any], *, run_id: str, fetched_at: str | None = None,
    fetcher: Callable[[str], tuple[bytes, dict[str, Any]]] = default_fetch,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    observed = fetched_at or utc_now()
    evidence: list[dict[str, Any]] = []
    raw_by_id: dict[str, bytes] = {}
    for source in registry["sources"]:
        sid, url = source["source_id"], source["authority_url"]
        base: dict[str, Any] = {
            "source_id": sid,
            "programme": source["programme"],
            "programme_tags": source.get("programme_tags") or [],
            "authority_class": source["authority_class"],
            "authority_url": url,
            "observation_state": source["observation_state"],
            "legislative_identifier": source.get("legislative_identifier"),
            "procedure_identifier": source.get("procedure_identifier"),
            "semantic_basis": source["semantic_basis"],
            "market_intelligence_only": True,
            "publication_effect": "NONE",
            "missing_for_open_confirmation": list(MISSING_FOR_OPEN),
        }
        for flag in MATERIAL_FLAGS:
            base[flag] = False
        try:
            raw, meta = fetcher(url)
            final_url = str(meta.get("final_url") or meta.get("requested_url") or url)
            host = (urllib.parse.urlparse(final_url).hostname or "").casefold()
            if int(meta.get("status") or 0) != 200 or host not in ALLOWED_HOSTS:
                raise ValueError(f"{sid} left official authority or returned non-200")
            ctype = str(meta.get("content_type") or "")
            if "html" not in ctype.casefold():
                raise ValueError(f"{sid} unexpected content type: {ctype}")
            text = html_text(raw)
            verify_markers(text, source)
            raw_by_id[sid] = raw
            semantics = {
                "source_id": sid,
                "programme": source["programme"],
                "observation_state": source["observation_state"],
                "legislative_identifier": source.get("legislative_identifier"),
                "procedure_identifier": source.get("procedure_identifier"),
                "procedure_state": procedure_state(text) if source.get("procedure_identifier") else None,
                "proposal_stage": "COMMISSION_PROPOSAL_PRESENTED" if sid == "MFF-2028-2034-COMMISSION-ROOT" else None,
                "programme_period": PROGRAMME_PERIOD,
            }
            evidence.append({
                **base,
                "source_health": {
                    "health_state": "HEALTHY", "lkg_required": False,
                    "requested_url": str(meta.get("requested_url") or url), "final_url": final_url,
                    "http_status": int(meta.get("status") or 200), "content_type": ctype,
                    "raw_size_bytes": len(raw), "raw_sha256": sha256_bytes(raw),
                    "error_type": None, "error": None,
                },
                "semantic_fingerprint": sha256_json(semantics), "semantics": semantics,
            })
        except Exception as exc:
            evidence.append({
                **base,
                "source_health": {
                    "health_state": "DEGRADED", "lkg_required": True,
                    "requested_url": url, "final_url": None, "http_status": None,
                    "content_type": None, "raw_size_bytes": 0, "raw_sha256": None,
                    "error_type": classify_failure(exc), "error": f"{type(exc).__name__}: {exc}",
                },
                "semantic_fingerprint": None, "semantics": None,
            })
    healthy = sum(row["source_health"]["health_state"] == "HEALTHY" for row in evidence)
    semantics = [row["semantics"] for row in evidence if row["semantics"] is not None]
    snapshot: dict[str, Any] = {
        "schema": SCHEMA, "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY, "programme_family": PROGRAMME_FAMILY,
        "programme_period": PROGRAMME_PERIOD, "authority_class": "OFFICIAL_EU_COMMISSION_AND_EUR_LEX",
        "observation_state": "PROGRAMMING_PIPELINE", "run_id": run_id, "fetched_at": observed,
        "registry_sha256": sha256_json(registry), "source_count": len(evidence),
        "healthy_source_count": healthy, "degraded_source_count": len(evidence) - healthy,
        "source_health": "HEALTHY" if healthy == len(evidence) else "DEGRADED",
        "evidence": evidence, "semantic_fingerprint": sha256_json(semantics),
        "market_intelligence_only": True, "publication_effect": "NONE",
        "missing_for_open_confirmation": list(MISSING_FOR_OPEN),
    }
    for flag in MATERIAL_FLAGS:
        snapshot[flag] = False
    validate_snapshot(snapshot, registry=registry)
    return snapshot, raw_by_id


def validate_snapshot(snapshot: Mapping[str, Any], *, registry: Mapping[str, Any]) -> None:
    if snapshot.get("schema") != SCHEMA or snapshot.get("parser_version") != PARSER_VERSION:
        raise ValueError("MFF watch schema/parser drift")
    if snapshot.get("source_family") != SOURCE_FAMILY or snapshot.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("MFF watch family drift")
    if snapshot.get("observation_state") != "PROGRAMMING_PIPELINE" or snapshot.get("source_count") != len(registry["sources"]):
        raise ValueError("MFF watch observation/source inventory drift")
    validate_snapshot_integrity(snapshot)
    for row in snapshot.get("evidence") or []:
        health = row.get("source_health") or {}
        if health.get("health_state") == "HEALTHY":
            if health.get("http_status") != 200 or not re.fullmatch(r"[0-9a-f]{64}", str(health.get("raw_sha256") or "")):
                raise ValueError("healthy MFF source lacks valid receipt")
        elif health.get("health_state") != "DEGRADED":
            raise ValueError("unexpected MFF source health")


def validate_snapshot_integrity(snapshot: Mapping[str, Any]) -> None:
    if snapshot.get("schema") != SCHEMA or snapshot.get("parser_version") != PARSER_VERSION:
        raise ValueError("MFF snapshot identity drift")
    if snapshot.get("source_family") != SOURCE_FAMILY or snapshot.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("MFF snapshot family drift")
    if snapshot.get("programme_period") != PROGRAMME_PERIOD or snapshot.get("observation_state") != "PROGRAMMING_PIPELINE":
        raise ValueError("MFF snapshot programme/observation drift")
    rows = snapshot.get("evidence") or []
    seen: set[str] = set()
    for row in rows:
        sid = str(row.get("source_id") or "")
        if not sid or sid in seen:
            raise ValueError("MFF snapshot source identity missing/duplicate")
        seen.add(sid)
        for flag in MATERIAL_FLAGS:
            if row.get(flag) is not False:
                raise ValueError(f"MFF evidence attempted authorization: {flag}")
        semantics, fingerprint = row.get("semantics"), row.get("semantic_fingerprint")
        health = row.get("source_health") or {}
        if health.get("health_state") == "HEALTHY":
            if not isinstance(semantics, Mapping) or sha256_json(semantics) != fingerprint:
                raise ValueError("MFF healthy evidence semantic fingerprint mismatch")
        elif health.get("health_state") == "DEGRADED":
            if semantics is not None or fingerprint is not None or health.get("lkg_required") is not True:
                raise ValueError("MFF degraded evidence weakened fail-closed state")
        else:
            raise ValueError("MFF snapshot unexpected source health")
    if snapshot.get("semantic_fingerprint") != sha256_json([row["semantics"] for row in rows if row.get("semantics") is not None]):
        raise ValueError("MFF snapshot semantic fingerprint mismatch")
    for flag in MATERIAL_FLAGS:
        if snapshot.get(flag) is not False:
            raise ValueError(f"MFF snapshot attempted authorization: {flag}")
    if snapshot.get("publication_effect") != "NONE" or snapshot.get("market_intelligence_only") is not True:
        raise ValueError("MFF snapshot crossed non-authorizing boundary")


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("MFF timestamps must be timezone-aware")
    return parsed


def reconcile(current: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    validate_snapshot_integrity(current)
    changes: list[dict[str, Any]] = []
    if previous is None:
        state = "BASELINE_CAPTURED_NON_AUTHORIZING"
    else:
        validate_snapshot_integrity(previous)
        if parse_time(str(previous.get("fetched_at"))) > parse_time(str(current.get("fetched_at"))):
            raise ValueError("previous MFF snapshot is newer than current")
        before = {row["source_id"]: row.get("semantic_fingerprint") for row in previous.get("evidence") or []}
        after = {row["source_id"]: row.get("semantic_fingerprint") for row in current.get("evidence") or []}
        for sid in sorted(set(before) | set(after)):
            if before.get(sid) != after.get(sid):
                changes.append({"source_id": sid, "before": before.get(sid), "after": after.get(sid)})
        state = "NO_CHANGE" if not changes else "PROGRAMMING_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
    receipt: dict[str, Any] = {
        "schema": RECONCILIATION_SCHEMA, "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY, "programme_family": PROGRAMME_FAMILY,
        "programme_period": PROGRAMME_PERIOD, "current_run_id": current.get("run_id"),
        "previous_run_id": previous.get("run_id") if previous else None,
        "current_fetched_at": current.get("fetched_at"),
        "previous_fetched_at": previous.get("fetched_at") if previous else None,
        "reconciliation_state": state, "semantic_change_count": len(changes),
        "semantic_changes": changes, "pipeline_watch_candidate": bool(changes),
        "source_health_watch_candidate": current.get("degraded_source_count", 0) > 0,
        "market_intelligence_only": True, "publication_effect": "NONE",
    }
    for flag in MATERIAL_FLAGS:
        receipt[flag] = False
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True, type=pathlib.Path)
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--previous", type=pathlib.Path)
    args = parser.parse_args()
    registry = load_registry(args.registry)
    snapshot, raws = collect(registry, run_id=args.run_id)
    previous = json.loads(args.previous.read_text(encoding="utf-8")) if args.previous and args.previous.exists() else None
    reconciliation = reconcile(snapshot, previous)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "eu-direct-mff-2028-2034-programming-snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "eu-direct-mff-2028-2034-programming-reconciliation.json").write_text(
        json.dumps(reconciliation, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    raw_dir = args.output_dir / "raw"
    raw_dir.mkdir(exist_ok=True)
    for sid, raw in raws.items():
        (raw_dir / f"{sid}.html").write_bytes(raw)
    print(json.dumps({
        "source_count": snapshot["source_count"], "healthy_source_count": snapshot["healthy_source_count"],
        "degraded_source_count": snapshot["degraded_source_count"],
        "reconciliation_state": reconciliation["reconciliation_state"],
        "semantic_change_count": reconciliation["semantic_change_count"],
        "open_call_authorized": snapshot["open_call_authorized"], "publication_effect": snapshot["publication_effect"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
