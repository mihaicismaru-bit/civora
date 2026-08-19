#!/usr/bin/env python3
"""Publish exactly one canonical VÂLCEA CLAR Facebook introduction post.

The post is deliberately isolated from the normal social backlog. It uses one
provenance-backed real photograph of Râmnicu Vâlcea, creates at most one remote
Facebook post, verifies it by read-back, and only then removes the explicitly
superseded text-only introduction post. Synthetic media and queue fan-out are
forbidden by contract.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
SOCIAL = ROOT / "valcea-clar" / "social"
sys.path.insert(0, str(SOCIAL))

import facebook_publish as legacy  # noqa: E402

POST = SOCIAL / "facebook_intro_photo_post.json"
STATE = SOCIAL / "facebook_intro_photo_state.json"
DEFAULT_GRAPH_VERSION = "v26.0"
LIVE_ENV = "VALCEA_FB_INTRO_PHOTO_LIVE_ENABLED"


class IntroPhotoError(RuntimeError):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.is_file():
        return dict(default or {})
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise IntroPhotoError(f"{path} must contain an object")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate(post: dict[str, Any]) -> None:
    policy = post.get("publication_policy") or {}
    if policy.get("exactly_one_post") is not True or policy.get("no_other_queue_items") is not True:
        raise IntroPhotoError("intro post is not isolated to exactly one publication")
    image = post.get("image") or {}
    if image.get("kind") != "photograph" or image.get("synthetic") is not False:
        raise IntroPhotoError("synthetic or non-photographic media is forbidden")
    if image.get("subject_match") is not True or image.get("editor_approved") is not True:
        raise IntroPhotoError("photo subject/editor approval gate failed")
    if image.get("source_type") != "creative_commons" or image.get("rights_basis") != "creative_commons":
        raise IntroPhotoError("intro photograph must carry explicit reusable rights")
    for key in ("source_url", "direct_source_url", "credit", "license_url", "alt_text", "captured_at"):
        if not str(image.get(key) or "").strip():
            raise IntroPhotoError(f"photo provenance missing: {key}")
    direct = urllib.parse.urlparse(str(image["direct_source_url"]))
    source = urllib.parse.urlparse(str(image["source_url"]))
    if direct.scheme != "https" or direct.hostname != "upload.wikimedia.org":
        raise IntroPhotoError("photo binary must resolve from Wikimedia upload HTTPS")
    if source.scheme != "https" or source.hostname != "commons.wikimedia.org":
        raise IntroPhotoError("photo attribution source must be Wikimedia Commons HTTPS")
    link = urllib.parse.urlparse(str(post.get("link") or ""))
    if link.scheme != "https" or link.hostname not in {"valceaclar.ro", "www.valceaclar.ro"}:
        raise IntroPhotoError("post link must be canonical valceaclar.ro")
    if not str(post.get("message") or "").strip():
        raise IntroPhotoError("post message is missing")


def supplied_token() -> str:
    token = (
        os.environ.get("VALCEA_META_PAGE_ACCESS_TOKEN", "").strip()
        or os.environ.get("VALCEA_FB_PAGE_ACCESS_TOKEN", "").strip()
    )
    if not token:
        raise IntroPhotoError("Meta/Facebook token is missing")
    return token


def graph_form(
    *,
    url: str,
    data: dict[str, str],
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "ValceaClar-IntroPhoto/1.0"},
    )
    try:
        with request_fn(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise IntroPhotoError(f"Meta HTTP {exc.code}: {detail[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise IntroPhotoError(f"Meta transport error: {exc.reason}") from exc
    if not isinstance(payload, dict):
        raise IntroPhotoError("Meta returned a non-object response")
    if payload.get("error"):
        raise IntroPhotoError(f"Meta error: {str(payload['error'])[:1000]}")
    return payload


def graph_read(
    *,
    post_id: str,
    token: str,
    version: str,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    query = urllib.parse.urlencode({
        "fields": "id,message,permalink_url,created_time,full_picture",
        "access_token": token,
    })
    request = urllib.request.Request(
        f"https://graph.facebook.com/{version}/{post_id}?{query}",
        method="GET",
        headers={"User-Agent": "ValceaClar-IntroPhoto/1.0"},
    )
    try:
        with request_fn(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise IntroPhotoError(f"Meta read-back HTTP {exc.code}: {detail[:1000]}") from exc
    if not isinstance(payload, dict) or payload.get("error"):
        raise IntroPhotoError(f"Meta read-back failed: {payload}")
    return payload


def publish_photo(
    *,
    page_id: str,
    token: str,
    version: str,
    post: dict[str, Any],
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> str:
    image = post["image"]
    caption = (
        str(post["message"]).strip()
        + "\n\nFoto: " + str(image["credit"]).strip()
        + " · fotografie realizată la " + str(image["captured_at"]).strip()
    )
    payload = graph_form(
        url=f"https://graph.facebook.com/{version}/{page_id}/photos",
        data={
            "url": str(image["direct_source_url"]),
            "caption": caption,
            "published": "true",
            "alt_text_custom": str(image["alt_text"]),
            "access_token": token,
        },
        request_fn=request_fn,
    )
    post_id = str(payload.get("post_id") or payload.get("id") or "").strip()
    if not post_id:
        raise IntroPhotoError(f"Meta returned no post id: {payload}")
    return post_id


def normalize(value: object) -> str:
    return " ".join(str(value or "").split())


def run(
    *,
    apply: bool,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
    token_resolver=legacy.resolve_page_token,
    delete_fn=legacy.graph_delete,
) -> dict[str, Any]:
    post = load(POST)
    validate(post)
    state = load(STATE, {"schema_version": "1.0", "id": post.get("id")})
    page_id = str(post.get("page_id") or os.environ.get("VALCEA_FB_PAGE_ID") or "").strip()
    version = os.environ.get("VALCEA_FB_GRAPH_VERSION", DEFAULT_GRAPH_VERSION).strip() or DEFAULT_GRAPH_VERSION

    if not apply:
        return {
            "schema_version": "1.0",
            "status": "DRY_RUN",
            "id": post["id"],
            "page_id": page_id,
            "photo_source": post["image"]["source_url"],
            "replaces": post.get("replace_post_ids") or [],
            "exactly_one_post": True,
            "synthetic_media_used": False,
        }
    if os.environ.get(LIVE_ENV, "").strip().lower() != "true":
        raise IntroPhotoError(f"{LIVE_ENV} must be true for --apply")

    supplied = supplied_token()
    try:
        page_token, identity = token_resolver(page_id, supplied, version)
    except Exception as exc:
        raise IntroPhotoError(f"Facebook Page identity/token validation failed: {exc}") from exc

    existing_post_id = str(state.get("facebook_post_id") or "").strip()
    created_this_run = False
    if existing_post_id:
        post_id = existing_post_id
    else:
        post_id = publish_photo(
            page_id=page_id,
            token=page_token,
            version=version,
            post=post,
            request_fn=request_fn,
        )
        created_this_run = True
        # Persist immediately after the remote side effect. A later verification
        # or cleanup failure must never create a duplicate photo post on retry.
        write(STATE, {
            "schema_version": "1.0",
            "id": post["id"],
            "status": "POST_CREATED_VERIFY_PENDING",
            "facebook_post_id": post_id,
            "page_id": page_id,
            "photo_source": post["image"]["source_url"],
            "photo_credit": post["image"]["credit"],
            "created_at": now(),
            "synthetic_media_used": False,
        })

    readback = graph_read(
        post_id=post_id,
        token=page_token,
        version=version,
        request_fn=request_fn,
    )
    expected_start = normalize(post["message"])
    actual = normalize(readback.get("message"))
    message_ok = bool(expected_start) and actual.startswith(expected_start)
    picture_ok = bool(str(readback.get("full_picture") or "").strip())
    if not message_ok or not picture_ok:
        result = {
            "schema_version": "1.0",
            "id": post["id"],
            "status": "VERIFY_FAILED_REPLACEMENT_PRESERVED",
            "facebook_post_id": post_id,
            "page_id": page_id,
            "message_verified": message_ok,
            "picture_verified": picture_ok,
            "permalink_url": readback.get("permalink_url"),
            "replaced_posts_deleted": [],
            "synthetic_media_used": False,
        }
        write(STATE, result)
        return result

    cleanup: dict[str, Any] = {}
    for old_id in post.get("replace_post_ids") or []:
        cleanup[str(old_id)] = delete_fn(str(old_id), page_token, version)

    result = {
        "schema_version": "1.0",
        "id": post["id"],
        "status": "PUBLISHED_AND_VERIFIED",
        "facebook_post_id": post_id,
        "page_id": page_id,
        "page_name": identity.get("page_name"),
        "post_created_this_run": created_this_run,
        "message_verified": True,
        "picture_verified": True,
        "permalink_url": readback.get("permalink_url"),
        "photo_source": post["image"]["source_url"],
        "photo_credit": post["image"]["credit"],
        "photo_captured_at": post["image"]["captured_at"],
        "replacement_cleanup": cleanup,
        "exactly_one_post": True,
        "synthetic_media_used": False,
        "verified_at": now(),
        "credentials_logged": False,
        "credentials_persisted": False,
    }
    write(STATE, result)
    return result


def self_test() -> int:
    post = load(POST)
    validate(post)
    assert post["publication_policy"]["exactly_one_post"] is True
    assert post["image"]["synthetic"] is False
    assert "upload.wikimedia.org" in post["image"]["direct_source_url"]
    assert "VÂLCEA CLAR e despre Vâlcea" in post["message"]

    remote = {"message": "", "picture": "https://example.test/photo.jpg"}
    calls: list[str] = []

    class FakeResponse:
        def __init__(self, payload: dict[str, Any]):
            self.payload = payload
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_open(request, timeout=0):
        calls.append(f"{request.get_method()} {request.full_url}")
        if request.get_method() == "POST" and request.full_url.endswith("/1234360446430980/photos"):
            body = urllib.parse.parse_qs(request.data.decode("utf-8"))
            remote["message"] = body["caption"][0]
            return FakeResponse({"post_id": "1234360446430980_999"})
        if request.get_method() == "GET" and "/1234360446430980_999?" in request.full_url:
            return FakeResponse({
                "id": "1234360446430980_999",
                "message": remote["message"],
                "full_picture": remote["picture"],
                "permalink_url": "https://www.facebook.com/1234360446430980/posts/999",
            })
        raise AssertionError(request.full_url)

    deleted: list[str] = []
    def fake_delete(object_id, token, version):
        deleted.append(object_id)
        return {"status": "deleted", "response": {"success": True}}

    old_env = dict(os.environ)
    original = STATE.read_text(encoding="utf-8") if STATE.is_file() else None
    try:
        if STATE.is_file():
            STATE.unlink()
        os.environ["VALCEA_META_PAGE_ACCESS_TOKEN"] = "fixture-token"
        os.environ[LIVE_ENV] = "true"
        result = run(
            apply=True,
            request_fn=fake_open,
            token_resolver=lambda page_id, token, version: (
                "fixture-page-token",
                {"page_name": "Vâlcea Clar", "source": "fixture"},
            ),
            delete_fn=fake_delete,
        )
        assert result["status"] == "PUBLISHED_AND_VERIFIED"
        assert result["picture_verified"] is True
        assert result["exactly_one_post"] is True
        assert len([call for call in calls if call.startswith("POST ")]) == 1
        assert deleted == list(post.get("replace_post_ids") or [])
    finally:
        if original is None:
            STATE.unlink(missing_ok=True)
        else:
            STATE.write_text(original, encoding="utf-8")
        os.environ.clear()
        os.environ.update(old_env)
    print("VÂLCEA CLAR one-shot Facebook real-photo intro self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            return self_test()
        result = run(apply=args.apply)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") == "PUBLISHED_AND_VERIFIED" or not args.apply else 2
    except IntroPhotoError as exc:
        failure = {
            "schema_version": "1.0",
            "status": "FAIL",
            "error": str(exc),
            "credentials_logged": False,
            "credentials_persisted": False,
        }
        write(STATE, failure)
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
