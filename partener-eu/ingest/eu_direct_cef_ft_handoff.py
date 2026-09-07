#!/usr/bin/env python3
"""Resolve one bounded CEF exact-handoff target without inferring material status.

The programme-wide F&T sample is explicitly non-exhaustive. If it contains a CEF
candidate, that current discovery pointer wins. If the bounded sample omits the
family, a validated previous exact CEF receipt may be used only as a pointer for
a fresh exact authority recheck. If neither exists, the family is skipped for
this run with a non-authorizing omission receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from typing import Any, Mapping

from eu_direct_cef_ft_exact import select_cef_candidate, validate_evidence

SCHEMA = "PARTENER_EU_CEF_FT_HANDOFF_STATE_V1"
PARSER_VERSION = "EU_DIRECT_CEF_FT_HANDOFF_V1"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "CEF"
AUTHORITY_CLASS = "EU_COMMISSION_FUNDING_TENDERS"
CURRENT_MODE = "CURRENT_BOUNDED_SAMPLE_CANDIDATE_EXACT_RECHECK"
OMITTED_RECHECK_MODE = "BOUNDED_SAMPLE_FAMILY_OMITTED_PREVIOUS_IDENTITY_EXACT_RECHECK"
OMITTED_SKIP_MODE = "BOUNDED_SAMPLE_FAMILY_OMITTED_NO_SAFE_IDENTITY_NON_AUTHORIZING"
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


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def load_previous(path: pathlib.Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    previous = json.loads(path.read_text(encoding="utf-8"))
    validate_evidence(previous)
    return previous


def resolve_handoff(
    taxonomy: Mapping[str, Any],
    *,
    previous: Mapping[str, Any] | None = None,
    run_id: str = "cef-ft-handoff",
) -> dict[str, Any]:
    if taxonomy.get("schema") != "PARTENER_EU_FT_PROGRAMME_TAXONOMY_V1":
        raise ValueError("unexpected programme taxonomy schema")
    if taxonomy.get("market_intelligence_only") is not True or taxonomy.get("material_fact_use") is not False:
        raise ValueError("programme taxonomy crossed discovery boundary")

    previous_obj: dict[str, Any] | None = None
    if previous is not None:
        previous_obj = dict(previous)
        validate_evidence(previous_obj)

    current_candidate: dict[str, Any] | None
    try:
        current_candidate = select_cef_candidate(taxonomy)
    except ValueError as exc:
        if str(exc) != "programme taxonomy contains no CEF candidate":
            raise
        current_candidate = None

    if current_candidate is not None:
        target_reference = current_candidate["identifier"]
        observation_state = CURRENT_MODE
        exact_recheck_required = True
        current_taxonomy_candidate = True
    elif previous_obj is not None:
        target_reference = str(previous_obj["reference"])
        observation_state = OMITTED_RECHECK_MODE
        exact_recheck_required = True
        current_taxonomy_candidate = False
    else:
        target_reference = None
        observation_state = OMITTED_SKIP_MODE
        exact_recheck_required = False
        current_taxonomy_candidate = False

    previous_same_identity = bool(
        previous_obj is not None
        and target_reference is not None
        and str(previous_obj.get("reference")) == target_reference
    )
    state: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": observation_state,
        "run_id": run_id,
        "taxonomy_sha256": sha256_json(taxonomy),
        "current_taxonomy_candidate": current_taxonomy_candidate,
        "current_source_candidate": current_candidate,
        "previous_evidence_available": previous_obj is not None,
        "previous_evidence_sha256": sha256_json(previous_obj) if previous_obj is not None else None,
        "previous_reference": previous_obj.get("reference") if previous_obj is not None else None,
        "previous_same_identity": previous_same_identity,
        "target_reference": target_reference,
        "exact_recheck_required": exact_recheck_required,
        "bounded_sample_omission_is_material_fact": False,
        "closure_inference_authorized": False,
        "semantic_reconciliation_required_if_exact": exact_recheck_required,
        "field_scoped_material_admission_required_if_exact": exact_recheck_required,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        state[key] = False
    validate_state(state)
    return state


def validate_state(state: Mapping[str, Any]) -> None:
    if state.get("schema") != SCHEMA or state.get("parser_version") != PARSER_VERSION:
        raise ValueError("CEF handoff state schema/parser drift")
    if state.get("source_family") != SOURCE_FAMILY or state.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("CEF handoff family drift")
    if state.get("authority_class") != AUTHORITY_CLASS:
        raise ValueError("CEF handoff authority drift")
    mode = state.get("observation_state")
    if mode not in {CURRENT_MODE, OMITTED_RECHECK_MODE, OMITTED_SKIP_MODE}:
        raise ValueError("unsupported CEF handoff state")
    target = state.get("target_reference")
    exact_required = state.get("exact_recheck_required") is True
    if exact_required != bool(target):
        raise ValueError("CEF handoff target/exact requirement mismatch")
    if mode == CURRENT_MODE and state.get("current_taxonomy_candidate") is not True:
        raise ValueError("current CEF mode lost current candidate")
    if mode == OMITTED_RECHECK_MODE:
        if state.get("current_taxonomy_candidate") is not False or state.get("previous_evidence_available") is not True:
            raise ValueError("CEF omission recheck lacks validated previous pointer")
        if state.get("previous_same_identity") is not True:
            raise ValueError("CEF omission recheck previous identity mismatch")
    if mode == OMITTED_SKIP_MODE:
        if state.get("current_taxonomy_candidate") is not False or state.get("previous_evidence_available") is not False:
            raise ValueError("CEF omission skip unexpectedly has a candidate")
        if target is not None or exact_required:
            raise ValueError("CEF omission skip attempted exact handoff")
    if state.get("bounded_sample_omission_is_material_fact") is not False or state.get("closure_inference_authorized") is not False:
        raise ValueError("CEF sample omission crossed material boundary")
    for key in MATERIAL_FLAGS:
        if state.get(key) is not False:
            raise ValueError(f"CEF handoff attempted authorization: {key}")
    if state.get("publication_effect") != "NONE" or state.get("canonical_corpus_mutation") is not False:
        raise ValueError("CEF handoff crossed publication boundary")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--taxonomy", required=True, type=pathlib.Path)
    parser.add_argument("--previous", type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--run-id", default="cef-ft-handoff-live")
    args = parser.parse_args()

    taxonomy = json.loads(args.taxonomy.read_text(encoding="utf-8"))
    previous = load_previous(args.previous)
    state = resolve_handoff(taxonomy, previous=previous, run_id=args.run_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "observation_state": state["observation_state"],
        "target_reference": state["target_reference"],
        "exact_recheck_required": state["exact_recheck_required"],
        "previous_same_identity": state["previous_same_identity"],
        "open_call_authorized": state["open_call_authorized"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
