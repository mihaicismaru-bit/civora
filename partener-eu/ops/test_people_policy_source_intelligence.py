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

assert sources["policy"]["directOfficialOnly"] is True
assert sources["policy"]["generalPressExcludedAsAuthority"] is True
ids = {x["id"] for x in sources["sources"]}
assert {"GOV_RO_NEWS", "MIPE_PRIMARY", "EC_RO_NEWS", "MS_PRESS", "AFIR_COMMUNICATES", "ADR_SV_OLTENIA_NEWS", "FED_MAI"} <= ids

enabled_sources = [x for x in sources["sources"] if x.get("enabled", True)]
network_budget_seconds = collector.source_fetch_budget_seconds(enabled_sources)
assert collector.MAX_SOURCE_FETCH_WORKERS >= 2
assert collector.FETCH_TIMEOUT_SECONDS <= 18
# The editorial workflow has a 10-minute wall-clock envelope. Keep a full
# minute of headroom for parsing, validation and durable checkpointing.
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
article = """<html><head><title>Dragoș Pîslaru: finanțare europeană</title></head><body>
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
assert len(items) == 1
item = items[0]
assert item["signalKind"] == "STATEMENT_SIGNAL"
assert item["administrativeFact"]["status"] == "UNCONFIRMED_FROM_SIGNAL"
assert item["administrativeFact"]["failClosed"] is True
assert item["roleVerification"]["sourceTier"].startswith("T1")
assert item["sourceSnapshot"]["contentHash"]
assert item["canonicalLink"]["status"] == "UNRESOLVED"
assert item["person"] == "Dragoș Pîslaru"

# A reachable listing is not reported as healthy article coverage when every
# candidate article fetch fails. The ledger must expose the measured failure.
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

# A reachable source with no discoverable candidates is distinct from proven
# article coverage; it must not be collapsed into OK.
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

bad = copy.deepcopy(item)
bad["administrativeFact"]["status"] = "CONFIRMED"
assert builder.trusted_official_item(bad, tracked) is None

bad = copy.deepcopy(item)
bad["roleVerification"]["sourceUrl"] = ""
assert builder.trusted_official_item(bad, tracked) is None

bad = copy.deepcopy(item)
bad["sourceSnapshot"]["contentHash"] = ""
assert builder.trusted_official_item(bad, tracked) is None

# Historical observations keep their verified role-at-observation snapshot even
# if the live registry later changes; history is not silently rewritten.
changed_registry = copy.deepcopy(tracked)
changed_registry["dragos-pislaru"]["role"] = "Altă funcție ulterioară"
accepted = builder.trusted_official_item(item, changed_registry)
assert accepted is not None
assert accepted["roleVerification"]["role"] == item["roleVerification"]["role"]

hosts = refiner.official_hosts(sources)
assert "www.afir.ro" in hosts
assert refiner.direct_official(item, hosts) is True
assert refiner.fail_closed_signal(item) is True
unsafe = copy.deepcopy(item)
unsafe["administrativeFact"]["failClosed"] = False
assert refiner.fail_closed_signal(unsafe) is False

print(json.dumps({
    "officialSources": len(sources["sources"]),
    "verifiedRoles": len(verified),
    "failClosedSignalContract": True,
    "explicitCodeCanonicalLink": True,
    "canonicalOfficialLedgerBoundary": True,
    "historicalRoleSnapshotPreserved": True,
    "sourceHealthRequiresArticleFetchProof": True,
    "boundedConcurrentSourceIngest": True,
    "worstCaseNetworkBudgetSeconds": network_budget_seconds,
}, ensure_ascii=False, indent=2))
