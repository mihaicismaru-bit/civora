#!/usr/bin/env python3
"""Build channel-native social packages from live newsroom stories.

Individual stories are the unit of distribution. Morning/evening recap items are
never allowed to become the trigger, queue item or canonical social product. A
story that is publishable on the site but lacks an approved story-specific
photograph is kept in HOLD_MEDIA for visual channels; the site publication is
not delayed. Rights-cleared archival/context photographs are allowed only when
they match the story subject and carry an explicit disclosure that is propagated
into every visual-channel caption.

TikTok additionally has its own platform-native editorial/media gate. An image
that is acceptable as disclosed context on Facebook/Instagram does not become
current TikTok media automatically.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
SCRIPTS = VC / "scripts"
SOCIAL = VC / "social"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SOCIAL))
from newsroom_decide import story_ready  # noqa: E402
import tiktok_editorial_v1 as tiktok_editorial  # noqa: E402

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


def visual_disclosure(visual: dict | None) -> str:
    if not isinstance(visual, dict):
        return ""
    image = visual.get("image")
    if not isinstance(image, dict):
        return ""
    note = str(image.get("editorial_note") or "").strip()
    if image.get("contextual_archive") is True and not note:
        raise RuntimeError("contextual archival visual requires editorial_note disclosure")
    return note


def facebook_copy(story: dict, visual: dict | None = None) -> str:
    section = str(story.get("section") or "ȘTIRI").replace("_", " ")
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    parts = [
        f"{section} | VÂLCEA CLAR",
        headline,
        dek,
    ]
    disclosure = visual_disclosure(visual)
    if disclosure:
        parts.append(disclosure)
    parts.extend([
        "Detaliile și sursele verificate sunt în articol.",
        "#ValceaClar #Valcea #RamnicuValcea #StiriValcea",
    ])
    return "\n\n".join(parts)


def instagram_copy(story: dict, visual: dict | None = None) -> str:
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    section = str(story.get("section") or "ȘTIRI").replace("_", " ")
    parts = [
        section,
        headline,
        dek,
    ]
    disclosure = visual_disclosure(visual)
    if disclosure:
        parts.append(disclosure)
    parts.extend([
        "Contextul complet și sursele: valceaclar.ro",
        "#ValceaClar #Valcea #RamnicuValcea #StiriLocale",
    ])
    return "\n\n".join(parts)


def tiktok_copy(product: dict, visual: dict | None = None) -> tuple[str, str]:
    """Reader-facing TikTok copy from the native editorial product.

    No generic hashtag block. The platform product already encodes the verified
    hook and storyboard; copy only carries the strongest verified fact, useful
    context and canonical source boundary.
    """
    hook = str(product.get("hook") or "").strip()
    title = hook[:90]
    parts: list[str] = []
    storyboard = product.get("storyboard") if isinstance(product.get("storyboard"), list) else []
    for purpose in ("verified_fact", "context", "document_fact", "attribution_boundary"):
        for beat in storyboard:
            if not isinstance(beat, dict) or beat.get("purpose") != purpose:
                continue
            text = " ".join(str(beat.get("on_screen") or "").split())
            if text and text not in parts:
                parts.append(text)
            break
    disclosure = visual_disclosure(visual)
    if disclosure:
        parts.append(disclosure)
    parts.append("Documente și context: valceaclar.ro")
    return title, "\n\n".join(parts)


def find_visual(story: dict, visual_registry: dict) -> dict | None:
    explicit = visual_registry.get("stories", {}).get(str(story.get("id")))
    if isinstance(explicit, dict):
        return explicit
    visual = story.get("visual")
    if isinstance(visual, dict) and visual.get("image_path") and isinstance(visual.get("image"), dict):
        return {"image_path": visual["image_path"], "image": visual["image"]}
    return None


def remove_recap_items(outbox: dict) -> list[str]:
    """Remove legacy recap snapshots from the active social queue entirely.

    Historical remote-publication evidence is stored in the independent
    platform state files, so keeping recap copies in the active outbox has no
    audit value and risks accidental evaluation by a platform adapter.
    """
    items = outbox.get("items", [])
    if not isinstance(items, list):
        outbox["items"] = []
        return []
    removed = [
        str(item.get("id"))
        for item in items
        if isinstance(item, dict) and str(item.get("id") or "").startswith("editia-de-")
    ]
    outbox["items"] = [
        item for item in items
        if not (isinstance(item, dict) and str(item.get("id") or "").startswith("editia-de-"))
    ]
    return removed


def tiktok_platform_config(story: dict, visual: dict | None) -> dict:
    product = tiktok_editorial.package(story, visual)
    tt_title, tt_description = tiktok_copy(product, visual)
    common = {
        "status": "hold",
        "mode": "direct_post",
        "title": tt_title,
        "description": tt_description,
        "privacy_level": None,
        "disable_comment": False,
        "consent": {"granted": False, "source": None, "granted_at": None, "actor": None},
        "editorial_product_status": product.get("status"),
        "editorial_rendering_version": product.get("rendering_version"),
        "editorial_product_fingerprint_sha256": product.get("product_fingerprint_sha256"),
        "editorial_native_format": product.get("native_format"),
        "premium_asset_required": product.get("status") == "READY",
        "synthetic_filler_forbidden": True,
        "archive_as_current_forbidden": True,
        "verbatim_cross_platform_reuse_allowed": False,
    }
    if product.get("status") != "READY":
        return {
            **common,
            "reason": str(product.get("hold_reason") or "tiktok_editorial_gate_not_ready"),
        }
    source_path = str(product.get("source_image_path") or "").strip()
    if source_path:
        # Temporary source URL. build_social_media_assets.py replaces this with
        # the canonical premium 1080x1920 composite URL before TikTok can ever
        # become platform-ready.
        common["photo_url"] = f"{BASE}/media/social/{Path(source_path).name}"
    return {
        **common,
        "reason": "site_consent_and_tiktok_app_audit_required",
    }


def story_item(story: dict, visual: dict | None, existing: dict | None) -> dict:
    item = existing if isinstance(existing, dict) else {}
    item_id = f"story-{story['id']}"
    link = canonical_link(story)
    fb = facebook_copy(story, visual)
    ig = instagram_copy(story, visual)
    tt = tiktok_platform_config(story, visual)

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
        item["platforms"] = {
            "facebook": {"status": "ready", "mode": "direct_publish"},
            "instagram": {"status": "ready", "mode": "direct_publish", "caption": ig},
            "tiktok": tt,
        }
    else:
        item["status"] = "hold"
        item["hold_reason"] = "story_specific_approved_photo_required"
        item.pop("image_path", None)
        item.pop("image", None)
        item["platforms"] = {
            "facebook": {"status": "hold", "reason": "story_specific_approved_photo_required"},
            "instagram": {"status": "hold", "reason": "story_specific_approved_photo_required", "caption": ig},
            "tiktok": tt,
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

    removed_recaps = remove_recap_items(outbox)
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
    outbox["policy"]["legacy_recap_outbox_policy"] = "removed_from_active_queue; historical evidence remains in platform state"
    outbox["policy"]["site_story_may_publish_before_social_media_ready"] = True
    outbox["policy"]["archival_context_requires_explicit_disclosure"] = True
    outbox["policy"]["tiktok_archival_context_never_counts_as_current_media"] = True
    outbox["policy"]["tiktok_ready_photo_requires_premium_editorial_composite"] = True
    write(OUTBOX, outbox)

    result = {
        "status": "PASS",
        "publication_model": "continuous_story_first",
        "stories_seen": len(stories),
        "story_items": created_or_updated,
        "ready_now": ready,
        "held_for_story_specific_media": held,
        "removed_recap_items": removed_recaps,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
