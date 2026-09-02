#!/usr/bin/env python3
"""Bounded detail-level health-workforce reconciliation for VÂLCEA CLAR.

Consumes the already-validated Ministry of Health, Posturi.gov.ro and cross-source
context receipts. It binds source-specific publication/detail identities and
compares only explicit retained role/specialty language. Lexical compatibility is
newsroom follow-up context, never proof that two references describe the same
vacancy or staffing need.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

CONTRACT = "VALCEA_CLAR_HEALTH_WORKFORCE_DETAIL_RECONCILIATION_V1"
MINISTRY_SCHEMA = "MS_VALCEA_HEALTH_WORKFORCE_REFERENCE_V1"
POSTURI_SCHEMA = "POSTURI_GOV_VALCEA_REFERENCE_V1"
CONTEXT_SCHEMA = "VALCEA_CLAR_HEALTH_WORKFORCE_REFERENCE_CONTEXT_V1"
OBSERVATION_STATE = "DETAIL_ROLE_PUBLICATION_CONTEXT_NON_AUTHORIZING"

BOUNDARIES = {
    "material_fact_use": False,
    "same_vacancy_inference_authorized": False,
    "same_need_inference_authorized": False,
    "same_publication_inference_authorized": False,
    "dedupe_authorized": False,
    "current_vacancy_authorized": False,
    "deadline_authorized": False,
    "eligibility_authorized": False,
    "salary_authorized": False,
    "staffing_shortage_authorized": False,
    "service_capacity_authorized": False,
    "breaking_authorized": False,
    "fact_kernel_write_authorized": False,
    "editorial_writer_authorized": False,
    "publication_authorized": False,
    "distribution_authorized": False,
    "runtime_persistence_authorized": False,
}

GENERIC_TOKENS = {
    "anunt", "concurs", "rezultat", "rezultate", "rectificare", "erata",
    "spital", "spitalul", "judetean", "judeteanul", "urgenta", "valcea", "sju",
    "post", "posturi", "vacant", "vacante", "ocupare", "angajare",
    "medic", "medici", "specialist", "specialisti", "primar", "primari",
    "sectia", "sectie", "compartiment", "serviciu", "serviciul",
    "de", "din", "la", "pentru", "si", "al", "a", "ai", "ale", "nr",
}


def _normalize(value: Any) -> str:
    text = " ".join(str(value or "").split())
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def _hash_ok(value: Any) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", str(value or "")))


def _https_host(url: Any, hosts: set[str]) -> bool:
    parts = urlsplit(str(url or ""))
    return (
        parts.scheme == "https"
        and (parts.hostname or "").lower() in hosts
        and not parts.username
        and not parts.password
        and parts.port in (None, 443)
    )


def _role_tokens(title: Any) -> list[str]:
    tokens: list[str] = []
    for token in _normalize(title).split():
        if token in GENERIC_TOKENS or len(token) < 4 or token.isdigit():
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens[:12]


def _role_context(ministry_title: Any, posturi_title: Any) -> dict[str, Any]:
    left = _role_tokens(ministry_title)
    right = _role_tokens(posturi_title)
    overlap = sorted(set(left) & set(right))
    if overlap:
        state = "LEXICAL_ROLE_SPECIALTY_CONTEXT_OVERLAP_NON_AUTHORIZING"
    elif left and right:
        state = "EXPLICIT_ROLE_SPECIALTY_CONTEXT_DIFFERS_OR_NO_OVERLAP"
    else:
        state = "ROLE_SPECIALTY_CONTEXT_UNRESOLVED_FROM_RETAINED_TITLES"
    return {
        "state": state,
        "ministry_distinctive_tokens": left,
        "posturi_distinctive_tokens": right,
        "shared_distinctive_tokens": overlap,
        "lexical_overlap_observed": bool(overlap),
        "role_identity_match_inferred": False,
    }


def _validate_inputs(
    ministry: dict[str, Any],
    posturi: dict[str, Any],
    context: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if ministry.get("schema") != MINISTRY_SCHEMA or ministry.get("status") != "PASS":
        raise ValueError("ministry_receipt_invalid")
    if posturi.get("schema") != POSTURI_SCHEMA or posturi.get("status") != "PASS":
        raise ValueError("posturi_receipt_invalid")
    if context.get("schema") != CONTEXT_SCHEMA or context.get("status") != "PASS":
        raise ValueError("context_receipt_invalid")
    if context.get("observation_state") != "CROSS_SOURCE_REFERENCE_CONTEXT_NON_AUTHORIZING":
        raise ValueError("context_observation_state_invalid")

    for key in (
        "material_fact_use", "same_vacancy_inference_authorized",
        "same_need_inference_authorized", "dedupe_authorized",
        "fact_kernel_write_authorized", "editorial_writer_authorized",
        "publication_authorized", "distribution_authorized",
        "runtime_persistence_authorized",
    ):
        if context.get(key) is not False:
            raise ValueError(f"context_boundary_drift:{key}")

    ministry_refs = ministry.get("references")
    posturi_refs = posturi.get("references")
    follow_up = context.get("follow_up_candidates")
    if not isinstance(ministry_refs, list) or not 1 <= len(ministry_refs) <= 16:
        raise ValueError("ministry_reference_inventory_invalid")
    if not isinstance(posturi_refs, list) or not 0 <= len(posturi_refs) <= 16:
        raise ValueError("posturi_reference_inventory_invalid")
    if not isinstance(follow_up, list) or len(follow_up) > 16:
        raise ValueError("context_follow_up_inventory_invalid")

    for ref in ministry_refs:
        if not isinstance(ref, dict):
            raise ValueError("ministry_reference_invalid")
        if not _https_host(ref.get("url"), {"ms.ro", "www.ms.ro"}):
            raise ValueError("ministry_reference_url_invalid")
        if not _hash_ok(ref.get("source_page_sha256")) or not _hash_ok(ref.get("evidence_sha256")):
            raise ValueError("ministry_reference_hash_invalid")

    posturi_by_evidence: dict[str, dict[str, Any]] = {}
    for ref in posturi_refs:
        if not isinstance(ref, dict):
            raise ValueError("posturi_reference_invalid")
        if not _https_host(ref.get("url"), {"posturi.gov.ro", "www.posturi.gov.ro"}):
            raise ValueError("posturi_reference_url_invalid")
        for key in ("detail_sha256", "evidence_sha256"):
            if not _hash_ok(ref.get(key)):
                raise ValueError(f"posturi_reference_hash_invalid:{key}")
        posturi_by_evidence[str(ref["evidence_sha256"])] = ref

    resolved_follow_up: list[dict[str, Any]] = []
    for item in follow_up:
        if not isinstance(item, dict):
            raise ValueError("follow_up_candidate_invalid")
        if item.get("candidate_state") != "EXACT_DETAIL_RECONCILIATION_REQUIRED_NON_AUTHORIZING":
            raise ValueError("follow_up_candidate_state_invalid")
        for key in ("same_institution_inferred", "same_vacancy_inferred", "same_need_inferred", "dedupe_authorized"):
            if item.get(key) is not False:
                raise ValueError(f"follow_up_boundary_drift:{key}")
        compact = item.get("posturi_reference")
        if not isinstance(compact, dict) or not _hash_ok(compact.get("evidence_sha256")):
            raise ValueError("follow_up_posturi_reference_invalid")
        raw = posturi_by_evidence.get(str(compact["evidence_sha256"]))
        if raw is None:
            raise ValueError("follow_up_posturi_reference_not_bound_to_raw_receipt")
        if str(raw.get("url")) != str(compact.get("url")):
            raise ValueError("follow_up_posturi_url_binding_mismatch")
        if raw.get("institution_identity_state") != "EXPLICIT_FIRST_PARTY_DETAIL_SUMMARY":
            raise ValueError("follow_up_posturi_institution_not_explicit")
        if not _hash_ok(raw.get("institution_evidence_sha256")):
            raise ValueError("follow_up_posturi_institution_evidence_invalid")
        resolved_follow_up.append(raw)

    return ministry_refs, posturi_refs, resolved_follow_up


def build_reconciliation(
    ministry: dict[str, Any],
    posturi: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    ministry_refs, posturi_refs, follow_up_refs = _validate_inputs(ministry, posturi, context)

    pairs: list[dict[str, Any]] = []
    overlap_count = 0
    unresolved_count = 0
    no_overlap_count = 0

    for posturi_ref in follow_up_refs:
        for ministry_ref in ministry_refs:
            role = _role_context(ministry_ref.get("title"), posturi_ref.get("title"))
            if role["state"] == "LEXICAL_ROLE_SPECIALTY_CONTEXT_OVERLAP_NON_AUTHORIZING":
                overlap_count += 1
            elif role["state"] == "ROLE_SPECIALTY_CONTEXT_UNRESOLVED_FROM_RETAINED_TITLES":
                unresolved_count += 1
            else:
                no_overlap_count += 1
            pairs.append({
                "pair_state": role["state"],
                "institution_context": "SJU_VALCEA_EXPLICIT_IN_BOTH_SOURCE_CONTRACTS_NON_AUTHORIZING",
                "role_specialty_context": role,
                "publication_identity_context": {
                    "ministry_url": ministry_ref.get("url"),
                    "ministry_evidence_sha256": ministry_ref.get("evidence_sha256"),
                    "posturi_url": posturi_ref.get("url"),
                    "posturi_detail_sha256": posturi_ref.get("detail_sha256"),
                    "posturi_evidence_sha256": posturi_ref.get("evidence_sha256"),
                    "source_specific_publication_identities_bound": True,
                    "shared_cross_source_publication_identifier_retained": False,
                    "same_publication_inferred": False,
                },
                "same_vacancy_inferred": False,
                "same_need_inferred": False,
                "dedupe_authorized": False,
                "required_before_any_same_vacancy_conclusion": [
                    "explicit_shared_first_party_vacancy_identifier_or_equivalent_identity",
                    "role_specialty_identity_from_first_party_detail_evidence",
                    "publication_or_event_identity_reconciled_across_first_party_details",
                ],
            })

    if not follow_up_refs:
        state = "NO_EXPLICIT_SJU_POSTURI_FOLLOW_UP_CANDIDATE"
    elif overlap_count:
        state = "ROLE_SPECIALTY_LEXICAL_CONTEXT_OBSERVED_NON_AUTHORIZING"
    elif unresolved_count:
        state = "ROLE_SPECIALTY_DETAIL_EVIDENCE_STILL_REQUIRED"
    else:
        state = "NO_ROLE_SPECIALTY_LEXICAL_OVERLAP_IN_RETAINED_TITLES"

    fingerprint_basis = {
        "ministry_run_id": ministry.get("run_id"),
        "posturi_run_id": posturi.get("run_id"),
        "context_run_id": context.get("run_id"),
        "context_source_fingerprint_sha256": context.get("source_fingerprint_sha256"),
        "ministry_evidence": [r.get("evidence_sha256") for r in ministry_refs],
        "posturi_evidence": [r.get("evidence_sha256") for r in posturi_refs],
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_basis, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    payload = {
        "schema": CONTRACT,
        "status": "PASS",
        "reconciliation_state": state,
        "observation_state": OBSERVATION_STATE,
        "coverage": {
            "ministry_reference_count": len(ministry_refs),
            "posturi_reference_count": len(posturi_refs),
            "explicit_sju_follow_up_reference_count": len(follow_up_refs),
            "pair_count": len(pairs),
            "lexical_role_specialty_overlap_pair_count": overlap_count,
            "role_specialty_unresolved_pair_count": unresolved_count,
            "no_role_specialty_overlap_pair_count": no_overlap_count,
            "bounded_non_exhaustive": True,
        },
        "pair_candidates": pairs[:256],
        "source_fingerprint_sha256": fingerprint,
        "interpretation": (
            "SOURCE_SPECIFIC_DETAIL_IDENTITIES_AND_EXPLICIT_TITLE_LANGUAGE_ONLY;"
            "LEXICAL_OVERLAP_IS_FOLLOW_UP_CONTEXT_NOT_VACANCY_IDENTITY"
        ),
        "required_next_evidence": (
            "MINISTRY_DETAIL_LEVEL_ROLE_SPECIALTY_EVIDENCE_AND_SHARED_FIRST_PARTY_VACANCY_IDENTITY_"
            "BEFORE_ANY_DEDUPE_OR_SAME_VACANCY_CONCLUSION"
        ),
        **BOUNDARIES,
    }
    stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["run_id"] = hashlib.sha256(stable).hexdigest()[:24]
    return payload


def _fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    h = lambda ch: ch * 64
    ministry = {
        "schema": MINISTRY_SCHEMA, "status": "PASS", "run_id": "m1",
        "references": [{
            "title": "Anunț concurs - Spitalul Județean de Urgență Vâlcea - psihiatrie pediatrică",
            "url": "https://www.ms.ro/ro/minister/cariera-medici/anunt-sju-valcea/",
            "source_page_sha256": h("a"), "evidence_sha256": h("b"),
        }],
    }
    posturi_ref = {
        "title": "Medic specialist psihiatrie pediatrică",
        "url": "https://posturi.gov.ro/joburi/medic-specialist-psihiatrie-pediatrica/",
        "detail_sha256": h("c"), "evidence_sha256": h("d"),
        "institution_identity_state": "EXPLICIT_FIRST_PARTY_DETAIL_SUMMARY",
        "institution_name": "Spitalul Județean de Urgență Vâlcea",
        "institution_evidence_sha256": h("e"),
    }
    posturi = {
        "schema": POSTURI_SCHEMA, "status": "PASS", "run_id": "p1",
        "references": [posturi_ref],
    }
    context = {
        "schema": CONTEXT_SCHEMA, "status": "PASS", "run_id": "c1",
        "source_fingerprint_sha256": h("f"),
        "observation_state": "CROSS_SOURCE_REFERENCE_CONTEXT_NON_AUTHORIZING",
        "follow_up_candidates": [{
            "candidate_state": "EXACT_DETAIL_RECONCILIATION_REQUIRED_NON_AUTHORIZING",
            "same_institution_explicit_in_both_source_contracts": True,
            "same_institution_inferred": False,
            "same_vacancy_inferred": False,
            "same_need_inferred": False,
            "dedupe_authorized": False,
            "posturi_reference": {"url": posturi_ref["url"], "evidence_sha256": posturi_ref["evidence_sha256"]},
        }],
        "material_fact_use": False,
        "same_vacancy_inference_authorized": False,
        "same_need_inference_authorized": False,
        "dedupe_authorized": False,
        "fact_kernel_write_authorized": False,
        "editorial_writer_authorized": False,
        "publication_authorized": False,
        "distribution_authorized": False,
        "runtime_persistence_authorized": False,
    }
    return ministry, posturi, context


def self_test() -> None:
    ministry, posturi, context = _fixture()
    result = build_reconciliation(ministry, posturi, context)
    assert result["reconciliation_state"] == "ROLE_SPECIALTY_LEXICAL_CONTEXT_OBSERVED_NON_AUTHORIZING"
    assert result["coverage"]["pair_count"] == 1
    assert result["coverage"]["lexical_role_specialty_overlap_pair_count"] == 1
    pair = result["pair_candidates"][0]
    assert pair["role_specialty_context"]["shared_distinctive_tokens"] == ["pediatrica", "psihiatrie"]
    assert pair["same_vacancy_inferred"] is False
    assert pair["publication_identity_context"]["same_publication_inferred"] is False

    ministry2, posturi2, context2 = _fixture()
    ministry2["references"][0]["title"] = "Anunț concurs - Spitalul Județean de Urgență Vâlcea"
    unresolved = build_reconciliation(ministry2, posturi2, context2)
    assert unresolved["reconciliation_state"] == "ROLE_SPECIALTY_DETAIL_EVIDENCE_STILL_REQUIRED"
    assert unresolved["coverage"]["role_specialty_unresolved_pair_count"] == 1

    bad = json.loads(json.dumps(context))
    bad["dedupe_authorized"] = True
    try:
        build_reconciliation(ministry, posturi, bad)
    except ValueError as exc:
        assert "context_boundary_drift" in str(exc)
    else:
        raise AssertionError("authorizing context must fail closed")
    print("Health workforce detail reconciliation self-test: PASS")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"input_not_object:{path}")
    return value


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--ministry", type=Path)
    parser.add_argument("--posturi", type=Path)
    parser.add_argument("--context", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.self_test:
        self_test()
        return 0
    if args.ministry is None or args.posturi is None or args.context is None:
        parser.error("--ministry, --posturi and --context are required")
    try:
        result = build_reconciliation(_load(args.ministry), _load(args.posturi), _load(args.context))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"FAIL: {exc}") from exc
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    coverage = result["coverage"]
    print(
        "Health workforce detail reconciliation: PASS "
        f"({coverage['pair_count']} pairs / "
        f"{coverage['lexical_role_specialty_overlap_pair_count']} lexical role overlaps / "
        f"{coverage['role_specialty_unresolved_pair_count']} unresolved; "
        f"state={result['reconciliation_state']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
