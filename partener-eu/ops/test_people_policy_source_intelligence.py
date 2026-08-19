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

assert {
    "dragos-pislaru",
    "ilie-bolojan",
    "cseke-attila",
    "adrian-ionut-chesnoiu",
    "dragos-cristian-vlad",
} <= set(verified)
assert builder.role_snapshot(next(x for x in people["people"] if x["id"] == "oana-toiu")) is None
assert verified["adrian-ionut-chesnoiu"]["roleVerification"]["sourceUrl"].startswith("https://www.afir.ro/")
assert verified["dragos-cristian-vlad"]["roleVerification"]["sourceUrl"].startswith("https://www.adr.gov.ro/")

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

# AFIR already has a direct-official communiqué source. A verified AFIR leader
# must now be materializable as a person signal without promoting admin facts.
afir_source = next(x for x in sources["sources"] if x["id"] == "AFIR_COMMUNICATES")
afir_listing = '<a href="/comunicate/test-signal">Fonduri europene pentru investiții rurale</a>'
afir_article = """<html><head><title>Adrian Chesnoiu: finanțări europene pentru mediul rural</title></head><body>
19 august 2026. Adrian-Ionuț Chesnoiu a anunțat că AFIR pregătește finanțări FEADR pentru investiții rurale.
</body></html>"""
old_fetch = collector.fetch
try:
    collector.fetch = lambda url, limit=900_000: afir_listing if url == afir_source["url"] else afir_article
    afir_status, afir_items = collector.ingest_source(afir_source, people, canonical)
finally:
    collector.fetch = old_fetch
assert afir_status["status"] == "OK"
assert len(afir_items) == 1
item = afir_items[0]
assert item["personId"] == "adrian-ionut-chesnoiu"
assert item["person"] == "Adrian-Ionuț Chesnoiu"
assert item["institution"] == "AFIR"
assert item["signalKind"] == "STATEMENT_SIGNAL"
assert item["administrativeFact"]["status"] == "UNCONFIRMED_FROM_SIGNAL"
assert item["administrativeFact"]["failClosed"] is True
assert item["roleVerification"]["sourceTier"].startswith("T1")
assert item["sourceSnapshot"]["sourceId"] == "AFIR_COMMUNICATES"
assert item["sourceSnapshot"]["contentHash"]
assert item["canonicalLink"]["status"] == "UNRESOLVED"

# ADR's direct-official articles are likewise productive only after the current
# president is role-verified in the tracked decision-maker registry.
adr_source = next(x for x in sources["sources"] if x["id"] == "ADR_ARTICLES")
adr_listing = '<a href="/articole/test-signal">Programul Europa Digitală și fonduri europene</a>'
adr_article = """<html><head><title>Dragoș-Cristian Vlad: Programul Europa Digitală</title></head><body>
19 august 2026. Dragoș-Cristian Vlad a anunțat instruiri pentru accesarea fondurilor europene prin Programul Europa Digitală.
</body></html>"""
old_fetch = collector.fetch
try:
    collector.fetch = lambda url, limit=900_000: adr_listing if url == adr_source["url"] else adr_article
    adr_status, adr_items = collector.ingest_source(adr_source, people, canonical)
finally:
    collector.fetch = old_fetch
assert adr_status["status"] == "OK"
assert len(adr_items) == 1
adr_item = adr_items[0]
assert adr_item["personId"] == "dragos-cristian-vlad"
assert adr_item["institution"] == "ADR"
assert adr_item["signalKind"] == "STATEMENT_SIGNAL"
assert adr_item["administrativeFact"]["status"] == "UNCONFIRMED_FROM_SIGNAL"
assert adr_item["sourceSnapshot"]["sourceId"] == "ADR_ARTICLES"

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
changed_registry["adrian-ionut-chesnoiu"]["role"] = "Altă funcție ulterioară"
accepted = builder.trusted_official_item(item, changed_registry)
assert accepted is not None
assert accepted["roleVerification"]["role"] == item["roleVerification"]["role"]

hosts = refiner.official_hosts(sources)
assert "www.afir.ro" in hosts
assert "www.adr.gov.ro" in hosts
assert refiner.direct_official(item, hosts) is True
assert refiner.direct_official(adr_item, hosts) is True
assert refiner.fail_closed_signal(item) is True
unsafe = copy.deepcopy(item)
unsafe["administrativeFact"]["failClosed"] = False
assert refiner.fail_closed_signal(unsafe) is False

print(json.dumps({
    "officialSources": len(sources["sources"]),
    "verifiedRoles": len(verified),
    "productiveVerifiedActors": ["AFIR", "ADR"],
    "failClosedSignalContract": True,
    "explicitCodeCanonicalLink": True,
    "canonicalOfficialLedgerBoundary": True,
    "historicalRoleSnapshotPreserved": True,
}, ensure_ascii=False, indent=2))
