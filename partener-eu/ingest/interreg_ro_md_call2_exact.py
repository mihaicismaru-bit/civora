#!/usr/bin/env python3
"""Exact-current, fail-closed evidence for Interreg NEXT Romania-Moldova Call 2.

The adapter binds the official programme Call 2 detail page to the current
programme calls index. It may observe a past submission-window candidate and
raw deadline text, but never authorizes status, deadline, budget, eligibility,
publication, distribution or alerts. Semantic reconciliation and field-scoped
material admission remain downstream gates.
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

SCHEMA = "PARTENER_EU_INTERREG_RO_MD_CALL2_EXACT_EVIDENCE_V1"
PARSER_VERSION = "INTERREG_RO_MD_CALL2_EXACT_V1"
RECONCILIATION_SCHEMA = "PARTENER_EU_INTERREG_RO_MD_CALL2_EXACT_RECONCILIATION_V1"
RECONCILIATION_PARSER_VERSION = "INTERREG_RO_MD_CALL2_EXACT_RECONCILE_V1"
SOURCE_FAMILY = "INTERREG"
PROGRAMME_FAMILY = "INTERREG_NEXT_RO_MD_2021_2027"
PROGRAMME_ID = "RO_MD"
PROGRAMME = "Interreg NEXT Romania-Republic of Moldova Programme"
AUTHORITY_CLASS = "T1_OFFICIAL_PROGRAMME_EXACT_CALL"
CALL_IDENTIFIER = "2"
CALL_IDENTIFIER_KIND = "OFFICIAL_CALL_NUMBER"
EXACT_URL = "https://ro-md.net/en/funding/calls-for-proposals/guidelines-for-applicants-small-scale-projects-open-call-2"
INDEX_URL = "https://ro-md.net/en/funding/calls-for-proposals"
ALLOWED_HOSTS = {"ro-md.net", "www.ro-md.net"}
RAW_DEADLINE_TEXT = "July 21, 2025, 14:00 CET (Romanian time)"

MATERIAL_FLAGS = (
    "material_fact_use", "open_call_authorized", "closed_call_authorized",
    "deadline_authorized", "budget_authorized", "eligibility_authorized",
    "publish_authorized", "distribution_authorized", "call_alert_authorized",
    "canonical_corpus_mutation",
)
MISSING_FOR_MATERIAL_ADMISSION = (
    "same_identity_previous_exact_receipt_or_reviewed_baseline_exception",
    "semantic_reconciliation",
    "field_scoped_material_admission",
    "publication_distribution_gate_if_reader_facing",
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


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def normal(value: str) -> str:
    text = html.unescape(value or "").casefold()
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


def html_text(raw: bytes) -> str:
    probe = TextProbe()
    probe.feed(raw.decode("utf-8", errors="replace"))
    return " ".join(probe.parts)


def visible_text_sha256(raw: bytes) -> str:
    return sha256_bytes(normal(html_text(raw)).encode("utf-8"))


def host_allowed(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and (parsed.hostname or "").casefold() in ALLOWED_HOSTS


def default_fetch(url: str, timeout: float = 30.0) -> tuple[bytes, dict[str, Any]]:
    req = urllib.request.Request(url, headers={
        "User-Agent": "PARTENER.EU-exact-call/1.0 (+https://partener.eu)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en",
    })
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError(f"RO-MD Call 2 exact source exceeds 5 MB: {url}")
        meta = {
            "requested_url": url,
            "final_url": str(response.geturl()),
            "status": int(getattr(response, "status", 200) or 200),
            "content_type": str(response.headers.get("Content-Type") or ""),
        }
    return raw, meta


def require(text: str, anchors: tuple[str, ...], *, source: str) -> None:
    hay = normal(text)
    missing = [anchor for anchor in anchors if normal(anchor) not in hay]
    if missing:
        raise ValueError(f"{source} missing required provenance anchors: {missing}")


def source_row(kind: str, url: str, raw: bytes | None, meta: Mapping[str, Any] | None, error: str | None) -> dict[str, Any]:
    if error is not None:
        return {
            "kind": kind, "requested_url": url, "final_url": None,
            "http_status": None, "content_type": None, "raw_sha256": None,
            "normalized_visible_text_sha256": None, "health_state": "DEGRADED",
            "lkg_required": True, "error": error,
        }
    assert raw is not None and meta is not None
    final = str(meta.get("final_url") or url)
    status = int(meta.get("status") or 0)
    ctype = str(meta.get("content_type") or "")
    healthy = status == 200 and host_allowed(final) and "html" in ctype.casefold()
    return {
        "kind": kind, "requested_url": url, "final_url": final if healthy else None,
        "http_status": status if healthy else None, "content_type": ctype if healthy else None,
        "raw_sha256": sha256_bytes(raw) if healthy else None,
        "normalized_visible_text_sha256": visible_text_sha256(raw) if healthy else None,
        "health_state": "HEALTHY" if healthy else "DEGRADED",
        "lkg_required": not healthy,
        "error": None if healthy else "HTTP_OR_AUTHORITY_OR_CONTENT_TYPE_DRIFT",
    }


def degraded_receipt(run_id: str, fetched_at: str, sources: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema": SCHEMA, "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY, "programme_family": PROGRAMME_FAMILY,
        "programme_id": PROGRAMME_ID, "programme": PROGRAMME,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": "EXACT_CALL_EVIDENCE_DEGRADED_FAIL_CLOSED",
        "run_id": run_id, "fetched_at": fetched_at,
        "official_call_identifier": CALL_IDENTIFIER,
        "official_call_identifier_kind": CALL_IDENTIFIER_KIND,
        "exact_authority_url": EXACT_URL, "current_index_authority_url": INDEX_URL,
        "source_health_state": "DEGRADED", "lkg_required": True,
        "current_material_truth_available": False, "sources": sources,
        "candidate_state": "UNKNOWN", "candidate_status_label": None,
        "candidate_deadline_text": None, "deadline_interpretation": None,
        "exact_semantics": None, "exact_semantic_fingerprint": None,
        "semantic_reconciliation_required": True,
        "field_scoped_material_admission_required": True,
        "previous_or_lkg_is_current_truth": False,
        "missing_for_material_admission": list(MISSING_FOR_MATERIAL_ADMISSION),
        "publication_effect": "NONE", "degraded_reason": reason,
    }
    for flag in MATERIAL_FLAGS:
        receipt[flag] = False
    validate_evidence(receipt)
    return receipt


def collect(*, run_id: str, fetched_at: str | None = None,
            fetcher: Callable[[str], tuple[bytes, dict[str, Any]]] = default_fetch) -> tuple[dict[str, Any], dict[str, bytes]]:
    observed = fetched_at or utc_now()
    sources: list[dict[str, Any]] = []
    raws: dict[str, bytes] = {}
    for kind, url in (("exact_call", EXACT_URL), ("current_index", INDEX_URL)):
        try:
            raw, meta = fetcher(url)
            row = source_row(kind, url, raw, meta, None)
            if row["health_state"] == "HEALTHY":
                raws[kind] = raw
        except Exception as exc:
            row = source_row(kind, url, None, None, f"{type(exc).__name__}: {exc}")
        sources.append(row)

    if any(row["health_state"] != "HEALTHY" for row in sources):
        return degraded_receipt(run_id, observed, sources, "SOURCE_TRANSPORT_OR_AUTHORITY_DEGRADED"), raws

    try:
        exact_text = html_text(raws["exact_call"])
        index_text = html_text(raws["current_index"])
        require(exact_text, (
            "Guidelines for Applicants - Small scale projects - Call 2",
            "2nd call for proposals for small scale projects",
            "The deadline for application is July 21, 2025, 14:00 CET (Romanian time)",
            "JEMS",
        ), source="RO-MD exact Call 2")
        require(index_text, (
            "Calls for proposals",
            "Guidelines for Applicants - Small scale projects - Call 2",
            "Interreg NEXT Romania-Republic of Moldova Programme",
        ), source="RO-MD current calls index")
    except Exception as exc:
        return degraded_receipt(run_id, observed, sources, f"SEMANTIC_MARKER_DRIFT: {type(exc).__name__}: {exc}"), raws

    semantics = {
        "programme_id": PROGRAMME_ID,
        "programme": PROGRAMME,
        "official_call_identifier": CALL_IDENTIFIER,
        "official_call_identifier_kind": CALL_IDENTIFIER_KIND,
        "call_title": "Guidelines for Applicants - Small scale projects - Call 2",
        "exact_authority_url": EXACT_URL,
        "current_index_authority_url": INDEX_URL,
        "candidate_state": "CALL_WINDOW_EXPIRED_CANDIDATE",
        "candidate_status_label": "Submission window expired candidate",
        "candidate_deadline_text": RAW_DEADLINE_TEXT,
        "deadline_interpretation": "RAW_OFFICIAL_TEXT_ONLY_NO_TIMEZONE_NORMALIZATION",
        "status_basis": "CURRENT_OFFICIAL_EXACT_PAGE_EXPOSES_PAST_SUBMISSION_DEADLINE_AND_CURRENT_INDEX_RETAINS_CALL_IDENTITY",
    }
    receipt: dict[str, Any] = {
        "schema": SCHEMA, "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY, "programme_family": PROGRAMME_FAMILY,
        "programme_id": PROGRAMME_ID, "programme": PROGRAMME,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": "EXACT_CALL_CURRENT_EVIDENCE_NON_AUTHORIZING",
        "run_id": run_id, "fetched_at": observed,
        "official_call_identifier": CALL_IDENTIFIER,
        "official_call_identifier_kind": CALL_IDENTIFIER_KIND,
        "exact_authority_url": EXACT_URL, "current_index_authority_url": INDEX_URL,
        "source_health_state": "HEALTHY", "lkg_required": False,
        "current_material_truth_available": False, "sources": sources,
        "candidate_state": semantics["candidate_state"],
        "candidate_status_label": semantics["candidate_status_label"],
        "candidate_deadline_text": semantics["candidate_deadline_text"],
        "deadline_interpretation": semantics["deadline_interpretation"],
        "status_basis": semantics["status_basis"],
        "exact_semantics": semantics, "exact_semantic_fingerprint": sha256_json(semantics),
        "semantic_reconciliation_required": True,
        "field_scoped_material_admission_required": True,
        "previous_or_lkg_is_current_truth": False,
        "missing_for_material_admission": list(MISSING_FOR_MATERIAL_ADMISSION),
        "publication_effect": "NONE", "degraded_reason": None,
    }
    for flag in MATERIAL_FLAGS:
        receipt[flag] = False
    validate_evidence(receipt)
    return receipt, raws


def validate_evidence(receipt: Mapping[str, Any]) -> None:
    if receipt.get("schema") != SCHEMA or receipt.get("parser_version") != PARSER_VERSION:
        raise ValueError("RO-MD Call 2 evidence schema/parser drift")
    if receipt.get("source_family") != SOURCE_FAMILY or receipt.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("RO-MD Call 2 family drift")
    if receipt.get("programme_id") != PROGRAMME_ID or str(receipt.get("official_call_identifier")) != CALL_IDENTIFIER:
        raise ValueError("RO-MD Call 2 identity drift")
    if receipt.get("official_call_identifier_kind") != CALL_IDENTIFIER_KIND:
        raise ValueError("RO-MD Call 2 identifier-kind drift")
    if receipt.get("exact_authority_url") != EXACT_URL or receipt.get("current_index_authority_url") != INDEX_URL:
        raise ValueError("RO-MD Call 2 authority drift")
    if not host_allowed(str(receipt.get("exact_authority_url"))) or not host_allowed(str(receipt.get("current_index_authority_url"))):
        raise ValueError("RO-MD Call 2 authority host drift")
    if receipt.get("semantic_reconciliation_required") is not True or receipt.get("field_scoped_material_admission_required") is not True:
        raise ValueError("RO-MD Call 2 weakened admission requirements")
    if receipt.get("previous_or_lkg_is_current_truth") is not False:
        raise ValueError("RO-MD Call 2 promoted history/LKG to current truth")
    if receipt.get("source_health_state") == "HEALTHY":
        if receipt.get("candidate_state") != "CALL_WINDOW_EXPIRED_CANDIDATE":
            raise ValueError("RO-MD Call 2 candidate lifecycle drift")
        semantics = receipt.get("exact_semantics")
        if not isinstance(semantics, Mapping) or sha256_json(semantics) != receipt.get("exact_semantic_fingerprint"):
            raise ValueError("RO-MD Call 2 semantic fingerprint tampered")
        if receipt.get("deadline_interpretation") != "RAW_OFFICIAL_TEXT_ONLY_NO_TIMEZONE_NORMALIZATION":
            raise ValueError("RO-MD Call 2 deadline interpretation drift")
    elif receipt.get("source_health_state") == "DEGRADED":
        if receipt.get("candidate_state") != "UNKNOWN" or receipt.get("candidate_deadline_text") is not None:
            raise ValueError("degraded RO-MD Call 2 leaked material candidate semantics")
        if receipt.get("lkg_required") is not True or receipt.get("current_material_truth_available") is not False:
            raise ValueError("degraded RO-MD Call 2 weakened LKG boundary")
    else:
        raise ValueError("RO-MD Call 2 unknown source health state")
    for flag in MATERIAL_FLAGS:
        if receipt.get(flag) is not False:
            raise ValueError(f"RO-MD Call 2 attempted authorization: {flag}")
    if receipt.get("publication_effect") != "NONE":
        raise ValueError("RO-MD Call 2 attempted publication effect")


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("RO-MD Call 2 reconciliation timestamps must be timezone-aware")
    return parsed


def reconcile(current: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    validate_evidence(current)
    changes: list[dict[str, Any]] = []
    if previous is None:
        state = "BASELINE_CAPTURED_NON_AUTHORIZING"
    else:
        validate_evidence(previous)
        for flag in MATERIAL_FLAGS:
            if previous.get(flag) is not False:
                raise ValueError(f"previous RO-MD Call 2 attempted authorization widening: {flag}")
        if previous.get("official_call_identifier") != current.get("official_call_identifier"):
            raise ValueError("RO-MD Call 2 reconciliation identity mismatch")
        if previous.get("exact_authority_url") != current.get("exact_authority_url"):
            raise ValueError("RO-MD Call 2 reconciliation authority mismatch")
        if parse_time(str(previous.get("fetched_at"))) >= parse_time(str(current.get("fetched_at"))):
            raise ValueError("previous RO-MD Call 2 evidence must be strictly older than current")
        if current.get("source_health_state") != "HEALTHY":
            state = "CURRENT_DEGRADED_LKG_REQUIRED_NON_AUTHORIZING"
        elif previous.get("source_health_state") != "HEALTHY":
            state = "CURRENT_HEALTHY_PREVIOUS_DEGRADED_NON_AUTHORIZING"
        else:
            before = dict(previous["exact_semantics"])
            after = dict(current["exact_semantics"])
            for key in sorted(set(before) | set(after)):
                if before.get(key) != after.get(key):
                    changes.append({"field": key, "before": before.get(key), "after": after.get(key)})
            state = "NO_CHANGE" if not changes else "RO_MD_CALL2_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"

    receipt: dict[str, Any] = {
        "schema": RECONCILIATION_SCHEMA, "parser_version": RECONCILIATION_PARSER_VERSION,
        "source_family": SOURCE_FAMILY, "programme_family": PROGRAMME_FAMILY,
        "programme_id": PROGRAMME_ID, "official_call_identifier": CALL_IDENTIFIER,
        "current_fetched_at": current.get("fetched_at"),
        "previous_fetched_at": previous.get("fetched_at") if previous else None,
        "current_evidence_sha256": sha256_json(current),
        "previous_evidence_sha256": sha256_json(previous) if previous else None,
        "current_exact_semantic_fingerprint": current.get("exact_semantic_fingerprint"),
        "previous_exact_semantic_fingerprint": previous.get("exact_semantic_fingerprint") if previous else None,
        "reconciliation_state": state,
        "semantic_change_count": len(changes), "semantic_changes": changes,
        "semantic_reconciliation_passed": True,
        "material_admission_ready_for_downstream_review": bool(
            previous is not None and current.get("source_health_state") == "HEALTHY" and previous.get("source_health_state") == "HEALTHY"
        ),
        "lkg_is_current_truth": False,
        "field_scoped_material_admission_required": True,
        "publication_effect": "NONE",
    }
    for flag in MATERIAL_FLAGS:
        receipt[flag] = False
    validate_reconciliation(receipt, current=current, previous=previous)
    return receipt


def validate_reconciliation(receipt: Mapping[str, Any], *, current: Mapping[str, Any], previous: Mapping[str, Any] | None) -> None:
    if receipt.get("schema") != RECONCILIATION_SCHEMA or receipt.get("parser_version") != RECONCILIATION_PARSER_VERSION:
        raise ValueError("RO-MD Call 2 reconciliation schema/parser drift")
    validate_evidence(current)
    if receipt.get("current_evidence_sha256") != sha256_json(current):
        raise ValueError("RO-MD Call 2 reconciliation current binding failed")
    if previous is None:
        if receipt.get("reconciliation_state") != "BASELINE_CAPTURED_NON_AUTHORIZING" or receipt.get("material_admission_ready_for_downstream_review") is not False:
            raise ValueError("RO-MD Call 2 baseline reconciliation invalid")
    else:
        validate_evidence(previous)
        if receipt.get("previous_evidence_sha256") != sha256_json(previous):
            raise ValueError("RO-MD Call 2 reconciliation previous binding failed")
    if receipt.get("lkg_is_current_truth") is not False:
        raise ValueError("RO-MD Call 2 reconciliation promoted LKG")
    for flag in MATERIAL_FLAGS:
        if receipt.get(flag) is not False:
            raise ValueError(f"RO-MD Call 2 reconciliation attempted authorization: {flag}")
    if receipt.get("publication_effect") != "NONE":
        raise ValueError("RO-MD Call 2 reconciliation attempted publication")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--reconciliation-output", required=True)
    parser.add_argument("--previous")
    args = parser.parse_args()
    current, _ = collect(run_id=args.run_id)
    previous = None
    if args.previous:
        previous = json.loads(pathlib.Path(args.previous).read_text(encoding="utf-8"))
    rec = reconcile(current, previous)
    out = pathlib.Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rout = pathlib.Path(args.reconciliation_output)
    rout.parent.mkdir(parents=True, exist_ok=True)
    rout.write_text(json.dumps(rec, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "programme_id": PROGRAMME_ID,
        "official_call_identifier": CALL_IDENTIFIER,
        "source_health_state": current["source_health_state"],
        "candidate_state": current["candidate_state"],
        "reconciliation_state": rec["reconciliation_state"],
        "semantic_change_count": rec["semantic_change_count"],
        "open_call_authorized": current["open_call_authorized"],
        "publication_effect": current["publication_effect"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
