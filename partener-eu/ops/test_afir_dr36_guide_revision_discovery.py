#!/usr/bin/env python3
"""DR36 LEADER approved guide revision is not a GAL-specific OPEN call."""
import copy
import json
from pathlib import Path
from urllib.parse import urlparse

REGISTRY = Path(__file__).resolve().parents[1] / "ingest" / "source_registry.json"
IDENTITY = "SRC-RO-AFIR-DR36-LEADER-GUIDE-ED2-REV0-OMADR309-20261112"
PAGE = "https://www.afir.ro/domenii-de-interventie/detalii-si-anexe-dr-36"
ORDER = "https://www.afir.ro/media/bzagtrsj/omadr-nr309-12112026.pdf"
GUIDE = "https://www.afir.ro/api/file?filename=Ghid+Implementare+DR-36+Editia+II%2C+Revizia+0&filetype=pdf&url=%2Fmedia%2Fgbxhdr21%2Fghid-implementare-dr_36_editia-ii-revizia-0.pdf"
NO_RECEIPT_OR_CALL_FACTS = {
    "status", "call_status", "submission_status", "current_status", "deadline",
    "application_deadline", "submission_deadline", "budget", "budget_eur",
    "eligibility", "call_identifier", "exact_call_identifier", "submission_endpoint",
    "application_endpoint", "current_gal_call", "actual_open", "last_verified_open",
    "final_url", "fetched_at", "raw_sha256", "semantic_sha256", "parser_version",
    "run_id", "handoff_sha256", "confirmed_effective_eligibility_changes",
}
EXPECTED = {
    "tier": "T1",
    "class": "official_approved_implementation_guide_revision_discovery",
    "url": PAGE,
    "authority_class": "T1_OFFICIAL_AGENCY_MADR_AFIR",
    "authority_scope": "DR36_LEADER_APPROVED_GUIDE_ED2_REV0_NOT_EXACT_GAL_CALL",
    "observation_state": "APPROVED_IMPLEMENTATION_GUIDE_REVISION_DISCOVERED_RAW_PENDING",
    "approval_order_identifier_discovery": "OMADR 309/12.11.2026",
    "approval_order_date_discovery": "2026-11-12",
    "guide_publication_datetime_discovery": "2026-11-13 11:45 Europe/Bucharest",
    "guide_edition_discovery": "II",
    "guide_revision_discovery": "0",
    "guide_original_url_discovery": GUIDE,
    "approval_order_original_url_discovery": ORDER,
    "adapter_required": "AFIR_DR36_LEADER_ED2_REV0_OMADR309_PAIRED_ORIGINALS_SURFACEMC_RECONCILE_V1",
}

def check(rows):
    matches = [r for r in rows if r.get("id") == IDENTITY]
    assert len(matches) == 1, "DR36 guidance discovery must be unique"
    row = matches[0]
    for key, value in EXPECTED.items():
        assert row.get(key) == value, "DR36 identity/evidence drift: " + key
    for url in (row["url"], row["guide_original_url_discovery"],
                row["approval_order_original_url_discovery"]):
        parsed = urlparse(url)
        assert parsed.scheme == "https" and parsed.hostname == "www.afir.ro"
        assert parsed.username is None and parsed.password is None and parsed.port is None
    assert set(("ROMANIA", "AFIR", "GUIDE_REVISION", "LEGAL_FRAMEWORK", "DISCOVERY")).issubset(
        set(row.get("source_families") or [])
    )
    assert not {"CALL_REGISTRY", "PROGRAMMING_PIPELINE", "OPEN_CALL"}.intersection(row.get("source_families") or [])
    assert row.get("programme_family") == "PS_PAC_2023_2027/DR36_LEADER"
    for key in ("material_fact_use", "credentials_required", "open_call_authorized",
                "material_fact_publication_authorized"):
        assert row.get(key) is False, "Unreviewed guide authorised material fact: " + key
    assert not NO_RECEIPT_OR_CALL_FACTS.intersection(row), "Unacquired raw or material call fact fabricated"
    evidence = set(row.get("extract") or [])
    assert {"MADR_order_309_12_november_2026_approves_guide_edition_II_revision_0",
            "AFIR_guide_document_index_labels_publication_13_november_2026_1145",
            "guide_and_order_distinct_official_pdf_sources_require_paired_immutable_raw_receipts",
            "DR36_LEADER_general_implementation_guide_not_a_GAL_specific_open_submission",
            "individual_GAL_call_identifier_current_endpoint_and_semantic_reconciliation_pending"}.issubset(evidence)
    note = row.get("note") or ""
    for word in ("12 November 2026", "13 November 2026 11:45", "Edition II Revision 0",
                 "NOT_CAPTURED", "SURFACEMC", "final_url", "fetched_at UTC",
                 "raw_sha256", "semantic_sha256", "parser_version", "run_id",
                 "handoff_sha256", "LKG", "OPEN_CALL", "NO MATERIAL PUBLICATION",
                 "NO DISTRIBUTION", "NO ALERT", "GAL-specific"):
        assert word in note, "Guide has lost stage/provenance warning: " + word

def main():
    rows = json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    check(rows)
    trial = copy.deepcopy(rows)
    trial.append(copy.deepcopy(next(x for x in rows if x.get("id") == IDENTITY)))
    for label, case in [("duplicate", trial)]:
        try:
            check(case)
        except AssertionError:
            pass
        else:
            raise AssertionError("DR36 unsafe mutation admitted: " + label)
    rejected = 1
    mutations = [
        ("observation_state", "OPEN_CALL"),
        ("tier", "T2"),
        ("authority_scope", "EXACT_GAL_CALL"),
        ("authority_class", "T3_SOCIAL"),
        ("url", "https://example.invalid/guide.pdf"),
        ("guide_original_url_discovery", "https://example.invalid/guide.pdf"),
        ("approval_order_original_url_discovery", "https://example.invalid/order.pdf"),
        ("approval_order_identifier_discovery", "OMADR 310/12.11.2026"),
        ("approval_order_date_discovery", "2026-11-18"),
        ("guide_publication_datetime_discovery", "2026-11-18 11:45 Europe/Bucharest"),
        ("guide_edition_discovery", "I"),
        ("guide_revision_discovery", "3"),
        ("material_fact_use", True),
        ("open_call_authorized", True),
        ("material_fact_publication_authorized", True),
        ("credentials_required", True),
        ("status", "OPEN"),
        ("deadline", "2027-01-31T17:00:00+02:00"),
        ("budget_eur", 12000000),
        ("eligibility", ["all Romanian applicants"]),
        ("call_identifier", "DR36-GAL-OPEN"),
        ("submission_endpoint", "https://www.afir.ro/fake-submit"),
        ("raw_sha256", "0"*64),
        ("final_url", ORDER),
        ("fetched_at", "2026-11-18T12:30:00Z"),
        ("parser_version", "fabricated"),
        ("run_id", "fabricated"),
        ("handoff_sha256", "0"*64),
    ]
    for key, value in mutations:
        trial = copy.deepcopy(rows)
        next(x for x in trial if x.get("id") == IDENTITY)[key] = value
        try:
            check(trial)
        except AssertionError:
            rejected += 1
        else:
            raise AssertionError("DR36 unsafe mutation admitted: " + key)
    print(json.dumps({
        "result": "PASS", "source_id": IDENTITY, "negative_mutations_rejected": rejected,
        "state": "APPROVED_IMPLEMENTATION_GUIDE_REVISION_DISCOVERED_RAW_PENDING",
        "open_call_authorized": False, "publication_effect": "NONE",
    }))

if __name__ == "__main__":
    main()
