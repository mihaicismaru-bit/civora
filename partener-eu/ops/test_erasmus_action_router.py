#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "partener-eu" / "ingest"))

import erasmus_action_router as router


def _write_registry(data: dict) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    with handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return Path(handle.name)


def _expect_registry_fail(data: dict, needle: str) -> None:
    path = _write_registry(data)
    try:
        router.load_registry(path)
    except ValueError as exc:
        assert needle in str(exc), str(exc)
    else:
        raise AssertionError("expected fail-closed Erasmus registry rejection")
    finally:
        path.unlink(missing_ok=True)


def _assert_non_authorizing(result: dict) -> None:
    assert result["schema"] == "PARTENER_EU_ERASMUS_ACTION_ROUTER_V2"
    assert result["adapter_id"] == "ERASMUS_ACTION_ROUTER_V2"
    assert result["parser_version"] == "ERASMUS_ACTION_ROUTER_V2"
    assert result["source_family"] == "EU_DIRECT"
    assert result["programme_family"] == "Erasmus+"
    assert result["observation_state"] == "APPLICATION_ROUTE_INTELLIGENCE"
    assert result["market_intelligence_only"] is True
    assert result["publication_effect"] == "NONE"
    for key in router.MATERIAL_FLAGS:
        assert result[key] is False
    assert result["exact_action_endpoint_required"] is True
    assert result["exact_call_or_topic_identifier_required"] is True
    assert result["semantic_reconciliation_required"] is True
    assert "exact_action_or_call_identifier" in result["missing_for_open_confirmation"]
    assert "semantic_reconciliation" in result["missing_for_open_confirmation"]
    assert "field_scoped_material_admission" in result["missing_for_open_confirmation"]
    assert len(result["registry_sha256"]) == 64
    assert len(result["route_semantic_fingerprint"]) == 64


def _source_ids(result: dict) -> set[str]:
    return {str(row.get("source_id")) for row in result.get("evidence") or []}


