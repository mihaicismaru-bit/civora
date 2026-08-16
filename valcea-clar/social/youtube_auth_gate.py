#!/usr/bin/env python3
"""Fail-closed OAuth linkage gate for the VÂLCEA CLAR YouTube channel.

This module verifies the configured Google OAuth refresh-token contract and the
remote YouTube channel identity without uploading or mutating any video. It is
intentionally separate from editorial materialization: YouTube remains
outbox-only until the project has the required YouTube API audit for public
uploads and a READY real-video product exists.

No credential value or access token is persisted or printed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
STATE = VC / "social" / "youtube_access_state.json"
EVENT = VC / "site" / "story_publication_event.json"
TOKEN_URL = "https://oauth2.googleapis.com/token"
TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
YOUTUBE_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"

CLIENT_ID_ENV = "VALCEA_YOUTUBE_CLIENT_ID"
CLIENT_SECRET_ENV = "VALCEA_YOUTUBE_CLIENT_SECRET"
REFRESH_TOKEN_ENV = "VALCEA_YOUTUBE_REFRESH_TOKEN"
EXPECTED_CHANNEL_ID = "UCjGW2t53es-yQy2U4oFd20w"
EXPECTED_CHANNEL_TITLE = "VÂLCEA CLAR"
REQUIRED_SCOPES = {
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.upload",
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def request_json(
    request: urllib.request.Request,
    *,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
    timeout: int = 45,
) -> dict[str, Any]:
    try:
        with request_fn(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        # Error bodies from these endpoints do not need to be persisted. Keep a
        # bounded diagnostic while never including request bodies/credentials.
        raise RuntimeError(f"YouTube OAuth/API HTTP {exc.code}: {detail[:500]}") from exc
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise RuntimeError("YouTube OAuth/API returned non-object JSON")
    return payload


def credential_values() -> tuple[str, str, str]:
    return (
        os.getenv(CLIENT_ID_ENV, "").strip(),
        os.getenv(CLIENT_SECRET_ENV, "").strip(),
        os.getenv(REFRESH_TOKEN_ENV, "").strip(),
    )


def credential_check() -> dict[str, Any]:
    client_id, client_secret, refresh_token = credential_values()
    present = {
        CLIENT_ID_ENV: bool(client_id),
        CLIENT_SECRET_ENV: bool(client_secret),
        REFRESH_TOKEN_ENV: bool(refresh_token),
    }
    missing = [name for name, ok in present.items() if not ok]
    result = {
        "status": "PASS" if not missing else "BLOCKED_MISSING_CREDENTIALS",
        "platform": "youtube",
        "credential_contract": "oauth2_refresh_token_three_secret_refs",
        "credential_presence": present,
        "missing": missing,
        "credentials_logged": False,
        "network_calls": False,
        "remote_mutation_performed": False,
    }
    if missing:
        raise RuntimeError("missing required YouTube OAuth GitHub secrets: " + ", ".join(missing))
    return result


def refresh_access_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    *,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> tuple[str, dict[str, Any]]:
    body = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode("utf-8")
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "ValceaClar-YouTubeAuthGate/1.0"},
        method="POST",
    )
    payload = request_json(request, request_fn=request_fn)
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("Google OAuth refresh returned no access token")
    metadata = {
        "token_type": str(payload.get("token_type") or ""),
        "expires_in": int(payload.get("expires_in") or 0),
        "access_token_persisted": False,
    }
    return token, metadata


def token_scopes(
    access_token: str,
    *,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> set[str]:
    query = urllib.parse.urlencode({"access_token": access_token})
    request = urllib.request.Request(
        f"{TOKENINFO_URL}?{query}",
        headers={"User-Agent": "ValceaClar-YouTubeAuthGate/1.0"},
        method="GET",
    )
    payload = request_json(request, request_fn=request_fn)
    scopes = {value for value in str(payload.get("scope") or "").split() if value}
    missing = sorted(REQUIRED_SCOPES - scopes)
    if missing:
        raise RuntimeError("authorized YouTube token is missing required scopes: " + ", ".join(missing))
    return scopes


def read_authorized_channel(
    access_token: str,
    *,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, str]:
    query = urllib.parse.urlencode({"part": "id,snippet", "mine": "true"})
    request = urllib.request.Request(
        f"{YOUTUBE_CHANNELS_URL}?{query}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "ValceaClar-YouTubeAuthGate/1.0",
        },
        method="GET",
    )
    payload = request_json(request, request_fn=request_fn)
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    if len(items) != 1 or not isinstance(items[0], dict):
        raise RuntimeError(f"expected exactly one authorized YouTube channel, got {len(items)}")
    channel = items[0]
    snippet = channel.get("snippet") if isinstance(channel.get("snippet"), dict) else {}
    identity = {
        "channel_id": str(channel.get("id") or "").strip(),
        "title": str(snippet.get("title") or "").strip(),
        "custom_url": str(snippet.get("customUrl") or "").strip(),
    }
    if identity["channel_id"] != EXPECTED_CHANNEL_ID:
        raise RuntimeError(
            f"authorized YouTube channel id mismatch: expected {EXPECTED_CHANNEL_ID}, got {identity['channel_id'] or '<missing>'}"
        )
    if identity["title"].casefold() != EXPECTED_CHANNEL_TITLE.casefold():
        raise RuntimeError(
            f"authorized YouTube channel title mismatch: expected {EXPECTED_CHANNEL_TITLE!r}, got {identity['title']!r}"
        )
    return identity


def event_fingerprint() -> str | None:
    event = load(EVENT, {})
    value = str(event.get("fingerprint") or "").strip()
    return value or None


def verify_remote(*, persist: bool = False, request_fn: Callable[..., Any] = urllib.request.urlopen) -> dict[str, Any]:
    credential_check()
    client_id, client_secret, refresh_token = credential_values()
    access_token, refresh_meta = refresh_access_token(
        client_id, client_secret, refresh_token, request_fn=request_fn
    )
    scopes = token_scopes(access_token, request_fn=request_fn)
    identity = read_authorized_channel(access_token, request_fn=request_fn)
    checked_at = utc_now()
    result = {
        "status": "VERIFIED_REMOTE",
        "platform": "youtube",
        "credential_contract": "oauth2_refresh_token_three_secret_refs",
        "credential_references": [CLIENT_ID_ENV, CLIENT_SECRET_ENV, REFRESH_TOKEN_ENV],
        "credential_presence_verified": True,
        "oauth_refresh_verified": True,
        "network_identity_verified": True,
        "verified_channel_id": identity["channel_id"],
        "verified_channel_title": identity["title"],
        "verified_custom_url": identity["custom_url"],
        "verified_scopes": sorted(REQUIRED_SCOPES),
        "verified_at": checked_at,
        "oauth_metadata": refresh_meta,
        "direct_publication_enabled": False,
        "direct_publication_blocker": "youtube_api_project_audit_required_for_public_upload",
        "public_upload_api_audit_verified": False,
        "historical_backlog_replay_forbidden": True,
        "credential_link_activation_baseline_event_fingerprint": event_fingerprint(),
        "access_token_persisted": False,
        "refresh_token_persisted": False,
        "remote_mutation_performed": False,
    }
    if persist:
        state = load(STATE, {"schema_version": "1.0", "platform": "youtube"})
        state.update(result)
        state["schema_version"] = "1.1"
        state["execution_owner"] = "civora_site_engine"
        state["publication_model"] = "continuous_story_first"
        write(STATE, state)
    return result


def preview() -> dict[str, Any]:
    state = load(STATE, {"schema_version": "1.0", "platform": "youtube"})
    return {
        "status": "PREVIEW_ONLY",
        "platform": "youtube",
        "expected_channel_id": EXPECTED_CHANNEL_ID,
        "expected_channel_title": EXPECTED_CHANNEL_TITLE,
        "required_scopes": sorted(REQUIRED_SCOPES),
        "credential_contract": "oauth2_refresh_token_three_secret_refs",
        "state_exists": STATE.is_file(),
        "state_remote_verified": state.get("network_identity_verified") is True,
        "direct_publication_enabled": False,
        "direct_publication_blocker": "youtube_api_project_audit_required_for_public_upload",
        "network_calls": False,
        "remote_mutation_performed": False,
    }


def self_test() -> int:
    assert EXPECTED_CHANNEL_ID.startswith("UC") and len(EXPECTED_CHANNEL_ID) > 20
    assert EXPECTED_CHANNEL_TITLE == "VÂLCEA CLAR"
    assert REQUIRED_SCOPES == {
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/youtube.upload",
    }
    sample = load(Path("/definitely/missing"), {"platform": "youtube"})
    assert sample == {"platform": "youtube"}
    result = preview()
    assert result["network_calls"] is False
    assert result["remote_mutation_performed"] is False
    assert result["direct_publication_enabled"] is False
    print("VÂLCEA CLAR YouTube OAuth linkage gate self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--credential-check", action="store_true")
    parser.add_argument("--verify-remote", action="store_true")
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.credential_check:
        print(json.dumps(credential_check(), ensure_ascii=False, indent=2))
        return 0
    if args.verify_remote:
        print(json.dumps(verify_remote(persist=args.persist), ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(preview(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
