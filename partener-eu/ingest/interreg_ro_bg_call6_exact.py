#!/usr/bin/env python3
"""Exact-current, fail-closed evidence for Interreg VI-A Romania-Bulgaria Call 6.

The adapter binds the official Call 6 detail page to the programme's current
official closed-calls index. It may observe a CLOSED candidate and deadline,
but never authorizes a material call fact, publication, distribution or alert.
Semantic reconciliation and field-scoped material admission remain mandatory.
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

SCHEMA = "PARTENER_EU_INTERREG_RO_BG_CALL6_EXACT_EVIDENCE_V1"
PARSER_VERSION = "INTERREG_RO_BG_CALL6_EXACT_V1"
RECONCILIATION_SCHEMA = "PARTENER_EU_INTERREG_RO_BG_CALL6_EXACT_RECONCILIATION_V1"
RECONCILIATION_VERSION = "INTERREG_RO_BG_CALL6_EXACT_RECONCILE_V1"
REGISTRY_SCHEMA = "PARTENER_EU_INTERREG_RO_BG_CALL6_EXACT_REGISTRY_V1"
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
ALLOWED_HOSTS = {"interregviarobg.eu", "www.interregviarobg.eu"}


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
    text = re.sub(r"[^a-z0-9:+./-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def html_text(raw: bytes) -> str:
    probe = TextProbe()
    probe.feed(raw.decode("utf-8", errors="replace"))
    return " ".join(probe.parts)


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def validate_registry(registry: Mapping[str, Any]) -> None:
    if registry.get("schema") != REGISTRY_SCHEMA:
        raise ValueError("RO-BG Call 6 registry schema drift")
    if registry.get("source_family") != "INTERREG":
        raise ValueError("RO-BG Call 6 source-family drift")
    if registry.get("programme_family") != "INTERREG_ROMANIA_BULGARIA_2021_2027":
        raise ValueError("RO-BG Call 6 programme-family drift")
    if str(registry.get("official_call_identifier")) != "6" or registry.get("official_call_identifier_kind") != "OFFICIAL_CALL_NUMBER":
        raise ValueError("RO-BG Call 6 official identity drift")
    for key in ("exact_url", "closed_index_url", "programme_calls_url"):
        url = str(registry.get(key) or "")
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in ALLOWED_HOSTS:
            raise ValueError(f"RO-BG Call 6 authority drift: {key}")
    if urllib.parse.urlparse(str(registry["exact_url"])).path.rstrip("/") != "/en/open-calls-for-proposals-call-6":
        raise ValueError("RO-BG Call 6 exact path drift")
    if urllib.parse.urlparse(str(registry["closed_index_url"])).path.rstrip("/") != "/en/calls-for-proposals-1":
        raise ValueError("RO-BG closed-index path drift")
    relevance = registry.get("territorial_relevance") or {}
    if set(relevance.get("country_pair") or []) != {"Romania", "Bulgaria"}:
        raise ValueError("RO-BG territorial relevance drift")
    if relevance.get("programme_area_relevance_only") is not True or relevance.get("call_eligibility_authorized") is not False:
        raise ValueError("RO-BG geography relevance became call eligibility")
    policy = registry.get("policy") or {}
    for flag in MATERIAL_FLAGS:
        if policy.get(flag) is not False:
            raise ValueError(f"RO-BG registry weakened fail-closed policy: {flag}")
    if policy.get("field_scoped_material_admission_required") is not True or policy.get("semantic_reconciliation_required") is not True:
        raise ValueError("RO-BG registry weakened material admission")
    if policy.get("previous_or_lkg_is_current_truth") is not False:
        raise ValueError("RO-BG registry promoted history/LKG to current truth")


def load_registry(path: str | pathlib.Path) -> dict[str, Any]:
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    validate_registry(data)
    return data


def default_fetch(url: str, timeout: float = 30.0) -> tuple[bytes, dict[str, Any]]:
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; PARTENER.EU/1.0; +https://partener.eu)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError("RO-BG exact source exceeds 5 MB")
        meta = {
            "requested_url": url,
            "final_url": str(response.geturl()),
            "http_status": int(getattr(response, "status", 200) or 200),
            "content_type": str(response.headers.get("Content-Type") or ""),
        }
    return raw, meta


def _source_row(kind: str, url: str, raw: bytes | None, meta: Mapping[str, Any] | None, error: str | None) -> dict[str, Any]:
    if error is not None:
        return {
            "kind": kind, "requested_url": url, "final_url": None, "http_status": None,
            "content_type": None, "raw_sha256": None, "health_state": "DEGRADED",
            "lkg_required": True, "error": error,
        }
    assert raw is not None and meta is not None
    final = str(meta.get("final_url") or url)
    parsed = urllib.parse.urlparse(final)
    status = int(meta.get("http_status") or 0)
    ctype = str(meta.get("content_type") or "").casefold()
    if status != 200 or parsed.scheme != "https" or (parsed.hostname or "").casefold() not in ALLOWED_HOSTS or "html" not in ctype:
        return {
            "kind": kind, "requested_url": url, "final_url": final, "http_status": status,
            "content_type": str(meta.get("content_type") or ""), "raw_sha256": sha256_bytes(raw),
            "health_state": "DEGRADED", "lkg_required": True,
            "error": "HTTP_OR_AUTHORITY_OR_CONTENT_TYPE_DRIFT",
        }
    return {
        "kind": kind, "requested_url": url, "final_url": final, "http_status": status,
        "content_type": str(meta.get("content_type") or ""), "raw_sha256": sha256_bytes(raw),
        "health_state": "HEALTHY", "lkg_required": False, "error": None,
    }


def _require_markers(text: str, markers: list[str], source: str) -> None:
    hay = normal(text)
    missing = [marker for marker in markers if normal(marker) not in hay]
    if missing:
        raise ValueError(f"{source} missing required markers: {missing}")


def _deadline(exact_text: str) -> str:
    hay = normal(exact_text)
    pattern = r"deadline for uploading applications in the jems system is 22\s*(?:nd\s*)?of december 2025(?: at)? 13:00 eet"
    if not re.search(pattern, hay):
        raise ValueError("RO-BG Call 6 exact endpoint no longer exposes expected deadline statement")
    return "22 December 2025, 13:00 EET"


def _degraded_receipt(registry: Mapping[str, Any], run_id: str, fetched_at: str, sources: list[dict[str, Any]], error: str) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema": SCHEMA, "parser_version": PARSER_VERSION,
        "source_family": registry["source_family"], "programme_family": registry["programme_family"],
        "programme_id": registry["programme_id"], "programme": registry["programme"],
        "authority_class": registry["authority_class"], "observation_state": "EXACT_CALL_EVIDENCE_DEGRADED_FAIL_CLOSED",
        "run_id": run_id, "fetched_at": fetched_at,
        "official_call_identifier": str(registry["official_call_identifier"]),
        "official_call_identifier_kind": registry["official_call_identifier_kind"],
        "exact_authority_url": registry["exact_url"], "closed_index_authority_url": registry["closed_index_url"],
        "source_health_state": "DEGRADED", "lkg_required": True, "sources": sources,
        "candidate_state": "UNKNOWN", "candidate_status_label": None, "candidate_deadline_text": None,
        "exact_semantics": None, "exact_semantic_fingerprint": None,
        "territorial_relevance": registry["territorial_relevance"],
        "market_intelligence_only": False, "field_scoped_material_admission_required": True,
        "semantic_reconciliation_required": True, "publication_effect": "NONE",
        "missing_for_material_admission": list(MISSING_FOR_MATERIAL_ADMISSION),
        "degraded_reason": error,
    }
    for flag in MATERIAL_FLAGS:
        receipt[flag] = False
    return receipt


def collect(*, registry: Mapping[str, Any], run_id: str, fetched_at: str | None = None, fetcher: Callable[[str], tuple[bytes, dict[str, Any]]] = default_fetch) -> tuple[dict[str, Any], dict[str, bytes]]:
    validate_registry(registry)
    observed = fetched_at or utc_now()
    raws: dict[str, bytes] = {}
    sources: list[dict[str, Any]] = []
    for kind, key in (("exact", "exact_url"), ("closed_index", "closed_index_url")):
        url = str(registry[key])
        try:
            raw, meta = fetcher(url)
            raws[kind] = raw
            row = _source_row(kind, url, raw, meta, None)
        except Exception as exc:  # fail closed on transport/parsing boundary
            row = _source_row(kind, url, None, None, f"{type(exc).__name__}: {exc}")
        sources.append(row)
    if any(row["health_state"] != "HEALTHY" for row in sources):
        return _degraded_receipt(registry, run_id, observed, sources, "SOURCE_TRANSPORT_OR_AUTHORITY_DEGRADED"), raws
    try:
        exact_text = html_text(raws["exact"])
        closed_text = html_text(raws["closed_index"])
        _require_markers(exact_text, list(registry["required_exact_markers"]), "RO-BG exact Call 6")
        _require_markers(closed_text, list(registry["required_closed_index_markers"]), "RO-BG current closed-calls index")
        deadline = _deadline(exact_text)
    except Exception as exc:
        return _degraded_receipt(registry, run_id, observed, sources, f"SEMANTIC_MARKER_DRIFT: {type(exc).__name__}: {exc}"), raws
    semantics = {
        "programme_id": registry["programme_id"],
        "official_call_identifier": str(registry["official_call_identifier"]),
        "official_call_identifier_kind": registry["official_call_identifier_kind"],
        "call_title": "Call 6",
        "exact_authority_url": registry["exact_url"],
        "closed_index_authority_url": registry["closed_index_url"],
        "candidate_state": "CLOSED_CALL_CANDIDATE",
        "candidate_status_label": "Closed calls for proposals",
        "candidate_deadline_text": deadline,
        "candidate_launch_date_text": "23 June 2025",
        "status_basis": "CURRENT_OFFICIAL_PROGRAMME_CLOSED_CALL_INDEX_LISTS_CALL_6",
    }
    receipt: dict[str, Any] = {
        "schema": SCHEMA, "parser_version": PARSER_VERSION,
        "source_family": registry["source_family"], "programme_family": registry["programme_family"],
        "programme_id": registry["programme_id"], "programme": registry["programme"],
        "authority_class": registry["authority_class"], "observation_state": "EXACT_CALL_CURRENT_EVIDENCE_NON_AUTHORIZING",
        "run_id": run_id, "fetched_at": observed,
        "official_call_identifier": str(registry["official_call_identifier"]),
        "official_call_identifier_kind": registry["official_call_identifier_kind"],
        "exact_authority_url": registry["exact_url"], "closed_index_authority_url": registry["closed_index_url"],
        "source_health_state": "HEALTHY", "lkg_required": False, "sources": sources,
        "candidate_state": semantics["candidate_state"], "candidate_status_label": semantics["candidate_status_label"],
        "candidate_deadline_text": deadline, "candidate_launch_date_text": semantics["candidate_launch_date_text"],
        "status_basis": semantics["status_basis"], "exact_semantics": semantics,
        "exact_semantic_fingerprint": sha256_json(semantics),
        "territorial_relevance": registry["territorial_relevance"],
        "market_intelligence_only": False, "field_scoped_material_admission_required": True,
        "semantic_reconciliation_required": True, "publication_effect": "NONE",
        "missing_for_material_admission": list(MISSING_FOR_MATERIAL_ADMISSION),
        "degraded_reason": None,
    }
    for flag in MATERIAL_FLAGS:
        receipt[flag] = False
    validate_evidence(receipt)
    return receipt, raws


def validate_evidence(receipt: Mapping[str, Any]) -> None:
    if receipt.get("schema") != SCHEMA or receipt.get("parser_version") != PARSER_VERSION:
        raise ValueError("RO-BG exact evidence schema/parser drift")
    if receipt.get("source_family") != "INTERREG" or receipt.get("programme_family") != "INTERREG_ROMANIA_BULGARIA_2021_2027":
        raise ValueError("RO-BG exact evidence family drift")
    if str(receipt.get("official_call_identifier")) != "6" or receipt.get("official_call_identifier_kind") != "OFFICIAL_CALL_NUMBER":
        raise ValueError("RO-BG exact evidence identity drift")
    for flag in MATERIAL_FLAGS:
        if receipt.get(flag) is not False:
            raise ValueError(f"RO-BG exact evidence became authorizing: {flag}")
    if receipt.get("publication_effect") != "NONE" or receipt.get("field_scoped_material_admission_required") is not True:
        raise ValueError("RO-BG exact evidence publication/admission drift")
    relevance = receipt.get("territorial_relevance") or {}
    if relevance.get("programme_area_relevance_only") is not True or relevance.get("call_eligibility_authorized") is not False:
        raise ValueError("RO-BG programme geography promoted to call eligibility")
    if receipt.get("source_health_state") == "HEALTHY":
        if receipt.get("candidate_state") != "CLOSED_CALL_CANDIDATE" or receipt.get("candidate_status_label") != "Closed calls for proposals":
            raise ValueError("RO-BG current lifecycle candidate drift")
        if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("exact_semantic_fingerprint") or "")):
            raise ValueError("RO-BG exact semantic fingerprint invalid")
        if sha256_json(receipt.get("exact_semantics")) != receipt.get("exact_semantic_fingerprint"):
            raise ValueError("RO-BG exact semantic fingerprint tampered")
        if receipt.get("lkg_required") is not False:
            raise ValueError("RO-BG healthy current evidence unexpectedly requires LKG")
    elif receipt.get("source_health_state") == "DEGRADED":
        if receipt.get("candidate_state") != "UNKNOWN" or receipt.get("exact_semantic_fingerprint") is not None:
            raise ValueError("RO-BG degraded evidence retained material semantics")
        if receipt.get("lkg_required") is not True:
            raise ValueError("RO-BG degraded evidence failed to require LKG")
    else:
        raise ValueError("RO-BG exact evidence source-health drift")


def reconcile(current: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    validate_evidence(current)
    base = {
        "schema": RECONCILIATION_SCHEMA, "reconciler_version": RECONCILIATION_VERSION,
        "source_family": current["source_family"], "programme_family": current["programme_family"],
        "programme_id": current["programme_id"], "official_call_identifier": current["official_call_identifier"],
        "current_fetched_at": current["fetched_at"], "current_evidence_sha256": sha256_json(current),
        "previous_fetched_at": None, "previous_evidence_sha256": None,
        "semantic_change_count": 0, "semantic_changes": [], "semantic_reconciliation_passed": False,
        "material_admission_ready_for_downstream_review": False,
        "field_scoped_material_admission_required": True,
        "missing_for_material_admission": list(MISSING_FOR_MATERIAL_ADMISSION),
        "lkg_reference_required": current.get("source_health_state") == "DEGRADED",
        "lkg_reference_is_current_truth": False, "publication_effect": "NONE",
    }
    for flag in MATERIAL_FLAGS:
        base[flag] = False
    if current.get("source_health_state") != "HEALTHY":
        base["reconciliation_state"] = "CURRENT_SOURCE_DEGRADED_FAIL_CLOSED"
        return base
    if previous is None:
        base["reconciliation_state"] = "BASELINE_CAPTURED_NON_AUTHORIZING"
        base["semantic_reconciliation_passed"] = True
        return base
    validate_evidence(previous)
    if previous.get("source_health_state") != "HEALTHY":
        raise ValueError("RO-BG previous comparison receipt is degraded and cannot be semantic baseline")
    identity = ("programme_family", "programme_id", "official_call_identifier", "exact_authority_url", "closed_index_authority_url")
    if any(previous.get(key) != current.get(key) for key in identity):
        raise ValueError("RO-BG same-identity reconciliation rejected identity drift")
    if parse_time(str(previous["fetched_at"])) >= parse_time(str(current["fetched_at"])):
        raise ValueError("RO-BG same-identity reconciliation rejected history inversion")
    base["previous_fetched_at"] = previous["fetched_at"]
    base["previous_evidence_sha256"] = sha256_json(previous)
    previous_sem = previous.get("exact_semantics") or {}
    current_sem = current.get("exact_semantics") or {}
    keys = ("candidate_state", "candidate_status_label", "candidate_deadline_text", "candidate_launch_date_text")
    changes = [{"field": key, "previous": previous_sem.get(key), "current": current_sem.get(key)} for key in keys if previous_sem.get(key) != current_sem.get(key)]
    base["semantic_changes"] = changes
    base["semantic_change_count"] = len(changes)
    base["semantic_reconciliation_passed"] = True
    base["material_admission_ready_for_downstream_review"] = True
    base["reconciliation_state"] = "NO_CHANGE" if not changes else "RO_BG_CALL6_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
    return base


def write_outputs(output_dir: pathlib.Path, evidence: Mapping[str, Any], reconciliation: Mapping[str, Any], raws: Mapping[str, bytes]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "interreg-ro-bg-call6-exact-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (output_dir / "interreg-ro-bg-call6-exact-reconciliation.json").write_text(json.dumps(reconciliation, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if "exact" in raws:
        (output_dir / "exact-call.html").write_bytes(raws["exact"])
    if "closed_index" in raws:
        (output_dir / "closed-calls-index.html").write_bytes(raws["closed_index"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--previous")
    args = parser.parse_args()
    registry = load_registry(args.registry)
    evidence, raws = collect(registry=registry, run_id=args.run_id)
    previous = json.loads(pathlib.Path(args.previous).read_text(encoding="utf-8")) if args.previous else None
    reconciliation = reconcile(evidence, previous)
    write_outputs(pathlib.Path(args.output_dir), evidence, reconciliation, raws)
    print(json.dumps({
        "source_health_state": evidence["source_health_state"],
        "official_call_identifier": evidence["official_call_identifier"],
        "candidate_state": evidence["candidate_state"],
        "reconciliation_state": reconciliation["reconciliation_state"],
        "semantic_change_count": reconciliation["semantic_change_count"],
        "closed_call_authorized": False,
        "publication_effect": "NONE",
    }, sort_keys=True))


if __name__ == "__main__":
    main()