def main() -> None:
    registry, _ = router.load_registry()
    sources = {row["id"]: row for row in registry["evidence_sources"]}
    assert sources["ERASMUS-PROGRAMME-GUIDE-HOW-TO-APPLY"]["authority_url"].endswith("/programme-guide/part-c/how-to-apply")
    assert "ERASMUS-OFFICIAL-WHERE-TO-APPLY" in sources

    central = router.resolve(
        management_mode="CENTRALISED_EACEA",
        run_id="TEST-ERASMUS-CENTRAL",
        action_reference_hint="ERASMUS-EDU-2026-PI-ALL-INNO-EDU-ENTERP",
        observed_at="2026-09-02T12:00:00Z",
        live=False,
    )
    _assert_non_authorizing(central)
    assert central["management_mode"] == "CENTRALISED_EACEA"
    assert central["route"]["registration_identifier_kind"] == "PIC"
    assert central["route"]["route_class"] == "CENTRALISED_EU_DIRECT"
    assert central["route"]["application_gateway_url"].startswith("https://ec.europa.eu/info/funding-tenders/")
    assert central["evidence_source_count"] == 4
    assert {
        "ERASMUS-OFFICIAL-HOW-TO-APPLY",
        "ERASMUS-OFFICIAL-WHERE-TO-APPLY",
        "ERASMUS-PROGRAMME-GUIDE-HOW-TO-APPLY",
        "ERASMUS-EACEA-HOW-TO-GET-GRANT",
    } == _source_ids(central)
    assert central["source_health_state"] == "NOT_PROBED"
    assert central["lkg_required"] is False
    assert central["action_reference_hint_authority"] == "DISCOVERY_HINT_ONLY_NOT_CALL_IDENTIFIER"

    decentral = router.resolve(
        management_mode="DECENTRALISED_NATIONAL_AGENCY",
        run_id="TEST-ERASMUS-NA",
        observed_at="2026-09-02T12:00:00Z",
        live=False,
    )
    _assert_non_authorizing(decentral)
    assert decentral["management_mode"] == "DECENTRALISED_NATIONAL_AGENCY"
    assert decentral["route"]["registration_identifier_kind"] == "OID"
    assert decentral["route"]["route_class"] == "DECENTRALISED_NATIONAL_AGENCY"
    assert decentral["route"]["application_gateway_url"] == "https://webgate.ec.europa.eu/erasmus-esc/index/"
    assert decentral["evidence_source_count"] == 3
    assert "ERASMUS-EACEA-HOW-TO-GET-GRANT" not in _source_ids(decentral)
    assert decentral["action_reference_hint"] is None

    try:
        router.resolve(
            management_mode="AUTO_GUESS",
            run_id="TEST-ERASMUS-BAD-MODE",
            observed_at="2026-09-02T12:00:00Z",
        )
    except ValueError as exc:
        assert "unsupported Erasmus management mode" in str(exc)
    else:
        raise AssertionError("unknown Erasmus management mode must fail closed")

    bad = copy.deepcopy(registry)
    bad["policy"]["open_call_authorized"] = True
    _expect_registry_fail(bad, "became authorizing")

    bad = copy.deepcopy(registry)
    bad["policy"]["call_alert_authorized"] = True
    _expect_registry_fail(bad, "became authorizing")

    bad = copy.deepcopy(registry)
    bad["management_modes"]["CENTRALISED_EACEA"]["exact_action_endpoint_required"] = False
    _expect_registry_fail(bad, "exact action endpoint requirement relaxed")

    bad = copy.deepcopy(registry)
    bad["management_modes"]["DECENTRALISED_NATIONAL_AGENCY"]["application_gateway_url"] = "http://webgate.ec.europa.eu/erasmus-esc/index/"
    _expect_registry_fail(bad, "application gateway drift")

    bad = copy.deepcopy(registry)
    bad["evidence_sources"][0]["authority_url"] = "https://example.invalid/resources-and-tools/how-to-apply"
    _expect_registry_fail(bad, "official host not allowlisted")

    bad = copy.deepcopy(registry)
    bad["management_modes"]["CENTRALISED_EACEA"]["route_basis_source_ids"].append("MISSING-SOURCE")
    _expect_registry_fail(bad, "route basis source drift")

    original_probe = router._probe_source
    try:
        def fake_probe(source: dict, *, timeout: float) -> dict:
            return {
                "health_state": "HEALTHY",
                "lkg_required": False,
                "requested_url": source["authority_url"],
                "final_url": source["authority_url"],
                "http_status": 200,
                "content_type": "text/html",
                "raw_sha256": "a" * 64,
                "raw_size_bytes": 1000,
                "missing_marker_groups": [],
                "error": None,
            }

        router._probe_source = fake_probe
        live = router.resolve(
            management_mode="CENTRALISED_EACEA",
            run_id="TEST-ERASMUS-LIVE-SYNTHETIC",
            observed_at="2026-09-02T12:00:00Z",
            live=True,
        )
        _assert_non_authorizing(live)
        assert live["healthy_evidence_source_count"] == 4
        assert live["degraded_evidence_source_count"] == 0
        assert live["source_health_state"] == "HEALTHY"
        assert live["lkg_required"] is False
        assert all(row["source_health"]["raw_sha256"] == "a" * 64 for row in live["evidence"])

        def degraded_probe(source: dict, *, timeout: float) -> dict:
            row = fake_probe(source, timeout=timeout)
            if source["id"] == "ERASMUS-EACEA-HOW-TO-GET-GRANT":
                row.update({
                    "health_state": "DEGRADED",
                    "lkg_required": True,
                    "final_url": None,
                    "http_status": 503,
                    "raw_sha256": None,
                    "raw_size_bytes": 0,
                    "error": "synthetic transport failure",
                })
            return row

        router._probe_source = degraded_probe
        degraded = router.resolve(
            management_mode="CENTRALISED_EACEA",
            run_id="TEST-ERASMUS-LIVE-DEGRADED",
            observed_at="2026-09-02T12:00:00Z",
            live=True,
        )
        _assert_non_authorizing(degraded)
        assert degraded["source_health_state"] == "DEGRADED"
        assert degraded["degraded_evidence_source_count"] == 1
        assert degraded["lkg_required"] is True
    finally:
        router._probe_source = original_probe

    print(json.dumps({
        "status": "PASS",
        "adapter_id": central["adapter_id"],
        "central_route": central["route"]["route_class"],
        "central_registration": central["route"]["registration_identifier_kind"],
        "central_evidence_sources": central["evidence_source_count"],
        "decentral_route": decentral["route"]["route_class"],
        "decentral_registration": decentral["route"]["registration_identifier_kind"],
        "decentral_evidence_sources": decentral["evidence_source_count"],
        "open_call_authorized": central["open_call_authorized"],
        "call_alert_authorized": central["call_alert_authorized"],
        "publication_effect": central["publication_effect"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
