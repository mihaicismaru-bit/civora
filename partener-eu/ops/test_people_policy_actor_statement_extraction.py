#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ingest" / "people_policy_official_ingest.py"
spec = importlib.util.spec_from_file_location("people_policy_official_ingest", MODULE_PATH)
assert spec and spec.loader
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

source = {
    "id": "TEST_OFFICIAL",
    "publisher": "Instituție oficială de test",
    "institution": "TEST",
    "url": "https://official.example/news",
    "tier": "T1_DIRECT_OFFICIAL",
    "allowedHosts": ["official.example"],
    "pathHints": ["/news/"],
    "maxLinks": 1,
    "enabled": True,
}
people = {
    "people": [{
        "id": "dragos-pislaru",
        "name": "Dragoș Pîslaru",
        "aliases": ["Dragoș Pîslaru", "Dragos Pislaru", "Pîslaru", "Pislaru"],
        "role": "Ministrul Investițiilor și Proiectelor Europene",
        "institution": "MIPE",
        "priority": 100,
        "active": True,
        "roleVerification": {
            "status": "VERIFIED",
            "verifiedAt": "2026-08-19T08:00:00Z",
            "sourceUrl": "https://official.example/role",
            "sourceTier": "T1_DIRECT_OFFICIAL",
        },
    }]
}
listing = '<a href="/news/article">Fonduri europene și PNRR</a>'


def run(article: str):
    old_fetch = collector.fetch
    try:
        collector.fetch = lambda url, limit=900_000: listing if url == source["url"] else article
        return collector.ingest_source(source, people, {"calls": []})
    finally:
        collector.fetch = old_fetch


article = """<html><head><title>Dragoș Pîslaru a anunțat finanțare PNRR</title></head><body>
19 august 2026. Programul PNRR include finanțare pentru investiții și proiecte publice.
Dragoș Pîslaru a declarat că fondurile europene pentru investiții trebuie accelerate în perioada următoare.
</body></html>"""
status, items = run(article)
assert status["status"] == "OK"
assert len(items) == 1
item = items[0]
assert item["statement"].startswith("Dragoș Pîslaru a declarat")
assert "Programul PNRR include" not in item["statement"]
assert item["statementExtraction"] == {
    "version": "ACTOR_REPORTING_FUNDING_SENTENCE_V1",
    "scope": "ARTICLE_BODY",
    "titleExcluded": True,
}
assert item["signalKind"] == "STATEMENT_SIGNAL"
assert item["administrativeFact"] == {"status": "UNCONFIRMED_FROM_SIGNAL", "failClosed": True}

parser = collector.TextParser()
parser.feed(article)
assert "Dragoș Pîslaru a anunțat finanțare PNRR" not in collector.clean(" ".join(parser.parts))
assert "Dragoș Pîslaru a anunțat finanțare PNRR" == collector.clean(" ".join(parser.title_parts))

title_only = """<html><head><title>Dragoș Pîslaru a anunțat finanțare PNRR</title></head><body>
Dragoș Pîslaru a participat la reuniunea de lucru de astăzi. Programul PNRR include finanțare pentru investiții publice.
</body></html>"""
status, items = run(title_only)
assert status["status"] == "OK"
assert items == []
assert status["nonStatementActorMentionsRejected"] == 1

split_context = """<html><head><title>Fonduri europene și PNRR</title></head><body>
Dragoș Pîslaru a declarat că negocierile tehnice vor continua în perioada următoare.
Programul PNRR include finanțare pentru investiții și proiecte publice.
</body></html>"""
status, items = run(split_context)
assert status["status"] == "OK"
assert items == []
assert status["nonStatementActorMentionsRejected"] == 1

print("actor-aware article statement extraction: PASS")
