#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INGEST = ROOT / "partener-eu" / "ingest"
STATE = INGEST / "state"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


collector = load_module("people_policy_official_ingest", INGEST / "people_policy_official_ingest.py")
builder = load_module("build_people_policy", INGEST / "build_people_policy.py")
refiner = load_module("refine_people_policy", INGEST / "refine_people_policy.py")
sources = json.loads((STATE / "people_policy_source_registry.json").read_text(encoding="utf-8"))
people = json.loads((STATE / "people_policy_registry.json").read_text(encoding="utf-8"))
seed_state = json.loads((STATE / "people_policy_seed.json").read_text(encoding="utf-8"))

assert sources["policy"]["directOfficialOnly"] is True
assert sources["policy"]["generalPressExcludedAsAuthority"] is True
assert sources["policy"]["articleStatementEvidenceRequiredForProjection"] is True
assert sources["policy"]["genericListingRowsCannotBecomePersonSignals"] is True
assert people["policy"]["historicalSignalsRequireRoleAtObservation"] is True
assert people["policy"]["articleStatementEvidenceRequiredForOfficialSignals"] is True
ids = {x["id"] for x in sources["sources"]}
assert {"GOV_RO_NEWS", "MIPE_PRIMARY", "EC_RO_NEWS", "MS_PRESS", "AFIR_COMMUNICATES", "ADR_SV_OLTENIA_NEWS", "FED_MAI"} <= ids

enabled_sources = [x for x in sources["sources"] if x.get("enabled", True)]
network_budget_seconds = collector.source_fetch_budget_seconds(enabled_sources)
assert collector.MAX_SOURCE_FETCH_WORKERS >= 2
assert collector.FETCH_TIMEOUT_SECONDS <= 18
assert network_budget_seconds < 540

for source in sources["sources"]:
    assert source["url"].startswith("https://")
    assert collector.official_host(source["url"], source["allowedHosts"])
    assert source["tier"].startswith("T1")
    assert source.get("enabled") is True

verified = {}
for person in people["people"]:
    snap = builder.role_snapshot(person)
    if (person.get("roleVerification") or {}).get("status") == "VERIFIED":
        assert snap is not None
        assert snap["sourceUrl"].startswith("https://")
        verified[person["id"]] = person
    else:
        assert snap is None

assert {"dragos-pislaru", "ilie-bolojan", "cseke-attila"} <= set(verified)
assert builder.role_snapshot(next(x for x in people["people"] if x["id"] == "oana-toiu")) is None

sample = {
    "people": [
        verified["dragos-pislaru"],
        next(x for x in people["people"] if x["id"] == "oana-toiu"),
    ]
}
actor = collector.actor_for("Dragoș Pîslaru a anunțat priorități pentru fonduri europene și PNRR.", sample)
assert actor is not None and actor[0]["id"] == "dragos-pislaru"
assert collector.actor_for("Oana Țoiu a vorbit despre coeziune și fonduri europene.", sample) is None

canonical = {
    "calls": [
        {"id": "call-1", "code": "PEO/311/PEO_P9/OP4/ESO4.7/PEO_A34", "programme": "PEO"},
        {"id": "call-2", "code": "PIDS/123", "programme": "PoIDS"},
    ]
}
link = collector.canonical_link_for("Apel PEO/311/PEO_P9/OP4/ESO4.7/PEO_A34 intră în discuție.", canonical)
assert link["status"] == "MATCHED_EXPLICIT_CODE" and link["callId"] == "call-1"
assert collector.canonical_link_for("Un apel PEO fără cod explicit.", canonical)["status"] == "UNRESOLVED"

source = next(x for x in sources["sources"] if x["id"] == "AFIR_COMMUNICATES")
listing = '<a href="/comunicate/test-signal">Fonduri europene PNRR</a>'
article = """<html><head><title>Declarație Dragoș Pîslaru</title></head><body>
19 august 2026. Dragoș Pîslaru a anunțat că fondurile europene pentru investiții rămân o prioritate.
</body></html>"""
old_fetch = collector.fetch
try:
    collector.fetch = lambda url, limit=900_000: listing if url == source["url"] else article
    status, items = collector.ingest_source(source, people, canonical)
