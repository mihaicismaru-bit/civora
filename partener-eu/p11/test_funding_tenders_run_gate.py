#!/usr/bin/env python3
from __future__ import annotations
import copy
from funding_tenders_run_gate import classify_reconciliation

def fixture():
    return {
        "schema": "PARTENER_EU_FUNDING_TENDERS_RECONCILIATION_RECEIPT_V1",
        "publication_effect": "NONE",
        "publish_authorized": False,
        "canonical_corpus_mutation": False,
        "material_fact_action": "NONE",
        "records": [],
        "quarantined_records": [
            {"identifier":"PORTAL-ONLY-001","reconciliation_status":"REVIEW_REQUIRED","ready_for_staging":False,"material_fact_use":False,"publish_authorized":False,"reasons":["NON_DIRECT_OR_PORTAL_ONLY_CALL_TYPE"]},
            {"identifier":"TOPIC-MISMATCH-002","reconciliation_status":"REVIEW_REQUIRED","ready_for_staging":False,"material_fact_use":False,"publish_authorized":False,"reasons":["STRUCTURED_TOPIC_STATUS_MISMATCH"]},
        ],
        "stats": {"normalized_records":2,"ready_for_staging":0,"review_required":2},
        "material_fact_use": False,
        "ready_for_staging": False,
        "missing_proofs": [],
    }

def expect_failure(value, needle):
    try:
        classify_reconciliation(value)
    except ValueError as exc:
        assert needle in str(exc), (needle, str(exc))
    else:
        raise AssertionError("expected failure")

def main():
    zero=fixture()
    got=classify_reconciliation(zero)
    assert got == {"ready":False,"mode":"NO_DIRECT_CALLS_FAIL_CLOSED","ready_for_staging":0,"review_required":2}

    ready=fixture()
    ready["records"]=[{"identifier":"HORIZON-READY-001","reconciliation_status":"PASS","ready_for_staging":True,"material_fact_use":True,"publish_authorized":False,"reasons":[]}]
    ready["stats"]={"normalized_records":3,"ready_for_staging":1,"review_required":2}
    ready["material_fact_use"]=True
    ready["ready_for_staging"]=True
    ready["missing_proofs"]=["CANONICAL_STAGING_ADMISSION","PUBLIC_PROJECTION_QUALITY_GATE"]
    got=classify_reconciliation(ready)
    assert got["ready"] is True and got["mode"]=="READY" and got["ready_for_staging"]==1

    bad=copy.deepcopy(zero); bad["ready_for_staging"]=True
    expect_failure(bad,"zero-ready receipt cannot authorize")
    bad=copy.deepcopy(zero); bad["quarantined_records"][0]["material_fact_use"]=True
    expect_failure(bad,"quarantined row became authorizing")
    bad=copy.deepcopy(zero); bad["stats"]["normalized_records"]=3
    expect_failure(bad,"normalized_records stats mismatch")
    bad=copy.deepcopy(zero); bad["missing_proofs"]=["PUBLIC_PROJECTION_QUALITY_GATE"]
    expect_failure(bad,"zero-ready receipt cannot advertise downstream proofs")

    print("PASS Funding & Tenders run gate: zero direct calls are a consistent fail-closed no-op")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
