#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "partener-eu" / "ingest"))

import creative_europe_ft_exact as exact
import creative_europe_ft_reconcile as reconcile
import funding_tenders_fetch as ft


def _sha(value: object) -> str:
    return hashlib.sha256(exact.canonical_json(value)).hexdigest()


def evidence(
    *,
    run_id: str,
    fetched_at: str,
    state: str = "OPEN_CALL",
    status_code: str = "31094502",
    status_label: str = "Open",
    deadline: str | None = "2026-09-17T00:00:00.000+0000",
) -> dict:
    reference = "CREA-MEDIA-2026-DEVMINISLATE"
    semantic = {
        "reference": reference,
        "status_code": status_code,
        "status_label": status_label,
        "candidate_observation_state": state,
        "authority_url": ft.topic_url(reference),
        "authority_url_verified": True,
        "programme": "CREA",
        "deadline_candidate": deadline,
        "budget_candidate": None,
    }
    value = {
        "schema": "PARTENER_EU_CREATIVE_EUROPE_FT_EXACT_EVIDENCE_V1",
        "adapter_id": "CREATIVE_EUROPE_CALLS_V1",
        "evidence_layer": "EXACT_FUNDING_TENDERS_TOPIC",
        "parser_version": "CREATIVE_EUROPE_FT_EXACT_V1",
        "source_family": "EU_DIRECT",
        "programme_family": "CREATIVE_EUROPE",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS",
        "observation_state": "EXACT_TOPIC_EVIDENCE_NON_AUTHORIZING",
        **semantic,
        "fetched_at": fetched_at,
        "run_id": run_id,
        "search_receipt": {"endpoint": "synthetic"},
        "search_raw_sha256": "a" * 64,
        "facet_receipt": {"endpoint": "synthetic"},
        "facet_raw_sha256": "b" * 64,
        "topic_readback": {"verified": True, "body_sha256": "c" * 64},
        "semantic_fingerprint": _sha(semantic),
        "market_intelligence_only": True,
        "requires_reconcile": True,
        "missing_for_material_admission": [
            "semantic reconciliation against previous observation/LKG",
            "call-specific material admission for deadline/budget/eligibility/participation",
        ],
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in exact.MATERIAL_FLAGS:
        value[key] = False
    exact.validate_exact_evidence(value)
    return value


def expect_fail(current: dict, previous: dict | None, needle: str) -> None:
    try:
        reconcile.reconcile(current, previous, reconciled_at="2026-09-01T00:10:00Z")
    except ValueError as exc:
        if needle not in str(exc):
            raise AssertionError(f"unexpected error {exc!r}; wanted {needle!r}") from exc
    else:
        raise AssertionError(f"expected fail-closed rejection containing {needle!r}")


def assert_locked(receipt: dict) -> None:
    assert receipt["semantic_reconciliation_passed"] is True
    assert receipt["requires_material_admission"] is True
    assert receipt["market_intelligence_only"] is True
    assert receipt["call_alert_authorized"] is False
    assert receipt["publication_effect"] == "NONE"
    assert receipt["canonical_corpus_mutation"] is False
    for key in exact.MATERIAL_FLAGS:
        assert receipt[key] is False, (key, receipt[key])


def main() -> None:
    previous = evidence(run_id="prev", fetched_at="2026-08-31T18:00:00Z")
    current = evidence(run_id="current", fetched_at="2026-09-01T00:00:00Z")

    baseline = reconcile.reconcile(current, None, reconciled_at="2026-09-01T00:10:00Z")
    assert baseline["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
    assert baseline["semantic_change_count"] == 0
    assert_locked(baseline)

    same = reconcile.reconcile(current, previous, reconciled_at="2026-09-01T00:10:00Z")
    assert same["reconciliation_state"] == "NO_CHANGE"
    assert same["semantic_change_count"] == 0
    assert same["semantic_changed"] is False
    assert same["material_admission_ready_for_downstream_review"] is True
    assert_locked(same)

    closed = evidence(
        run_id="closed",
        fetched_at="2026-09-01T00:05:00Z",
        state="CLOSED_CALL",
        status_code="31094503",
        status_label="Closed",
        deadline="2026-09-17T00:00:00.000+0000",
    )
    changed = reconcile.reconcile(closed, current, reconciled_at="2026-09-01T00:10:00Z")
    assert changed["reconciliation_state"] == "EXACT_TOPIC_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
    assert changed["semantic_changed"] is True
    assert changed["semantic_change_count"] >= 3
    assert changed["material_admission_ready_for_downstream_review"] is False
    assert "current Funding & Tenders status is not verified OPEN" in changed["missing_for_material_admission"]
    assert_locked(changed)

    wrong_ref = copy.deepcopy(previous)
    wrong_ref["reference"] = "CREA-CULT-2026-OTHER"
    semantic = {key: wrong_ref.get(key) for key in reconcile.SEMANTIC_FIELDS}
    wrong_ref["authority_url"] = ft.topic_url(wrong_ref["reference"])
    semantic["authority_url"] = wrong_ref["authority_url"]
    wrong_ref["semantic_fingerprint"] = _sha(semantic)
    expect_fail(current, wrong_ref, "reference mismatch")

    future_previous = copy.deepcopy(previous)
    future_previous["fetched_at"] = "2026-09-01T00:01:00Z"
    expect_fail(current, future_previous, "newer than current")

    tampered = copy.deepcopy(current)
    tampered["status_label"] = "Closed"
    expect_fail(tampered, previous, "semantic fingerprint")

    authorizing = copy.deepcopy(current)
    authorizing["open_call_authorized"] = True
    expect_fail(authorizing, previous, "became authorizing")

    receipt = copy.deepcopy(same)
    receipt["distribution_authorized"] = True
    try:
        reconcile.validate_receipt(receipt)
    except ValueError as exc:
        assert "became authorizing" in str(exc)
    else:
        raise AssertionError("authorizing reconciliation receipt must fail closed")

    print(json.dumps({
        "status": "PASS",
        "baseline": baseline["reconciliation_state"],
        "same": same["reconciliation_state"],
        "changed": changed["reconciliation_state"],
        "open_call_authorized": same["open_call_authorized"],
        "call_alert_authorized": same["call_alert_authorized"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
