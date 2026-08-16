#!/usr/bin/env python3
"""Build durable story-first products for VÂLCEA CLAR outbox-only channels.

Outbox-only sister publications consume the same individual verified story
publication identity as the site and active social adapters. They remain native
products with independent state/dedupe and cannot claim network publication
until a verified adapter and credentials exist.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
sys.path.insert(0, str(VC / "scripts"))
from newsroom_decide import story_ready  # noqa: E402
from native_identity import product_identity  # noqa: E402

POINTER = VC / "site" / "current_edition.json"
DECISION = VC / "site" / "newsroom_decision.json"
EVENT = VC / "site" / "story_publication_event.json"
THREADS_OUTBOX = VC / "social" / "threads_outbox.json"
THREADS_STATE = VC / "social" / "threads_state.json"
X_OUTBOX = VC / "social" / "x_outbox.json"
X_STATE = VC / "social" / "x_state.json"
LINKEDIN_OUTBOX = VC / "social" / "linkedin_outbox.json"
LINKEDIN_STATE = VC / "social" / "linkedin_state.json"
TELEGRAM_OUTBOX = VC / "social" / "telegram_outbox.json"
TELEGRAM_STATE = VC / "social" / "telegram_state.json"
WHATSAPP_OUTBOX = VC / "social" / "whatsapp_outbox.json"
WHATSAPP_STATE = VC / "social" / "whatsapp_state.json"
YOUTUBE_OUTBOX = VC / "social" / "youtube_outbox.json"
YOUTUBE_STATE = VC / "social" / "youtube_state.json"
BASE = "https://valceaclar.ro"
IDENTITY_SOURCE = "valcea-clar/social/native_platform_identity_system.json"


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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slug(story_id: str) -> str:
    value = re.sub(r"[^a-z0-9-]+", "-", story_id.lower())
    return re.sub(r"-+", "-", value).strip("-") or "story"


def canonical(story: dict) -> str:
    return f"{BASE}/stiri/{slug(str(story['id']))}/"


def compact(text: str, limit: int = 260) -> str:
    value = " ".join(str(text).split())
    if len(value) <= limit:
        return value
    cut = value[: max(1, limit - 1)].rsplit(" ", 1)[0]
    return (cut or value[: max(1, limit - 1)]).rstrip(" ,.;:") + "…"


def first_money(text: str) -> str | None:
    match = re.search(r"(?<!\d)(\d{1,3}(?:\.\d{3})+(?:,\d+)?)\s+lei\b", text, re.I)
    if not match:
        return None
    raw = match.group(1).replace(".", "").replace(",", ".")
    try:
        number = float(raw)
    except ValueError:
        return None
    if number >= 1_000_000:
        return f"{number / 1_000_000:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " mil. lei"
    return f"{int(round(number)):,}".replace(",", ".") + " lei"


def money_values(text: str) -> list[str]:
    values: list[str] = []
    for match in re.finditer(r"(?<!\d)(\d{1,3}(?:\.\d{3})+(?:,\d+)?)\s+lei\b", text, re.I):
        raw = match.group(1).replace(".", "").replace(",", ".")
        try:
            number = float(raw)
        except ValueError:
            continue
        if number >= 1_000_000:
            shown = f"{number / 1_000_000:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " mil. lei"
        else:
            shown = f"{int(round(number)):,}".replace(",", ".") + " lei"
        if shown not in values:
            values.append(shown)
    return values


def contractor_pair(text: str) -> str | None:
    match = re.search(r"asocierii\s+(.+?)(?:,\s+cu\s+subcontractan|;|\.)", text, re.I)
    if not match:
        return None
    value = " ".join(match.group(1).split())
    value = re.sub(r"\bSRL\b", "", value, flags=re.I)
    value = re.sub(r"\s+[—–-]\s+", " + ", value)
    return re.sub(r"\s+", " ", value).strip(" +") or None


def threads_product(story: dict) -> dict:
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    sequence = [headline, dek]
    if paragraphs:
        sequence.append(paragraphs[0])
    sequence.append(f"Surse și context complet: {canonical(story)}")
    return {
        "id": f"threads-story-{story['id']}",
        "story_id": story["id"],
        "status": "outbox_ready",
        "publication_mode": "durable_outbox_only",
        "native_format": "thread" if len(sequence) > 2 else "text",
        "thread": sequence,
        "canonical_url": canonical(story),
        "source_preserving": True,
        "edition_gate": False,
    }


def x_interest_gate(story: dict) -> tuple[bool, str | None]:
    gate = str(story.get("material_fact_gate") or "").strip()
    if gate in {"PASS_DATE_ONLY", "PASS_TITLE_DATE_ONLY"}:
        return False, "x_interest_gate_thin_title_date_source_only"
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    useful = len(headline) + len(dek) + sum(len(p) for p in paragraphs[:2])
    if useful < 110:
        return False, "x_interest_gate_insufficient_context"
    return True, None


def x_product(story: dict) -> dict:
    """Build a compact, source-forward X product with an independent interest gate.

    X is a live-news wire, not a second Threads account. It leads with the
    verified change/number/utility, puts one concrete idea in each bounded post,
    and ends with one canonical source link. Thin event stubs stay HOLD.
    """
    story_id = str(story["id"])
    headline = str(story.get("headline") or "").strip()
    ok, reason = x_interest_gate(story)
    if not ok:
        return {
            "id": f"x-story-{story_id}",
            "story_id": story_id,
            "status": "hold",
            "publication_mode": "durable_outbox_only",
            "native_format": "text",
            "format_family": "x_hold",
            "hold_reason": reason,
            "posts": [compact(headline)],
            "canonical_url": canonical(story),
            "source_preserving": True,
            "max_post_chars_internal": 260,
            "hashtags_default": False,
            "fake_urgency_forbidden": True,
            "engagement_bait_forbidden": True,
            "verbatim_cross_platform_reuse_allowed": False,
            "quote_post_dependency_forbidden": True,
            "direct_publication_enabled": False,
            "direct_publication_blocker": "x_api_pay_per_use_conflicts_zero_paid_dependency",
            "edition_gate": False,
        }

    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    section = str(story.get("section") or "").upper()
    corpus = " ".join([headline, dek, *paragraphs])
    lower = corpus.lower()
    money = money_values(corpus)
    pair = contractor_pair(corpus)
    correction = story.get("correction") is True
    posts: list[str] = []
    hook_family = "what_changed"

    if correction:
        posts.append(compact(f"Corecție: {headline}"))
        hook_family = "correction"
    elif "luminos" in lower and "zăvoi" in lower and "intrarea este liberă" in lower:
        posts.append("Azi în Zăvoi: intrarea este liberă la Luminos Fest.")
        posts.append("Evenimentul are loc în 15–16 august. Lampioanele plutitoare se rezervă separat, online.")
        hook_family = "local_utility"
    elif "olănești" in lower and money:
        posts.append(f"{money[0]} pentru proiectul de pe Olănești.")
        posts.append("Documentația SMIS 334436 include, în zona Omniasig, un pod nou exclusiv pietonal și ciclist.")
        contract = money[1] if len(money) > 1 else None
        actor = pair or "asocierea câștigătoare"
        detail = f"Contractul principal: {actor}"
        if contract:
            detail += f", {contract} fără TVA"
        detail += ". Nu atribuim lucrările vizibile unei firme fără documente suficiente."
        posts.append(compact(detail))
        hook_family = "key_number"
    elif money and (section == "INVESTIGAȚII" or any(token in lower for token in ("contract", "buget", "finanț", "smis"))):
        posts.append(compact(f"{money[0]}: {headline}"))
        if dek:
            posts.append(compact(dek))
        hook_family = "key_number"
    else:
        posts.append(compact(headline))
        if dek:
            posts.append(compact(dek))
        elif paragraphs:
            posts.append(compact(paragraphs[0]))

    posts = [post for post in posts if post][:3]
    posts.append(compact(f"Documente și context: {canonical(story)}"))

    return {
        "id": f"x-story-{story_id}",
        "story_id": story_id,
        "status": "outbox_ready",
        "publication_mode": "durable_outbox_only",
        "native_format": "thread" if len(posts) > 2 else "text",
        "format_family": "x_live_thread" if len(posts) > 2 else "x_update",
        "hook_family": hook_family,
        "posts": posts,
        "canonical_url": canonical(story),
        "source_preserving": True,
        "max_post_chars_internal": 260,
        "hashtags_default": False,
        "fake_urgency_forbidden": True,
        "engagement_bait_forbidden": True,
        "verbatim_cross_platform_reuse_allowed": False,
        "quote_post_dependency_forbidden": True,
        "direct_publication_enabled": False,
        "direct_publication_blocker": "x_api_pay_per_use_conflicts_zero_paid_dependency",
        "official_api_reference": "https://docs.x.com/x-api/posts/create-post",
        "official_pricing_reference": "https://docs.x.com/x-api/getting-started/pricing",
        "edition_gate": False,
    }


def linkedin_product(story: dict) -> dict:
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    opening = dek or headline
    context = [headline]
    if paragraphs:
        context.append(paragraphs[0])
    return {
        "id": f"linkedin-story-{story['id']}",
        "story_id": story["id"],
        "status": "outbox_ready",
        "publication_mode": "durable_outbox_only",
        "native_format": "text",
        "format_family": "professional_context_post",
        "hook": f"Context local — {opening}",
        "context_blocks": context,
        "canonical_url": canonical(story),
        "source_preserving": True,
        "verbatim_cross_platform_reuse_allowed": False,
        "edition_gate": False,
    }


def telegram_product(story: dict) -> dict:
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    correction = story.get("correction") is True
    topics = {str(value).strip() for value in story.get("topics", []) if str(value).strip()}
    verified_breaking = story.get("lifecycle_stage") == "breaking" and "verified_breaking_updates" in topics
    alert = correction or verified_breaking
    prefix = "Corecție — " if correction else ("Actualizare — " if verified_breaking else "De știut — ")
    support = [value for value in (dek, paragraphs[0] if paragraphs else "") if value]
    return {
        "id": f"telegram-story-{story['id']}",
        "story_id": story["id"],
        "status": "outbox_ready",
        "publication_mode": "durable_outbox_only",
        "native_format": "alert" if alert else "text",
        "format_family": "channel_update",
        "message": [f"{prefix}{headline}", *support[:2]],
        "canonical_url": canonical(story),
        "link_policy": "native_preferred",
        "source_preserving": True,
        "fake_urgency_forbidden": True,
        "verbatim_cross_platform_reuse_allowed": False,
        "edition_gate": False,
    }


def whatsapp_product(story: dict) -> dict:
    """Build the low-noise WhatsApp sister-publication product.

    WhatsApp deliberately does not inherit Telegram alert semantics. A normal
    verified story remains a compact message; only an explicit correction is
    labelled as such. Recipient scope is a future dispatch gate and is never
    inferred here.
    """
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    correction = story.get("correction") is True
    prefix = "Corecție — " if correction else "Vâlcea — "
    support = [value for value in (dek, paragraphs[0] if paragraphs else "") if value]
    return {
        "id": f"whatsapp-story-{story['id']}",
        "story_id": story["id"],
        "status": "outbox_ready",
        "publication_mode": "durable_outbox_only",
        "native_format": "text",
        "format_family": "message_update",
        "message": [f"{prefix}{headline}", *support[:2]],
        "canonical_url": canonical(story),
        "link_policy": "native_preferred",
        "source_preserving": True,
        "fake_urgency_forbidden": True,
        "verbatim_cross_platform_reuse_allowed": False,
        "recipient_scope_required_before_dispatch": True,
        "edition_gate": False,
    }


def youtube_product(story: dict) -> dict:
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    script = [headline, dek, *paragraphs[:2], f"Sursele sunt în articol: {canonical(story)}"]
    return {
        "id": f"youtube-story-{story['id']}",
        "story_id": story["id"],
        "status": "hold_media",
        "publication_mode": "durable_outbox_only",
        "native_format": "short",
        "title": headline[:100],
        "script_blocks": script,
        "canonical_url": canonical(story),
        "hold_reason": "real_story_specific_video_and_verified_upload_access_required",
        "real_video_required": True,
        "synthetic_real_person_media_forbidden": True,
        "edition_gate": False,
    }


def output_specs():
    """Return the deterministic materialization contract for outbox-only channels."""
    return [
        (THREADS_OUTBOX, THREADS_STATE, "threads", threads_product),
        (X_OUTBOX, X_STATE, "x", x_product),
        (LINKEDIN_OUTBOX, LINKEDIN_STATE, "linkedin", linkedin_product),
        (TELEGRAM_OUTBOX, TELEGRAM_STATE, "telegram", telegram_product),
        (WHATSAPP_OUTBOX, WHATSAPP_STATE, "whatsapp", whatsapp_product),
        (YOUTUBE_OUTBOX, YOUTUBE_STATE, "youtube", youtube_product),
    ]


def upsert(doc: dict, products: list[dict]) -> dict:
    existing = {
        str(item.get("id")): item
        for item in doc.get("items", [])
        if isinstance(item, dict) and item.get("id")
    }
    for product in products:
        existing[product["id"]] = product
    doc["items"] = list(existing.values())
    doc["publication_model"] = "continuous_story_first"
    doc["edition_recaps_are_publication_gates"] = False
    return doc


def main() -> int:
    pointer = load(POINTER)
    snapshot = load(VC / str(pointer["json_source"]))
    decision = load(DECISION, {"publishable_story_ids": []})
    event = load(EVENT, {"story_ids": []})
    allowed = set(event.get("story_ids") or decision.get("publishable_story_ids") or [])
    stories = [
        item for item in snapshot.get("items", [])
        if item.get("id") in allowed and story_ready(item)[0]
    ]

    counts = {}
    for outbox_path, state_path, platform, factory in output_specs():
        identity = product_identity(platform)
        products = [factory(story) for story in stories]
        for product in products:
            product["identity"] = identity
        outbox = upsert(
            load(outbox_path, {"schema_version": "1.0", "platform": platform, "items": []}),
            products,
        )
        outbox["identity_source"] = IDENTITY_SOURCE
        outbox["identity_channel_id"] = identity["channel_id"]
        write(outbox_path, outbox)
        state = load(state_path, {
            "schema_version": "1.0",
            "platform": platform,
            "execution_owner": "civora_site_engine",
            "published": {},
            "failures": {},
        })
        state["publication_model"] = "continuous_story_first"
        state["identity_source"] = IDENTITY_SOURCE
        state["identity_channel_id"] = identity["channel_id"]
        write(state_path, state)
        counts[f"{platform}_products"] = len(stories)

    print(json.dumps({
        "status": "PASS",
        "publication_model": "continuous_story_first",
        "identity_source": IDENTITY_SOURCE,
        "story_count": len(stories),
        **counts,
        "x_state": "OUTBOX_ONLY_X_API_PAY_PER_USE_BLOCKED_BY_ZERO_PAID_POLICY",
        "youtube_state": "HOLD_MEDIA_UNTIL_REAL_VIDEO_AND_ACCESS",
        "telegram_state": "OUTBOX_ONLY_UNTIL_VERIFIED_ACCESS",
        "whatsapp_state": "OUTBOX_ONLY_UNTIL_VERIFIED_ACCESS_AND_RECIPIENT_SCOPE_POLICY",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
