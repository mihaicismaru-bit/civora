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

SCHEMA = "PARTENER_EU_I3_PROGRAMME_INTELLIGENCE_V1"
REGISTRY_SCHEMA = "PARTENER_EU_I3_PROGRAMME_INTELLIGENCE_REGISTRY_V1"
PARSER_VERSION = "EU_DIRECT_I3_PROGRAMME_INTELLIGENCE_V1"
ALLOWED_HOSTS = {"eismea.ec.europa.eu"}
ALLOWED_STATES = {
    "PROGRAMME_INTELLIGENCE",
    "PROGRAMMING_PIPELINE",
    "PARTNER_INTELLIGENCE",
    "CALL_INDEX_DISCOVERY",
}
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
    "exact_call_or_topic_identifier_bound_as_material_identity",
    "current_official_exact_call_or_topic_endpoint",
    "fresh_structured_funding_tenders_status",
    "same_identity_semantic_reconciliation",
    "call_specific_deadline_budget_eligibility_and_geography",
    "field_scoped_material_admission",
]


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
        raise ValueError("I3 registry schema drift")
    if registry.get("source_family") != "EU_DIRECT" or registry.get("programme_id") != "I3":
        raise ValueError("I3 programme identity drift")
    if registry.get("authority_class") != "T1_EISMEA_OFFICIAL":
        raise ValueError("I3 authority class drift")
    if not registry.get("evidence_checked_date"):
        raise ValueError("I3 evidence_checked_date required")

    policy = registry.get("policy") or {}
    for flag in MATERIAL_FLAGS:
        if policy.get(flag) is not False:
            raise ValueError(f"I3 registry became authorizing: {flag}")
    for key in (
        "market_intelligence_only",
        "exact_call_or_topic_identifier_required",
        "current_official_exact_endpoint_required",
        "structured_funding_tenders_reconciliation_required",
        "semantic_reconciliation_required",
        "field_scoped_material_admission_required",
    ):
        if policy.get(key) is not True:
            raise ValueError(f"I3 policy weakened: {key}")

    sources = registry.get("sources") or []
    if len(sources) != 5:
        raise ValueError("I3 source inventory drift")
    source_ids: set[str] = set()
    call_hints: set[str] = set()
    for row in sources:
        sid = str(row.get("source_id") or "")
        if not sid or sid in source_ids:
            raise ValueError("I3 source id missing/duplicate")
        source_ids.add(sid)
        parsed = urllib.parse.urlparse(str(row.get("url") or ""))
        if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in ALLOWED_HOSTS:
            raise ValueError("I3 authority URL drift")
        if row.get("observation_state") not in ALLOWED_STATES:
            raise ValueError("I3 observation state became call state")
        if not row.get("required_markers"):
            raise ValueError("I3 source markers missing")
        hint = row.get("call_reference_hint")
        if hint:
            if row.get("observation_state") != "CALL_INDEX_DISCOVERY":
                raise ValueError("I3 call hint escaped discovery-only state")
            if hint in call_hints:
                raise ValueError("I3 call reference hint duplicated")
            call_hints.add(str(hint))

    if call_hints != {"I3-2026-INV1", "I3-2026-INV2a"}:
        raise ValueError("I3 discovery reference inventory drift")
    if (registry.get("applicant_fit") or {}).get("fit_is_not_eligibility") is not True:
        raise ValueError("I3 applicant fit became eligibility")
    if (registry.get("geography_fit") or {}).get("fit_is_not_eligibility") is not True:
        raise ValueError("I3 geography fit became eligibility")
    if (registry.get("partner_intelligence") or {}).get("partner_intelligence_is_not_call_eligibility") is not True:
        raise ValueError("I3 partner intelligence became eligibility")