finally:
    collector.fetch = old_fetch
assert status["status"] == "OK"
assert status["listingFetched"] is True
assert status["articleFetchAttempts"] == 1
assert status["articleFetchSuccesses"] == 1
assert status["articleFetchFailures"] == 0
assert status["statementEvidenceRejected"] == 0
assert len(items) == 1
item = items[0]
assert item["signalKind"] == "STATEMENT_SIGNAL"
assert item["administrativeFact"]["status"] == "UNCONFIRMED_FROM_SIGNAL"
assert item["administrativeFact"]["failClosed"] is True
assert item["roleVerification"]["sourceTier"].startswith("T1")
assert item["sourceSnapshot"]["contentHash"]
assert item["canonicalLink"]["status"] == "UNRESOLVED"
assert item["person"] == "Dragoș Pîslaru"
assert item["statementExtraction"]["status"] == "ACTOR_SPEECH_FUNDING_BOUND"
assert item["statementExtraction"]["scope"] == "SENTENCE"
assert "Dragoș Pîslaru a anunțat" in item["statement"]

preface_article = """<html><head><title>Fonduri europene pentru investiții</title></head><body>
19 august 2026. Finanțarea europeană este importantă pentru economie. Dragoș Pîslaru a anunțat că fondurile europene pentru proiectele de investiții vor rămâne o prioritate.
</body></html>"""
try:
    collector.fetch = lambda url, limit=900_000: listing if url == source["url"] else preface_article
    preface_status, preface_items = collector.ingest_source(source, people, canonical)
finally:
    collector.fetch = old_fetch
assert preface_status["statementEvidenceRejected"] == 0
assert len(preface_items) == 1
assert preface_items[0]["statement"].startswith("Dragoș Pîslaru a anunțat")
assert "Finanțarea europeană este importantă" not in preface_items[0]["statement"]

adjacent_article = """<html><head><title>Declarație privind prioritățile</title></head><body>
19 august 2026. Dragoș Pîslaru a declarat că măsura va începe în această toamnă. Aceasta privește finanțarea prin PNRR pentru proiectele selectate.
</body></html>"""
try:
    collector.fetch = lambda url, limit=900_000: listing if url == source["url"] else adjacent_article
    adjacent_status, adjacent_items = collector.ingest_source(source, people, canonical)
finally:
    collector.fetch = old_fetch
assert adjacent_status["statementEvidenceRejected"] == 0
assert len(adjacent_items) == 1
assert adjacent_items[0]["statementExtraction"]["scope"] == "ADJACENT_SENTENCES"
assert "Dragoș Pîslaru a declarat" in adjacent_items[0]["statement"]
assert "PNRR" in adjacent_items[0]["statement"]

headline_only_article = """<html><head><title>Dragoș Pîslaru anunță finanțare PNRR</title></head><body>
19 august 2026. Materialul prezintă contextul general al programului fără o declarație atribuită în corpul articolului.
</body></html>"""
try:
    collector.fetch = lambda url, limit=900_000: listing if url == source["url"] else headline_only_article
    headline_only_status, headline_only_items = collector.ingest_source(source, people, canonical)
finally:
    collector.fetch = old_fetch
assert headline_only_items == []
assert headline_only_status["statementEvidenceRejected"] == 1

detached_article = """<html><head><title>Ministrul și finanțările europene</title></head><body>
19 august 2026. Dragoș Pîslaru a participat la reuniunea de lucru. Programul de finanțare PNRR are mai multe proiecte în pregătire și rămâne pe agenda instituției.
</body></html>"""
try:
    collector.fetch = lambda url, limit=900_000: listing if url == source["url"] else detached_article
    detached_status, detached_items = collector.ingest_source(source, people, canonical)
