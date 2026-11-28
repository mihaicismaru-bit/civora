#!/usr/bin/env python3
import datetime as dt
import importlib.util
import json
import pathlib
import tempfile


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "ingest" / "intelligence_index.py"
spec = importlib.util.spec_from_file_location("intelligence_index", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def fixture_state(root):
    write(root / "afir_corpus.json", {
        "schemaVersion": 1, "status": "PASS", "generatedAt": "2026-08-12T08:00:00Z",
        "policy": {"failClosed": True, "materialFactsAutoPromoted": False},
        "items": [
            {"url": "https://www.afir.ro/finantare/test/", "title": "Test AFIR", "observedAt": "2026-08-12T08:00:00Z", "sha256": "a", "contentType": "text/html", "textExtracted": True, "materialChangeCandidate": False, "materialFactAction": "NONE"},
            {"url": "https://afir.ro/finantare/test", "title": "Duplicate", "observedAt": "2026-08-12T08:00:00Z", "sha256": "a", "contentType": "text/html", "textExtracted": True, "materialChangeCandidate": False, "materialFactAction": "NONE"},
            {"url": "https://www.afir.ro/doc/test.pdf", "title": "Ghid", "observedAt": "2026-08-12T08:00:00Z", "sha256": "b", "contentType": "application/pdf", "textExtracted": True, "materialChangeCandidate": True, "materialFactAction": "RESOLUTION_TASK_ONLY"},
        ],
    })
    write(root / "peo_calendar_state.json", {
        "status": "OK_OFFICIAL_OIR_COPY", "directMipeVerified": False,
        "lastRun": {"observedAt": "2026-08-12T08:00:00Z"},
        "retrievalSource": "https://oirvest.ro/calendar.xlsx",
        "canonicalContainer": "https://mfe.gov.ro/peos/calendar-lansari-apeluri/",
        "items": [{"id": "c1", "programme": "PEO", "title": "Apel planificat", "plannedLaunch": "2026-10-01", "plannedClose": "2026-12-01", "budget": "100", "applicants": "UAT", "materialization": "NOT_YET_VERIFIED"}],
    })
    write(root / "mipe_state.json", {
        "status": "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED", "items": [],
        "lastRun": {"observedAt": "2026-08-12T08:00:00Z", "sourceAvailable": False},
    })
    write(root / "source_registry_health.json", {
        "schema_version": "1.2",
        "observed_at": "2026-08-12T08:00:00Z",
        "summary": {"total": 3, "fail": 1, "resolution_tasks_required": 1},
        "sources": [
            {"id": "SRC-MYSMIS-CALLS", "url": "https://resurse.mysmis2021.gov.ro/calls", "selected_url": "https://resurse.mysmis2021.gov.ro/calls", "final_url": "https://resurse.mysmis2021.gov.ro/calls", "tier": "T1", "health": "PASS", "semantic_hash_changed": False, "resolution_task_required": False, "semantic_sha256": "b" * 64, "raw_sha256": "a" * 64, "ok": True, "content_quality_ok": True, "quarantined": False},
            {"id": "SRC-OIRVEST-PEO", "url": "https://oirvest.ro/peo-2021-2027/", "selected_url": "https://oirvest.ro/peo-2021-2027/", "final_url": "https://oirvest.ro/peo-2021-2027/", "tier": "T1B", "health": "PASS", "semantic_hash_changed": True, "resolution_task_required": True, "semantic_sha256": "d" * 64, "raw_sha256": "c" * 64, "ok": True, "content_quality_ok": True, "quarantined": False},
            {"id": "SRC-DISCOVERY-ONLY", "tier": "T1", "health": "FAIL", "semantic_hash_changed": False, "resolution_task_required": False},
        ],
    })
    write(root / "source_registry.json", {
        "schema_version": "1.2",
        "sources": [
            {"id": "SRC-MYSMIS-CALLS", "tier": "T1", "class": "authoritative_call_registry", "owner": "MySMIS", "url": "https://resurse.mysmis2021.gov.ro/calls", "programmes": ["2021-2027"], "material_fact_use": True},
            {"id": "SRC-OIRVEST-PEO", "tier": "T1B", "class": "official_intermediate_body", "owner": "OIR Vest", "url": "https://oirvest.ro/peo-2021-2027/", "programmes": ["PEO"], "material_fact_use": True},
            {"id": "SRC-DISCOVERY-ONLY", "tier": "T1", "class": "official_discovery_index", "owner": "Discovery", "url": "https://example.gov.ro/discovery", "programmes": ["2021-2027"], "material_fact_use": False},
        ],
    })


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        fixture_state(root)
        reference = dt.datetime(2026, 8, 12, 10, tzinfo=dt.timezone.utc)
        registry_path = root / "source_registry.json"
        # PEO calendar dates are estimates, not actual call lifecycle. Keep
        # historical rows searchable without presenting them as future launches.
        for launch, close, expected in (
            ("2025-10-01T00:00:00", "2025-12-31T00:00:00", "HISTORICAL_ESTIMATE"),
            ("2026-08-13", "2026-12-01", "FUTURE_LAUNCH_ESTIMATE"),
            ("2026-08-12", "2026-08-12", "CURRENT_ESTIMATE_WINDOW"),
            ("2026-08-01", "2026-08-12", "CURRENT_ESTIMATE_WINDOW"),
            ("2026-08-13", "2026-08-12", "UNKNOWN_ESTIMATE_WINDOW"),
            (None, "2026-08-12", "UNKNOWN_ESTIMATE_WINDOW"),
            ("2026-08-13", None, "UNKNOWN_ESTIMATE_WINDOW"),
            ("2026-02-30", "2026-12-01", "UNKNOWN_ESTIMATE_WINDOW"),
            ("2026-08-13T10:00:00", "2026-12-01", "UNKNOWN_ESTIMATE_WINDOW"),
        ):
            state = {
                "status": "OK_OFFICIAL_OIR_COPY",
                "lastRun": {"observedAt": "2026-08-12T08:00:00Z"},
                "items": [{"id": "test", "title": "Estimate",
                           "plannedLaunch": launch, "plannedClose": close}],
            }
            _, calendar_rows = mod.peo_calendar_records(state, reference, {})
            assert len(calendar_rows) == 1
            row = calendar_rows[0]
            assert row["planningHorizon"] == expected, row
            assert row["plannedLaunch"] == launch and row["plannedClose"] == close
            assert row["recordType"] == "PLANNED_CALL"
            assert row["decisionUse"] == "PLANNING_ONLY"
            assert row["publishMaterialFacts"] is False
        # Romanian local date can already be tomorrow relative to UTC.
        boundary = dt.datetime(2026, 8, 12, 22, tzinfo=dt.timezone.utc)
        assert mod.planning_horizon("2026-08-12", "2026-08-12", boundary) == "HISTORICAL_ESTIMATE"

        # The domestic-only fixture deliberately lacks the international roster.
        # Test the full production contract separately before using a local
        # reduced contract for the pre-existing domestic behavior assertions.
        full_contract = json.loads(mod.DEFAULT_CONTRACT.read_text(encoding="utf-8"))
        international = {"EU_DIRECT", "BRUSSELS", "EEA_NORWAY", "INTERREG", "PROGRAMMING_PIPELINE"}
        domestic = {"MIPE", "MYSMIS", "AFIR", "OI_ADR", "CALENDARS"}
        assert set(full_contract["requiredSourceFamilies"]) == domestic | international
        incomplete = mod.compile_with_replay(root, reference, source_registry_path=registry_path)
        assert set(incomplete["dataPlane"]["coverage"]["missingRequiredFamilies"]) == international
        assert incomplete["dataPlane"]["coverage"]["status"] == "FAIL"
        assert incomplete["readiness"] == "BLOCKED_CONTRACT_FAIL_CLOSED"
        assert incomplete["summary"]["materialFactsAutopromoted"] == 0

        extended_registry = json.loads(registry_path.read_text(encoding="utf-8"))
        for source_id, programme, source_class, families in (
            ("SRC-EU-TEST-ROSTER", "EU direct programmes", "official_direct_call_registry", ["EU_DIRECT", "BRUSSELS"]),
            ("SRC-EEA-TEST-ROSTER", "EEA Grants 2021-2028", "official_programming_framework", ["EEA_NORWAY"]),
            ("SRC-INTERREG-TEST-ROSTER", "Interreg Danube Region Programme 2021-2027", "official_interreg_call_registry", ["INTERREG"]),
            ("SRC-MFF-TEST-ROSTER", "MFF 2028-2034", "official_programming_pipeline", ["PROGRAMMING_PIPELINE"]),
        ):
            extended_registry["sources"].append({
                "id": source_id, "tier": "T1", "class": source_class,
                "url": "https://official.example/" + source_id,
                "programmes": [programme], "source_families": families,
                "material_fact_use": False,
            })
        extended_path = root / "extended_registry.json"
        write(extended_path, extended_registry)
        complete = mod.compile_with_replay(root, reference, source_registry_path=extended_path)
        coverage = complete["dataPlane"]["coverage"]
        assert coverage["status"] == "PASS", coverage
        assert coverage["missingRequiredFamilies"] == []
        assert complete["dataPlane"]["contract"]["status"] == "PASS"
        families = {row["family"]: row for row in coverage["requiredFamilies"]}
        for family in international:
            assert families[family]["status"] == "PRESENT_DEGRADED", families[family]
            assert families[family]["availableSourceIds"] == []
        assert complete["summary"]["recordCount"] == incomplete["summary"]["recordCount"]
        assert complete["summary"]["materialFactsAutopromoted"] == 0
        assert all(gate["publishMaterialFacts"] is False
                   for gate in complete["dataPlane"]["dependencyIsolation"]["gates"])
        assert complete["dataPlane"]["replay"]["byteEquivalent"] is True

        # A registered roster is not a verified acquisition. Remove each
        # family independently to ensure no required family can disappear.
        for family in sorted(international):
            reduced = json.loads(json.dumps(extended_registry))
            for definition in reduced["sources"]:
                definition["source_families"] = [
                    value for value in definition.get("source_families", []) if value != family
                ]
            write(extended_path, reduced)
            absent = mod.compile_with_replay(root, reference, source_registry_path=extended_path)
            assert absent["dataPlane"]["coverage"]["missingRequiredFamilies"] == [family]
            assert absent["readiness"] == "BLOCKED_CONTRACT_FAIL_CLOSED"
            assert absent["summary"]["materialFactsAutopromoted"] == 0

        domestic_contract = dict(full_contract)
        domestic_contract["requiredSourceFamilies"] = [
            family for family in full_contract["requiredSourceFamilies"] if family in domestic
        ]
        domestic_contract_path = root / "domestic_contract.json"
        write(domestic_contract_path, domestic_contract)
        index = mod.compile_with_replay(root, reference, contract_path=domestic_contract_path, source_registry_path=registry_path)
        assert index["contract"]["status"] == "PASS", index["contract"]
        assert index["readiness"] == "DEGRADED_FAIL_CLOSED"
        assert index["dataPlane"]["contract"]["status"] == "PASS"
        assert index["dataPlane"]["coverage"]["status"] == "PASS"
        assert index["dataPlane"]["coverage"]["missingRequiredFamilies"] == []
        assert index["dataPlane"]["replay"]["status"] == "PASS"
        assert index["dataPlane"]["replay"]["byteEquivalent"] is True
        assert index["summary"]["duplicatesRemoved"] == 1
        assert index["summary"]["materialFactsAutopromoted"] == 0
        assert index["summary"]["recordCount"] == 3
        assert "MIPE_CORPUS" in index["summary"]["unavailableT1Sources"]
        failed_mipe = next(row for row in index["sources"] if row["id"] == "MIPE_CORPUS")
        assert failed_mipe["lastAttemptFreshness"]["status"] == "CURRENT"
        assert failed_mipe["freshness"]["status"] == "UNKNOWN"
        assert "MIPE_CORPUS" in index["summary"]["materialStaleOrUnknownSources"]

        # Future-dated receipts must not be clamped to a current zero age.
        for timestamp, expected, age in (
            ("2026-08-12T10:00:01Z", "UNKNOWN", None),
            ("2026-08-12T13:00:00+02:00", "UNKNOWN", None),
            ("2026-08-12T10:00:00Z", "CURRENT", 0),
            ("2026-08-12T06:00:00Z", "CURRENT", 4),
            ("2026-08-12T05:59:59Z", "STALE", 4),
            ("invalid", "UNKNOWN", None),
            (None, "UNKNOWN", None),
        ):
            assert mod.freshness(timestamp, reference, 4) == {
                "status": expected, "ageHours": age, "maxAgeHours": 4,
            }

        # A fresh attempt, an available-but-degraded source, and a stale
        # successful response must never turn LKG into current evidence.
        for status, available, observed, expected, decision in (
            ("OK", True, "2026-08-12T08:00:00Z", "CURRENT", "OFFICIAL_EVIDENCE_INDEX"),
            ("OK", False, "2026-08-12T08:00:00Z", "UNKNOWN", "LAST_KNOWN_GOOD_DISCOVERY_ONLY"),
            ("DEGRADED_LAST_KNOWN_GOOD_PRESERVED", True, "2026-08-12T08:00:00Z", "UNKNOWN", "LAST_KNOWN_GOOD_DISCOVERY_ONLY"),
            ("OK", "false", "2026-08-12T08:00:00Z", "UNKNOWN", "LAST_KNOWN_GOOD_DISCOVERY_ONLY"),
            ("OK", True, "2026-08-11T08:00:00Z", "STALE", "LAST_KNOWN_GOOD_DISCOVERY_ONLY"),
            ("OK", True, "2026-08-12T10:00:01Z", "UNKNOWN", "LAST_KNOWN_GOOD_DISCOVERY_ONLY"),
        ):
            state = {
                "status": status,
                "lastRun": {"observedAt": observed, "sourceAvailable": available},
                "items": [{"url": "https://mfe.gov.ro/ghid/sample", "title": "Sample", "observedAt": observed}],
            }
            source, records = mod.mipe_records(state, reference, {"freshnessSlaHours": 4})
            assert source["freshness"]["status"] == expected, source
            assert records[0]["freshness"] == expected
            assert records[0]["decisionUse"] == decision
            assert records[0]["publishMaterialFacts"] is False
            assert records[0]["observedAt"] == observed
        # AFIR LKG must remain searchable but cannot be labelled current evidence.
        # The corpus timestamp and material resolution candidate are preserved.
        for status, observed, expected, decision in (
            ("PASS", "2026-08-12T08:00:00Z", "CURRENT", "OFFICIAL_EVIDENCE_INDEX"),
            ("PASS", "2026-08-11T08:00:00Z", "STALE", "LAST_KNOWN_GOOD_DISCOVERY_ONLY"),
            ("FAIL", "2026-08-12T08:00:00Z", "CURRENT", "LAST_KNOWN_GOOD_DISCOVERY_ONLY"),
            ("DEGRADED_LAST_KNOWN_GOOD_PRESERVED", "2026-08-12T08:00:00Z", "CURRENT", "LAST_KNOWN_GOOD_DISCOVERY_ONLY"),
            ("PASS", None, "UNKNOWN", "LAST_KNOWN_GOOD_DISCOVERY_ONLY"),
            ("PASS", "2026-08-12T10:00:01Z", "UNKNOWN", "LAST_KNOWN_GOOD_DISCOVERY_ONLY"),
        ):
            source, records = mod.afir_records({
                "status": status, "generatedAt": observed,
                "items": [{"url": "https://www.afir.ro/doc/test.pdf",
                           "sha256": "preserved", "observedAt": observed, "materialChangeCandidate": True}],
            }, reference, {"freshnessSlaHours": 4})
            assert source["freshness"]["status"] == expected
            assert len(records) == 1
            row = records[0]
            assert row["decisionUse"] == decision
            assert row["observedAt"] == observed
            assert row["fingerprint"] == "preserved"
            assert row["materialFactAction"] == "RESOLUTION_REQUIRED"
            assert row["publishMaterialFacts"] is False

        # A successful fresh corpus cannot refresh stale, future, malformed,
        # or missing per-item observations. Preserve the actual observation.
        for timestamp, expected in (
            ("2026-08-12T08:30:00Z", "CURRENT"),
            ("2026-08-12T06:00:00Z", "CURRENT"),
            ("2026-08-12T05:59:59Z", "STALE"),
            ("2026-08-12T10:00:01Z", "UNKNOWN"),
            ("invalid", "UNKNOWN"),
            (None, "UNKNOWN"),
        ):
            for family, build, state, url in (
                ("AFIR", mod.afir_records,
                 {"status": "PASS", "generatedAt": "2026-08-12T09:00:00Z"},
                 "https://afir.ro/doc/sample.pdf"),
                ("MIPE", mod.mipe_records,
                 {"status": "OK", "lastRun": {"sourceAvailable": True,
                                               "observedAt": "2026-08-12T09:00:00Z"}},
                 "https://mfe.gov.ro/ghid/sample"),
            ):
                item = {"url": url, "title": "Sample", "sha256": "preserved"}
                if timestamp is not None:
                    item["observedAt"] = timestamp
                state["items"] = [item]
                source, records = build(state, reference, {"freshnessSlaHours": 4})
                assert source["freshness"]["status"] == "CURRENT", family
                assert len(records) == 1
                row = records[0]
                assert row["observedAt"] == timestamp
                assert row["freshness"] == expected, (family, row)
                assert row["decisionUse"] == (
                    "OFFICIAL_EVIDENCE_INDEX" if expected == "CURRENT"
                    else "LAST_KNOWN_GOOD_DISCOVERY_ONLY"
                )
                assert row["fingerprint"] == "preserved"
                assert row["publishMaterialFacts"] is False

        # The actual MIPE LKG registry lives on the MySMIS reporting host.
        # Keep the exact index searchable; it is not an exact call endpoint.
        mysmis_url = ("https://reporting.mysmis2021.gov.ro/ords/repo_bo/r/mysmis-2021/"
                      "finantari-programe-2021-2027")
        for status, available, item_at in (
            ("DEGRADED_LAST_KNOWN_GOOD_PRESERVED", False, "2026-08-01T08:00:00Z"),
            ("OK", True, "2026-08-12T08:00:00Z"),
        ):
            _, retained = mod.mipe_records({
                "status": status,
                "lastRun": {"sourceAvailable": available, "observedAt": "2026-08-12T08:00:00Z"},
                "items": [
                    {"url": mysmis_url, "title": "Registry", "observedAt": item_at,
                     "sha256": "retained"},
                    {"url": mysmis_url + "?session=123", "title": "Session"},
                    {"url": mysmis_url + "/other", "title": "Other"},
                    {"url": mysmis_url.replace(".gov.ro/", ".gov.ro.example.com/"), "title": "Spoof"},
                ],
            }, reference, {"freshnessSlaHours": 4})
            assert len(retained) == 1, retained
            row = retained[0]
            assert row["canonicalUrl"] == mysmis_url
            assert row["observedAt"] == item_at
            assert row["fingerprint"] == "retained"
            assert row["programme"] == "MIPE / MySMIS"
            assert row["decisionUse"] == "LAST_KNOWN_GOOD_DISCOVERY_ONLY"
            assert row["publishMaterialFacts"] is False
            assert row["provenance"][0]["url"] == mysmis_url

        material = next(row for row in index["records"] if row.get("materialChangeCandidate"))
        assert material["materialFactAction"] == "RESOLUTION_REQUIRED"
        assert material["publishMaterialFacts"] is False
        planned = next(row for row in index["records"] if row["recordType"] == "PLANNED_CALL")
        assert planned["decisionUse"] == "PLANNING_ONLY"
        assert planned["materialization"] == "NOT_YET_VERIFIED"
        gates = {row["sourceId"]: row for row in index["dataPlane"]["dependencyIsolation"]["gates"]}
        assert gates["MIPE_CORPUS"]["materialFactGate"] == "BLOCKED_SOURCE_DEPENDENCIES"
        assert gates["MIPE_CORPUS"]["affectedScopes"] == ["MIPE_MANAGED_PROGRAMMES"]
        assert gates["AFIR_CORPUS"]["materialFactGate"] == "RECONCILIATION_REQUIRED"
        assert gates["AFIR_CORPUS"]["blocksUnrelatedSources"] is False
        assert gates["SRC-DISCOVERY-ONLY"]["availability"] == "UNAVAILABLE_LAST_KNOWN_GOOD"
        assert gates["SRC-DISCOVERY-ONLY"]["materialFactGate"] == "DISCOVERY_ONLY"
        assert "SRC-DISCOVERY-ONLY" not in index["summary"]["unavailableT1Sources"]
        assert "SRC-DISCOVERY-ONLY" in index["summary"]["operationalUnavailableT1Sources"]
        assert index["dataPlane"]["dependencyIsolation"]["globalStop"] is False

        # Declared family tags survive projection, and programming sources
        # cannot become material call authorities even if misconfigured.
        definitions = [
            ("SRC-EU-TEST", "official_direct_call_registry", ["EU_DIRECT", "BRUSSELS", "CALL_REGISTRY"], False),
            ("SRC-EEA-TEST", "official_programming_framework", ["EEA_NORWAY", "PROGRAMMING_PIPELINE"], True),
            ("SRC-INTERREG-TEST", "official_interreg_call_registry", ["INTERREG", "CBC"], False),
            ("SRC-INTERREG-FUTURE", "official_programming_pipeline", ["INTERREG", "PROGRAMMING_PIPELINE"], True),
            ("SRC-ADRCENTRU-CONSULT", "official_intermediate_body_consultation_index", [], True),
            ("SRC-EU-TAGGED-PLAN", "official_direct_programme_gateway", ["PROGRAMMING_PIPELINE"], True),
            ("SRC-MYSMIS-TEST", "authoritative_call_registry", ["CALL_REGISTRY", "CALL_REGISTRY"], False),
        ]
        registry_fixture = {"sources": [
            {"id": source_id, "class": kind, "source_families": tags,
             "tier": "T1", "material_fact_use": True,
             "url": "https://official.example/" + source_id}
            for source_id, kind, tags, _ in definitions
        ]}
        health_fixture = {"sources": [
            {"id": source_id, "health": "PASS", "ok": True, "content_quality_ok": True,
             "quarantined": False, "raw_sha256": "a" * 64, "semantic_sha256": "b" * 64,
             "url": "https://official.example/" + source_id,
             "selected_url": "https://official.example/" + source_id,
             "final_url": "https://official.example/" + source_id}
            for source_id, _, _, _ in definitions
        ]}
        inventory = mod.build_source_inventory(
            [{"id": "VERIFIED_SOURCE_REGISTRY", "freshness": {"status": "CURRENT"}}],
            registry_fixture, health_fixture, {}, {}
        )
        by_id = {row["id"]: row for row in inventory}
        for source_id, _, tags, planning in definitions:
            row = by_id[source_id]
            assert set(tags) <= set(row["sourceFamilies"]), row
            assert row["sourceFamilies"] == sorted(set(row["sourceFamilies"]))
            assert row["planningOnly"] is planning
            gate = mod.dependency_gate(row)
            assert gate["materialFactGate"] == (
                "PLANNING_ONLY" if planning else "RECONCILIATION_REQUIRED"
            ), gate
            assert gate["publishMaterialFacts"] is False
        assert "MYSMIS" in by_id["SRC-MYSMIS-TEST"]["sourceFamilies"]
        assert "OI_ADR" in by_id["SRC-ADRCENTRU-CONSULT"]["sourceFamilies"]
        assert mod.registry_families({"source_families": "PROGRAMMING_PIPELINE"}) == []
        assert mod.registry_families({"source_families": [None, "", " ", 4, "EEA_NORWAY"]}) == ["EEA_NORWAY"]

        # A current registry batch is not evidence freshness for each row.
        # Failed, low-information, quarantined, contradictory and missing
        # observations must never inherit a current evidence timestamp.
        primary = "https://official.example/SRC-MYSMIS-TEST"
        alias = "https://official.example/mysmis-alias"
        definition = next(row for row in registry_fixture["sources"] if row["id"] == "SRC-MYSMIS-TEST")
        definition["canonical_aliases"] = [alias]
        valid_health = {"id": "SRC-MYSMIS-TEST", "health": "PASS", "ok": True,
                        "url": primary, "selected_url": primary, "final_url": primary,
                        "content_quality_ok": True, "quarantined": False,
                        "raw_sha256": "a" * 64, "semantic_sha256": "b" * 64}
        verified_at = "2026-08-12T08:00:00Z"
        for row_health, expected, availability in (
            (valid_health, "CURRENT", "AVAILABLE"),
            (dict(valid_health, selected_url=alias, final_url=alias), "CURRENT", "AVAILABLE"),
            (dict(valid_health, final_url=alias), "CURRENT", "AVAILABLE"),
            (dict(valid_health, url=alias), "UNKNOWN", "UNKNOWN"),
            (dict(valid_health, selected_url="https://other.example/calls"), "UNKNOWN", "UNKNOWN"),
            (dict(valid_health, final_url="https://other.example/calls"), "UNKNOWN", "UNKNOWN"),
            (dict(valid_health, final_url=None), "UNKNOWN", "UNKNOWN"),
            (dict(valid_health, selected_url=[]), "UNKNOWN", "UNKNOWN"),
            (dict(valid_health, health="FAIL"), "UNKNOWN", "UNAVAILABLE_LAST_KNOWN_GOOD"),
            (dict(valid_health, health="DEGRADED"), "UNKNOWN", "DEGRADED_LAST_KNOWN_GOOD"),
            (dict(valid_health, ok=False), "UNKNOWN", "UNKNOWN"),
            (dict(valid_health, ok="true"), "UNKNOWN", "UNKNOWN"),
            (dict(valid_health, content_quality_ok=False), "UNKNOWN", "UNKNOWN"),
            (dict(valid_health, quarantined=True), "UNKNOWN", "UNKNOWN"),
            (dict(valid_health, raw_sha256=None), "UNKNOWN", "UNKNOWN"),
            (dict(valid_health, raw_sha256="g" * 64), "UNKNOWN", "UNKNOWN"),
            (dict(valid_health, semantic_sha256="a" * 63), "UNKNOWN", "UNKNOWN"),
            ({}, "UNKNOWN", "UNKNOWN"),
        ):
            fixture = {"observed_at": verified_at, "sources": [row_health] if row_health else []}
            projected = mod.build_source_inventory(
                [{"id": "VERIFIED_SOURCE_REGISTRY",
                  "freshness": {"status": "CURRENT", "ageHours": 2, "maxAgeHours": 4}}],
                registry_fixture, fixture, {}, {}
            )
            row = next(item for item in projected if item["id"] == "SRC-MYSMIS-TEST")
            assert row["freshness"]["status"] == expected, row
            assert row["observedAt"] == (verified_at if expected == "CURRENT" else None)
            assert row["lastAttemptObservedAt"] == (verified_at if row_health else None)
            assert row["lastAttemptFreshness"]["status"] == ("CURRENT" if row_health else "UNKNOWN")
            gate = mod.dependency_gate(row)
            assert gate["availability"] == availability, gate
            assert gate["materialFactGate"] == (
                "RECONCILIATION_REQUIRED" if expected == "CURRENT" else "BLOCKED_SOURCE_DEPENDENCIES"
            ), gate
            assert gate["publishMaterialFacts"] is False
        assert not mod.registry_endpoint_bound(dict(definition, url=alias), valid_health)
        assert not mod.registry_endpoint_bound(dict(definition, canonical_aliases=alias),
                                               dict(valid_health, selected_url=alias, final_url=alias))
        duplicate = mod.build_source_inventory(
            [{"id": "VERIFIED_SOURCE_REGISTRY", "freshness": {"status": "CURRENT"}}],
            registry_fixture, {"observed_at": verified_at, "sources": [valid_health, valid_health]}, {}, {}
        )
        row = next(item for item in duplicate if item["id"] == "SRC-MYSMIS-TEST")
        assert row["endpointBinding"] == "AMBIGUOUS"
        assert row["freshness"]["status"] == "UNKNOWN"
        assert mod.dependency_gate(row)["materialFactGate"] == "BLOCKED_SOURCE_DEPENDENCIES"
        inventory = {row["id"]: row for row in index["dataPlane"]["sourceInventory"]}
        assert inventory["SRC-DISCOVERY-ONLY"]["freshness"]["status"] == "UNKNOWN"
        assert inventory["SRC-DISCOVERY-ONLY"]["lastAttemptFreshness"]["status"] == "CURRENT"

        # A discovery-only T1 outage must remain visible operationally without
        # degrading material readiness when all material-authority sources are healthy.
        afir = json.loads((root / "afir_corpus.json").read_text(encoding="utf-8"))
        for row in afir["items"]:
            row["materialChangeCandidate"] = False
        write(root / "afir_corpus.json", afir)
        write(root / "mipe_state.json", {
            "status": "OK", "items": [],
            "lastRun": {"observedAt": "2026-08-12T08:00:00Z", "sourceAvailable": True},
        })
        registry = json.loads((root / "source_registry_health.json").read_text(encoding="utf-8"))
        registry["summary"]["resolution_tasks_required"] = 0
        for row in registry["sources"]:
            if row["id"] == "SRC-OIRVEST-PEO":
                row["semantic_hash_changed"] = False
                row["resolution_task_required"] = False
        write(root / "source_registry_health.json", registry)
        healthy_material = mod.compile_with_replay(root, reference, contract_path=domestic_contract_path, source_registry_path=registry_path)
        assert healthy_material["readiness"] == "READY_FOR_DISCOVERY_ONLY"
        assert healthy_material["sources"][-1]["status"] == "DEGRADED"
        assert healthy_material["summary"]["materialResolutionTasksRequired"] == 0
        assert healthy_material["summary"]["materialStaleOrUnknownSources"] == []
        assert healthy_material["summary"]["unavailableT1Sources"] == []
        assert healthy_material["summary"]["operationalUnavailableT1Sources"] == ["SRC-DISCOVERY-ONLY"]
        assert healthy_material["dataPlane"]["dependencyIsolation"]["blockedSourceIds"] == []

        stale = mod.compile_with_replay(
            root,
            dt.datetime(2026, 8, 14, tzinfo=dt.timezone.utc),
            contract_path=domestic_contract_path, source_registry_path=registry_path,
        )
        assert set(stale["summary"]["staleOrUnknownSources"]) == {
            "AFIR_CORPUS", "PEO_CALENDAR", "MIPE_CORPUS", "VERIFIED_SOURCE_REGISTRY",
            "SRC-MYSMIS-CALLS", "SRC-OIRVEST-PEO", "SRC-DISCOVERY-ONLY",
        }
        assert set(stale["summary"]["materialStaleOrUnknownSources"]) == {
            "AFIR_CORPUS", "MIPE_CORPUS", "SRC-MYSMIS-CALLS", "SRC-OIRVEST-PEO",
        }

        del afir["policy"]
        write(root / "afir_corpus.json", afir)
        invalid = mod.compile_with_replay(root, reference, contract_path=domestic_contract_path, source_registry_path=registry_path)
        assert invalid["contract"]["status"] == "FAIL"
        assert invalid["readiness"] == "BLOCKED_CONTRACT_FAIL_CLOSED"
    print("PASS intelligence_index")


if __name__ == "__main__":
    main()
