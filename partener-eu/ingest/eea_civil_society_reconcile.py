#!/usr/bin/env python3
"""Fail-closed semantic reconciliation for EEA Civil Society Fund Romania live evidence.

This stage can authorize exact official call-page facts for canonical staging, but it
never publishes them. It requires a complete live-evidence envelope, exact official
readback, intact semantic fingerprints, parseable material fields, and zero
conflicts/errors. Any defect rejects the whole batch; no partial promotion occurs.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
from typing import Any
from urllib.parse import urlparse

SCHEMA = "PARTENER_EU_EEA_CSF_RECONCILIATION_RECEIPT_V1"
INPUT_SCHEMA = "PARTENER_EU_EEA_CSF_LIVE_EVIDENCE_V1"
SOURCE_FAMILY = "EEA_NORWAY"
PROGRAMME_FAMILY = "EEA Civil Society Fund Romania 2021-2028"
AUTHORITY_CLASS = "EEA_FMO_CIVIL_SOCIETY_FUND_ROMANIA"
OFFICIAL_HOSTS = {"eeagrants.org", "www.eeagrants.org"}
CALL_PATH_RE = re.compile(
    r"^/(?:en|ro)/eea-civil-society-fund-romania/calls/call-(?P<number>\d+)-[^/?#]+/?$",
    re.IGNORECASE,
)
CALL_ID_RE = re.compile(r"^EEA-CSF-RO-CALL-(\d{2})$")
STATE_LABELS = {
    "OPEN_CALL": {"OPEN", "OPEN CALL"},
    "FORTHCOMING_CALL": {"FORTHCOMING", "UPCOMING", "FORTHCOMING CALL"},
    "CLOSED_CALL": {"CLOSED", "CLOSED CALL"},
}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _fail(message: str) -> None:
    raise ValueError(message)


def _parse_date(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{field}: non-empty DD/MM/YYYY value required")
    try:
        parsed = dt.datetime.strptime(value.strip(), "%d/%m/%Y").date()
    except ValueError as exc:
        raise ValueError(f"{field}: invalid DD/MM/YYYY value {value!r}") from exc
    return parsed.isoformat()


def _parse_eur(value: Any, field: str) -> int:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{field}: non-empty EUR amount required")
    text = value.upper().replace("EURO", "EUR")
    if "€" not in text and "EUR" not in text:
        _fail(f"{field}: EUR/€ marker required")
    digits = re.sub(r"\D", "", text)
    if not digits:
        _fail(f"{field}: amount digits missing")
    amount = int(digits)
    if amount <= 0:
        _fail(f"{field}: amount must be positive")
    return amount


def _official_call_url(value: Any, call_number: int) -> str:
    if not isinstance(value, str) or not value:
        _fail("authority_url: non-empty string required")
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in OFFICIAL_HOSTS or parsed.username or parsed.password:
        _fail(f"authority_url: non-official EEA URL {value!r}")
    match = CALL_PATH_RE.match(parsed.path or "")
    if not match or int(match.group("number")) != call_number:
        _fail(f"authority_url: call identity/path mismatch for call {call_number}")
    if parsed.query or parsed.fragment:
        _fail("authority_url: query/fragment not allowed on canonical call detail")
    return value.rstrip("/")


def _semantic_from_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "call_identifier": record.get("call_identifier"),
        "programme": record.get("programme_family"),
        "title": record.get("title"),
        "status_label": record.get("status_label"),
        "authority_url": record.get("authority_url"),
        "publication_date": record.get("publication_date_candidate"),
        "deadline": record.get("deadline_candidate"),
        "questions_deadline": record.get("questions_deadline_candidate"),
        "amount_available": record.get("budget_candidate"),
        "grant_from": record.get("grant_from_candidate"),
        "grant_to": record.get("grant_to_candidate"),
        "eligible_applicants": record.get("eligible_applicants_candidate"),
    }


def _validate_eligibility(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("eligible_applicants_candidate: non-empty official text required")
    collapsed = " ".join(value.split())
    lowered = collapsed.lower()
    if "romania" not in lowered and "românia" not in lowered:
        _fail("eligible_applicants_candidate: Romanian eligibility scope not explicit")
    if "non-profit" not in lowered and "nonprofit" not in lowered and "non profit" not in lowered:
        _fail("eligible_applicants_candidate: non-profit applicant class not explicit")
    return collapsed


def reconcile_live_evidence(
    evidence: dict[str, Any],
    *,
    reconciled_at: str | None = None,
    minimum_calls: int = 1,
) -> dict[str, Any]:
    if not isinstance(evidence, dict) or evidence.get("schema") != INPUT_SCHEMA:
        _fail(f"input schema must be {INPUT_SCHEMA}")
    if evidence.get("source_family") != SOURCE_FAMILY:
        _fail("source_family mismatch")
    if evidence.get("programme_family") != PROGRAMME_FAMILY:
        _fail("programme_family mismatch")
    if evidence.get("authority_class") != AUTHORITY_CLASS:
        _fail("authority_class mismatch")
    if evidence.get("publication_effect") != "NONE":
        _fail("input live evidence must be non-publishing")
    if evidence.get("publish_authorized") or evidence.get("material_fact_use"):
        _fail("input live evidence cannot pre-authorize material facts")
    if evidence.get("errors") or evidence.get("conflicts"):
        _fail("live evidence contains errors/conflicts")

    stats = evidence.get("stats")
    records = evidence.get("records")
    pages = evidence.get("pages")
    if not isinstance(stats, dict) or not isinstance(records, list) or not isinstance(pages, list):
        _fail("live evidence envelope missing stats/records/pages")
    if len(records) < minimum_calls:
        _fail(f"normalized call count {len(records)} below minimum {minimum_calls}")
    expected = len(records)
    if stats.get("discovered_call_urls") != expected or stats.get("fetched_call_pages") != expected or stats.get("normalized_records") != expected:
        _fail(f"incomplete live batch: {stats}")
    if stats.get("errors") or stats.get("conflicts") or stats.get("unknown_evidence"):
        _fail(f"unresolved live evidence stats: {stats}")

    page_by_id: dict[str, dict[str, Any]] = {}
    for page in pages:
        if not isinstance(page, dict):
            _fail("page evidence row must be object")
        call_id = page.get("call_identifier")
        if not isinstance(call_id, str) or call_id in page_by_id:
            _fail(f"duplicate/missing page call_identifier {call_id!r}")
        page_by_id[call_id] = page

    reconciled_records: list[dict[str, Any]] = []
    seen: set[str] = set()
    total_budget = 0

    for record in records:
        if not isinstance(record, dict):
            _fail("call evidence row must be object")
        if record.get("source_family") != SOURCE_FAMILY or record.get("programme_family") != PROGRAMME_FAMILY or record.get("authority_class") != AUTHORITY_CLASS:
            _fail("call evidence authority/programme mismatch")
        call_id = record.get("call_identifier")
        match = CALL_ID_RE.match(str(call_id or ""))
        if not match or call_id in seen:
            _fail(f"invalid/duplicate call identifier {call_id!r}")
        seen.add(call_id)
        call_number = int(match.group(1))
        if int(str(record.get("call_number") or "0")) != call_number:
            _fail(f"{call_id}: call_number mismatch")

        if not record.get("authority_url_verified"):
            _fail(f"{call_id}: exact authority URL readback not verified")
        authority_url = _official_call_url(record.get("authority_url"), call_number)

        state = record.get("observation_state")
        if state not in STATE_LABELS:
            _fail(f"{call_id}: state {state!r} is not material-call evidence")
        label = str(record.get("status_label") or "").strip().upper().replace("_", " ")
        if label not in STATE_LABELS[state]:
            _fail(f"{call_id}: status label {label!r} does not support state {state}")

        page = page_by_id.get(call_id)
        if not page:
            _fail(f"{call_id}: exact-page evidence missing")
        if int(page.get("http_status") or 0) != 200:
            _fail(f"{call_id}: exact page HTTP status is not 200")
        if str(page.get("final_url") or "").rstrip("/") != authority_url:
            _fail(f"{call_id}: final URL drift between page and record")
        if page.get("raw_hash") != record.get("raw_hash"):
            _fail(f"{call_id}: raw hash drift between page and normalized evidence")
        if page.get("observation_state") != state:
            _fail(f"{call_id}: page/record observation-state drift")

        semantic = _semantic_from_record(record)
        if _sha256(_canonical_json(semantic)) != record.get("semantic_fingerprint"):
            _fail(f"{call_id}: semantic fingerprint mismatch")

        publication_date = _parse_date(record.get("publication_date_candidate"), f"{call_id}.publication_date")
        deadline = _parse_date(record.get("deadline_candidate"), f"{call_id}.deadline")
        questions_deadline = _parse_date(record.get("questions_deadline_candidate"), f"{call_id}.questions_deadline")
        if publication_date > deadline:
            _fail(f"{call_id}: publication date after submission deadline")
        if questions_deadline > deadline:
            _fail(f"{call_id}: questions deadline after submission deadline")

        budget = _parse_eur(record.get("budget_candidate"), f"{call_id}.budget")
        grant_from = _parse_eur(record.get("grant_from_candidate"), f"{call_id}.grant_from")
        grant_to = _parse_eur(record.get("grant_to_candidate"), f"{call_id}.grant_to")
        if grant_from > grant_to:
            _fail(f"{call_id}: grant minimum exceeds maximum")
        if grant_to > budget:
            _fail(f"{call_id}: grant maximum exceeds call budget")
        eligible = _validate_eligibility(record.get("eligible_applicants_candidate"))
        total_budget += budget

        reconciled_records.append({
            "call_identifier": call_id,
            "call_number": call_number,
            "programme_family": PROGRAMME_FAMILY,
            "source_family": SOURCE_FAMILY,
            "authority_class": AUTHORITY_CLASS,
            "authority_url": authority_url,
            "source_run_id": record.get("run_id"),
            "fetched_at": record.get("fetched_at"),
            "raw_hash": record.get("raw_hash"),
            "semantic_fingerprint": record.get("semantic_fingerprint"),
            "reconciliation_status": "PASS",
            "evidence_basis": "EXACT_OFFICIAL_CALL_PAGE_READBACK",
            "observation_state": state,
            "material_facts": {
                "title": record.get("title"),
                "status": state,
                "publication_date": publication_date,
                "submission_deadline": deadline,
                "questions_deadline": questions_deadline,
                "budget_eur": budget,
                "grant_min_eur": grant_from,
                "grant_max_eur": grant_to,
                "eligible_applicants": eligible,
            },
            "material_fact_use": True,
            "publish_authorized": False,
            "requires_reconcile": False,
            "ready_for_staging": True,
            "missing_proofs": [
                "CANONICAL_STAGING_ADMISSION",
                "PUBLIC_PROJECTION_QUALITY_GATE",
            ],
        })

    if set(page_by_id) != seen:
        _fail("page evidence contains identities not represented in normalized records")

    reconciled_at = reconciled_at or _utc_now()
    source_hash = _sha256(_canonical_json(evidence))
    batch_semantic_hash = _sha256(_canonical_json([
        [row["call_identifier"], row["semantic_fingerprint"]] for row in reconciled_records
    ]))
    return {
        "schema": SCHEMA,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "reconciled_at": reconciled_at,
        "source_run_id": evidence.get("run_id"),
        "source_fetched_at": evidence.get("fetched_at"),
        "source_evidence_hash": source_hash,
        "batch_semantic_hash": batch_semantic_hash,
        "records": reconciled_records,
        "stats": {
            "reconciled_calls": len(reconciled_records),
            "material_fact_ready_for_staging": len(reconciled_records),
            "total_call_budget_eur": total_budget,
            "errors": 0,
            "conflicts": 0,
        },
        "material_fact_use": True,
        "ready_for_staging": True,
        "publish_authorized": False,
        "publication_effect": "NONE",
        "rollback": "Discard this receipt; live evidence remains immutable and no canonical/public state is mutated.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--minimum-calls", type=int, default=1)
    args = parser.parse_args()
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    receipt = reconcile_live_evidence(evidence, minimum_calls=args.minimum_calls)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "reconciled_calls": receipt["stats"]["reconciled_calls"],
        "total_call_budget_eur": receipt["stats"]["total_call_budget_eur"],
        "ready_for_staging": receipt["ready_for_staging"],
        "publish_authorized": receipt["publish_authorized"],
        "publication_effect": receipt["publication_effect"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
