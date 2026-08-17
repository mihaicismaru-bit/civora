#!/usr/bin/env python3
"""Fail-closed Facebook text+link fallback for VÂLCEA CLAR.

The premium photo/composite lane remains preferred. This adapter exists so a
fully verified, socially useful story is not silenced on Facebook merely because
no story-specific rights-cleared photograph is available. It publishes only
new canonical story-publication-event stories, only when the newsroom story-ready
gate passes, and only when no approved story visual exists.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
SOCIAL = VC / "social"
SCRIPTS = VC / "scripts"
sys.path.insert(0, str(SOCIAL))
sys.path.insert(0, str(SCRIPTS))

import facebook_publish as legacy  # noqa: E402
import story_social_policy as policy  # noqa: E402
from newsroom_decide import story_ready  # noqa: E402

CURRENT = VC / "site" / "current_edition.json"
EVENT = VC / "site" / "story_publication_event.json"
STATE = SOCIAL / "facebook_state.json"
VISUALS = SOCIAL / "story_visuals.json"
DEFAULT_PAGE_ID = "1234360446430980"
DEFAULT_GRAPH_VERSION = "v26.0"
LIVE_ENABLE_ENV = "VALCEA_FB_TEXT_LIVE_ENABLED"
ADAPTER_VERSION = "facebook-editorial-text-v1.0"


class FacebookTextPublishError(RuntimeError):
    pass


def load(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        if default is not None:
            return default
        raise FacebookTextPublishError(f"missing required file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FacebookTextPublishError(f"{path} must contain an object")
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


def canonical_link(story_id: str, event: dict[str, Any]) -> str:
    urls = event.get("canonical_urls") if isinstance(event.get("canonical_urls"), dict) else {}
    value = str(urls.get(story_id) or "").strip()
    if value.startswith("https://valceaclar.ro/") or value.startswith("https://www.valceaclar.ro/"):
        return value
    slug = "".join(ch.lower() if ch.isalnum() or ch == "-" else "-" for ch in story_id)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return f"https://valceaclar.ro/stiri/{slug.strip('-')}/"


def approved_visual_exists(story_id: str, registry: dict[str, Any]) -> bool:
    visual = (registry.get("stories") or {}).get(story_id) if isinstance(registry.get("stories"), dict) else None
    if not isinstance(visual, dict) or not str(visual.get("image_path") or "").strip():
        return False
    image = visual.get("image") if isinstance(visual.get("image"), dict) else {}
    return (
        image.get("kind") == "photograph"
        and image.get("synthetic") is False
        and image.get("subject_match") is True
        and image.get("editor_approved") is True
    )


def clean_paragraphs(story: dict[str, Any]) -> list[str]:
    return [" ".join(str(value).split()) for value in story.get("paragraphs", []) if str(value).strip()]


def build_text_product(story: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    story_id = str(story["id"])
    section = str(story.get("section") or "ȘTIRI").replace("_", " ").upper()
    headline = " ".join(str(story.get("headline") or "").split())
    dek = " ".join(str(story.get("dek") or "").split())
    paragraphs = clean_paragraphs(story)

    body: list[str] = [f"{section} | VÂLCEA CLAR", headline]
    if dek and dek.lower() != headline.lower():
        body.append(dek)
    if paragraphs:
        first = paragraphs[0]
        if first.lower() not in {headline.lower(), dek.lower()}:
            body.append(first)
    body.append("Contextul complet și sursele verificate sunt în articol.")
    link = canonical_link(story_id, event)
    product = {
        "status": "READY",
        "story_id": story_id,
        "state_key": state_key(story_id),
        "native_format": "text_link",
        "publication_product": ADAPTER_VERSION,
        "message": "\n\n".join(part for part in body if part).strip(),
        "canonical_url": link,
        "visual_used": False,
        "synthetic_media_used": False,
        "source_preserving": True,
        "verbatim_cross_platform_reuse_allowed": False,
    }
    product["product_fingerprint_sha256"] = digest(product)
    return product


def current_event_stories() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pointer = load(CURRENT)
    snapshot = load(VC / str(pointer["json_source"]))
    event = load(EVENT, {"new_story_ids": []})
    wanted = {str(value) for value in event.get("new_story_ids", []) if str(value).strip()}
    stories = [
        row for row in snapshot.get("items", [])
        if isinstance(row, dict) and str(row.get("id") or "") in wanted
    ]
    return stories, event


def plan_products() -> dict[str, Any]:
    stories, event = current_event_stories()
    state = load(STATE, {"schema_version": "3.0", "published": {}})
    published = state.get("published") if isinstance(state.get("published"), dict) else {}
    visuals = load(VISUALS, {"stories": {}})
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
        social_ok, social_reason = policy.social_interest_gate(story)
        if not social_ok:
            holds.append({"story_id": story_id, "reason": social_reason})
            continue
        if approved_visual_exists(story_id, visuals):
            skipped.append({"story_id": story_id, "reason": "approved_visual_available_prefer_composite_lane"})
            continue
        eligible.append(build_text_product(story, event))

    return {
        "status": "DRY_RUN",
        "adapter": ADAPTER_VERSION,
        "eligible": eligible,
        "holds": holds,
        "skipped": skipped,
    }


def token_from_env() -> str:
    token = (
        os.environ.get("VALCEA_META_PAGE_ACCESS_TOKEN", "").strip()
        or os.environ.get("VALCEA_FB_PAGE_ACCESS_TOKEN", "").strip()
    )
    if not token:
        raise FacebookTextPublishError("Meta/Facebook Page access token is missing")
    return token


def graph_text_post(
    *,
    page_id: str,
    token: str,
    version: str,
    product: dict[str, Any],
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> str:
    fields = {
        "message": str(product["message"]),
        "link": str(product["canonical_url"]),
        "published": "true",
        "access_token": token,
    }
    body = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(
        f"https://graph.facebook.com/{version}/{page_id}/feed",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "ValceaClar-Facebook-Text/1.0",
        },
    )
    try:
        with request_fn(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise FacebookTextPublishError(f"Meta Page feed POST HTTP {exc.code}: {detail[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise FacebookTextPublishError(f"Meta Page feed transport error: {exc.reason}") from exc
    if not isinstance(payload, dict):
        raise FacebookTextPublishError("Meta Page feed returned a non-object response")
    post_id = str(payload.get("id") or "").strip()
    if not post_id:
        raise FacebookTextPublishError(f"Meta Page feed returned no post id: {payload}")
    return post_id


def persist_publication(state: dict[str, Any], product: dict[str, Any], post_id: str) -> None:
    published = state.setdefault("published", {})
    if not isinstance(published, dict):
        raise FacebookTextPublishError("facebook_state.published must be an object")
    published[product["state_key"]] = {
        "facebook_post_id": post_id,
        "published_at": utc_now(),
        "link": product["canonical_url"],
        "publication_product": ADAPTER_VERSION,
        "native_format": product["native_format"],
        "visual_used": False,
        "synthetic_media_used": False,
        "product_fingerprint_sha256": product["product_fingerprint_sha256"],
    }
    state["last_text_attempt"] = {
        "at": utc_now(),
        "status": "published",
        "story_id": product["story_id"],
        "state_key": product["state_key"],
    }
    write(STATE, state)


def apply(max_items: int) -> dict[str, Any]:
    preview = plan_products()
    products = preview["eligible"][: max(0, max_items)]
    if not products:
        return {**preview, "status": "NO_ELIGIBLE_POSTS", "published": []}
    if os.environ.get(LIVE_ENABLE_ENV, "").strip().lower() != "true":
        raise FacebookTextPublishError(f"{LIVE_ENABLE_ENV} must be true for --apply")

    supplied = token_from_env()
    page_id = os.environ.get("VALCEA_FB_PAGE_ID", DEFAULT_PAGE_ID).strip() or DEFAULT_PAGE_ID
    version = os.environ.get("VALCEA_FB_GRAPH_VERSION", DEFAULT_GRAPH_VERSION).strip() or DEFAULT_GRAPH_VERSION
    try:
        page_token, identity = legacy.resolve_page_token(page_id, supplied, version)
    except Exception as exc:
        raise FacebookTextPublishError(f"Facebook Page identity/token validation failed: {exc}") from exc

    state = load(STATE, {"schema_version": "3.0", "published": {}})
    completed: list[dict[str, Any]] = []
    for product in products:
        try:
            post_id = graph_text_post(
                page_id=page_id,
                token=page_token,
                version=version,
                product=product,
            )
        except Exception as exc:
            state["last_text_attempt"] = {
                "at": utc_now(),
                "status": "failed",
                "story_id": product["story_id"],
                "state_key": product["state_key"],
                "reason": str(exc)[:1000],
            }
            write(STATE, state)
            raise
        persist_publication(state, product, post_id)
        completed.append({"story_id": product["story_id"], "facebook_post_id": post_id})

    state["last_text_identity"] = {
        "verified_at": utc_now(),
        "page_id": page_id,
        "page_name": identity.get("page_name"),
        "token_source": identity.get("source"),
        "token_value_logged": False,
    }
    write(STATE, state)
    return {**preview, "status": "PUBLISHED", "published": completed}


def self_test() -> int:
    event = {"canonical_urls": {"x": "https://valceaclar.ro/stiri/x/"}}
    story = {
        "id": "x",
        "section": "MOBILITATE",
        "headline": "DN 7: două victime într-un incident rutier",
        "dek": "INFOTRAFIC a consemnat două victime în incidentul rutier din 17 august 2026, la ora 15:45.",
        "paragraphs": ["Sursa oficială a descris și circulație alternativă la momentul informării."],
        "material_fact_gate": "PASS",
    }
    product = build_text_product(story, event)
    assert product["native_format"] == "text_link"
    assert product["visual_used"] is False
    assert product["canonical_url"].endswith("/stiri/x/")

    captured: dict[str, Any] = {}

    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def read(self):
            return b'{"id":"page_fixture-post_fixture"}'

    def fake_open(request, timeout=0):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["body"] = urllib.parse.parse_qs(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    post_id = graph_text_post(
        page_id=DEFAULT_PAGE_ID,
        token="fixture-token-never-logged",
        version=DEFAULT_GRAPH_VERSION,
        product=product,
        request_fn=fake_open,
    )
    assert post_id == "page_fixture-post_fixture"
    assert captured["method"] == "POST"
    assert captured["url"].endswith(f"/{DEFAULT_GRAPH_VERSION}/{DEFAULT_PAGE_ID}/feed")
    assert captured["body"]["link"] == ["https://valceaclar.ro/stiri/x/"]
    assert captured["body"]["access_token"] == ["fixture-token-never-logged"]
    print("VÂLCEA CLAR Facebook text-first fallback self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--max-items", type=int, default=int(os.environ.get("VALCEA_FB_TEXT_MAX_PER_RUN", "1")))
    args = parser.parse_args()
    try:
        if args.self_test:
            return self_test()
        result = apply(args.max_items) if args.apply else plan_products()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except FacebookTextPublishError as exc:
        print(json.dumps({"status": "FAIL", "adapter": ADAPTER_VERSION, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
