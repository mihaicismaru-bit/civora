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
from zoneinfo import ZoneInfo

SCHEMA = "PARTENER_EU_EEA_CSF_RECONCILIATION_RECEIPT_V1"
INPUT_SCHEMA = "PARTENER_EU_EEA_CSF_LIVE_EVIDENCE_V1"
SOURCE_FAMILY = "EEA_NORWAY"
PROGRAMME_FAMILY = "EEA Civil Society Fund Romania 2021-2028"
AUTHORITY_CLASS = "EEA_FMO_CIVIL_SOCIETY_FUND_ROMANIA"
OFFICIAL_HOSTS = {"eeagrants.org", "www.eeagrants.org"}
FETCH_PARSER_VERSION = "EEA_CSF_ROMANIA_LIVE_FETCH_V3"
# Date-only deadlines of Romanian calls are interpreted in Romania's civil time,
# never in UTC (midnight UTC can already be the following day locally).
ROMANIA_TIMEZONE = ZoneInfo("Europe/Bucharest")
ADAPTER_PARSER_VERSION = "EEA_CSF_ROMANIA_CALLS_V1"
MAX_RAW_BYTES = 4_000_000
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
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
    # The official call pages currently use exact integer EUR amounts such as
    # €3,718,664. Stripping all non-digits silently changes decimal values,
    # ungrouped separators and annotated estimates into invented budgets.
    # Accept only an entire currency-marked integer with valid comma thousands
    # grouping. Unsupported formats require source review, not normalization.
    text = value.strip().upper()
    digits_pattern = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)"
    matched = re.fullmatch(
        rf"(?:€\s*|EUR\s*)({digits_pattern})|({digits_pattern})\s*(?:€|EUR)",
        text,
    )
    if matched is None:
        _fail(f"{field}: exact integer EUR/€ amount with valid grouping required")
    amount = int((matched.group(1) or matched.group(2)).replace(",", ""))
    if amount <= 0:
        _fail(f"{field}: amount must be positive")
    return amount


def _valid_raw_hash(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        _fail(f"{field}: lowercase 64-character SHA-256 required")
    return value


def _valid_raw_page(page: dict[str, Any], field: str) -> None:
    if page.get("http_status") != 200:
        _fail(f"{field}: HTTP 200 required")
    content_type = page.get("content_type")
    # Substring checks would admit application/json; note=text/html or
    # text/html-spoofed as if they were authoritative HTML receipts.
    if (not isinstance(content_type, str) or
            content_type.split(";", 1)[0].strip().lower()
            not in {"text/html", "application/xhtml+xml"}):
        _fail(f"{field}: official HTML content type required")
    size = page.get("bytes")
    if (isinstance(size, bool) or not isinstance(size, int)
            or not 0 < size <= MAX_RAW_BYTES):
        _fail(f"{field}: positive bounded raw byte count required")
    _valid_raw_hash(page.get("raw_hash"), f"{field}.raw_hash")


def _valid_official_index(value: Any) -> None:
    if not isinstance(value, dict):
        _fail("source_index: official acquisition evidence required")
    url = value.get("url")
    if not isinstance(url, str):
        _fail("source_index: official index URL required")
    parsed = urlparse(url)
    if (parsed.scheme != "https" or (parsed.hostname or "").lower() not in OFFICIAL_HOSTS
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443) or parsed.params
            or parsed.query or parsed.fragment
            or not re.fullmatch(r"/(?:en|ro)/eea-civil-society-fund-romania/calls/?",
                                parsed.path, re.IGNORECASE)):
        _fail("source_index: untrusted or non-canonical official index URL")
    _valid_raw_page(value, "source_index")
    mode = value.get("discovery_mode")
    direct_count = value.get("direct_exact_call_links")
    if mode not in {
        "INDEX_EXACT_ANCHORS",
        "PINNED_OFFICIAL_DETAIL_DISCOVERY_REQUIRES_FRESH_READBACK",
    }:
        _fail("source_index: unsupported acquisition discovery mode")
    if (isinstance(direct_count, bool) or not isinstance(direct_count, int)
            or direct_count < 0):
        _fail("source_index: valid direct exact-call link count required")
    if mode == "INDEX_EXACT_ANCHORS" and direct_count == 0:
        _fail("source_index: direct-link mode has no direct links")
    if mode.startswith("PINNED_") and direct_count != 0:
        _fail("source_index: fallback mode contradicts direct-link evidence")