def fetch(url: str, timeout: float = 30.0) -> tuple[bytes, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; PARTENER.EU/1.0; +https://partener.eu)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(3_000_001)
        if len(raw) > 3_000_000:
            raise ValueError("I3 source exceeds 3 MB")
        return raw, {
            "requested_url": url,
            "final_url": str(response.geturl()),
            "http_status": int(getattr(response, "status", 200) or 200),
            "content_type": str(response.headers.get("Content-Type") or ""),
        }


def collect(registry: Mapping[str, Any], run_id: str, fetcher=fetch) -> dict[str, Any]:
    validate_registry(registry)
    evidence: list[dict[str, Any]] = []
    healthy = 0

    for source in registry["sources"]:
        row: dict[str, Any] = {
            "source_id": source["source_id"],
            "source_family": "EU_DIRECT",
            "programme_family": registry["programme_family"],
            "programme_id": registry["programme_id"],
            "authority_class": registry["authority_class"],
            "authority_url": source["url"],
            "observation_state": source["observation_state"],
            "call_reference_hint": source.get("call_reference_hint"),
            "call_reference_hint_authority": (
                "DISCOVERY_HINT_ONLY_NOT_CALL_IDENTIFIER" if source.get("call_reference_hint") else None
            ),
            "market_intelligence_only": True,
            "material_fact_use": False,
        }
        try:
            raw, meta = fetcher(source["url"])
            final = urllib.parse.urlparse(meta["final_url"])
            ctype = str(meta["content_type"]).casefold()
            if (
                meta["http_status"] != 200
                or final.scheme != "https"
                or (final.hostname or "").casefold() not in ALLOWED_HOSTS
                or "html" not in ctype
            ):
                raise ValueError("HTTP_OR_AUTHORITY_OR_CONTENT_TYPE_DRIFT")
            text = normal(html_text(raw))
            missing = [marker for marker in source["required_markers"] if normal(marker) not in text]
            if missing:
                raise ValueError(f"MARKER_DRIFT:{missing}")
            normalized_visible_text_sha256 = sha256_bytes(text.encode("utf-8"))
            semantic_payload = {
                "source_id": source["source_id"],
                "programme_id": registry["programme_id"],
                "observation_state": source["observation_state"],
                "authority_url": source["url"],
                "call_reference_hint": source.get("call_reference_hint"),
                "normalized_visible_text_sha256": normalized_visible_text_sha256,
            }
            row.update(
                {
                    "requested_url": meta["requested_url"],
                    "final_url": meta["final_url"],
                    "http_status": meta["http_status"],
                    "content_type": meta["content_type"],
                    "raw_sha256": sha256_bytes(raw),
                    "raw_size_bytes": len(raw),
                    "source_health": "HEALTHY",
                    "lkg_required": False,
                    "normalized_visible_text_sha256": normalized_visible_text_sha256,
                    "source_semantic_fingerprint": sha256_json(semantic_payload),
                    "error": None,
                }
            )
            healthy += 1
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            lowered = message.casefold()
            failure_class = (
                "TLS_CERTIFICATE_VERIFY_FAILED"
                if "certificate verify failed" in lowered or "certificate_verify_failed" in lowered
                else type(exc).__name__.upper()
            )
            row.update(
                {
                    "requested_url": source["url"],
                    "final_url": None,
                    "http_status": None,
                    "content_type": None,
                    "raw_sha256": None,
                    "raw_size_bytes": 0,
                    "source_health": "DEGRADED",
                    "failure_class": failure_class,
                    "lkg_required": True,
                    "normalized_visible_text_sha256": None,
                    "source_semantic_fingerprint": None,
                    "error": message,
                }
            )
        evidence.append(row)

    degraded = len(evidence) - healthy
    snapshot: dict[str, Any] = {
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
        "registry_evidence_checked_date": registry["evidence_checked_date"],
        "source_count": len(evidence),
        "healthy_source_count": healthy,
        "degraded_source_count": degraded,
        "source_health_state": "HEALTHY" if degraded == 0 else "DEGRADED",
        "lkg_required": degraded > 0,
        "market_intelligence_only": True,
        "fit_score_is_not_eligibility": True,
        "geography_fit_is_not_eligibility": True,
        "partner_intelligence_is_not_call_eligibility": True,
        "applicant_fit_tags": list((registry.get("applicant_fit") or {}).get("tags") or []),
        "geography_fit_tags": list((registry.get("geography_fit") or {}).get("tags") or []),
        "partner_intelligence_tags": list((registry.get("partner_intelligence") or {}).get("tags") or []),
        "exact_call_or_topic_identifier_required": True,
        "current_official_exact_endpoint_required": True,
        "structured_funding_tenders_reconciliation_required": True,
        "semantic_reconciliation_required": True,
        "field_scoped_material_admission_required": True,
        "missing_for_open_confirmation": list(MISSING_FOR_OPEN),
        "evidence": evidence,
        "publication_effect": "NONE",
    }
    for flag in MATERIAL_FLAGS:
        snapshot[flag] = False
    snapshot["semantic_fingerprint"] = sha256_json(
        {
            "programme_id": snapshot["programme_id"],
            "source_inventory": [
                (
                    row["source_id"],
                    row["observation_state"],
                    row.get("call_reference_hint"),
                    row["source_semantic_fingerprint"],
                )
                for row in evidence
            ],
            "applicant_fit_tags": snapshot["applicant_fit_tags"],
            "geography_fit_tags": snapshot["geography_fit_tags"],
            "partner_intelligence_tags": snapshot["partner_intelligence_tags"],
        }
    )
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    registry = json.loads(pathlib.Path(args.registry).read_text(encoding="utf-8"))
    snapshot = collect(registry, args.run_id)
    path = pathlib.Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "programme_id": snapshot["programme_id"],
                "source_health_state": snapshot["source_health_state"],
                "healthy_source_count": snapshot["healthy_source_count"],
                "degraded_source_count": snapshot["degraded_source_count"],
                "open_call_authorized": False,
                "publication_effect": "NONE",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
