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

CURRENT_MODE = "CURRENT_BOUNDED_SAMPLE_CANDIDATE_EXACT_RECHECK"
OMITTED_RECHECK_MODE = "BOUNDED_SAMPLE_FAMILY_OMITTED_PREVIOUS_IDENTITY_EXACT_RECHECK"
OMITTED_SKIP_MODE = "BOUNDED_SAMPLE_FAMILY_OMITTED_NO_SAFE_IDENTITY_NON_AUTHORIZING"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def check_non_authorizing(obj: dict[str, Any]) -> None:
    for key in MATERIAL_FLAGS:
        assert obj[key] is False, (key, obj.get(key))
    assert obj["canonical_corpus_mutation"] is False
    assert obj["publication_effect"] == "NONE"


def check_fit_binding(exact: dict[str, Any]) -> None:
    fit = exact["programme_fit_evidence"]
    assert canonical_sha(fit) == exact["programme_fit_semantic_fingerprint"]
    assert fit["observation_state"] == "PROGRAMME_FIT_RESEARCH_NON_AUTHORIZING"
    assert fit["facts"]["fit_state"] == "ROMANIA_PROGRAMME_LEVEL_FIT_DEMONSTRATED_NON_AUTHORIZING"
    assert fit["eligibility_fact_authorized"] is False
    assert fit["call_fact_authorized"] is False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--previous-smp-available", action="store_true")
    parser.add_argument("--previous-smp-run-id")
    args = parser.parse_args()
    root = args.root

    taxonomy = load(root / "programme-taxonomy.json")
    handoff = load(root / "smp-exact/ft-smp-handoff-state.json")
    assert taxonomy["schema"] == "PARTENER_EU_FT_PROGRAMME_TAXONOMY_V1"
    assert handoff["schema"] == "PARTENER_EU_SMP_FT_HANDOFF_V1"
    check_non_authorizing(handoff)
    assert handoff["bounded_sample_omission_is_material_fact"] is False
    assert handoff["closure_inference_authorized"] is False
    assert handoff["previous_evidence_available"] is args.previous_smp_available

    previous_path = root / "history/previous/smp-exact/ft-smp-exact-evidence.json"
    if args.previous_smp_available:
        assert args.previous_smp_run_id
        assert previous_path.exists()
        previous = load(previous_path)
        assert previous["schema"] == "PARTENER_EU_SMP_FT_EXACT_EVIDENCE_V1"
        assert canonical_sha(previous) == handoff["previous_evidence_sha256"]
        assert previous["reference"] == handoff["previous_reference"]
        check_fit_binding(previous)
        check_non_authorizing(previous)
    else:
        assert args.previous_smp_run_id is None
        assert not previous_path.exists()

    smp_rows = [
        row for row in taxonomy.get("records") or []
        if row.get("programme_family_normalized") == "SINGLE_MARKET_PROGRAMME"
    ]
    exact_required = handoff["exact_recheck_required"] is True
    mode = handoff["observation_state"]
    if exact_required:
        assert mode in {CURRENT_MODE, OMITTED_RECHECK_MODE}
        if mode == CURRENT_MODE:
            assert smp_rows
            assert handoff["current_taxonomy_candidate"] is True
        else:
            assert not smp_rows
            assert handoff["current_taxonomy_candidate"] is False
            assert handoff["previous_evidence_available"] is True
            assert handoff["previous_same_identity"] is True

        exact = load(root / "smp-exact/ft-smp-exact-evidence.json")
        rec = load(root / "smp-exact/ft-smp-reconciliation.json")
        assert exact["schema"] == "PARTENER_EU_SMP_FT_EXACT_EVIDENCE_V1"
        assert rec["schema"] == "PARTENER_EU_SMP_FT_RECONCILIATION_V1"
        assert exact["reference"] == handoff["target_reference"]
        assert exact["programme_family"] == "SINGLE_MARKET_PROGRAMME"
        assert exact["reference"].startswith("SMP-")
        assert "single market programme" in exact["programme_label_official"].casefold()
        assert exact["authority_url_verified"] is True
        assert exact["authority_readback"]["verified"] is True
        assert exact["candidate_state"] in {"OPEN_CALL", "FORTHCOMING_CALL", "CLOSED_CALL", "UNKNOWN"}
        assert exact["status_label"]
        check_fit_binding(exact)
        check_non_authorizing(exact)
        check_non_authorizing(rec)
        assert rec["reference"] == exact["reference"]
        assert rec["current_evidence_sha256"] == canonical_sha(exact)

        previous_same_identity = handoff["previous_same_identity"] is True
        if previous_same_identity:
            assert args.previous_smp_available
            previous = load(previous_path)
            assert previous["reference"] == exact["reference"]
            assert rec["previous_evidence_sha256"] == canonical_sha(previous)
            assert rec["reconciliation_state"] in {
                "NO_CHANGE",
                "SMP_EXACT_TOPIC_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING",
            }
        else:
            assert rec["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
            assert rec["previous_evidence_sha256"] is None

        assert rec["material_admission_ready_for_downstream_review"] is (exact["candidate_state"] == "OPEN_CALL")
        result = {
            "handoff_state": mode,
            "reference": exact["reference"],
            "candidate_state": exact["candidate_state"],
            "status_label": exact["status_label"],
            "authority_url_verified": exact["authority_url_verified"],
            "programme_fit_state": exact["programme_fit_evidence"]["facts"]["fit_state"],
            "previous_evidence_available": args.previous_smp_available,
            "previous_same_identity": previous_same_identity,
            "previous_run_id": args.previous_smp_run_id,
            "reconciliation_state": rec["reconciliation_state"],
            "semantic_change_count": rec["semantic_change_count"],
            "material_admission_ready_for_downstream_review": rec["material_admission_ready_for_downstream_review"],
            "open_call_authorized": rec["open_call_authorized"],
        }
    else:
        assert not smp_rows
        assert mode == OMITTED_SKIP_MODE
        assert handoff["current_taxonomy_candidate"] is False
        assert handoff["previous_evidence_available"] is False
        assert handoff["target_reference"] is None
        assert not (root / "smp-exact/ft-smp-exact-evidence.json").exists()
        assert not (root / "smp-exact/ft-smp-reconciliation.json").exists()
        result = {
            "handoff_state": mode,
            "reference": None,
            "exact_recheck_required": False,
            "previous_evidence_available": False,
            "open_call_authorized": False,
        }

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