def _official_call_url(value: Any, call_number: int) -> str:
    if not isinstance(value, str) or not value:
        _fail("authority_url: non-empty string required")
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or host not in OFFICIAL_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
    ):
        _fail(f"authority_url: non-official EEA URL {value!r}")
    match = CALL_PATH_RE.match(parsed.path or "")
    if not match or int(match.group("number")) != call_number:
        _fail(f"authority_url: call identity/path mismatch for call {call_number}")
    if parsed.params or parsed.query or parsed.fragment:
        _fail("authority_url: path parameters, query or fragment not allowed on canonical call detail")
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
    run_id = evidence.get("run_id")
    if (not isinstance(run_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", run_id) is None):
        _fail("run_id: non-empty bounded acquisition identity required")
    if evidence.get("parser_version") != FETCH_PARSER_VERSION:
        _fail("parser_version: unsupported acquisition parser")
    if evidence.get("adapter_version") != ADAPTER_PARSER_VERSION:
        _fail("adapter_version: unsupported normalized record parser")
    _valid_official_index(evidence.get("source_index"))

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

    # Cross-check the summary against the immutable acquisition envelope.
    # Otherwise a forged/mixed replay could carry OPEN rows while advertising
    # CLOSED counters, or relabel the pinned fallback as direct-link evidence.
    if (not isinstance(evidence.get("errors"), list)
            or not isinstance(evidence.get("conflicts"), list)
            or len(evidence["errors"]) != 0 or len(evidence["conflicts"]) != 0):
        _fail("acquisition error/conflict ledgers must be explicitly empty")
    expected_counts = {
        "open_call_evidence": sum(
            row.get("observation_state") == "OPEN_CALL" for row in records if isinstance(row, dict)
        ),
        "forthcoming_call_evidence": sum(
            row.get("observation_state") == "FORTHCOMING_CALL" for row in records if isinstance(row, dict)
        ),
        "closed_call_evidence": sum(
            row.get("observation_state") == "CLOSED_CALL" for row in records if isinstance(row, dict)
        ),
        "unknown_evidence": sum(
            row.get("observation_state") == "UNKNOWN" for row in records if isinstance(row, dict)
        ),
        "errors": 0,
        "conflicts": 0,
        "index_direct_exact_call_links": evidence["source_index"]["direct_exact_call_links"],
    }
    for key, required in expected_counts.items():
        observed = stats.get(key)
        if isinstance(observed, bool) or not isinstance(observed, int) or observed != required:
            _fail(f"acquisition stats mismatch for {key}: {observed!r} != {required}")
    fallback = evidence["source_index"]["discovery_mode"].startswith("PINNED_")
    if stats.get("official_pinned_fallback_used") is not fallback:
        _fail("acquisition discovery mode/fallback flag drift")
    if not fallback and stats["index_direct_exact_call_links"] != expected:
        _fail("direct exact-call discovery count does not match batch")

    # Date-only official deadlines cannot establish whether an OPEN status is
    # still actionable on the final day: a closing hour may have passed. Until
    # an independently verified official cutoff time is in the evidence schema,
    # fail closed on the deadline day itself (Romanian civil calendar), as well
    # as on later days. Never invent a default closing hour.
    def evidence_time(value: Any, field: str) -> dt.datetime:
        try:
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field}: invalid timestamp") from exc
        if parsed.tzinfo is None:
            _fail(f"{field}: timezone-aware timestamp required")
        return parsed.astimezone(dt.timezone.utc)

    source_time = evidence_time(evidence.get("fetched_at"), "fetched_at")
    reconciled_at = reconciled_at or _utc_now()
    reconciliation_time = evidence_time(reconciled_at, "reconciled_at")
    if reconciliation_time < source_time:
        _fail("reconciliation cannot predate official evidence acquisition")

    page_by_id: dict[str, dict[str, Any]] = {}
    for page in pages:
        if not isinstance(page, dict):
            _fail("page evidence row must be object")
        call_id = page.get("call_identifier")
        if not isinstance(call_id, str) or call_id in page_by_id:
            _fail(f"duplicate/missing page call_identifier {call_id!r}")
        _valid_raw_page(page, f"{call_id}.page")
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

        if (record.get("fetched_at") != evidence.get("fetched_at")
                or record.get("run_id") != evidence.get("run_id")):
            _fail(f"{call_id}: source capture timestamp/run mismatch")
        if record.get("parser_version") != ADAPTER_PARSER_VERSION:
            _fail(f"{call_id}: adapter parser version mismatch")
        # The acquisition normalizer correctly marks CLOSED_CALL as not
        # requiring further call-state reconciliation; it remains non-publishing.
        expected_review = record.get("observation_state") in {
            "OPEN_CALL", "FORTHCOMING_CALL", "UNKNOWN"
        }
        if (record.get("material_fact_use") is not False
                or record.get("publish_authorized") is not False
                or record.get("requires_reconcile") is not expected_review):
            _fail(f"{call_id}: acquisition record pre-authorized material facts")
        _valid_raw_hash(record.get("raw_hash"), f"{call_id}.raw_hash")
        if not record.get("authority_url_verified"):
            _fail(f"{call_id}: exact authority URL readback not verified")
        authority_url = _official_call_url(record.get("authority_url"), call_number)

        state = record.get("observation_state")
        if state not in STATE_LABELS:
            _fail(f"{call_id}: state {state!r} is not material-call evidence")
        label = str(record.get("status_label") or "").strip().upper().replace("_", " ")
        if label not in STATE_LABELS[state]:
            _fail(f"{call_id}: status label {label!r} does not support state {state}")
        # An OPEN/FORTHCOMING observation is a perishable snapshot, even when
        # its deadline has not passed. Reject a delayed replay rather than
        # staging stale call availability as current. Historical CLOSED
        # evidence remains admissible for audit/replay without publication.
        if state in {"OPEN_CALL", "FORTHCOMING_CALL"} and (
            reconciliation_time - source_time > dt.timedelta(hours=24)
        ):
            _fail(f"{call_id}: active call evidence older than 24 hours; fresh official readback required")

        page = page_by_id.get(call_id)
        if not page:
            _fail(f"{call_id}: exact-page evidence missing")
        if int(page.get("http_status") or 0) != 200:
            _fail(f"{call_id}: exact page HTTP status is not 200")
        if str(page.get("final_url") or "").rstrip("/") != authority_url:
            _fail(f"{call_id}: final URL drift between page and record")
        _official_call_url(page.get("requested_url"), call_number)
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
        # A date-only field is insufficient to authorize last-day OPEN:
        # a real 16:00 (or earlier) cutoff cannot be inferred from DD/MM/YYYY.
        deadline_date = dt.date.fromisoformat(deadline)
        if state in {"OPEN_CALL", "FORTHCOMING_CALL"} and (
            source_time.astimezone(ROMANIA_TIMEZONE).date() >= deadline_date
            or reconciliation_time.astimezone(ROMANIA_TIMEZONE).date() >= deadline_date
        ):
            _fail(f"{call_id}: active status on/after date-only deadline requires verified cutoff time")

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
