#!/usr/bin/env python3
"""Decide whether VÂLCEA CLAR has a newly publishable live story set.

This is the continuous-newsroom gate. It deliberately does NOT weaken the
existing evidence rules. A source title/date discovery is useful for the radar
but is not, by itself, a publishable article. The live newsroom only advances
when the structured story set that meets the editorial standard changes.

Morning/evening editions remain recap snapshots. They are not publication
windows and must never delay an otherwise publishable story.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import generate_edition as edition_engine

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "site" / "newsroom_state.json"
DECISION = ROOT / "site" / "newsroom_decision.json"
TZ = ZoneInfo("Europe/Bucharest")


def canonical_story(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "section": item.get("section"),
        "priority": int(item.get("priority") or 0),
        "headline": item.get("headline") or "",
        "dek": item.get("dek") or "",
        "paragraphs": [str(p).strip() for p in item.get("paragraphs", []) if str(p).strip()],
        "material_fact_gate": item.get("material_fact_gate"),
        "sources": [
            {
                "name": src.get("name"),
                "url": src.get("url"),
                "tier": src.get("tier"),
            }
            for src in item.get("sources", [])
            if src.get("url")
        ],
        "visual": item.get("visual") or None,
    }


def story_ready(item: dict) -> tuple[bool, str]:
    # Automatic primary-source discovery is intentionally title/date/source only.
    # It enters the radar immediately but cannot masquerade as a finished article.
    if item.get("auto_generated") and item.get("auto_scope") in {
        "source_title_and_publication_date_only",
        "title_date_source_only",
    }:
        return False, "title_date_only_not_full_story"

    headline = str(item.get("headline") or "").strip()
    dek = str(item.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in item.get("paragraphs", []) if str(p).strip()]
    sources = [src for src in item.get("sources", []) if src.get("url")]

    if len(headline) < 12:
        return False, "headline_too_short"
    if len(dek) < 35:
        return False, "dek_too_short"
    if not paragraphs:
        return False, "no_verified_body"
    if sum(len(p) for p in paragraphs) < 120:
        return False, "verified_body_too_thin"
    if not sources:
        return False, "no_source_url"
    return True, "publishable_story"


def digest(stories: list[dict]) -> str:
    raw = json.dumps(stories, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_state() -> dict:
    if not STATE.is_file():
        return {}
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def decide(now: datetime) -> dict:
    registry, auto_count = edition_engine.merged_registry()
    slot = edition_engine.choose_slot(now, "auto")
    eligible = edition_engine.eligible_facts(registry, now, slot)

    publishable: list[dict] = []
    rejected: list[dict] = []
    for item in eligible:
        ok, reason = story_ready(item)
        if ok:
            publishable.append(canonical_story(item))
        else:
            rejected.append({"id": item.get("id"), "reason": reason})

    publishable.sort(key=lambda x: (-x["priority"], x["id"] or ""))
    fingerprint = digest(publishable)
    previous = load_state()
    changed = bool(publishable) and fingerprint != previous.get("last_published_fingerprint")

    previous_ids = set(previous.get("last_published_story_ids") or [])
    current_ids = [story["id"] for story in publishable]
    new_ids = [story_id for story_id in current_ids if story_id not in previous_ids]

    return {
        "schema_version": "1.0",
        "evaluated_local": now.isoformat(timespec="seconds"),
        "mode": "continuous_story_first",
        "edition_windows_are_publication_gates": False,
        "recap_editions_retained": True,
        "slot_for_legacy_snapshot_compatibility": slot,
        "changed": changed,
        "publishable_story_count": len(publishable),
        "publishable_story_ids": current_ids,
        "new_story_ids": new_ids,
        "fingerprint": fingerprint,
        "auto_fact_registry_count": auto_count,
        "rejected_candidate_count": len(rejected),
        "rejected": rejected,
        "policy": {
            "verified_structured_story_required": True,
            "title_date_only_is_not_article": True,
            "minimum_confidence_inherited_from_edition_engine": edition_engine.MIN_CONFIDENCE,
            "fail_closed": True,
            "publish_on_change_not_clock_window": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit-state", action="store_true", help="Persist decision as the last published newsroom state")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        full = {
            "headline": "Primăria publică un proiect verificat pentru municipiu",
            "dek": "Documentele publice confirmă măsura și permit redactarea unei știri complete, cu sursa indicată.",
            "paragraphs": ["Acesta este un paragraf verificat suficient de lung pentru a demonstra că materialul are corp editorial și nu este doar un titlu preluat automat dintr-o listă de comunicate."],
            "sources": [{"url": "https://example.com/document", "name": "Sursă"}],
        }
        assert story_ready(full)[0] is True
        title_only = dict(full, auto_generated=True, auto_scope="source_title_and_publication_date_only")
        assert story_ready(title_only)[0] is False
        print("Continuous newsroom decision self-test: PASS")
        return 0

    decision = decide(datetime.now(TZ))
    DECISION.parent.mkdir(parents=True, exist_ok=True)
    DECISION.write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.commit_state and decision["publishable_story_count"]:
        state = {
            "schema_version": "1.0",
            "last_published_at": decision["evaluated_local"],
            "last_published_fingerprint": decision["fingerprint"],
            "last_published_story_ids": decision["publishable_story_ids"],
            "mode": "continuous_story_first",
            "edition_windows_are_publication_gates": False,
        }
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(decision, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
