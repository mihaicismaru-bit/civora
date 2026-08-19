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

source = next(x for x in sources["sources"] if x["id"] == "ANRE_PRESS")
person = next(x for x in people["people"] if x["id"] == "george-sergiu-niculescu")

assert source["url"] == "https://anre.ro/category/comunicari-publice/comunicate-de-presa/"
assert source["tier"] == "T1_DIRECT_OFFICIAL"
assert collector.official_host(source["url"], source["allowedHosts"])
assert source["maxLinks"] <= 10
assert collector.source_fetch_budget_seconds([x for x in sources["sources"] if x.get("enabled", True)]) < 540

snapshot = builder.role_snapshot(person)
assert snapshot is not None
assert snapshot["role"] == "Președinte"
assert snapshot["institution"].endswith("(ANRE)")
assert snapshot["sourceUrl"].startswith("https://anre.ro/")
assert snapshot["sourceTier"] == "T1_DIRECT_OFFICIAL"

listing = '<a href="/comunicat-de-presa-test-partener-anre">Comunicat de presă privind investițiile energetice</a>'
article = """<html><head><title>ANRE — investiții energetice</title></head><body>
20 august 2026. George Niculescu a declarat că investițiile în energie regenerabilă și proiectele de racordare trebuie accelerate prin reguli predictibile.
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
assert status["statementEvidenceRejected"] == 0
assert len(items) == 1

item = items[0]
assert item["personId"] == "george-sergiu-niculescu"
assert item["person"] == "George Sergiu Niculescu"
assert item["signalKind"] == "STATEMENT_SIGNAL"
assert item["administrativeFact"] == {"status": "UNCONFIRMED_FROM_SIGNAL", "failClosed": True}
assert item["statementExtraction"]["status"] == "ACTOR_SPEECH_FUNDING_BOUND"
assert item["statementExtraction"]["scope"] == "SENTENCE"
assert item["canonicalLink"]["status"] in {"UNRESOLVED", "MATCHED_EXPLICIT_CODE"}
assert item["sourceSnapshot"]["contentHash"]
assert item["roleVerification"]["role"] == "Președinte"

tracked = {p["id"]: p for p in people["people"] if p.get("active")}
trusted = builder.trusted_official_item(item, tracked)
assert trusted is not None
assert trusted["statementEvidence"]["status"] == "VERIFIED_ARTICLE_STATEMENT"
assert trusted["administrativeFact"]["failClosed"] is True

direct_quote_article = """<html><head><title>ANRE — investiții energetice</title></head><body>
20 august 2026. George Niculescu, președinte ANRE: „Investițiile în rețele și finanțarea proiectelor de energie regenerabilă trebuie accelerate prin reguli predictibile și transparente.”
</body></html>"""
try:
    collector.fetch = lambda url, limit=900_000: listing if url == source["url"] else direct_quote_article
    quote_status, quote_items = collector.ingest_source(source, people, canonical)
finally:
    collector.fetch = old_fetch
assert quote_status["statementEvidenceRejected"] == 0
assert len(quote_items) == 1
quote_item = quote_items[0]
assert quote_item["statementExtraction"]["scope"] == "ACTOR_ROLE_COLON_QUOTE"
assert quote_item["statementExtraction"]["signalCue"] == "DIRECT_QUOTE_ATTRIBUTION"
assert quote_item["signalKind"] == "STATEMENT_SIGNAL"
assert quote_item["administrativeFact"] == {"status": "UNCONFIRMED_FROM_SIGNAL", "failClosed": True}
trusted_quote = builder.trusted_official_item(quote_item, tracked)
assert trusted_quote is not None
assert trusted_quote["statementEvidence"]["signalCue"] == "DIRECT_QUOTE_ATTRIBUTION"
assert trusted_quote["statementEvidence"]["evidenceMode"] == "ACTOR_ROLE_COLON_QUOTE"

colon_without_quote = """<html><head><title>ANRE — investiții energetice</title></head><body>
20 august 2026. George Niculescu, președinte ANRE: Investițiile în rețele și finanțarea proiectelor trebuie accelerate prin reguli predictibile.
</body></html>"""
try:
    collector.fetch = lambda url, limit=900_000: listing if url == source["url"] else colon_without_quote
    no_quote_status, no_quote_items = collector.ingest_source(source, people, canonical)
finally:
    collector.fetch = old_fetch
assert no_quote_items == []
assert no_quote_status["statementEvidenceRejected"] == 1

quote_without_funding = """<html><head><title>ANRE — investiții energetice</title></head><body>
20 august 2026. George Niculescu, președinte ANRE: „Regulile trebuie să fie predictibile, transparente și aplicate consecvent pentru toți participanții la piață.”
</body></html>"""
try:
    collector.fetch = lambda url, limit=900_000: listing if url == source["url"] else quote_without_funding
    no_funding_status, no_funding_items = collector.ingest_source(source, people, canonical)
finally:
    collector.fetch = old_fetch
assert no_funding_items == []
assert no_funding_status["statementEvidenceRejected"] == 1

reversed_attribution = """<html><head><title>ANRE — investiții energetice</title></head><body>
20 august 2026. ANRE: „George Niculescu, președinte, consideră că finanțarea proiectelor energetice trebuie să rămână predictibilă și transparentă pentru investitori.”
</body></html>"""
try:
    collector.fetch = lambda url, limit=900_000: listing if url == source["url"] else reversed_attribution
    reversed_status, reversed_items = collector.ingest_source(source, people, canonical)
finally:
    collector.fetch = old_fetch
assert reversed_items == []
assert reversed_status["statementEvidenceRejected"] == 1

print(json.dumps({
    "source": source["id"],
    "person": person["id"],
    "status": status["status"],
    "signalKind": trusted["signalKind"],
    "failClosed": trusted["administrativeFact"]["failClosed"],
}, ensure_ascii=False, indent=2))
