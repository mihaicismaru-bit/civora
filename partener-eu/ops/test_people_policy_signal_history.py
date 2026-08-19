#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INGEST = ROOT / "partener-eu" / "ingest"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


collector = load_module("people_policy_official_ingest_history", INGEST / "people_policy_official_ingest.py")

URL = "https://pr2021-2027.adroltenia.ro/2026/08/06/semnal-oficial/"
STATEMENT = "Stelian Bărăgan a declarat că finanțarea europeană susține investițiile regionale."
ROLE = {
    "role": "Vicepreședinte",
    "institution": "Consiliul Județean Dolj",
    "verifiedAt": "2026-08-06",
    "sourceUrl": "https://www.cjdolj.ro/conducere",
    "sourceTier": "T1_DIRECT_OFFICIAL",
}


def make_item(content: str, observed: str, *, statement: str = STATEMENT, person_id: str = "stelian-baragan"):
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    fingerprint = hashlib.sha256(f"{person_id}|{URL}|{content_hash}".encode("utf-8")).hexdigest()
    return {
        "id": "official-" + fingerprint[:18],
        "personId": person_id,
        "person": "Stelian Bărăgan" if person_id == "stelian-baragan" else "Alt decident",
        "role": ROLE["role"],
        "institution": ROLE["institution"],
        "roleVerification": copy.deepcopy(ROLE),
        "date": "2026-08-06",
        "type": "FUNDING_COMMITMENT",
        "signalKind": "STATEMENT_SIGNAL",
        "statement": statement,
        "headline": "Finanțare regională",
        "administrativeFact": {"status": "UNCONFIRMED_FROM_SIGNAL", "failClosed": True},
        "canonicalLink": {"status": "UNRESOLVED"},
        "sources": [{"label": "ADR Sud-Vest Oltenia", "url": URL, "tier": "T1_DIRECT_OFFICIAL"}],
        "sourceSnapshot": {
            "sourceId": "ADR_SV_OLTENIA_NEWS",
            "publisher": "ADR Sud-Vest Oltenia",
            "tier": "T1_DIRECT_OFFICIAL",
            "url": URL,
            "observedAt": observed,
            "contentHash": content_hash,
        },
        "observedAt": observed,
        "sourceId": "ADR_SV_OLTENIA_NEWS",
        "priority": 75,
        "officialIngested": True,
        "fingerprint": fingerprint,
    }


first = make_item("article bytes v1", "2026-08-19T10:00:00Z")
second = make_item("article bytes v2", "2026-08-19T11:00:00Z")
assert first["fingerprint"] != second["fingerprint"]
assert collector.logical_signal_key(first) == collector.logical_signal_key(second)

merged = collector.deduplicate_signal_history([first, second])
assert len(merged) == 1
signal = merged[0]
assert signal["id"].startswith("official-signal-")
assert signal["logicalSignalKey"] == collector.logical_signal_key(first)
assert signal["administrativeFact"] == {"status": "UNCONFIRMED_FROM_SIGNAL", "failClosed": True}
assert signal["roleVerification"] == ROLE
assert signal["observationCount"] == 2
assert len(signal["observations"]) == 2
assert signal["firstObservedAt"] == "2026-08-19T10:00:00Z"
assert signal["lastObservedAt"] == "2026-08-19T11:00:00Z"
assert {row["contentHash"] for row in signal["observations"]} == {
    first["sourceSnapshot"]["contentHash"],
    second["sourceSnapshot"]["contentHash"],
}
assert set(signal["legacyIds"]) == {first["id"], second["id"]}

# A re-fetch of identical bytes is an observation of the existing version, not a
# second logical signal or a second content version.
third = make_item("article bytes v2", "2026-08-19T12:00:00Z")
rerun = collector.deduplicate_signal_history([signal, third])
assert len(rerun) == 1
signal = rerun[0]
assert len(signal["observations"]) == 2
assert signal["observationCount"] == 3
v2 = next(row for row in signal["observations"] if row["contentHash"] == third["sourceSnapshot"]["contentHash"])
assert v2["observationCount"] == 2
assert v2["firstObservedAt"] == "2026-08-19T11:00:00Z"
assert v2["lastObservedAt"] == "2026-08-19T12:00:00Z"

# Same article/headline may contain two genuinely different attributed statements;
# statement identity therefore remains part of the logical key.
different_statement = make_item(
    "article bytes v3",
    "2026-08-19T13:00:00Z",
    statement="Stelian Bărăgan a anunțat că granturile pentru IMM vor avea o linie separată.",
)
assert collector.logical_signal_key(first) != collector.logical_signal_key(different_statement)
assert len(collector.deduplicate_signal_history([first, different_statement])) == 2

# A different actor is never merged even when article/date/text happen to coincide.
different_actor = make_item("article bytes v4", "2026-08-19T14:00:00Z", person_id="alt-decident")
assert collector.logical_signal_key(first) != collector.logical_signal_key(different_actor)
assert len(collector.deduplicate_signal_history([first, different_actor])) == 2

# Role-at-observation stays anchored to the historical representative when the same
# statement is re-fetched after the registry role has changed.
role_changed = copy.deepcopy(second)
role_changed["roleVerification"] = {
    **ROLE,
    "role": "Funcție ulterioară",
    "verifiedAt": "2026-08-19",
}
role_changed["role"] = "Funcție ulterioară"
role_preserved = collector.deduplicate_signal_history([first, role_changed])[0]
assert role_preserved["roleVerification"] == ROLE
assert role_preserved["role"] == ROLE["role"]

print(json.dumps({
    "stableLogicalSignalIdentity": True,
    "contentVersionsPreserved": 2,
    "repeatObservationCompacted": True,
    "distinctStatementsRemainDistinct": True,
    "distinctActorsRemainDistinct": True,
    "roleAtObservationPreserved": True,
    "administrativeFactFailClosed": True,
}, ensure_ascii=False, indent=2))
