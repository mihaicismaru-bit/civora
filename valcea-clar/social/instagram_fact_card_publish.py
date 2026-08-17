#!/usr/bin/env python3
"""Verified fact-card fallback publisher for VÂLCEA CLAR Instagram.

The primary Instagram lane remains the approved real-photo editorial cover /
carousel. This adapter is used only for a newly published canonical story that
passes the newsroom and social-interest gates but has no approved story-specific
photograph. It renders an explicit newsroom text card from the verified fact
kernel; it never depicts the event, person or place synthetically.

Publishing is two phase. The deterministic JPEG is first persisted to `main`.
Instagram then fetches that exact artifact from a raw GitHub transport URL on a
later run. A canonical valceaclar.ro media URL is recorded as the intended public
identity, while the transport URL is explicitly metadata, not editorial source.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
SOCIAL = VC / "social"
SCRIPTS = VC / "scripts"
sys.path.insert(0, str(SOCIAL))
sys.path.insert(0, str(SCRIPTS))

import editorial_asset_contract as asset_contract  # noqa: E402
import feed_identity_v1_1 as feed_identity  # noqa: E402
import instagram_publish as legacy  # noqa: E402
import story_social_policy as social_policy  # noqa: E402
from newsroom_decide import story_ready  # noqa: E402

CURRENT = VC / "site" / "current_edition.json"
EVENT = VC / "site" / "story_publication_event.json"
STATE = SOCIAL / "instagram_state.json"
VISUALS = SOCIAL / "story_visuals.json"
SYSTEM = SOCIAL / "instagram_visual_system.json"
RUNTIME = VC / "site" / "runtime" / "media" / "social" / "editorial" / "instagram-text"
CANONICAL_BASE = "https://valceaclar.ro/media/social/editorial/instagram-text/"
RAW_BASE = (
    "https://raw.githubusercontent.com/mihaicismaru-bit/civora/main/"
    "valcea-clar/site/runtime/media/social/editorial/instagram-text/"
)
DEFAULT_GRAPH_VERSION = "v26.0"
DEFAULT_GRAPH_HOST = "graph.facebook.com"
LIVE_ENABLE_ENV = "VALCEA_IG_TEXT_CARD_LIVE_ENABLED"
ADAPTER_VERSION = "instagram-editorial-fact-card-v1.0"


class InstagramFactCardError(RuntimeError):
    pass


def load(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        if default is not None:
            return default
        raise InstagramFactCardError(f"missing required file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise InstagramFactCardError(f"{path} must contain an object")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def state_key(story_id: str) -> str:
    return f"story-{story_id}"


def event_stories() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pointer = load(CURRENT)
    snapshot = load(VC / str(pointer["json_source"]))
    event = load(EVENT, {"new_story_ids": []})
    wanted = {str(value) for value in event.get("new_story_ids", []) if str(value).strip()}
    stories = [
        row for row in snapshot.get("items", [])
        if isinstance(row, dict) and str(row.get("id") or "") in wanted
    ]
    return stories, event


def canonical_link(story_id: str, event: dict[str, Any]) -> str:
    urls = event.get("canonical_urls") if isinstance(event.get("canonical_urls"), dict) else {}
    value = str(urls.get(story_id) or "").strip()
    if value.startswith("https://valceaclar.ro/") or value.startswith("https://www.valceaclar.ro/"):
        return value
    return f"https://valceaclar.ro/stiri/{story_id}/"


def approved_visual_exists(story_id: str, registry: dict[str, Any]) -> bool:
    stories = registry.get("stories") if isinstance(registry.get("stories"), dict) else {}
    visual = stories.get(story_id) if isinstance(stories, dict) else None
    if not isinstance(visual, dict) or not str(visual.get("image_path") or "").strip():
        return False
    image = visual.get("image") if isinstance(visual.get("image"), dict) else {}
    return (
        image.get("kind") == "photograph"
        and image.get("synthetic") is False
        and image.get("subject_match") is True
        and image.get("editor_approved") is True
        and bool(str(image.get("rights_basis") or "").strip())
    )


def compact(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return (cut or text[: limit - 1]).rstrip(" ,.;:") + "…"


def card_copy(story: dict[str, Any]) -> tuple[str, str]:
    section = str(story.get("section") or "ȘTIRI").replace("_", " ").upper()
    headline = compact(story.get("headline"), 155)
    dek = compact(story.get("dek"), 210)
    paragraphs = [compact(value, 180) for value in story.get("paragraphs", []) if str(value).strip()]
    body_parts = [headline]
    if dek and dek.lower() != headline.lower():
        body_parts.append(dek)
    elif paragraphs:
        body_parts.append(paragraphs[0])
    return section, "  ".join(value for value in body_parts if value)


def build_product(story: dict[str, Any], event: dict[str, Any], system: dict[str, Any]) -> dict[str, Any]:
    story_id = str(story["id"])
    section, body = card_copy(story)
    identity = {
        "story_id": story_id,
        "section": section,
        "body": body,
        "canonical_url": canonical_link(story_id, event),
        "rendering_version": ADAPTER_VERSION,
    }
    fingerprint = digest(identity)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    rendered = RUNTIME / f"{story_id}-ig-text-{fingerprint[:12]}.jpg"
    feed_identity.render_instagram_text_slide(
        {"kicker": section, "body": body},
        1,
        rendered,
        system,
    )
    sha = asset_contract.sha256(rendered)
    canonical_url = CANONICAL_BASE + rendered.name
    delivery_url = RAW_BASE + rendered.name
    asset = {
        "kind": "editorial_text_card",
        "synthetic": False,
        "story_id": story_id,
        "platform": "instagram",
        "renderer": ADAPTER_VERSION,
        "rendered_path": str(rendered.relative_to(ROOT)),
        "canonical_public_url": canonical_url,
        "delivery_url": delivery_url,
        "delivery_transport": "github_raw_main",
        "sha256": sha,
        "product_fingerprint_sha256": fingerprint,
        "rights_basis": "original_editorial_layout",
        "source_fact_kernel": "canonical_verified_story",
        "depicts_real_scene": False,
        "alt_text": compact(f"VÂLCEA CLAR. {section}. {body}", 950),
    }
    asset["asset_fingerprint_sha256"] = asset_contract.canonical_digest(asset)

    headline = compact(story.get("headline"), 260)
    dek = compact(story.get("dek"), 520)
    caption_parts = [headline]
    if dek and dek.lower() != headline.lower():
        caption_parts.append(dek)
    caption_parts.append("Card editorial construit exclusiv din informația verificată; nu este o fotografie a evenimentului.")
    caption_parts.append("Contextul complet și sursele: valceaclar.ro")
    caption = "\n\n".join(part for part in caption_parts if part)
    if legacy.utf16_units(caption) > 2200:
        caption = legacy.truncate_utf16(caption, 2200)

    return {
        "status": "READY",
        "story_id": story_id,
        "state_key": state_key(story_id),
        "template_id": "verified_fact_card",
        "native_format": "single_photo",
        "hook": headline,
        "caption": caption,
        "canonical_url": canonical_link(story_id, event),
        "product_fingerprint_sha256": fingerprint,
        "assets": [asset],
        "visual_policy": "text_card_no_synthetic_depiction",
    }


def plan_products() -> dict[str, Any]:
    stories, event = event_stories()
    state = load(STATE, {"schema_version": "1.0", "published": {}, "failures": {}})
    published = state.get("published") if isinstance(state.get("published"), dict) else {}
    visuals = load(VISUALS, {"stories": {}})
    system = load(SYSTEM)
    eligible: list[dict[str, Any]] = []
    holds: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for story in stories:
        story_id = str(story.get("id") or "")
        key = state_key(story_id)
        if key in published:
            skipped.append({"story_id": story_id, "reason": "already_published"})
            continue
        ready, ready_reason = story_ready(story)
        if not ready:
            holds.append({"story_id": story_id, "reason": f"canonical_story_readiness_gate:{ready_reason}"})
            continue
        social_ok, social_reason = social_policy.social_interest_gate(story)
        if not social_ok:
            holds.append({"story_id": story_id, "reason": social_reason})
            continue
        if approved_visual_exists(story_id, visuals):
            skipped.append({"story_id": story_id, "reason": "approved_visual_available_prefer_photo_composite_lane"})
            continue
        eligible.append(build_product(story, event, system))

    return {
        "status": "DRY_RUN",
        "adapter": ADAPTER_VERSION,
        "eligible": eligible,
        "holds": holds,
        "skipped": skipped,
    }


def remote_jpeg_ready(url: str, request_fn: Callable[..., Any] = urllib.request.urlopen) -> tuple[bool, str | None]:
    try:
        request = urllib.request.Request(url, method="GET", headers={"User-Agent": "ValceaClar-Instagram-FactCard/1.0"})
        with request_fn(request, timeout=25) as response:
            ctype = str(response.headers.get("Content-Type") or "").lower()
            first = response.read(24)
        if "image/jpeg" not in ctype and not first.startswith(b"\xff\xd8\xff"):
            return False, f"not_jpeg:{ctype or 'unknown'}"
        return True, None
    except urllib.error.HTTPError as exc:
        return False, f"HTTP_{exc.code}"
    except urllib.error.URLError as exc:
        return False, f"transport:{exc.reason}"
    except Exception as exc:
        return False, str(exc)[:400]


def publish_product(
    product: dict[str, Any],
    *,
    account_id: str,
    token: str,
    version: str,
    host: str,
    graph_post_fn: Callable[..., dict[str, Any]] = legacy.graph_post,
    graph_get_fn: Callable[..., dict[str, Any]] = legacy.graph_get,
    sleep_fn: Callable[[float], None] = __import__("time").sleep,
) -> dict[str, Any]:
    asset = product["assets"][0]
    container = graph_post_fn(
        host,
        version,
        f"{account_id}/media",
        token,
        {
            "image_url": str(asset["delivery_url"]),
            "caption": str(product["caption"]),
            "alt_text": str(asset["alt_text"]),
        },
    )
    container_id = str(container.get("id") or "").strip()
    if not container_id:
        raise InstagramFactCardError(f"Instagram returned no container id: {container}")
    status = legacy.wait_for_container(
        host,
        version,
        container_id,
        token,
        graph_get_fn=graph_get_fn,
        sleep_fn=sleep_fn,
    )
    media_id = legacy._publish_container(
        account_id,
        token,
        version,
        host,
        container_id,
        graph_post_fn=graph_post_fn,
    )
    return {
        "instagram_media_id": media_id,
        "container_id": container_id,
        "container_status": status,
        "published_at": utc_now(),
        "native_format": "single_photo",
        "product_fingerprint_sha256": product["product_fingerprint_sha256"],
        "asset_fingerprints": [asset["asset_fingerprint_sha256"]],
        "publication_product": ADAPTER_VERSION,
    }


def persist_wait(state: dict[str, Any], product: dict[str, Any], error: str | None) -> None:
    pending = state.setdefault("pending_public_media", {})
    if not isinstance(pending, dict):
        raise InstagramFactCardError("instagram_state.pending_public_media must be an object")
    asset = product["assets"][0]
    pending[product["state_key"]] = {
        "story_id": product["story_id"],
        "updated_at": utc_now(),
        "product_fingerprint_sha256": product["product_fingerprint_sha256"],
        "canonical_public_url": asset["canonical_public_url"],
        "delivery_url": asset["delivery_url"],
        "last_preflight_error": error,
        "publication_product": ADAPTER_VERSION,
    }
    state["last_attempt"] = {
        "at": utc_now(),
        "status": "waiting_public_media",
        "item_id": product["state_key"],
        "publication_product": ADAPTER_VERSION,
    }
    write(STATE, state)


def persist_publication(state: dict[str, Any], product: dict[str, Any], result: dict[str, Any]) -> None:
    published = state.setdefault("published", {})
    failures = state.setdefault("failures", {})
    pending = state.setdefault("pending_public_media", {})
    if not isinstance(published, dict) or not isinstance(failures, dict) or not isinstance(pending, dict):
        raise InstagramFactCardError("invalid Instagram state structure")
    asset = product["assets"][0]
    published[product["state_key"]] = {
        **result,
        "canonical_url": product["canonical_url"],
        "template_id": product["template_id"],
        "hook": product["hook"],
        "visual_policy": product["visual_policy"],
        "asset": {
            "kind": asset["kind"],
            "synthetic": False,
            "depicts_real_scene": False,
            "sha256": asset["sha256"],
            "asset_fingerprint_sha256": asset["asset_fingerprint_sha256"],
            "canonical_public_url": asset["canonical_public_url"],
            "delivery_url": asset["delivery_url"],
        },
    }
    failures.pop(product["state_key"], None)
    pending.pop(product["state_key"], None)
    state["last_attempt"] = {
        "at": utc_now(),
        "status": "published",
        "item_id": product["state_key"],
        "publication_product": ADAPTER_VERSION,
    }
    write(STATE, state)


def apply(max_items: int) -> dict[str, Any]:
    preview = plan_products()
    products = preview["eligible"][: max(0, max_items)]
    if not products:
        return {**preview, "status": "NO_ELIGIBLE_POSTS", "results": [], "waiting": []}
    if os.environ.get(LIVE_ENABLE_ENV, "").strip().lower() != "true":
        raise InstagramFactCardError(f"{LIVE_ENABLE_ENV} must be true for --apply")

    account_id = os.environ.get("VALCEA_IG_ACCOUNT_ID", "").strip()
    token = os.environ.get("VALCEA_IG_ACCESS_TOKEN", "").strip()
    version = os.environ.get("VALCEA_IG_GRAPH_VERSION", DEFAULT_GRAPH_VERSION).strip() or DEFAULT_GRAPH_VERSION
    host = os.environ.get("VALCEA_IG_GRAPH_HOST", DEFAULT_GRAPH_HOST).strip() or DEFAULT_GRAPH_HOST
    if not account_id or not token:
        raise InstagramFactCardError("Instagram account id/access token missing")

    state = load(STATE, {"schema_version": "1.0", "published": {}, "failures": {}})
    results: list[dict[str, Any]] = []
    waiting: list[dict[str, Any]] = []
    for product in products:
        asset = product["assets"][0]
        ready, error = remote_jpeg_ready(str(asset["delivery_url"]))
        if not ready:
            persist_wait(state, product, error)
            waiting.append({
                "story_id": product["story_id"],
                "state_key": product["state_key"],
                "reason": "WAIT_PUBLIC_MEDIA",
                "delivery_url": asset["delivery_url"],
                "preflight_error": error,
            })
            continue
        try:
            result = publish_product(
                product,
                account_id=account_id,
                token=token,
                version=version,
                host=host,
            )
        except Exception as exc:
            failures = state.setdefault("failures", {})
            failures[product["state_key"]] = {
                "failed_at": utc_now(),
                "error": str(exc)[:1000],
                "publication_product": ADAPTER_VERSION,
            }
            state["last_attempt"] = {
                "at": utc_now(),
                "status": "failed",
                "item_id": product["state_key"],
                "publication_product": ADAPTER_VERSION,
            }
            write(STATE, state)
            raise
        persist_publication(state, product, result)
        results.append({"story_id": product["story_id"], **result})

    status = "PUBLISHED" if results else "WAIT_PUBLIC_MEDIA" if waiting else "NO_ELIGIBLE_POSTS"
    return {
        "status": status,
        "adapter": ADAPTER_VERSION,
        "results": results,
        "waiting": waiting,
        "holds": preview["holds"],
        "skipped": preview["skipped"],
    }


def self_test() -> int:
    system = load(SYSTEM)
    event = {"canonical_urls": {"fixture": "https://valceaclar.ro/stiri/fixture/"}}
    story = {
        "id": "fixture",
        "section": "MOBILITATE",
        "headline": "DN 7: două victime într-un incident rutier",
        "dek": "INFOTRAFIC a indicat două victime și circulație alternativă la momentul informării.",
        "paragraphs": ["Materialul păstrează contextul temporal și sursa oficială."],
        "material_fact_gate": "PASS",
    }
    product = build_product(story, event, system)
    asset = product["assets"][0]
    assert product["native_format"] == "single_photo"
    assert product["template_id"] == "verified_fact_card"
    assert asset["kind"] == "editorial_text_card"
    assert asset["synthetic"] is False and asset["depicts_real_scene"] is False
    assert asset["delivery_url"].startswith(RAW_BASE)
    assert (ROOT / asset["rendered_path"]).is_file()
    assert asset_contract.sha256(ROOT / asset["rendered_path"]) == asset["sha256"]

    class Headers:
        def get(self, key, default=None):
            return "image/jpeg" if key.lower() == "content-type" else default

    class FakeResponse:
        headers = Headers()
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
        def read(self, size=-1): return b"\xff\xd8\xfffixture"

    def fake_open(request, timeout=0):
        return FakeResponse()

    assert remote_jpeg_ready(asset["delivery_url"], request_fn=fake_open) == (True, None)

    calls: list[tuple[str, dict[str, str]]] = []
    def fake_post(host, version, path, token, fields):
        calls.append((path, dict(fields)))
        if path.endswith("/media_publish"):
            return {"id": "published-media-id"}
        return {"id": "container-id"}
    def fake_get(host, version, path, token, params=None):
        return {"status_code": "FINISHED"}

    result = publish_product(
        product,
        account_id="17841439178488749",
        token="fixture-token-never-logged",
        version="v26.0",
        host="graph.facebook.com",
        graph_post_fn=fake_post,
        graph_get_fn=fake_get,
        sleep_fn=lambda seconds: None,
    )
    assert result["instagram_media_id"] == "published-media-id"
    assert calls[0][1]["image_url"].startswith(RAW_BASE)
    assert calls[-1][0].endswith("/media_publish")
    print("VÂLCEA CLAR Instagram fact-card fallback self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--max-items", type=int, default=int(os.environ.get("VALCEA_IG_TEXT_CARD_MAX_PER_RUN", "1")))
    args = parser.parse_args()
    try:
        if args.self_test:
            return self_test()
        result = apply(args.max_items) if args.apply else plan_products()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except InstagramFactCardError as exc:
        print(json.dumps({"status": "FAIL", "adapter": ADAPTER_VERSION, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
