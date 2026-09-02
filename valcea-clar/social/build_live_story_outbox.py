#!/usr/bin/env python3
"""Build channel-native social packages from live newsroom stories.

Individual stories are the unit of distribution. Morning/evening recap items are
never allowed to become the trigger, queue item or canonical social product. A
story that is publishable on the site but lacks an approved story-specific
photograph is kept in HOLD_MEDIA for visual channels; the canonical Facebook
writer may subsequently use its deterministic text+link fallback for *new*
stories. Rights-cleared archival/context photographs are allowed only when they
match the story subject and carry an explicit disclosure that is propagated into
every visual-channel caption.

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
import generate_edition  # noqa: E402
import tiktok_editorial_v1 as tiktok_editorial  # noqa: E402
from social_common import is_socially_held, remove_socially_held_items  # noqa: E402

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


def clean_text(value: object) -> str:
    return " ".join(str(value or "").split())


def facebook_copy_is_canonical(message: str) -> bool:
    """Reject the old RSS-like/category-prefixed Facebook caption shape."""
    blocks = [block.strip() for block in str(message or "").split("\n\n") if block.strip()]
    if not blocks:
        return False
    first = clean_text(blocks[0]).casefold()
    if first.endswith("| vâlcea clar"):
        return False
    return True


def facebook_copy(story: dict, visual: dict | None = None) -> str:
    """Build Facebook-native link copy from the canonical story kernel.

    The link preview already carries the article headline. For text+link fallback
    posts, lead with the useful local consequence/context (normally the dek)
    instead of duplicating the card title or prepending a mechanical section
    label. This follows the persisted Facebook rule: consequence first, then
    context and canonical link.
    """
    headline = clean_text(story.get("headline"))
    dek = clean_text(story.get("dek"))
    paragraphs = [clean_text(value) for value in story.get("paragraphs", []) if clean_text(value)]

    lead = dek if dek and dek.casefold() != headline.casefold() else headline
    parts: list[str] = [lead] if lead else []
    if paragraphs:
        first = paragraphs[0]
        seen = {value.casefold() for value in (headline, dek, lead) if value}
        if first.casefold() not in seen:
            parts.append(first)

    disclosure = visual_disclosure(visual)
    if disclosure:
        parts.append(disclosure)
    if story.get("brief_kind") == "primary_source_notice":
        parts.append("Informare din sursă primară: publicăm numai ceea ce este confirmat în acest stadiu și păstrăm linkul către sursa oficială.")
    parts.append("Detalii, context și surse verificate în articol.")

    message = "\n\n".join(part for part in parts if part)
    if not facebook_copy_is_canonical(message):
        raise RuntimeError("facebook copy violates platform-native editorial canon")
    return message


def instagram_copy(story: dict, visual: dict | None = None) -> str:
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    section = str(story.get("section") or "ȘTIRI").replace("_", " ")
    parts = [section, headline, dek]
    disclosure = visual_disclosure(visual)
    if disclosure:
        parts.append(disclosure)
    if story.get("brief_kind") == "primary_source_notice":
        parts.append("Informare din sursă primară; detaliile suplimentare rămân în verificare.")
    parts.extend([
        "Contextul complet și sursele: valceaclar.ro",
        "#ValceaClar #Valcea #RamnicuValcea #StiriLocale",
    ])
    return "\n\n".join(part for part in parts if part)


def tiktok_copy(product: dict, visual: dict | None = None) -> tuple[str, str]:
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
    items = outbox.get("items", [])
    if not isinstance(items, list):
        outbox["items"] = []
        return []
    removed = [
        str(item.get("id")) for item in items
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
        return {**common, "reason": str(product.get("hold_reason") or "tiktok_editorial_gate_not_ready")}
    source_path = str(product.get("source_image_path") or "").strip()
    if source_path:
        common["photo_url"] = f"{BASE}/media/social/{Path(source_path).name}"
    return {**common, "reason": "site_consent_and_tiktok_app_audit_required"}


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
        "canonical_headline": clean_text(story.get("headline")),
        "link": link,
        "replace_post_ids": item.get("replace_post_ids", []),
        **({"brief_kind": story.get("brief_kind"), "auto_scope": story.get("auto_scope")} if story.get("auto_generated") else {}),
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
            "facebook": {
                "status": "hold",
                "reason": "story_specific_approved_photo_required",
                "text_link_fallback_allowed_for_new_story": True,
            },
            "instagram": {"status": "hold", "reason": "story_specific_approved_photo_required", "caption": ig},
            "tiktok": tt,
        }
    return item


def decision_approved_full_stories(decision: dict, snapshot: dict) -> list[dict]:
    """Rehydrate all newsroom-approved stories, including ephemeral auto briefs.

    FACT_KERNEL_COMPOSED stories are normally restored from the canonical Writer
    registry. Automatic primary-source briefs are generated inside the live run;
    an older transaction did not persist ``auto_facts.json`` on the publish
    branch, so they may exist in the public edition snapshot and decision while
    being absent from the registry on a later social run. The edition snapshot
    already contains the exact canonical copy that passed ``story_ready``. Use
    that compact public projection as a safe fallback only for decision-approved
    IDs missing from the full registry.
    """
    allowed_order = [str(value) for value in decision.get("publishable_story_ids") or [] if str(value)]
    compact_by_id = {
        str(item.get("id") or ""): item
        for item in snapshot.get("items", [])
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    if allowed_order:
        registry, _ = generate_edition.merged_registry()
        full_by_id = {
            str(item.get("id") or ""): item
            for item in registry.get("facts") or []
            if isinstance(item, dict) and str(item.get("id") or "")
        }
        stories: list[dict] = []
        for story_id in allowed_order:
            full = full_by_id.get(story_id)
            if full is not None and story_ready(full)[0]:
                stories.append(full)
                continue
            compact = compact_by_id.get(story_id)
            if compact is not None and story_ready(compact)[0]:
                stories.append(compact)
        return stories

    return [
        story for story in snapshot.get("items", [])
        if isinstance(story, dict) and story_ready(story)[0]
    ]


def main() -> int:
    pointer = load(CURRENT)
    snapshot = load(VC / str(pointer["json_source"]))
    decision = load(DECISION, {"publishable_story_ids": []})
    outbox = load(OUTBOX, {"schema_version": "4.0", "items": []})
    visuals = load(VISUALS, {"stories": {}})

    stories = [
        story for story in decision_approved_full_stories(decision, snapshot)
        if not is_socially_held(str(story.get("id") or ""))
    ]

    removed_recaps = remove_recap_items(outbox)
    removed_holds = remove_socially_held_items(outbox)
    existing_by_id = {
        str(item.get("id")): item for item in outbox.get("items", [])
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

    policy = outbox.setdefault("policy", {})
    policy["publication_model"] = "continuous_story_first"
    policy["edition_recaps_are_social_publication_gates"] = False
    policy["edition_recaps_are_social_queue_items"] = False
    policy["legacy_recap_outbox_policy"] = "removed_from_active_queue; historical evidence remains in platform state"
    policy["site_story_may_publish_before_social_media_ready"] = True
    policy["archival_context_requires_explicit_disclosure"] = True
    policy["tiktok_archival_context_never_counts_as_current_media"] = True
    policy["tiktok_ready_photo_requires_premium_editorial_composite"] = True
    policy["facebook_missing_photo_is_soft_block_for_new_story"] = True
    policy["facebook_link_copy_rule"] = "local_consequence_first_no_category_prefix_no_generic_hashtag_block"
    policy["facebook_link_preview_requires_exact_story_og_metadata"] = True
    write(OUTBOX, outbox)

    result = {
        "status": "PASS",
        "publication_model": "continuous_story_first",
        "stories_seen": len(stories),
        "story_items": created_or_updated,
        "ready_now": ready,
        "held_for_story_specific_media": held,
        "removed_recap_items": removed_recaps,
        "removed_publication_holds": removed_holds,
        "decision_snapshot_fallback_enabled": True,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
