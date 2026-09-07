#!/usr/bin/env python3
"""Exact official evidence for EUI City-to-City Exchanges.

Authority precedence:
1) exact EUI City-to-City Exchanges call page;
2) current EUI Guidance for Applicants;
3) Portico programme metadata is discovery/conflict evidence only.

The exact EUI authorities describe a continuous/rolling opportunity with no
currently fixed end date. Portico may expose an aggregate deadline; that
metadata is preserved as a discrepancy but cannot become the canonical
deadline. A formal call/topic identifier is not fabricated, therefore this
lane never authorizes OPEN_CALL or any material field.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import pathlib
import re
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

SCHEMA = "PARTENER_EU_EUI_C2C_EXACT_EVIDENCE_V1"
PARSER_VERSION = "EU_DIRECT_EUI_C2C_EXACT_V1"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "EUROPEAN_URBAN_INITIATIVE"
OPPORTUNITY_FAMILY = "CITY_TO_CITY_EXCHANGES"
AUTHORITY_CLASS = "EUI_EXACT_C2C_PAGE_AND_CURRENT_GUIDANCE"
OBSERVATION_LAYER = "EXACT_CONTINUOUS_OPPORTUNITY_NON_AUTHORIZING"
IDENTITY_SLUG = "eui-city-to-city-exchanges"
TITLE = "City-to-City Exchanges"
DEFAULT_CALL_URL = "https://www.urban-initiative.eu/capacity-building/city-to-city-exchanges/call"
DEFAULT_GUIDANCE_URL = (
    "https://www.urban-initiative.eu/sites/default/files/2026-04/"
    "EUI_City-to-City_Exchanges_%20guidance_update_April_2026_0.pdf"
)
DEFAULT_PORTICO_URL = "https://portico.urban-initiative.eu/urban-panorama/european-urban-initiative"
MATERIAL_FLAGS = (
    "material_fact_use", "open_call_authorized", "closed_call_authorized",
    "deadline_authorized", "budget_authorized", "eligibility_authorized",
    "publish_authorized", "distribution_authorized", "call_alert_authorized",
)


class ExactC2CEvidenceError(ValueError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def _validate_url(url: str, *, host: str, path_prefix: str) -> str:
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https":
        raise ExactC2CEvidenceError(f"non-HTTPS EUI C2C URL: {url!r}")
    if (parsed.hostname or "").casefold() != host.casefold():
        raise ExactC2CEvidenceError(f"unexpected EUI C2C host: {parsed.hostname!r}")
    if not (parsed.path or "/").startswith(path_prefix):
        raise ExactC2CEvidenceError(f"EUI C2C path outside bounded allowlist: {parsed.path!r}")
    return url


def _normalise_text(raw: bytes) -> str:
    text = html.unescape(raw.decode("utf-8", errors="ignore"))
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _http_fetch(url: str, *, timeout: float = 20.0, accept: str = "text/html,*/*;q=0.1") -> tuple[bytes, int, str, str]:
    req = Request(
        url,
        headers={"User-Agent": "PARTENER.EU-EUIC2C/1.0 (+https://partener.eu)", "Accept": accept},
        method="GET",
    )
    with urlopen(req, timeout=timeout) as response:
        return (
            response.read(),
            int(getattr(response, "status", 200)),
            str(response.geturl()),
            str(response.headers.get("Content-Type", "")),
        )


def _receipt(
    url: str, *, raw: bytes | None = None, status: int | None = None,
    final_url: str | None = None, content_type: str | None = None,
    health: str, error: str | None = None,
) -> dict[str, Any]:
    return {
        "health_state": health,
        "lkg_required": health != "HEALTHY",
        "requested_url": url,
        "final_url": final_url,
        "http_status": status,
        "content_type": content_type,
        "raw_sha256": sha256_bytes(raw) if raw is not None else None,
        "raw_size_bytes": len(raw) if raw is not None else 0,
        "error": error,
    }


def _safe_fetch(
    url: str, *, fetcher: Callable[..., tuple[bytes, int, str, str]],
    timeout: float, accept: str, host: str, path_prefix: str,
) -> tuple[bytes | None, dict[str, Any]]:
    _validate_url(url, host=host, path_prefix=path_prefix)
    try:
        raw, status, final_url, content_type = fetcher(url, timeout=timeout, accept=accept)
        _validate_url(final_url, host=host, path_prefix=path_prefix)
        health = "HEALTHY" if status == 200 else "DEGRADED_HTTP"
        return raw, _receipt(
            url, raw=raw, status=status, final_url=final_url,
            content_type=content_type, health=health,
            error=None if status == 200 else f"unexpected HTTP status {status}",
        )
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        return None, _receipt(
            url, status=getattr(exc, "code", None), health="DEGRADED_TRANSPORT",
            error=f"{type(exc).__name__}: {exc}",
        )


def _page_semantics(raw: bytes, *, call_url: str) -> dict[str, Any]:
    text = _normalise_text(raw)
    folded = text.casefold()
    required = (
        "city-to-city exchanges",
        "continuously open",
        "rolling basis",
        "urban authorities from eu member states",
    )
    missing = [marker for marker in required if marker not in folded]
    if missing:
        raise ExactC2CEvidenceError(f"exact C2C page lost required markers: {missing}")
    permanent = "open on a permanent basis" in folded or "applications are always open" in folded
    if not permanent:
        raise ExactC2CEvidenceError("exact C2C page lost permanent/always-open marker")
    support_markers = {
        "travel_accommodation": "travel and accommodation costs" in folded,
        "moderation": "moderation services" in folded,
        "peer_learning": "peer learning" in folded,
    }
    if not all(support_markers.values()):
        raise ExactC2CEvidenceError("exact C2C page lost capacity-building support markers")
    return {
        "identity_scheme": "OFFICIAL_EXACT_URL_CONTINUOUS_C2C_GUIDANCE_CHAIN",
        "identity_slug": IDENTITY_SLUG,
        "official_call_identifier": None,
        "title": TITLE,
        "authority_url": call_url,
        "candidate_state": "CONTINUOUS_OPPORTUNITY",
        "status_label": "Continuously open",
        "deadline_candidate": None,
        "deadline_semantics": "NO_CURRENTLY_FIXED_END_DATE",
        "application_window": "ROLLING_CONTINUOUS",
        "opportunity_type": "CAPACITY_BUILDING_PEER_LEARNING_SUPPORT",
        "geography_scope_candidate": "EU_MEMBER_STATE_URBAN_AUTHORITIES",
        "romanian_fit": "GEOGRAPHIC_PROGRAMME_FIT_ONLY",
        "support_kind": "TRAVEL_ACCOMMODATION_AND_MODERATION_SUPPORT",
    }


def _validate_guidance_pdf(raw: bytes | None, receipt: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(receipt)
    if row.get("health_state") != "HEALTHY":
        return row
    content_type = str(row.get("content_type") or "").casefold()
    if raw is None or not raw.startswith(b"%PDF") or len(raw) < 1000 or "pdf" not in content_type:
        row.update(
            health_state="DEGRADED_MARKER_MISMATCH", lkg_required=True,
            error="current EUI C2C Guidance did not validate as PDF",
        )
    return row


def _portico_metadata(raw: bytes | None) -> dict[str, Any]:
    if not raw:
        return {"listing_found": False, "status_label": None, "deadline_observed": None}
    text = _normalise_text(raw)
    match = re.search(
        r"City-to-City Exchanges.{0,800}?(Open|Closed).{0,400}?Deadline date\s*:\s*(\d{2}/\d{2}/\d{4})",
        text, flags=re.I | re.S,
    )
    if not match:
        return {"listing_found": False, "status_label": None, "deadline_observed": None}
    day, month, year = match.group(2).split("/")
    return {
        "listing_found": True,
        "status_label": match.group(1).title(),
        "deadline_observed": f"{year}-{month}-{day}",
    }


def collect_exact(
    *, run_id: str, call_url: str = DEFAULT_CALL_URL,
    guidance_url: str = DEFAULT_GUIDANCE_URL, portico_url: str = DEFAULT_PORTICO_URL,
    fetched_at: str | None = None, timeout: float = 20.0,
    output_dir: pathlib.Path | None = None,
    fetcher: Callable[..., tuple[bytes, int, str, str]] = _http_fetch,
) -> dict[str, Any]:
    fetched_at = fetched_at or utc_now()
    _validate_url(call_url, host="www.urban-initiative.eu", path_prefix="/capacity-building/city-to-city-exchanges/call")
    _validate_url(guidance_url, host="www.urban-initiative.eu", path_prefix="/sites/default/files/2026-04/")
    _validate_url(portico_url, host="portico.urban-initiative.eu", path_prefix="/urban-panorama/european-urban-initiative")

    page_raw, page = _safe_fetch(
        call_url, fetcher=fetcher, timeout=timeout,
        accept="text/html,application/xhtml+xml,*/*;q=0.1",
        host="www.urban-initiative.eu", path_prefix="/capacity-building/city-to-city-exchanges/call",
    )
    guidance_raw, guidance = _safe_fetch(
        guidance_url, fetcher=fetcher, timeout=timeout,
        accept="application/pdf,*/*;q=0.1",
        host="www.urban-initiative.eu", path_prefix="/sites/default/files/2026-04/",
    )
    guidance = _validate_guidance_pdf(guidance_raw, guidance)
    portico_raw, portico = _safe_fetch(
        portico_url, fetcher=fetcher, timeout=timeout,
        accept="text/html,application/xhtml+xml,*/*;q=0.1",
        host="portico.urban-initiative.eu", path_prefix="/urban-panorama/european-urban-initiative",
    )

    semantics = None
    if page_raw is not None and page.get("health_state") == "HEALTHY":
        try:
            semantics = _page_semantics(page_raw, call_url=call_url)
        except ExactC2CEvidenceError as exc:
            page = {
                **page, "health_state": "DEGRADED_MARKER_MISMATCH",
                "lkg_required": True, "error": str(exc),
            }

    # The exact EUI page + current Guidance are canonical for the application
    # window. Portico is an official aggregator/discovery surface only.
    authority_healthy = (
        page.get("health_state") == "HEALTHY"
        and guidance.get("health_state") == "HEALTHY"
        and semantics is not None
    )
    source_health_state = "HEALTHY" if authority_healthy else "DEGRADED"
    if not authority_healthy:
        semantics = {
            "identity_scheme": "OFFICIAL_EXACT_URL_CONTINUOUS_C2C_GUIDANCE_CHAIN",
            "identity_slug": IDENTITY_SLUG,
            "official_call_identifier": None,
            "title": TITLE,
            "authority_url": call_url,
            "candidate_state": "UNKNOWN",
            "status_label": "Unknown",
            "deadline_candidate": None,
            "deadline_semantics": "UNRESOLVED",
            "application_window": "UNRESOLVED",
            "opportunity_type": "CAPACITY_BUILDING_PEER_LEARNING_SUPPORT",
            "geography_scope_candidate": None,
            "romanian_fit": "UNRESOLVED",
            "support_kind": None,
        }

    portico_meta = _portico_metadata(portico_raw if portico.get("health_state") == "HEALTHY" else None)
    discrepancy = None
    if (
        source_health_state == "HEALTHY"
        and portico_meta.get("deadline_observed")
        and semantics.get("deadline_candidate") is None
    ):
        discrepancy = {
            "kind": "AUTHORITY_PRECEDENCE_DEADLINE_CONFLICT",
            "field": "deadline",
            "aggregator_value": portico_meta["deadline_observed"],
            "canonical_value": None,
            "resolution": "EXACT_EUI_PAGE_AND_CURRENT_GUIDANCE_PREVAIL",
            "material_authorization_effect": "NONE",
        }

    identity_basis = {
        "identity_scheme": semantics["identity_scheme"],
        "identity_slug": IDENTITY_SLUG,
        "title": TITLE,
        "authority_url": call_url,
        "guidance_url": guidance_url,
    }
    exact_semantics = dict(semantics)
    exact_semantics["guidance_url"] = guidance_url
    evidence: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "opportunity_family": OPPORTUNITY_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_LAYER,
        "fetched_at": fetched_at,
        "run_id": run_id,
        "authority_url": call_url,
        "guidance_url": guidance_url,
        "discovery_url": portico_url,
        "identity_key": sha256_json(identity_basis),
        "identity_scheme": semantics["identity_scheme"],
        "identity_slug": IDENTITY_SLUG,
        "official_call_identifier": None,
        "title": TITLE,
        "candidate_state": semantics["candidate_state"],
        "status_label": semantics["status_label"],
        "deadline_candidate": None,
        "deadline_semantics": semantics["deadline_semantics"],
        "application_window": semantics["application_window"],
        "opportunity_type": semantics["opportunity_type"],
        "geography_scope_candidate": semantics["geography_scope_candidate"],
        "romanian_fit": semantics["romanian_fit"],
        "support_kind": semantics["support_kind"],
        "exact_semantics": exact_semantics,
        "exact_semantic_fingerprint": sha256_json(exact_semantics),
        "source_health_state": source_health_state,
        "lkg_required": source_health_state != "HEALTHY",
        "source_receipts": {
            "exact_c2c_page": page,
            "current_guidance": guidance,
            "portico_discovery": portico,
        },
        "portico_metadata_observation": portico_meta,
        "authority_discrepancy": discrepancy,
        "authority_precedence": [
            "EXACT_EUI_C2C_PAGE",
            "CURRENT_EUI_C2C_GUIDANCE",
            "PORTICO_DISCOVERY_METADATA_NON_AUTHORIZING",
        ],
        "semantic_reconciliation_required": True,
        "field_scoped_material_admission_required": True,
        "missing_for_open_confirmation": [
            "official_call_or_topic_identifier",
            "field_scoped_material_admission",
        ],
        "market_intelligence_only": True,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        evidence[key] = False
    validate_evidence(evidence)

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "eui-c2c-exact-evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        if page_raw is not None:
            (output_dir / "eui-c2c-page.html").write_bytes(page_raw)
        if guidance_raw is not None:
            (output_dir / "eui-c2c-guidance.pdf").write_bytes(guidance_raw)
        if portico_raw is not None:
            (output_dir / "eui-c2c-portico.html").write_bytes(portico_raw)
    return evidence


def validate_evidence(evidence: Mapping[str, Any]) -> None:
    if evidence.get("schema") != SCHEMA or evidence.get("parser_version") != PARSER_VERSION:
        raise ExactC2CEvidenceError("EUI C2C schema/parser drift")
    if evidence.get("source_family") != SOURCE_FAMILY or evidence.get("programme_family") != PROGRAMME_FAMILY:
        raise ExactC2CEvidenceError("EUI C2C source/programme-family drift")
    if evidence.get("opportunity_family") != OPPORTUNITY_FAMILY:
        raise ExactC2CEvidenceError("EUI C2C opportunity-family drift")
    if evidence.get("authority_class") != AUTHORITY_CLASS or evidence.get("observation_state") != OBSERVATION_LAYER:
        raise ExactC2CEvidenceError("EUI C2C authority/observation drift")
    _validate_url(str(evidence.get("authority_url") or ""), host="www.urban-initiative.eu", path_prefix="/capacity-building/city-to-city-exchanges/call")
    _validate_url(str(evidence.get("guidance_url") or ""), host="www.urban-initiative.eu", path_prefix="/sites/default/files/2026-04/")
    _validate_url(str(evidence.get("discovery_url") or ""), host="portico.urban-initiative.eu", path_prefix="/urban-panorama/european-urban-initiative")
    if evidence.get("identity_slug") != IDENTITY_SLUG or evidence.get("official_call_identifier") is not None:
        raise ExactC2CEvidenceError("EUI C2C exact identity drift or fabricated formal identifier")
    if sha256_json(evidence.get("exact_semantics")) != evidence.get("exact_semantic_fingerprint"):
        raise ExactC2CEvidenceError("EUI C2C semantic fingerprint mismatch")
    if not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("identity_key") or "")):
        raise ExactC2CEvidenceError("EUI C2C identity hash missing")
    if evidence.get("deadline_candidate") is not None:
        raise ExactC2CEvidenceError("EUI C2C adapter promoted an aggregate/fixed deadline")
    healthy = evidence.get("source_health_state") == "HEALTHY"
    if healthy:
        if evidence.get("lkg_required") is not False:
            raise ExactC2CEvidenceError("healthy EUI C2C incorrectly requires LKG")
        if evidence.get("candidate_state") != "CONTINUOUS_OPPORTUNITY":
            raise ExactC2CEvidenceError("healthy EUI C2C lost continuous-opportunity state")
        if evidence.get("deadline_semantics") != "NO_CURRENTLY_FIXED_END_DATE":
            raise ExactC2CEvidenceError("healthy EUI C2C lost no-fixed-end semantics")
        for name in ("exact_c2c_page", "current_guidance"):
            row = (evidence.get("source_receipts") or {}).get(name) or {}
            if row.get("health_state") != "HEALTHY" or row.get("http_status") != 200:
                raise ExactC2CEvidenceError(f"healthy EUI C2C missing healthy canonical receipt: {name}")
            if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("raw_sha256") or "")):
                raise ExactC2CEvidenceError(f"healthy EUI C2C missing canonical raw hash: {name}")
    else:
        if evidence.get("source_health_state") != "DEGRADED" or evidence.get("lkg_required") is not True:
            raise ExactC2CEvidenceError("degraded EUI C2C health contract drift")
        if evidence.get("candidate_state") != "UNKNOWN" or evidence.get("deadline_semantics") != "UNRESOLVED":
            raise ExactC2CEvidenceError("degraded EUI C2C retained current material semantics")
    if evidence.get("market_intelligence_only") is not True:
        raise ExactC2CEvidenceError("EUI C2C lane stopped being non-authorizing market intelligence")
    for key in MATERIAL_FLAGS:
        if evidence.get(key) is not False:
            raise ExactC2CEvidenceError(f"EUI C2C adapter attempted material authorization: {key}")
    if evidence.get("publication_effect") != "NONE" or evidence.get("canonical_corpus_mutation") is not False:
        raise ExactC2CEvidenceError("EUI C2C adapter crossed publication/corpus boundary")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--call-url", default=DEFAULT_CALL_URL)
    parser.add_argument("--guidance-url", default=DEFAULT_GUIDANCE_URL)
    parser.add_argument("--portico-url", default=DEFAULT_PORTICO_URL)
    parser.add_argument("--output-dir", type=pathlib.Path)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    evidence = collect_exact(
        run_id=args.run_id, call_url=args.call_url, guidance_url=args.guidance_url,
        portico_url=args.portico_url, timeout=args.timeout, output_dir=args.output_dir,
    )
    print(json.dumps({
        "identity_slug": evidence["identity_slug"],
        "source_health_state": evidence["source_health_state"],
        "candidate_state": evidence["candidate_state"],
        "status_label": evidence["status_label"],
        "deadline_candidate": evidence["deadline_candidate"],
        "official_call_identifier": evidence["official_call_identifier"],
        "portico_deadline_observed": evidence["portico_metadata_observation"].get("deadline_observed"),
        "authority_discrepancy": evidence["authority_discrepancy"],
        "open_call_authorized": evidence["open_call_authorized"],
        "publication_effect": evidence["publication_effect"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
