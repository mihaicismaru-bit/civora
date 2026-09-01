#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "partener-eu" / "ingest"))

from eu4health_hadea_ft_reconcile import MATERIAL_FLAGS, reconcile  # noqa: E402

REFERENCE = "EU4H-2026-SANTE-PJ-08"
TOPIC_URL = (
    "https://ec.europa.eu/info/funding-tenders/opportunities/portal/"
    "screen/opportunities/topic-details/" + REFERENCE
)


def hadea_fixture(*, status: str = "Closed", reference: str = REFERENCE) -> dict:
    return {
        "adapter_id": "EU4HEALTH_HADEA_CALLS_V1",
        "source_family": "EU_DIRECT",
        "programme_family": "EU4Health",
        "observation_state": "EXACT_CALL_EVIDENCE_UNRECONCILED",
        "market_intelligence_only": True,
        "publication_effect": "NONE",
        "evidence_usable_for_reconciliation": True,
        "source_health": {
            "health_state": "HEALTHY",
            "raw_sha256": "a" * 64,
        },
        "extracted": {
            "call_reference": reference,
            "status_candidate": status,
            "programme_candidate": "EU4Health",
            "funding_tenders_exact_topic_url": TOPIC_URL if reference == REFERENCE else TOPIC_URL.replace(REFERENCE, reference),
        },
        **{key: False for key in MATERIAL_FLAGS},
    }


def ft_fixture(*, status: str = "Closed", reference: str = REFERENCE, verified: bool = True) -> dict:
    topic = TOPIC_URL if reference == REFERENCE else TOPIC_URL.replace(REFERENCE, reference)
    return {
        "schema_version": "1.0",
        "collector_version": "EU4HEALTH_HADEA_FT_RECONCILE_V1",
        "source_family": "EU_DIRECT",
        "programme_family": "EU4Health",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS_EXACT_TOPIC",
        "identifier": reference,
        "topic_url": topic,
        "structured_topic": {
            "identifier": reference,
            "raw_sha256": "b" * 64,
            "status_codes": ["31094503"],
            "verified": verified,
        },
        "status_code": "31094503",
        "status_label": status,
        "topic_page_readback": {
            "verified": verified,
            "body_sha256": "c" * 64,
        },
        "verified": verified,
        "material_fact_use": False,
        "publish_authorized": False,
        "publication_effect": "NONE",
    }


def assert_failed_closed(result: dict) -> None:
    assert result["observation_state"] == "RECONCILIATION_FAILED_CLOSED"
    assert result["semantic_reconciliation_passed"] is False
    assert result["material_admission_ready_for_downstream_review"] is False
    assert result["candidate_material_status"] is None
    for key in MATERIAL_FLAGS:
        assert result[key] is False
    assert result["publication_effect"] == "NONE"
    assert result["canonical_corpus_mutation"] is False


def main() -> None:
    ok = reconcile(
        hadea_fixture(),
        ft_fixture(),
        run_id="fixture-eu4health-reconcile-ok",
        observed_at="2026-08-31T14:00:00Z",
    )
    assert ok["observation_state"] == "EXACT_CALL_REFERENCE_AND_STATUS_RECONCILED_NON_AUTHORIZING"
    assert ok["semantic_reconciliation_passed"] is True
    assert ok["identity_match"] is True
    assert ok["topic_url_match"] is True
    assert ok["status_match"] is True
    assert ok["programme_match"] is True
    assert ok["hadea_reference"] == REFERENCE == ok["funding_tenders_reference"]
    assert ok["candidate_material_status"] == "Closed"
    assert ok["material_admission_ready_for_downstream_review"] is True
    assert "current_funding_tenders_status_is_not_open" in ok["missing_for_open_confirmation"]
    assert len(ok["semantic_fingerprint"]) == 64
    for key in MATERIAL_FLAGS:
        assert ok[key] is False
    assert ok["publication_effect"] == "NONE"
    assert ok["canonical_corpus_mutation"] is False

    mismatch_id = reconcile(
        hadea_fixture(),
        ft_fixture(reference="EU4H-2026-SANTE-PJ-99"),
        run_id="fixture-eu4health-reconcile-id-mismatch",
        observed_at="2026-08-31T14:00:00Z",
    )
    assert_failed_closed(mismatch_id)
    assert "same_call_reference_match_hadea_to_funding_tenders" in mismatch_id["missing_for_open_confirmation"]

    mismatch_status = reconcile(
        hadea_fixture(status="Closed"),
        ft_fixture(status="Open"),
        run_id="fixture-eu4health-reconcile-status-mismatch",
        observed_at="2026-08-31T14:00:00Z",
    )
    assert_failed_closed(mismatch_status)
    assert "semantic_status_match_hadea_to_funding_tenders" in mismatch_status["missing_for_open_confirmation"]

    unverified = reconcile(
        hadea_fixture(),
        ft_fixture(verified=False),
        run_id="fixture-eu4health-reconcile-unverified",
        observed_at="2026-08-31T14:00:00Z",
    )
    assert_failed_closed(unverified)
    assert "verified_exact_structured_funding_tenders_evidence" in unverified["missing_for_open_confirmation"]

    unsafe = hadea_fixture()
    unsafe["open_call_authorized"] = True
    try:
        reconcile(
            unsafe,
            ft_fixture(),
            run_id="fixture-eu4health-reconcile-unsafe",
            observed_at="2026-08-31T14:00:00Z",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("authorizing HaDEA input must fail closed")

    print(json.dumps({
        "reference": REFERENCE,
        "reconciliation_state": ok["observation_state"],
        "candidate_material_status": ok["candidate_material_status"],
        "semantic_reconciliation_passed": ok["semantic_reconciliation_passed"],
        "open_call_authorized": ok["open_call_authorized"],
        "result": "PASS",
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
