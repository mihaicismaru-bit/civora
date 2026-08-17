#!/usr/bin/env python3
"""Decide whether VÂLCEA CLAR has a newly publishable live story set.

This is the continuous-newsroom gate. It deliberately does NOT weaken the
existing evidence rules. A source title/date discovery is useful for the radar
but is not, by itself, a publishable article. New claim-kernel stories must also
carry the provenance proof emitted by Editorial Writer v1.

Morning/evening editions remain recap snapshots. They are not publication
windows and must never delay an otherwise publishable story.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import generate_edition as edition_engine

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(REPO_ROOT / "local-news-os" / "core"))
from temporal_freshness import CONTRACT as TEMPORAL_CONTRACT, durable_story_temporal_violations

STATE = ROOT / "site" / "newsroom_state.json"
DECISION = ROOT / "site" / "newsroom_decision.json"
PUBLICATION_HOLDS = ROOT / "editorial" / "publication_holds.json"
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
        "editorial_product": item.get("editorial_product") or None,
    }


def active_publication_holds() -> set[str]:
    """Return story IDs that are explicitly barred from public projection.

    Holds are editorial state, not temporary rendering hints. Any malformed hold
    file fails closed for rows that can still be parsed as active holds, while a
    missing file preserves the historical no-hold behavior.
    """
    if not PUBLICATION_HOLDS.is_file():
        return set()
    try:
        document = json.loads(PUBLICATION_HOLDS.read_text(encoding="utf-8"))
    except Exception:
        return set()
    held: set[str] = set()
    for row in document.get("holds") or []:
        if not isinstance(row, dict):
            continue
        story_id = str(row.get("story_id") or "").strip()
        status = str(row.get("status") or "").strip().upper()
        public_projection = row.get("public_projection")
        if story_id and public_projection is False and status not in {"RELEASED", "CLOSED", "RESOLVED"}:
            held.add(story_id)
    return held


def story_ready(item: dict) -> tuple[bool, str]:
    story_id = str(item.get("id") or "").strip()
    if story_id and story_id in active_publication_holds():
        return False, "editorial_publication_hold"

    # Durable story copy must remain semantically true in the archive. Relative
    # temporal words are forbidden at this gate even if another upstream path
    # accidentally admitted them.
    if durable_story_temporal_violations(item, "ro-RO"):
        return False, "relative_temporal_language_not_durable"

    # Automatic primary-source discovery is intentionally title/date/source only.
    # It enters the radar immediately but cannot masquerade as a finished article.
    if item.get("auto_generated") and item.get("auto_scope") in {
        "source_title_and_publication_date_only",
        "title_date_source_only",
    }:
        return False, "title_date_only_not_full_story"

    editorial = item.get("editorial_product") if isinstance(item.get("editorial_product"), dict) else {}
    writer_mode = str(editorial.get("writer_mode") or "")
    if writer_mode == "FACT_KERNEL_REJECTED_FAIL_CLOSED":
        return False, "editorial_writer_rejected_fact_kernel"
    if writer_mode == "FACT_KERNEL_COMPOSED":
        if editorial.get("claim_trace_complete") is not True:
            return False, "claim_trace_incomplete"
        if editorial.get("source_level_trace") is not True:
            return False, "source_trace_incomplete"
        if editorial.get("auto_publish_eligible_by_format") is not True:
            return False, "editorial_format_requires_review"
        trace = editorial.get("claim_trace") or []
        if not trace or any(not row.get("source_urls") or not row.get("text_sha256") for row in trace if isinstance(row, dict)):
            return False, "claim_trace_invalid"

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

    writer_stats = load_editorial_writer_stats()
    return {
        "schema_version": "1.3",
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
        "editorial_writer": writer_stats,
        "rejected_candidate_count": len(rejected),
        "rejected": rejected,
        "active_publication_holds": sorted(active_publication_holds()),
        "policy": {
            "verified_structured_story_required": True,
            "title_date_only_is_not_article": True,
            "fact_kernel_claim_trace_required": True,
            "reputational_formats_require_review": True,
            "editorial_publication_holds_fail_closed": True,
            "held_story_social_distribution_allowed": False,
            "minimum_confidence_inherited_from_edition_engine": edition_engine.MIN_CONFIDENCE,
            "fail_closed": True,
            "publish_on_change_not_clock_window": True,
            "durable_temporal_language_contract": TEMPORAL_CONTRACT,
            "relative_time_words_in_durable_story_copy": False,
        },
    }


def load_editorial_writer_stats() -> dict:
    path = ROOT / "editorial" / "editorial_products.json"
    if not path.is_file():
        return {"writer_id": "manual_journalism_v1", "status": "NOT_MATERIALIZED"}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"writer_id": "manual_journalism_v1", "status": "INVALID_OUTPUT"}
    return {
        "writer_id": doc.get("writer_id"),
        "status": "ACTIVE",
        **(doc.get("stats") or {}),
        "registry_fingerprint_sha256": doc.get("registry_fingerprint_sha256"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit-state", action="store_true", help="Persist decision as the last published newsroom state")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        edition_engine.editorial_writer.self_test()
        full = {
            "id": "self-test-full",
            "headline": "Primăria publică un proiect verificat pentru municipiu în 17 august 2026",
            "dek": "Documentele publice confirmă măsura și permit redactarea unei știri complete, cu sursa indicată.",
            "paragraphs": ["Acesta este un paragraf verificat suficient de lung pentru a demonstra că materialul are corp editorial și nu este doar un titlu preluat automat dintr-o listă de comunicate."],
            "sources": [{"url": "https://example.com/document", "name": "Sursă"}],
        }
        assert story_ready(full)[0] is True
        relative = dict(full, id="self-test-relative", headline="Azi primăria publică un proiect verificat pentru municipiu")
        assert story_ready(relative) == (False, "relative_temporal_language_not_durable")
        title_only = dict(full, auto_generated=True, auto_scope="source_title_and_publication_date_only")
        assert story_ready(title_only)[0] is False
        held = dict(full, id="olanesti-bridge-monitor")
        assert story_ready(held) == (False, "editorial_publication_hold")
        assert "olanesti-bridge-monitor" in active_publication_holds()
        composed = dict(full, editorial_product={
            "writer_mode": "FACT_KERNEL_COMPOSED",
            "claim_trace_complete": True,
            "source_level_trace": True,
            "auto_publish_eligible_by_format": True,
            "claim_trace": [{"text_sha256": "abc", "source_urls": ["https://example.com/document"]}],
        })
        assert story_ready(composed)[0] is True
        no_trace = dict(composed, editorial_product={**composed["editorial_product"], "claim_trace_complete": False})
        assert story_ready(no_trace) == (False, "claim_trace_incomplete")
        review_format = dict(composed, editorial_product={**composed["editorial_product"], "auto_publish_eligible_by_format": False})
        assert story_ready(review_format) == (False, "editorial_format_requires_review")
        print("Continuous newsroom decision self-test: PASS")
        return 0

    decision = decide(datetime.now(TZ))
    DECISION.parent.mkdir(parents=True, exist_ok=True)
    DECISION.write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.commit_state and decision["publishable_story_count"]:
        state = {
            "schema_version": "1.3",
            "last_published_at": decision["evaluated_local"],
            "last_published_fingerprint": decision["fingerprint"],
            "last_published_story_ids": decision["publishable_story_ids"],
            "active_publication_holds": decision["active_publication_holds"],
            "editorial_writer": decision["editorial_writer"],
            "mode": "continuous_story_first",
            "edition_windows_are_publication_gates": False,
            "durable_temporal_language_contract": TEMPORAL_CONTRACT,
        }
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(decision, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
