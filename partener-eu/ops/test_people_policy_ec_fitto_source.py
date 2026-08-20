#!/usr/bin/env python3
from __future__ import annotations

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
sources = json.loads((STATE / "people_policy_source_registry.json").read_text(encoding="utf-8"))
people = json.loads((STATE / "people_policy_registry.json").read_text(encoding="utf-8"))
canonical = json.loads((STATE / "mipe_canonical_calls.json").read_text(encoding="utf-8"))

source = next(x for x in sources["sources"] if x["id"] == "EC_FITTO_PROFILE")
person = next(x for x in people["people"] if x["id"] == "raffaele-fitto")

assert source["url"] == "https://commission.europa.eu/about/organisation/college-commissioners/raffaele-fitto_en"
assert source["tier"] == "T1_DIRECT_OFFICIAL_EU"
assert collector.official_host(source["url"], source["allowedHosts"])
assert collector.official_host("https://ec.europa.eu/commission/presscorner/detail/en/speech_test", source["allowedHosts"])
assert source["maxLinks"] <= 8
assert collector.source_fetch_budget_seconds([x for x in sources["sources"] if x.get("enabled", True)]) < 540

snapshot = builder.role_snapshot(person)
assert snapshot is not None
assert snapshot["role"] == "Executive Vice-President for Cohesion and Reforms"
assert snapshot["institution"] == "European Commission"
assert snapshot["sourceUrl"] == source["url"]
assert snapshot["sourceTier"] == "T1_DIRECT_OFFICIAL_EU"

listing = '<a href="https://ec.europa.eu/commission/presscorner/detail/en/speech_test">Speech on cohesion policy and EU funding</a>'
article = """<html><head><title>European Commission — cohesion policy</title></head><body>
20 august 2026. Raffaele Fitto a declarat că politica de coeziune și fondurile europene trebuie să continue să susțină investițiile regionale și implementarea reformelor.
</body></html>"""

old_fetch = collector.fetch
try:
    collector.fetch = lambda url, limit=900_000: listing if url == source["url"] else article
    status, items = collector.ingest_source(source, people, canonical)
finally:
    collector.fetch = old_fetch

assert status["status"] == "OK"
assert status["listingFetched"] is True
assert status["candidateLinks"] == 1
assert status["articleFetchAttempts"] == 1
assert status["articleFetchSuccesses"] == 1
assert status["articleFetchFailures"] == 0
assert status["statementEvidenceRejected"] == 0
assert len(items) == 1

item = items[0]
assert item["personId"] == "raffaele-fitto"
assert item["person"] == "Raffaele Fitto"
assert item["signalKind"] == "STATEMENT_SIGNAL"
assert item["administrativeFact"] == {"status": "UNCONFIRMED_FROM_SIGNAL", "failClosed": True}
assert item["statementExtraction"]["status"] == "ACTOR_SPEECH_FUNDING_BOUND"
assert item["statementExtraction"]["scope"] == "SENTENCE"
assert item["roleVerification"]["role"] == "Executive Vice-President for Cohesion and Reforms"
assert item["roleVerification"]["sourceTier"] == "T1_DIRECT_OFFICIAL_EU"
assert item["sourceSnapshot"]["contentHash"]
assert item["canonicalLink"]["status"] in {"UNRESOLVED", "MATCHED_EXPLICIT_CODE"}

tracked = {p["id"]: p for p in people["people"] if p.get("active")}
trusted = builder.trusted_official_item(item, tracked)
assert trusted is not None
assert trusted["statementEvidence"]["status"] == "VERIFIED_ARTICLE_STATEMENT"
assert trusted["administrativeFact"]["status"] == "UNCONFIRMED_FROM_SIGNAL"
assert trusted["administrativeFact"]["failClosed"] is True

print(json.dumps({
    "source": source["id"],
    "person": person["id"],
    "status": status["status"],
    "signalKind": trusted["signalKind"],
    "failClosed": trusted["administrativeFact"]["failClosed"],
}, ensure_ascii=False, indent=2))
