#!/usr/bin/env python3
"""Retraction-only cleanup for the superseded Facebook intro bypass.

This file exists temporarily so the workflow that created the non-canonical
introduction post can remove that exact remote side effect. It has no content
creation path. After a successful retraction the workflow and this script are
removed; all Facebook content publication must use the canonical story-first
editorial publisher.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOCIAL = ROOT / "valcea-clar" / "social"
sys.path.insert(0, str(SOCIAL))

import facebook_publish as legacy  # noqa: E402

STATE = SOCIAL / "facebook_intro_photo_state.json"
DEFAULT_GRAPH_VERSION = "v26.0"
LIVE_ENV = "VALCEA_FB_INTRO_PHOTO_LIVE_ENABLED"


class RetractionError(RuntimeError):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load() -> dict[str, Any]:
    if not STATE.is_file():
        raise RetractionError("Facebook intro state is missing")
    value = json.loads(STATE.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RetractionError("Facebook intro state must be an object")
    return value


def write(value: dict[str, Any]) -> None:
    STATE.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def supplied_token() -> str:
    token = (
        os.environ.get("VALCEA_META_PAGE_ACCESS_TOKEN", "").strip()
        or os.environ.get("VALCEA_FB_PAGE_ACCESS_TOKEN", "").strip()
    )
    if not token:
        raise RetractionError("Meta/Facebook token is missing")
    return token


def run(*, apply: bool, token_resolver=legacy.resolve_page_token, delete_fn=legacy.graph_delete) -> dict[str, Any]:
    state = load()
    post_id = str(state.get("facebook_post_id") or state.get("retracted_post_id") or "").strip()
    page_id = str(state.get("page_id") or os.environ.get("VALCEA_FB_PAGE_ID") or "").strip()
    version = os.environ.get("VALCEA_FB_GRAPH_VERSION", DEFAULT_GRAPH_VERSION).strip() or DEFAULT_GRAPH_VERSION
    if not post_id or not page_id:
        raise RetractionError("Facebook intro post/page identity is missing")

    base = {
        "schema_version": "1.1",
        "id": state.get("id") or "facebook-intro-photo-20260819",
        "page_id": page_id,
        "retracted_post_id": post_id,
        "policy_violation_reason": (
            "one-off Facebook publisher bypassed the canonical site-story-first doctrine, "
            "Facebook interest gate, and platform-native editorial product path"
        ),
        "new_content_created": False,
        "credentials_logged": False,
        "credentials_persisted": False,
    }
    if not apply:
        return {**base, "status": "DRY_RUN_RETRACTION"}
    if os.environ.get(LIVE_ENV, "").strip().lower() != "true":
        raise RetractionError(f"{LIVE_ENV} must be true for --apply")

    try:
        page_token, identity = token_resolver(page_id, supplied_token(), version)
    except Exception as exc:
        raise RetractionError(f"Facebook Page identity/token validation failed: {exc}") from exc

    deletion = delete_fn(post_id, page_token, version)
    deleted = str((deletion or {}).get("status") or "") in {"deleted", "already_absent"}
    result = {
        **base,
        "status": "RETRACTED_POLICY_VIOLATION" if deleted else "RETRACTION_FAILED",
        "page_name": identity.get("page_name"),
        "deletion": deletion,
        "retracted_at": now(),
    }
    write(result)
    if not deleted:
        raise RetractionError(f"Meta did not confirm deletion: {deletion}")
    return result


def self_test() -> int:
    original = STATE.read_text(encoding="utf-8") if STATE.is_file() else None
    old_env = dict(os.environ)
    deleted: list[str] = []
    try:
        STATE.write_text(json.dumps({
            "id": "fixture-intro",
            "facebook_post_id": "123_fixture_post",
            "page_id": "123_fixture_page",
        }), encoding="utf-8")
        os.environ["VALCEA_META_PAGE_ACCESS_TOKEN"] = "fixture-token"
        os.environ[LIVE_ENV] = "true"
        result = run(
            apply=True,
            token_resolver=lambda page_id, token, version: (
                "fixture-page-token", {"page_name": "Vâlcea Clar"}
            ),
            delete_fn=lambda object_id, token, version: (
                deleted.append(object_id) or {"status": "deleted", "response": {"success": True}}
            ),
        )
        assert result["status"] == "RETRACTED_POLICY_VIOLATION"
        assert result["new_content_created"] is False
        assert deleted == ["123_fixture_post"]
    finally:
        if original is None:
            STATE.unlink(missing_ok=True)
        else:
            STATE.write_text(original, encoding="utf-8")
        os.environ.clear()
        os.environ.update(old_env)
    print("VÂLCEA CLAR Facebook intro retraction self-test: PASS")
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
    except RetractionError as exc:
        print(json.dumps({
            "status": "FAIL",
            "error": str(exc),
            "new_content_created": False,
            "credentials_logged": False,
            "credentials_persisted": False,
        }, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
