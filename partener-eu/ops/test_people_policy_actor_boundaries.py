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


collector = load_module("people_policy_official_ingest_actor_boundaries", INGEST / "people_policy_official_ingest.py")
registry = json.loads((STATE / "people_policy_registry.json").read_text(encoding="utf-8"))
sorin = next(person for person in registry["people"] if person["id"] == "sorin-maxim")
assert (sorin.get("roleVerification") or {}).get("status") == "VERIFIED"

# Explicit full-name and surname mentions remain discoverable. Multiple registry
# spellings may fold to the same entity, so assert identity rather than one raw alias.
full_alias = collector.actor_alias(sorin, "Sorin Maxim a declarat că finanțarea europeană rămâne prioritară.")
assert full_alias is not None and collector.fold(full_alias) == "sorin maxim"
assert collector.fold(collector.actor_alias(sorin, "Maxim: finanțarea PNRR trebuie accelerată.")) == "maxim"
assert collector.fold(collector.actor_alias(sorin, "Potrivit lui Maxim, granturile trebuie urmărite atent.")) == "maxim"

# A surname alias must never match inside another lexical token.
for text in (
    "Programul maximizează impactul finanțării PNRR.",
    "Valoarea maximum eligibilă este descrisă în ghid.",
    "Impactul poate fi maximizat prin investiții eligibile.",
):
    assert collector.actor_alias(sorin, text) is None, text
    assert collector.actor_for(text, {"people": [sorin]}) is None, text

# This sentence satisfied actor+speech+funding under substring matching because
# `maxim` occurred inside `maximizează`. It must now fail closed.
false_statement = "Programul maximizează finanțarea PNRR, a declarat autoritatea de management în comunicat."
assert collector.statement_window_for(sorin, false_statement) is None
assert collector.actor_statement_for(false_statement, {"people": [sorin]}) is None

# A real surname/full-name statement still survives the stricter boundary.
valid_statement = "Sorin Maxim a declarat că finanțarea prin Programul Regional Vest va continua pentru investiții."
evidence = collector.statement_window_for(sorin, valid_statement)
assert evidence is not None
assert collector.fold(evidence["actorAlias"]) == "sorin maxim"
assert evidence["scope"] == "SENTENCE"
assert evidence["signalCue"] in collector.STATEMENT_CUES
assert evidence["fundingCue"] in collector.FUNDING_TERMS

# Romanian diacritic folding must not weaken the entity boundary itself.
assert collector.alias_present("Crețu a anunțat finanțarea.", "Cretu") is True
assert collector.alias_present("decretul a fost publicat", "Cretu") is False

print(json.dumps({
    "actorAliasTokenBoundaries": True,
    "surnameSubstringFalsePositiveRejected": True,
    "explicitSurnameMentionPreserved": True,
    "actorSpeechFundingFailClosedPreserved": True,
}, ensure_ascii=False, indent=2))
