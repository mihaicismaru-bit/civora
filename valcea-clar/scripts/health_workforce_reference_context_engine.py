#!/usr/bin/env python3
"""Fail-closed cross-source health-workforce context for VÂLCEA CLAR.

Consumes already-produced first-party reference receipts from the Ministry of
Health career lane and Posturi.gov.ro Vâlcea lane. It may surface bounded
institution-level newsroom context and exact-detail follow-up candidates, but it
never infers same vacancy, same staffing need, deduplicates evidence, or
authorizes material facts, Fact Kernel writes, Editorial Writer use, publication
or distribution.

The Ministry receipt is SJU Vâlcea-specific by its upstream contract.
Posturi.gov.ro institution identity is admitted only when the upstream adapter
retains an explicit first-party detail-summary institution with its own evidence
hash. Even an explicit same-institution signal remains non-authorizing.
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

CONTRACT = "VALCEA_CLAR_HEALTH_WORKFORCE_REFERENCE_CONTEXT_V1"
MS_SCHEMA = "MS_VALCEA_HEALTH_WORKFORCE_REFERENCE_V1"
MS_SOURCE_FAMILY = "MS_HEALTH_WORKFORCE"
MS_AUTHORITY_CLASS = "FIRST_PARTY_HEALTH_MINISTRY_CAREER_REFERENCE"
MS_ALLOWED_HOSTS = {"ms.ro", "www.ms.ro"}
MS_PATH_PREFIX = "/ro/minister/cariera-medici/"

POSTURI_SCHEMA = "POSTURI_GOV_VALCEA_REFERENCE_V1"
POSTURI_SOURCE_FAMILY = "POSTURI_GOV_VALCEA"
POSTURI_AUTHORITY_CLASS = "FIRST_PARTY_GOVERNMENT_PUBLIC_JOBS_REFERENCE"
POSTURI_ALLOWED_HOSTS = {"posturi.gov.ro", "www.posturi.gov.ro"}
POSTURI_PATH_PREFIX = "/joburi/"
POSTURI_HEALTH_TOPIC = "PUBLIC_JOBS_HEALTH_REFERENCE"
POSTURI_TOPICS = {
    POSTURI_HEALTH_TOPIC,
    "PUBLIC_JOBS_ADMINISTRATION_REFERENCE",
    "PUBLIC_JOBS_EDUCATION_REFERENCE",
    "PUBLIC_JOBS_PUBLIC_SERVICE_REFERENCE",
    "PUBLIC_JOBS_OTHER_REFERENCE",
}
POSTURI_INSTITUTION_EXPLICIT = "EXPLICIT_FIRST_PARTY_DETAIL_SUMMARY"
POSTURI_INSTITUTION_UNRESOLVED = "UNRESOLVED_FROM_FIRST_PARTY_DETAIL_SUMMARY"
OBSERVATION_STATE = "REFERENCE_ONLY_NON_AUTHORIZING"

SOURCE_NON_AUTHORIZING_FLAGS = {
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
}

ENGINE_BOUNDARIES = {
    "material_fact_use": False,
    "same_vacancy_inference_authorized": False,
    "same_need_inference_authorized": False,
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

STATE_EXPLICIT_SAME_INSTITUTION = "EXPLICIT_SAME_INSTITUTION_REFERENCE_CONTEXT_NON_AUTHORIZING"
STATE_COUNTY_CONTEXT = "COUNTY_HEALTH_WORKFORCE_CONTEXT_ONLY_INSTITUTION_UNRESOLVED"
STATE_MINISTRY_ONLY = "MINISTRY_SJU_ONLY_NO_BOUNDED_POSTURI_HEALTH_REFERENCE"


def _normalize(value: Any) -> str:
    text = " ".join(str(value or "").split())
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def _explicit_sju_valcea(value: Any) -> bool:
    text = _normalize(value)
    aliases = (
        "spitalul judetean de urgenta valcea",
        "spital judetean de urgenta valcea",
        "sju valcea",
    )
    return any(alias in text for alias in aliases)


def _hash_ok(value: Any) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", str(value or "")))


def _require_source_boundaries(payload: dict[str, Any], *, extra_false: Iterable[str] = ()) -> None:
    for key, expected in SOURCE_NON_AUTHORIZING_FLAGS.items():
        if payload.get(key) is not expected:
            raise ValueError(f"source_authorization_boundary_drift:{key}")
    for key in extra_false:
        if payload.get(key) is not False:
            raise ValueError(f"source_authorization_boundary_drift:{key}")


def _validate_url(url: Any, *, hosts: set[str], path_prefix: str) -> None:
    parts = urlsplit(str(url or ""))
    if parts.scheme != "https" or (parts.hostname or "").lower() not in hosts:
        raise ValueError("source_reference_url_identity_invalid")
    if parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError("source_reference_url_authority_invalid")
    if not parts.path.startswith(path_prefix):
        raise ValueError("source_reference_path_invalid")


def _validate_ministry(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("schema") != MS_SCHEMA:
        raise ValueError("ministry_schema_mismatch")
    if payload.get("status") != "PASS":
        raise ValueError("ministry_source_not_pass")
    if payload.get("source_family") != MS_SOURCE_FAMILY:
        raise ValueError("ministry_source_family_mismatch")
    if payload.get("authority_class") != MS_AUTHORITY_CLASS:
        raise ValueError("ministry_authority_class_mismatch")
    if payload.get("observation_state") != OBSERVATION_STATE:
        raise ValueError("ministry_observation_state_mismatch")
    _require_source_boundaries(
        payload,
        extra_false=("staffing_level_authorized", "treatment_availability_authorized"),
    )

    references = payload.get("references")
    if not isinstance(references, list) or len(references) > 16:
        raise ValueError("ministry_reference_inventory_invalid")
    if payload.get("reference_count") != len(references):
        raise ValueError("ministry_reference_count_mismatch")

    validated: list[dict[str, Any]] = []
    for ref in references:
        if not isinstance(ref, dict):
            raise ValueError("ministry_reference_invalid")
        if ref.get("source_family") != MS_SOURCE_FAMILY:
            raise ValueError("ministry_reference_source_family_mismatch")
        if ref.get("authority_class") != MS_AUTHORITY_CLASS:
            raise ValueError("ministry_reference_authority_mismatch")
        if ref.get("observation_state") != OBSERVATION_STATE:
            raise ValueError("ministry_reference_observation_state_mismatch")
        if not _explicit_sju_valcea(ref.get("title")):
            raise ValueError("ministry_reference_lost_explicit_sju_identity")
        _validate_url(ref.get("url"), hosts=MS_ALLOWED_HOSTS, path_prefix=MS_PATH_PREFIX)
        if not _hash_ok(ref.get("source_page_sha256")) or not _hash_ok(ref.get("evidence_sha256")):
            raise ValueError("ministry_reference_hash_invalid")
        validated.append(ref)
    return validated


def _validate_posturi(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("schema") != POSTURI_SCHEMA:
        raise ValueError("posturi_schema_mismatch")
    if payload.get("status") != "PASS":
        raise ValueError("posturi_source_not_pass")
    if payload.get("source_family") != POSTURI_SOURCE_FAMILY:
        raise ValueError("posturi_source_family_mismatch")
    if payload.get("authority_class") != POSTURI_AUTHORITY_CLASS:
        raise ValueError("posturi_authority_class_mismatch")
    if payload.get("observation_state") != OBSERVATION_STATE:
        raise ValueError("posturi_observation_state_mismatch")
    if payload.get("institution_identity_contract") != "EXPLICIT_FIRST_PARTY_DETAIL_SUMMARY_ONLY":
        raise ValueError("posturi_institution_identity_contract_mismatch")
    _require_source_boundaries(
        payload,
        extra_false=(
            "institution_status_authorized",
            "same_vacancy_inference_authorized",
            "same_need_inference_authorized",
            "dedupe_authorized",
        ),
    )

    references = payload.get("references")
    if not isinstance(references, list) or len(references) > 16:
        raise ValueError("posturi_reference_inventory_invalid")
    if payload.get("reference_count") != len(references):
        raise ValueError("posturi_reference_count_mismatch")

    validated: list[dict[str, Any]] = []
    for ref in references:
        if not isinstance(ref, dict):
            raise ValueError("posturi_reference_invalid")
        if ref.get("source_family") != POSTURI_SOURCE_FAMILY:
            raise ValueError("posturi_reference_source_family_mismatch")
        if ref.get("authority_class") != POSTURI_AUTHORITY_CLASS:
            raise ValueError("posturi_reference_authority_mismatch")
        if ref.get("observation_state") != OBSERVATION_STATE:
            raise ValueError("posturi_reference_observation_state_mismatch")
        if ref.get("topic_class") not in POSTURI_TOPICS:
            raise ValueError("posturi_reference_topic_unknown")
        _validate_url(ref.get("url"), hosts=POSTURI_ALLOWED_HOSTS, path_prefix=POSTURI_PATH_PREFIX)
        for key in ("index_sha256", "detail_sha256", "evidence_sha256"):
            if not _hash_ok(ref.get(key)):
                raise ValueError(f"posturi_reference_hash_invalid:{key}")

        identity_state = ref.get("institution_identity_state")
        if identity_state == POSTURI_INSTITUTION_EXPLICIT:
            if not str(ref.get("institution_name") or "").strip():
                raise ValueError("posturi_explicit_institution_name_missing")
            if not _hash_ok(ref.get("institution_evidence_sha256")):
                raise ValueError("posturi_explicit_institution_hash_invalid")
        elif identity_state == POSTURI_INSTITUTION_UNRESOLVED:
            if ref.get("institution_name") is not None or ref.get("institution_evidence_sha256") is not None:
                raise ValueError("posturi_unresolved_institution_leaked_asserted_identity")
        else:
            raise ValueError("posturi_institution_identity_state_unknown")
        validated.append(ref)
    return validated


def _posturi_explicit_sju(ref: dict[str, Any]) -> bool:
    return (
        ref.get("institution_identity_state") == POSTURI_INSTITUTION_EXPLICIT
        and _explicit_sju_valcea(ref.get("institution_name"))
    )


def _compact_reference(ref: dict[str, Any], *, source: str) -> dict[str, Any]:
    item = {
        "source": source,
        "title": " ".join(str(ref.get("title") or "").split()),
        "url": ref.get("url"),
        "topic_class": ref.get("topic_class"),
        "evidence_sha256": ref.get("evidence_sha256"),
    }
    if source == MS_SOURCE_FAMILY:
        item["source_page_sha256"] = ref.get("source_page_sha256")
    else:
        item["detail_sha256"] = ref.get("detail_sha256")
        item["institution_name"] = ref.get("institution_name")
        item["institution_identity_state"] = ref.get("institution_identity_state")
        item["institution_evidence_sha256"] = ref.get("institution_evidence_sha256")
    return item


def build_context(ministry: dict[str, Any], posturi: dict[str, Any]) -> dict[str, Any]:
    ministry_refs = _validate_ministry(ministry)
    posturi_refs = _validate_posturi(posturi)
    posturi_health = [ref for ref in posturi_refs if ref.get("topic_class") == POSTURI_HEALTH_TOPIC]
    posturi_explicit_sju = [ref for ref in posturi_health if _posturi_explicit_sju(ref)]
    posturi_explicit_sju_title = [ref for ref in posturi_health if _explicit_sju_valcea(ref.get("title"))]

    if posturi_explicit_sju:
        state = STATE_EXPLICIT_SAME_INSTITUTION
    elif posturi_health:
        state = STATE_COUNTY_CONTEXT
    else:
        state = STATE_MINISTRY_ONLY

    follow_up = []
    for ref in posturi_explicit_sju[:16]:
        follow_up.append(
            {
                "candidate_state": "EXACT_DETAIL_RECONCILIATION_REQUIRED_NON_AUTHORIZING",
                "institution_identity": "SJU_VALCEA_EXPLICIT_IN_POSTURI_FIRST_PARTY_DETAIL_SUMMARY",
                "posturi_reference": _compact_reference(ref, source=POSTURI_SOURCE_FAMILY),
                "ministry_reference_count": len(ministry_refs),
                "same_institution_explicit_in_both_source_contracts": True,
                "same_institution_inferred": False,
                "same_vacancy_inferred": False,
                "same_need_inferred": False,
                "dedupe_authorized": False,
                "missing_before_any_same_vacancy_conclusion": [
                    "shared_exact_vacancy_identifier_or_equivalent_first_party_identity",
                    "detail_level_role_specialty_identity_reconciliation",
                    "detail_level_publication_or_event_identity_reconciliation",
                ],
            }
        )

    source_fingerprint_basis = {
        "ministry_run_id": ministry.get("run_id"),
        "posturi_run_id": posturi.get("run_id"),
        "ministry_evidence": [ref.get("evidence_sha256") for ref in ministry_refs],
        "posturi_evidence": [ref.get("evidence_sha256") for ref in posturi_refs],
        "posturi_institution_evidence": [ref.get("institution_evidence_sha256") for ref in posturi_refs],
    }
    source_fingerprint = hashlib.sha256(
        json.dumps(source_fingerprint_basis, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    payload = {
        "schema": CONTRACT,
        "status": "PASS",
        "context_state": state,
        "observation_state": "CROSS_SOURCE_REFERENCE_CONTEXT_NON_AUTHORIZING",
        "institution_context": {
            "ministry_contract_institution": "SJU_VALCEA",
            "posturi_institution_identity": (
                "SJU_VALCEA_EXPLICIT_IN_FIRST_PARTY_DETAIL_SUMMARY"
                if posturi_explicit_sju
                else "UNRESOLVED_OR_OTHER_INSTITUTION_IN_BOUNDED_POSTURI_HEALTH_REFERENCES"
            ),
            "same_institution_explicit_source_count": 2 if posturi_explicit_sju else 1,
            "same_institution_inferred": False,
            "same_vacancy_inferred": False,
            "same_need_inferred": False,
        },
        "coverage": {
            "ministry_reference_count": len(ministry_refs),
            "posturi_reference_count": len(posturi_refs),
            "posturi_health_reference_count": len(posturi_health),
            "posturi_explicit_institution_count": sum(
                1 for ref in posturi_refs if ref.get("institution_identity_state") == POSTURI_INSTITUTION_EXPLICIT
            ),
            "posturi_explicit_sju_institution_count": len(posturi_explicit_sju),
            "posturi_explicit_sju_title_count": len(posturi_explicit_sju_title),
            "follow_up_candidate_count": len(follow_up),
            "bounded_non_exhaustive": True,
        },
        "ministry_references": [_compact_reference(ref, source=MS_SOURCE_FAMILY) for ref in ministry_refs[:16]],
        "posturi_health_references": [_compact_reference(ref, source=POSTURI_SOURCE_FAMILY) for ref in posturi_health[:16]],
        "follow_up_candidates": follow_up,
        "source_fingerprint_sha256": source_fingerprint,
        "coverage_note": "CROSS_SOURCE_INSTITUTION_CONTEXT_ONLY_NOT_VACANCY_DEDUPLICATION",
        "required_next_evidence": (
            "ROLE_AND_PUBLICATION_IDENTITY_RECONCILIATION_BEFORE_ANY_SAME_VACANCY_OR_SAME_NEED_CONCLUSION"
        ),
        **ENGINE_BOUNDARIES,
    }
    stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["run_id"] = hashlib.sha256(stable).hexdigest()[:24]
    return payload


def _fixture_ministry() -> dict[str, Any]:
    h1 = "a" * 64
    h2 = "b" * 64
    return {
        "schema": MS_SCHEMA,
        "status": "PASS",
        "source_family": MS_SOURCE_FAMILY,
        "authority_class": MS_AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "reference_count": 1,
        "references": [
            {
                "title": "Anunț concurs - Spitalul Județean de Urgență Vâlcea",
                "url": "https://www.ms.ro/ro/minister/cariera-medici/anunt-concurs-spitalul-judetean-de-urgenta-valcea-25/",
                "topic_class": "HEALTH_WORKFORCE_VACANCY_REFERENCE",
                "source_page_sha256": h1,
                "evidence_sha256": h2,
                "source_family": MS_SOURCE_FAMILY,
                "authority_class": MS_AUTHORITY_CLASS,
                "observation_state": OBSERVATION_STATE,
            }
        ],
        "run_id": "ministry-fixture",
        "staffing_level_authorized": False,
        "treatment_availability_authorized": False,
        **SOURCE_NON_AUTHORIZING_FLAGS,
    }


def _fixture_posturi(
    title: str,
    topic: str = POSTURI_HEALTH_TOPIC,
    institution_name: str | None = None,
) -> dict[str, Any]:
    h1 = "c" * 64
    h2 = "d" * 64
    h3 = "e" * 64
    explicit = institution_name is not None
    return {
        "schema": POSTURI_SCHEMA,
        "status": "PASS",
        "source_family": POSTURI_SOURCE_FAMILY,
        "authority_class": POSTURI_AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "reference_count": 1,
        "references": [
            {
                "title": title,
                "url": "https://posturi.gov.ro/joburi/medic-specialist-psihiatrie-pediatrica/",
                "topic_class": topic,
                "institution_name": institution_name,
                "institution_identity_state": (
                    POSTURI_INSTITUTION_EXPLICIT if explicit else POSTURI_INSTITUTION_UNRESOLVED
                ),
                "institution_evidence_sha256": ("f" * 64 if explicit else None),
                "index_sha256": h1,
                "detail_sha256": h2,
                "evidence_sha256": h3,
                "source_family": POSTURI_SOURCE_FAMILY,
                "authority_class": POSTURI_AUTHORITY_CLASS,
                "observation_state": OBSERVATION_STATE,
            }
        ],
        "run_id": "posturi-fixture",
        "institution_identity_contract": "EXPLICIT_FIRST_PARTY_DETAIL_SUMMARY_ONLY",
        "institution_status_authorized": False,
        "same_vacancy_inference_authorized": False,
        "same_need_inference_authorized": False,
        "dedupe_authorized": False,
        **SOURCE_NON_AUTHORIZING_FLAGS,
    }


def self_test() -> None:
    county_only = build_context(_fixture_ministry(), _fixture_posturi("Medic specialist psihiatrie pediatrică"))
    assert county_only["context_state"] == STATE_COUNTY_CONTEXT
    assert county_only["coverage"]["posturi_health_reference_count"] == 1
    assert county_only["coverage"]["posturi_explicit_sju_institution_count"] == 0
    assert county_only["follow_up_candidates"] == []
    assert county_only["dedupe_authorized"] is False
    assert county_only["same_vacancy_inference_authorized"] is False

    explicit = build_context(
        _fixture_ministry(),
        _fixture_posturi(
            "Medic specialist psihiatrie pediatrică",
            institution_name="Spitalul Județean de Urgență Vâlcea",
        ),
    )
    assert explicit["context_state"] == STATE_EXPLICIT_SAME_INSTITUTION
    assert explicit["coverage"]["posturi_explicit_sju_institution_count"] == 1
    assert explicit["coverage"]["posturi_explicit_sju_title_count"] == 0
    assert explicit["coverage"]["follow_up_candidate_count"] == 1
    assert explicit["follow_up_candidates"][0]["same_vacancy_inferred"] is False
    assert explicit["follow_up_candidates"][0]["same_institution_explicit_in_both_source_contracts"] is True

    other_hospital = build_context(
        _fixture_ministry(),
        _fixture_posturi("Medic specialist pneumolog", institution_name="Spitalul Municipal Costache Nicolescu Drăgășani"),
    )
    assert other_hospital["context_state"] == STATE_COUNTY_CONTEXT
    assert other_hospital["coverage"]["posturi_explicit_institution_count"] == 1
    assert other_hospital["coverage"]["posturi_explicit_sju_institution_count"] == 0

    no_health = build_context(
        _fixture_ministry(),
        _fixture_posturi("Inspector", "PUBLIC_JOBS_ADMINISTRATION_REFERENCE", institution_name="Primăria Drăgășani"),
    )
    assert no_health["context_state"] == STATE_MINISTRY_ONLY

    bad = _fixture_posturi("Medic specialist")
    bad["publication_authorized"] = True
    try:
        build_context(_fixture_ministry(), bad)
    except ValueError as exc:
        assert "authorization_boundary_drift" in str(exc)
    else:
        raise AssertionError("authorizing source receipt must fail closed")

    bad_identity = _fixture_posturi("Medic specialist", institution_name="Spitalul Județean de Urgență Vâlcea")
    bad_identity["references"][0]["institution_evidence_sha256"] = "bad"
    try:
        build_context(_fixture_ministry(), bad_identity)
    except ValueError as exc:
        assert "institution_hash_invalid" in str(exc)
    else:
        raise AssertionError("invalid institution evidence hash must fail closed")

    print("Health workforce reference context engine self-test: PASS")


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"input_not_object:{path}")
    return payload


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--ministry", type=Path)
    parser.add_argument("--posturi", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.self_test:
        self_test()
        return 0
    if args.ministry is None or args.posturi is None:
        parser.error("--ministry and --posturi are required")

    try:
        result = build_context(_load(args.ministry), _load(args.posturi))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"FAIL: {exc}") from exc

    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    print(
        "Health workforce reference context: PASS "
        f"({result['coverage']['ministry_reference_count']} ministry / "
        f"{result['coverage']['posturi_health_reference_count']} posturi health refs / "
        f"{result['coverage']['posturi_explicit_sju_institution_count']} explicit SJU; "
        f"state={result['context_state']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