finally:
    collector.fetch = old_fetch
assert detached_items == []
assert detached_status["statementEvidenceRejected"] == 1

try:
    def fetch_failure(url, limit=900_000):
        if url == source["url"]:
            return listing
        raise OSError("simulated article fetch failure")
    collector.fetch = fetch_failure
    failed_status, failed_items = collector.ingest_source(source, people, canonical)
finally:
    collector.fetch = old_fetch
assert failed_status["status"] == "DEGRADED_ARTICLE_FETCH_FAILED"
assert failed_status["listingFetched"] is True
assert failed_status["articleFetchAttempts"] == 1
assert failed_status["articleFetchSuccesses"] == 0
assert failed_status["articleFetchFailures"] == 1
assert failed_items == []

try:
    collector.fetch = lambda url, limit=900_000: "<html><body>Nicio legătură candidată.</body></html>"
    empty_status, empty_items = collector.ingest_source(source, people, canonical)
finally:
    collector.fetch = old_fetch
assert empty_status["status"] == "OK_NO_CANDIDATES"
assert empty_status["listingFetched"] is True
assert empty_status["candidateLinks"] == 0
assert empty_status["articleFetchAttempts"] == 0
assert empty_items == []

tracked = {p["id"]: p for p in people["people"] if p.get("active")}
accepted = builder.trusted_official_item(item, tracked)
assert accepted is not None
assert accepted["roleVerification"] == item["roleVerification"]
assert accepted["statementEvidence"]["status"] == "VERIFIED_ARTICLE_STATEMENT"
assert accepted["statementEvidence"]["articleUrl"] == item["sources"][0]["url"]
assert accepted["statementEvidence"]["contentHash"] == item["sourceSnapshot"]["contentHash"]

no_actor_statement = copy.deepcopy(item)
no_actor_statement["headline"] = "Finanțări europene pentru investiții"
no_actor_statement["statement"] = "Programul de finanțare pentru investiții are un buget actualizat."
assert builder.trusted_official_item(no_actor_statement, tracked) is None

bad = copy.deepcopy(item)
bad["administrativeFact"]["status"] = "CONFIRMED"
assert builder.trusted_official_item(bad, tracked) is None

bad = copy.deepcopy(item)
bad["roleVerification"]["sourceUrl"] = ""
assert builder.trusted_official_item(bad, tracked) is None

bad = copy.deepcopy(item)
bad["sourceSnapshot"]["contentHash"] = ""
assert builder.trusted_official_item(bad, tracked) is None

changed_registry = copy.deepcopy(tracked)
changed_registry["dragos-pislaru"]["role"] = "Altă funcție ulterioară"
accepted_after_role_change = builder.trusted_official_item(item, changed_registry)
assert accepted_after_role_change is not None
assert accepted_after_role_change["roleVerification"]["role"] == item["roleVerification"]["role"]

legacy_seed = next(x for x in seed_state["items"] if x["personId"] == "cseke-attila")
assert builder.trusted_seed_item(legacy_seed, tracked) is None
historical_seed = copy.deepcopy(legacy_seed)
historical_seed["signalKind"] = "STATEMENT_SIGNAL"
historical_seed["administrativeFact"] = {"status": "UNCONFIRMED_FROM_SIGNAL", "failClosed": True}
historical_seed["roleVerification"] = {
    "role": "Ministrul Dezvoltării, Lucrărilor Publice și Administrației",
    "institution": "MDLPA",
    "verifiedAt": "2026-07-08",
    "sourceUrl": "https://www.mdlpa.ro/pages/comunicate",
    "sourceTier": "T1_DIRECT_OFFICIAL",
}
trusted_historical_seed = builder.trusted_seed_item(historical_seed, changed_registry)
assert trusted_historical_seed is not None
assert trusted_historical_seed["role"] == "Ministrul Dezvoltării, Lucrărilor Publice și Administrației"
assert trusted_historical_seed["institution"] == "MDLPA"

