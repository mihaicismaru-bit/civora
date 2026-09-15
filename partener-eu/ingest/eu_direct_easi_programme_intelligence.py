#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import pathlib
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any, Mapping

SCHEMA = "PARTENER_EU_EASI_PROGRAMME_INTELLIGENCE_V1"
REGISTRY_SCHEMA = "PARTENER_EU_EASI_PROGRAMME_INTELLIGENCE_REGISTRY_V1"
PARSER_VERSION = "EU_DIRECT_EASI_PROGRAMME_INTELLIGENCE_V1"
ALLOWED_HOSTS = {"european-social-fund-plus.ec.europa.eu"}
MATERIAL_FLAGS = (
    "material_fact_use", "open_call_authorized", "closed_call_authorized",
    "deadline_authorized", "budget_authorized", "eligibility_authorized",
    "publish_authorized", "distribution_authorized", "call_alert_authorized",
    "canonical_corpus_mutation",
)
ALLOWED_STATES = {
    "PROGRAMME_INTELLIGENCE", "APPLICATION_ROUTE_INTELLIGENCE",
    "PROGRAMMING_PIPELINE", "PARTNER_INTELLIGENCE",
}


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


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(raw)


def normal(value: str) -> str:
    text = html.unescape(value or "").casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+./&:-]+", " ", text)).strip()


def html_text(raw: bytes) -> str:
    probe = TextProbe()
    probe.feed(raw.decode("utf-8", errors="replace"))
    return " ".join(probe.parts)


def validate_registry(registry: Mapping[str, Any]) -> None:
    if registry.get("schema") != REGISTRY_SCHEMA:
        raise ValueError("EaSI registry schema drift")
    if registry.get("source_family") != "EU_DIRECT" or registry.get("programme_id") != "ESF_PLUS_EASI":
        raise ValueError("EaSI programme identity drift")
    policy = registry.get("policy") or {}
    for flag in MATERIAL_FLAGS:
        if policy.get(flag) is not False:
            raise ValueError(f"EaSI registry became authorizing: {flag}")
    for key in (
        "market_intelligence_only", "exact_call_or_topic_identifier_required",
        "current_official_exact_endpoint_required", "semantic_reconciliation_required",
        "field_scoped_material_admission_required",
    ):
        if policy.get(key) is not True:
            raise ValueError(f"EaSI policy weakened: {key}")
    sources = registry.get("sources") or []
    if len(sources) != 4:
        raise ValueError("EaSI source inventory drift")
    for row in sources:
        parsed = urllib.parse.urlparse(str(row.get("url") or ""))
        if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in ALLOWED_HOSTS:
            raise ValueError("EaSI authority URL drift")
        if row.get("observation_state") not in ALLOWED_STATES:
            raise ValueError("EaSI observation state became call state")
        if not row.get("required_markers"):
            raise ValueError("EaSI source markers missing")
    fit = registry.get("applicant_fit") or {}
    if fit.get("fit_is_not_eligibility") is not True:
        raise ValueError("EaSI fit became eligibility")
    partner = registry.get("partner_intelligence") or {}
    if partner.get("partner_intelligence_is_not_call_eligibility") is not True:
        raise ValueError("EaSI partner intelligence became eligibility")


def fetch(url: str, timeout: float = 30.0) -> tuple[bytes, dict[str, Any]]:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; PARTENER.EU/1.0; +https://partener.eu)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en",
    })
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read(3_000_001)
        if len(raw) > 3_000_000:
            raise ValueError("EaSI source exceeds 3 MB")
        return raw, {
            "requested_url": url,
            "final_url": str(response.geturl()),
            "http_status": int(getattr(response, "status", 200) or 200),
            "content_type": str(response.headers.get("Content-Type") or ""),
        }


