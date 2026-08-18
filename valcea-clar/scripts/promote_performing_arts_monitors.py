#!/usr/bin/env python3
"""Promote performing-arts monitors and source-change signals into the general VÂLCEA CLAR monitor registry.

The general Editorial Opportunity Engine consumes monitor_registry.json. This
bridge keeps performing arts as a first-class newsroom source without granting
publication authority to a calendar change or source hash change.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERAL = ROOT / "editorial" / "monitor_registry.json"
CULTURE = ROOT / "editorial" / "performing_arts_monitor_registry.json"
CANDIDATES = ROOT / "editorial" / "performing_arts_update_candidates.json"
PREFIXES = ("performing-arts-", "performing-arts-signal-")


def load(path: Path, default: dict) -> dict:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_monitor(row: dict) -> dict:
    item = dict(row)
    item.setdefault("status", "ACTIVE_REVERIFY")
    item.setdefault("publication_mode", "STORY_ONLY_AFTER_PRIMARY_EVIDENCE")
    item["public_projection"] = False
    item["normal_story_ready_gate_required"] = True
    return item


def signal_monitor(candidate: dict) -> dict:
    key = str(candidate.get("key") or "").strip()
    institution = str(candidate.get("institution") or candidate.get("source_id") or "Sursă culturală").strip()
    money = bool(candidate.get("public_money_signal"))
    programme = bool(candidate.get("programme_signal"))
    priority = 94 if money else (91 if programme else 86)
    signals = []
    if programme: signals.append("program/stagiune")
    if money: signals.append("bani publici")
    if not signals: signals.append("modificare sursă")
    return {
        "id": f"performing-arts-signal-{key}",
        "label": f"{institution} — semnal nou: {', '.join(signals)}",
        "section": "CULTURĂ",
        "status": "ACTIVE_REVERIFY",
        "priority": priority,
        "purpose": "Semnal de modificare detectat automat într-o sursă de spectacole. Data evenimentului nu este tratată ca dată de publicare, iar schimbarea sursei trebuie reverificată înainte de orice articol.",
        "publication_mode": "STORY_ONLY_AFTER_PRIMARY_EVIDENCE",
        "public_projection": False,
        "source_bindings": [{
            "ref_type": "url",
            "id": candidate.get("source_id"),
            "publisher": institution,
            "url": candidate.get("url"),
            "tier": candidate.get("tier"),
        }],
        "recovered_leads": [{
            "id": f"performing-arts-lead-{key}",
            "label": f"Schimbare materială în {institution}",
            "verification_status": "REVERIFY",
            "public_projection": False,
            "recovery_note": str(candidate.get("excerpt") or "")[:1000],
            "source_contract": candidate.get("source_contract"),
            "scope": candidate.get("scope") or [],
            "event_date_is_not_published_at": True,
            "public_money_signal": money,
            "programme_signal": programme,
        }],
        "normal_story_ready_gate_required": True,
    }


def build() -> tuple[dict, int, int]:
    general = load(GENERAL, {})
    base_rows = [
        row for row in (general.get("monitors") or [])
        if isinstance(row, dict) and not str(row.get("id") or "").startswith(PREFIXES)
    ]
    culture_doc = load(CULTURE, {})
    culture_rows = [normalize_monitor(row) for row in culture_doc.get("monitors") or [] if isinstance(row, dict)]
    candidates_doc = load(CANDIDATES, {"candidates": []})
    signal_rows = [
        signal_monitor(row) for row in candidates_doc.get("candidates") or []
        if isinstance(row, dict) and row.get("status") == "needs_editorial_verification" and row.get("key")
    ]
    ids: set[str] = set()
    merged = []
    for row in base_rows + culture_rows + signal_rows:
        mid = str(row.get("id") or "")
        if not mid or mid in ids:
            continue
        ids.add(mid)
        merged.append(row)
    output = dict(general)
    output["monitors"] = merged
    policy = output.setdefault("policy", {})
    policy["performing_arts_sources_feed_general_opportunity_engine"] = True
    policy["event_date_may_not_be_inferred_as_published_at"] = True
    policy["performing_arts_source_change_is_not_story"] = True
    return output, len(culture_rows), len(signal_rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output, stable, signals = build()
    if not any(str(row.get("id") or "").startswith("performing-arts-") for row in output.get("monitors") or []):
        raise SystemExit("performing arts monitors were not promoted")
    if args.check:
        print(json.dumps({"status":"PASS","stable_monitors":stable,"signal_monitors":signals}, ensure_ascii=False))
        return 0
    GENERAL.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status":"PASS","stable_monitors":stable,"signal_monitors":signals,"general_monitor_count":len(output.get("monitors") or [])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
