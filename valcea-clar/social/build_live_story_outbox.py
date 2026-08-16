#!/usr/bin/env python3
"""Build channel-native social packages from live newsroom stories.

Individual stories are the unit of distribution. Morning/evening recap items are
never allowed to become the trigger or canonical social product. A story that
is publishable on the site but lacks an approved story-specific photograph is
kept in HOLD_MEDIA for visual channels; the site publication is not delayed.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
SCRIPTS = VC / "scripts"
sys.path.insert(0, str(SCRIPTS))
from newsroom_decide import story_ready  # noqa: E402

CURRENT = VC / "site" / "current_edition.json"
DECISION = VC / "site" / "newsroom_decision.json"
OUTBOX = VC / "social" / "facebook_outbox.json"
VISUALS = VC / "social" / "story_visuals.json"
BASE = "https://valceaclar.ro"


def load(path: Path, default=None):
    if not path.exists():
        if default is not None:
            return default
        raise RuntimeError(f"missing required file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} must contain an object")
    return value


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slug(story_id: str) -> str:
    value = re.sub(r"[^a-z0-9-]+", "-", story_id.lower())
    return re.sub(r"-+", "-", value).strip("-") or "story"


def canonical_link(story: dict) -> str:
    return f"{BASE}/stiri/{slug(str(story['id']))}/"


def facebook_copy(story: dict) -> str:
    section = str(story.get("section") or "ȘTIRI").replace("_", " ")
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    return "\n\n".join([
        f"{section} | VÂLCEA CLAR",
        headline,
        dek,
        "Detaliile și sursele verificate sunt în articol.",
        "#ValceaClar #Valcea #RamnicuValcea #StiriValcea",
    ])


def instagram_copy(story: dict) -> str:
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    section = str(story.get("section") or "ȘTIRI").replace("_", " ")
    return "\n\n".join([
        section,
        headline,
        dek,
        "Contextul complet și sursele: valceaclar.ro",
        "#ValceaClar #Valcea #RamnicuValcea #StiriLocale",
    ])


def tiktok_copy(story: dict) -> tuple[str, str]:
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    title = headline[:90]
    description = "\n\n".join([
        headline,
        dek,
        "Detalii și surse pe valceaclar.ro.",
        "#ValceaClar #Valcea #StiriValcea",
    ])
    return title, description


def find_visual(story: dict, visual_registry: dict) -> dict | None:
    explicit = visual_registry.get("stories", {}).get(str(story.get("id")))
    if isinstance(explicit, dict):
        return explicit
    visual = story.get("visual")
    if isinstance(visual, dict) and visual.get("image_path") and isinstance(visual.get("image"), dict):
        return {"image_path": visual["image_path"], "image": visual["image"]}
    return None


def disable_recap_items(outbox: dict) -> list[str]:
    """Permanently remove recap snapshots from active social evaluation.

    Historic remote publication state lives in platform state files, so the
    outbox item itself can always be disabled. This applies to READY, HOLD and
    any legacy platform-local status: no adapter may evaluate an `editia-de-*`
    item after the story-first migration.
    """
    disabled: list[str] = []
    for item in outbox.get("items", []):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "")
        if not item_id.startswith("editia-de-"):
            continue

        if item.get("status") != "disabled" or item.get("disabled_reason") != "recap_is_not_story_distribution_unit":
            disabled.append(item_id)
        item["status"] = "disabled"
        item["disabled_reason"] = "recap_is_not_story_distribution_unit"
        item["publication_model"] = "legacy_recap_retired"

        platforms = item.get("platforms")
        if isinstance(platforms, dict):
            for package in platforms.values():
                if not isinstance(package, dict):
                    continue
                package["status"] = "disabled"
                package["reason"] = "recap_is_not_story_distribution_unit"
                package["edition_gate"] = False
    return disabled


def story_item(story: dict, visual: dict | None, existing: dict | None) -> dict:
    item = existing if isinstance(existing, dict) else {}
    item_id = f"story-{story['id']}"
    link = canonical_link(story)
    fb = facebook_copy(story)
    ig = instagram_copy(story)
    tt_title, tt_description = tiktok_copy(story)

    item.update({
        "id": item_id,
        "source_story_id": story["id"],
        "generation_mode": "continuous_story_first_social_v1",
        "message": fb,
        "link": link,
        "replace_post_ids": item.get("replace_post_ids", []),
    })

    if visual:
        item["status"] = "ready"
        item["image_path"] = visual["image_path"]
        item["image"] = visual["image"]
        item.pop("hold_reason", None)
        filename = Path(str(visual["image_path"])).name
        item["platforms"] = {
            "facebook": {"status": "ready", "mode": "direct_publish"},
            "instagram": {"status": "ready", "mode": "direct_publish", "caption": ig},
            "tiktok": {
                "status": "hold",
                "mode": "direct_post",
                "reason": "site_consent_and_tiktok_app_audit_required",
                "title": tt_title,
                "description": tt_description,
                "photo_url": f"{BASE}/media/social/{filename}",
                "privacy_level": None,
                "disable_comment": False,
                "consent": {"granted": False, "source": None, "granted_at": None, "actor": None},
            },
        }
    else:
        item["status"] = "hold"
        item["hold_reason"] = "story_specific_approved_photo_required"
        item.pop("image_path", None)
        item.pop("image", None)
        item["platforms"] = {
            "facebook": {"status": "hold", "reason": "story_specific_approved_photo_required"},
            "instagram": {"status": "hold", "reason": "story_specific_approved_photo_required", "caption": ig},
            "tiktok": {"status": "hold", "reason": "story_specific_approved_media_and_site_consent_required", "title": tt_title, "description": tt_description},
        }
    return item


def main() -> int:
    pointer = load(CURRENT)
    snapshot = load(VC / str(pointer["json_source"]))
    decision = load(DECISION, {"publishable_story_ids": []})
    outbox = load(OUTBOX, {"schema_version": "4.0", "items": []})
    visuals = load(VISUALS, {"stories": {}})

    allowed = set(decision.get("publishable_story_ids") or [])
    stories = []
    for story in snapshot.get("items", []):
        if story.get("id") not in allowed:
            continue
        if story_ready(story)[0]:
            stories.append(story)

    disabled_recaps = disable_recap_items(outbox)
    existing_by_id = {
        str(item.get("id")): item
        for item in outbox.get("items", [])
        if isinstance(item, dict) and item.get("id")
    }

    created_or_updated = []
    ready = []
    held = []
    for story in stories:
        item_id = f"story-{story['id']}"
        visual = find_visual(story, visuals)
        item = story_item(story, visual, existing_by_id.get(item_id))
        if item_id not in existing_by_id:
            outbox.setdefault("items", []).append(item)
            existing_by_id[item_id] = item
        created_or_updated.append(item_id)
        (ready if item.get("status") == "ready" else held).append(item_id)

    outbox.setdefault("policy", {})["publication_model"] = "continuous_story_first"
    outbox["policy"]["edition_recaps_are_social_publication_gates"] = False
    outbox["policy"]["edition_recaps_are_social_queue_items"] = False
    outbox["policy"]["site_story_may_publish_before_social_media_ready"] = True
    write(OUTBOX, outbox)

    result = {
        "status": "PASS",
        "publication_model": "continuous_story_first",
        "stories_seen": len(stories),
        "story_items": created_or_updated,
        "ready_now": ready,
        "held_for_story_specific_media": held,
        "disabled_recap_items": disabled_recaps,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
