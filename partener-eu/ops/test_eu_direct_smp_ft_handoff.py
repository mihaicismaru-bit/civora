#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1] / "ingest"
sys.path.insert(0, str(ROOT))

from eu_direct_smp_ft_handoff import (  # noqa: E402
    CURRENT_MODE,
    OMITTED_RECHECK_MODE,
    OMITTED_SKIP_MODE,
    resolve,
    validate,
)
from eu_direct_smp_ft_exact import (  # noqa: E402
    LEGACY_PARSER_VERSION as SMP_LEGACY_PARSER,
    MATERIAL_FLAGS,
    SCHEMA as SMP_SCHEMA,
    programme_fit_evidence,
    sha256_json,
)

REF = "SMP-FOOD-2026-FW-STAKEHOLDERS-PJ"


def taxonomy(records):
    return {
        "schema": "PARTENER_EU_FT_PROGRAMME_TAXONOMY_V1",
        "market_intelligence_only": True,
        "material_fact_use": False,
        "records": records,
    }


def smp_row(reference=REF):
    return {
        "programme_family_normalized": "SINGLE_MARKET_PROGRAMME",
        "identifier": reference,
        "status_label_candidate": "Open",
        "taxonomy_fingerprint": "a" * 64,
        "source_semantic_fingerprint": "b" * 64,
        "authority_url_candidate": f"https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{reference}",
    }


def previous(reference=REF):
    authority_url = f"https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{reference}"
    semantics = {
        "identifier": reference,
        "call_identifier": "SMP-FOOD-2026-FW-STAKEHOLDERS",
        "title": "Synthetic Single Market Programme test",
        "programme_reference": "43252405",
        "programme_label": "Single Market Programme (SMP)",
        "status_label": "Open",
        "observation_state": "OPEN_CALL",
        "authority_url": authority_url,
        "deadline_candidate": None,
        "budget_candidate": None,
    }
    fit = programme_fit_evidence(observed_at="2026-09-01T00:00:00+00:00")
    obj = {
        "schema": SMP_SCHEMA,
        "parser_version": SMP_LEGACY_PARSER,
        "source_family": "EU_DIRECT",
        "programme_family": "SINGLE_MARKET_PROGRAMME",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS",
        "observation_state": "EXACT_CURRENT_TOPIC_NON_AUTHORIZING",
        "reference": reference,
        "fetched_at": "2026-09-01T00:00:00+00:00",
        "run_id": "previous",
        "search_receipt": {"sha256": "c" * 64},
        "facet_receipt": {"sha256": "d" * 64},
        "search_raw_sha256": "e" * 64,
        "facet_raw_sha256": "f" * 64,
        "authority_url": authority_url,
        "authority_readback": {"verified": True, "url": authority_url},
        "authority_url_verified": True,
        "candidate_state": "OPEN_CALL",
        "status_label": "Open",
        "call_identifier": semantics["call_identifier"],
        "title": semantics["title"],
        "programme_reference": semantics["programme_reference"],
        "programme_label_official": "Single Market Programme (SMP)",
        "deadline_candidate": None,
        "budget_candidate": None,
        "exact_semantics": semantics,
        "exact_semantic_fingerprint": sha256_json(semantics),
        "primary_exact_record_count": 1,
        "linked_type8_record_count": 0,
        "linked_type8_record_hashes": [],
        "source_candidate": {},
        "source_candidate_fingerprint": None,
        "programme_fit_evidence": fit,
        "programme_fit_semantic_fingerprint": sha256_json(fit),
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
    current = resolve(taxonomy([smp_row()]), run_id="current")
    validate(current)
    assert current["observation_state"] == CURRENT_MODE
    assert current["target_reference"] == REF
    assert current["exact_recheck_required"] is True
    assert current["current_taxonomy_candidate"] is True
    assert current["previous_evidence_available"] is False
    assert current["closure_inference_authorized"] is False
    assert current["open_call_authorized"] is False

    prev = previous()
    omitted_recheck = resolve(taxonomy([]), previous=prev, run_id="omitted-recheck")
    validate(omitted_recheck)
    assert omitted_recheck["observation_state"] == OMITTED_RECHECK_MODE
    assert omitted_recheck["target_reference"] == prev["reference"]
    assert omitted_recheck["exact_recheck_required"] is True
    assert omitted_recheck["previous_same_identity"] is True
    assert omitted_recheck["bounded_sample_omission_is_material_fact"] is False
    assert omitted_recheck["closure_inference_authorized"] is False
    assert omitted_recheck["open_call_authorized"] is False

    omitted_skip = resolve(taxonomy([]), run_id="omitted-skip")
    validate(omitted_skip)
    assert omitted_skip["observation_state"] == OMITTED_SKIP_MODE
    assert omitted_skip["target_reference"] is None
    assert omitted_skip["exact_recheck_required"] is False
    assert omitted_skip["open_call_authorized"] is False

    different_prev = previous("SMP-COSME-2025-OTHER-TEST")
    current_with_other_history = resolve(taxonomy([smp_row()]), previous=different_prev, run_id="current-other-history")
    assert current_with_other_history["observation_state"] == CURRENT_MODE
    assert current_with_other_history["previous_evidence_available"] is True
    assert current_with_other_history["previous_same_identity"] is False

    tampered = copy.deepcopy(omitted_recheck)
    tampered["closure_inference_authorized"] = True
    expect_fail(lambda: validate(tampered))

    widened = copy.deepcopy(omitted_recheck)
    widened["open_call_authorized"] = True
    expect_fail(lambda: validate(widened))

    bad_skip = copy.deepcopy(omitted_skip)
    bad_skip["target_reference"] = prev["reference"]
    expect_fail(lambda: validate(bad_skip))

    invalid_previous = copy.deepcopy(prev)
    invalid_previous["authority_url_verified"] = False
    expect_fail(lambda: resolve(taxonomy([]), previous=invalid_previous, run_id="invalid-previous"))

    fit_widened = copy.deepcopy(prev)
    fit_widened["programme_fit_evidence"]["eligibility_fact_authorized"] = True
    fit_widened["programme_fit_semantic_fingerprint"] = sha256_json(fit_widened["programme_fit_evidence"])
    expect_fail(lambda: resolve(taxonomy([]), previous=fit_widened, run_id="invalid-fit-previous"))

    print(json.dumps({
        "current": current["observation_state"],
        "omitted_with_previous": omitted_recheck["observation_state"],
        "omitted_without_previous": omitted_skip["observation_state"],
        "legacy_history_replay_compatible": True,
        "material_authorization": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
