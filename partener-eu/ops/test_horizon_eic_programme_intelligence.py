#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from horizon_eic_programme_intelligence import (
    DEFAULT_REGISTRY,
    MATERIAL_FLAGS,
    acquire,
    load_registry,
)


def _write_temp_registry(data: dict) -> Path:
    handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False)
    with handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return Path(handle.name)


def _expect_registry_failure(mutator) -> None:
    data = json.loads(DEFAULT_REGISTRY.read_text(encoding="utf-8"))
    mutator(data)
    path = _write_temp_registry(data)
    try:
        try:
            load_registry(path)
        except ValueError:
            return
        raise AssertionError("tampered registry unexpectedly passed fail-closed validation")
    finally:
        path.unlink(missing_ok=True)


def main() -> None:
    registry, registry_sha = load_registry()
    assert len(registry_sha) == 64
    assert set(registry["programme_families"]) == {"Horizon Europe", "European Innovation Council"}
    assert {row["id"] for row in registry["sources"]} == {
        "HORIZON_EUROPE_GATEWAY",
        "HORIZON_WORK_PROGRAMMES_2026_2027",
        "EIC_WORK_PROGRAMME_2026",
        "EIC_FUNDING_OPPORTUNITIES_INDEX",
    }
    assert {row["observation_state"] for row in registry["sources"]} == {
        "PROGRAMME_INTELLIGENCE",
        "PROGRAMMING_PIPELINE",
        "CALL_INDEX_DISCOVERY",
    }
    assert all(row["material_fact_use"] is False for row in registry["sources"])
    assert registry["policy"]["market_intelligence_only"] is True
    assert registry["policy"]["publication_effect"] == "NONE"
    assert all(registry["policy"][key] is False for key in MATERIAL_FLAGS)
    assert registry["policy"]["exact_call_or_topic_identifier_required"] is True
    assert registry["policy"]["current_official_exact_endpoint_required"] is True
    assert registry["policy"]["semantic_reconciliation_required"] is True
    assert registry["policy"]["field_scoped_material_admission_required"] is True

    result = acquire(
        run_id="TEST-HORIZON-EIC-1",
        observed_at="2026-09-02T12:00:00Z",
        live=False,
    )
    assert result["schema"] == "PARTENER_EU_HORIZON_EIC_PROGRAMME_INTELLIGENCE_V1"
    assert result["source_family"] == "EU_DIRECT"
    assert result["source_count"] == 4
    assert result["source_health_state"] == "NOT_PROBED"
    assert result["healthy_source_count"] == 0
    assert result["degraded_source_count"] == 0
    assert result["lkg_required"] is False
    assert result["market_intelligence_only"] is True
    assert result["fit_scores_are_not_eligibility"] is True
    assert all(result[key] is False for key in MATERIAL_FLAGS)
    assert result["publication_effect"] == "NONE"
    assert result["exact_call_or_topic_identifier_required"] is True
    assert result["current_official_exact_endpoint_required"] is True
    assert result["semantic_reconciliation_required"] is True
    assert result["field_scoped_material_admission_required"] is True
    assert {
        "exact_call_or_topic_identifier",
        "current_official_exact_call_or_topic_endpoint",
        "explicit_current_official_call_status",
        "semantic_reconciliation",
        "field_scoped_material_admission",
    }.issubset(set(result["missing_for_open_confirmation"]))

    programmes = {row["programme_family"]: row for row in result["programme_intelligence"]}
    assert set(programmes) == {"Horizon Europe", "European Innovation Council"}
    assert "SME" in programmes["Horizon Europe"]["applicant_fit_tags"]
    assert "RESEARCH_ORGANISATION" in programmes["Horizon Europe"]["applicant_fit_tags"]
    assert "STARTUP" in programmes["European Innovation Council"]["applicant_fit_tags"]
    assert "DEEP_TECH" in programmes["European Innovation Council"]["applicant_fit_tags"]
    assert "HORIZON_EUROPE_2028_2034_PROPOSAL" in programmes["Horizon Europe"]["pipeline_signals"]
    assert "EIC_WORK_PROGRAMME_2026" in programmes["European Innovation Council"]["pipeline_signals"]
    for row in programmes.values():
        assert row["market_intelligence_only"] is True
        assert row["fit_score_is_not_eligibility"] is True
        assert 0.0 <= row["fit_score"] <= 1.0

    for source in result["sources"]:
        assert source["source_health"]["health_state"] == "NOT_PROBED"
        assert source["material_fact_use"] is False
        assert source["observation_state"] != "OPEN_CALL"
        assert len(source["source_semantic_fingerprint"]) == 64

    _expect_registry_failure(lambda data: data["policy"].__setitem__("open_call_authorized", True))
    _expect_registry_failure(lambda data: data["policy"].__setitem__("semantic_reconciliation_required", False))
    _expect_registry_failure(lambda data: data["sources"][3].__setitem__("observation_state", "OPEN_CALL"))
    _expect_registry_failure(lambda data: data["sources"][0].__setitem__("material_fact_use", True))
    _expect_registry_failure(lambda data: data["sources"][0].__setitem__("authority_url", "http://example.com/horizon"))
    _expect_registry_failure(lambda data: data["sources"][2].__setitem__("programme_family", "Unknown Programme"))

    print(json.dumps({
        "status": "PASS",
        "schema": result["schema"],
        "source_count": result["source_count"],
        "programme_families": result["programme_families"],
        "open_call_authorized": result["open_call_authorized"],
        "publication_effect": result["publication_effect"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
