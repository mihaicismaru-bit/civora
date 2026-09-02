#!/usr/bin/env python3
"""Resolve a bounded CERV exact-recheck target from official structured discovery.

No discovery result or omission authorizes a material call fact. A verified
structured discovery pointer may request a later fresh exact readback. If the
current bounded discovery omits CERV, a validated previous exact receipt may be
used only as an identity pointer for a fresh exact authority recheck. If neither
exists, the lane skips non-authorizing and never infers absence or closure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from typing import Any, Mapping

from eu_direct_cerv_ft_discovery import validate_receipt, validate_reference
from eu_direct_cerv_ft_exact import validate_evidence

SCHEMA = "PARTENER_EU_CERV_FT_HANDOFF_V1"
PARSER_VERSION = "EU_DIRECT_CERV_FT_HANDOFF_V2"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "CERV"
AUTHORITY_CLASS = "EU_COMMISSION_FUNDING_TENDERS"
CURRENT_MODE = "CURRENT_OFFICIAL_STRUCTURED_CERV_IDENTITY_EXACT_RECHECK_REQUIRED"
OMITTED_RECHECK_MODE = "OFFICIAL_STRUCTURED_DISCOVERY_OMITTED_PREVIOUS_IDENTITY_EXACT_RECHECK_REQUIRED"
OMITTED_SKIP_MODE = "OFFICIAL_STRUCTURED_DISCOVERY_NO_SAFE_CERV_IDENTITY_NON_AUTHORIZING_SKIP"
MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
    "call_alert_authorized",
    "canonical_corpus_mutation",
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
    discovery: Mapping[str, Any],
    *,
    previous: Mapping[str, Any] | None = None,
    run_id: str = "cerv-ft-handoff-live",
) -> dict[str, Any]:
    discovery_obj = dict(discovery)
    validate_receipt(discovery_obj)

    previous_obj: dict[str, Any] | None = None
    if previous is not None:
        previous_obj = dict(previous)
        validate_evidence(previous_obj)

    selected = discovery_obj.get("selected_candidate")
    if selected is not None:
        target = validate_reference(str(discovery_obj.get("selected_reference") or ""))
        state = CURRENT_MODE
        exact_required = True
        current_discovery_candidate = True
    elif previous_obj is not None:
        target = validate_reference(str(previous_obj.get("reference") or ""))
        state = OMITTED_RECHECK_MODE
        exact_required = True
        current_discovery_candidate = False
    else:
        target = None
        state = OMITTED_SKIP_MODE
        exact_required = False
        current_discovery_candidate = False

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
        "discovery_sha256": sha256_json(discovery_obj),
        "discovery_observation_state": discovery_obj.get("observation_state"),
        "discovery_selected_candidate": selected,
        "current_discovery_candidate": current_discovery_candidate,
        "target_reference": target,
        "exact_recheck_required": exact_required,
        "previous_evidence_available": previous_obj is not None,
        "previous_evidence_sha256": sha256_json(previous_obj) if previous_obj is not None else None,
        "previous_reference": previous_obj.get("reference") if previous_obj is not None else None,
        "previous_same_identity": previous_same_identity,
        "bounded_discovery_absence_is_material_fact": False,
        "closure_inference_authorized": False,
        "semantic_reconciliation_required_if_exact": exact_required,
        "field_scoped_material_admission_required_if_exact": exact_required,
        "publication_effect": "NONE",
    }
    for key in MATERIAL_FLAGS:
        receipt[key] = False
    validate(receipt)
    return receipt


def validate(receipt: Mapping[str, Any]) -> None:
    if receipt.get("schema") != SCHEMA or receipt.get("parser_version") != PARSER_VERSION:
        raise ValueError("CERV F&T handoff schema/parser drift")
    if receipt.get("source_family") != SOURCE_FAMILY or receipt.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("CERV F&T handoff family drift")
    if receipt.get("authority_class") != AUTHORITY_CLASS:
        raise ValueError("CERV F&T handoff authority drift")
    mode = receipt.get("observation_state")
    if mode not in {CURRENT_MODE, OMITTED_RECHECK_MODE, OMITTED_SKIP_MODE}:
        raise ValueError("CERV F&T handoff state unsupported")
    target = receipt.get("target_reference")
    required = receipt.get("exact_recheck_required") is True
    if required != bool(target):
        raise ValueError("CERV F&T handoff target/exact mismatch")
    if target is not None:
        validate_reference(str(target))

    previous_available = receipt.get("previous_evidence_available") is True
    previous_same_identity = receipt.get("previous_same_identity") is True
    previous_reference = receipt.get("previous_reference")
    previous_digest = receipt.get("previous_evidence_sha256")
    if previous_available:
        validate_reference(str(previous_reference or ""))
        if not isinstance(previous_digest, str) or len(previous_digest) != 64 or any(ch not in "0123456789abcdef" for ch in previous_digest):
            raise ValueError("CERV F&T handoff previous evidence binding invalid")
    elif previous_reference is not None or previous_digest is not None or previous_same_identity:
        raise ValueError("CERV F&T handoff claims previous details without validated evidence")

    if mode == CURRENT_MODE:
        selected = receipt.get("discovery_selected_candidate")
        if not isinstance(selected, Mapping):
            raise ValueError("CERV F&T handoff current mode lost structured discovery candidate")
        if selected.get("identifier") != target:
            raise ValueError("CERV F&T handoff current candidate identity mismatch")
        if receipt.get("current_discovery_candidate") is not True or not required:
            raise ValueError("CERV F&T handoff current candidate did not require exact recheck")
        expected_same = previous_available and previous_reference == target
        if previous_same_identity is not expected_same:
            raise ValueError("CERV F&T handoff current/previous identity binding mismatch")
    if mode == OMITTED_RECHECK_MODE:
        if receipt.get("discovery_selected_candidate") is not None or receipt.get("current_discovery_candidate") is not False:
            raise ValueError("CERV F&T handoff omission recheck unexpectedly has current discovery candidate")
        if not previous_available or not previous_same_identity or previous_reference != target or not required:
            raise ValueError("CERV F&T handoff omission recheck lacks validated previous identity pointer")
    if mode == OMITTED_SKIP_MODE:
        if receipt.get("discovery_selected_candidate") is not None or receipt.get("current_discovery_candidate") is not False:
            raise ValueError("CERV F&T handoff omission skip unexpectedly has current discovery candidate")
        if previous_available or previous_same_identity or target is not None or required:
            raise ValueError("CERV F&T handoff omission attempted unsafe exact target")

    if receipt.get("bounded_discovery_absence_is_material_fact") is not False or receipt.get("closure_inference_authorized") is not False:
        raise ValueError("CERV F&T handoff attempted absence/closure inference")
    if receipt.get("semantic_reconciliation_required_if_exact") is not required:
        raise ValueError("CERV F&T handoff semantic reconciliation gate mismatch")
    if receipt.get("field_scoped_material_admission_required_if_exact") is not required:
        raise ValueError("CERV F&T handoff material admission gate mismatch")
    for key in MATERIAL_FLAGS:
        if receipt.get(key) is not False:
            raise ValueError(f"CERV F&T handoff attempted authorization: {key}")
    if receipt.get("publication_effect") != "NONE":
        raise ValueError("CERV F&T handoff crossed publication boundary")
    digest = str(receipt.get("discovery_sha256") or "")
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("CERV F&T handoff lacks immutable discovery binding")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discovery", required=True, type=pathlib.Path)
    parser.add_argument("--previous", type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--run-id", default="cerv-ft-handoff-live")
    args = parser.parse_args()
    discovery = json.loads(args.discovery.read_text(encoding="utf-8"))
    previous = load_previous(args.previous)
    receipt = resolve(discovery, previous=previous, run_id=args.run_id)
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
