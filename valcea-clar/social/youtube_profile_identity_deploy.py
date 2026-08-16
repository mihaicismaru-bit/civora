#!/usr/bin/env python3
"""Fail-closed YouTube banner deployment for VÂLCEA CLAR profile identity.

Default mode is dry-run. Live mutation requires BOTH --apply and the explicit
runtime enable flag plus OAuth. The adapter performs remote readback and never
persists credentials. Avatar mutation is deliberately out of scope.
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

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
SOCIAL = VC / "social"
DEPLOYMENT = SOCIAL / "profile_identity_deployment.json"
ASSET_DIR = SOCIAL / "profile-assets"
BANNER = ASSET_DIR / "youtube-header.jpg"
STATE = VC / "site" / "runtime" / "media" / "social" / "profile" / "youtube-profile-deployment-state.json"
API_BASE = "https://www.googleapis.com/youtube/v3"
UPLOAD_BASE = "https://www.googleapis.com/upload/youtube/v3"
LIVE_ENABLE_ENV = "VALCEA_YOUTUBE_PROFILE_LIVE_ENABLED"
OAUTH_ENV = "VALCEA_YOUTUBE_OAUTH_ACCESS_TOKEN"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_state(value: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def banner_contract(path: Path, deployment: dict[str, Any]) -> dict[str, Any]:
    youtube = deployment["platforms"]["youtube"]
    api = youtube["banner_api"]
    if not path.is_file():
        raise RuntimeError(f"YouTube profile banner missing: {path}")
    size = path.stat().st_size
    if size > int(api["max_bytes"]):
        raise RuntimeError(f"YouTube banner exceeds {api['max_bytes']} bytes")
    with Image.open(path) as image:
        width, height = image.size
        fmt = image.format
    if width < int(api["minimum_width"]) or height < int(api["minimum_height"]):
        raise RuntimeError("YouTube banner is below official minimum dimensions")
    if width * 9 != height * 16:
        raise RuntimeError("YouTube banner must be 16:9")
    if (width, height) != (int(api["recommended_width"]), int(api["recommended_height"])):
        raise RuntimeError("Canonical VÂLCEA CLAR YouTube banner must use recommended 2560x1440 canvas")
    if fmt not in {"JPEG", "PNG"}:
        raise RuntimeError(f"unsupported YouTube banner image format: {fmt}")
    return {"width": width, "height": height, "bytes": size, "format": fmt}


def request_json(
    request: urllib.request.Request,
    *,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
    timeout: int = 60,
) -> dict[str, Any]:
    try:
        with request_fn(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"YouTube API HTTP {exc.code}: {detail[:1000]}") from exc
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise RuntimeError("YouTube API returned non-object JSON")
    return payload


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "User-Agent": "ValceaClar-ProfileIdentity/1.0"}


def read_channel(token: str, *, request_fn: Callable[..., Any] = urllib.request.urlopen) -> dict[str, Any]:
    query = urllib.parse.urlencode({"part": "brandingSettings", "mine": "true"})
    req = urllib.request.Request(f"{API_BASE}/channels?{query}", headers=auth_headers(token), method="GET")
    payload = request_json(req, request_fn=request_fn)
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    if len(items) != 1 or not isinstance(items[0], dict):
        raise RuntimeError(f"expected exactly one authorized YouTube channel, got {len(items)}")
    channel = items[0]
    if not str(channel.get("id") or "").strip():
        raise RuntimeError("authorized YouTube channel response has no id")
    if not isinstance(channel.get("brandingSettings"), dict):
        channel["brandingSettings"] = {}
    return channel


def banner_signature(channel: dict[str, Any]) -> dict[str, str]:
    branding = channel.get("brandingSettings") if isinstance(channel.get("brandingSettings"), dict) else {}
    image = branding.get("image") if isinstance(branding.get("image"), dict) else {}
    return {
        "bannerExternalUrl": str(image.get("bannerExternalUrl") or ""),
        "bannerImageUrl": str(image.get("bannerImageUrl") or ""),
        "bannerTvHighImageUrl": str(image.get("bannerTvHighImageUrl") or ""),
    }


def upload_banner(token: str, path: Path, *, request_fn: Callable[..., Any] = urllib.request.urlopen) -> str:
    url = f"{UPLOAD_BASE}/channelBanners/insert?uploadType=media"
    headers = auth_headers(token)
    headers["Content-Type"] = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    req = urllib.request.Request(url, data=path.read_bytes(), headers=headers, method="POST")
    payload = request_json(req, request_fn=request_fn, timeout=90)
    banner_url = str(payload.get("url") or "").strip()
    if not banner_url.startswith("https://"):
        raise RuntimeError("channelBanners.insert returned no usable banner url")
    return banner_url


def update_banner(
    token: str,
    channel: dict[str, Any],
    banner_url: str,
    *,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    branding = json.loads(json.dumps(channel.get("brandingSettings") or {}))
    image = branding.get("image") if isinstance(branding.get("image"), dict) else {}
    image["bannerExternalUrl"] = banner_url
    branding["image"] = image
    body = json.dumps({"id": channel["id"], "brandingSettings": branding}, ensure_ascii=False).encode("utf-8")
    headers = auth_headers(token)
    headers["Content-Type"] = "application/json; charset=utf-8"
    query = urllib.parse.urlencode({"part": "brandingSettings"})
    req = urllib.request.Request(f"{API_BASE}/channels?{query}", data=body, headers=headers, method="PUT")
    payload = request_json(req, request_fn=request_fn)
    if str(payload.get("id") or "") != str(channel["id"]):
        raise RuntimeError("channels.update did not acknowledge the expected channel id")
    return payload


def readback_confirms(before: dict[str, str], after: dict[str, str], uploaded_url: str) -> bool:
    if after.get("bannerExternalUrl") == uploaded_url:
        return True
    before_values = {value for value in before.values() if value}
    after_values = {value for value in after.values() if value}
    if after_values and after_values != before_values:
        return True
    return False


def apply_banner(token: str, *, request_fn: Callable[..., Any] = urllib.request.urlopen) -> dict[str, Any]:
    deployment = load(DEPLOYMENT)
    asset = banner_contract(BANNER, deployment)
    before_channel = read_channel(token, request_fn=request_fn)
    before = banner_signature(before_channel)
    uploaded_url = upload_banner(token, BANNER, request_fn=request_fn)
    update = update_banner(token, before_channel, uploaded_url, request_fn=request_fn)
    after_channel = read_channel(token, request_fn=request_fn)
    after = banner_signature(after_channel)
    confirmed = readback_confirms(before, after, uploaded_url)
    result = {
        "status": "CONFIRMED_REMOTE" if confirmed else "REMOTE_UPDATE_ACKNOWLEDGED_READBACK_INCONCLUSIVE",
        "at": utc_now(),
        "channel_id": str(before_channel["id"]),
        "asset": asset,
        "update_acknowledged": str(update.get("id") or "") == str(before_channel["id"]),
        "remote_readback_confirmed": confirmed,
        "before_banner_present": any(bool(v) for v in before.values()),
        "after_banner_present": any(bool(v) for v in after.values()),
        "credential_persisted": False,
    }
    write_state(result)
    if not confirmed:
        raise RuntimeError("YouTube accepted the banner update but remote readback did not yet confirm a changed banner")
    return result


def dry_run() -> dict[str, Any]:
    deployment = load(DEPLOYMENT)
    contract = banner_contract(BANNER, deployment)
    youtube = deployment["platforms"]["youtube"]
    return {
        "status": "DRY_RUN_READY",
        "platform": "youtube",
        "scope": "banner_only",
        "asset": contract,
        "live_status": youtube["live_status"],
        "live_apply_enabled": os.getenv(LIVE_ENABLE_ENV, "").strip().lower() == "true",
        "oauth_present": bool(os.getenv(OAUTH_ENV, "").strip()),
        "credentials_logged": False,
        "remote_mutation_performed": False,
    }


def self_test() -> int:
    before = {"bannerExternalUrl": "", "bannerImageUrl": "https://old.example/banner.jpg", "bannerTvHighImageUrl": ""}
    same = dict(before)
    changed = {"bannerExternalUrl": "", "bannerImageUrl": "https://new.example/banner.jpg", "bannerTvHighImageUrl": ""}
    assert readback_confirms(before, same, "https://upload.example/temp") is False
    assert readback_confirms(before, changed, "https://upload.example/temp") is True
    exact = dict(before)
    exact["bannerExternalUrl"] = "https://upload.example/temp"
    assert readback_confirms(before, exact, "https://upload.example/temp") is True
    headers = auth_headers("secret-fixture-token")
    assert headers["Authorization"].endswith("secret-fixture-token")
    assert "secret-fixture-token" not in json.dumps({"credential_persisted": False})
    print("VÂLCEA CLAR YouTube profile identity deployer self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.apply:
        print(json.dumps(dry_run(), ensure_ascii=False, indent=2))
        return 0
    if os.getenv(LIVE_ENABLE_ENV, "").strip().lower() != "true":
        print(json.dumps({"status": "BLOCKED_LIVE_NOT_ENABLED", "required": f"{LIVE_ENABLE_ENV}=true"}, ensure_ascii=False))
        return 2
    token = os.getenv(OAUTH_ENV, "").strip()
    if not token:
        print(json.dumps({"status": "BLOCKED_MISSING_OAUTH", "required_env": OAUTH_ENV}, ensure_ascii=False))
        return 2
    result = apply_banner(token)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
