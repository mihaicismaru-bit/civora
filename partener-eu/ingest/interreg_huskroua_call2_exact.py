#!/usr/bin/env python3
"""Exact, current, fail-closed evidence for HUSKROUA 2nd Call lifecycle.

This adapter binds the official 2nd Call detail page to the programme-owned
closure announcement. It may observe a CLOSED_CALL_CANDIDATE, but it never
authorizes status, deadline, budget, eligibility, publication, distribution or
alerts. Same-identity semantic reconciliation and field-scoped material
admission remain mandatory downstream.
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

SCHEMA = "PARTENER_EU_INTERREG_HUSKROUA_CALL2_EXACT_EVIDENCE_V1"
PARSER_VERSION = "INTERREG_HUSKROUA_CALL2_EXACT_V1"
REGISTRY_SCHEMA = "PARTENER_EU_INTERREG_HUSKROUA_CALL2_EXACT_REGISTRY_V1"
ALLOWED_HOSTS = {"next.huskroua-cbc.eu", "www.next.huskroua-cbc.eu"}
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


def default_fetch(url: str, timeout: float = 30.0) -> tuple[bytes, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; PARTENER.EU/1.0; +https://partener.eu)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError("HUSKROUA exact source exceeds 5 MB")
        meta = {
            "requested_url": url,
            "final_url": str(response.geturl()),
            "http_status": int(getattr(response, "status", 200) or 200),
            "content_type": str(response.headers.get("Content-Type") or ""),
        }
    return raw, meta


def _host_ok(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and (parsed.hostname or "").casefold() in ALLOWED_HOSTS


def validate_registry(registry: Mapping[str, Any]) -> None:
    if registry.get("schema") != REGISTRY_SCHEMA:
        raise ValueError("HUSKROUA Call 2 registry schema drift")
    if registry.get("source_family") != "INTERREG" or registry.get("programme_family") != "INTERREG_HUSKROUA_2021_2027":
        raise ValueError("HUSKROUA Call 2 family drift")
    if registry.get("programme_id") != "HUSKROUA":
        raise ValueError("HUSKROUA programme identity drift")
    if str(registry.get("official_call_identifier")) != "2" or registry.get("official_call_identifier_kind") != "OFFICIAL_CALL_NUMBER":
        raise ValueError("HUSKROUA Call 2 identity drift")
    for key in ("exact_call_url", "closure_url"):
        if not _host_ok(str(registry.get(key) or "")):
            raise ValueError(f"HUSKROUA authority drift: {key}")
    if urllib.parse.urlparse(str(registry["exact_call_url"])).path.rstrip("/") != "/calls/2nd-call-for-proposals":
        raise ValueError("HUSKROUA exact call path drift")
    if "closure-of-the-2nd-call-for-proposals" not in urllib.parse.urlparse(str(registry["closure_url"])).path:
        raise ValueError("HUSKROUA closure path drift")
    policy = registry.get("policy") or {}
    for flag in MATERIAL_FLAGS:
        if policy.get(flag) is not False:
            raise ValueError(f"HUSKROUA registry weakened fail-closed policy: {flag}")
    if policy.get("semantic_reconciliation_required") is not True or policy.get("field_scoped_material_admission_required") is not True:
        raise ValueError("HUSKROUA registry weakened material admission")
    if policy.get("previous_or_lkg_is_current_truth") is not False:
        raise ValueError("HUSKROUA registry promoted history/LKG to current truth")


def load_registry(path: str | pathlib.Path) -> dict[str, Any]:
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    validate_registry(data)
    return data


def _require_markers(text: str, markers: list[str], source: str) -> None:
    hay = normal(text)
    missing = [marker for marker in markers if normal(marker) not in hay]
    if missing:
        raise ValueError(f"{source} missing required provenance markers: {missing}")


def _source_row(kind: str, url: str, raw: bytes | None, meta: Mapping[str, Any] | None, error: str | None) -> dict[str, Any]:
    if error is not None:
        return {
            "kind": kind,
            "requested_url": url,
            "final_url": None,
            "http_status": None,
            "content_type": None,
            "raw_sha256": None,
            "normalized_visible_text_sha256": None,
            "health_state": "DEGRADED",
            "lkg_required": True,
            "error": error,
        }
    assert raw is not None and meta is not None
    final = str(meta.get("final_url") or url)
    status = int(meta.get("http_status") or 0)
    ctype = str(meta.get("content_type") or "")
    healthy = status == 200 and _host_ok(final) and "html" in ctype.casefold()
    return {
        "kind": kind,
        "requested_url": url,
        "final_url": final if healthy else None,
        "http_status": status if healthy else None,
        "content_type": ctype if healthy else None,
        "raw_sha256": sha256_bytes(raw) if healthy else None,
        "normalized_visible_text_sha256": visible_text_sha256(raw) if healthy else None,
        "health_state": "HEALTHY" if healthy else "DEGRADED",
        "lkg_required": not healthy,
        "error": None if healthy else "HTTP_OR_AUTHORITY_OR_CONTENT_TYPE_DRIFT",
    }


def _degraded_receipt(registry: Mapping[str, Any], run_id: str, fetched_at: str, sources: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": registry["source_family"],
        "programme_family": registry["programme_family"],
        "programme_id": registry["programme_id"],
        "programme": registry["programme"],
        "authority_class": registry["authority_class"],
        "observation_state": "EXACT_CALL_EVIDENCE_DEGRADED_FAIL_CLOSED",
        "run_id": run_id,
        "fetched_at": fetched_at,
        "official_call_identifier": str(registry["official_call_identifier"]),
        "official_call_identifier_kind": registry["official_call_identifier_kind"],
        "exact_authority_url": registry["exact_call_url"],
        "closure_authority_url": registry["closure_url"],
        "source_health_state": "DEGRADED",
        "lkg_required": True,
        "current_material_truth_available": False,
        "sources": sources,
        "candidate_state": "UNKNOWN",
        "candidate_status_label": None,
        "exact_semantics": None,
        "exact_semantic_fingerprint": None,
        "semantic_reconciliation_required": True,
        "field_scoped_material_admission_required": True,
        "previous_or_lkg_is_current_truth": False,
        "missing_for_material_admission": list(MISSING_FOR_MATERIAL_ADMISSION),
        "publication_effect": "NONE",
        "degraded_reason": reason,
    }
    for flag in MATERIAL_FLAGS:
        receipt[flag] = False
    return receipt


def collect(
    *,
    registry: Mapping[str, Any],
    run_id: str,
    fetched_at: str | None = None,
    fetcher: Callable[[str], tuple[bytes, dict[str, Any]]] = default_fetch,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    validate_registry(registry)
    observed = fetched_at or utc_now()
    raws: dict[str, bytes] = {}
    sources: list[dict[str, Any]] = []
    for kind, key in (("exact_call", "exact_call_url"), ("closure", "closure_url")):
        url = str(registry[key])
        try:
            raw, meta = fetcher(url)
            row = _source_row(kind, url, raw, meta, None)
            if row["health_state"] == "HEALTHY":
                raws[kind] = raw
        except Exception as exc:
            row = _source_row(kind, url, None, None, f"{type(exc).__name__}: {exc}")
        sources.append(row)

    if any(row["health_state"] != "HEALTHY" for row in sources):
        receipt = _degraded_receipt(registry, run_id, observed, sources, "SOURCE_TRANSPORT_OR_AUTHORITY_DEGRADED")
        validate_evidence(receipt)
        return receipt, raws

    try:
        exact_text = html_text(raws["exact_call"])
        closure_text = html_text(raws["closure"])
        _require_markers(exact_text, list(registry["required_exact_markers"]), "HUSKROUA Call 2 detail")
        _require_markers(closure_text, list(registry["required_closure_markers"]), "HUSKROUA Call 2 closure")
    except Exception as exc:
        receipt = _degraded_receipt(registry, run_id, observed, sources, f"SEMANTIC_MARKER_DRIFT: {type(exc).__name__}: {exc}")
        validate_evidence(receipt)
        return receipt, raws

    source_hashes = {row["kind"]: row["normalized_visible_text_sha256"] for row in sources}
    semantics = {
        "programme_id": registry["programme_id"],
        "official_call_identifier": str(registry["official_call_identifier"]),
        "official_call_identifier_kind": registry["official_call_identifier_kind"],
        "call_title": "2nd Call for Proposals",
        "exact_authority_url": registry["exact_call_url"],
        "closure_authority_url": registry["closure_url"],
        "candidate_state": "CLOSED_CALL_CANDIDATE",
        "candidate_status_label": "Closed",
        "status_basis": "CURRENT_OFFICIAL_PROGRAMME_CLOSURE_ANNOUNCEMENT",
        "source_visible_text_sha256": source_hashes,
    }
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": registry["source_family"],
        "programme_family": registry["programme_family"],
        "programme_id": registry["programme_id"],
        "programme": registry["programme"],
        "authority_class": registry["authority_class"],
        "observation_state": "EXACT_CALL_CURRENT_EVIDENCE_NON_AUTHORIZING",
        "run_id": run_id,
        "fetched_at": observed,
        "official_call_identifier": str(registry["official_call_identifier"]),
        "official_call_identifier_kind": registry["official_call_identifier_kind"],
        "exact_authority_url": registry["exact_call_url"],
        "closure_authority_url": registry["closure_url"],
        "source_health_state": "HEALTHY",
        "lkg_required": False,
        "current_material_truth_available": False,
        "sources": sources,
        "candidate_state": semantics["candidate_state"],
        "candidate_status_label": semantics["candidate_status_label"],
        "status_basis": semantics["status_basis"],
        "exact_semantics": semantics,
        "exact_semantic_fingerprint": sha256_json(semantics),
        "semantic_reconciliation_required": True,
        "field_scoped_material_admission_required": True,
        "previous_or_lkg_is_current_truth": False,
        "missing_for_material_admission": list(MISSING_FOR_MATERIAL_ADMISSION),
        "publication_effect": "NONE",
        "degraded_reason": None,
    }
    for flag in MATERIAL_FLAGS:
        receipt[flag] = False
    validate_evidence(receipt)
    return receipt, raws


def validate_evidence(receipt: Mapping[str, Any]) -> None:
    if receipt.get("schema") != SCHEMA or receipt.get("parser_version") != PARSER_VERSION:
        raise ValueError("HUSKROUA Call 2 evidence schema/parser drift")
    if receipt.get("source_family") != "INTERREG" or receipt.get("programme_family") != "INTERREG_HUSKROUA_2021_2027":
        raise ValueError("HUSKROUA Call 2 evidence family drift")
    if receipt.get("programme_id") != "HUSKROUA" or str(receipt.get("official_call_identifier")) != "2":
        raise ValueError("HUSKROUA Call 2 evidence identity drift")
    if receipt.get("official_call_identifier_kind") != "OFFICIAL_CALL_NUMBER":
        raise ValueError("HUSKROUA Call 2 identifier-kind drift")
    if not _host_ok(str(receipt.get("exact_authority_url") or "")) or not _host_ok(str(receipt.get("closure_authority_url") or "")):
        raise ValueError("HUSKROUA Call 2 evidence authority drift")
    if receipt.get("semantic_reconciliation_required") is not True or receipt.get("field_scoped_material_admission_required") is not True:
        raise ValueError("HUSKROUA Call 2 material-admission boundary weakened")
    if receipt.get("previous_or_lkg_is_current_truth") is not False or receipt.get("current_material_truth_available") is not False:
        raise ValueError("HUSKROUA Call 2 promoted evidence/history to current material truth")
    if receipt.get("publication_effect") != "NONE":
        raise ValueError("HUSKROUA Call 2 publication boundary drift")
    for flag in MATERIAL_FLAGS:
        if receipt.get(flag) is not False:
            raise ValueError(f"HUSKROUA Call 2 attempted authorization: {flag}")

    state = receipt.get("source_health_state")
    sources = receipt.get("sources")
    if not isinstance(sources, list) or len(sources) != 2:
        raise ValueError("HUSKROUA Call 2 requires two official source receipts")
    if {row.get("kind") for row in sources} != {"exact_call", "closure"}:
        raise ValueError("HUSKROUA Call 2 source set drift")

    if state == "HEALTHY":
        if receipt.get("lkg_required") is not False or receipt.get("candidate_state") != "CLOSED_CALL_CANDIDATE":
            raise ValueError("HUSKROUA Call 2 healthy state/candidate drift")
        if receipt.get("candidate_status_label") != "Closed" or receipt.get("status_basis") != "CURRENT_OFFICIAL_PROGRAMME_CLOSURE_ANNOUNCEMENT":
            raise ValueError("HUSKROUA Call 2 closure semantics drift")
        for row in sources:
            if row.get("health_state") != "HEALTHY" or row.get("http_status") != 200 or not _host_ok(str(row.get("final_url") or "")):
                raise ValueError("HUSKROUA Call 2 healthy source receipt drift")
            if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("raw_sha256") or "")):
                raise ValueError("HUSKROUA Call 2 healthy source lost raw SHA-256")
            if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("normalized_visible_text_sha256") or "")):
                raise ValueError("HUSKROUA Call 2 healthy source lost visible-text SHA-256")
        semantics = receipt.get("exact_semantics")
        if not isinstance(semantics, Mapping) or receipt.get("exact_semantic_fingerprint") != sha256_json(semantics):
            raise ValueError("HUSKROUA Call 2 exact semantic fingerprint mismatch")
        expected_hashes = {row["kind"]: row["normalized_visible_text_sha256"] for row in sources}
        if semantics.get("source_visible_text_sha256") != expected_hashes:
            raise ValueError("HUSKROUA Call 2 semantic/source hash binding drift")
    elif state == "DEGRADED":
        if receipt.get("lkg_required") is not True or receipt.get("candidate_state") != "UNKNOWN":
            raise ValueError("HUSKROUA Call 2 degraded state failed closed")
        if receipt.get("candidate_status_label") is not None or receipt.get("exact_semantics") is not None or receipt.get("exact_semantic_fingerprint") is not None:
            raise ValueError("HUSKROUA Call 2 degraded state retained semantic facts")
        if not receipt.get("degraded_reason"):
            raise ValueError("HUSKROUA Call 2 degraded state lacks reason")
    else:
        raise ValueError("HUSKROUA Call 2 source health drift")


def write_outputs(receipt: Mapping[str, Any], raws: Mapping[str, bytes], out_dir: pathlib.Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "huskroua-call2-exact-evidence.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(exist_ok=True)
    for kind, raw in raws.items():
        (raw_dir / f"{kind}.html").write_bytes(raw)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default="partener-eu/ingest/interreg_huskroua_call2_exact_registry.json")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    receipt, raws = collect(registry=load_registry(args.registry), run_id=args.run_id)
    write_outputs(receipt, raws, pathlib.Path(args.out_dir))
    print(json.dumps({
        "schema": receipt["schema"],
        "source_health_state": receipt["source_health_state"],
        "candidate_state": receipt["candidate_state"],
        "official_call_identifier": receipt["official_call_identifier"],
        "exact_semantic_fingerprint": receipt["exact_semantic_fingerprint"],
        "publication_effect": receipt["publication_effect"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
