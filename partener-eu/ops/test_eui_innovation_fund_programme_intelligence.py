#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "partener-eu" / "ingest"))

import eui_innovation_fund_programme_intelligence as mod


def _write_registry(data: dict) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False)
    with handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    return Path(handle.name)


def expect_fail(label: str, fn) -> None:
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(f"expected fail-closed rejection: {label}")


def main() -> int:
    registry, _ = mod.load_registry()
    assert registry["registry_id"] == "EUI_INNOVATION_FUND_PROGRAMME_INTELLIGENCE_REGISTRY_V1"
    assert len(registry["sources"]) == 5
    assert [s["programme_family"] for s in registry["sources"]].count("European Urban Initiative") == 2
    assert [s["programme_family"] for s in registry["sources"]].count("Innovation Fund") == 3

    first = mod.acquire(run_id="regression-1", observed_at="2026-09-02T19:50:00Z", live=False)
    second = mod.acquire(run_id="regression-2", observed_at="2026-09-02T19:50:00Z", live=False)
    assert first["semantic_fingerprint"] == second["semantic_fingerprint"]
    assert first["source_count"] == 5
    assert first["source_health_state"] == "NOT_PROBED"
    assert first["market_intelligence_only"] is True
    assert first["fit_scores_are_not_eligibility"] is True
    assert first["publication_effect"] == "NONE"
    assert first["open_call_authorized"] is False
    assert first["closed_call_authorized"] is False
    assert first["deadline_authorized"] is False
    assert first["budget_authorized"] is False
    assert first["eligibility_authorized"] is False
    assert first["publish_authorized"] is False
    assert first["distribution_authorized"] is False
    assert first["call_alert_authorized"] is False
    assert first["canonical_corpus_mutation"] is False
    assert first["field_scoped_material_admission_required"] is True
    assert "exact_call_or_topic_identifier" in first["missing_for_open_confirmation"]

    by_programme = {row["programme_family"]: row for row in first["programme_intelligence"]}
    assert set(by_programme) == {"European Urban Initiative", "Innovation Fund"}
    assert "URBAN_AUTHORITY" in by_programme["European Urban Initiative"]["applicant_fit_tags"]
    assert "INNOVATIVE_ACTIONS" in by_programme["European Urban Initiative"]["market_signals"]
    assert "INDUSTRIAL_DECARBONISATION" in by_programme["Innovation Fund"]["market_signals"]
    assert "COMPANY" in by_programme["Innovation Fund"]["applicant_fit_tags"]
    assert all(row["fit_score_is_not_eligibility"] is True for row in by_programme.values())

    bad = copy.deepcopy(registry)
    bad["policy"]["open_call_authorized"] = True
    p = _write_registry(bad)
    try:
        expect_fail("registry self-authorizes OPEN", lambda: mod.load_registry(p))
    finally:
        p.unlink(missing_ok=True)

    bad = copy.deepcopy(registry)
    bad["sources"][0]["observation_state"] = "OPEN_CALL"
    p = _write_registry(bad)
    try:
        expect_fail("programme source promoted to OPEN_CALL", lambda: mod.load_registry(p))
    finally:
        p.unlink(missing_ok=True)

    bad = copy.deepcopy(registry)
    bad["sources"][0]["authority_url"] = "http://portico.urban-initiative.eu/urban-panorama/european-urban-initiative"
    p = _write_registry(bad)
    try:
        expect_fail("non-HTTPS authority", lambda: mod.load_registry(p))
    finally:
        p.unlink(missing_ok=True)

    bad = copy.deepcopy(registry)
    bad["sources"][3]["authority_url"] = "https://example.com/innovation-fund"
    p = _write_registry(bad)
    try:
        expect_fail("authority host drift", lambda: mod.load_registry(p))
    finally:
        p.unlink(missing_ok=True)

    bad = copy.deepcopy(registry)
    bad["sources"][1]["material_fact_use"] = True
    p = _write_registry(bad)
    try:
        expect_fail("call index became material", lambda: mod.load_registry(p))
    finally:
        p.unlink(missing_ok=True)

    source = copy.deepcopy(registry["sources"][0])
    with mock.patch.object(mod, "urlopen", side_effect=URLError("synthetic transport failure")):
        health = mod._probe_source(source, timeout=0.1)
    assert health["health_state"] == "DEGRADED_TRANSPORT"
    assert health["lkg_required"] is True
    assert health["raw_sha256"] is None
    assert health["final_url"] is None

    tampered = copy.deepcopy(first)
    tampered["open_call_authorized"] = True
    expect_fail("normalized result self-authorizes OPEN", lambda: mod.validate_result(tampered))

    tampered = copy.deepcopy(first)
    tampered["programme_intelligence"][0]["fit_score_is_not_eligibility"] = False
    expect_fail("fit score becomes eligibility", lambda: mod.validate_result(tampered))

    print(json.dumps({
        "adapter": mod.PARSER_VERSION,
        "sources": first["source_count"],
        "programmes": sorted(by_programme),
        "open_call_authorized": first["open_call_authorized"],
        "publication_effect": first["publication_effect"],
        "regression": "PASS",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
