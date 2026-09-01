#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1] / "ingest"
sys.path.insert(0, str(ROOT))

from eu_direct_digital_ft_handoff import (  # noqa: E402
    CURRENT_MODE,
    OMITTED_RECHECK_MODE,
    OMITTED_SKIP_MODE,
    resolve_handoff,
    validate_state,
)
from eu_direct_digital_ft_exact import SCHEMA as DIGITAL_SCHEMA, PARSER_VERSION as DIGITAL_PARSER  # noqa: E402


def taxonomy(records):
    return {
        "schema": "PARTENER_EU_FT_PROGRAMME_TAXONOMY_V1",
        "market_intelligence_only": True,
        "material_fact_use": False,
        "records": records,
    }


def digital_row(reference="DIGITAL-2026-AI-DATA-10-COMPLIANCE"):
    return {
        "programme_family_normalized": "DIGITAL_EUROPE",
        "identifier": reference,
        "status_label_candidate": "Open",
        "taxonomy_fingerprint": "a" * 64,
        "source_semantic_fingerprint": "b" * 64,
        "authority_url_candidate": f"https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{reference}",
    }


def previous(reference="DIGITAL-2026-AI-DATA-10-COMPLIANCE"):
    from eu_direct_digital_ft_exact import MATERIAL_FLAGS, sha256_json

    semantics = {
        "identifier": reference,
        "call_identifier": "DIGITAL-2026-AI-DATA-10",
        "title": "Synthetic Digital Europe test",
        "programme_reference": "43152860",
        "programme_label": "Digital Europe Programme",
        "status_label": "Open",
        "observation_state": "OPEN_CALL",
        "authority_url": f"https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{reference}",
        "deadline_candidate": None,
        "budget_candidate": None,
    }
    obj = {
        "schema": DIGITAL_SCHEMA,
        "parser_version": DIGITAL_PARSER,
        "source_family": "EU_DIRECT",
        "programme_family": "DIGITAL_EUROPE",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS",
        "observation_state": "EXACT_CURRENT_TOPIC_NON_AUTHORIZING",
        "reference": reference,
        "fetched_at": "2026-09-01T00:00:00+00:00",
        "run_id": "previous",
        "search_receipt": {"sha256": "c" * 64},
        "facet_receipt": {"sha256": "d" * 64},
        "search_raw_sha256": "e" * 64,
        "facet_raw_sha256": "f" * 64,
        "authority_url": semantics["authority_url"],
        "authority_readback": {"verified": True, "url": semantics["authority_url"]},
        "authority_url_verified": True,
        "candidate_state": "OPEN_CALL",
        "status_label": "Open",
        "call_identifier": semantics["call_identifier"],
        "title": semantics["title"],
        "programme_reference": semantics["programme_reference"],
        "programme_label_official": "Digital Europe Programme",
        "deadline_candidate": None,
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
    }
    for key in MATERIAL_FLAGS:
        obj[key] = False
    return obj


def expect_fail(fn):
    try:
        fn()
    except Exception:
        return
    raise AssertionError("expected fail-closed rejection")


def main() -> int:
    current = resolve_handoff(taxonomy([digital_row()]), run_id="current")
    assert current["observation_state"] == CURRENT_MODE
    assert current["target_reference"] == "DIGITAL-2026-AI-DATA-10-COMPLIANCE"
    assert current["exact_recheck_required"] is True
    assert current["current_taxonomy_candidate"] is True
    assert current["previous_evidence_available"] is False
    assert current["closure_inference_authorized"] is False
    assert current["open_call_authorized"] is False

    prev = previous()
    omitted_recheck = resolve_handoff(taxonomy([]), previous=prev, run_id="omitted-recheck")
    assert omitted_recheck["observation_state"] == OMITTED_RECHECK_MODE
    assert omitted_recheck["target_reference"] == prev["reference"]
    assert omitted_recheck["exact_recheck_required"] is True
    assert omitted_recheck["previous_same_identity"] is True
    assert omitted_recheck["bounded_sample_omission_is_material_fact"] is False
    assert omitted_recheck["closure_inference_authorized"] is False
    assert omitted_recheck["open_call_authorized"] is False

    omitted_skip = resolve_handoff(taxonomy([]), run_id="omitted-skip")
    assert omitted_skip["observation_state"] == OMITTED_SKIP_MODE
    assert omitted_skip["target_reference"] is None
    assert omitted_skip["exact_recheck_required"] is False
    assert omitted_skip["open_call_authorized"] is False

    different_prev = previous("DIGITAL-2025-OTHER-01-TEST")
    current_with_other_history = resolve_handoff(
        taxonomy([digital_row()]), previous=different_prev, run_id="current-other-history"
    )
    assert current_with_other_history["observation_state"] == CURRENT_MODE
    assert current_with_other_history["previous_evidence_available"] is True
    assert current_with_other_history["previous_same_identity"] is False

    tampered = copy.deepcopy(omitted_recheck)
    tampered["closure_inference_authorized"] = True
    expect_fail(lambda: validate_state(tampered))

    widened = copy.deepcopy(omitted_recheck)
    widened["open_call_authorized"] = True
    expect_fail(lambda: validate_state(widened))

    bad_skip = copy.deepcopy(omitted_skip)
    bad_skip["target_reference"] = prev["reference"]
    expect_fail(lambda: validate_state(bad_skip))

    invalid_previous = copy.deepcopy(prev)
    invalid_previous["authority_url_verified"] = False
    expect_fail(lambda: resolve_handoff(taxonomy([]), previous=invalid_previous, run_id="invalid-previous"))

    print(json.dumps({
        "current": current["observation_state"],
        "omitted_with_previous": omitted_recheck["observation_state"],
        "omitted_without_previous": omitted_skip["observation_state"],
        "material_authorization": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
