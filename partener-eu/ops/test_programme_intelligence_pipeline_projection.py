#!/usr/bin/env python3
from __future__ import annotations

import copy

from programme_intelligence_pipeline_projection import REQUIRED_MISSING_FOR_OPEN, project, validate_projection

FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "closed_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
    "call_alert_authorized",
    "canonical_corpus_mutation",
)


def add_boundary(obj: dict) -> dict:
    obj["market_intelligence_only"] = True
    obj["publication_effect"] = "NONE"
    for flag in FLAGS:
        obj[flag] = False
    return obj


def eea_fixture() -> dict:
    return add_boundary({
        "schema": "PARTENER_EU_EEA_NORWAY_ROMANIA_PROGRAMME_WATCH_V1",
        "source_family": "EEA_NORWAY",
        "programme_family": "EEA_NORWAY_ROMANIA_2021_2028",
        "authority_class": "EEA_NORWAY_FMO_OFFICIAL",
        "source_health": "HEALTHY",
        "run_id": "run-1",
        "fetched_at": "2026-09-02T06:00:00+00:00",
        "semantic_fingerprint": "a" * 64,
        "programming_observations": [
            {
                "title": "Romania EEA Grants 2021-2028 Memorandum of Understanding",
                "observation_state": "PROGRAMMING",
                "source_url": "https://eeagrants.org/en/fmo/documents-library/mou-romania-2021-2028-eea-1",
                "authority_class": "EEA_NORWAY_FMO_OFFICIAL",
                "observed_at": "2026-09-02T06:00:00+00:00",
                "open_call_authorized": False,
                "material_fact_use": False,
            },
            {
                "title": "Romania Norway Grants 2021-2028 Memorandum of Understanding",
                "observation_state": "PROGRAMMING",
                "source_url": "https://eeagrants.org/en/fmo/documents-library/mou-romania-2021-2028-norway",
                "authority_class": "EEA_NORWAY_FMO_OFFICIAL",
                "observed_at": "2026-09-02T06:00:00+00:00",
                "open_call_authorized": False,
                "material_fact_use": False,
            },
        ],
        "missing_for_open_call_confirmation": [
            "selected exact call identifier",
            "fresh call-specific official endpoint readback",
            "semantic reconciliation against same-identity previous evidence",
            "field-scoped material admission",
        ],
    })


def fallback(configured: bool = False, health: str = "NOT_CONFIGURED") -> dict:
    return {
        "configured": configured,
        "authority_url": "https://interreg.eu/programmes/example/" if configured else None,
        "authority_class": "INTERREG_INTERACT_PROGRAMME_REGISTRY_FALLBACK",
        "surface_role": "CENTRAL_INTERREG_PROGRAMME_REGISTRY_FALLBACK" if configured else None,
        "observation_state": "PROGRAMME_REGISTRY_FALLBACK_ONLY",
        "provenance_note": "programme identity only" if configured else None,
        "transport_health": health,
        "requested_url": None,
        "final_url": "https://interreg.eu/programmes/example/" if health == "HEALTHY" else None,
        "status": 200 if health == "HEALTHY" else None,
        "content_type": "text/html" if health == "HEALTHY" else None,
        "source_sha256": "b" * 64 if health == "HEALTHY" else None,
        "programme_identity_verified_non_authorizing": health == "HEALTHY",
        "call_surface_authority": False,
        "call_fact_authorized": False,
        "error_type": None,
        "failure_class": None,
        "error": None,
    }


def surface(programme_id: str, state: str, *, health: str = "HEALTHY", fb: dict | None = None) -> dict:
    return {
        "programme_id": programme_id,
        "programme": f"Programme {programme_id}",
        "authority_url": f"https://example.invalid/{programme_id.lower()}",
        "authority_class": "INTERREG_OFFICIAL_CALL_DISCOVERY_SURFACE",
        "surface_role": "PROGRAMME_CALL_PLANNING" if state == "PLANNED" else "PROGRAMME_CALL_INDEX",
        "observation_state": state,
        "programme_filter_required": False,
        "authority_note": "non-authorizing",
        "observed_at": "2026-09-02T06:00:00+00:00",
        "market_intelligence_only": True,
        "call_fact_authorized": False,
        "status_fact_authorized": False,
        "deadline_fact_authorized": False,
        "budget_fact_authorized": False,
        "eligibility_fact_authorized": False,
        "transport_health": health,
        "requested_url": f"https://example.invalid/{programme_id.lower()}",
        "final_url": f"https://example.invalid/{programme_id.lower()}" if health == "HEALTHY" else None,
        "status": 200 if health == "HEALTHY" else None,
        "content_type": "text/html" if health == "HEALTHY" else None,
        "source_sha256": "c" * 64 if health == "HEALTHY" else None,
        "error_type": None if health == "HEALTHY" else "URLError",
        "failure_class": None if health == "HEALTHY" else "TLS_CERTIFICATE_VERIFY_FAILED",
        "error": None if health == "HEALTHY" else "certificate verify failed",
        "fallback_provenance": fb or fallback(),
    }


