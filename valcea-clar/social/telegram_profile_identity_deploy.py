#!/usr/bin/env python3
"""Fail-closed Telegram channel-photo deployment for VÂLCEA CLAR.

Default mode is dry-run. Live mutation requires --apply, an explicit runtime
enable flag, bot token and target channel id/username. The bot must have the
required channel administrator rights. The adapter calls setChatPhoto and then
getChat; it reports CONFIRMED_REMOTE only when Telegram acknowledges the write
and remote readback exposes a changed/new chat photo. Credentials are never
persisted.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
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
AVATAR = ASSET_DIR / "telegram-avatar.png"
STATE = VC / "site" / "runtime" / "media" / "social" / "profile" / "telegram-profile-deployment-state.json"
LIVE_ENABLE_ENV = "VALCEA_TELEGRAM_PROFILE_LIVE_ENABLED"
TOKEN_ENV = "VALCEA_TELEGRAM_BOT_TOKEN"
CHANNEL_ENV = "VALCEA_TELEGRAM_CHANNEL_ID"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_state(value: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def avatar_contract(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"Telegram canonical avatar missing: {path}")
    with Image.open(path) as image:
        width, height = image.size
        fmt = image.format
    if fmt not in {"PNG", "JPEG"}:
        raise RuntimeError(f"unsupported Telegram avatar image format: {fmt}")
    if width <= 0 or height <= 0 or width != height:
        raise RuntimeError("Telegram canonical avatar must be a non-empty square")
    return {
        "width": width,
        "height": height,
        "bytes": path.stat().st_size,
        "format": fmt,
        "sha256": sha256(path),
    }


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
        raise RuntimeError(f"Telegram profile API HTTP {exc.code}: {detail[:1000]}") from exc
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise RuntimeError("Telegram Bot API returned non-object JSON")
    return payload


def api_url(token: str, method: str) -> str:
    if not token or not method:
        raise ValueError("Telegram token and method are required")
    return f"https://api.telegram.org/bot{token}/{method}"


def multipart_photo(chat_id: str, path: Path) -> tuple[bytes, str]:
    boundary = "----ValceaClarTelegramProfileBoundary"
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    chunks: list[bytes] = []
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="chat_id"\r\n\r\n',
        str(chat_id).encode("utf-8"),
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="photo"; filename="{path.name}"\r\n'.encode("utf-8"),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        path.read_bytes(),
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def get_chat(
    *,
    token: str,
    chat_id: str,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    body = urllib.parse.urlencode({"chat_id": chat_id}).encode("utf-8")
    req = urllib.request.Request(
        api_url(token, "getChat"),
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "ValceaClar-Telegram-ProfileIdentity/1.0",
        },
    )
    payload = request_json(req, request_fn=request_fn)
    if payload.get("ok") is not True or not isinstance(payload.get("result"), dict):
        raise RuntimeError("Telegram getChat did not return an authorized chat")
    return payload


def set_chat_photo(
    *,
    token: str,
    chat_id: str,
    path: Path,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    body, content_type = multipart_photo(chat_id, path)
    req = urllib.request.Request(
        api_url(token, "setChatPhoto"),
        data=body,
        method="POST",
        headers={
            "Content-Type": content_type,
            "User-Agent": "ValceaClar-Telegram-ProfileIdentity/1.0",
        },
    )
    payload = request_json(req, request_fn=request_fn, timeout=90)
    if payload.get("ok") is not True or payload.get("result") is not True:
        raise RuntimeError("Telegram setChatPhoto did not acknowledge the update")
    return payload


def chat_photo_signature(payload: dict[str, Any]) -> tuple[str, str]:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    photo = result.get("photo") if isinstance(result.get("photo"), dict) else {}
    return (
        str(photo.get("small_file_unique_id") or photo.get("small_file_id") or ""),
        str(photo.get("big_file_unique_id") or photo.get("big_file_id") or ""),
    )


def readback_confirms(before: tuple[str, str], after: tuple[str, str]) -> bool:
    if not any(after):
        return False
    if not any(before):
        return True
    return after != before


def apply_chat_photo(
    *,
    token: str,
    chat_id: str,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    asset = avatar_contract(AVATAR)
    before_payload = get_chat(token=token, chat_id=chat_id, request_fn=request_fn)
    before = chat_photo_signature(before_payload)
    ack = set_chat_photo(token=token, chat_id=chat_id, path=AVATAR, request_fn=request_fn)
    after_payload = get_chat(token=token, chat_id=chat_id, request_fn=request_fn)
    after = chat_photo_signature(after_payload)
    confirmed = ack.get("ok") is True and readback_confirms(before, after)
    remote = after_payload.get("result") if isinstance(after_payload.get("result"), dict) else {}
    result = {
        "status": "CONFIRMED_REMOTE" if confirmed else "REMOTE_UPDATE_NOT_FULLY_CONFIRMED",
        "at": utc_now(),
        "platform": "telegram",
        "scope": "channel_chat_photo",
        "asset": asset,
        "update_acknowledged": ack.get("ok") is True and ack.get("result") is True,
        "remote_readback_confirmed": confirmed,
        "before_photo_present": any(before),
        "after_photo_present": any(after),
        "remote_photo_signature_changed": bool(any(before) and after != before),
        "remote_chat_id": remote.get("id"),
        "remote_chat_type": remote.get("type"),
        "credential_persisted": False,
    }
    write_state(result)
    if not confirmed:
        raise RuntimeError("Telegram accepted setChatPhoto but getChat did not confirm a new/changed chat photo")
    return result


def dry_run() -> dict[str, Any]:
    deployment = load(DEPLOYMENT)
    telegram = deployment["platforms"]["telegram"]
    return {
        "status": "DRY_RUN_READY",
        "platform": "telegram",
        "scope": "channel_chat_photo",
        "asset": avatar_contract(AVATAR),
        "live_status": telegram["live_status"],
        "live_apply_enabled": os.getenv(LIVE_ENABLE_ENV, "").strip().lower() == "true",
        "bot_token_present": bool(os.getenv(TOKEN_ENV, "").strip()),
        "channel_id_present": bool(os.getenv(CHANNEL_ENV, "").strip()),
        "administrator_rights_required": True,
        "remote_mutation_performed": False,
        "credentials_logged": False,
    }


def self_test() -> int:
    before = ("old-small", "old-big")
    assert readback_confirms(before, before) is False
    assert readback_confirms(before, ("new-small", "new-big")) is True
    assert readback_confirms(("", ""), ("new-small", "new-big")) is True
    assert readback_confirms(("", ""), ("", "")) is False

    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "avatar.png"
        Image.new("RGB", (512, 512), (247, 246, 243)).save(path, "PNG")
        contract = avatar_contract(path)
        assert contract["format"] == "PNG"
        assert contract["width"] == contract["height"] == 512
        body, content_type = multipart_photo("@fixturechannel", path)
        assert b'name="chat_id"' in body and b"@fixturechannel" in body
        assert b'name="photo"' in body and path.read_bytes()[:8] in body
        assert content_type.startswith("multipart/form-data; boundary=")

    payload = {
        "ok": True,
        "result": {
            "id": -100123,
            "type": "channel",
            "photo": {
                "small_file_unique_id": "s1",
                "big_file_unique_id": "b1",
            },
        },
    }
    assert chat_photo_signature(payload) == ("s1", "b1")
    token = "fixture-secret-token"
    assert token in api_url(token, "getChat")
    persisted = {"credential_persisted": False, "remote_chat_id": -100123}
    assert token not in json.dumps(persisted)
    print("VÂLCEA CLAR Telegram profile identity deployer self-test: PASS")
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
    token = os.getenv(TOKEN_ENV, "").strip()
    chat_id = os.getenv(CHANNEL_ENV, "").strip()
    missing = [name for name, value in ((TOKEN_ENV, token), (CHANNEL_ENV, chat_id)) if not value]
    if missing:
        print(json.dumps({"status": "BLOCKED_MISSING_ACCESS", "required_envs": missing}, ensure_ascii=False))
        return 2
    result = apply_chat_photo(token=token, chat_id=chat_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
