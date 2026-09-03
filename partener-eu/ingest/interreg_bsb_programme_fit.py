#!/usr/bin/env python3
"""Bounded Interreg NEXT Black Sea Basin programme/geography/applicant intelligence.

Acquisition-only and non-authorizing. This adapter verifies Romania programme fit,
expands the official Sud-Est NUTS II signal to its six Romanian counties using the
official ADR Sud-Est region definition, and records historical applicant signals
from the programme's closed second calls. None of this evidence can establish a
current call, deadline, budget, or applicant eligibility.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import pathlib
import re
import unicodedata
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any, Callable, Mapping

SCHEMA = "PARTENER_EU_INTERREG_BSB_PROGRAMME_FIT_V1"
PARSER_VERSION = "INTERREG_BSB_PROGRAMME_FIT_V1"
SOURCE_FAMILY = "INTERREG"
PROGRAMME_FAMILY = "INTERREG_NEXT_BLACK_SEA_BASIN"
PROGRAMME_ID = "BSB"
CCI = "2021TC16NXTN002"
OBSERVATION_STATE = "PROGRAMME_GEOGRAPHY_APPLICANT_MARKET_INTELLIGENCE_NON_AUTHORIZING"

MATERIAL_FLAGS = (
    "material_fact_use", "open_call_authorized", "closed_call_authorized",
    "deadline_authorized", "budget_authorized", "eligibility_authorized",
    "publish_authorized", "distribution_authorized", "call_alert_authorized",
    "canonical_corpus_mutation",
)

ROMANIA_SCOPE = ("Braila", "Buzau", "Constanta", "Galati", "Tulcea", "Vrancea")
SUPPORTED_APPLICANT_TYPES = ("PUBLIC_AUTHORITY", "PUBLIC_LAW_BODY", "NGO_NONPROFIT")

SOURCES: tuple[dict[str, Any], ...] = (
    {
        "id": "BSB_KEEP_PROGRAMME_VALIDATED_GEOGRAPHY",
        "url": "https://keep.eu/programmes/387/2021-2027-Black-Sea-Basin/",
        "hosts": ("keep.eu", "www.keep.eu"),
        "authority_class": "T1_INTERACT_PROGRAMME_VALIDATED_REGISTRY",
        "observation_state": "PROGRAMME_GEOGRAPHY_RESEARCH_NON_AUTHORIZING",
        "markers": (
            "2021 - 2027 Interreg VI-B NEXT Black Sea Basin",
            "2021TC16NXTN002",
            "Eligible geographical area",
            "RO Romania",
            "Sud-Est",
            "Programme validated the information",
        ),
    },
    {
        "id": "BSB_OFFICIAL_SECOND_CALL_HISTORY",
        "url": "https://blacksea-cbc.net/interreg-next-bsb-2021-2027/calls-for-proposals/second-call-for-proposals",
        "hosts": ("blacksea-cbc.net", "www.blacksea-cbc.net"),
        "authority_class": "T1_OFFICIAL_PROGRAMME",
        "observation_state": "HISTORICAL_CLOSED_CALL_APPLICANT_SIGNAL_NON_AUTHORIZING",
        "markers": (
            "Second Calls for Proposals",
            "CLOSED",
            "Public authorities",
            "Bodies governed by public law",
            "Non-profit organizations",
        ),
    },
    {
        "id": "ADRSE_REGION_MEMBERSHIP",
        "url": "https://www.adrse.ro/",
        "hosts": ("adrse.ro", "www.adrse.ro"),
        "authority_class": "T1_ROMANIA_REGIONAL_AUTHORITY",
        "observation_state": "ROMANIA_REGION_MEMBERSHIP_REFERENCE_NON_AUTHORIZING",
        "markers": (
            "Regiunea de Dezvoltare Sud-Est",
            "Braila", "Buzau", "Constanta", "Galati", "Tulcea", "Vrancea",
        ),
    },
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def fold(value: str) -> str:
    text = html.unescape(value or "").casefold()
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip()


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


def visible_text(raw: bytes) -> str:
    probe = TextProbe()
    probe.feed(raw.decode("utf-8", errors="replace"))
    return " ".join(probe.parts)


def default_fetch(url: str, timeout: float = 30.0) -> tuple[bytes, dict[str, Any]]:
    request = urllib.request.Request(url, headers={
        "User-Agent": "PARTENER.EU-source-watch/1.0 (+https://partener.eu)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en,ro;q=0.8",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError(f"BSB source exceeds 5 MB: {url}")
        meta = {
            "requested_url": url,
            "final_url": str(response.geturl()),
            "http_status": int(getattr(response, "status", 200) or 200),
            "content_type": str(response.headers.get("Content-Type") or ""),
        }
    if meta["http_status"] != 200:
        raise ValueError(f"BSB source returned HTTP {meta['http_status']}: {url}")
    return raw, meta


def host_allowed(url: str, allowed: tuple[str, ...]) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").casefold()
    return host in {item.casefold() for item in allowed}


def require_markers(text: str, markers: tuple[str, ...], *, source_id: str) -> None:
    haystack = fold(text)
    missing = [marker for marker in markers if fold(marker) not in haystack]
    if missing:
        raise ValueError(f"{source_id} missing required authority markers: {missing}")


def collect(
    *,
    run_id: str,
    fetched_at: str | None = None,
    fetcher: Callable[[str], tuple[bytes, dict[str, Any]]] = default_fetch,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    observed = fetched_at or utc_now()
    receipts: list[dict[str, Any]] = []
    raw_by_id: dict[str, bytes] = {}

    for spec in SOURCES:
        raw, meta = fetcher(spec["url"])
        final_url = str(meta.get("final_url") or meta.get("requested_url") or "")
        if int(meta.get("http_status") or 0) != 200 or not host_allowed(final_url, spec["hosts"]):
            raise ValueError(f"{spec['id']} escaped its approved authority")
        text = visible_text(raw)
        require_markers(text, spec["markers"], source_id=spec["id"])
        raw_by_id[spec["id"]] = raw
        normalized_hash = sha256_bytes(fold(text).encode("utf-8"))
        receipts.append({
            "source_id": spec["id"],
            "authority_url": spec["url"],
            **dict(meta),
            "fetched_at": observed,
            "raw_sha256": sha256_bytes(raw),
            "normalized_visible_text_sha256": normalized_hash,
            "authority_class": spec["authority_class"],
            "observation_state": spec["observation_state"],
            "source_health": "HEALTHY",
        })

    result: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "programme_id": PROGRAMME_ID,
        "programme": "Interreg VI-B NEXT Black Sea Basin",
        "programme_period": "2021-2027",
        "programme_cci": CCI,
        "run_id": run_id,
        "fetched_at": observed,
        "observation_state": OBSERVATION_STATE,
        "source_health": "HEALTHY",
        "source_receipts": receipts,
        "romania_programme_region": "Sud-Est",
        "romania_scope": list(ROMANIA_SCOPE),
        "territorial_fit_state": "ROMANIA_PROGRAMME_TERRITORY_VERIFIED_NON_AUTHORIZING",
        "territory_resolution_basis": "PROGRAMME_VALIDATED_NUTS2_SUD_EST_PLUS_ADRSE_OFFICIAL_COUNTY_MEMBERSHIP",
        "applicant_signal_observation_state": "HISTORICAL_CLOSED_CALL_APPLICANT_SIGNAL",
        "supported_applicant_types": list(SUPPORTED_APPLICANT_TYPES),
        "partnership_signal": "TRANSNATIONAL_PARTNERSHIP_CALL_SPECIFIC_RULES_REQUIRED",
        "call_specific_applicant_rules_required": True,
        "historical_call_status_observed": "CLOSED",
        "historical_call_status_is_current_truth": False,
        "market_intelligence_only": True,
        "fit_is_not_eligibility": True,
        "missing_for_open_confirmation": [
            "exact_current_call_or_topic_identifier",
            "fresh_current_official_exact_call_endpoint",
            "explicit_current_official_open_status",
            "call_specific_applicant_geography_partnership_and_role_rules",
            "same_identity_semantic_reconciliation",
            "field_scoped_material_admission",
        ],
        "publication_effect": "NONE",
    }
    for flag in MATERIAL_FLAGS:
        result[flag] = False
    result["semantic_fingerprint"] = sha256_json({
        "programme_id": PROGRAMME_ID,
        "programme_cci": CCI,
        "romania_programme_region": result["romania_programme_region"],
        "romania_scope": result["romania_scope"],
        "supported_applicant_types": result["supported_applicant_types"],
        "source_semantics": [
            (row["source_id"], row["authority_url"], row["observation_state"], row["normalized_visible_text_sha256"])
            for row in receipts
        ],
    })
    validate(result)
    return result, raw_by_id


def validate(result: Mapping[str, Any]) -> None:
    if result.get("schema") != SCHEMA or result.get("parser_version") != PARSER_VERSION:
        raise ValueError("BSB programme-fit schema/parser drift")
    if result.get("source_family") != SOURCE_FAMILY or result.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("BSB programme-fit family drift")
    if result.get("programme_id") != PROGRAMME_ID or result.get("programme_cci") != CCI:
        raise ValueError("BSB programme identity drift")
    if result.get("observation_state") != OBSERVATION_STATE or result.get("source_health") != "HEALTHY":
        raise ValueError("BSB programme-fit health/state drift")
    if result.get("romania_programme_region") != "Sud-Est" or list(result.get("romania_scope") or []) != list(ROMANIA_SCOPE):
        raise ValueError("BSB Romania territorial scope drift")
    if set(result.get("supported_applicant_types") or []) != set(SUPPORTED_APPLICANT_TYPES):
        raise ValueError("BSB applicant signal drift")
    if result.get("applicant_signal_observation_state") != "HISTORICAL_CLOSED_CALL_APPLICANT_SIGNAL":
        raise ValueError("BSB historical applicant signal state drift")
    if result.get("historical_call_status_observed") != "CLOSED" or result.get("historical_call_status_is_current_truth") is not False:
        raise ValueError("BSB historical call status widened into current truth")
    if result.get("market_intelligence_only") is not True or result.get("fit_is_not_eligibility") is not True:
        raise ValueError("BSB programme-fit crossed market intelligence boundary")
    if result.get("call_specific_applicant_rules_required") is not True or result.get("publication_effect") != "NONE":
        raise ValueError("BSB programme-fit weakened exact-call requirements")
    for flag in MATERIAL_FLAGS:
        if result.get(flag) is not False:
            raise ValueError(f"BSB programme-fit attempted authorization: {flag}")

    receipts = result.get("source_receipts")
    if not isinstance(receipts, list) or len(receipts) != len(SOURCES):
        raise ValueError("BSB programme-fit requires complete authority receipts")
    specs = {row["id"]: row for row in SOURCES}
    for receipt in receipts:
        source_id = str(receipt.get("source_id") or "")
        if source_id not in specs:
            raise ValueError("BSB unknown source receipt")
        spec = specs[source_id]
        if receipt.get("authority_url") != spec["url"] or receipt.get("authority_class") != spec["authority_class"]:
            raise ValueError(f"BSB source identity drift: {source_id}")
        if receipt.get("observation_state") != spec["observation_state"] or receipt.get("source_health") != "HEALTHY":
            raise ValueError(f"BSB source state drift: {source_id}")
        if int(receipt.get("http_status") or 0) != 200 or not host_allowed(str(receipt.get("final_url") or ""), spec["hosts"]):
            raise ValueError(f"BSB source authority/transport drift: {source_id}")
        for key in ("raw_sha256", "normalized_visible_text_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get(key) or "")):
                raise ValueError(f"BSB source hash missing: {source_id}/{key}")

    expected = sha256_json({
        "programme_id": PROGRAMME_ID,
        "programme_cci": CCI,
        "romania_programme_region": result["romania_programme_region"],
        "romania_scope": result["romania_scope"],
        "supported_applicant_types": result["supported_applicant_types"],
        "source_semantics": [
            (row["source_id"], row["authority_url"], row["observation_state"], row["normalized_visible_text_sha256"])
            for row in receipts
        ],
    })
    if result.get("semantic_fingerprint") != expected:
        raise ValueError("BSB semantic fingerprint mismatch")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    out = pathlib.Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result, raw = collect(run_id=args.run_id)
    raw_dir = out / "raw"
    raw_dir.mkdir(exist_ok=True)
    for source_id, body in raw.items():
        (raw_dir / f"{source_id.casefold()}.html").write_bytes(body)
    target = out / "interreg-bsb-programme-fit.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "programme_id": result["programme_id"],
        "programme_cci": result["programme_cci"],
        "romania_region": result["romania_programme_region"],
        "romania_scope": result["romania_scope"],
        "source_health": result["source_health"],
        "semantic_fingerprint": result["semantic_fingerprint"],
        "open_call_authorized": result["open_call_authorized"],
        "output": str(target),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
