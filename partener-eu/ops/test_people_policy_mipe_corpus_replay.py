#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INGEST = ROOT / "partener-eu" / "ingest"
STATE = INGEST / "state"
sys.path.insert(0, str(INGEST))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


collector = load_module("people_policy_official_ingest", INGEST / "people_policy_official_ingest.py")
replay = load_module("people_policy_mipe_corpus_replay", INGEST / "people_policy_mipe_corpus_replay.py")
sources = json.loads((STATE / "people_policy_source_registry.json").read_text(encoding="utf-8"))
people = json.loads((STATE / "people_policy_registry.json").read_text(encoding="utf-8"))
source = next(x for x in sources["sources"] if x["id"] == "MIPE_PRIMARY")

text = (
    "19 august 2026. Dragoș Pîslaru a anunțat că finanțarea europeană prin PNRR "
    "pentru proiectele de investiții rămâne o prioritate și că ministerul va urmări implementarea."
)
page = {
    "id": "synthetic-mipe-page",
    "url": "https://mfe.gov.ro/comunicate/test-declaratie/",
    "title": "Declarație privind finanțarea europeană",
    "programme": "PNRR",
    "pageClass": "NEWS",
    "kind": "NEWS",
    "summary": text,
    "textPreview": text,
    "documents": [],
    "contentHash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    "contentSelector": "main",
    "tier": "T1",
    "source": "MIPE",
    "observedAt": "2026-08-19T20:00:00Z",
    "retrievalTransport": "playwright-edge-direct-romania-v3",
    "verification": "CANONICAL_OFFICIAL_FETCH",
}
corpus = {
    "schemaVersion": 3,
    "source": "MIPE",
    "officialHosts": ["mfe.gov.ro", "www.mfe.gov.ro"],
    "generatedAt": "2026-08-19T20:01:00Z",
    "status": "PASS",
    "pages": [page],
}
canonical = {"calls": []}

ok, reason = replay.validate_corpus(corpus)
assert ok is True and reason == "OK"
ok, reason = replay.validate_page(page, source)
assert ok is True and reason == "OK"

bad_hash = copy.deepcopy(page)
bad_hash["contentHash"] = "0" * 64
assert replay.validate_page(bad_hash, source) == (False, "PAGE_CONTENT_HASH_MISMATCH")

bad_host = copy.deepcopy(page)
bad_host["url"] = "https://example.com/comunicate/test/"
assert replay.validate_page(bad_host, source) == (False, "PAGE_HOST_NOT_OFFICIAL_MIPE")

bad_transport = copy.deepcopy(page)
bad_transport["retrievalTransport"] = "generic-http"
assert replay.validate_page(bad_transport, source) == (False, "PAGE_TRANSPORT_NOT_CANONICAL_WINDOWS_EDGE")

replay_status, fresh = replay.replay_pages(corpus, source, people, canonical, "2026-08-19T20:05:00Z")
assert replay_status["status"] == "REPLAY_OK"
assert replay_status["pagesSeen"] == 1
assert replay_status["pagesIntegrityAccepted"] == 1
assert replay_status["acceptedItems"] == 1
assert len(fresh) == 1
item = fresh[0]
assert item["personId"] == "dragos-pislaru"
assert item["signalKind"] == "STATEMENT_SIGNAL"
assert item["administrativeFact"] == {"status": "UNCONFIRMED_FROM_SIGNAL", "failClosed": True}
assert item["canonicalLink"]["status"] == "UNRESOLVED"
assert item["sourceSnapshot"]["url"] == page["url"]
assert item["sourceSnapshot"]["observedAt"] == page["observedAt"]
assert item["sourceSnapshot"]["contentHash"] == page["contentHash"]
assert item["sourceSnapshot"]["acquisitionPath"] == "PERSISTED_MIPE_WINDOWS_CORPUS_REPLAY"
assert item["sourceSnapshot"]["retrievalTransport"] == "playwright-edge-direct-romania-v3"
assert item["sourceSnapshot"]["verification"] == "CANONICAL_OFFICIAL_FETCH"
assert item["sourceSnapshot"]["corpusGeneratedAt"] == corpus["generatedAt"]
assert item["observedAt"] == page["observedAt"]
assert item["replayedAt"] == "2026-08-19T20:05:00Z"
assert item["roleVerification"]["verifiedAt"] == "2026-08-19"
assert item["statementExtraction"]["status"] == "ACTOR_SPEECH_FUNDING_BOUND"