def interreg_fixture() -> dict:
    return add_boundary({
        "schema": "PARTENER_EU_INTERREG_ROMANIA_CALL_SURFACE_WATCH_V2",
        "source_family": "INTERREG",
        "programme_family": "INTERREG_ROMANIA_RELEVANT_2021_2027",
        "source_health": "DEGRADED",
        "run_id": "run-1",
        "fetched_at": "2026-09-02T06:00:00+00:00",
        "semantic_fingerprint": "d" * 64,
        "discovered_call_facts": [],
        "fallback_does_not_restore_call_surface_coverage": True,
        "surfaces": [surface("RO_RS", "PLANNED"), surface("RO_HU", "CALL_DISCOVERY_ONLY")],
        "missing_for_open_call_confirmation": [
            "selected exact programme call identifier",
            "fresh current exact official call endpoint readback",
            "same-identity semantic reconciliation",
            "field-scoped material admission",
        ],
    })


def expect_failure(eea: dict, interreg: dict, fragment: str) -> None:
    try:
        project(eea, interreg)
    except ValueError as exc:
        if fragment not in str(exc):
            raise AssertionError(f"unexpected error: {exc}") from exc
    else:
        raise AssertionError(f"expected failure containing {fragment!r}")


def main() -> None:
    eea = eea_fixture()
    interreg = interreg_fixture()
    output = project(eea, interreg)
    validate_projection(output)

    assert output["surface"] == "PROGRAMARE_VIITOARE_PIPELINE"
    assert output["surface_state"] == "PREVIEW_READ_ONLY_NOT_PUBLISHED"
    assert output["seo_indexing_state"] == "NOINDEX_PREVIEW_ONLY"
    assert output["card_count"] == 3
    assert {card["observation_state"] for card in output["cards"]} == {"PROGRAMMING", "PLANNED"}
    assert not any(card["card_id"] == "INTERREG_RO_HU_PLANNED" for card in output["cards"])
    assert all(REQUIRED_MISSING_FOR_OPEN.issubset(set(card["missing_for_open_confirmation"])) for card in output["cards"])
    assert all(card["open_call_authorized"] is False for card in output["cards"])
    assert all(card["publish_authorized"] is False for card in output["cards"])
    assert output["distribution_authorized"] is False
    assert output["material_change_claimed"] is False
    assert output["semantic_reconciliation_present"] is False
    assert output["semantic_reconciliation_required_before_material_change"] is True

    bad_eea = copy.deepcopy(eea)
    bad_eea["open_call_authorized"] = True
    expect_failure(bad_eea, interreg, "authorizing drift")

    bad_interreg = copy.deepcopy(interreg)
    bad_interreg["surfaces"][0]["observation_state"] = "OPEN_CALL"
    expect_failure(eea, bad_interreg, "observation state drift")

    bad_fallback = copy.deepcopy(interreg)
    bad_fallback["surfaces"][0]["fallback_provenance"]["call_surface_authority"] = True
    expect_failure(eea, bad_fallback, "fallback attempted call authority")

    degraded = copy.deepcopy(interreg)
    degraded["surfaces"][0] = surface("RO_RS", "PLANNED", health="DEGRADED", fb=fallback(configured=True, health="HEALTHY"))
    degraded_output = project(eea, degraded)
    planned = next(card for card in degraded_output["cards"] if card["source_family"] == "INTERREG")
    assert planned["confidence"] == "LOW"
    assert planned["confidence_reason"] == "DIRECT_PROGRAMME_SURFACE_DEGRADED_REGISTRY_PROVENANCE_ONLY"
    assert planned["open_call_authorized"] is False

    tampered = copy.deepcopy(output)
    tampered["cards"][0]["open_confirmation_state"] = "CONFIRMED_OPEN"
    try:
        validate_projection(tampered)
    except ValueError as exc:
        assert "open confirmation state drift" in str(exc)
    else:
        raise AssertionError("tampered projection should fail")

    print({
        "status": "PASS",
        "card_count": output["card_count"],
        "states": sorted({card["observation_state"] for card in output["cards"]}),
        "surface": output["surface"],
        "publication_effect": output["publication_effect"],
    })


if __name__ == "__main__":
    main()
