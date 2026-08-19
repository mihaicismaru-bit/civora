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


collector = load_module("people_policy_official_ingest_actor_boundaries", INGEST / "people_policy_official_ingest.py")
builder = load_module("build_people_policy_actor_boundaries", INGEST / "build_people_policy.py")
registry = json.loads((STATE / "people_policy_registry.json").read_text(encoding="utf-8"))
sorin = next(person for person in registry["people"] if person["id"] == "sorin-maxim")
assert (sorin.get("roleVerification") or {}).get("status") == "VERIFIED"

# Explicit full-name and surname mentions remain discoverable. Multiple registry
# spellings may fold to the same entity, so assert identity rather than one raw alias.
full_alias = collector.actor_alias(sorin, "Sorin Maxim a declarat că finanțarea europeană rămâne prioritară.")
assert full_alias is not None and collector.fold(full_alias) == "sorin maxim"
assert collector.fold(collector.actor_alias(sorin, "Maxim: finanțarea PNRR trebuie accelerată.")) == "maxim"
assert collector.fold(collector.actor_alias(sorin, "Potrivit lui Maxim, granturile trebuie urmărite atent.")) == "maxim"

# A surname alias must never match inside another lexical token at collection.
for text in (
    "Programul maximizează impactul finanțării PNRR.",
    "Valoarea maximum eligibilă este descrisă în ghid.",
    "Impactul poate fi maximizat prin investiții eligibile.",
):
    assert collector.actor_alias(sorin, text) is None, text
    assert collector.actor_for(text, {"people": [sorin]}) is None, text
    assert builder.actor_alias(sorin, text) is None, text

# This sentence satisfied actor+speech+funding under substring matching because
# `maxim` occurred inside `maximizează`. It must now fail closed.
false_statement = "Programul maximizează finanțarea PNRR, a declarat autoritatea de management în comunicat."
assert collector.statement_window_for(sorin, false_statement) is None
assert collector.actor_statement_for(false_statement, {"people": [sorin]}) is None
assert builder.actor_alias(sorin, false_statement) is None

# A real surname/full-name statement still survives the stricter boundary in
# both the collector and the projection trust barrier.
valid_statement = "Sorin Maxim a declarat că finanțarea prin Programul Regional Vest va continua pentru investiții."
evidence = collector.statement_window_for(sorin, valid_statement)
assert evidence is not None
assert collector.fold(evidence["actorAlias"]) == "sorin maxim"
assert evidence["scope"] == "SENTENCE"
assert evidence["signalCue"] in collector.STATEMENT_CUES
assert evidence["fundingCue"] in collector.FUNDING_TERMS
builder_alias = builder.actor_alias(sorin, valid_statement)
assert builder_alias is not None and builder.norm(builder_alias) == "sorin maxim"

# Romanian diacritic folding must not weaken the entity boundary itself.
assert collector.alias_present("Crețu a anunțat finanțarea.", "Cretu") is True
assert collector.alias_present("decretul a fost publicat", "Cretu") is False
assert builder.alias_present("Crețu a anunțat finanțarea.", "Cretu") is True
assert builder.alias_present("decretul a fost publicat", "Cretu") is False

# Revalidate the durable projection boundary, not only collection. An older
# ledger row carrying the historical substring false-positive must be rejected
# when people_policy is rebuilt, while an otherwise identical real statement is
# still accepted.
role = builder.role_snapshot(sorin)
assert role is not None
source_url = "https://adrvest.ro/comunicate/test-actor-boundary"
snapshot = {
    "sourceId": "ADR_VEST_NEWS",
    "publisher": "ADR Vest",
    "tier": "T1_DIRECT_OFFICIAL",
    "url": source_url,
    "observedAt": "2026-08-19T18:00:00Z",
    "contentHash": "a" * 64,
}
ledger_row = {
    "id": "official-actor-boundary-regression",
    "personId": "sorin-maxim",
    "person": sorin["name"],
    "role": role["role"],
    "institution": role["institution"],
    "roleVerification": role,
    "date": "2026-08-19",
    "type": "FUNDING_COMMITMENT",
    "signalKind": "STATEMENT_SIGNAL",
    "topic": "Programul Regional Vest",
    "headline": "Finanțări pentru investiții regionale",
    "statement": false_statement,
    "officialFact": "Niciun efect administrativ nu este promovat din această declarație.",
    "administrativeFact": {"status": "UNCONFIRMED_FROM_SIGNAL", "failClosed": True},
    "analysis": "Semnal relevant doar pentru monitorizare.",
    "watch": "Documentul oficial aplicabil.",
    "audiences": ["Beneficiari", "Consultanți"],
    "canonicalLink": {"status": "UNRESOLVED"},
    "sources": [{"label": "ADR Vest", "url": source_url, "tier": "T1_DIRECT_OFFICIAL"}],
    "sourceSnapshot": snapshot,
    "fingerprint": "b" * 64,
    "officialIngested": True,
}
tracked = {"sorin-maxim": sorin}
assert builder.trusted_official_item(ledger_row, tracked) is None
valid_ledger_row = copy.deepcopy(ledger_row)
valid_ledger_row["statement"] = valid_statement
assert builder.trusted_official_item(valid_ledger_row, tracked) is not None

print(json.dumps({
    "actorAliasTokenBoundaries": True,
    "surnameSubstringFalsePositiveRejected": True,
    "explicitSurnameMentionPreserved": True,
    "actorSpeechFundingFailClosedPreserved": True,
    "projectionTrustBarrierRejectsHistoricalSubstringCollision": True,
}, ensure_ascii=False, indent=2))
