#!/usr/bin/env python3
"""Create and pin one canonical VÂLCEA CLAR orientation post on Facebook.

This is intentionally idempotent and narrow. It does not delete, rewrite or
reorder news posts. It creates one text-only newsroom orientation post from the
canonical profile contract and then asks Meta to pin it. A failed pin is
recorded for manual completion without duplicating the post on a retry.
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
VC = ROOT / "valcea-clar"
SOCIAL = VC / "social"
sys.path.insert(0, str(SOCIAL))

import facebook_publish as legacy  # noqa: E402

PROFILE = SOCIAL / "profile_presence_system.json"
STATE = SOCIAL / "facebook_featured_state.json"
DEFAULT_PAGE_ID = "1234360446430980"
DEFAULT_GRAPH_VERSION = "v26.0"
LIVE_ENV = "VALCEA_FB_FEATURED_LIVE_ENABLED"
PRODUCT = "facebook-profile-orientation-v1"


class FeaturedSetupError(RuntimeError):
    pass


def load(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.is_file():
        return dict(default or {})
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FeaturedSetupError(f"{path} must contain an object")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def message_from_contract() -> str:
    profile = load(PROFILE)
    fb = (profile.get("platforms") or {}).get("facebook") or {}
    short_bio = " ".join(str(fb.get("short_bio") or "").split())
    about = " ".join(str(fb.get("about") or "").split())
    if not short_bio or not about:
        raise FeaturedSetupError("canonical Facebook short_bio/about missing")
    return f"VÂLCEA CLAR\n\n{short_bio}\n\n{about}"


def supplied_token() -> str:
    token = (
        os.environ.get("VALCEA_META_PAGE_ACCESS_TOKEN", "").strip()
        or os.environ.get("VALCEA_FB_PAGE_ACCESS_TOKEN", "").strip()
    )
    if not token:
        raise FeaturedSetupError("Meta/Facebook Page access token is missing")
    return token


def graph(
    *,
    url: str,
    data: dict[str, Any] | None = None,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    encoded = None
    method = "GET"
    headers = {"User-Agent": "ValceaClar-Facebook-Featured/1.0"}
    if data is not None:
        encoded = urllib.parse.urlencode(data).encode("utf-8")
        method = "POST"
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=encoded, method=method, headers=headers)
    try:
        with request_fn(request, timeout=35) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise FeaturedSetupError(f"Graph HTTP {exc.code}: {detail[:900]}") from exc
    except urllib.error.URLError as exc:
        raise FeaturedSetupError(f"Graph transport error: {exc.reason}") from exc
    if not isinstance(payload, dict):
        raise FeaturedSetupError("Graph returned a non-object response")
    if payload.get("error"):
        raise FeaturedSetupError(f"Graph error: {str(payload['error'])[:900]}")
    return payload


def create_text_post(*, page_id: str, page_token: str, version: str, message: str, request_fn=urllib.request.urlopen) -> str:
    payload = graph(
        url=f"https://graph.facebook.com/{version}/{page_id}/feed",
        data={"message": message, "published": "true", "access_token": page_token},
        request_fn=request_fn,
    )
    post_id = str(payload.get("id") or "").strip()
    if not post_id:
        raise FeaturedSetupError(f"Meta returned no orientation post id: {payload}")
    return post_id


def set_pinned(*, post_id: str, page_token: str, version: str, request_fn=urllib.request.urlopen) -> tuple[bool, str]:
    try:
        payload = graph(
            url=f"https://graph.facebook.com/{version}/{post_id}",
            data={"is_pinned": "true", "access_token": page_token},
            request_fn=request_fn,
        )
    except Exception as exc:
        return False, str(exc)[:900]
    if payload.get("success") is True or str(payload.get("id") or "") == post_id:
        return True, "accepted"
    return False, f"unexpected_response:{str(payload)[:700]}"


def read_post(*, post_id: str, page_token: str, version: str, request_fn=urllib.request.urlopen) -> dict[str, Any]:
    query = urllib.parse.urlencode({"fields": "id,message,is_pinned,permalink_url", "access_token": page_token})
    return graph(url=f"https://graph.facebook.com/{version}/{post_id}?{query}", request_fn=request_fn)


def run(*, apply: bool, request_fn=urllib.request.urlopen, token_resolver=legacy.resolve_page_token) -> dict[str, Any]:
    desired_message = message_from_contract()
    state = load(STATE, {"schema_version": "1.0", "product": PRODUCT})
    page_id = os.environ.get("VALCEA_FB_PAGE_ID", DEFAULT_PAGE_ID).strip() or DEFAULT_PAGE_ID
    version = os.environ.get("VALCEA_FB_GRAPH_VERSION", DEFAULT_GRAPH_VERSION).strip() or DEFAULT_GRAPH_VERSION

    if not apply:
        return {
            "schema_version": "1.0",
            "product": PRODUCT,
            "status": "DRY_RUN",
            "page_id": page_id,
            "message": desired_message,
            "existing_post_id": state.get("post_id"),
            "credentials_logged": False,
        }
    if os.environ.get(LIVE_ENV, "").strip().lower() != "true":
        raise FeaturedSetupError(f"{LIVE_ENV} must be true for --apply")

    supplied = supplied_token()
    try:
        page_token, identity = token_resolver(page_id, supplied, version)
    except Exception as exc:
        raise FeaturedSetupError(f"Facebook Page identity/token validation failed: {exc}") from exc

    post_id = str(state.get("post_id") or "").strip()
    created = False
    if not post_id:
        post_id = create_text_post(
            page_id=page_id,
            page_token=page_token,
            version=version,
            message=desired_message,
            request_fn=request_fn,
        )
        created = True
        # Persist the remote side effect before attempting the optional pin so a
        # pin error can never cause a duplicate orientation post on retry.
        state.update({
            "schema_version": "1.0",
            "product": PRODUCT,
            "page_id": page_id,
            "post_id": post_id,
            "message": desired_message,
            "created_at": utc_now(),
            "status": "POST_CREATED_PIN_PENDING",
            "credentials_logged": False,
            "credentials_persisted": False,
        })
        write(STATE, state)

    pin_ok, pin_reason = set_pinned(
        post_id=post_id,
        page_token=page_token,
        version=version,
        request_fn=request_fn,
    )
    verification: dict[str, Any] = {}
    try:
        verification = read_post(
            post_id=post_id,
            page_token=page_token,
            version=version,
            request_fn=request_fn,
        )
    except Exception as exc:
        verification = {"readback_error": str(exc)[:900]}

    message_matches = " ".join(str(verification.get("message") or "").split()) == " ".join(desired_message.split()) if verification.get("message") is not None else None
    pinned_readback = verification.get("is_pinned") is True
    status = "PINNED_AND_VERIFIED" if pin_ok and pinned_readback and message_matches is True else (
        "PIN_ACCEPTED_READBACK_LIMITED" if pin_ok and message_matches is not False else "MANUAL_PIN_REQUIRED"
    )
    result = {
        "schema_version": "1.0",
        "product": PRODUCT,
        "status": status,
        "page_id": page_id,
        "page_name": identity.get("page_name"),
        "post_id": post_id,
        "post_created_this_run": created,
        "message": desired_message,
        "pin_accepted": pin_ok,
        "pin_reason": pin_reason,
        "is_pinned_readback": verification.get("is_pinned"),
        "message_readback_matches": message_matches,
        "permalink_url": verification.get("permalink_url"),
        "verified_at": utc_now(),
        "credentials_logged": False,
        "credentials_persisted": False,
    }
    write(STATE, result)
    return result


def self_test() -> int:
    calls: list[tuple[str, str]] = []
    remote = {"post_id": "123_fixture_456", "message": "", "is_pinned": False}

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
        calls.append((request.get_method(), request.full_url))
        if request.get_method() == "POST" and request.full_url.endswith(f"/{DEFAULT_PAGE_ID}/feed"):
            body = urllib.parse.parse_qs(request.data.decode("utf-8"))
            remote["message"] = body["message"][0]
            return FakeResponse({"id": remote["post_id"]})
        if request.get_method() == "POST" and request.full_url.endswith("/123_fixture_456"):
            remote["is_pinned"] = True
            return FakeResponse({"success": True})
        if request.get_method() == "GET" and "/123_fixture_456?" in request.full_url:
            return FakeResponse({
                "id": remote["post_id"],
                "message": remote["message"],
                "is_pinned": remote["is_pinned"],
                "permalink_url": "https://www.facebook.com/123/posts/456",
            })
        raise AssertionError(request.full_url)

    old_env = dict(os.environ)
    original_state = STATE.read_text(encoding="utf-8") if STATE.is_file() else None
    try:
        if STATE.is_file():
            STATE.unlink()
        os.environ["VALCEA_META_PAGE_ACCESS_TOKEN"] = "fixture-identity-token"
        os.environ["VALCEA_FB_PAGE_ID"] = DEFAULT_PAGE_ID
        os.environ[LIVE_ENV] = "true"
        result = run(
            apply=True,
            request_fn=fake_open,
            token_resolver=lambda page_id, token, version: (
                "fixture-page-token",
                {"page_name": "Vâlcea Clar", "source": "fixture"},
            ),
        )
        assert result["status"] == "PINNED_AND_VERIFIED"
        assert result["post_created_this_run"] is True
        assert result["is_pinned_readback"] is True
        second = run(
            apply=True,
            request_fn=fake_open,
            token_resolver=lambda page_id, token, version: (
                "fixture-page-token",
                {"page_name": "Vâlcea Clar", "source": "fixture"},
            ),
        )
        assert second["post_created_this_run"] is False
        assert sum(1 for method, url in calls if method == "POST" and url.endswith(f"/{DEFAULT_PAGE_ID}/feed")) == 1
    finally:
        if original_state is None:
            if STATE.is_file():
                STATE.unlink()
        else:
            STATE.write_text(original_state, encoding="utf-8")
        os.environ.clear()
        os.environ.update(old_env)
    print("VÂLCEA CLAR Facebook featured setup self-test: PASS")
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
        return 0
    except FeaturedSetupError as exc:
        result = {
            "schema_version": "1.0",
            "product": PRODUCT,
            "status": "FAIL",
            "error": str(exc),
            "credentials_logged": False,
            "credentials_persisted": False,
        }
        write(STATE, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
