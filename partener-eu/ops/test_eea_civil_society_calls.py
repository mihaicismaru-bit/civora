#!/usr/bin/env python3
import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ingest" / "eea_civil_society_calls.py"
DATA_PLANE = ROOT / "partener-eu" / "ingest" / "data_plane_contract.json"
spec = importlib.util.spec_from_file_location("eea_csf", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)

CALL1 = "https://eeagrants.org/en/eea-civil-society-fund-romania/calls/strengthening-democracy-and-rule-law-through-civil-society-initiatives"
CALL4 = "https://eeagrants.org/en/eea-civil-society-fund-romania/calls/promoting-diversity-equality-and-combating-gender-based-violence"
CALL6_RO = "https://eeagrants.org/ro/eea-civil-society-fund-romania/calls/call-6-protecting-human-rights-through-climate-and-environmental-actions"
ROOT_CALLS = "https://eeagrants.org/en/eea-civil-society-fund-romania/calls"
FETCHED = "2026-08-27T15:00:00+00:00"


def fail(msg):
    raise SystemExit(f"FAIL: {msg}")


def base_record():
    return {
        "callNumber": "1",
        "title": "Strengthening Democracy and Rule of Law through Civil Society Initiatives",
        "status": "Open",
        "authorityUrl": CALL1,
        "publicationDate": "08/07/2026",
        "submissionDeadline": "08/10/2026",
        "questionsDeadline": "29/09/2026",
        "amountAvailable": "EUR 3,718,664",
        "grantAmountFrom": "EUR 200,001",
        "grantAmountTo": "EUR 350,000",
        "eligibleApplicants": "Non-governmental and non-profit organisations legally established in Romania",
    }


def main():
    plane = json.loads(DATA_PLANE.read_text(encoding="utf-8"))
    domains = set((plane.get("programmeDomains") or {}).get(module.PROGRAMME_FAMILY) or [])
    required_domains = {"EEA_NORWAY_GRANTS", "CIVIL_SOCIETY"}
    if not required_domains.issubset(domains):
        fail(f"EEA CSF programme lacks data-plane domains: {sorted(required_domains - domains)}")

    open_row = module.normalize_record(
        base_record(),
        fetched_at=FETCHED,
        run_id="TEST-OPEN",
        raw_hash="raw-open",
        verified_authority_urls=[CALL1],
    )
    if open_row["observation_state"] != "OPEN_CALL":
        fail("exact verified official OPEN call must normalize as OPEN_CALL")
    if open_row["publish_authorized"] or open_row["material_fact_use"]:
        fail("normalizer must not authorize publication or material facts")
    if not open_row["requires_reconcile"]:
        fail("OPEN evidence candidate must still require semantic reconciliation")
    if open_row["call_identifier"] != "EEA-CSF-RO-CALL-01":
        fail("stable call identifier drift")
    if open_row["deadline_candidate"] != "08/10/2026":
        fail("deadline candidate not preserved")
    if open_row["authority_class"] != "EEA_FMO_CIVIL_SOCIETY_FUND_ROMANIA":
        fail("authority class drift")

    ro_record = base_record()
    ro_record.update({"callNumber": "6", "authorityUrl": CALL6_RO})
    ro_row = module.normalize_record(
        ro_record,
        fetched_at=FETCHED,
        run_id="TEST-RO",
        raw_hash="raw-ro",
        verified_authority_urls=[CALL6_RO],
    )
    if ro_row["observation_state"] != "OPEN_CALL" or ro_row["call_identifier"] != "EEA-CSF-RO-CALL-06":
        fail("official Romanian-language call detail path must retain the same authority gate")

    unverified = module.normalize_record(
        base_record(),
        fetched_at=FETCHED,
        run_id="TEST-UNVERIFIED",
        raw_hash="raw-unverified",
        verified_authority_urls=[],
    )
    if unverified["observation_state"] != "UNKNOWN":
        fail("OPEN label without exact official readback must fail closed")

    root_only = base_record()
    root_only["authorityUrl"] = ROOT_CALLS
    root_row = module.normalize_record(
        root_only,
        fetched_at=FETCHED,
        run_id="TEST-ROOT",
        raw_hash="raw-root",
        verified_authority_urls=[ROOT_CALLS],
    )
    if root_row["authority_url"] is not None or root_row["observation_state"] != "UNKNOWN":
        fail("generic calls registry must not masquerade as exact call authority")

    third_party = base_record()
    third_party["authorityUrl"] = "https://example.org/calls/1"
    third_row = module.normalize_record(
        third_party,
        fetched_at=FETCHED,
        run_id="TEST-THIRD",
        raw_hash="raw-third",
        verified_authority_urls=[third_party["authorityUrl"]],
    )
    if third_row["authority_url"] is not None or third_row["observation_state"] != "UNKNOWN":
        fail("non-FMO host must never authorize EEA CSF call state")

    pipeline = base_record()
    pipeline["observationState"] = "PROGRAMME_PREPARATION"
    pipeline_row = module.normalize_record(
        pipeline,
        fetched_at=FETCHED,
        run_id="TEST-PIPELINE",
        raw_hash="raw-pipeline",
        verified_authority_urls=[CALL1],
    )
    if pipeline_row["observation_state"] != "PROGRAMMING_PIPELINE":
        fail("programme preparation must remain pipeline even when text says Open")

    call4 = copy.deepcopy(base_record())
    call4.update({
        "callNumber": "Call #4",
        "title": "Promoting Diversity, Equality and Combating Gender-Based Violence",
        "authorityUrl": CALL4,
        "amountAvailable": "EUR 4,478,018",
        "grantAmountFrom": "EUR 100,000",
    })
    payload = {"calls": [base_record(), copy.deepcopy(base_record()), call4]}
    batch = module.normalize_payload(
        payload,
        fetched_at=FETCHED,
        run_id="TEST-BATCH",
        verified_authority_urls=[CALL1, CALL4],
    )
    if len(batch["records"]) != 2 or batch["stats"]["duplicate_records_collapsed"] != 1:
        fail("identical duplicate calls must collapse deterministically")
    if batch["publication_effect"] != "NONE":
        fail("adapter batch must remain non-publishing")

    conflict = copy.deepcopy(base_record())
    conflict["amountAvailable"] = "EUR 99"
    conflict_batch = module.normalize_payload(
        {"calls": [base_record(), conflict]},
        fetched_at=FETCHED,
        run_id="TEST-CONFLICT",
        verified_authority_urls=[CALL1],
    )
    if conflict_batch["stats"]["conflicts"] != 1:
        fail("same call/programme/authority with semantic drift must enter reconcile")
    if not conflict_batch["records"][0]["requires_reconcile"]:
        fail("conflicting retained record must require reconcile")

    print("PASS EEA Civil Society Fund Romania call adapter: data-plane mapping, exact EN/RO call gate, pipeline guard, authority guard, dedup and reconcile")


if __name__ == "__main__":
    main()