def collect(registry: Mapping[str, Any], run_id: str, fetcher=fetch) -> dict[str, Any]:
    validate_registry(registry)
    evidence = []
    healthy = 0
    for source in registry["sources"]:
        row = {
            "source_id": source["source_id"],
            "authority_url": source["url"],
            "observation_state": source["observation_state"],
            "authority_class": registry["authority_class"],
            "material_fact_use": False,
        }
        try:
            raw, meta = fetcher(source["url"])
            final = urllib.parse.urlparse(meta["final_url"])
            ctype = meta["content_type"].casefold()
            if meta["http_status"] != 200 or final.scheme != "https" or (final.hostname or "").casefold() not in ALLOWED_HOSTS or "html" not in ctype:
                raise ValueError("HTTP_OR_AUTHORITY_OR_CONTENT_TYPE_DRIFT")
            text = normal(html_text(raw))
            missing = [m for m in source["required_markers"] if normal(m) not in text]
            if missing:
                raise ValueError(f"MARKER_DRIFT:{missing}")
            normalized_text_sha256 = sha256_bytes(text.encode("utf-8"))
            semantics = {
                "source_id": source["source_id"],
                "programme_id": registry["programme_id"],
                "observation_state": source["observation_state"],
                "authority_url": source["url"],
                "required_markers_present": True,
                "normalized_visible_text_sha256": normalized_text_sha256,
            }
            row.update({
                "requested_url": meta["requested_url"], "final_url": meta["final_url"],
                "http_status": meta["http_status"], "content_type": meta["content_type"],
                "raw_sha256": sha256_bytes(raw), "source_health": "HEALTHY", "lkg_required": False,
                "normalized_visible_text_sha256": normalized_text_sha256,
                "source_semantic_fingerprint": sha256_json(semantics), "error": None,
            })
            healthy += 1
        except Exception as exc:
            row.update({
                "requested_url": source["url"], "final_url": None, "http_status": None,
                "content_type": None, "raw_sha256": None, "source_health": "DEGRADED",
                "lkg_required": True, "normalized_visible_text_sha256": None,
                "source_semantic_fingerprint": None, "error": f"{type(exc).__name__}: {exc}",
            })
        evidence.append(row)
    degraded = len(evidence) - healthy
    snapshot = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": registry["source_family"],
        "programme_family": registry["programme_family"],
        "programme_id": registry["programme_id"],
        "authority_class": registry["authority_class"],
        "observation_state": "PROGRAMME_INTELLIGENCE",
        "run_id": run_id,
        "fetched_at": utc_now(),
        "registry_sha256": sha256_json(registry),
        "source_count": len(evidence),
        "healthy_source_count": healthy,
        "degraded_source_count": degraded,
        "source_health_state": "HEALTHY" if degraded == 0 else "DEGRADED",
        "lkg_required": degraded > 0,
        "market_intelligence_only": True,
        "fit_score_is_not_eligibility": True,
        "partner_intelligence_is_not_call_eligibility": True,
        "applicant_fit_tags": list((registry.get("applicant_fit") or {}).get("tags") or []),
        "partner_intelligence_tags": list((registry.get("partner_intelligence") or {}).get("tags") or []),
        "exact_call_or_topic_identifier_required": True,
        "current_official_exact_endpoint_required": True,
        "semantic_reconciliation_required": True,
        "field_scoped_material_admission_required": True,
        "missing_for_open_confirmation": [
            "exact_call_or_topic_identifier", "current_official_exact_call_or_topic_endpoint",
            "explicit_current_official_call_status", "semantic_reconciliation",
            "field_scoped_material_admission",
        ],
        "evidence": evidence,
        "publication_effect": "NONE",
    }
    for flag in MATERIAL_FLAGS:
        snapshot[flag] = False
    snapshot["semantic_fingerprint"] = sha256_json({
        "programme_id": snapshot["programme_id"],
        "source_inventory": [(r["source_id"], r["observation_state"], r["source_semantic_fingerprint"]) for r in evidence],
        "fit_tags": snapshot["applicant_fit_tags"],
        "partner_tags": snapshot["partner_intelligence_tags"],
    })
    return snapshot


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    registry = json.loads(pathlib.Path(args.registry).read_text(encoding="utf-8"))
    snapshot = collect(registry, args.run_id)
    path = pathlib.Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "programme_family": snapshot["programme_family"],
        "source_health_state": snapshot["source_health_state"],
        "healthy_source_count": snapshot["healthy_source_count"],
        "degraded_source_count": snapshot["degraded_source_count"],
        "open_call_authorized": False,
        "publication_effect": "NONE",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
