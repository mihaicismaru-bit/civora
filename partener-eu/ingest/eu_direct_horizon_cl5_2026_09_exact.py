#!/usr/bin/env python3
"""Exact current Horizon Europe call evidence for HORIZON-CL5-2026-09.

This is a bounded acquisition-only adapter. It cross-checks the exact official
CINEA call page with the European Commission Funding & Tenders Search/Facet
APIs for the same call identifier. It may expose an upstream candidate state
for semantic review, but it never authorizes status, deadline, budget,
eligibility, publication, distribution, alerts, or corpus mutation.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping

import funding_tenders_fetch as ft

SCHEMA = "PARTENER_EU_HORIZON_CL5_2026_09_EXACT_EVIDENCE_V1"
PARSER_VERSION = "EU_DIRECT_HORIZON_CL5_2026_09_EXACT_V1"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "HORIZON_EUROPE_CLUSTER5"
AUTHORITY_CLASS = "EU_COMMISSION_CINEA_PLUS_FUNDING_TENDERS"
OBSERVATION_LAYER = "EXACT_CURRENT_CALL_NON_AUTHORIZING"
CALL_IDENTIFIER = "HORIZON-CL5-2026-09"
CINEA_URL = (
    "https://cinea.ec.europa.eu/funding-opportunities/calls-proposals/"
    "eur-2232-m-cross-sectoral-solutions-climate-transition-sustainable-secure-and-competitive-energy_en"
)
FT_CALL_URL = (
    "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/"
    "calls-for-proposals?callIdentifier=HORIZON-CL5-2026-09&frameworkProgramme=43108390&"
    "isExactMatch=true"
)
PROGRAMME_CODE_EXPECTED = "43108390"
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


class ExactCallConflict(ValueError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def _scalar(value: Any) -> str | None:
    return ft._scalar(value)


def _first_scalar(record: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _scalar(record.get(key))
        if value:
            return value
    return None


def _record_type(record: Mapping[str, Any]) -> str | None:
    return _scalar(record.get("type"))


def _record_programme_reference(record: Mapping[str, Any]) -> str | None:
    for key in ("frameworkProgramme", "programme", "programmeReference"):
        value = _scalar(record.get(key))
        if value:
            return value
    return None


def _record_call_identifier(record: Mapping[str, Any]) -> str | None:
    return _first_scalar(record, "callIdentifier", "callId", "callReference")


def _framework_programme_map(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("official Facet response must be an object")
    facets = payload.get("facets")
    if not isinstance(facets, list):
        raise ValueError("official Facet response is missing facets")
    matches = [f for f in facets if isinstance(f, dict) and f.get("name") == "frameworkProgramme"]
    if len(matches) != 1:
        raise ValueError(f"expected one frameworkProgramme facet, found {len(matches)}")
    values = matches[0].get("values")
    if not isinstance(values, list) or not values:
        raise ValueError("frameworkProgramme facet has no values")
    result: dict[str, str] = {}
    for row in values:
        if not isinstance(row, dict):
            continue
        code = _scalar(row.get("rawValue"))
        label = _scalar(row.get("value"))
        if not code or not label or label == code or label.isdigit():
            continue
        previous = result.get(code)
        if previous and previous != label:
            raise ValueError(f"ambiguous programme label for {code}: {previous!r} vs {label!r}")
        result[code] = label
    if not result:
        raise ValueError("frameworkProgramme facet yielded no readable labels")
    return result


def _is_horizon_europe_label(label: str) -> bool:
    token = re.sub(r"[^a-z0-9]+", " ", label.casefold()).strip()
    return "horizon europe" in token


def reference_query() -> dict[str, Any]:
    return {
        "bool": {
            "must": [
                {"terms": {"type": list(ft.CALL_TYPES)}},
                {"term": {"programmePeriod": "2021 - 2027"}},
            ]
        }
    }


def _normalise_html(raw: bytes) -> str:
    decoded = html.unescape(raw.decode("utf-8", errors="replace"))
    decoded = re.sub(r"<script\b[^>]*>.*?</script>", " ", decoded, flags=re.I | re.S)
    decoded = re.sub(r"<style\b[^>]*>.*?</style>", " ", decoded, flags=re.I | re.S)
    decoded = re.sub(r"<[^>]+>", " ", decoded)
    return re.sub(r"\s+", " ", decoded).strip()


def _status_from_cinea_text(text: str) -> str | None:
    match = re.search(r"\bstatus\s+(open|closed|forthcoming)\b", text, flags=re.I)
    if not match:
        return None
    token = match.group(1).casefold()
    return {"open": "Open", "closed": "Closed", "forthcoming": "Forthcoming"}[token]


def _deadline_from_cinea_text(text: str) -> str | None:
    match = re.search(
        r"\bdeadline date\s+([0-9]{1,2}\s+[A-Za-z]+\s+20[0-9]{2},\s*[0-9]{1,2}:[0-9]{2}\s*\([A-Z]{2,5}\))",
        text,
        flags=re.I,
    )
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else None


def default_cinea_fetch(url: str, timeout: float = 30.0) -> tuple[bytes, dict[str, Any]]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "cinea.ec.europa.eu":
        raise ValueError("CINEA URL left the declared official authority")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "PARTENER.EU-HorizonExact/1.0 (+https://partener.eu)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read(3_000_001)
        if len(raw) > 3_000_000:
            raise ValueError("CINEA exact page exceeds 3 MB evidence limit")
        final_url = str(response.geturl())
        final = urllib.parse.urlparse(final_url)
        if final.scheme != "https" or final.hostname != "cinea.ec.europa.eu":
            raise ValueError("CINEA exact page redirected outside official authority")
        status = int(getattr(response, "status", 200) or 200)
        ctype = str(response.headers.get("Content-Type") or "")
    if status != 200:
        raise ValueError(f"CINEA exact page HTTP {status}")
    return raw, {
        "requested_url": url,
        "final_url": final_url,
        "http_status": status,
        "content_type": ctype,
        "bytes": len(raw),
        "sha256": sha256_bytes(raw),
    }


def _cinea_readback(
    *,
    fetcher: Callable[[str], tuple[bytes, dict[str, Any]]] = default_cinea_fetch,
) -> tuple[dict[str, Any], bytes | None]:
    try:
        raw, receipt = fetcher(CINEA_URL)
        text = _normalise_html(raw)
        lowered = text.casefold()
        required = (CALL_IDENTIFIER.casefold(), "call for proposals", "horizon europe")
        missing = [marker for marker in required if marker not in lowered]
        status_label = _status_from_cinea_text(text)
        if missing or not status_label:
            return {
                "verified": False,
                "url": CINEA_URL,
                "receipt": receipt,
                "status_label": None,
                "deadline_text": None,
                "error": f"marker/status mismatch: missing={missing}, status={status_label!r}",
            }, raw
        return {
            "verified": True,
            "url": CINEA_URL,
            "receipt": receipt,
            "status_label": status_label,
            "deadline_text": _deadline_from_cinea_text(text),
            "error": None,
        }, raw
    except (ValueError, OSError, urllib.error.URLError) as exc:
        return {
            "verified": False,
            "url": CINEA_URL,
            "receipt": None,
            "status_label": None,
            "deadline_text": None,
            "error": f"{type(exc).__name__}: {exc}",
        }, None


def _candidate_state(status_label: str | None) -> str:
    return {"Open": "OPEN_CALL", "Closed": "CLOSED_CALL", "Forthcoming": "FORTHCOMING_CALL"}.get(
        str(status_label or ""), "UNKNOWN"
    )


def _structured_snapshot(
    *,
    search_payload: Any,
    facet_payload: Any,
) -> dict[str, Any]:
    rows = [
        row for row in ft.flatten_search_payload(search_payload)
        if str(_record_call_identifier(row) or "").upper() == CALL_IDENTIFIER
        and _record_type(row) in {"1", "2"}
    ]
    if not rows:
        raise ValueError(f"Funding & Tenders returned no direct records for {CALL_IDENTIFIER}")
    programme_labels = _framework_programme_map(facet_payload)
    topics: list[dict[str, Any]] = []
    for row in rows:
        programme_ref = _record_programme_reference(row)
        programme_label = programme_labels.get(programme_ref or "")
        if programme_ref != PROGRAMME_CODE_EXPECTED or not programme_label or not _is_horizon_europe_label(programme_label):
            raise ValueError(
                f"record is not proven Horizon Europe: {programme_ref!r} {programme_label!r}"
            )
        status_code = ft._record_status_code(row)
        status_label = ft.resolve_reference_label([facet_payload], status_code or "") if status_code else None
        if not status_label:
            raise ValueError("Funding & Tenders Facet did not resolve current status")
        identifier = str(ft._record_identifier(row) or "").upper()
        if not identifier or not identifier.startswith(CALL_IDENTIFIER + "-"):
            raise ValueError(f"unexpected topic identity under exact call: {identifier!r}")
        topics.append({
            "identifier": identifier,
            "record_type": _record_type(row),
            "status_code": status_code,
            "status_label": status_label,
            "title": _first_scalar(row, "title", "topicTitle", "name"),
            "deadline_candidate": _first_scalar(row, "deadlineDate", "deadlineDates", "deadline"),
            "budget_candidate": _first_scalar(row, "budget", "budgetOverview", "topicBudget", "callBudget"),
        })
    dedup: dict[str, dict[str, Any]] = {}
    for topic in topics:
        key = topic["identifier"]
        previous = dedup.get(key)
        if previous and sha256_json(previous) != sha256_json(topic):
            raise ExactCallConflict(f"conflicting structured rows for topic {key}")
        dedup[key] = topic
    topics = [dedup[key] for key in sorted(dedup)]
    status_labels = sorted({str(row["status_label"]) for row in topics})
    if len(status_labels) != 1:
        raise ExactCallConflict(f"mixed Funding & Tenders status labels for {CALL_IDENTIFIER}: {status_labels}")
    return {
        "call_identifier": CALL_IDENTIFIER,
        "programme_reference": PROGRAMME_CODE_EXPECTED,
        "programme_label": programme_labels[PROGRAMME_CODE_EXPECTED],
        "topic_count": len(topics),
        "topic_identifiers": [row["identifier"] for row in topics],
        "status_label": status_labels[0],
        "topic_rows": topics,
        "topic_semantic_hashes": [sha256_json(row) for row in topics],
    }


def collect_exact(
    *,
    run_id: str,
    fetched_at: str | None = None,
    output_dir: pathlib.Path | None = None,
    post_func: Callable[..., tuple[Any, bytes, dict[str, Any]]] = ft._safe_json_post,
    cinea_fetcher: Callable[[str], tuple[bytes, dict[str, Any]]] = default_cinea_fetch,
) -> dict[str, Any]:
    fetched_at = fetched_at or utc_now()
    cinea, cinea_raw = _cinea_readback(fetcher=cinea_fetcher)
    search_payload = facet_payload = None
    search_raw = facet_raw = None
    search_receipt = facet_receipt = None
    structured: dict[str, Any] | None = None
    structured_error: str | None = None
    try:
        parts = {"query": reference_query(), "languages": ["en"]}
        search_payload, search_raw, search_receipt = post_func(
            ft.SEARCH_ENDPOINT, text=CALL_IDENTIFIER, page_size=50, page_number=1, parts=parts
        )
        facet_payload, facet_raw, facet_receipt = post_func(
            ft.FACET_ENDPOINT, text=CALL_IDENTIFIER, page_size=50, page_number=1, parts=parts
        )
        structured = _structured_snapshot(search_payload=search_payload, facet_payload=facet_payload)
    except (ValueError, OSError, urllib.error.URLError) as exc:
        structured_error = f"{type(exc).__name__}: {exc}"

    agreement = bool(
        cinea.get("verified") is True
        and structured is not None
        and cinea.get("status_label") == structured.get("status_label")
    )
    healthy = agreement
    if healthy:
        status_label = str(cinea["status_label"])
        exact_semantics = {
            "call_identifier": CALL_IDENTIFIER,
            "candidate_state": _candidate_state(status_label),
            "status_label": status_label,
            "cinea_authority_url": CINEA_URL,
            "funding_tenders_call_url": FT_CALL_URL,
            "cinea_deadline_text": cinea.get("deadline_text"),
            "programme_reference": structured.get("programme_reference"),
            "programme_label": structured.get("programme_label"),
            "topic_count": structured.get("topic_count"),
            "topic_identifiers": structured.get("topic_identifiers"),
            "topic_semantic_hashes": structured.get("topic_semantic_hashes"),
        }
        source_health_state = "HEALTHY"
        candidate_state = _candidate_state(status_label)
        deadline_candidate = cinea.get("deadline_text")
        lkg_required = False
        evidence_usable = True
        degradation_reason = None
    else:
        exact_semantics = {
            "call_identifier": CALL_IDENTIFIER,
            "candidate_state": "UNKNOWN",
            "status_label": None,
            "cinea_authority_url": CINEA_URL,
            "funding_tenders_call_url": FT_CALL_URL,
        }
        source_health_state = "DEGRADED_SEMANTIC_OR_TRANSPORT"
        candidate_state = "UNKNOWN"
        status_label = None
        deadline_candidate = None
        lkg_required = True
        evidence_usable = False
        reasons = [x for x in (str(cinea.get("error") or ""), structured_error or "") if x]
        if cinea.get("verified") is True and structured is not None and not agreement:
            reasons.append(
                f"status disagreement CINEA={cinea.get('status_label')!r} F&T={structured.get('status_label')!r}"
            )
        degradation_reason = "; ".join(reasons) or "exact authorities did not produce an agreeing current state"

    evidence: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_LAYER,
        "call_identifier": CALL_IDENTIFIER,
        "fetched_at": fetched_at,
        "run_id": run_id,
        "cinea_authority_url": CINEA_URL,
        "funding_tenders_call_url": FT_CALL_URL,
        "cinea_readback": cinea,
        "search_receipt": search_receipt,
        "facet_receipt": facet_receipt,
        "search_raw_sha256": sha256_bytes(search_raw) if search_raw is not None else None,
        "facet_raw_sha256": sha256_bytes(facet_raw) if facet_raw is not None else None,
        "structured_snapshot": structured,
        "structured_error": structured_error,
        "authority_agreement_verified": agreement,
        "source_health_state": source_health_state,
        "lkg_required": lkg_required,
        "evidence_usable_for_reconciliation": evidence_usable,
        "degradation_reason": degradation_reason,
        "candidate_state": candidate_state,
        "status_label": status_label,
        "deadline_candidate": deadline_candidate,
        "budget_candidate": None,
        "exact_semantics": exact_semantics,
        "exact_semantic_fingerprint": sha256_json(exact_semantics),
        "semantic_reconciliation_required": True,
        "field_scoped_material_admission_required": True,
        "material_admission_ready_for_downstream_review": False,
        "market_intelligence_only": True,
        "publication_effect": "NONE",
    }
    for key in MATERIAL_FLAGS:
        evidence[key] = False
    validate_evidence(evidence)

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        if cinea_raw is not None:
            (output_dir / "cinea-exact-page.html").write_bytes(cinea_raw)
        if search_raw is not None:
            (output_dir / "ft-search-response.json").write_bytes(search_raw)
        if facet_raw is not None:
            (output_dir / "ft-facet-response.json").write_bytes(facet_raw)
        (output_dir / "horizon-cl5-2026-09-exact-evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
    return evidence


def validate_evidence(evidence: Mapping[str, Any]) -> None:
    if evidence.get("schema") != SCHEMA or evidence.get("parser_version") != PARSER_VERSION:
        raise ValueError("Horizon CL5 exact evidence schema/parser drift")
    if evidence.get("source_family") != SOURCE_FAMILY or evidence.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("Horizon CL5 exact evidence family drift")
    if evidence.get("call_identifier") != CALL_IDENTIFIER:
        raise ValueError("Horizon CL5 exact call identifier drift")
    if evidence.get("cinea_authority_url") != CINEA_URL or evidence.get("funding_tenders_call_url") != FT_CALL_URL:
        raise ValueError("Horizon CL5 exact authority URL drift")
    usable = evidence.get("evidence_usable_for_reconciliation")
    if usable not in {True, False}:
        raise ValueError("Horizon CL5 exact evidence usability missing")
    if usable:
        if evidence.get("source_health_state") != "HEALTHY" or evidence.get("lkg_required") is not False:
            raise ValueError("healthy Horizon CL5 source-health binding invalid")
        if evidence.get("authority_agreement_verified") is not True:
            raise ValueError("healthy Horizon CL5 evidence lacks authority agreement")
        cinea = evidence.get("cinea_readback") or {}
        structured = evidence.get("structured_snapshot") or {}
        if cinea.get("verified") is not True or cinea.get("status_label") != structured.get("status_label"):
            raise ValueError("healthy Horizon CL5 authority agreement binding invalid")
        if evidence.get("candidate_state") not in {"OPEN_CALL", "CLOSED_CALL", "FORTHCOMING_CALL"}:
            raise ValueError("healthy Horizon CL5 candidate state unsupported")
        if not evidence.get("status_label") or not structured.get("topic_identifiers"):
            raise ValueError("healthy Horizon CL5 evidence missing current structured semantics")
        for receipt_key in ("search_receipt", "facet_receipt"):
            receipt = evidence.get(receipt_key) or {}
            if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("sha256") or "")):
                raise ValueError(f"healthy Horizon CL5 evidence lacks immutable {receipt_key}")
    else:
        if evidence.get("source_health_state") != "DEGRADED_SEMANTIC_OR_TRANSPORT" or evidence.get("lkg_required") is not True:
            raise ValueError("degraded Horizon CL5 evidence lacks LKG/source-health binding")
        if evidence.get("candidate_state") != "UNKNOWN" or evidence.get("status_label") is not None:
            raise ValueError("degraded Horizon CL5 evidence leaked current status")
        if evidence.get("deadline_candidate") is not None or evidence.get("budget_candidate") is not None:
            raise ValueError("degraded Horizon CL5 evidence leaked current material candidates")
        if not evidence.get("degradation_reason"):
            raise ValueError("degraded Horizon CL5 evidence lacks degradation reason")
    semantics = evidence.get("exact_semantics")
    if not isinstance(semantics, dict) or sha256_json(semantics) != evidence.get("exact_semantic_fingerprint"):
        raise ValueError("Horizon CL5 exact semantic fingerprint mismatch")
    if evidence.get("semantic_reconciliation_required") is not True or evidence.get("field_scoped_material_admission_required") is not True:
        raise ValueError("Horizon CL5 exact evidence skipped downstream gates")
    if evidence.get("material_admission_ready_for_downstream_review") is not False:
        raise ValueError("raw Horizon CL5 evidence cannot self-admit material facts")
    if evidence.get("market_intelligence_only") is not True:
        raise ValueError("Horizon CL5 exact evidence left market-intelligence boundary")
    for key in MATERIAL_FLAGS:
        if evidence.get(key) is not False:
            raise ValueError(f"Horizon CL5 exact evidence attempted authorization: {key}")
    if evidence.get("publication_effect") != "NONE":
        raise ValueError("Horizon CL5 exact evidence crossed publication boundary")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    parser.add_argument("--run-id", default="horizon-cl5-2026-09-exact-live")
    args = parser.parse_args()
    evidence = collect_exact(run_id=args.run_id, output_dir=args.output_dir)
    print(json.dumps({
        "call_identifier": evidence["call_identifier"],
        "source_health_state": evidence["source_health_state"],
        "candidate_state": evidence["candidate_state"],
        "status_label": evidence["status_label"],
        "deadline_candidate": evidence["deadline_candidate"],
        "authority_agreement_verified": evidence["authority_agreement_verified"],
        "exact_semantic_fingerprint": evidence["exact_semantic_fingerprint"],
        "open_call_authorized": evidence["open_call_authorized"],
        "publication_effect": evidence["publication_effect"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
