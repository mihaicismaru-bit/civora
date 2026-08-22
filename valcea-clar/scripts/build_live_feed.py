#!/usr/bin/env python3
"""Build the public live feed for the continuous VÂLCEA CLAR newsroom.

The current edition document is retained as a compatibility snapshot, but the
public feed exposes individual stories and canonical story URLs as the primary
publication model. Edition windows never authorize or delay story publication.

Publication timestamps are stable state. Existing archive timestamps always
win. When the archive has not yet absorbed a same-day publication, the last
persisted live feed from Git HEAD is the next source of truth. Only a genuinely
newly admitted story may use the `published_at` value just reconciled and
validated in the canonical story manifest. This closes the first-publication
handoff without inventing a second clock or weakening any publication gate.

Verified story photographs are projected from the canonical story manifest.
The feed never invents a visual: only provenance-backed real media with a public
URL is admitted, and contextual photographs must retain their disclosure. A
media-only refresh mode updates that projection without changing generated_at
or any editorial timestamp.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
POINTER = ROOT / "site" / "current_edition.json"
PLACES = ROOT / "web" / "data" / "places.json"
OUT = ROOT / "site" / "runtime" / "live-feed.json"
STORY_MANIFEST = ROOT / "site" / "runtime" / "stiri" / "manifest.json"
STORY_ARCHIVE = ROOT / "site" / "story_archive.json"
PUBLISHABLE = {"auto_approved", "editor_approved"}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ensure_story_runtime() -> None:
    # render_frontpage.py recreates site/runtime. Recap workflows still call it
    # for compatibility, so immediately restore canonical story routes and the
    # live-newsroom homepage presentation before exporting the site.
    if STORY_MANIFEST.is_file():
        return
    import render_story_pages
    code = render_story_pages.main()
    if code not in (None, 0) or not STORY_MANIFEST.is_file():
        raise SystemExit("Refusing live feed: canonical story runtime was not rendered")


def published_feed_dates_from_doc(doc: dict) -> dict[str, str]:
    if doc.get("publication_model") != "continuous_story_first":
        return {}
    return {
        str(item.get("id")): str(item.get("first_published_at") or "").strip()
        for item in doc.get("stories", [])
        if isinstance(item, dict) and item.get("id") and item.get("first_published_at")
    }


def previous_published_feed_dates() -> dict[str, str]:
    """Read stable timestamps from the last persisted feed, even after runtime reset.

    render_frontpage.py intentionally recreates site/runtime before this builder
    runs. The worktree copy of live-feed.json can therefore be gone while Git
    HEAD still contains the exact feed that was publicly projected before the
    current transaction. Reading that committed object preserves publication
    history without inventing timestamps or trusting a volatile working file.
    """
    if OUT.is_file():
        try:
            dates = published_feed_dates_from_doc(load(OUT))
            if dates:
                return dates
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

    try:
        rel = OUT.relative_to(REPO).as_posix()
        raw = subprocess.check_output(
            ["git", "show", f"HEAD:{rel}"],
            cwd=REPO,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=8,
        )
        doc = json.loads(raw)
        if isinstance(doc, dict):
            return published_feed_dates_from_doc(doc)
    except (OSError, ValueError, TypeError, json.JSONDecodeError, subprocess.SubprocessError):
        pass
    return {}


def resolve_first_published_at(
    story_id: str,
    route: dict,
    archive_dates: dict[str, str],
    previous_feed_dates: dict[str, str] | None = None,
) -> str:
    """Resolve a stable publication timestamp without creating a new clock."""
    archived = str(archive_dates.get(story_id) or "").strip()
    if archived:
        return archived
    previous = str((previous_feed_dates or {}).get(story_id) or "").strip()
    if previous:
        return previous
    return str(route.get("published_at") or "").strip()


def verified_visual(value: object) -> dict | None:
    """Return a safe public visual or fail closed."""
    if not isinstance(value, dict):
        return None
    if value.get("provenance_status") != "VERIFIED":
        return None
    if value.get("synthetic") is True:
        return None
    if not str(value.get("public_url") or "").strip():
        return None
    if value.get("contextual_archive") is True and not str(value.get("editorial_note") or "").strip():
        return None
    return copy.deepcopy(value)


def resolve_story_visual(item: dict, route: dict) -> dict | None:
    """Prefer the canonical story-manifest image over legacy snapshot media."""
    manifest_visual = verified_visual(route.get("image"))
    if manifest_visual:
        return manifest_visual
    return verified_visual(item.get("visual"))


def manifest_routes() -> dict[str, dict]:
    manifest = load(STORY_MANIFEST)
    return {
        str(item.get("id")): item
        for item in manifest.get("stories", [])
        if isinstance(item, dict) and item.get("id") and item.get("canonical")
    }


def story_feed(snapshot: dict) -> list[dict]:
    routes = manifest_routes()
    archive = load(STORY_ARCHIVE)
    archive_dates = {
        str(item.get("id")): str(item.get("first_published_at") or "").strip()
        for item in archive.get("stories", [])
        if isinstance(item, dict) and item.get("id") and item.get("first_published_at")
    }
    previous_feed_dates = previous_published_feed_dates()
    stories = []
    for item in snapshot.get("items", []):
        story_id = str(item.get("id") or "")
        route = routes.get(story_id)
        if not route:
            continue
        first_published_at = resolve_first_published_at(
            story_id,
            route,
            archive_dates,
            previous_feed_dates,
        )
        if not first_published_at:
            raise SystemExit(f"Refusing live feed: missing first_published_at for {story_id}")
        stories.append({
            "id": story_id,
            "section": item.get("section"),
            "priority": item.get("priority"),
            "headline": item.get("headline"),
            "dek": item.get("dek"),
            "paragraphs": item.get("paragraphs", []),
            "path": route.get("path"),
            "canonical_url": route.get("canonical"),
            "sources": item.get("sources", []),
            "visual": resolve_story_visual(item, route),
            "first_published_at": first_published_at,
        })
    stories.sort(key=lambda item: (-int(item.get("priority") or 0), item["id"]))
    return stories


def refresh_media_only() -> int:
    """Reconcile feed visuals from the already-authorized story manifest.

    This is intentionally timestamp-stable. It is run after the derived media
    projector has finished enriching the manifest, so the public bridge receives
    the same verified photograph and disclosure as the canonical article page.
    """
    if not OUT.is_file():
        raise SystemExit("Refusing media-only refresh: live feed is missing")
    ensure_story_runtime()
    feed = load(OUT)
    if feed.get("publication_model") != "continuous_story_first" or not isinstance(feed.get("stories"), list):
        raise SystemExit("Refusing media-only refresh: invalid story-first feed")
    routes = manifest_routes()
    changed = 0
    projected = 0
    for story in feed["stories"]:
        if not isinstance(story, dict) or not story.get("id"):
            continue
        route = routes.get(str(story["id"]))
        if not route:
            continue
        # The post-projection manifest is canonical for presentation. If it has
        # no eligible image, remove any stale feed visual instead of carrying it.
        resolved = verified_visual(route.get("image"))
        if story.get("visual") != resolved:
            story["visual"] = resolved
            changed += 1
        if resolved:
            projected += 1
    feed["schema_version"] = "2.3"
    policy = feed.setdefault("policy", {})
    policy["story_visual_source"] = "verified_story_manifest"
    policy["contextual_visual_disclosure_required"] = True
    policy["synthetic_story_media_allowed"] = False
    before_generated_at = feed.get("generated_at")
    write(OUT, feed)
    if feed.get("generated_at") != before_generated_at:
        raise SystemExit("Media-only refresh illegally changed generated_at")
    print(json.dumps({
        "status": "PASS",
        "mode": "media_only",
        "changed_story_visuals": changed,
        "stories_with_verified_visual": projected,
        "generated_at_preserved": True,
        "feed": str(OUT.relative_to(ROOT)),
    }, ensure_ascii=False))
    return 0


def self_test() -> int:
    archive_dates = {"existing": "2026-08-20T10:00:00+03:00"}
    previous_feed_dates = {
        "same-day-existing": "2026-08-22T12:03:59+03:00",
        "existing": "2026-08-21T11:11:11+03:00",
    }
    assert resolve_first_published_at(
        "existing",
        {"published_at": "2026-08-22T09:28:15+03:00"},
        archive_dates,
        previous_feed_dates,
    ) == "2026-08-20T10:00:00+03:00"
    assert resolve_first_published_at(
        "same-day-existing",
        {},
        archive_dates,
        previous_feed_dates,
    ) == "2026-08-22T12:03:59+03:00"
    assert resolve_first_published_at(
        "new-story",
        {"published_at": "2026-08-22T17:07:00+03:00"},
        archive_dates,
        previous_feed_dates,
    ) == "2026-08-22T17:07:00+03:00"
    assert resolve_first_published_at("missing", {}, archive_dates, previous_feed_dates) == ""

    exact = {
        "public_url": "https://example.test/exact.jpg",
        "provenance_status": "VERIFIED",
        "synthetic": False,
    }
    contextual = {
        "public_url": "https://example.test/context.jpg",
        "provenance_status": "VERIFIED",
        "synthetic": False,
        "contextual_archive": True,
        "editorial_note": "Foto de context; nu surprinde evenimentul descris.",
    }
    assert resolve_story_visual({"visual": contextual}, {"image": exact})["public_url"].endswith("exact.jpg")
    assert resolve_story_visual({"visual": contextual}, {})["public_url"].endswith("context.jpg")
    assert verified_visual({**contextual, "editorial_note": ""}) is None
    assert verified_visual({**exact, "synthetic": True}) is None
    assert verified_visual({"public_url": "https://example.test/no-proof.jpg"}) is None
    print("VÂLCEA CLAR live-feed publication + persisted-timestamp + verified-media handoff self-test: PASS")
    return 0


def main() -> int:
    pointer = load(POINTER)
    if pointer.get("status") not in PUBLISHABLE or pointer.get("publication_intent") != "publish":
        raise SystemExit("Refusing live feed: no publishable compatibility snapshot")
    snapshot = load(ROOT / pointer["json_source"])
    if snapshot.get("edition_id") != pointer.get("edition_id"):
        raise SystemExit("Refusing live feed: compatibility snapshot pointer mismatch")
    ensure_story_runtime()
    places = load(PLACES).get("places", [])
    stories = story_feed(snapshot)
    venue_feed = [
        {
            "id": p.get("id"),
            "slug": p.get("slug"),
            "name": p.get("name"),
            "type": p.get("type"),
            "city": (p.get("location") or {}).get("city"),
            "summary": (p.get("editorial") or {}).get("dek") or (p.get("offer") or {}).get("summary"),
            "badges": p.get("badges", [])[:2],
            "media": p.get("media") if (p.get("media") or {}).get("hero", {}).get("subject_match") == "verified" else None,
        }
        for p in places
    ]
    payload = {
        "schema_version": "2.3",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "canonical_domain": "valceaclar.ro",
        "publication_model": "continuous_story_first",
        "stories": stories,
        "story_count": len(stories),
        "edition": snapshot,
        "pointer": pointer,
        "compatibility_snapshot": snapshot,
        "compatibility_pointer": pointer,
        "unde_iesim": venue_feed,
        "unde_iesim_count": len(venue_feed),
        "policy": {
            "verified_facts_only": True,
            "candidate_records_hidden": True,
            "paid_llm_api_required": False,
            "refresh_strategy": "event_first_with_polling_fallback",
            "individual_story_is_publication_unit": True,
            "edition_windows_are_publication_gates": False,
            "canonical_story_urls_required": True,
            "story_body_is_source_preserving": True,
            "recap_render_may_not_remove_story_routes": True,
            "edition_fields_are_compatibility_only": True,
            "unde_iesim_full_verified_catalogue": True,
            "first_publication_timestamp_source": "archive_then_last_persisted_feed_then_reconciled_story_manifest",
            "story_visual_source": "verified_story_manifest_then_existing_snapshot_visual",
            "contextual_visual_disclosure_required": True,
            "synthetic_story_media_allowed": False,
        },
    }
    write(OUT, payload)
    print(json.dumps({
        "status": "PASS",
        "publication_model": payload["publication_model"],
        "stories": len(stories),
        "stories_with_verified_visual": sum(1 for row in stories if row.get("visual")),
        "venues": len(venue_feed),
        "compatibility_snapshot": snapshot["edition_id"],
        "feed": str(OUT.relative_to(ROOT)),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    if "--refresh-media-only" in sys.argv:
        raise SystemExit(refresh_media_only())
    raise SystemExit(main())
