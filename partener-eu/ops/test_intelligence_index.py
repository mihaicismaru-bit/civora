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
            {"url": "https://www.afir.ro/finantare/test/", "title": "Test AFIR", "sha256": "a", "contentType": "text/html", "textExtracted": True, "materialChangeCandidate": False, "materialFactAction": "NONE"},
            {"url": "https://afir.ro/finantare/test", "title": "Duplicate", "sha256": "a", "contentType": "text/html", "textExtracted": True, "materialChangeCandidate": False, "materialFactAction": "NONE"},
            {"url": "https://www.afir.ro/doc/test.pdf", "title": "Ghid", "sha256": "b", "contentType": "application/pdf", "textExtracted": True, "materialChangeCandidate": True, "materialFactAction": "RESOLUTION_TASK_ONLY"},
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
        "summary": {"total": 2, "fail": 0, "resolution_tasks_required": 1},
        "sources": [
            {"id": "SRC-MYSMIS-CALLS", "tier": "T1", "health": "PASS", "semantic_hash_changed": False, "resolution_task_required": False, "semantic_sha256": "mysmis"},
            {"id": "SRC-OIRVEST-PEO", "tier": "T1B", "health": "PASS", "semantic_hash_changed": True, "resolution_task_required": True, "semantic_sha256": "oir"},
        ],
    })
    write(root / "source_registry.json", {
        "schema_version": "1.2",
        "sources": [
            {"id": "SRC-MYSMIS-CALLS", "tier": "T1", "class": "authoritative_call_registry", "owner": "MySMIS", "url": "https://resurse.mysmis2021.gov.ro/calls", "programmes": ["2021-2027"], "material_fact_use": True},
            {"id": "SRC-OIRVEST-PEO", "tier": "T1B", "class": "official_intermediate_body", "owner": "OIR Vest", "url": "https://oirvest.ro/peo-2021-2027/", "programmes": ["PEO"], "material_fact_use": True},
        ],
    })


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        fixture_state(root)
        reference = dt.datetime(2026, 8, 12, 10, tzinfo=dt.timezone.utc)
        registry_path = root / "source_registry.json"
        index = mod.compile_with_replay(root, reference, source_registry_path=registry_path)
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
        assert index["dataPlane"]["dependencyIsolation"]["globalStop"] is False
        stale = mod.compile_with_replay(
            root,
            dt.datetime(2026, 8, 14, tzinfo=dt.timezone.utc),
            source_registry_path=registry_path,
        )
        assert set(stale["summary"]["staleOrUnknownSources"]) == {
            "AFIR_CORPUS", "PEO_CALENDAR", "MIPE_CORPUS", "VERIFIED_SOURCE_REGISTRY",
            "SRC-MYSMIS-CALLS", "SRC-OIRVEST-PEO",
        }
        afir = json.loads((root / "afir_corpus.json").read_text(encoding="utf-8"))
        del afir["policy"]
        write(root / "afir_corpus.json", afir)
        invalid = mod.compile_with_replay(root, reference, source_registry_path=registry_path)
        assert invalid["contract"]["status"] == "FAIL"
        assert invalid["readiness"] == "BLOCKED_CONTRACT_FAIL_CLOSED"
    print("PASS intelligence_index")


if __name__ == "__main__":
    main()
