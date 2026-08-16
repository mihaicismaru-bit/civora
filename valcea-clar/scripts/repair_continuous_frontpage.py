#!/usr/bin/env python3
"""Repair and enforce the continuous story-first VÂLCEA CLAR homepage.

Morning/evening editions are compatibility recap snapshots. They may add or
omit stories according to their time window, but they must never delete an
already published canonical story from the live homepage, story manifest, live
feed or sitemap.

This repair layer deterministically rebuilds the public story archive from all
publishable edition snapshots that have already been committed. Only reader-
facing items that pass the full-story gate are admitted; title/date/source-only
automatic candidates and operational telemetry remain hidden. The current
edition is retained only as compatibility metadata.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import render_frontpage as frontpage
import render_story_pages as story_renderer
from newsroom_decide import story_ready

ROOT = Path(__file__).resolve().parents[1]
EDITIONS = ROOT / "editions"
FACTS = ROOT / "editorial" / "facts_registry.json"
POINTER = ROOT / "site" / "current_edition.json"
ARCHIVE = ROOT / "site" / "story_archive.json"
RUNTIME = ROOT / "site" / "runtime"
PLACES = ROOT / "web" / "data" / "places.json"
PUBLISHABLE = {"auto_approved", "editor_approved"}
HIDDEN_OPERATIONAL_IDS = {
    "unde-iesim-operational",
    "source-radar-operational",
}
HIDDEN_SECTIONS = {
    "NOTA_REDACTIEI",
    "OPERATIONAL",
    "OPERAȚIONAL",
    "SISTEM",
}
TZ = ZoneInfo("Europe/Bucharest")
BASE = "https://valceaclar.ro"


def load(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        if default is not None:
            return default
        raise SystemExit(f"Missing required input: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def parse_stamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    return parsed


def public_reader_item(item: dict[str, Any]) -> bool:
    story_id = str(item.get("id") or "").strip()
    section = str(item.get("section") or "").strip().upper()
    if not story_id:
        return False
    if story_id in HIDDEN_OPERATIONAL_IDS or story_id.endswith("-operational"):
        return False
    if section in HIDDEN_SECTIONS:
        return False
    if item.get("internal_operational_telemetry") is True or item.get("operational_only") is True:
        return False
    return True


def canonical_story(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "section": item.get("section"),
        "priority": int(item.get("priority") or 0),
        "headline": item.get("headline") or "",
        "dek": item.get("dek") or "",
        "paragraphs": [str(p).strip() for p in item.get("paragraphs", []) if str(p).strip()],
        "confidence": int(item.get("confidence") or 0),
        "material_fact_gate": item.get("material_fact_gate"),
        "sources": [
            {
                "name": src.get("name"),
                "url": src.get("url"),
                "tier": src.get("tier"),
            }
            for src in item.get("sources", [])
            if isinstance(src, dict) and src.get("url")
        ],
        **({"visual": item.get("visual")} if item.get("visual") else {}),
    }


def collect_from_documents(documents: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the durable union of reader-facing full stories from recaps."""
    rows: dict[str, dict[str, Any]] = {}
    for doc in documents:
        if doc.get("status") not in PUBLISHABLE or doc.get("publication_intent") != "publish":
            continue
        stamp = str(doc.get("updated_local") or "").strip()
        edition_id = str(doc.get("edition_id") or "").strip()
        for item in doc.get("items", []):
            if not isinstance(item, dict) or not public_reader_item(item):
                continue
            ok, _reason = story_ready(item)
            if not ok:
                continue
            story_id = str(item.get("id") or "").strip()
            previous = rows.get(story_id)
            row = canonical_story(item)
            row["first_published_at"] = (
                previous.get("first_published_at") if previous else stamp
            ) or stamp
            row["last_seen_at"] = stamp
            row["last_seen_edition"] = edition_id
            rows[story_id] = row
    return list(rows.values())


def current_fact_index() -> dict[str, dict[str, Any]]:
    doc = load(FACTS, {"facts": []})
    return {
        str(item.get("id")): item
        for item in doc.get("facts", [])
        if isinstance(item, dict) and item.get("id")
    }


