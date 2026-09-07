#!/usr/bin/env python3
"""Exact-current, non-authorizing pilot for one Interreg Danube call.

The pilot is intentionally bound to one stable official exact endpoint and the
programme's current official calls index. It may observe a candidate lifecycle
state and deadline only as exact evidence. It never authorizes publication or a
material call fact; field-scoped admission remains a later gate.
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

SCHEMA = "PARTENER_EU_INTERREG_DANUBE_EXACT_CALL_V1"
PARSER_VERSION = "INTERREG_DANUBE_EXACT_CALL_V1"
RECONCILIATION_SCHEMA = "PARTENER_EU_INTERREG_DANUBE_EXACT_RECONCILIATION_V1"
RECONCILIATION_PARSER_VERSION = "INTERREG_DANUBE_EXACT_RECONCILE_V1"
SOURCE_FAMILY = "INTERREG"
PROGRAMME_FAMILY = "INTERREG_DANUBE_REGION_2021_2027"
PROGRAMME_ID = "DANUBE"
PROGRAMME = "Interreg Danube Region Programme"
AUTHORITY_CLASS = "T1_OFFICIAL_PROGRAMME_EXACT_CALL"
CALL_IDENTIFIER = "third-call-for-proposals"
CALL_IDENTIFIER_KIND = "OFFICIAL_EXACT_ENDPOINT_SLUG"
EXACT_URL = "https://interreg-danube.eu/calls-for-proposals/third-call-for-proposals"
INDEX_URL = "https://interreg-danube.eu/calls-for-proposals"
ALLOWED_HOSTS = {"interreg-danube.eu", "www.interreg-danube.eu"}

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
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


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


def host_allowed(url: str) -> bool:
    return (urllib.parse.urlparse(url).hostname or "").casefold() in ALLOWED_HOSTS


def default_fetch(url: str, timeout: float = 30.0) -> tuple[bytes, dict[str, Any]]:
    req = urllib.request.Request(url, headers={
        "User-Agent": "PARTENER.EU-exact-call/1.0 (+https://partener.eu)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en",
    })
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError(f"Danube exact source exceeds 5 MB: {url}")
        meta = {
            "requested_url": url,
            "final_url": str(response.geturl()),
            "status": int(getattr(response, "status", 200) or 200),
            "content_type": str(response.headers.get("Content-Type") or ""),
        }
    if meta["status"] != 200:
        raise ValueError(f"Danube exact source returned HTTP {meta['status']}: {url}")
    if not host_allowed(meta["final_url"]):
        raise ValueError("Danube exact source left official programme authority")
    return raw, meta


def require(text: str, anchors: tuple[str, ...], *, source: str) -> None:
    hay = normal(text)
    missing = [anchor for anchor in anchors if normal(anchor) not in hay]
    if missing:
        raise ValueError(f"{source} missing exact-call anchors: {missing}")


def _deadline_text(exact_text: str) -> str:
    match = re.search(
        r"open until\s+15\s+december\s+2025.*?15th\s+of\s+december,?\s+14\.00\s+central european time\s*\(cet\)",
        normal(exact_text),
    )
    if not match:
        raise ValueError("Danube exact endpoint no longer exposes the expected call deadline statement")
    return "15 December 2025, 14:00 CET"


def collect(
    *,
    run_id: str,
    fetched_at: str | None = None,
    fetcher: Callable[[str], tuple[bytes, dict[str, Any]]] = default_fetch,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    observed = fetched_at or utc_now()
    exact_raw, exact_meta = fetcher(EXACT_URL)
    index_raw, index_meta = fetcher(INDEX_URL)
    for name, meta in (("exact", exact_meta), ("index", index_meta)):
        if int(meta.get("status") or 0) != 200:
            raise ValueError(f"Danube {name} authority did not return HTTP 200")
        final = str(meta.get("final_url") or meta.get("requested_url") or "")
        if not host_allowed(final):
            raise ValueError(f"Danube {name} authority escaped official host")

    exact_text = html_text(exact_raw)
    index_text = html_text(index_raw)
    require(
        exact_text,
        (
            "Third call for proposals",
            "The 3rd CfP is open until 15 December 2025",
            "The Application Form (AF) must be submitted",
        ),
        source="Danube exact call",
    )
    require(
        index_text,
        (
            "Calls for proposals",
            "Closed calls",
            "Application deadline 15 Dec 2025",
            "Third call for proposals",
        ),
        source="Danube calls index",
    )
    deadline = _deadline_text(exact_text)

    semantics = {
        "programme_id": PROGRAMME_ID,
        "programme": PROGRAMME,
        "call_identifier": CALL_IDENTIFIER,
        "call_identifier_kind": CALL_IDENTIFIER_KIND,
        "exact_authority_url": EXACT_URL,
        "current_index_authority_url": INDEX_URL,
        "call_title": "Third call for proposals",
        "candidate_state": "CLOSED_CALL_CANDIDATE",
        "candidate_status_label": "Closed calls",
        "candidate_deadline_text": deadline,
        "status_basis": "CURRENT_OFFICIAL_PROGRAMME_INDEX_CLASSIFIES_THE_EXACT_CALL_UNDER_CLOSED_CALLS",
    }
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "programme_id": PROGRAMME_ID,
        "programme": PROGRAMME,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": "EXACT_CALL_CURRENT_EVIDENCE_NON_AUTHORIZING",
        "run_id": run_id,
        "fetched_at": observed,
        "call_identifier": CALL_IDENTIFIER,
        "call_identifier_kind": CALL_IDENTIFIER_KIND,
        "exact_authority_url": EXACT_URL,
        "current_index_authority_url": INDEX_URL,
        "exact_final_url": str(exact_meta.get("final_url") or EXACT_URL),
        "index_final_url": str(index_meta.get("final_url") or INDEX_URL),
        "exact_http_status": int(exact_meta.get("status") or 200),
        "index_http_status": int(index_meta.get("status") or 200),
        "exact_source_sha256": sha256_bytes(exact_raw),
        "index_source_sha256": sha256_bytes(index_raw),
        "exact_authority_verified": True,
        "current_index_authority_verified": True,
        "candidate_state": semantics["candidate_state"],
        "candidate_status_label": semantics["candidate_status_label"],
        "candidate_deadline_text": deadline,
        "status_basis": semantics["status_basis"],
        "exact_semantics": semantics,
        "exact_semantic_fingerprint": sha256_json(semantics),
        "market_intelligence_only": False,
        "field_scoped_material_admission_required": True,
        "publication_effect": "NONE",
        "missing_for_material_admission": list(MISSING_FOR_MATERIAL_ADMISSION),
    }
    for flag in MATERIAL_FLAGS:
        receipt[flag] = False
    validate_evidence(receipt)
    return receipt, {"exact": exact_raw, "index": index_raw}


def validate_evidence(receipt: Mapping[str, Any]) -> None:
    if receipt.get("schema") != SCHEMA or receipt.get("parser_version") != PARSER_VERSION:
        raise ValueError("Danube exact-call schema/parser drift")
    if receipt.get("source_family") != SOURCE_FAMILY or receipt.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("Danube exact-call family drift")
    if receipt.get("programme_id") != PROGRAMME_ID or receipt.get("call_identifier") != CALL_IDENTIFIER:
        raise ValueError("Danube exact-call identity drift")
    if receipt.get("call_identifier_kind") != CALL_IDENTIFIER_KIND:
        raise ValueError("Danube exact-call identifier kind drift")
    if receipt.get("exact_authority_url") != EXACT_URL or receipt.get("current_index_authority_url") != INDEX_URL:
        raise ValueError("Danube exact-call authority drift")
    if receipt.get("exact_authority_verified") is not True or receipt.get("current_index_authority_verified") is not True:
        raise ValueError("Danube exact-call authority not verified")
    if receipt.get("candidate_state") != "CLOSED_CALL_CANDIDATE" or receipt.get("candidate_status_label") != "Closed calls":
        raise ValueError("Danube exact-call candidate lifecycle drift")
    semantics = receipt.get("exact_semantics")
    if not isinstance(semantics, Mapping) or sha256_json(semantics) != receipt.get("exact_semantic_fingerprint"):
        raise ValueError("Danube exact-call semantic fingerprint tampered")
    if receipt.get("field_scoped_material_admission_required") is not True:
        raise ValueError("Danube exact-call weakened field-scoped admission")
    missing = set(receipt.get("missing_for_material_admission") or [])
    if not set(MISSING_FOR_MATERIAL_ADMISSION).issubset(missing):
        raise ValueError("Danube exact-call weakened material-admission requirements")
    for flag in MATERIAL_FLAGS:
        if receipt.get(flag) is not False:
            raise ValueError(f"Danube exact-call attempted authorization: {flag}")
    if receipt.get("publication_effect") != "NONE":
        raise ValueError("Danube exact-call attempted publication effect")


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Danube exact reconciliation timestamps must be timezone-aware")
    return parsed


def reconcile(current: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    validate_evidence(current)
    changes: list[dict[str, Any]] = []
    if previous is None:
        state = "BASELINE_CAPTURED_NON_AUTHORIZING"
    else:
        validate_evidence(previous)
        if previous.get("call_identifier") != current.get("call_identifier"):
            raise ValueError("Danube exact reconciliation identity mismatch")
        if previous.get("exact_authority_url") != current.get("exact_authority_url"):
            raise ValueError("Danube exact reconciliation authority mismatch")
        if parse_time(str(previous.get("fetched_at"))) > parse_time(str(current.get("fetched_at"))):
            raise ValueError("previous Danube exact evidence is newer than current")
        before = dict(previous["exact_semantics"])
        after = dict(current["exact_semantics"])
        for key in sorted(set(before) | set(after)):
            if before.get(key) != after.get(key):
                changes.append({"field": key, "before": before.get(key), "after": after.get(key)})
        state = "NO_CHANGE" if not changes else "DANUBE_EXACT_CALL_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"

    receipt: dict[str, Any] = {
        "schema": RECONCILIATION_SCHEMA,
        "parser_version": RECONCILIATION_PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "programme_id": PROGRAMME_ID,
        "call_identifier": CALL_IDENTIFIER,
        "current_fetched_at": current.get("fetched_at"),
        "previous_fetched_at": previous.get("fetched_at") if previous else None,
        "current_evidence_sha256": sha256_json(current),
        "previous_evidence_sha256": sha256_json(previous) if previous else None,
        "current_exact_semantic_fingerprint": current.get("exact_semantic_fingerprint"),
        "previous_exact_semantic_fingerprint": previous.get("exact_semantic_fingerprint") if previous else None,
        "reconciliation_state": state,
        "semantic_change_count": len(changes),
        "semantic_changes": changes,
        "semantic_reconciliation_passed": True,
        "material_admission_ready_for_downstream_review": previous is not None,
        "field_scoped_material_admission_required": True,
        "publication_effect": "NONE",
    }
    for flag in MATERIAL_FLAGS:
        receipt[flag] = False
    validate_reconciliation(receipt, current=current, previous=previous)
    return receipt


def validate_reconciliation(
    receipt: Mapping[str, Any], *, current: Mapping[str, Any], previous: Mapping[str, Any] | None = None
) -> None:
    if receipt.get("schema") != RECONCILIATION_SCHEMA or receipt.get("parser_version") != RECONCILIATION_PARSER_VERSION:
        raise ValueError("Danube reconciliation schema/parser drift")
    validate_evidence(current)
    if receipt.get("call_identifier") != CALL_IDENTIFIER or receipt.get("current_evidence_sha256") != sha256_json(current):
        raise ValueError("Danube reconciliation current binding failed")
    if previous is None:
        if receipt.get("reconciliation_state") != "BASELINE_CAPTURED_NON_AUTHORIZING":
            raise ValueError("Danube baseline reconciliation invalid")
        if receipt.get("previous_evidence_sha256") is not None or receipt.get("material_admission_ready_for_downstream_review") is not False:
            raise ValueError("Danube baseline unexpectedly ready for material admission")
    else:
        validate_evidence(previous)
        if receipt.get("previous_evidence_sha256") != sha256_json(previous):
            raise ValueError("Danube reconciliation previous binding failed")
        expected = "NO_CHANGE" if previous.get("exact_semantic_fingerprint") == current.get("exact_semantic_fingerprint") else "DANUBE_EXACT_CALL_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
        if receipt.get("reconciliation_state") != expected:
            raise ValueError("Danube reconciliation state disagrees with semantic fingerprints")
        if receipt.get("material_admission_ready_for_downstream_review") is not True:
            raise ValueError("Danube same-identity reconciliation should be ready only for downstream review")
    for flag in MATERIAL_FLAGS:
        if receipt.get(flag) is not False:
            raise ValueError(f"Danube reconciliation attempted authorization: {flag}")
    if receipt.get("publication_effect") != "NONE" or receipt.get("field_scoped_material_admission_required") is not True:
        raise ValueError("Danube reconciliation crossed admission/publication boundary")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--reconciliation-output", required=True, type=pathlib.Path)
    parser.add_argument("--previous", type=pathlib.Path)
    args = parser.parse_args()
    current, raw = collect(run_id=args.run_id)
    previous = json.loads(args.previous.read_text(encoding="utf-8")) if args.previous else None
    reconciliation = reconcile(current, previous)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(current, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    args.reconciliation_output.parent.mkdir(parents=True, exist_ok=True)
    args.reconciliation_output.write_text(json.dumps(reconciliation, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (args.output.parent / "danube-third-call-exact.html").write_bytes(raw["exact"])
    (args.output.parent / "danube-calls-index.html").write_bytes(raw["index"])
    print(json.dumps({
        "call_identifier": CALL_IDENTIFIER,
        "candidate_state": current["candidate_state"],
        "candidate_deadline_text": current["candidate_deadline_text"],
        "reconciliation_state": reconciliation["reconciliation_state"],
        "semantic_change_count": reconciliation["semantic_change_count"],
        "open_call_authorized": current["open_call_authorized"],
        "closed_call_authorized": current["closed_call_authorized"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