generic_mipe_row = {
    "date": "2026-08-18",
    "headline": "https://mfe.gov.ro/",
    "summary": "Dragoș Pîslaru. Programul PEO, PNRR, finanțări și noutăți.",
    "url": "https://mfe.gov.ro/",
    "tier": "T1",
}
assert builder.mention_item(verified["dragos-pislaru"], generic_mipe_row, "MIPE") is None

trusted_synthetic = {
    "date": "2026-08-19",
    "headline": "Dragoș Pîslaru anunță priorități pentru fonduri europene",
    "url": item["sources"][0]["url"],
    "tier": "T1_DIRECT_OFFICIAL",
    "roleVerification": item["roleVerification"],
    "sourceSnapshot": item["sourceSnapshot"],
    "statementEvidence": accepted["statementEvidence"],
    "programme": "PNRR",
}
synthetic = builder.mention_item(verified["dragos-pislaru"], trusted_synthetic, "MIPE")
assert synthetic is not None
assert synthetic["statementEvidence"]["status"] == "VERIFIED_ARTICLE_STATEMENT"
assert synthetic["roleVerification"] == item["roleVerification"]

hosts = refiner.official_hosts(sources)
assert "www.afir.ro" in hosts
assert refiner.direct_official(accepted, hosts) is True
assert refiner.fail_closed_signal(accepted) is True
assert refiner.article_statement_evidence(accepted) is True
unsafe = copy.deepcopy(accepted)
unsafe["administrativeFact"]["failClosed"] = False
assert refiner.fail_closed_signal(unsafe) is False
no_evidence = copy.deepcopy(accepted)
no_evidence.pop("statementEvidence", None)
assert refiner.article_statement_evidence(no_evidence) is False

workflow_path = ROOT / ".github" / "workflows" / "partener-eu-editorial-daily.yml"
workflow = workflow_path.read_text(encoding="utf-8")
ordered_markers = [
    "- name: Ingest official decision-maker signals",
    "- name: Persist official-source ledger checkpoint",
    "- name: Generate verified decision-maker projection",
    "- name: Validate verified decision-maker projection",
    "- name: Persist verified decision-maker projection checkpoint",
    "- name: Generate daily briefing",
]
positions = [workflow.index(marker) for marker in ordered_markers]
assert positions == sorted(positions)
projection_block = workflow.split("- name: Generate verified decision-maker projection", 1)[1].split("- name:", 1)[0]
assert "build_people_policy.py" in projection_block
assert "refine_people_policy.py" in projection_block
projection_persist_block = workflow.split("- name: Persist verified decision-maker projection checkpoint", 1)[1].split("- name:", 1)[0]
assert "partener-eu/ingest/state/people_policy.json" in projection_persist_block
assert "partener-eu/web/people-policy-data.js" in projection_persist_block
assert "daily_brief.json" not in projection_persist_block
daily_block = workflow.split("- name: Generate daily briefing", 1)[1].split("- name:", 1)[0]
assert "build_daily_brief.py" in daily_block
assert "build_people_policy.py" not in daily_block
assert "refine_people_policy.py" not in daily_block

print(json.dumps({
    "officialSources": len(sources["sources"]),
    "verifiedRoles": len(verified),
    "failClosedSignalContract": True,
    "explicitCodeCanonicalLink": True,
    "canonicalOfficialLedgerBoundary": True,
    "historicalRoleSnapshotPreserved": True,
    "historicalSeedsRequireRoleAtObservation": True,
    "genericListingRowsRejected": True,
    "articleStatementEvidenceRequired": True,
    "actorSpeechFundingWindowRequired": True,
    "titleOnlyStatementRejected": True,
    "detachedActorFundingRejected": True,
    "sourceHealthRequiresArticleFetchProof": True,
    "boundedConcurrentSourceIngest": True,
    "durableVerifiedProjectionCheckpoint": True,
    "worstCaseNetworkBudgetSeconds": network_budget_seconds,
}, ensure_ascii=False, indent=2))