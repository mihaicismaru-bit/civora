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


def expect_fail(evidence, label):
    try:
        module.reconcile_live_evidence(evidence, minimum_calls=2)
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

    bad = copy.deepcopy(evidence)
    bad["errors"] = [{"url": CALL2, "error": "synthetic"}]
    bad["stats"]["errors"] = 1
    expect_fail(bad, "partial live acquisition")

    print("PASS EEA CSF reconciliation: exact authority, semantic integrity, material-field validation, staging-only authorization and fail-closed batch semantics")


if __name__ == "__main__":
    main()
