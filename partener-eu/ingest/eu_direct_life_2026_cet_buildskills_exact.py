#!/usr/bin/env python3
"""Exact official LIFE 2026 CET BUILDUP Skills topic evidence.

Bounded acquisition-only adapter for LIFE-2026-CET-BUILDSKILLS. It cross-checks
the exact CINEA call page with the European Commission Funding & Tenders
Search/Facet APIs for the same exact topic identifier. Upstream status/deadline
may be observed as candidates for semantic review, but this module never
authorizes material facts, publication, distribution, alerts, or corpus mutation.
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

SCHEMA = "PARTENER_EU_LIFE_2026_CET_BUILDSKILLS_EXACT_EVIDENCE_V1"
PARSER_VERSION = "EU_DIRECT_LIFE_2026_CET_BUILDSKILLS_EXACT_V1"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "LIFE_CLEAN_ENERGY_TRANSITION"
AUTHORITY_CLASS = "EU_COMMISSION_CINEA_PLUS_FUNDING_TENDERS"
OBSERVATION_STATE = "EXACT_CURRENT_TOPIC_CANDIDATE_NON_AUTHORIZING"
TOPIC_IDENTIFIER = "LIFE-2026-CET-BUILDSKILLS"
CINEA_URL = (
    "https://cinea.ec.europa.eu/funding-opportunities/calls-proposals/"
    "build-skills-national-platforms-energy-efficiency-skills-clean-energy-transition_en"
)
FT_TOPIC_URL = (
    "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/"
    "topic-details/LIFE-2026-CET-BUILDSKILLS"
)
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


class ExactTopicConflict(ValueError):
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


def _record_programme_reference(record: Mapping[str, Any]) -> str | None:
    return _first_scalar(record, "frameworkProgramme", "programme", "programmeReference")


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


def _is_life_label(label: str) -> bool:
    token = re.sub(r"[^a-z0-9]+", " ", label.casefold()).strip()
    return "life" in token.split() and "environment" in token and "climate action" in token


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
            "User-Agent": "PARTENER.EU-LIFEExact/1.0 (+https://partener.eu)",
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
    *, fetcher: Callable[[str], tuple[bytes, dict[str, Any]]] = default_cinea_fetch,
) -> tuple[dict[str, Any], bytes | None]:
    try:
        raw, receipt = fetcher(CINEA_URL)
        text = _normalise_html(raw)
        lowered = text.casefold()
        required = (
            TOPIC_IDENTIFIER.casefold(),
            "call for proposals",
            "programme for the environment and climate action",
            "life",
        )
        missing = [marker for marker in required if marker not in lowered]
        status_label = _status_from_cinea_text(text)
        deadline = _deadline_from_cinea_text(text)
        if missing or not status_label or not deadline:
            return {
                "verified": False,
                "url": CINEA_URL,
                "receipt": receipt,
                "status_label": None,
                "deadline_text": None,
                "error": f"marker/status/deadline mismatch: missing={missing}, status={status_label!r}, deadline={deadline!r}",
            }, raw
        return {
            "verified": True,
            "url": CINEA_URL,
            "receipt": receipt,
            "status_label": status_label,
            "deadline_text": deadline,
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


def _structured_snapshot(*, search_payload: Any, facet_payload: Any) -> dict[str, Any]:
    rows = [
        row for row in ft.flatten_search_payload(search_payload)
        if str(ft._record_identifier(row) or "").upper() == TOPIC_IDENTIFIER
        and str(_scalar(row.get("type")) or "") in {"1", "2"}
    ]
    if not rows:
        raise ValueError(f"Funding & Tenders returned no exact record for {TOPIC_IDENTIFIER}")
    programme_labels = _framework_programme_map(facet_payload)
    normalized: list[dict[str, Any]] = []
    for row in rows:
        programme_ref = _record_programme_reference(row)
        programme_label = programme_labels.get(programme_ref or "")
        if not programme_ref or not programme_label or not _is_life_label(programme_label):
            raise ValueError(f"record is not proven LIFE programme: {programme_ref!r} {programme_label!r}")
        status_code = ft._record_status_code(row)
        status_label = ft.resolve_reference_label([facet_payload], status_code or "") if status_code else None
        if not status_label:
            raise ValueError("Funding & Tenders Facet did not resolve current status")
        normalized.append({
            "topic_identifier": TOPIC_IDENTIFIER,
            "call_identifier": _record_call_identifier(row),
            "record_type": _scalar(row.get("type")),
            "programme_reference": programme_ref,
            "programme_label": programme_label,
            "status_code": status_code,
            "status_label": status_label,
            "title": _first_scalar(row, "title", "topicTitle", "name"),
            "deadline_candidate": _first_scalar(row, "deadlineDate", "deadlineDates", "deadline"),
            "budget_candidate": _first_scalar(row, "budget", "budgetOverview", "topicBudget", "callBudget"),
        })
    semantic_hashes = {sha256_json(row) for row in normalized}
    if len(semantic_hashes) != 1:
        raise ExactTopicConflict(f"conflicting exact Funding & Tenders rows for {TOPIC_IDENTIFIER}")
    result = normalized[0]
    result["duplicate_exact_row_count"] = len(normalized)
    return result


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
            ft.SEARCH_ENDPOINT, text=TOPIC_IDENTIFIER, page_size=50, page_number=1, parts=parts
        )
        facet_payload, facet_raw, facet_receipt = post_func(
            ft.FACET_ENDPOINT, text=TOPIC_IDENTIFIER, page_size=50, page_number=1, parts=parts
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
            "topic_identifier": TOPIC_IDENTIFIER,
            "call_identifier": structured.get("call_identifier"),
            "candidate_state": _candidate_state(status_label),
            "status_label": status_label,
            "cinea_authority_url": CINEA_URL,
            "funding_tenders_topic_url": FT_TOPIC_URL,
            "cinea_deadline_text": cinea.get("deadline_text"),
            "programme_reference": structured.get("programme_reference"),
            "programme_label": structured.get("programme_label"),
            "structured_deadline_candidate": structured.get("deadline_candidate"),
            "title": structured.get("title"),
        }
        source_health_state = "HEALTHY"
        candidate_state = _candidate_state(status_label)
        deadline_candidate = cinea.get("deadline_text")
        lkg_required = False
        evidence_usable = True
        degradation_reason = None
    else:
        exact_semantics = {
            "topic_identifier": TOPIC_IDENTIFIER,
            "call_identifier": None,
            "candidate_state": "UNKNOWN",
            "status_label": None,
            "cinea_authority_url": CINEA_URL,
            "funding_tenders_topic_url": FT_TOPIC_URL,
            "cinea_deadline_text": None,
            "programme_reference": None,
            "programme_label": None,
            "structured_deadline_candidate": None,
            "title": None,
        }
        source_health_state = "DEGRADED_SEMANTIC_OR_TRANSPORT"
        candidate_state = "UNKNOWN"
        deadline_candidate = None
        lkg_required = True
        evidence_usable = False
        reasons: list[str] = []
        if cinea.get("verified") is not True:
            reasons.append(f"CINEA exact evidence unusable: {cinea.get('error')}")
        if structured is None:
            reasons.append(f"Funding & Tenders exact evidence unusable: {structured_error}")
        elif cinea.get("verified") is True and cinea.get("status_label") != structured.get("status_label"):
            reasons.append(
                f"authority status disagreement: CINEA={cinea.get('status_label')!r}, F&T={structured.get('status_label')!r}"
            )
        degradation_reason = "; ".join(reasons) or "exact authority agreement not proven"

    flags = {key: False for key in MATERIAL_FLAGS}
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
        "fetched_at": fetched_at,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "topic_identifier": TOPIC_IDENTIFIER,
        "cinea_authority_url": CINEA_URL,
        "funding_tenders_topic_url": FT_TOPIC_URL,
        "source_health_state": source_health_state,
        "authority_agreement_verified": agreement,
        "evidence_usable_for_reconciliation": evidence_usable,
        "candidate_state": candidate_state,
        "status_label": str(cinea.get("status_label")) if healthy else None,
        "deadline_candidate": deadline_candidate,
        "structured_snapshot": structured if healthy else None,
        "cinea_snapshot": cinea,
        "source_receipts": {
            "cinea": cinea.get("receipt"),
            "funding_tenders_search": search_receipt,
            "funding_tenders_facet": facet_receipt,
        },
        "exact_semantics": exact_semantics,
        "exact_semantic_fingerprint": sha256_json(exact_semantics),
        "semantic_reconciliation_required": True,
        "field_scoped_material_admission_required": True,
        "material_admission_ready_for_downstream_review": False,
        "lkg_required": lkg_required,
        "lkg_is_current_truth": False,
        "market_intelligence_only": True,
        "degradation_reason": degradation_reason,
        **flags,
        "publication_effect": "NONE",
    }
    validate_evidence(result)

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "life-2026-cet-buildskills-exact-evidence.json").write_text(
            json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        if cinea_raw is not None:
            (output_dir / "life-2026-cet-buildskills-cinea.html").write_bytes(cinea_raw)
        if search_raw is not None:
            (output_dir / "life-2026-cet-buildskills-ft-search.json").write_bytes(search_raw)
        if facet_raw is not None:
            (output_dir / "life-2026-cet-buildskills-ft-facet.json").write_bytes(facet_raw)
    return result


def validate_evidence(result: Mapping[str, Any]) -> None:
    if result.get("schema") != SCHEMA or result.get("parser_version") != PARSER_VERSION:
        raise ValueError("LIFE BUILDUP Skills exact evidence schema/parser drift")
    if result.get("source_family") != SOURCE_FAMILY or result.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("LIFE BUILDUP Skills source/programme family drift")
    if result.get("authority_class") != AUTHORITY_CLASS or result.get("observation_state") != OBSERVATION_STATE:
        raise ValueError("LIFE BUILDUP Skills authority/observation drift")
    if result.get("topic_identifier") != TOPIC_IDENTIFIER:
        raise ValueError("LIFE BUILDUP Skills exact topic identity drift")
    if result.get("cinea_authority_url") != CINEA_URL or result.get("funding_tenders_topic_url") != FT_TOPIC_URL:
        raise ValueError("LIFE BUILDUP Skills authority URL drift")
    if result.get("semantic_reconciliation_required") is not True:
        raise ValueError("LIFE BUILDUP Skills skipped semantic reconciliation")
    if result.get("field_scoped_material_admission_required") is not True:
        raise ValueError("LIFE BUILDUP Skills skipped field-scoped admission")
    if result.get("material_admission_ready_for_downstream_review") is not False:
        raise ValueError("raw LIFE BUILDUP Skills evidence became review-ready before replay")
    if result.get("lkg_is_current_truth") is not False or result.get("market_intelligence_only") is not True:
        raise ValueError("LIFE BUILDUP Skills crossed LKG/market-intelligence boundary")
    fingerprint = str(result.get("exact_semantic_fingerprint") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError("LIFE BUILDUP Skills semantic fingerprint missing")
    healthy = result.get("source_health_state") == "HEALTHY"
    if healthy:
        if result.get("authority_agreement_verified") is not True or result.get("evidence_usable_for_reconciliation") is not True:
            raise ValueError("healthy LIFE BUILDUP Skills lacks authority agreement")
        if result.get("candidate_state") not in {"OPEN_CALL", "CLOSED_CALL", "FORTHCOMING_CALL"}:
            raise ValueError("healthy LIFE BUILDUP Skills lacks explicit candidate status")
        if result.get("status_label") not in {"Open", "Closed", "Forthcoming"}:
            raise ValueError("healthy LIFE BUILDUP Skills status label drift")
        if not result.get("deadline_candidate"):
            raise ValueError("healthy LIFE BUILDUP Skills lacks exact CINEA deadline candidate")
        structured = result.get("structured_snapshot") or {}
        if structured.get("topic_identifier") != TOPIC_IDENTIFIER:
            raise ValueError("healthy LIFE BUILDUP Skills structured identity drift")
        if not _is_life_label(str(structured.get("programme_label") or "")):
            raise ValueError("healthy LIFE BUILDUP Skills lost LIFE programme binding")
        if result.get("lkg_required") is not False:
            raise ValueError("healthy LIFE BUILDUP Skills incorrectly requires LKG")
    else:
        if result.get("source_health_state") != "DEGRADED_SEMANTIC_OR_TRANSPORT":
            raise ValueError("unsupported LIFE BUILDUP Skills source-health state")
        if result.get("candidate_state") != "UNKNOWN" or result.get("status_label") is not None:
            raise ValueError("degraded LIFE BUILDUP Skills leaked status candidate")
        if result.get("deadline_candidate") is not None or result.get("structured_snapshot") is not None:
            raise ValueError("degraded LIFE BUILDUP Skills leaked material candidate data")
        if result.get("evidence_usable_for_reconciliation") is not False or result.get("lkg_required") is not True:
            raise ValueError("degraded LIFE BUILDUP Skills did not fail closed")
    for key in MATERIAL_FLAGS:
        if result.get(key) is not False:
            raise ValueError(f"LIFE BUILDUP Skills exact evidence attempted authorization: {key}")
    if result.get("publication_effect") != "NONE":
        raise ValueError("LIFE BUILDUP Skills exact evidence crossed publication boundary")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--fetched-at")
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    args = parser.parse_args()
    result = collect_exact(run_id=args.run_id, fetched_at=args.fetched_at, output_dir=args.output_dir)
    print(json.dumps({
        "topic_identifier": result["topic_identifier"],
        "source_health_state": result["source_health_state"],
        "candidate_state": result["candidate_state"],
        "status_label": result["status_label"],
        "deadline_candidate": result["deadline_candidate"],
        "programme_reference": (result.get("structured_snapshot") or {}).get("programme_reference"),
        "programme_label": (result.get("structured_snapshot") or {}).get("programme_label"),
        "exact_semantic_fingerprint": result["exact_semantic_fingerprint"],
        "open_call_authorized": result["open_call_authorized"],
        "publication_effect": result["publication_effect"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
