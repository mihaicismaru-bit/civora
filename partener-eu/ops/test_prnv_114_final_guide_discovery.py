#!/usr/bin/env python3
"""Guard PRNV/2026/114/1 16 Nov final guide discovery against phantom OPEN."""
import copy
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "ingest" / "source_registry.json"
ID = "SRC-RO-ADRNORDVEST-PRNV-2026-114-1-FINAL-GUIDE-20261116"
URL = "https://regionordvest.ro/apel-prnv-2026-114-1-sprijin-pentru-ecosistemul-de-inovare-si-transfer-tehnologic/"
FORBIDDEN = {
    "status", "call_status", "current_status", "deadline", "submission_deadline",
    "budget", "budget_eur", "eligibility", "exact_submission_endpoint",
    "application_endpoint", "verified_guide_sha256", "verified_annex_sha256",
    "final_url", "fetched_at", "raw_sha256", "semantic_sha256", "parser_version",
    "run_id", "handoff_sha256", "publish_authorized", "last_verified_open",
    "submission_open", "my_smis_status",
}
def validate(rows):
    matches = [s for s in rows if s.get("id") == ID]
    assert len(matches) == 1, "Exact source must appear exactly once"
    s = matches[0]
    expected = {
        "tier": "T1",
        "url": URL,
        "authority_class": "T1_MANAGING_AUTHORITY_ADR_NORD_VEST",
        "authority_scope": "EXACT_PRNV_2026_114_1_GUIDE_PUBLICATION_DISCOVERY_ONLY",
        "observation_state": "FINAL_GUIDE_PUBLISHED_EXACT_CODE_RAW_PENDING",
        "call_identifier_discovery": "PRNV/2026/114/1",
        "guide_publication_date_discovery": "2026-11-16",
        "preceding_consultation_start_discovery": "2026-10-20",
        "preceding_consultation_end_discovery": "2026-11-10",
        "adapter_required": "ADR_NORD_VEST_PRNV_2026_114_1_FINAL_GUIDE_MYSMIS_EXACT_RAW_RECONCILE_V1",
    }
    for k,v in expected.items():
        assert s.get(k) == v, "Unsafe PRNV guide identity/stage drift: " + k
    assert urlparse(s["url"]).hostname == "regionordvest.ro"
    assert set(("ROMANIA","ADR","GUIDE_FINAL","DISCOVERY")).issubset(set(s.get("source_families",[])))
    assert all(s.get(k) is False for k in ("material_fact_use","credentials_required","open_call_authorized","material_fact_publication_authorized")), "Discovery must never authorize material claims"
    assert not (FORBIDDEN & s.keys()), "Unacquired original, fabricated receipt or current call assertion"
    extract = set(s.get("extract",[]))
    assert {"final_guide_initial_version_link_labeled_16_november_2026",
            "general_projects_deposited_table_is_cross_call_index_not_evidence_of_prnv_114_submissions",
            "my_smis_exact_live_submission_and_semantic_reconciliation_pending"}.issubset(extract)
    note=s.get("note","")
    for token in ("16 November 2026","PRNV/2026/114/1","NOT_CAPTURED",
                  "SURFACEMC","MySMIS","LKG","OPEN_CALL","NO MATERIAL PUBLICATION"):
        assert token in note, "Guide raw/evidence/quarantine lost: "+token

def main():
    rows=json.loads(REGISTRY.read_text(encoding="utf-8"))["sources"]
    validate(rows)
    mutations=[
        ("observation_state","OPEN_CALL"),
        ("open_call_authorized",True),
        ("material_fact_use",True),
        ("material_fact_publication_authorized",True),
        ("call_identifier_discovery","PRNV/2026/114/2"),
        ("guide_publication_date_discovery","2026-11-18"),
        ("preceding_consultation_end_discovery","2026-11-16"),
        ("authority_scope","CALL_OPEN_AUTHORITY"),
        ("authority_class","T3_MEDIA"),
        ("tier","T2"),
        ("url","https://example.invalid/guide"),
        ("exact_submission_endpoint","https://mysmis2021.gov.ro/fake"),
        ("status","OPEN"),
        ("deadline","2027-01-31"),
        ("budget_eur",100000000),
        ("eligibility",["any Romanian enterprise"]),
        ("raw_sha256","0"*64),
        ("fetched_at","2026-11-18T09:00:00Z"),
        ("run_id","fabricated-run"),
        ("parser_version","fabricated-parser"),
        ("verified_guide_sha256","0"*64),
    ]
    rejected=0
    for k,v in mutations:
        trial=copy.deepcopy(rows)
        next(x for x in trial if x.get("id")==ID)[k]=v
        try: validate(trial)
        except AssertionError: rejected+=1
        else: raise AssertionError("Unsafe mutation accepted: "+k)
    trial=copy.deepcopy(rows)
    trial.append(copy.deepcopy(next(x for x in rows if x.get("id")==ID)))
    try: validate(trial)
    except AssertionError: rejected+=1
    else: raise AssertionError("Duplicate source accepted")
    print(json.dumps({"result":"PASS","source_id":ID,
      "negative_mutations_rejected":rejected,
      "state":"FINAL_GUIDE_PUBLISHED_EXACT_CODE_RAW_PENDING",
      "open_call_authorized":False,"publication_effect":"NONE"}))

if __name__ == "__main__":
    main()
