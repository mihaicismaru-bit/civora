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

source = next(x for x in sources["sources"] if x["id"] == "MS_PRESS")
person = next(x for x in people["people"] if x["id"] == "cseke-attila")

# Both ms.gov.ro spellings fail TLS hostname validation from the hosted runner.
# The same official Ministry site is served on ms.ro/www.ms.ro. Use the actual
# canonical listing root exposed there so candidate discovery cannot re-ingest
# that category page as if it were a press article. Legacy .gov.ro hosts remain
# allowlisted only for historical absolute links and provenance.
assert source["url"] == "https://ms.ro/centrul-de-presa/"
assert source["url"].startswith("https://ms.ro/")
assert collector.official_host(source["url"], source["allowedHosts"])
assert collector.official_host("https://www.ms.ro/centrul-de-presa/example/", source["allowedHosts"])
assert collector.official_host("https://ms.gov.ro/ro/centrul-de-presa/example/", source["allowedHosts"])
assert collector.official_host("https://www.ms.gov.ro/ro/centrul-de-presa/example/", source["allowedHosts"])
assert source["tier"] == "T1_DIRECT_OFFICIAL"
assert source["pathHints"] == ["/centrul-de-presa/"]
assert collector.source_fetch_budget_seconds([x for x in sources["sources"] if x.get("enabled", True)]) < 540

snapshot = builder.role_snapshot(person)
assert snapshot is not None
assert snapshot["role"] == "Ministrul interimar al Sănătății"
assert snapshot["institution"] == "Ministerul Sănătății"
assert snapshot["sourceTier"] == "T1_DIRECT_OFFICIAL"

listing = """
<a href="/centrul-de-presa/">Centru de presă — Ministerul Sănătății</a>
<a href="/centrul-de-presa/cseke-attila-investitii-pnrr-test/">
  Cseke Attila: investițiile PNRR trebuie accelerate
</a>
"""
candidates = collector.candidate_links(source, listing)
assert source["url"] not in candidates
assert candidates == ["https://ms.ro/centrul-de-presa/cseke-attila-investitii-pnrr-test/"]

article = """<html><head><title>Ministerul Sănătății — investiții PNRR</title></head><body>
20 august 2026. Cseke Attila a declarat că investițiile în spitalele finanțate prin PNRR trebuie accelerate, iar fiecare termen de implementare trebuie urmărit cu atenție.
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
assert item["personId"] == "cseke-attila"
assert item["signalKind"] == "STATEMENT_SIGNAL"
assert item["administrativeFact"] == {"status": "UNCONFIRMED_FROM_SIGNAL", "failClosed": True}
assert item["statementExtraction"]["status"] == "ACTOR_SPEECH_FUNDING_BOUND"
assert item["statementExtraction"]["scope"] == "SENTENCE"
assert item["sourceSnapshot"]["url"] == candidates[0]
assert item["sourceSnapshot"]["contentHash"]
assert item["roleVerification"]["role"] == "Ministrul interimar al Sănătății"

tracked = {p["id"]: p for p in people["people"] if p.get("active")}
trusted = builder.trusted_official_item(item, tracked)
assert trusted is not None
assert trusted["statementEvidence"]["status"] == "VERIFIED_ARTICLE_STATEMENT"
assert trusted["administrativeFact"]["failClosed"] is True

print(json.dumps({
    "source": source["id"],
    "transportRoot": source["url"],
    "listingExcluded": source["url"] not in candidates,
    "candidate": candidates[0],
    "status": status["status"],
    "signalKind": trusted["signalKind"],
    "failClosed": trusted["administrativeFact"]["failClosed"],
}, ensure_ascii=False, indent=2))
