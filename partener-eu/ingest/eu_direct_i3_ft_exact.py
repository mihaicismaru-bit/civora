#!/usr/bin/env python3
"""Exact current Funding & Tenders evidence for one I3 call reference.

Binds a current official EISMEA exact call page to the structured Funding &
Tenders Search/Facet record and the exact Funding & Tenders topic readback.
All status/deadline/budget/eligibility values remain candidates only. This
adapter is acquisition-only and cannot authorize publication or alerts.
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

import funding_tenders_fetch as ft
from funding_tenders_api import normalize_payload

SCHEMA = "PARTENER_EU_I3_FT_EXACT_EVIDENCE_V1"
PARSER_VERSION = "EU_DIRECT_I3_FT_EXACT_V1"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "I3"
AUTHORITY_CLASS = "EISMEA_PLUS_EU_COMMISSION_FUNDING_TENDERS"
OBSERVATION_LAYER = "EXACT_CURRENT_CALL_NON_AUTHORIZING"
REF_RE = re.compile(r"^I3-[A-Z0-9]+(?:-[A-Z0-9]+)+$", re.IGNORECASE)
DIRECT_TYPES = {"1", "2"}
EISMEA_HOST = "eismea.ec.europa.eu"
EISMEA_PATH_PREFIX = "/funding-opportunities/calls-proposals/"
MATERIAL_FLAGS = (
    "material_fact_use", "open_call_authorized", "closed_call_authorized",
    "deadline_authorized", "budget_authorized", "eligibility_authorized",
    "publish_authorized", "distribution_authorized", "call_alert_authorized",
)


class ExactI3Conflict(ValueError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def validate_reference(reference: str) -> str:
    value = str(reference or "").strip().upper()
    if not REF_RE.fullmatch(value):
        raise ValueError(f"not an explicit I3 call reference: {reference!r}")
    return value


def _scalar(value: Any) -> str | None:
    return ft._scalar(value)


def _record_type(record: Mapping[str, Any]) -> str | None:
    return _scalar(record.get("type"))


def _record_programme_reference(record: Mapping[str, Any]) -> str | None:
    for key in ("frameworkProgramme", "programme", "programmeReference"):
        value = _scalar(record.get(key))
        if value:
            return value
    return None


def _first_scalar(record: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _scalar(record.get(key))
        if value:
            return value
    return None


def _framework_programme_map(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("official Facet response must be an object")
    facets = payload.get("facets")
    if not isinstance(facets, list):
        raise ValueError("official Facet response is missing facets")
    matches = [f for f in facets if isinstance(f, dict) and f.get("name") == "frameworkProgramme"]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one frameworkProgramme facet, found {len(matches)}")
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
            raise ValueError(f"ambiguous official programme label for {code}: {previous!r} vs {label!r}")
        result[code] = label
    if not result:
        raise ValueError("frameworkProgramme facet yielded no human-readable labels")
    return result


def _is_i3_label(label: str) -> bool:
    token = re.sub(r"[^a-z0-9]+", " ", label.casefold()).strip()
    return "interregional innovation investments" in token or token == "i3"


def reference_query() -> dict[str, Any]:
    return {"bool": {"must": [
        {"terms": {"type": list(ft.CALL_TYPES)}},
        {"term": {"programmePeriod": "2021 - 2027"}},
    ]}}


def _material_snapshot(record: Mapping[str, Any], *, programme_label: str, status_label: str) -> dict[str, Any]:
    return {
        "identifier": ft._record_identifier(record),
        "record_type": _record_type(record),
        "programme_reference": _record_programme_reference(record),
        "programme_label": programme_label,
        "call_identifier": _first_scalar(record, "callIdentifier", "callId", "callReference"),
        "status_code": ft._record_status_code(record),
        "status_label": status_label,
        "title": _first_scalar(record, "title", "topicTitle", "name"),
        "deadline_candidate": _first_scalar(record, "deadlineDate", "deadlineDates", "deadline"),
        "budget_candidate": _first_scalar(record, "budget", "budgetOverview", "topicBudget", "callBudget"),
    }


def _validate_eismea_url(url: str) -> str:
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() != EISMEA_HOST:
        raise ValueError("I3 EISMEA exact authority escaped official HTTPS host")
    if not (parsed.path or "/").startswith(EISMEA_PATH_PREFIX):
        raise ValueError("I3 EISMEA exact authority escaped bounded call path")
    return url


def _normalise_visible_text(raw: bytes) -> str:
    text = html.unescape(raw.decode("utf-8", errors="ignore"))
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _http_fetch(url: str, *, timeout: float = 25.0) -> tuple[bytes, int, str, str]:
    request = Request(
        url,
        headers={
            "User-Agent": "PARTENER.EU-I3Exact/1.0 (+https://partener.eu)",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.1",
        },
        method="GET",
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read(), int(getattr(response, "status", 200)), str(response.geturl()), str(response.headers.get("Content-Type", ""))


def _fetch_eismea_exact(
    reference: str,
    url: str,
    *,
    timeout: float,
    fetcher: Callable[..., tuple[bytes, int, str, str]],
) -> tuple[bytes | None, dict[str, Any], str | None]:
    _validate_eismea_url(url)
    try:
        raw, status, final_url, content_type = fetcher(url, timeout=timeout)
        _validate_eismea_url(final_url)
        text = _normalise_visible_text(raw)
        markers_ok = reference.casefold() in text.casefold() and "interregional innovation investments" in text.casefold()
        content_ok = "html" in content_type.casefold() or raw.lstrip().startswith(b"<")
        healthy = status == 200 and markers_ok and content_ok
        status_candidate = None
        if re.search(r"\bstatus\s+open\b", text, flags=re.I) or re.search(r"\bcall for proposals\s+open\b", text, flags=re.I):
            status_candidate = "Open"
        elif re.search(r"\bstatus\s+closed\b", text, flags=re.I) or re.search(r"\bcall for proposals\s+closed\b", text, flags=re.I):
            status_candidate = "Closed"
        receipt = {
            "health_state": "HEALTHY" if healthy else "DEGRADED_MARKER_MISMATCH",
            "lkg_required": not healthy,
            "requested_url": url,
            "final_url": final_url,
            "http_status": status,
            "content_type": content_type,
            "raw_sha256": sha256_bytes(raw),
            "raw_size_bytes": len(raw),
            "normalized_visible_text_sha256": sha256_bytes(text.encode("utf-8")),
            "exact_reference_marker_verified": reference.casefold() in text.casefold(),
            "programme_marker_verified": "interregional innovation investments" in text.casefold(),
            "error": None if healthy else "official EISMEA exact page failed status/content/reference/programme markers",
        }
        return raw, receipt, status_candidate
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        return None, {
            "health_state": "DEGRADED_TRANSPORT",
            "lkg_required": True,
            "requested_url": url,
            "final_url": None,
            "http_status": getattr(exc, "code", None),
            "content_type": None,
            "raw_sha256": None,
            "raw_size_bytes": 0,
            "normalized_visible_text_sha256": None,
            "exact_reference_marker_verified": False,
            "programme_marker_verified": False,
            "error": f"{type(exc).__name__}: {exc}",
        }, None


def collect_exact(
    reference: str,
    *,
    eismea_url: str,
    run_id: str,
    fetched_at: str | None = None,
    output_dir: pathlib.Path | None = None,
    post_func: Callable[..., tuple[Any, bytes, dict[str, Any]]] = ft._safe_json_post,
    topic_func: Callable[..., dict[str, Any]] = ft._topic_readback,
    eismea_fetcher: Callable[..., tuple[bytes, int, str, str]] = _http_fetch,
) -> dict[str, Any]:
    reference = validate_reference(reference)
    eismea_url = _validate_eismea_url(eismea_url)
    fetched_at = fetched_at or utc_now()
    common_parts = {"query": reference_query(), "languages": ["en"]}

    search_payload, search_raw, search_receipt = post_func(
        ft.SEARCH_ENDPOINT, text=reference, page_size=10, page_number=1, parts=common_parts
    )
    facet_payload, facet_raw, facet_receipt = post_func(
        ft.FACET_ENDPOINT, text=reference, page_size=10, page_number=1, parts=common_parts
    )
    matching = [row for row in ft.flatten_search_payload(search_payload)
                if str(ft._record_identifier(row) or "").upper() == reference]
    if not matching:
        raise ValueError(f"Funding & Tenders returned no exact record for {reference}")
    primary = [row for row in matching if _record_type(row) in DIRECT_TYPES]
    linked_type8 = [row for row in matching if _record_type(row) == "8"]
    if not primary:
        raise ValueError(f"Funding & Tenders returned no direct-call record for {reference}")

    programme_labels = _framework_programme_map(facet_payload)
    material_rows: list[tuple[str, Mapping[str, Any], dict[str, Any]]] = []
    for row in primary:
        programme_ref = _record_programme_reference(row)
        programme_label = programme_labels.get(programme_ref or "")
        if not programme_label or not _is_i3_label(programme_label):
            raise ValueError(f"exact record is not proven to belong to I3: {programme_ref!r} {programme_label!r}")
        status_code = ft._record_status_code(row)
        status_label = ft.resolve_reference_label([facet_payload], status_code or "") if status_code else None
        if not status_label:
            raise ValueError(f"official Facet did not resolve current status for {reference}")
        snapshot = _material_snapshot(row, programme_label=programme_label, status_label=status_label)
        material_rows.append((sha256_json(snapshot), row, snapshot))
    signatures = sorted({signature for signature, _, _ in material_rows})
    if len(signatures) != 1:
        raise ExactI3Conflict(f"conflicting exact I3 records for {reference}: {len(signatures)} material variants")
    chosen, snapshot = material_rows[0][1], material_rows[0][2]

    authority_url = ft.topic_url(reference)
    readback = topic_func(authority_url)
    eismea_raw, eismea_receipt, eismea_status = _fetch_eismea_exact(
        reference, eismea_url, timeout=25.0, fetcher=eismea_fetcher
    )
    authority_verified = readback.get("verified") is True
    eismea_verified = eismea_receipt.get("health_state") == "HEALTHY"

    structured_status = str(snapshot.get("status_label") or "").strip()
    cross_authority_status_consistent = eismea_status is None or eismea_status.casefold() == structured_status.casefold()
    usable = authority_verified and eismea_verified and cross_authority_status_consistent

    if usable:
        enriched = dict(chosen)
        enriched["statusLabel"] = snapshot["status_label"]
        enriched["authorityUrl"] = authority_url
        batch = normalize_payload([enriched], fetched_at=fetched_at, run_id=run_id, verified_authority_urls=[authority_url])
        records = [row for row in batch.get("records") or [] if str(row.get("identifier") or "").upper() == reference]
        if len(records) != 1:
            raise ValueError(f"exact I3 normalizer returned {len(records)} records for {reference}")
        normalized = records[0]
        if normalized.get("authority_url_verified") is not True:
            raise ValueError("exact I3 authority verification was lost during normalization")
        candidate_state = normalized.get("observation_state")
        status_label = normalized.get("status_label")
        call_identifier = normalized.get("call_identifier")
        title = normalized.get("title")
        deadline_candidate = normalized.get("deadline_candidate")
        budget_candidate = normalized.get("budget_candidate")
        source_health_state = "HEALTHY"
        lkg_required = False
        degradation_reason = None
    else:
        candidate_state = "UNKNOWN"
        status_label = None
        call_identifier = snapshot.get("call_identifier")
        title = snapshot.get("title")
        deadline_candidate = None
        budget_candidate = None
        source_health_state = "DEGRADED_EXACT_AUTHORITY_CHAIN"
        lkg_required = True
        reasons = []
        if not authority_verified:
            reasons.append(str(readback.get("error") or "F&T topic readback unverified"))
        if not eismea_verified:
            reasons.append(str(eismea_receipt.get("error") or "EISMEA exact page unverified"))
        if not cross_authority_status_consistent:
            reasons.append(f"status conflict EISMEA={eismea_status!r} F&T={structured_status!r}")
        degradation_reason = "; ".join(reasons) or "exact authority chain unavailable"

    exact_semantics = {
        "identifier": reference,
        "call_identifier": call_identifier,
        "title": title,
        "programme_reference": snapshot.get("programme_reference"),
        "programme_label": snapshot.get("programme_label"),
        "status_label": status_label,
        "candidate_state": candidate_state,
        "funding_tenders_authority_url": authority_url,
        "eismea_authority_url": eismea_url,
        "eismea_status_label_candidate": eismea_status,
        "cross_authority_status_consistent": cross_authority_status_consistent,
        "deadline_candidate": deadline_candidate,
        "budget_candidate": budget_candidate,
    }
    evidence: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_LAYER,
        "reference": reference,
        "fetched_at": fetched_at,
        "run_id": run_id,
        "search_receipt": dict(search_receipt),
        "facet_receipt": dict(facet_receipt),
        "search_raw_sha256": sha256_bytes(search_raw),
        "facet_raw_sha256": sha256_bytes(facet_raw),
        "funding_tenders_authority_url": authority_url,
        "funding_tenders_authority_readback": dict(readback),
        "funding_tenders_authority_verified": authority_verified,
        "eismea_authority_url": eismea_url,
        "eismea_receipt": eismea_receipt,
        "eismea_status_label_candidate": eismea_status,
        "cross_authority_status_consistent": cross_authority_status_consistent,
        "source_health_state": source_health_state,
        "lkg_required": lkg_required,
        "evidence_usable_for_reconciliation": usable,
        "degradation_reason": degradation_reason,
        "candidate_state": candidate_state,
        "status_label": status_label,
        "call_identifier": call_identifier,
        "title": title,
        "programme_reference": snapshot.get("programme_reference"),
        "programme_label_official": snapshot.get("programme_label"),
        "deadline_candidate": deadline_candidate,
        "budget_candidate": budget_candidate,
        "structured_candidate_snapshot": snapshot,
        "exact_semantics": exact_semantics,
        "exact_semantic_fingerprint": sha256_json(exact_semantics),
        "primary_exact_record_count": len(primary),
        "linked_type8_record_count": len(linked_type8),
        "linked_type8_record_hashes": sorted(sha256_json(row) for row in linked_type8),
        "semantic_reconciliation_required": True,
        "field_scoped_material_admission_required": True,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        evidence[key] = False
    validate_evidence(evidence)

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "ft-i3-search-response.json").write_bytes(search_raw)
        (output_dir / "ft-i3-facet-response.json").write_bytes(facet_raw)
        if eismea_raw is not None:
            (output_dir / "i3-eismea-exact-page.html").write_bytes(eismea_raw)
        (output_dir / "ft-i3-exact-evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
    return evidence


def validate_evidence(evidence: Mapping[str, Any]) -> None:
    if evidence.get("schema") != SCHEMA or evidence.get("parser_version") != PARSER_VERSION:
        raise ValueError("I3 exact evidence schema/parser drift")
    reference = validate_reference(str(evidence.get("reference") or ""))
    if evidence.get("source_family") != SOURCE_FAMILY or evidence.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("I3 exact evidence family drift")
    if evidence.get("authority_class") != AUTHORITY_CLASS:
        raise ValueError("I3 exact evidence authority class drift")
    if evidence.get("funding_tenders_authority_url") != ft.topic_url(reference):
        raise ValueError("I3 exact F&T authority URL drift")
    _validate_eismea_url(str(evidence.get("eismea_authority_url") or ""))
    usable = evidence.get("evidence_usable_for_reconciliation")
    if usable not in {True, False}:
        raise ValueError("I3 exact reconciliation usability state missing")
    readback = evidence.get("funding_tenders_authority_readback") or {}
    eismea = evidence.get("eismea_receipt") or {}
    if usable:
        if evidence.get("funding_tenders_authority_verified") is not True or readback.get("verified") is not True:
            raise ValueError("I3 exact evidence lacks verified F&T exact topic authority")
        if readback.get("url") != evidence.get("funding_tenders_authority_url"):
            raise ValueError("I3 exact F&T readback binding invalid")
        if eismea.get("health_state") != "HEALTHY" or eismea.get("lkg_required") is not False:
            raise ValueError("I3 exact evidence lacks healthy EISMEA exact authority")
        if evidence.get("cross_authority_status_consistent") is not True:
            raise ValueError("I3 exact evidence has unresolved cross-authority status conflict")
        if evidence.get("source_health_state") != "HEALTHY" or evidence.get("lkg_required") is not False:
            raise ValueError("I3 healthy exact source-health binding invalid")
        if evidence.get("candidate_state") not in {"OPEN_CALL", "FORTHCOMING_CALL", "CLOSED_CALL", "UNKNOWN"}:
            raise ValueError("I3 exact candidate state unsupported")
        if not evidence.get("status_label"):
            raise ValueError("I3 exact evidence lacks resolved structured status label")
    else:
        if evidence.get("source_health_state") != "DEGRADED_EXACT_AUTHORITY_CHAIN" or evidence.get("lkg_required") is not True:
            raise ValueError("I3 degraded evidence lacks source-health/LKG binding")
        if evidence.get("candidate_state") != "UNKNOWN" or evidence.get("status_label") is not None:
            raise ValueError("I3 degraded evidence leaked current status candidate")
        if evidence.get("deadline_candidate") is not None or evidence.get("budget_candidate") is not None:
            raise ValueError("I3 degraded evidence leaked material candidates")
        if not evidence.get("degradation_reason"):
            raise ValueError("I3 degraded evidence lacks failure reason")
    if not _is_i3_label(str(evidence.get("programme_label_official") or "")):
        raise ValueError("I3 exact evidence lost official programme proof")
    semantics = evidence.get("exact_semantics")
    if not isinstance(semantics, dict) or sha256_json(semantics) != evidence.get("exact_semantic_fingerprint"):
        raise ValueError("I3 exact semantic fingerprint mismatch")
    for receipt_key in ("search_receipt", "facet_receipt"):
        receipt = evidence.get(receipt_key) or {}
        if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("sha256") or "")):
            raise ValueError(f"I3 exact evidence missing immutable {receipt_key}")
    for key in MATERIAL_FLAGS:
        if evidence.get(key) is not False:
            raise ValueError(f"I3 exact evidence attempted authorization: {key}")
    if evidence.get("publication_effect") != "NONE" or evidence.get("canonical_corpus_mutation") is not False:
        raise ValueError("I3 exact evidence crossed publication boundary")
    if evidence.get("semantic_reconciliation_required") is not True or evidence.get("field_scoped_material_admission_required") is not True:
        raise ValueError("I3 exact evidence skipped downstream gates")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", required=True)
    parser.add_argument("--eismea-url", required=True)
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    parser.add_argument("--run-id", default="i3-ft-exact-live")
    args = parser.parse_args()
    evidence = collect_exact(
        args.reference,
        eismea_url=args.eismea_url,
        run_id=args.run_id,
        output_dir=args.output_dir,
    )
    print(json.dumps({
        "reference": evidence["reference"],
        "candidate_state": evidence["candidate_state"],
        "status_label": evidence["status_label"],
        "source_health_state": evidence["source_health_state"],
        "evidence_usable_for_reconciliation": evidence["evidence_usable_for_reconciliation"],
        "cross_authority_status_consistent": evidence["cross_authority_status_consistent"],
        "open_call_authorized": evidence["open_call_authorized"],
        "publication_effect": evidence["publication_effect"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
