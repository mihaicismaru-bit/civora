#!/usr/bin/env python3
"""Fail-closed Instagram editorial publisher for VÂLCEA CLAR.

The adapter renders a platform-native 4:5 editorial cover or carousel from the
verified story kernel and approved source photograph. Rendered JPEGs are staged
into both the canonical site runtime and deterministic site export. Publishing
waits until every canonical valceaclar.ro media URL is publicly reachable.

No existing legacy story is republished: the adapter reuses the historical
`story-<story_id>` state identity. Live apply additionally requires an explicit
runtime feature flag.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable

import editorial_asset_contract as asset_contract
import instagram_editorial_v1_2 as patch
import instagram_publish as legacy

ig = patch.impl
ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
STATE = VC / "social" / "instagram_state.json"
OUTBOX = VC / "social" / "facebook_outbox.json"
VISUALS = VC / "social" / "story_visuals.json"
SYSTEM = VC / "social" / "instagram_visual_system.json"
RUNTIME = VC / "site" / "runtime" / "media" / "social" / "editorial" / "instagram"
DIST = VC / "dist" / "chatgpt-sites" / "media" / "social" / "editorial" / "instagram"
PUBLIC_BASE = "https://valceaclar.ro/media/social/editorial/instagram/"
DEFAULT_GRAPH_VERSION = "v26.0"
DEFAULT_GRAPH_HOST = "graph.facebook.com"
LIVE_ENABLE_ENV = "VALCEA_IG_EDITORIAL_LIVE_ENABLED"
ADAPTER_VERSION = "instagram-editorial-v1.0"


def load(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        if default is not None:
            return default
        raise RuntimeError(f"missing required file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def state_key(story_id: str) -> str:
    return f"story-{story_id}"


def canonical_link(story_id: str) -> str:
    return f"https://valceaclar.ro/stiri/{story_id}/"


def canonical_story_ready_ids() -> set[str]:
    outbox = load(OUTBOX, {"items": []})
    ready: set[str] = set()
    for item in outbox.get("items", []):
        if not isinstance(item, dict) or item.get("status") != "ready":
            continue
        platforms = item.get("platforms") if isinstance(item.get("platforms"), dict) else {}
        instagram = platforms.get("instagram") if isinstance(platforms.get("instagram"), dict) else {}
        if instagram.get("status") != "ready":
            continue
        story_id = str(item.get("source_story_id") or "").strip()
        if story_id:
            ready.add(story_id)
    return ready


def sha256(path: Path) -> str:
    return asset_contract.sha256(path)


def text_card_asset(
    *,
    story_id: str,
    rendered: Path,
    product_fingerprint: str,
    slide: dict[str, str],
    slide_index: int,
) -> dict[str, Any]:
    asset = {
        "kind": "editorial_text_card",
        "synthetic": False,
        "story_id": story_id,
        "platform": "instagram",
        "renderer": "instagram-editorial-v1.1",
        "slide_index": slide_index,
        "rendered_path": str(rendered.relative_to(ROOT)),
        "public_url": PUBLIC_BASE + rendered.name,
        "sha256": sha256(rendered),
        "product_fingerprint_sha256": product_fingerprint,
        "rights_basis": "original_editorial_layout",
        "source_fact_kernel": "canonical_verified_story",
        "alt_text": " ".join(
            value for value in (
                str(slide.get("kicker") or "").strip(),
                str(slide.get("lead") or "").strip(),
                str(slide.get("body") or "").strip(),
            ) if value
        )[:1000],
    }
    asset["asset_fingerprint_sha256"] = asset_contract.canonical_digest(asset)
    return asset


def validate_text_card(asset: dict[str, Any]) -> None:
    if asset.get("kind") != "editorial_text_card" or asset.get("synthetic") is not False:
        raise ValueError("invalid Instagram editorial text card")
    if asset.get("rights_basis") != "original_editorial_layout":
        raise ValueError("Instagram text card rights basis missing")
    if asset.get("source_fact_kernel") != "canonical_verified_story":
        raise ValueError("Instagram text card fact lineage missing")
    candidate = dict(asset)
    supplied = str(candidate.pop("asset_fingerprint_sha256", ""))
    if supplied != asset_contract.canonical_digest(candidate):
        raise ValueError("Instagram text card fingerprint mismatch")
    rendered = ROOT / str(asset.get("rendered_path") or "")
    if not rendered.is_file() or sha256(rendered) != str(asset.get("sha256") or ""):
        raise ValueError("Instagram text card bytes/fingerprint mismatch")
    url = str(asset.get("public_url") or "")
    if not url.startswith(PUBLIC_BASE):
        raise ValueError("Instagram text card public URL is not canonical")


def mirror(rendered: Path) -> None:
    DIST.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(rendered, DIST / rendered.name)


def caption(story: dict[str, Any], plan: dict[str, Any], visual: dict[str, Any]) -> str:
    parts = [str(plan.get("hook") or "").strip()]
    subline = str(plan.get("subline") or "").strip()
    if subline:
        parts.append(subline)
    dek = str(story.get("dek") or "").strip()
    if dek and dek.lower() not in " ".join(parts).lower():
        parts.append(dek)
    image = visual.get("image") if isinstance(visual.get("image"), dict) else {}
    note = str(image.get("editorial_note") or "").strip()
    if note:
        parts.append(note)
    parts.append("Contextul complet și sursele verificate: valceaclar.ro")
    value = "\n\n".join(part for part in parts if part)
    if legacy.utf16_units(value) > 2200:
        value = legacy.truncate_utf16(value, 2200)
    return value


def render_product(story: dict[str, Any], visual: dict[str, Any], system: dict[str, Any]) -> dict[str, Any]:
    plan = ig.package(story, visual)
    errors = ig.base.validate_plan(plan, system)
    if errors:
        return {"status": "HOLD", "story_id": str(story["id"]), "reason": "instagram_editorial_qa_failed", "qa_errors": errors}

    story_id = str(story["id"])
    fingerprint = str(plan["product_fingerprint_sha256"])
    RUNTIME.mkdir(parents=True, exist_ok=True)
    assets: list[dict[str, Any]] = []

    cover = RUNTIME / f"{story_id}-ig-{fingerprint[:12]}-01.jpg"
    ig.base.render_cover(plan, cover, system)
    mirror(cover)
    cover_asset = asset_contract.build_asset(
        story_id=story_id,
        platform="instagram",
        renderer="instagram-editorial-v1.1",
        rendered_path=cover,
        source_visual=visual,
        product_fingerprint=fingerprint,
        public_url=PUBLIC_BASE + cover.name,
    )
    asset_contract.validate_asset(cover_asset)
    cover_asset["alt_text"] = f"VÂLCEA CLAR: {plan['hook']}. {cover_asset['source_photo']['alt_text']}"[:1000]
    assets.append(cover_asset)

    for index, slide in enumerate(plan.get("detail_slides") or [], start=2):
        rendered = RUNTIME / f"{story_id}-ig-{fingerprint[:12]}-{index:02d}.jpg"
        ig.render_text_slide(slide, index, rendered, system)
        mirror(rendered)
        card = text_card_asset(
            story_id=story_id,
            rendered=rendered,
            product_fingerprint=fingerprint,
            slide=slide,
            slide_index=index,
        )
        validate_text_card(card)
        assets.append(card)

    native_format = str(plan.get("native_format") or "single_photo")
    if native_format == "single_photo" and len(assets) != 1:
        raise ValueError("Instagram single-photo product rendered unexpected asset count")
    if native_format == "carousel" and not 2 <= len(assets) <= 10:
        raise ValueError("Instagram carousel product requires 2..10 rendered assets")

    return {
        "status": "READY",
        "story_id": story_id,
        "state_key": state_key(story_id),
        "template_id": plan["template_id"],
        "native_format": native_format,
        "hook": plan["hook"],
        "caption": caption(story, plan, visual),
        "canonical_url": canonical_link(story_id),
        "product_fingerprint_sha256": fingerprint,
        "assets": assets,
    }


def plan_products() -> dict[str, Any]:
    visuals = load(VISUALS, {"stories": {}})
    system = load(SYSTEM)
    state = load(STATE, {"schema_version": "1.0", "published": {}, "failures": {}})
    published = state.get("published") if isinstance(state.get("published"), dict) else {}
    newsroom_ready = canonical_story_ready_ids()
    products: list[dict[str, Any]] = []
    holds: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for story in ig.base.stories():
        story_id = str(story["id"])
        key = state_key(story_id)
        if key in published:
            skipped.append({"story_id": story_id, "state_key": key, "reason": "already_published"})
            continue
        if story_id not in newsroom_ready:
            holds.append({"story_id": story_id, "reason": "canonical_story_readiness_gate_not_ready"})
            continue
        visual = ig.base.visual_for(story_id, visuals)
        ok, reason = ig.base.approved_for_instagram(story, visual)
        if not ok:
            holds.append({"story_id": story_id, "reason": reason})
            continue
        assert visual is not None
        product = render_product(story, visual, system)
        if product.get("status") != "READY":
            holds.append(product)
            continue
        products.append(product)
    return {
        "status": "DRY_RUN",
        "adapter": ADAPTER_VERSION,
        "eligible": products,
        "holds": holds,
        "skipped": skipped,
    }


def public_urls_ready(product: dict[str, Any], preflight_fn: Callable[[str], None]) -> tuple[bool, str | None]:
    try:
        for asset in product.get("assets", []):
            preflight_fn(str(asset["public_url"]))
    except Exception as exc:
        return False, str(exc)[:600]
    return True, None


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
    assets = product.get("assets") if isinstance(product.get("assets"), list) else []
    if product.get("native_format") == "carousel":
        child_ids: list[str] = []
        for asset in assets:
            child = graph_post_fn(
                host,
                version,
                f"{account_id}/media",
                token,
                {
                    "image_url": str(asset["public_url"]),
                    "is_carousel_item": "true",
                    "alt_text": str(asset.get("alt_text") or product["hook"]),
                },
            )
            child_id = str(child.get("id") or "").strip()
            if not child_id:
                raise RuntimeError(f"Instagram returned no carousel child id: {child}")
            legacy.wait_for_container(
                host, version, child_id, token,
                graph_get_fn=graph_get_fn, sleep_fn=sleep_fn,
            )
            child_ids.append(child_id)
        container = graph_post_fn(
            host,
            version,
            f"{account_id}/media",
            token,
            {
                "media_type": "CAROUSEL",
                "children": ",".join(child_ids),
                "caption": str(product["caption"]),
            },
        )
    else:
        asset = assets[0]
        child_ids = []
        container = graph_post_fn(
            host,
            version,
            f"{account_id}/media",
            token,
            {
                "image_url": str(asset["public_url"]),
                "caption": str(product["caption"]),
                "alt_text": str(asset.get("alt_text") or product["hook"]),
            },
        )
    container_id = str(container.get("id") or "").strip()
    if not container_id:
        raise RuntimeError(f"Instagram returned no container id: {container}")
    status = legacy.wait_for_container(
        host, version, container_id, token,
        graph_get_fn=graph_get_fn, sleep_fn=sleep_fn,
    )
    media_id = legacy._publish_container(
        account_id, token, version, host, container_id, graph_post_fn=graph_post_fn
    )
    return {
        "instagram_media_id": media_id,
        "container_id": container_id,
        "container_status": status,
        "child_container_ids": child_ids,
        "published_at": utc_now(),
        "native_format": product["native_format"],
        "product_fingerprint_sha256": product["product_fingerprint_sha256"],
        "asset_fingerprints": [asset["asset_fingerprint_sha256"] for asset in assets],
        "publication_product": ADAPTER_VERSION,
    }


def persist_wait(state: dict[str, Any], product: dict[str, Any], error: str | None) -> None:
    pending = state.setdefault("pending_public_media", {})
    if not isinstance(pending, dict):
        raise ValueError("instagram_state.pending_public_media must be an object")
    pending[product["state_key"]] = {
        "story_id": product["story_id"],
        "updated_at": utc_now(),
        "product_fingerprint_sha256": product["product_fingerprint_sha256"],
        "public_urls": [asset["public_url"] for asset in product["assets"]],
        "last_preflight_error": error,
    }
    state["last_attempt"] = {
        "at": utc_now(),
        "status": "waiting_public_media",
        "item_id": product["state_key"],
    }
    write(STATE, state)


def persist_publication(state: dict[str, Any], product: dict[str, Any], result: dict[str, Any]) -> None:
    published = state.setdefault("published", {})
    failures = state.setdefault("failures", {})
    pending = state.setdefault("pending_public_media", {})
    if not isinstance(published, dict) or not isinstance(failures, dict) or not isinstance(pending, dict):
        raise ValueError("invalid Instagram state structure")
    published[product["state_key"]] = {
        **result,
        "canonical_url": product["canonical_url"],
        "template_id": product["template_id"],
        "hook": product["hook"],
        "assets": [
            {
                "kind": asset["kind"],
                "sha256": asset["sha256"],
                "asset_fingerprint_sha256": asset["asset_fingerprint_sha256"],
                "public_url": asset["public_url"],
            }
            for asset in product["assets"]
        ],
    }
    failures.pop(product["state_key"], None)
    pending.pop(product["state_key"], None)
    state["last_attempt"] = {
        "at": utc_now(),
        "status": "published",
        "item_id": product["state_key"],
    }
    write(STATE, state)


def _fixture_product(story_id: str) -> dict[str, Any]:
    visuals = load(VISUALS)
    system = load(SYSTEM)
    story = next((row for row in ig.base.stories() if str(row.get("id")) == story_id), None)
    if not isinstance(story, dict):
        raise AssertionError(f"fixture story missing: {story_id}")
    visual = ig.base.visual_for(story_id, visuals)
    if not isinstance(visual, dict):
        raise AssertionError(f"fixture visual missing: {story_id}")
    product = render_product(story, visual, system)
    if product.get("status") != "READY":
        raise AssertionError(f"fixture not READY: {product}")
    return product


def self_test() -> int:
    assert state_key("x") == "story-x"
    assert "olanesti-bridge-monitor" in canonical_story_ready_ids()
    product = _fixture_product("olanesti-bridge-monitor")
    assert product["native_format"] == "carousel"
    assert len(product["assets"]) == 4
    assert product["assets"][0]["kind"] == "editorial_composite"
    assert all(asset["synthetic"] is False for asset in product["assets"])
    assert all(str(asset["public_url"]).startswith(PUBLIC_BASE) for asset in product["assets"])
    assert product["assets"][1]["kind"] == "editorial_text_card"
    assert "Ralunic + Dimex-2000 Company" in json.dumps(product, ensure_ascii=False)
    assert all((DIST / Path(asset["rendered_path"]).name).is_file() for asset in product["assets"])

    # Public-media preflight is fail-closed but not a hard publishing failure.
    ok, reason = public_urls_ready(product, lambda url: (_ for _ in ()).throw(RuntimeError("not deployed yet")))
    assert ok is False and "not deployed yet" in str(reason)
    assert public_urls_ready(product, lambda url: None) == (True, None)

    calls: list[tuple[str, dict[str, str]]] = []
    counter = {"n": 0}

    def fake_post(host, version, path, token, fields):
        calls.append((path, dict(fields)))
        counter["n"] += 1
        if path.endswith("/media_publish"):
            return {"id": "published-media-id"}
        return {"id": f"container-{counter['n']}"}

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
    assert len(result["child_container_ids"]) == 4
    assert any(fields.get("media_type") == "CAROUSEL" for _, fields in calls)
    assert calls[-1][0].endswith("/media_publish")
    print("VÂLCEA CLAR Instagram editorial adapter v1 self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    preview = plan_products()
    if not args.apply:
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0
    if not preview["eligible"]:
        print(json.dumps({**preview, "status": "NO_ELIGIBLE_POSTS"}, ensure_ascii=False, indent=2))
        return 0
    if os.getenv(LIVE_ENABLE_ENV, "").strip().lower() != "true":
        print(json.dumps({**preview, "status": "BLOCKED_EDITORIAL_LIVE_NOT_ENABLED"}, ensure_ascii=False, indent=2))
        return 0

    account_id = os.getenv("VALCEA_IG_ACCOUNT_ID", "").strip()
    token = os.getenv("VALCEA_IG_ACCESS_TOKEN", "").strip()
    version = os.getenv("VALCEA_IG_GRAPH_VERSION", DEFAULT_GRAPH_VERSION).strip() or DEFAULT_GRAPH_VERSION
    host = os.getenv("VALCEA_IG_GRAPH_HOST", DEFAULT_GRAPH_HOST).strip() or DEFAULT_GRAPH_HOST
    if not account_id or not token:
        print(json.dumps({**preview, "status": "BLOCKED_MISSING_CREDENTIALS"}, ensure_ascii=False, indent=2))
        return 0

    state = load(STATE, {"schema_version": "1.0", "published": {}, "failures": {}})
    max_per_run = max(1, int(os.getenv("VALCEA_IG_EDITORIAL_MAX_PER_RUN", "1")))
    results = []
    waiting = []
    for product in preview["eligible"][:max_per_run]:
        ready, error = public_urls_ready(product, legacy.remote_jpeg_preflight)
        if not ready:
            persist_wait(state, product, error)
            waiting.append({
                "story_id": product["story_id"],
                "state_key": product["state_key"],
                "reason": "WAIT_PUBLIC_MEDIA",
                "public_urls": [asset["public_url"] for asset in product["assets"]],
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
            failures[product["state_key"]] = {"failed_at": utc_now(), "error": str(exc)[:1000]}
            state["last_attempt"] = {"at": utc_now(), "status": "failed", "item_id": product["state_key"]}
            write(STATE, state)
            raise
        persist_publication(state, product, result)
        results.append({"story_id": product["story_id"], **result})

    status = "PUBLISHED" if results else "WAIT_PUBLIC_MEDIA" if waiting else "NO_ELIGIBLE_POSTS"
    print(json.dumps({
        "status": status,
        "adapter": ADAPTER_VERSION,
        "results": results,
        "waiting": waiting,
        "holds": preview["holds"],
        "remaining": max(0, len(preview["eligible"]) - len(results) - len(waiting)),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
