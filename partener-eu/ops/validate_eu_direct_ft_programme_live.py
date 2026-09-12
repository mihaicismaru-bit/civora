#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
    "call_alert_authorized",
)


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def check_non_authorizing(obj: dict[str, Any]) -> None:
    for key in MATERIAL_FLAGS:
        assert obj[key] is False, (key, obj.get(key))
    assert obj["canonical_corpus_mutation"] is False
    assert obj["publication_effect"] == "NONE"


def validate_exact_pair(exact: dict[str, Any], rec: dict[str, Any], *, family: str, prefix: str, label_token: str) -> None:
    assert exact["reference"].startswith(prefix)
    assert exact["programme_family"] == family
    assert label_token in exact["programme_label_official"].casefold()
    assert exact["authority_url_verified"] is True
    assert exact["authority_readback"]["verified"] is True
    assert exact["candidate_state"] in {"OPEN_CALL", "FORTHCOMING_CALL", "CLOSED_CALL", "UNKNOWN"}
    assert exact["status_label"]
    assert exact["semantic_reconciliation_required"] is True
    assert exact["field_scoped_material_admission_required"] is True
    check_non_authorizing(exact)
    check_non_authorizing(rec)
    assert rec["reference"] == exact["reference"]
    assert rec["current_evidence_sha256"] == canonical_sha(exact)
    assert rec["material_admission_ready_for_downstream_review"] is (exact["candidate_state"] == "OPEN_CALL")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--previous-life-available", action="store_true")
    parser.add_argument("--previous-life-run-id")
    parser.add_argument("--previous-cef-available", action="store_true")
    parser.add_argument("--previous-cef-run-id")
    args = parser.parse_args()

    root = args.root
    d = load(root / "programme-watch.json")
    c = load(root / "programme-coverage-receipt.json")
    t = load(root / "programme-taxonomy.json")
    life = load(root / "life-exact/ft-life-exact-evidence.json")
    life_rec = load(root / "life-exact/ft-life-reconciliation.json")
    cef_handoff = load(root / "cef-exact/ft-cef-handoff-state.json")

    assert d["schema"] == "PARTENER_EU_FT_PROGRAMME_COVERAGE_WATCH_V1"
    assert c["schema"] == "PARTENER_EU_FT_PROGRAMME_COVERAGE_RECEIPT_V1"
    assert t["schema"] == "PARTENER_EU_FT_PROGRAMME_TAXONOMY_V1"
    assert life["schema"] == "PARTENER_EU_LIFE_FT_EXACT_EVIDENCE_V1"
    assert life_rec["schema"] == "PARTENER_EU_LIFE_FT_RECONCILIATION_V1"
    assert cef_handoff["schema"] == "PARTENER_EU_CEF_FT_HANDOFF_STATE_V1"

    for obj in (d, c, t):
        assert obj["market_intelligence_only"] is True
        check_non_authorizing(obj)
    check_non_authorizing(cef_handoff)
    assert cef_handoff["bounded_sample_omission_is_material_fact"] is False
    assert cef_handoff["closure_inference_authorized"] is False

    assert d["stats"]["raw_search_records"] >= d["stats"]["accepted_candidates"]
    assert t["stats"]["source_records"] == d["stats"]["accepted_candidates"]
    assert t["stats"]["normalized_records"] == d["stats"]["accepted_candidates"]
    if d["pagination"]["stop_reason"] == "MAX_PAGES_REACHED":
        assert c["coverage_complete"] is False
        assert c["pagination_truncated"] is True
        assert c["more_results_possible"] is True
        assert c["coverage_scope"] == "BOUNDED_QUERY_SAMPLE_NON_AUTHORIZING"

    life_rows = [r for r in t["records"] if r["programme_family_normalized"] == "LIFE"]
    cef_rows = [r for r in t["records"] if r["programme_family_normalized"] == "CEF"]
    assert life_rows
    for row in d["records"]:
        assert row["authority_url_verified"] is False
        assert row["exact_topic_readback_required"] is True
        assert row["semantic_reconciliation_required"] is True
        assert row["material_fact_use"] is False
        assert row["open_call_authorized"] is False
        assert row["publish_authorized"] is False

    validate_exact_pair(life, life_rec, family="LIFE", prefix="LIFE-", label_token="environment and climate action")
    previous_life = None
    if args.previous_life_available:
        previous_life = load(root / "history/previous/life-exact/ft-life-exact-evidence.json")
        assert previous_life["reference"] == life["reference"]
        expected = (
            "NO_CHANGE"
            if previous_life["exact_semantic_fingerprint"] == life["exact_semantic_fingerprint"]
            else "LIFE_EXACT_TOPIC_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
        )
        assert life_rec["reconciliation_state"] == expected
        assert life_rec["previous_evidence_sha256"] == canonical_sha(previous_life)
    else:
        assert life_rec["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
        assert life_rec["previous_evidence_sha256"] is None

    current_candidate = cef_handoff["current_taxonomy_candidate"] is True
    exact_required = cef_handoff["exact_recheck_required"] is True
    if current_candidate:
        assert cef_rows
        assert cef_handoff["observation_state"] == "CURRENT_BOUNDED_SAMPLE_CANDIDATE_EXACT_RECHECK"
    else:
        assert not cef_rows
        assert cef_handoff["observation_state"] in {
            "BOUNDED_SAMPLE_FAMILY_OMITTED_PREVIOUS_IDENTITY_EXACT_RECHECK",
            "BOUNDED_SAMPLE_FAMILY_OMITTED_NO_SAFE_IDENTITY_NON_AUTHORIZING",
        }

    cef = cef_rec = previous_cef = None
    cef_previous_used = False
    if exact_required:
        cef = load(root / "cef-exact/ft-cef-exact-evidence.json")
        cef_rec = load(root / "cef-exact/ft-cef-reconciliation.json")
        validate_exact_pair(cef, cef_rec, family="CEF", prefix="CEF-", label_token="connecting europe facility")
        assert cef["reference"] == cef_handoff["target_reference"]
        cef_previous_used = args.previous_cef_available and cef_handoff["previous_same_identity"] is True
        if cef_previous_used:
            previous_cef = load(root / "history/previous/cef-exact/ft-cef-exact-evidence.json")
            assert previous_cef["reference"] == cef["reference"]
            expected = (
                "NO_CHANGE"
                if previous_cef["exact_semantic_fingerprint"] == cef["exact_semantic_fingerprint"]
                else "CEF_EXACT_TOPIC_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
            )
            assert cef_rec["reconciliation_state"] == expected
            assert cef_rec["previous_evidence_sha256"] == canonical_sha(previous_cef)
        else:
            assert cef_rec["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
            assert cef_rec["previous_evidence_sha256"] is None
        if not current_candidate:
            assert args.previous_cef_available
            assert cef_handoff["previous_same_identity"] is True
            assert cef_handoff["observation_state"] == "BOUNDED_SAMPLE_FAMILY_OMITTED_PREVIOUS_IDENTITY_EXACT_RECHECK"
    else:
        assert not current_candidate
        assert args.previous_cef_available is False
        assert cef_handoff["target_reference"] is None
        assert cef_handoff["observation_state"] == "BOUNDED_SAMPLE_FAMILY_OMITTED_NO_SAFE_IDENTITY_NON_AUTHORIZING"
        assert not (root / "cef-exact/ft-cef-exact-evidence.json").exists()
        assert not (root / "cef-exact/ft-cef-reconciliation.json").exists()

    print(json.dumps({
        "stats": d["stats"],
        "pagination": d["pagination"],
        "coverage": {
            "coverage_complete": c["coverage_complete"],
            "pagination_truncated": c["pagination_truncated"],
            "more_results_possible": c["more_results_possible"],
            "coverage_scope": c["coverage_scope"],
        },
        "programme_family_counts_normalized": t["programme_family_counts"],
        "life_exact": {
            "reference": life["reference"],
            "candidate_state": life["candidate_state"],
            "previous_evidence_available": args.previous_life_available,
            "previous_evidence_run_id": args.previous_life_run_id,
            "reconciliation_state": life_rec["reconciliation_state"],
            "semantic_change_count": life_rec["semantic_change_count"],
        },
        "cef_handoff": {
            "observation_state": cef_handoff["observation_state"],
            "current_taxonomy_candidate": current_candidate,
            "previous_evidence_available": args.previous_cef_available,
            "previous_evidence_run_id": args.previous_cef_run_id,
            "previous_same_identity": cef_handoff["previous_same_identity"],
            "target_reference": cef_handoff["target_reference"],
            "exact_recheck_required": exact_required,
            "closure_inference_authorized": cef_handoff["closure_inference_authorized"],
        },
        "cef_exact": None if cef is None else {
            "reference": cef["reference"],
            "candidate_state": cef["candidate_state"],
            "status_label": cef["status_label"],
            "authority_url_verified": cef["authority_url_verified"],
            "previous_evidence_used": cef_previous_used,
            "reconciliation_state": cef_rec["reconciliation_state"],
            "semantic_change_count": cef_rec["semantic_change_count"],
            "material_admission_ready_for_downstream_review": cef_rec["material_admission_ready_for_downstream_review"],
            "open_call_authorized": cef_rec["open_call_authorized"],
        },
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
