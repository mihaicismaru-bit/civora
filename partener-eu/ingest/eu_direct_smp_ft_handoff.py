#!/usr/bin/env python3
"""Resolve one bounded Single Market Programme exact-handoff target without inferring material status.

The programme-wide Funding & Tenders sample is explicitly non-exhaustive. If it
contains an SMP candidate, that current discovery pointer wins. If the bounded
sample omits the family, a validated previous exact SMP receipt may be used only
as a pointer for a fresh exact authority recheck. If neither exists, the family
is skipped for this run with a non-authorizing omission receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from typing import Any, Mapping

from eu_direct_smp_ft_exact import select_smp_candidate, validate_evidence

SCHEMA = "PARTENER_EU_SMP_FT_HANDOFF_V1"
PARSER_VERSION = "EU_DIRECT_SMP_FT_HANDOFF_V2"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "SINGLE_MARKET_PROGRAMME"
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


def resolve(
    taxonomy: Mapping[str, Any],
    *,
    previous: Mapping[str, Any] | None = None,
    run_id: str = "smp-ft-handoff-live",
) -> dict[str, Any]:
    if taxonomy.get("schema") != "PARTENER_EU_FT_PROGRAMME_TAXONOMY_V1":
        raise ValueError("unexpected programme taxonomy schema")
    if taxonomy.get("market_intelligence_only") is not True or taxonomy.get("material_fact_use") is not False:
        raise ValueError("programme taxonomy crossed discovery boundary")

    previous_obj: dict[str, Any] | None = None
    if previous is not None:
        previous_obj = dict(previous)
        validate_evidence(previous_obj)

    try:
        selected = select_smp_candidate(taxonomy)
    except ValueError as exc:
        if str(exc) != "programme taxonomy contains no Single Market Programme candidate":
            raise
        selected = None

    if selected is not None:
        state = CURRENT_MODE
        target = selected["identifier"]
        required = True
        current_taxonomy_candidate = True
    elif previous_obj is not None:
        state = OMITTED_RECHECK_MODE
        target = str(previous_obj["reference"])
        required = True
        current_taxonomy_candidate = False
    else:
        state = OMITTED_SKIP_MODE
        target = None
        required = False
        current_taxonomy_candidate = False

    previous_same_identity = bool(
        previous_obj is not None
        and target is not None
        and str(previous_obj.get("reference")) == target
    )
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": state,
        "taxonomy_sha256": sha256_json(taxonomy),
        "current_taxonomy_candidate": current_taxonomy_candidate,
        "current_source_candidate": selected,
        "previous_evidence_available": previous_obj is not None,
        "previous_evidence_sha256": sha256_json(previous_obj) if previous_obj is not None else None,
        "previous_reference": previous_obj.get("reference") if previous_obj is not None else None,
        "previous_same_identity": previous_same_identity,
        "target_reference": target,
        "exact_recheck_required": required,
        "bounded_sample_omission_is_material_fact": False,
        "closure_inference_authorized": False,
        "semantic_reconciliation_required_if_exact": required,
        "field_scoped_material_admission_required_if_exact": required,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        receipt[key] = False
    validate(receipt)
    return receipt


def validate(receipt: Mapping[str, Any]) -> None:
    if receipt.get("schema") != SCHEMA or receipt.get("parser_version") != PARSER_VERSION:
        raise ValueError("Single Market Programme handoff schema/parser drift")
    if receipt.get("source_family") != SOURCE_FAMILY or receipt.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("Single Market Programme handoff family drift")
    if receipt.get("authority_class") != AUTHORITY_CLASS:
        raise ValueError("Single Market Programme handoff authority drift")
    mode = receipt.get("observation_state")
    if mode not in {CURRENT_MODE, OMITTED_RECHECK_MODE, OMITTED_SKIP_MODE}:
        raise ValueError("Single Market Programme handoff state unsupported")
    target = receipt.get("target_reference")
    exact_required = receipt.get("exact_recheck_required") is True
    if exact_required != bool(target):
        raise ValueError("Single Market Programme handoff target/exact mismatch")
    if mode == CURRENT_MODE and receipt.get("current_taxonomy_candidate") is not True:
        raise ValueError("Single Market Programme current mode lost current candidate")
    if mode == OMITTED_RECHECK_MODE:
        if receipt.get("current_taxonomy_candidate") is not False or receipt.get("previous_evidence_available") is not True:
            raise ValueError("Single Market Programme omission recheck lacks validated previous pointer")
        if receipt.get("previous_same_identity") is not True:
            raise ValueError("Single Market Programme omission recheck previous identity mismatch")
    if mode == OMITTED_SKIP_MODE:
        if receipt.get("current_taxonomy_candidate") is not False or receipt.get("previous_evidence_available") is not False:
            raise ValueError("Single Market Programme omission skip unexpectedly has a candidate")
        if target is not None or exact_required:
            raise ValueError("Single Market Programme omission skip attempted exact handoff")
    if receipt.get("bounded_sample_omission_is_material_fact") is not False or receipt.get("closure_inference_authorized") is not False:
        raise ValueError("Single Market Programme sample omission crossed material boundary")
    for key in MATERIAL_FLAGS:
        if receipt.get(key) is not False:
            raise ValueError(f"Single Market Programme handoff attempted authorization: {key}")
    if receipt.get("publication_effect") != "NONE" or receipt.get("canonical_corpus_mutation") is not False:
        raise ValueError("Single Market Programme handoff crossed publication boundary")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--taxonomy", required=True, type=pathlib.Path)
    parser.add_argument("--previous", type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--run-id", default="smp-ft-handoff-live")
    args = parser.parse_args()
    taxonomy = json.loads(args.taxonomy.read_text(encoding="utf-8"))
    previous = load_previous(args.previous)
    receipt = resolve(taxonomy, previous=previous, run_id=args.run_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "observation_state": receipt["observation_state"],
        "target_reference": receipt["target_reference"],
        "exact_recheck_required": receipt["exact_recheck_required"],
        "previous_same_identity": receipt["previous_same_identity"],
        "open_call_authorized": receipt["open_call_authorized"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