def mark_activity(stories: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    facts = current_fact_index()
    for story in stories:
        fact = facts.get(str(story.get("id"))) or {}
        valid_from = parse_stamp(fact.get("valid_from"))
        valid_until = parse_stamp(fact.get("valid_until"))
        active = bool(valid_from and valid_until and valid_from <= now <= valid_until)
        story["archive_status"] = "active" if active else "published_archive"
        story["active_now"] = active
        story["path"] = story_renderer.route_for(story)
        story["canonical_url"] = BASE + story["path"]
    return stories


def sort_stories(stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def epoch(value: object) -> float:
        parsed = parse_stamp(value)
        return parsed.timestamp() if parsed else 0.0

    return sorted(
        stories,
        key=lambda item: (
            -int(bool(item.get("active_now"))),
            -epoch(item.get("last_seen_at")),
            -int(item.get("priority") or 0),
            str(item.get("id") or ""),
        ),
    )


def collect_archive(now: datetime | None = None) -> list[dict[str, Any]]:
    documents = []
    for path in sorted(EDITIONS.glob("*.json")):
        try:
            doc = load(path)
        except Exception:
            continue
        if isinstance(doc, dict):
            documents.append(doc)
    stories = collect_from_documents(documents)
    return sort_stories(mark_activity(stories, now or datetime.now(TZ)))


def archive_payload(stories: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "publication_model": "continuous_story_first",
        "generated_at": now.isoformat(timespec="seconds"),
        "retention_policy": "published_full_stories_persist_after_recap_or_validity_window_expires",
        "recap_editions_may_delete_published_stories": False,
        "operational_records_public": False,
        "story_count": len(stories),
        "stories": stories,
    }


def render_story_archive(stories: list[dict[str, Any]], updated_local: str) -> list[dict[str, Any]]:
    story_root = RUNTIME / "stiri"
    story_root.mkdir(parents=True, exist_ok=True)
    previous_manifest = load(story_root / "manifest.json", {"stories": []})
    visual_registry = story_renderer.load_optional(story_renderer.STORY_VISUALS)
    asset_manifest = story_renderer.load_optional(story_renderer.SOCIAL_ASSETS)

    publication_dates = story_renderer.reconcile_publication_dates(
        [item.get("id") for item in stories],
        previous_manifest.get("stories") or [],
        new_story_ids=[],
        published_at=None,
        bootstrap_event=story_renderer.load_optional(story_renderer.PUBLICATION_EVENT),
    )
    for item in stories:
        sid = str(item.get("id") or "")
        if sid and sid not in publication_dates and item.get("first_published_at"):
            publication_dates[sid] = str(item["first_published_at"])

    routes: list[dict[str, Any]] = []
    for item in stories:
        story_id = str(item.get("id") or "")
        route = story_renderer.route_for(item)
        related = story_renderer.rank_related(item, stories, limit=story_renderer.RELATED_LIMIT)
        published_at = publication_dates.get(story_id)
        media = story_renderer.resolve_verified_story_image(
            story_id,
            visual_registry,
            asset_manifest,
            runtime_asset_dir=story_renderer.RUNTIME_MEDIA,
            canonical_media_base_url=story_renderer.MEDIA_BASE,
        )
        target = RUNTIME / route.strip("/") / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            story_renderer.page(item, updated_local, stories, published_at, media),
            encoding="utf-8",
        )
        row: dict[str, Any] = {
            "id": story_id,
            "path": route,
            "canonical": BASE + route,
            "archive_status": item.get("archive_status"),
            "active_now": bool(item.get("active_now")),
            "related_story_ids": [story.get("id") for story in related],
            "structured_data_type": "NewsArticle",
        }
        if published_at:
            row["published_at"] = published_at
        if media:
            row["image"] = {
                "public_url": media["public_url"],
                "source_url": media["source_url"],
                "credit": media["credit"],
                "rights_basis": media["rights_basis"],
                "contextual_archive": media["contextual_archive"],
                "captured_at": media["captured_at"],
                "synthetic": False,
                "provenance_status": media["provenance_status"],
            }
        routes.append(row)

    manifest = {
        "schema_version": "1.5",
        "publication_model": "continuous_story_first",
        "homepage_presentation": "live_newsroom",
        "edition_is_canonical_story_url": False,
        "persistence_policy": "published_story_routes_survive_recap_turnover",
        "operational_records_public": False,
        "stories": routes,
    }
    (story_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return routes


def venue_rows(places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": p.get("id"),
            "slug": p.get("slug"),
            "name": p.get("name"),
            "type": p.get("type"),
            "city": (p.get("location") or {}).get("city"),
            "summary": (p.get("editorial") or {}).get("dek") or (p.get("offer") or {}).get("summary"),
            "badges": p.get("badges", [])[:2],
        }
        for p in places[:8]
    ]


def write_live_feed(
    stories: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    pointer: dict[str, Any],
    snapshot: dict[str, Any],
    places: list[dict[str, Any]],
    now: datetime,
) -> None:
    route_index = {str(row.get("id")): row for row in routes}
    feed_stories = []
    for item in stories:
        route = route_index.get(str(item.get("id"))) or {}
        feed_stories.append({
            "id": item.get("id"),
            "section": item.get("section"),
            "priority": item.get("priority"),
            "headline": item.get("headline"),
            "dek": item.get("dek"),
            "paragraphs": item.get("paragraphs", []),
            "path": route.get("path") or item.get("path"),
            "canonical_url": route.get("canonical") or item.get("canonical_url"),
            "sources": item.get("sources", []),
            "archive_status": item.get("archive_status"),
            "active_now": bool(item.get("active_now")),
            "visual": item.get("visual"),
        })
    payload = {
        "schema_version": "2.2",
        "generated_at": now.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z"),
        "canonical_domain": "valceaclar.ro",
        "publication_model": "continuous_story_first",
        "stories": feed_stories,
        "story_count": len(feed_stories),
        "edition": snapshot,
        "pointer": pointer,
        "compatibility_snapshot": snapshot,
        "compatibility_pointer": pointer,
        "unde_iesim": venue_rows(places),
        "policy": {
            "verified_facts_only": True,
            "candidate_records_hidden": True,
            "operational_records_hidden": True,
            "paid_llm_api_required": False,
            "individual_story_is_publication_unit": True,
            "edition_windows_are_publication_gates": False,
            "edition_fields_are_compatibility_only": True,
            "published_story_persistence": True,
            "recap_render_may_not_remove_story_routes": True,
            "expired_event_story_remains_archived_not_deleted": True,
        },
    }
    (RUNTIME / "live-feed.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_homepage(
    stories: list[dict[str, Any]],
    pointer: dict[str, Any],
    snapshot: dict[str, Any],
    places: list[dict[str, Any]],
) -> None:
    live_doc = dict(snapshot)
    live_doc["items"] = stories
    live_doc["title"] = "VÂLCEA CLAR — Știri live din Vâlcea"
    html = frontpage.render_home(live_doc, pointer, places)
    html = story_renderer.normalize_live_frontpage(html)
    (RUNTIME / "index.html").write_text(html, encoding="utf-8")
    story_renderer.link_frontpage(stories)


def write_indexing(routes: list[dict[str, Any]]) -> dict[str, Any]:
    paths = ["/"] + [str(row["path"]) for row in routes if row.get("path")]
    for static_path in ("/unde-iesim/", "/termeni/", "/confidentialitate/"):
        static_file = RUNTIME / static_path.strip("/") / "index.html"
        if static_file.is_file() and static_path not in paths:
            paths.append(static_path)
    return story_renderer.write_indexing_assets(RUNTIME, BASE, paths)


def repair() -> dict[str, Any]:
    now = datetime.now(TZ)
    pointer = load(POINTER)
    snapshot = load(ROOT / str(pointer["json_source"]))
    places = load(PLACES, {"places": []}).get("places", [])
    stories = collect_archive(now)
    if not stories:
        raise SystemExit("Refusing continuous-frontpage repair: no previously published full stories")

    RUNTIME.mkdir(parents=True, exist_ok=True)
    ARCHIVE.write_text(
        json.dumps(archive_payload(stories, now), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    routes = render_story_archive(stories, str(snapshot.get("updated_local") or now.isoformat()))
    write_homepage(stories, pointer, snapshot, places)
    write_live_feed(stories, routes, pointer, snapshot, places, now)
    indexing = write_indexing(routes)

    result = {
        "status": "PASS",
        "publication_model": "continuous_story_first",
        "story_count": len(stories),
        "active_story_count": sum(1 for item in stories if item.get("active_now")),
        "archived_story_count": sum(1 for item in stories if not item.get("active_now")),
        "compatibility_edition": snapshot.get("edition_id"),
        "routes": len(routes),
        "indexing_routes": indexing.get("route_count"),
        "frontpage": "site/runtime/index.html",
        "feed": "site/runtime/live-feed.json",
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


def self_test() -> int:
    full = {
        "id": "kept-story",
        "section": "LOCAL",
        "priority": 90,
        "headline": "O știre locală completă rămâne publicată după recap",
        "dek": "Documentele publice permit publicarea unei știri complete și verificabile pentru cititori.",
        "paragraphs": [
            "Acesta este un corp editorial verificat suficient de lung pentru a trece pragul de publicare și pentru a demonstra că povestea trebuie păstrată în arhiva live chiar dacă o ediție ulterioară nu o mai include."
        ],
        "confidence": 99,
        "material_fact_gate": "PASS",
        "sources": [{"name": "Sursă", "url": "https://example.test/source", "tier": "T1"}],
    }
    thin_auto = {
        **full,
        "id": "thin-auto",
        "auto_generated": True,
        "auto_scope": "source_title_and_publication_date_only",
    }
    operational = {
        **full,
        "id": "source-radar-operational",
        "headline": "Starea internă a surselor nu este știre pentru cititor",
    }
    first = {
        "edition_id": "2026-08-16-evening",
        "updated_local": "2026-08-16T20:00:00+03:00",
        "status": "auto_approved",
        "publication_intent": "publish",
        "items": [full, thin_auto, operational],
    }
    second = {
        "edition_id": "2026-08-17-morning",
        "updated_local": "2026-08-17T08:00:00+03:00",
        "status": "auto_approved",
        "publication_intent": "publish",
        "items": [],
    }
    archived = collect_from_documents([first, second])
    assert [row["id"] for row in archived] == ["kept-story"]
    assert archived[0]["first_published_at"] == "2026-08-16T20:00:00+03:00"
    assert archived[0]["last_seen_edition"] == "2026-08-16-evening"
    assert public_reader_item(operational) is False
    print("VÂLCEA CLAR continuous-frontpage persistence self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    repair()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
