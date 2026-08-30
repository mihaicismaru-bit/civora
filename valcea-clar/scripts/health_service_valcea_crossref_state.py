#!/usr/bin/env python3
"""Fail-closed cross-reference state for Vâlcea hospital service references.

Consumes normalized signals from the Ministry of Health SJU adapter, the Ministry
hospital-network adapter, and the CAS Vâlcea service-access adapter.

The output answers only a bounded editorial question: which service family is
explicitly registered for which known public hospital. CAS hospital-directory
signals are retained as county-level context only; they never prove hospital
identity, a specific service, current contract status, availability, opening
hours, appointments, beds, staffing, or emergency load.

No identity merge, dedupe, persistence, Fact Kernel promotion, Writer/public
projection, medical advice, patient facts, or current operational claims.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

TAXONOMY_VERSION = "2026-08-30.1"

SJU_SOURCE_ID = "signal-sju-valcea-ms-hospital-reference"
CAS_SOURCE_ID = "signal-cas-valcea-service-access"
NETWORK_SOURCES = {
    "signal-ms-valcea-hospital-dragasani-reference": (
        "dragasani",
        "Spitalul Municipal Costache Nicolescu Drăgășani",
    ),
    "signal-ms-valcea-hospital-horezu-reference": (
        "horezu",
        "Spitalul Orășenesc Horezu",
    ),
    "signal-ms-valcea-hospital-brezoi-reference": (
        "brezoi",
        "Spitalul Orășenesc Brezoi",
    ),
    "signal-ms-valcea-hospital-dragoesti-reference": (
        "dragoesti",
        "Spitalul de Psihiatrie Drăgoești",
    ),
    "signal-ms-valcea-hospital-mihaesti-pneumo-reference": (
        "mihaesti_pneumo",
        "Spitalul de Pneumoftiziologie Constantin Anastasatu Mihăești",
    ),
}
EXPECTED_SOURCE_TAXONOMIES = {
    SJU_SOURCE_ID: "2026-08-30.1",
    CAS_SOURCE_ID: "2026-08-30.1",
    **{source_id: "2026-08-30.1" for source_id in NETWORK_SOURCES},
}

SJU_SERVICE_FAMILIES = {
    "OUTPATIENT_SPECIALTY_REFERENCE": "outpatient_specialty",
    "LABORATORY_SERVICE_REFERENCE": "laboratory",
    "IMAGING_AND_NUCLEAR_MEDICINE_REFERENCE": "imaging_and_nuclear_medicine",
    "EMERGENCY_AND_CRITICAL_CARE_REFERENCE": "emergency_and_critical_care",
    "CARDIOVASCULAR_SERVICE_REFERENCE": "cardiovascular",
    "NEUROLOGY_AND_NEUROSURGERY_REFERENCE": "neurology_and_neurosurgery",
    "PEDIATRIC_SERVICE_REFERENCE": "pediatrics",
    "SURGICAL_SERVICE_REFERENCE": "surgery",
    "ONCOLOGY_AND_HEMATOLOGY_REFERENCE": "oncology_and_hematology",
    "OBSTETRICS_GYNECOLOGY_REFERENCE": "obstetrics_gynecology",
    "INFECTIOUS_DISEASE_SERVICE_REFERENCE": "infectious_diseases",
    "REHABILITATION_SERVICE_REFERENCE": "rehabilitation",
    "PSYCHIATRY_SERVICE_REFERENCE": "psychiatry",
}
NETWORK_SERVICE_FAMILIES = {
    "OUTPATIENT_SERVICE_REFERENCE": "outpatient_specialty",
    "LABORATORY_SERVICE_REFERENCE": "laboratory",
    "RADIOLOGY_IMAGING_SERVICE_REFERENCE": "imaging",
    "INTERNAL_MEDICINE_SERVICE_REFERENCE": "internal_medicine",
    "NEUROLOGY_SERVICE_REFERENCE": "neurology",
    "GENERAL_SURGERY_SERVICE_REFERENCE": "general_surgery",
    "OBSTETRICS_GYNECOLOGY_SERVICE_REFERENCE": "obstetrics_gynecology",
    "CRITICAL_CARE_SERVICE_REFERENCE": "critical_care",
    "PEDIATRIC_SERVICE_REFERENCE": "pediatrics",
    "PSYCHIATRY_SERVICE_REFERENCE": "psychiatry",
    "INFECTIOUS_DISEASE_SERVICE_REFERENCE": "infectious_diseases",
    "PULMONOLOGY_SERVICE_REFERENCE": "pulmonology",
}
STRUCTURAL_HOSPITAL_CLASSES = {
    "HOSPITAL_PROFILE_REFERENCE",
    "HOSPITAL_REGISTERED_CAPACITY_REFERENCE",
    "HOSPITAL_LOCATION_REFERENCE",
    "HOSPITAL_CONTACT_REFERENCE",
}
CAS_CONTEXT_SCOPE = "HOSPITAL"

FORBIDDEN_TRUE_FLAGS = {
    "current_service_status_claim_allowed",
    "appointment_availability_claim_allowed",
    "bed_availability_claim_allowed",
    "emergency_load_claim_allowed",
    "on_call_staffing_claim_allowed",
    "opening_hours_claim_allowed",
    "patient_person_fact_extraction_allowed",
    "medical_advice_allowed",
    "linked_document_fetch_allowed",
    "external_form_submission_allowed",
    "inferred_photo_rights_allowed",
    "persistence_allowed",
    "fact_kernel_promotion_allowed",
    "writer_allowed",
    "public_projection_allowed",
    "current_provider_status_claim_allowed",
    "linked_document_body_parse_allowed",
    "provider_person_extraction_allowed",
}


@dataclass(frozen=True)
class HealthServiceCrossrefState:
    state_id: str
    taxonomy_version: str
    state_class: str
    review_status: str
    source_signal_id: str
    source_id: str
    source_taxonomy_version: str
    source_url: str
    payload_sha256: str
    institution_id: Optional[str]
    institution_label: Optional[str]
    service_family: Optional[str]
    context_scope: Optional[str]
    hold_reason: Optional[str]
    evidence_sha256: Optional[str]
    supports_registered_service_reference: bool = False
    supports_institution_identity: bool = False
    supports_current_contract_status: bool = False
    service_availability_current: bool = False
    appointment_availability_current: bool = False
    bed_availability_current: bool = False
    emergency_load_current: bool = False
    doctor_on_call_current: bool = False
    opening_hours_current: bool = False
    provider_open_current: bool = False
    accepting_patients_current: bool = False
    patient_reference_allowed: bool = False
    medical_advice_allowed: bool = False
    identity_merge_allowed: bool = False
    dedupe_allowed: bool = False
    persistence_allowed: bool = False
    fact_kernel_promotion_allowed: bool = False
    writer_allowed: bool = False
    public_projection_allowed: bool = False


def clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _hash(*parts: Any) -> str:
    payload = "\0".join(clean(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _state_id(source_signal_id: str, state_class: str, institution_id: str = "", service_family: str = "") -> str:
    digest = _hash(source_signal_id, state_class, institution_id, service_family)[:20]
    return f"healthxref-{digest}"


def _evidence_hash(signal: dict[str, Any]) -> Optional[str]:
    excerpt = clean(signal.get("evidence_excerpt"))
    return hashlib.sha256(excerpt.encode("utf-8")).hexdigest() if excerpt else None


def _hold(signal: dict[str, Any], reason: str) -> HealthServiceCrossrefState:
    source_signal_id = clean(signal.get("signal_id")) or "unknown"
    source_id = clean(signal.get("source_id")) or "unknown"
    source_taxonomy = clean(signal.get("taxonomy_version")) or "unknown"
    return HealthServiceCrossrefState(
        state_id=_state_id(source_signal_id, "HOLD", service_family=reason),
        taxonomy_version=TAXONOMY_VERSION,
        state_class="HOLD_HEALTH_SERVICE_CROSSREF",
        review_status="HOLD",
        source_signal_id=source_signal_id,
        source_id=source_id,
        source_taxonomy_version=source_taxonomy,
        source_url="",
        payload_sha256=clean(signal.get("payload_sha256")),
        institution_id=None,
        institution_label=None,
        service_family=None,
        context_scope=None,
        hold_reason=reason,
        evidence_sha256=None,
    )


def _unsafe_boundary(signal: dict[str, Any]) -> Optional[str]:
    if signal.get("hold_reason"):
        return "UPSTREAM_SIGNAL_HELD"
    if clean(signal.get("signal_class")).startswith("HOLD"):
        return "UPSTREAM_SIGNAL_HELD"
    for flag in FORBIDDEN_TRUE_FLAGS:
        if signal.get(flag) is True:
            return f"UNSAFE_UPSTREAM_BOUNDARY_{flag.upper()}"
    authority = signal.get("publication_authority")
    if authority not in (None, "NONE"):
        return "PUBLICATION_AUTHORITY_DRIFT"
    return None


def _validate_common(signal: dict[str, Any]) -> Optional[str]:
    source_id = clean(signal.get("source_id"))
    if source_id not in EXPECTED_SOURCE_TAXONOMIES:
        return "UNKNOWN_SOURCE"
    expected_taxonomy = EXPECTED_SOURCE_TAXONOMIES[source_id]
    if clean(signal.get("taxonomy_version")) != expected_taxonomy:
        return "SOURCE_TAXONOMY_DRIFT"
    if not clean(signal.get("signal_id")):
        return "MISSING_SIGNAL_ID"
    if not clean(signal.get("source_url")):
        return "MISSING_SOURCE_URL"
    payload = clean(signal.get("payload_sha256"))
    if len(payload) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in payload):
        return "INVALID_PAYLOAD_SHA256"
    return _unsafe_boundary(signal)


def _hospital_state(
    signal: dict[str, Any],
    institution_id: str,
    institution_label: str,
    service_family: str,
) -> HealthServiceCrossrefState:
    source_signal_id = clean(signal["signal_id"])
    return HealthServiceCrossrefState(
        state_id=_state_id(source_signal_id, "REGISTERED_SERVICE", institution_id, service_family),
        taxonomy_version=TAXONOMY_VERSION,
        state_class="HEALTH_SERVICE_REGISTER_REFERENCE",
        review_status="REVIEW_REQUIRED",
        source_signal_id=source_signal_id,
        source_id=clean(signal["source_id"]),
        source_taxonomy_version=clean(signal["taxonomy_version"]),
        source_url=clean(signal["source_url"]),
        payload_sha256=clean(signal["payload_sha256"]),
        institution_id=institution_id,
        institution_label=institution_label,
        service_family=service_family,
        context_scope="MINISTRY_HOSPITAL_REGISTER",
        hold_reason=None,
        evidence_sha256=_evidence_hash(signal),
        supports_registered_service_reference=True,
        supports_institution_identity=True,
    )


def _cas_context_state(signal: dict[str, Any]) -> HealthServiceCrossrefState:
    source_signal_id = clean(signal["signal_id"])
    return HealthServiceCrossrefState(
        state_id=_state_id(source_signal_id, "CAS_HOSPITAL_CONTEXT"),
        taxonomy_version=TAXONOMY_VERSION,
        state_class="HEALTH_PROVIDER_CATEGORY_CONTEXT",
        review_status="REVIEW_REQUIRED",
        source_signal_id=source_signal_id,
        source_id=clean(signal["source_id"]),
        source_taxonomy_version=clean(signal["taxonomy_version"]),
        source_url=clean(signal["source_url"]),
        payload_sha256=clean(signal["payload_sha256"]),
        institution_id=None,
        institution_label=None,
        service_family=None,
        context_scope="CAS_VALCEA_HOSPITAL_PROVIDER_CATEGORY_ONLY",
        hold_reason=None,
        evidence_sha256=None,
        supports_registered_service_reference=False,
        supports_institution_identity=False,
        supports_current_contract_status=False,
    )


def normalize_signal(signal: dict[str, Any]) -> Optional[HealthServiceCrossrefState]:
    reason = _validate_common(signal)
    if reason:
        return _hold(signal, reason)

    source_id = clean(signal["source_id"])
    signal_class = clean(signal.get("signal_class"))

    if source_id == CAS_SOURCE_ID:
        if signal_class != "HEALTH_PROVIDER_DIRECTORY":
            return _hold(signal, "UNEXPECTED_CAS_SIGNAL_CLASS")
        if clean(signal.get("directory_scope")) != CAS_CONTEXT_SCOPE:
            return None
        if clean(signal.get("reference_kind")) not in {"HTML_REFERENCE", "DOCUMENT_REFERENCE"}:
            return _hold(signal, "UNEXPECTED_CAS_REFERENCE_KIND")
        return _cas_context_state(signal)

    if clean(signal.get("source_tier")) != "T1":
        return _hold(signal, "HOSPITAL_SOURCE_TIER_DRIFT")
    if clean(signal.get("reference_scope")) != "HOSPITAL_REGISTRY_REFERENCE":
        return _hold(signal, "HOSPITAL_REFERENCE_SCOPE_DRIFT")

    if source_id == SJU_SOURCE_ID:
        institution_id = "sju_valcea"
        institution_label = "Spitalul Județean de Urgență Vâlcea"
        service_family = SJU_SERVICE_FAMILIES.get(signal_class)
        if service_family:
            return _hospital_state(signal, institution_id, institution_label, service_family)
        if signal_class in STRUCTURAL_HOSPITAL_CLASSES:
            return None
        return _hold(signal, "UNKNOWN_SJU_REFERENCE_CLASS")

    institution_id, institution_label = NETWORK_SOURCES[source_id]
    hospital_key = clean(signal.get("hospital_key"))
    if hospital_key and hospital_key != institution_id:
        return _hold(signal, "HOSPITAL_KEY_SOURCE_MISMATCH")
    service_family = NETWORK_SERVICE_FAMILIES.get(signal_class)
    if service_family:
        return _hospital_state(signal, institution_id, institution_label, service_family)
    if signal_class in STRUCTURAL_HOSPITAL_CLASSES:
        return None
    return _hold(signal, "UNKNOWN_HOSPITAL_NETWORK_REFERENCE_CLASS")


def build_state(signals: Iterable[dict[str, Any]]) -> list[HealthServiceCrossrefState]:
    states: list[HealthServiceCrossrefState] = []
    seen: set[str] = set()
    for signal in signals:
        if not isinstance(signal, dict):
            states.append(_hold({}, "NON_OBJECT_SIGNAL"))
            continue
        state = normalize_signal(signal)
        if state is None or state.state_id in seen:
            continue
        seen.add(state.state_id)
        states.append(state)
    states.sort(
        key=lambda item: (
            item.review_status,
            item.institution_id or "~",
            item.service_family or "~",
            item.state_id,
        )
    )
    return states


def _base_signal(
    source_id: str,
    signal_class: str,
    *,
    signal_id: str,
    taxonomy_version: str,
    source_url: str,
    **extra: Any,
) -> dict[str, Any]:
    signal = {
        "signal_id": signal_id,
        "source_id": source_id,
        "taxonomy_version": taxonomy_version,
        "signal_class": signal_class,
        "source_url": source_url,
        "payload_sha256": "a" * 64,
        "hold_reason": None,
        "publication_authority": "NONE",
    }
    signal.update(extra)
    return signal


def self_test() -> None:
    sju = _base_signal(
        SJU_SOURCE_ID,
        "CARDIOVASCULAR_SERVICE_REFERENCE",
        signal_id="sju-cardiology",
        taxonomy_version="2026-08-30.1",
        source_url="https://www.ms.ro/ro/unitati-sanitare/spitalul-judetean-de-urgenta-valcea/",
        source_tier="T1",
        reference_scope="HOSPITAL_REGISTRY_REFERENCE",
        evidence_excerpt="Cardiologie și chirurgie vasculară.",
    )
    horezu = _base_signal(
        "signal-ms-valcea-hospital-horezu-reference",
        "INTERNAL_MEDICINE_SERVICE_REFERENCE",
        signal_id="horezu-internal",
        taxonomy_version="2026-08-30.1",
        source_url="https://www.ms.ro/ro/unitati-sanitare/spitalul-orasenesc-horezu/",
        source_tier="T1",
        reference_scope="HOSPITAL_REGISTRY_REFERENCE",
        hospital_key="horezu",
        evidence_excerpt="Medicină internă.",
    )
    cas_hospitals = _base_signal(
        CAS_SOURCE_ID,
        "HEALTH_PROVIDER_DIRECTORY",
        signal_id="cas-hospital-directory",
        taxonomy_version="2026-08-30.1",
        source_url="https://cas.cnas.ro/casvl/informatii-furnizori/furnizori-de-servicii-medicale",
        directory_scope="HOSPITAL",
        reference_kind="HTML_REFERENCE",
    )
    cas_outpatient = dict(cas_hospitals, signal_id="cas-outpatient", directory_scope="OUTPATIENT_SPECIALTY")
    states = build_state([sju, horezu, cas_hospitals, cas_outpatient])
    assert len(states) == 3, states
    sju_state = next(item for item in states if item.source_signal_id == "sju-cardiology")
    assert sju_state.institution_id == "sju_valcea"
    assert sju_state.service_family == "cardiovascular"
    assert sju_state.supports_registered_service_reference is True
    assert sju_state.public_projection_allowed is False
    horezu_state = next(item for item in states if item.source_signal_id == "horezu-internal")
    assert horezu_state.institution_id == "horezu"
    assert horezu_state.service_family == "internal_medicine"
    cas_state = next(item for item in states if item.source_signal_id == "cas-hospital-directory")
    assert cas_state.context_scope == "CAS_VALCEA_HOSPITAL_PROVIDER_CATEGORY_ONLY"
    assert cas_state.institution_id is None
    assert cas_state.service_family is None
    assert cas_state.supports_institution_identity is False
    assert cas_state.supports_current_contract_status is False

    cas_legacy_taxonomy = dict(cas_hospitals, signal_id="cas-legacy-taxonomy", taxonomy_version="2026-08-29.1")
    assert build_state([cas_legacy_taxonomy])[0].hold_reason == "SOURCE_TAXONOMY_DRIFT"

    unsafe = dict(sju, signal_id="sju-unsafe", current_service_status_claim_allowed=True)
    unsafe_state = build_state([unsafe])[0]
    assert unsafe_state.review_status == "HOLD"
    assert unsafe_state.hold_reason == "UNSAFE_UPSTREAM_BOUNDARY_CURRENT_SERVICE_STATUS_CLAIM_ALLOWED"
    assert unsafe_state.source_url == ""
    assert unsafe_state.evidence_sha256 is None

    drift = dict(sju, signal_id="sju-drift", taxonomy_version="2099-01-01.1")
    assert build_state([drift])[0].hold_reason == "SOURCE_TAXONOMY_DRIFT"

    mismatch = dict(horezu, signal_id="wrong-key", hospital_key="brezoi")
    assert build_state([mismatch])[0].hold_reason == "HOSPITAL_KEY_SOURCE_MISMATCH"

    held = dict(horezu, signal_id="held", hold_reason="UPSTREAM_TEST_HOLD")
    assert build_state([held])[0].hold_reason == "UPSTREAM_SIGNAL_HELD"

    unknown = dict(sju, signal_id="unknown", signal_class="CURRENT_WAIT_TIME_REFERENCE")
    assert build_state([unknown])[0].hold_reason == "UNKNOWN_SJU_REFERENCE_CLASS"

    structural = dict(sju, signal_id="profile", signal_class="HOSPITAL_PROFILE_REFERENCE")
    assert build_state([structural]) == []

    print("VÂLCEA CLAR health-service cross-reference self-test: OK")


def _load(path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("signals")
    if not isinstance(payload, list):
        raise ValueError("input must be a JSON list or an object with a 'signals' list")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", help="JSON output from supported health signal adapters.")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.input:
        parser.error("--input is required unless --self-test is used")

    states = build_state(_load(args.input))
    json.dump([asdict(item) for item in states], sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())