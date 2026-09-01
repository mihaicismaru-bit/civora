#!/usr/bin/env python3
"""Resolve a bounded Digital Europe exact-handoff target without status inference."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from typing import Any, Mapping

from eu_direct_digital_ft_exact import select_digital_candidate

SCHEMA = "PARTENER_EU_DIGITAL_FT_HANDOFF_STATE_V1"
PARSER_VERSION = "EU_DIRECT_DIGITAL_FT_HANDOFF_V1"
CURRENT_MODE = "CURRENT_BOUNDED_SAMPLE_CANDIDATE_EXACT_RECHECK"
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


def resolve_handoff(taxonomy: Mapping[str, Any], *, run_id: str = "digital-ft-handoff") -> dict[str, Any]:
    if taxonomy.get("schema") != "PARTENER_EU_FT_PROGRAMME_TAXONOMY_V1":
        raise ValueError("unexpected programme taxonomy schema")
    if taxonomy.get("market_intelligence_only") is not True or taxonomy.get("material_fact_use") is not False:
        raise ValueError("programme taxonomy crossed discovery boundary")
    try:
        candidate = select_digital_candidate(taxonomy)
    except ValueError as exc:
        if str(exc) != "programme taxonomy contains no Digital Europe candidate":
            raise
        candidate = None

    state: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": "EU_DIRECT",
        "programme_family": "DIGITAL_EUROPE",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS",
        "observation_state": CURRENT_MODE if candidate else OMITTED_SKIP_MODE,
        "run_id": run_id,
        "taxonomy_sha256": sha256_json(taxonomy),
        "current_taxonomy_candidate": candidate is not None,
        "current_source_candidate": candidate,
        "target_reference": candidate.get("identifier") if candidate else None,
        "exact_recheck_required": candidate is not None,
        "bounded_sample_omission_is_material_fact": False,
        "closure_inference_authorized": False,
        "semantic_reconciliation_required_if_exact": candidate is not None,
        "field_scoped_material_admission_required_if_exact": candidate is not None,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        state[key] = False
    validate_state(state)
    return state


def validate_state(state: Mapping[str, Any]) -> None:
    if state.get("schema") != SCHEMA or state.get("parser_version") != PARSER_VERSION:
        raise ValueError("Digital Europe handoff schema/parser drift")
    if state.get("source_family") != "EU_DIRECT" or state.get("programme_family") != "DIGITAL_EUROPE":
        raise ValueError("Digital Europe handoff family drift")
    if state.get("authority_class") != "EU_COMMISSION_FUNDING_TENDERS":
        raise ValueError("Digital Europe handoff authority drift")
    mode = state.get("observation_state")
    if mode not in {CURRENT_MODE, OMITTED_SKIP_MODE}:
        raise ValueError("unsupported Digital Europe handoff state")
    target = state.get("target_reference")
    exact_required = state.get("exact_recheck_required") is True
    if exact_required != bool(target):
        raise ValueError("Digital Europe handoff target/exact mismatch")
    if mode == CURRENT_MODE and state.get("current_taxonomy_candidate") is not True:
        raise ValueError("Digital Europe current mode lost current candidate")
    if mode == OMITTED_SKIP_MODE:
        if state.get("current_taxonomy_candidate") is not False or target is not None or exact_required:
            raise ValueError("Digital Europe omission skip attempted exact handoff")
    if state.get("bounded_sample_omission_is_material_fact") is not False or state.get("closure_inference_authorized") is not False:
        raise ValueError("Digital Europe sample omission crossed material boundary")
    for key in MATERIAL_FLAGS:
        if state.get(key) is not False:
            raise ValueError(f"Digital Europe handoff attempted authorization: {key}")
    if state.get("publication_effect") != "NONE" or state.get("canonical_corpus_mutation") is not False:
        raise ValueError("Digital Europe handoff crossed publication boundary")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--taxonomy", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--run-id", default="digital-ft-handoff-live")
    args = parser.parse_args()
    taxonomy = json.loads(args.taxonomy.read_text(encoding="utf-8"))
    state = resolve_handoff(taxonomy, run_id=args.run_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "observation_state": state["observation_state"],
        "target_reference": state["target_reference"],
        "exact_recheck_required": state["exact_recheck_required"],
        "open_call_authorized": state["open_call_authorized"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
