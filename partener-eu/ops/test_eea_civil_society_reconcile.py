#!/usr/bin/env python3
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ingest" / "eea_civil_society_reconcile.py"
spec = importlib.util.spec_from_file_location("eea_csf_reconcile", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)

FETCHED = "2026-08-27T17:58:46+00:00"
RUN = "TEST-EEA-CSF-RECONCILE"
CALL1 = "https://eeagrants.org/en/eea-civil-society-fund-romania/calls/call-1-strengthening-democracy-and-rule-law-through-civil-society-initiatives"
CALL2 = "https://eeagrants.org/en/eea-civil-society-fund-romania/calls/call-2-empowering-civic-participation-underserved-communities"


def fail(message):
    raise SystemExit(f"FAIL: {message}")


def fingerprint(record):
    semantic = {
        "call_identifier": record["call_identifier"],
        "programme": record["programme_family"],
        "title": record["title"],
        "status_label": record["status_label"],
        "authority_url": record["authority_url"],
        "publication_date": record["publication_date_candidate"],
        "deadline": record["deadline_candidate"],
        "questions_deadline": record["questions_deadline_candidate"],
        "amount_available": record["budget_candidate"],
        "grant_from": record["grant_from_candidate"],
        "grant_to": record["grant_to_candidate"],
        "eligible_applicants": record["eligible_applicants_candidate"],
    }
    raw = json.dumps(semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def make_record(number, url, title, budget, grant_from):
    record = {
        "source_family": "EEA_NORWAY",
        "programme_family": "EEA Civil Society Fund Romania 2021-2028",
        "authority_class": "EEA_FMO_CIVIL_SOCIETY_FUND_ROMANIA",
        "call_identifier": f"EEA-CSF-RO-CALL-{number:02d}",
        "call_number": str(number),
        "title": title,
        "status_label": "Open",
        "observation_state": "OPEN_CALL",
        "authority_url": url,
        "authority_url_verified": True,
        "publication_date_candidate": "08/07/2026",
        "deadline_candidate": "08/10/2026",
        "questions_deadline_candidate": "29/09/2026",
        "budget_candidate": budget,
        "grant_from_candidate": grant_from,
        "grant_to_candidate": "€350,000",
        "eligible_applicants_candidate": "Eligible Applicants are non-governmental and non-profit organizations, legally established in Romania.",
        "material_fact_use": False,
        "publish_authorized": False,
        "requires_reconcile": True,
        "fetched_at": FETCHED,
        "raw_hash": hashlib.sha256(url.encode()).hexdigest(),
        "parser_version": "EEA_CSF_ROMANIA_CALLS_V1",
        "run_id": RUN,
    }
    record["semantic_fingerprint"] = fingerprint(record)
    return record


def make_evidence():
    records = [
        make_record(1, CALL1, "Call #1 Strengthening Democracy and Rule of Law through Civil Society Initiatives", "€3,718,664", "€200,001"),
        make_record(2, CALL2, "Call #2 Empowering Civic Participation in Underserved Communities", "€4,500,000", "€15,000"),
    ]
    pages = [{
        "requested_url": row["authority_url"],
        "final_url": row["authority_url"],
        "http_status": 200,
        "content_type": "text/html; charset=utf-8",
        "raw_hash": row["raw_hash"],
        "bytes": 60000,
        "call_identifier": row["call_identifier"],
        "observation_state": row["observation_state"],
    } for row in records]
    return {
        "schema": "PARTENER_EU_EEA_CSF_LIVE_EVIDENCE_V1",
        "source_family": "EEA_NORWAY",
        "programme_family": "EEA Civil Society Fund Romania 2021-2028",
        "authority_class": "EEA_FMO_CIVIL_SOCIETY_FUND_ROMANIA",
        "fetched_at": FETCHED,
        "run_id": RUN,
        "parser_version": "EEA_CSF_ROMANIA_LIVE_FETCH_V2",
        "adapter_version": "EEA_CSF_ROMANIA_CALLS_V1",
        "source_index": {
            "url": "https://eeagrants.org/en/eea-civil-society-fund-romania/calls",
            "http_status": 200,
            "content_type": "text/html; charset=utf-8",
            "raw_hash": hashlib.sha256(b"official-index-fixture").hexdigest(),
            "bytes": 1000,
            "discovery_mode": "DIRECT_LINKS",
            "direct_exact_call_links": 2,
        },
        "pages": pages,
        "records": records,
        "conflicts": [],
        "errors": [],
        "stats": {
            "discovered_call_urls": 2,
            "fetched_call_pages": 2,
            "normalized_records": 2,
            "open_call_evidence": 2,
            "forthcoming_call_evidence": 0,
            "closed_call_evidence": 0,
            "unknown_evidence": 0,
            "errors": 0,
            "conflicts": 0,
        },
        "material_fact_use": False,
        "publish_authorized": False,
        "publication_effect": "NONE",
    }


def expect_fail(evidence, label, *, reconciled_at="2026-08-27T18:30:00+00:00"):
    # Freeze the clock so an unrelated expired OPEN label does not mask
    # the actual adversarial invariant under test.
    try:
        module.reconcile_live_evidence(
            evidence, minimum_calls=2, reconciled_at=reconciled_at
        )
    except ValueError:
        return
    fail(f"{label}: expected fail-closed rejection")


def main():
    evidence = make_evidence()
    receipt = module.reconcile_live_evidence(
        evidence,
        reconciled_at="2026-08-27T18:30:00+00:00",
        minimum_calls=2,
    )
    if receipt["stats"]["reconciled_calls"] != 2:
        fail("two-call batch did not reconcile")
    if receipt["stats"]["total_call_budget_eur"] != 8218664:
        fail(f"budget normalization drift: {receipt['stats']}")
    if not receipt["material_fact_use"] or not receipt["ready_for_staging"]:
        fail("reconciliation must authorize material facts for staging")
    if receipt["publish_authorized"] or receipt["publication_effect"] != "NONE":
        fail("reconciliation must remain non-publishing")
    facts = receipt["records"][0]["material_facts"]
    if facts["submission_deadline"] != "2026-10-08" or facts["budget_eur"] != 3718664:
        fail(f"material fact normalization drift: {facts}")
    if receipt["records"][0]["missing_proofs"] != [
        "CANONICAL_STAGING_ADMISSION",
        "PUBLIC_PROJECTION_QUALITY_GATE",
    ]:
        fail("staging/public gates must remain explicit")

    # The current official seven-call feed is CLOSED. Preserve its exact
    # normalizer contract while still admitting only a non-publishing staging
    # receipt, even when the reconciliation happens after the call deadline.
    closed = copy.deepcopy(evidence)
    for row, page in zip(closed["records"], closed["pages"]):
        row["status_label"] = "Closed"
        row["observation_state"] = "CLOSED_CALL"
        row["requires_reconcile"] = False
        row["semantic_fingerprint"] = fingerprint(row)
        page["observation_state"] = "CLOSED_CALL"
    closed["stats"]["open_call_evidence"] = 0
    closed["stats"]["closed_call_evidence"] = 2
    closed_receipt = module.reconcile_live_evidence(
        closed, reconciled_at="2026-11-06T19:00:00+00:00", minimum_calls=2
    )
    if (closed_receipt["stats"]["reconciled_calls"] != 2
            or closed_receipt["publish_authorized"]
            or any(row["observation_state"] != "CLOSED_CALL"
                   for row in closed_receipt["records"])):
        fail("closed official calls must remain non-publishing staging evidence")

    # Financial amounts must preserve the exact official integer value.
    # An intact semantic hash alone must not legalize ambiguous numerals.
    for raw, expected in (
        ("€3,718,664", 3718664),
        ("EUR 200,001", 200001),
        ("15,000 EUR", 15000),
        ("€ 350000", 350000),
    ):
        if module._parse_eur(raw, "test_budget") != expected:
            fail(f"strict EUR integer normalization drift: {raw}")

    for raw in (
        "3,718,664", "€3.718.664", "€3,71,8664",
        "€3,718,664.00", "€1.50", "€3,718,664 approx",
        "EUR 3,718,664 €", "€-200", "€0", "€3 million",
    ):
        try:
            module._parse_eur(raw, "test_budget")
        except ValueError:
            pass
        else:
            fail(f"ambiguous EUR source value accepted: {raw}")

    ambiguous_budget = copy.deepcopy(evidence)
    ambiguous_budget["records"][0]["budget_candidate"] = "€3,718,664.50"
    ambiguous_budget["records"][0]["semantic_fingerprint"] = fingerprint(ambiguous_budget["records"][0])
    expect_fail(ambiguous_budget, "source budget decimal not authorized after re-fingerprint")

    # Missing or forged acquisition provenance must never authorize material
    # field staging even when a valid semantic fingerprint is retained.
    for field in ("run_id", "parser_version", "adapter_version", "source_index"):
        bad = copy.deepcopy(evidence)
        bad.pop(field)
        expect_fail(bad, f"missing acquisition provenance {field}")
    for field, value in (
        ("run_id", "   "),
        ("parser_version", "UNREGISTERED_FETCH"),
        ("adapter_version", "UNREGISTERED_NORMALIZER"),
    ):
        bad = copy.deepcopy(evidence)
        bad[field] = value
        expect_fail(bad, f"invalid {field}: {value!r}")
    for field, value in (
        ("raw_hash", None), ("raw_hash", "0" * 63),
        ("bytes", 0), ("bytes", True),
        ("content_type", "application/json"), ("http_status", 403),
    ):
        bad = copy.deepcopy(evidence)
        bad["pages"][0][field] = value
        if field == "raw_hash":
            bad["records"][0][field] = value
        expect_fail(bad, f"invalid raw page {field}")
    bad = copy.deepcopy(evidence)
    bad["source_index"]["url"] = "https://example.com/en/eea-civil-society-fund-romania/calls"
    expect_fail(bad, "non-official index")
    bad = copy.deepcopy(evidence)
    bad["records"][0]["parser_version"] = "UNREGISTERED"
    expect_fail(bad, "record parser drift")
    bad = copy.deepcopy(evidence)
    bad["records"][0]["material_fact_use"] = True
    expect_fail(bad, "record acquisition cannot pre-authorize material facts")
    bad = copy.deepcopy(evidence)
    bad["pages"][0]["requested_url"] = "https://evil.example/en/eea-civil-society-fund-romania/calls/call-1-forged"
    expect_fail(bad, "non-official page request")
    bad = copy.deepcopy(evidence)
    bad["records"][0]["semantic_fingerprint"] = "0" * 64
    expect_fail(bad, "semantic fingerprint drift")

    bad = copy.deepcopy(evidence)
    bad["records"][0]["authority_url_verified"] = False
    expect_fail(bad, "unverified exact authority")

    bad = copy.deepcopy(evidence)
    bad["records"][0]["observation_state"] = "PROGRAMMING_PIPELINE"
    bad["pages"][0]["observation_state"] = "PROGRAMMING_PIPELINE"
    expect_fail(bad, "programming pipeline cannot become material call fact")

    bad = copy.deepcopy(evidence)
    bad["records"][1]["deadline_candidate"] = "01/07/2026"
    bad["records"][1]["semantic_fingerprint"] = fingerprint(bad["records"][1])
    expect_fail(bad, "deadline before publication")

    # Two official EEA CSF URLs have historically shown conflicting OPEN and
    # CLOSED labels for the same 8 October deadline. A stale OPEN after that
    # date cannot become CURRENT material-call evidence or enter staging.
    historical_open = copy.deepcopy(evidence)
    try:
        module.reconcile_live_evidence(
            historical_open, reconciled_at="2026-11-06T19:00:00+00:00",
            minimum_calls=2,
        )
    except ValueError as exc:
        if "stale open/forthcoming status past official submission date" not in str(exc):
            fail(f"historical OPEN wrong failure: {exc}")
    else:
        fail("historical OPEN accepted after official deadline")

    stale_capture = copy.deepcopy(evidence)
    stale_capture["fetched_at"] = "2026-11-06T17:00:00+00:00"
    for row in stale_capture["records"]:
        row["fetched_at"] = stale_capture["fetched_at"]
    expect_fail(
        stale_capture, "stale official OPEN captured after deadline",
        reconciled_at="2026-11-06T19:00:00+00:00",
    )

    # EEA Romania date-only deadlines use Romania's civil calendar, not UTC.
    # On 8 October 2026, 21:30 UTC is already 9 October 00:30 EEST:
    # a stale OPEN label cannot be staged during this UTC/local midnight gap.
    local_next_day = copy.deepcopy(evidence)
    local_next_day["fetched_at"] = "2026-10-08T21:30:00+00:00"
    for row in local_next_day["records"]:
        row["fetched_at"] = local_next_day["fetched_at"]
    expect_fail(
        local_next_day,
        "Romania-local deadline expired although UTC date is still 8 October",
        reconciled_at="2026-10-08T21:31:00+00:00",
    )

    # Positive boundary: 12:30 UTC is 8 October 15:30 in Romania,
    # before the official 16:00 local submission cut-off. This unit test
    # isolates the date-only guard; exact hours need independently proven
    # official evidence before a call can enter public projection.
    local_deadline_day = copy.deepcopy(evidence)
    local_deadline_day["fetched_at"] = "2026-10-08T12:30:00+00:00"
    for row in local_deadline_day["records"]:
        row["fetched_at"] = local_deadline_day["fetched_at"]
    local_receipt = module.reconcile_live_evidence(
        local_deadline_day,
        reconciled_at="2026-10-08T12:31:00+00:00",
        minimum_calls=2,
    )
    if (local_receipt["stats"]["reconciled_calls"] != 2
            or local_receipt["publish_authorized"]
            or not local_receipt["ready_for_staging"]):
        fail("valid Romanian deadline-day readback was incorrectly denied")

    mismatched_provenance = copy.deepcopy(evidence)
    mismatched_provenance["records"][0]["fetched_at"] = "2026-08-26T17:00:00+00:00"
    expect_fail(mismatched_provenance, "call-specific acquisition time differs from envelope")
    future_reconciliation = copy.deepcopy(evidence)
    try:
        module.reconcile_live_evidence(
            future_reconciliation, reconciled_at="2026-08-26T18:30:00+00:00",
            minimum_calls=2,
        )
    except ValueError as exc:
        if "cannot predate" not in str(exc):
            fail(f"retrodated reconciliation wrong failure: {exc}")
    else:
        fail("retrodated reconciliation accepted")

    for unsafe_url in (
        CALL1.replace("https://eeagrants.org/", "https://user@eeagrants.org/"),
        CALL1.replace("https://eeagrants.org/", "https://eeagrants.org:8443/"),
    ):
        try:
            module._official_call_url(unsafe_url, 1)
        except ValueError:
            pass
        else:
            fail(f"unsafe reconciliation authority accepted: {unsafe_url}")

    bad = copy.deepcopy(evidence)
    bad["errors"] = [{"url": CALL2, "error": "synthetic"}]
    bad["stats"]["errors"] = 1
    expect_fail(bad, "partial live acquisition")

    print("PASS EEA CSF reconciliation: exact authority, semantic integrity, material-field validation, staging-only authorization and fail-closed batch semantics")


if __name__ == "__main__":
    main()
