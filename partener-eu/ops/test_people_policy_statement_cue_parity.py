#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INGEST = ROOT / "partener-eu" / "ingest"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


collector = load_module("people_policy_official_ingest", INGEST / "people_policy_official_ingest.py")
builder = load_module("build_people_policy", INGEST / "build_people_policy.py")

# The canonical projection must never reject a speech cue that the collector can
# persist. Extra builder-only administrative context terms remain allowed.
assert set(collector.STATEMENT_CUES) <= set(builder.SIGNAL_EVIDENCE_TERMS)

person = {
    "id": "liviu-gabriel-musat",
    "name": "Liviu-Gabriel Mușat",
    "aliases": ["Liviu-Gabriel Mușat", "Liviu Gabriel Mușat", "Liviu Mușat"],
}
snapshot = {
    "observedAt": "2026-08-19T12:00:00Z",
    "contentHash": "a" * 64,
}
source_url = "https://example.gov.ro/comunicat"
item = {
    "headline": "Finanțări europene pentru dezvoltare regională",
    "statement": "Liviu-Gabriel Mușat a subliniat că finanțarea europeană susține proiectele regionale.",
}
evidence = builder.article_statement_evidence(item, person, source_url, snapshot)
assert evidence is not None
assert builder.norm(evidence["signalCue"]) == builder.norm("a subliniat")
assert evidence["fundingCue"]
assert evidence["status"] == "VERIFIED_ARTICLE_STATEMENT"

# Cue parity must not weaken the actor + funding gates.
no_actor = dict(item)
no_actor["statement"] = "Directorul a subliniat că finanțarea europeană susține proiectele regionale."
assert builder.article_statement_evidence(no_actor, person, source_url, snapshot) is None

no_funding = dict(item)
no_funding["headline"] = "Dezvoltare regională"
no_funding["statement"] = "Liviu-Gabriel Mușat a subliniat că instituția va continua dialogul public."
assert builder.article_statement_evidence(no_funding, person, source_url, snapshot) is None

print("people policy statement cue parity: PASS")
