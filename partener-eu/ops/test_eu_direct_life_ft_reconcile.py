#!/usr/bin/env python3
from __future__ import annotations

import copy
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ingest"))

from eu_direct_life_ft_exact import sha256_json
from eu_direct_life_ft_reconcile import reconcile, validate_receipt

REF = "LIFE-2026-SAP-ENV-ENVIRONMENT"


def evidence(ts="2026-09-01T15:00:00+00:00", state="OPEN_CALL", status="Open", deadline="2026-09-23T17:00:00Z"):
    authority_url = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/" + REF
    semantics = {
        "identifier": REF,
        "call_identifier": "LIFE-2026-SAP-ENV",
        "title": "Synthetic LIFE topic",
        "programme_reference": "43252405",
        "programme_label": "Programme for the Environment and Climate Action (LIFE)",
        "status_label": status,
        "observation_state": state,
        "authority_url": authority_url,
        "deadline_candidate": deadline,
        "budget_candidate": None,
    }
    return {
        "schema": "PARTENER_EU_LIFE_FT_EXACT_EVIDENCE_V1",
        "parser_version": "EU_DIRECT_LIFE_FT_EXACT_V1",
        "source_family": "EU_DIRECT",
        "programme_family": "LIFE",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS",
        "observation_state": "EXACT_CURRENT_TOPIC_NON_AUTHORIZING",
        "reference": REF,
        "fetched_at": ts,
        "run_id": "synthetic",
        "search_receipt": {"sha256": "a" * 64},
        "facet_receipt": {"sha256": "b" * 64},
        "search_raw_sha256": "c" * 64,
        "facet_raw_sha256": "d" * 64,
        "authority_url": authority_url,
        "authority_readback": {"url": authority_url, "verified": True},
        "authority_url_verified": True,
        "candidate_state": state,
        "status_label": status,
        "call_identifier": semantics["call_identifier"],
        "title": semantics["title"],
        "programme_reference": semantics["programme_reference"],
        "programme_label_official": semantics["programme_label"],
        "deadline_candidate": deadline,
        "budget_candidate": None,
        "exact_semantics": semantics,
        "exact_semantic_fingerprint": sha256_json(semantics),
        "primary_exact_record_count": 1,
        "linked_type8_record_count": 0,
        "linked_type8_record_hashes": [],
        "source_candidate": {},
        "source_candidate_fingerprint": None,
        "semantic_reconciliation_required": True,
        "field_scoped_material_admission_required": True,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
        "material_fact_use": False,
        "open_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "call_alert_authorized": False,
    }


def main():
    current = evidence()
    baseline = reconcile(current)
    validate_receipt(baseline, current=current)
    assert baseline["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
    assert baseline["material_admission_ready_for_downstream_review"] is True
    assert baseline["open_call_authorized"] is False

    same = evidence("2026-09-01T16:00:00+00:00")
    no_change = reconcile(same, current)
    assert no_change["reconciliation_state"] == "NO_CHANGE"
    assert no_change["semantic_change_count"] == 0

    closed = evidence("2026-09-01T17:00:00+00:00", state="CLOSED_CALL", status="Closed")
    changed = reconcile(closed, same)
    assert changed["reconciliation_state"] == "LIFE_EXACT_TOPIC_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
    assert changed["semantic_change_count"] >= 1
    assert changed["material_admission_ready_for_downstream_review"] is False
    assert changed["call_alert_authorized"] is False

    tampered = copy.deepcopy(current)
    tampered["exact_semantics"]["status_label"] = "Closed"
    try:
        reconcile(tampered)
        raise AssertionError("tampered exact semantics were accepted")
    except ValueError as exc:
        assert "fingerprint" in str(exc)

    broadened = copy.deepcopy(baseline)
    broadened["deadline_authorized"] = True
    try:
        validate_receipt(broadened, current=current)
        raise AssertionError("reconciliation broadened material scope")
    except ValueError as exc:
        assert "attempted authorization" in str(exc)

    print("eu_direct_life_ft_reconcile regression: PASS")


if __name__ == "__main__":
    main()
