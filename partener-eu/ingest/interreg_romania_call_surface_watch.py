#!/usr/bin/env python3
"""Official Interreg call-surface watch for programmes relevant to Romania.

Acquisition-only and non-authorizing. Direct programme call/planning surfaces are
preferred. When a direct programme surface fails at transport level, a configured
central Interreg/Interact programme registry page may be fetched only as fallback
provenance proving programme identity/continuity. Registry fallback never restores
call-surface coverage and can never authorize call facts.

A call status, deadline, budget or applicant eligibility can only come from a later
exact-call adapter bound to a selected identifier and a fresh current official call
endpoint.
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

SCHEMA = "PARTENER_EU_INTERREG_ROMANIA_CALL_SURFACE_WATCH_V2"
PARSER_VERSION = "INTERREG_ROMANIA_CALL_SURFACE_WATCH_V2"
SOURCE_FAMILY = "INTERREG"
PROGRAMME_FAMILY = "INTERREG_ROMANIA_RELEVANT_2021_2027"
AUTHORITY_CLASS = "INTERREG_OFFICIAL_CALL_DISCOVERY_SURFACE"
FALLBACK_AUTHORITY_CLASS = "INTERREG_INTERACT_PROGRAMME_REGISTRY_FALLBACK"
OBSERVATION_STATE = "CALL_SURFACE_DISCOVERY_NON_AUTHORIZING"
FALLBACK_OBSERVATION_STATE = "PROGRAMME_REGISTRY_FALLBACK_ONLY"

MATERIAL_FLAGS = (
    "material_fact_use", "open_call_authorized", "closed_call_authorized",
    "deadline_authorized", "budget_authorized", "eligibility_authorized",
    "publish_authorized", "distribution_authorized", "call_alert_authorized",
    "canonical_corpus_mutation",
)

SURFACES: tuple[dict[str, Any], ...] = (
    {
        "id": "RO_BG",
        "programme": "Interreg VI-A Romania-Bulgaria",
        "url": "https://interregviarobg.eu/en/calls-for-proposals-1",
        "hosts": ("interregviarobg.eu", "www.interregviarobg.eu"),
        "anchors": ("Closed calls for proposals", "Call 6", "Call 7"),
        "surface_role": "PROGRAMME_CALL_INDEX",
        "observation_state": "CALL_DISCOVERY_ONLY",
        "programme_filter_required": False,
        "authority_note": "official programme call archive/index; call state must be re-read on an exact call page",
        "fallback": {
            "url": "https://interreg.eu/programmes/romania-bulgaria/",
            "hosts": ("interreg.eu", "www.interreg.eu"),
            "anchors": ("Interreg Romania-Bulgaria", "Programme website", "keep.eu"),
            "role": "CENTRAL_INTERREG_PROGRAMME_REGISTRY_FALLBACK",
            "note": "Interact-managed programme registry fallback; validates programme identity/provenance only and is never call authority",
        },
    },
    {
        "id": "RO_HU",
        "programme": "Interreg VI-A Romania-Hungary",
        "url": "https://interreg-rohu.eu/en/calls-en/",
        "hosts": ("interreg-rohu.eu", "www.interreg-rohu.eu"),
        "anchors": ("CALLS FOR PROPOSALS", "1st Open Call for Proposals", "Interreg VI-A Romania"),
        "surface_role": "PROGRAMME_CALL_INDEX",
        "observation_state": "CALL_DISCOVERY_ONLY",
        "programme_filter_required": False,
        "authority_note": "official programme calls page; historic labels do not authorize current status",
    },
    {
        "id": "RO_RS",
        "programme": "Interreg IPA Romania-Serbia",
        "url": "https://romania-serbia.net/implementation/calls-for-proposals-calendar/",
        "hosts": ("romania-serbia.net", "www.romania-serbia.net"),
        "anchors": ("Timetable of the planned Calls", "2026"),
        "surface_role": "PROGRAMME_CALL_PLANNING",
        "observation_state": "PLANNED",
        "programme_filter_required": False,
        "authority_note": "official programme planning timetable; PLANNED can never authorize OPEN_CALL",
    },
    {
        "id": "RO_UA",
        "programme": "Interreg NEXT Romania-Ukraine",
        "url": "https://www.ro-ua.net/en/funding/calls-for-proposals",
        "hosts": ("ro-ua.net", "www.ro-ua.net"),
        "anchors": ("Calls for proposals", "Interreg NEXT Romania-Ukraine Programme"),
        "surface_role": "PROGRAMME_CALL_INDEX",
        "observation_state": "CALL_DISCOVERY_ONLY",
        "programme_filter_required": False,
        "authority_note": "official programme calls page; status/deadline text remains discovery until exact-call readback",
        "fallback": {
            "url": "https://interreg.eu/programmes/next-romania-ukraine/",
            "hosts": ("interreg.eu", "www.interreg.eu"),
            "anchors": ("Interreg NEXT Romania - Ukraine", "Programme website", "keep.eu"),
            "role": "CENTRAL_INTERREG_PROGRAMME_REGISTRY_FALLBACK",
            "note": "Interact-managed programme registry fallback; validates programme identity/provenance only and is never call authority",
        },
    },
    {
        "id": "RO_MD",
        "programme": "Interreg NEXT Romania-Republic of Moldova",
        "url": "https://ro-md.net/en/funding/calls-for-proposals",
        "hosts": ("ro-md.net", "www.ro-md.net"),
        "anchors": ("Calls for proposals", "Interreg NEXT Romania-Republic of Moldova Programme"),
        "surface_role": "PROGRAMME_CALL_INDEX",
        "observation_state": "CALL_DISCOVERY_ONLY",
        "programme_filter_required": False,
        "authority_note": "official programme calls page; status/deadline text remains discovery until exact-call readback",
        "fallback": {
            "url": "https://interreg.eu/programmes/next-romania-repmoldova/",
            "hosts": ("interreg.eu", "www.interreg.eu"),
            "anchors": ("Interreg NEXT Romania - Rep.Moldova", "Programme website", "keep.eu"),
            "role": "CENTRAL_INTERREG_PROGRAMME_REGISTRY_FALLBACK",
            "note": "Interact-managed programme registry fallback; validates programme identity/provenance only and is never call authority",
        },
    },
    {
        "id": "DANUBE",
        "programme": "Interreg Danube Region Programme",
        "url": "https://interreg-danube.eu/calls-for-proposals",
        "hosts": ("interreg-danube.eu", "www.interreg-danube.eu"),
        "anchors": ("Calls for proposals", "Third call"),
        "surface_role": "PROGRAMME_CALL_INDEX",
        "observation_state": "CALL_DISCOVERY_ONLY",
        "programme_filter_required": False,
        "authority_note": "official programme calls index; historic/open labels are non-authorizing discovery",
    },
    {
        "id": "INTERREG_EUROPE",
        "programme": "Interreg Europe",
        "url": "https://interreg.eu/calls-for-projects/",
        "hosts": ("interreg.eu", "www.interreg.eu"),
        "anchors": ("Calls for Projects", "Open & forthcoming calls"),
        "surface_role": "CENTRAL_INTERREG_CALL_REGISTRY",
        "observation_state": "CALL_DISCOVERY_ONLY",
        "programme_filter_required": True,
        "authority_note": "central Interreg/Interact calls registry based on programme data; an exact Interreg Europe programme/call endpoint is still required",
    },
    {
        "id": "HUSKROUA",
        "programme": "Interreg VI-A NEXT Hungary-Slovakia-Romania-Ukraine",
        "url": "https://next.huskroua-cbc.eu/calls/",
        "hosts": ("next.huskroua-cbc.eu",),
        "anchors": ("Calls", "1st Call for Proposals", "2nd Call for Proposals"),
        "surface_role": "PROGRAMME_CALL_INDEX",
        "observation_state": "CALL_DISCOVERY_ONLY",
        "programme_filter_required": False,
        "authority_note": "official programme calls index; historic call labels remain discovery-only and exact Call 2 lifecycle is reconciled separately",
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


def normal(value: str) -> str:
    text = html.unescape(value).casefold()
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
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


def html_text(raw: bytes) -> str:
    probe = TextProbe()
    probe.feed(raw.decode("utf-8", errors="replace"))
    return " ".join(probe.parts)


def default_fetch(url: str, timeout: float = 30.0) -> tuple[bytes, dict[str, Any]]:
    req = urllib.request.Request(url, headers={
        "User-Agent": "PARTENER.EU-source-watch/1.0 (+https://partener.eu)",
        "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en",
    })
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError(f"official Interreg source exceeds 5 MB: {url}")
        meta = {
            "requested_url": url,
            "final_url": str(response.geturl()),
            "status": int(getattr(response, "status", 200) or 200),
            "content_type": str(response.headers.get("Content-Type") or ""),
        }
    if meta["status"] != 200:
        raise ValueError(f"official Interreg source returned HTTP {meta['status']}: {url}")
    return raw, meta


def host_allowed(url: str, allowed: tuple[str, ...]) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").casefold()
    return host in {x.casefold() for x in allowed}


def require(text: str, anchors: tuple[str, ...], *, source: str) -> None:
    hay = normal(text)
    missing = [anchor for anchor in anchors if normal(anchor) not in hay]
    if missing:
        raise ValueError(f"{source} missing required provenance anchors: {missing}")


def classify_failure(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}".casefold()
    if "certificate verify failed" in text or "sslcertverificationerror" in text or ("tls" in text and "certificate" in text):
        return "TLS_CERTIFICATE_VERIFY_FAILED"
    if "timed out" in text or "timeout" in text:
        return "TIMEOUT"
    if "name or service not known" in text or "temporary failure in name resolution" in text or "getaddrinfo" in text:
        return "DNS_FAILURE"
    if "connection refused" in text or "connection reset" in text or "remote end closed" in text:
        return "CONNECTION_FAILURE"
    if "httperror" in text or "http error" in text:
        return "HTTP_ERROR"
    if isinstance(exc, ValueError):
        return "VALIDATION_ERROR"
    return "TRANSPORT_ERROR"


def fallback_template(spec: Mapping[str, Any]) -> dict[str, Any]:
    fallback = spec.get("fallback")
    if not isinstance(fallback, Mapping):
        return {
            "configured": False,
            "authority_url": None,
            "authority_class": FALLBACK_AUTHORITY_CLASS,
            "surface_role": None,
            "observation_state": FALLBACK_OBSERVATION_STATE,
            "provenance_note": None,
            "transport_health": "NOT_CONFIGURED",
            "requested_url": None,
            "final_url": None,
            "status": None,
            "content_type": None,
            "source_sha256": None,
            "programme_identity_verified_non_authorizing": False,
            "call_surface_authority": False,
            "call_fact_authorized": False,
            "error_type": None,
            "failure_class": None,
            "error": None,
        }
    return {
        "configured": True,
        "authority_url": fallback["url"],
        "authority_class": FALLBACK_AUTHORITY_CLASS,
        "surface_role": fallback["role"],
        "observation_state": FALLBACK_OBSERVATION_STATE,
        "provenance_note": fallback["note"],
        "transport_health": "NOT_USED_DIRECT_HEALTHY",
        "requested_url": fallback["url"],
        "final_url": None,
        "status": None,
        "content_type": None,
        "source_sha256": None,
        "programme_identity_verified_non_authorizing": False,
        "call_surface_authority": False,
        "call_fact_authorized": False,
        "error_type": None,
        "failure_class": None,
        "error": None,
    }


def collect(*, run_id: str, fetched_at: str | None = None, fetcher: Callable[[str], tuple[bytes, dict[str, Any]]] = default_fetch) -> tuple[dict[str, Any], dict[str, bytes]]:
    observed = fetched_at or utc_now()
    raw_by_id: dict[str, bytes] = {}
    surfaces: list[dict[str, Any]] = []

    for spec in SURFACES:
        base = {
            "programme_id": spec["id"],
            "programme": spec["programme"],
            "authority_url": spec["url"],
            "authority_class": AUTHORITY_CLASS,
            "surface_role": spec["surface_role"],
            "observation_state": spec["observation_state"],
            "programme_filter_required": spec["programme_filter_required"],
            "authority_note": spec["authority_note"],
            "observed_at": observed,
            "market_intelligence_only": True,
            "call_fact_authorized": False,
            "status_fact_authorized": False,
            "deadline_fact_authorized": False,
            "budget_fact_authorized": False,
            "eligibility_fact_authorized": False,
        }
        fallback_provenance = fallback_template(spec)
        try:
            raw, meta = fetcher(spec["url"])
            final_url = str(meta.get("final_url") or meta.get("requested_url") or "")
            if int(meta.get("status") or 0) != 200 or not host_allowed(final_url, spec["hosts"]):
                raise ValueError(f"{spec['id']} left its official call-discovery authority")
            require(html_text(raw), spec["anchors"], source=spec["programme"])
            raw_by_id[spec["id"]] = raw
            surfaces.append({
                **base,
                "transport_health": "HEALTHY",
                "requested_url": str(meta.get("requested_url") or spec["url"]),
                "final_url": final_url,
                "status": int(meta.get("status") or 200),
                "content_type": str(meta.get("content_type") or ""),
                "source_sha256": sha256_bytes(raw),
                "error_type": None,
                "failure_class": None,
                "error": None,
                "fallback_provenance": fallback_provenance,
            })
            continue
        except Exception as exc:
            failure_class = classify_failure(exc)
            direct_error = {
                "transport_health": "DEGRADED",
                "requested_url": spec["url"],
                "final_url": None,
                "status": None,
                "content_type": None,
                "source_sha256": None,
                "error_type": type(exc).__name__,
                "failure_class": failure_class,
                "error": str(exc)[:1000],
            }

        fallback = spec.get("fallback")
        if isinstance(fallback, Mapping):
            if failure_class == "VALIDATION_ERROR":
                fallback_provenance["transport_health"] = "NOT_ATTEMPTED_DIRECT_VALIDATION_FAILURE"
            else:
                try:
                    fallback_raw, fallback_meta = fetcher(str(fallback["url"]))
                    fallback_final = str(fallback_meta.get("final_url") or fallback_meta.get("requested_url") or "")
                    if int(fallback_meta.get("status") or 0) != 200 or not host_allowed(fallback_final, tuple(fallback["hosts"])):
                        raise ValueError(f"{spec['id']} fallback left Interreg/Interact registry authority")
                    require(html_text(fallback_raw), tuple(fallback["anchors"]), source=f"{spec['programme']} registry fallback")
                    raw_by_id[f"{spec['id']}__FALLBACK"] = fallback_raw
                    fallback_provenance.update({
                        "transport_health": "HEALTHY",
                        "requested_url": str(fallback_meta.get("requested_url") or fallback["url"]),
                        "final_url": fallback_final,
                        "status": int(fallback_meta.get("status") or 200),
                        "content_type": str(fallback_meta.get("content_type") or ""),
                        "source_sha256": sha256_bytes(fallback_raw),
                        "programme_identity_verified_non_authorizing": True,
                        "error_type": None,
                        "failure_class": None,
                        "error": None,
                    })
                except Exception as fallback_exc:
                    fallback_provenance.update({
                        "transport_health": "DEGRADED",
                        "requested_url": fallback["url"],
                        "final_url": None,
                        "status": None,
                        "content_type": None,
                        "source_sha256": None,
                        "programme_identity_verified_non_authorizing": False,
                        "error_type": type(fallback_exc).__name__,
                        "failure_class": classify_failure(fallback_exc),
                        "error": str(fallback_exc)[:1000],
                    })

        surfaces.append({
            **base,
            **direct_error,
            "fallback_provenance": fallback_provenance,
        })

    healthy = sum(1 for x in surfaces if x["transport_health"] == "HEALTHY")
    degraded = len(surfaces) - healthy
    fallback_configured = sum(1 for x in surfaces if x["fallback_provenance"]["configured"])
    fallback_attempted = sum(1 for x in surfaces if x["fallback_provenance"]["transport_health"] in {"HEALTHY", "DEGRADED"})
    fallback_healthy = sum(1 for x in surfaces if x["fallback_provenance"]["transport_health"] == "HEALTHY")
    fallback_degraded = sum(1 for x in surfaces if x["fallback_provenance"]["transport_health"] == "DEGRADED")
    degraded_with_healthy_fallback = sum(
        1 for x in surfaces
        if x["transport_health"] == "DEGRADED" and x["fallback_provenance"]["transport_health"] == "HEALTHY"
    )
    degraded_without_healthy_fallback = degraded - degraded_with_healthy_fallback

    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "fetched_at": observed,
        "run_id": run_id,
        "source_health": "HEALTHY" if degraded == 0 else "DEGRADED",
        "coverage_complete": degraded == 0,
        "call_surface_coverage_complete": degraded == 0,
        "fallback_does_not_restore_call_surface_coverage": True,
        "expected_surface_count": len(SURFACES),
        "healthy_surface_count": healthy,
        "degraded_surface_count": degraded,
        "fallback_configured_count": fallback_configured,
        "fallback_attempted_count": fallback_attempted,
        "fallback_healthy_count": fallback_healthy,
        "fallback_degraded_count": fallback_degraded,
        "degraded_direct_with_healthy_fallback_count": degraded_with_healthy_fallback,
        "degraded_direct_without_healthy_fallback_count": degraded_without_healthy_fallback,
        "market_intelligence_only": True,
        "surfaces": surfaces,
        "discovered_call_facts": [],
        "missing_for_open_call_confirmation": [
            "selected exact programme call identifier",
            "fresh current exact official call endpoint readback",
            "same-identity semantic reconciliation",
            "call-specific Romanian territory/applicant eligibility evidence",
            "field-scoped material admission",
        ],
        "publication_effect": "NONE",
    }
    for flag in MATERIAL_FLAGS:
        receipt[flag] = False
    receipt["semantic_fingerprint"] = sha256_json({
        "surfaces": [
            {
                "programme_id": x["programme_id"],
                "authority_url": x["authority_url"],
                "surface_role": x["surface_role"],
                "observation_state": x["observation_state"],
                "programme_filter_required": x["programme_filter_required"],
                "transport_health": x["transport_health"],
                "source_sha256": x["source_sha256"],
                "failure_class": x["failure_class"],
                "fallback_provenance": {
                    "configured": x["fallback_provenance"]["configured"],
                    "authority_url": x["fallback_provenance"]["authority_url"],
                    "surface_role": x["fallback_provenance"]["surface_role"],
                    "observation_state": x["fallback_provenance"]["observation_state"],
                    "transport_health": x["fallback_provenance"]["transport_health"],
                    "source_sha256": x["fallback_provenance"]["source_sha256"],
                    "failure_class": x["fallback_provenance"]["failure_class"],
                    "programme_identity_verified_non_authorizing": x["fallback_provenance"]["programme_identity_verified_non_authorizing"],
                    "call_surface_authority": x["fallback_provenance"]["call_surface_authority"],
                },
            }
            for x in surfaces
        ],
        "coverage_complete": receipt["coverage_complete"],
        "fallback_does_not_restore_call_surface_coverage": True,
    })
    validate_receipt(receipt)
    return receipt, raw_by_id


def validate_receipt(receipt: Mapping[str, Any]) -> None:
    if receipt.get("schema") != SCHEMA or receipt.get("parser_version") != PARSER_VERSION:
        raise ValueError("Interreg call-surface schema/parser drift")
    if receipt.get("source_family") != SOURCE_FAMILY or receipt.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("Interreg call-surface family drift")
    if receipt.get("authority_class") != AUTHORITY_CLASS or receipt.get("observation_state") != OBSERVATION_STATE:
        raise ValueError("Interreg call-surface authority/observation drift")
    if receipt.get("source_health") not in {"HEALTHY", "DEGRADED"} or receipt.get("market_intelligence_only") is not True or receipt.get("publication_effect") != "NONE":
        raise ValueError("Interreg call-surface watch crossed non-authorizing boundary")
    if receipt.get("discovered_call_facts") != []:
        raise ValueError("Interreg call-surface watch attempted to emit call facts")
    if receipt.get("fallback_does_not_restore_call_surface_coverage") is not True:
        raise ValueError("Interreg fallback attempted to restore call-surface authority")
    for flag in MATERIAL_FLAGS:
        if receipt.get(flag) is not False:
            raise ValueError(f"Interreg call-surface watch attempted authorization: {flag}")

    rows = receipt.get("surfaces")
    if not isinstance(rows, list) or len(rows) != len(SURFACES):
        raise ValueError("Interreg call-surface watch requires the canonical programme-surface set")
    specs = {x["id"]: x for x in SURFACES}
    if {x.get("programme_id") for x in rows} != set(specs):
        raise ValueError("Interreg call-surface programme set drift")

    healthy = 0
    degraded = 0
    fallback_configured = 0
    fallback_attempted = 0
    fallback_healthy = 0
    fallback_degraded = 0
    degraded_with_healthy_fallback = 0

    for row in rows:
        pid = str(row.get("programme_id") or "")
        spec = specs[pid]
        if row.get("authority_url") != spec["url"] or row.get("surface_role") != spec["surface_role"]:
            raise ValueError(f"Interreg call surface {pid} authority/role drift")
        if row.get("observation_state") != spec["observation_state"] or row.get("programme_filter_required") is not spec["programme_filter_required"]:
            raise ValueError(f"Interreg call surface {pid} observation/filter drift")
        if row.get("authority_note") != spec["authority_note"]:
            raise ValueError(f"Interreg call surface {pid} provenance note drift")
        if row.get("market_intelligence_only") is not True:
            raise ValueError(f"Interreg call surface {pid} escaped market-intelligence boundary")
        for field in ("call_fact_authorized", "status_fact_authorized", "deadline_fact_authorized", "budget_fact_authorized", "eligibility_fact_authorized"):
            if row.get(field) is not False:
                raise ValueError(f"Interreg call surface {pid} attempted field authorization: {field}")

        state = row.get("transport_health")
        if state == "HEALTHY":
            healthy += 1
            if int(row.get("status") or 0) != 200:
                raise ValueError(f"Interreg call surface {pid} healthy state lacks HTTP 200")
            if not host_allowed(str(row.get("final_url") or ""), spec["hosts"]):
                raise ValueError(f"Interreg call surface {pid} escaped official discovery authority")
            if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("source_sha256") or "")):
                raise ValueError(f"Interreg call surface {pid} lacks hash-bound evidence")
            if row.get("error") is not None or row.get("error_type") is not None or row.get("failure_class") is not None:
                raise ValueError(f"Interreg call surface {pid} healthy state carries an error")
        elif state == "DEGRADED":
            degraded += 1
            if row.get("source_sha256") is not None or row.get("status") is not None or row.get("final_url") is not None:
                raise ValueError(f"Interreg call surface {pid} degraded state retained partial authority facts")
            if not row.get("error_type") or not row.get("error") or not row.get("failure_class"):
                raise ValueError(f"Interreg call surface {pid} degraded state lacks transport evidence")
        else:
            raise ValueError(f"Interreg call surface {pid} invalid transport health")

        fb = row.get("fallback_provenance")
        if not isinstance(fb, Mapping):
            raise ValueError(f"Interreg call surface {pid} lacks fallback provenance contract")
        configured = isinstance(spec.get("fallback"), Mapping)
        if fb.get("configured") is not configured:
            raise ValueError(f"Interreg call surface {pid} fallback configuration drift")
        if fb.get("authority_class") != FALLBACK_AUTHORITY_CLASS or fb.get("observation_state") != FALLBACK_OBSERVATION_STATE:
            raise ValueError(f"Interreg call surface {pid} fallback authority/observation drift")
        if fb.get("call_surface_authority") is not False or fb.get("call_fact_authorized") is not False:
            raise ValueError(f"Interreg call surface {pid} fallback attempted call authority")
        if configured:
            fallback_configured += 1
            fallback = spec["fallback"]
            if fb.get("authority_url") != fallback["url"] or fb.get("surface_role") != fallback["role"] or fb.get("provenance_note") != fallback["note"]:
                raise ValueError(f"Interreg call surface {pid} fallback provenance drift")
        else:
            if fb.get("authority_url") is not None or fb.get("surface_role") is not None or fb.get("provenance_note") is not None:
                raise ValueError(f"Interreg call surface {pid} unexpected fallback provenance")

        fb_state = fb.get("transport_health")
        if state == "HEALTHY":
            expected_fb_state = "NOT_USED_DIRECT_HEALTHY" if configured else "NOT_CONFIGURED"
            if fb_state != expected_fb_state:
                raise ValueError(f"Interreg call surface {pid} healthy direct read unexpectedly used fallback")
        elif not configured:
            if fb_state != "NOT_CONFIGURED":
                raise ValueError(f"Interreg call surface {pid} unconfigured fallback drift")
        elif row.get("failure_class") == "VALIDATION_ERROR":
            if fb_state != "NOT_ATTEMPTED_DIRECT_VALIDATION_FAILURE":
                raise ValueError(f"Interreg call surface {pid} validation failure incorrectly used fallback")
        elif fb_state not in {"HEALTHY", "DEGRADED"}:
            raise ValueError(f"Interreg call surface {pid} transport failure lacks fallback attempt")

        if fb_state in {"HEALTHY", "DEGRADED"}:
            fallback_attempted += 1
        if fb_state == "HEALTHY":
            fallback_healthy += 1
            if int(fb.get("status") or 0) != 200:
                raise ValueError(f"Interreg call surface {pid} healthy fallback lacks HTTP 200")
            if not host_allowed(str(fb.get("final_url") or ""), tuple(spec["fallback"]["hosts"])):
                raise ValueError(f"Interreg call surface {pid} fallback escaped Interreg/Interact authority")
            if not re.fullmatch(r"[0-9a-f]{64}", str(fb.get("source_sha256") or "")):
                raise ValueError(f"Interreg call surface {pid} fallback lacks hash-bound evidence")
            if fb.get("programme_identity_verified_non_authorizing") is not True:
                raise ValueError(f"Interreg call surface {pid} healthy fallback did not bind programme identity")
            if fb.get("error") is not None or fb.get("error_type") is not None or fb.get("failure_class") is not None:
                raise ValueError(f"Interreg call surface {pid} healthy fallback carries an error")
            if state == "DEGRADED":
                degraded_with_healthy_fallback += 1
        elif fb_state == "DEGRADED":
            fallback_degraded += 1
            if fb.get("source_sha256") is not None or fb.get("status") is not None or fb.get("final_url") is not None:
                raise ValueError(f"Interreg call surface {pid} degraded fallback retained partial authority facts")
            if fb.get("programme_identity_verified_non_authorizing") is not False or not fb.get("error_type") or not fb.get("failure_class") or not fb.get("error"):
                raise ValueError(f"Interreg call surface {pid} degraded fallback lacks failure evidence")
        else:
            if fb.get("source_sha256") is not None or fb.get("status") is not None or fb.get("final_url") is not None:
                raise ValueError(f"Interreg call surface {pid} unused fallback retained partial evidence")
            if fb.get("programme_identity_verified_non_authorizing") is not False:
                raise ValueError(f"Interreg call surface {pid} unused fallback claimed programme identity")

    if receipt.get("healthy_surface_count") != healthy or receipt.get("degraded_surface_count") != degraded:
        raise ValueError("Interreg call-surface health counters drift")
    if receipt.get("expected_surface_count") != len(SURFACES):
        raise ValueError("Interreg call-surface expected count drift")
    if receipt.get("coverage_complete") is not (degraded == 0) or receipt.get("call_surface_coverage_complete") is not (degraded == 0):
        raise ValueError("Interreg call-surface coverage flag drift")
    if receipt.get("source_health") != ("HEALTHY" if degraded == 0 else "DEGRADED"):
        raise ValueError("Interreg call-surface aggregate health drift")
    if receipt.get("fallback_configured_count") != fallback_configured:
        raise ValueError("Interreg fallback configured counter drift")
    if receipt.get("fallback_attempted_count") != fallback_attempted or receipt.get("fallback_healthy_count") != fallback_healthy or receipt.get("fallback_degraded_count") != fallback_degraded:
        raise ValueError("Interreg fallback health counters drift")
    if receipt.get("degraded_direct_with_healthy_fallback_count") != degraded_with_healthy_fallback:
        raise ValueError("Interreg fallback-covered direct degradation counter drift")
    if receipt.get("degraded_direct_without_healthy_fallback_count") != degraded - degraded_with_healthy_fallback:
        raise ValueError("Interreg fallback-uncovered direct degradation counter drift")

    stable = {
        "surfaces": [
            {
                "programme_id": x["programme_id"],
                "authority_url": x["authority_url"],
                "surface_role": x["surface_role"],
                "observation_state": x["observation_state"],
                "programme_filter_required": x["programme_filter_required"],
                "transport_health": x["transport_health"],
                "source_sha256": x["source_sha256"],
                "failure_class": x["failure_class"],
                "fallback_provenance": {
                    "configured": x["fallback_provenance"]["configured"],
                    "authority_url": x["fallback_provenance"]["authority_url"],
                    "surface_role": x["fallback_provenance"]["surface_role"],
                    "observation_state": x["fallback_provenance"]["observation_state"],
                    "transport_health": x["fallback_provenance"]["transport_health"],
                    "source_sha256": x["fallback_provenance"]["source_sha256"],
                    "failure_class": x["fallback_provenance"]["failure_class"],
                    "programme_identity_verified_non_authorizing": x["fallback_provenance"]["programme_identity_verified_non_authorizing"],
                    "call_surface_authority": x["fallback_provenance"]["call_surface_authority"],
                },
            }
            for x in rows
        ],
        "coverage_complete": receipt.get("coverage_complete"),
        "fallback_does_not_restore_call_surface_coverage": True,
    }
    if receipt.get("semantic_fingerprint") != sha256_json(stable):
        raise ValueError("Interreg call-surface semantic fingerprint mismatch")


def write_outputs(receipt: Mapping[str, Any], raw_by_id: Mapping[str, bytes], out_dir: pathlib.Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "interreg-romania-call-surface-watch.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(exist_ok=True)
    for pid, raw in raw_by_id.items():
        safe_pid = pid.replace("__FALLBACK", "-fallback")
        (raw_dir / f"{safe_pid}.html").write_bytes(raw)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    receipt, raw_by_id = collect(run_id=args.run_id)
    write_outputs(receipt, raw_by_id, pathlib.Path(args.out_dir))
    print(json.dumps({
        "schema": receipt["schema"],
        "source_health": receipt["source_health"],
        "healthy_surface_count": receipt["healthy_surface_count"],
        "degraded_surface_count": receipt["degraded_surface_count"],
        "fallback_attempted_count": receipt["fallback_attempted_count"],
        "fallback_healthy_count": receipt["fallback_healthy_count"],
        "fallback_degraded_count": receipt["fallback_degraded_count"],
        "coverage_complete": receipt["coverage_complete"],
        "semantic_fingerprint": receipt["semantic_fingerprint"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