pre_verification_page = copy.deepcopy(page)
pre_verification_page["observedAt"] = "2026-08-18T20:00:00Z"
pre_corpus = copy.deepcopy(corpus)
pre_corpus["pages"] = [pre_verification_page]
pre_status, pre_items = replay.replay_pages(pre_corpus, source, people, canonical, "2026-08-19T20:05:00Z")
assert pre_items == []
assert pre_status["rejections"]["ROLE_NOT_VERIFIED_AT_OBSERVATION"] == 1

ledger = {
    "schemaVersion": 2,
    "generatedAt": "2026-08-19T19:55:00Z",
    "policy": {
        "administrativeFactsNeverPromotedFromSignals": True,
        "failClosed": True,
    },
    "sources": [
        {
            "id": "MIPE_PRIMARY",
            "publisher": source["publisher"],
            "url": source["url"],
            "tier": source["tier"],
            "status": "SOURCE_UNAVAILABLE_HISTORY_PRESERVED",
            "observedAt": "2026-08-19T19:55:00Z",
            "error": "Network is unreachable",
            "failClosed": True,
        }
    ],
    "items": [copy.deepcopy(item)],
    "quarantine": [],
}
direct_before = copy.deepcopy(ledger["sources"])
output, applied_status = replay.apply_replay(
    ledger, corpus, sources, people, canonical, "2026-08-19T20:06:00Z"
)
assert output["sources"] == direct_before
assert output["sources"][0]["status"] == "SOURCE_UNAVAILABLE_HISTORY_PRESERVED"
assert applied_status["directSourceHealthUnchanged"] is True
assert applied_status["directSourceStatus"] == "SOURCE_UNAVAILABLE_HISTORY_PRESERVED"
assert applied_status["status"] == "REPLAY_OK"
assert len(output["items"]) == 1
assert output["items"][0]["logicalSignalKey"] == item["logicalSignalKey"]
assert output["policy"]["mipeDirectHealthIndependentFromPersistentReplay"] is True
assert output["policy"]["administrativeFactsNeverPromotedFromSignals"] is True
assert output["policy"]["failClosed"] is True

healthy_ledger = copy.deepcopy(ledger)
healthy_ledger["sources"][0]["status"] = "OK"
healthy_output, healthy_status = replay.apply_replay(
    healthy_ledger, corpus, sources, people, canonical, "2026-08-19T20:07:00Z"
)
assert healthy_status["status"] == "SKIPPED_DIRECT_SOURCE_HEALTHY"
assert healthy_status["directSourceHealthUnchanged"] is True
assert healthy_output["sources"][0]["status"] == "OK"
assert healthy_output["items"] == healthy_ledger["items"]

bad_corpus = copy.deepcopy(corpus)
bad_corpus["pages"] = [bad_hash]
try:
    replay.apply_replay(ledger, bad_corpus, sources, people, canonical, "2026-08-19T20:08:00Z")
except ValueError as exc:
    assert "REPLAY_REJECTED_ALL_PAGE_INTEGRITY" in str(exc)
else:
    raise AssertionError("all-corrupt MIPE replay must fail closed")

# Logical identity deliberately ignores acquisition path/content-observation metadata.
direct_like = copy.deepcopy(item)
direct_like["sourceSnapshot"].pop("acquisitionPath", None)
direct_like["sourceSnapshot"].pop("retrievalTransport", None)
direct_like["sourceSnapshot"].pop("verification", None)
direct_like["replayedAt"] = ""
assert collector.logical_signal_key(direct_like) == collector.logical_signal_key(item)
assert len(collector.deduplicate_signal_history([direct_like, item])) == 1

print(json.dumps({
    "validReplaySignals": len(fresh),
    "directHealthPreserved": output["sources"][0]["status"],
    "deduplicatedSignals": len(output["items"]),
    "badHashRejected": True,
    "wrongHostRejected": True,
    "roleAtObservationRequired": True,
}, ensure_ascii=False))
