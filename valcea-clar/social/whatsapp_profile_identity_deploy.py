#!/usr/bin/env python3
"""Fail-closed WhatsApp Business profile-photo deployment for VÂLCEA CLAR.

Default mode is dry-run. Live mutation requires --apply, an explicit runtime
enable flag, Meta app id, WhatsApp phone-number id and access token. The
canonical PNG avatar is converted deterministically to JPEG for Meta's resumable
upload flow. Upload handles and credentials are never persisted. A remote
business-profile readback is mandatory before CONFIRMED_REMOTE is reported.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import tempfile
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
AVATAR = ASSET_DIR / "whatsapp-avatar.png"
STATE = VC / "site" / "runtime" / "media" / "social" / "profile" / "whatsapp-profile-deployment-state.json"
DEFAULT_GRAPH_VERSION = "v26.0"
LIVE_ENABLE_ENV = "VALCEA_WHATSAPP_PROFILE_LIVE_ENABLED"
TOKEN_ENV = "VALCEA_WHATSAPP_ACCESS_TOKEN"
PHONE_ID_ENV = "VALCEA_WHATSAPP_PHONE_NUMBER_ID"
APP_ID_ENV = "VALCEA_META_APP_ID"
GRAPH_VERSION_ENV = "VALCEA_WHATSAPP_GRAPH_VERSION"


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


def source_asset_contract(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"WhatsApp canonical avatar missing: {path}")
    with Image.open(path) as image:
        width, height = image.size
        fmt = image.format
    if fmt != "PNG":
        raise RuntimeError(f"WhatsApp canonical avatar must be PNG, got {fmt}")
    if width <= 0 or height <= 0 or width != height:
        raise RuntimeError("WhatsApp canonical avatar must be a non-empty square")
    return {
        "width": width,
        "height": height,
        "bytes": path.stat().st_size,
        "format": fmt,
        "sha256": sha256(path),
    }


def prepare_upload_jpeg(source: Path, destination: Path) -> dict[str, Any]:
    contract = source_asset_contract(source)
    with Image.open(source) as image:
        rgb = image.convert("RGB")
        rgb.save(
            destination,
            "JPEG",
            quality=94,
            optimize=True,
            progressive=True,
            subsampling=0,
        )
    with Image.open(destination) as converted:
        width, height = converted.size
        fmt = converted.format
    if (width, height) != (contract["width"], contract["height"]) or fmt != "JPEG":
        raise RuntimeError("WhatsApp deterministic JPEG transform changed avatar geometry or format")
    return {
        "width": width,
        "height": height,
        "bytes": destination.stat().st_size,
        "format": fmt,
        "mime_type": "image/jpeg",
        "sha256": sha256(destination),
        "source_sha256": contract["sha256"],
    }


def auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": "ValceaClar-WhatsApp-ProfileIdentity/1.0",
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
        raise RuntimeError(f"WhatsApp profile API HTTP {exc.code}: {detail[:1000]}") from exc
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise RuntimeError("WhatsApp profile API returned non-object JSON")
    return payload


def graph_url(version: str, path: str) -> str:
    version = str(version).strip() or DEFAULT_GRAPH_VERSION
    path = str(path).lstrip("/")
    return f"https://graph.facebook.com/{version}/{path}"


def read_profile(
    *,
    version: str,
    phone_number_id: str,
    token: str,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    query = urllib.parse.urlencode({"fields": "profile_picture_url"})
    req = urllib.request.Request(
        graph_url(version, f"{phone_number_id}/whatsapp_business_profile") + "?" + query,
        headers=auth_headers(token),
        method="GET",
    )
    return request_json(req, request_fn=request_fn)


def extract_profile_picture_url(payload: dict[str, Any]) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), list) else []
    if not data or not isinstance(data[0], dict):
        return ""
    row = data[0]
    direct = str(row.get("profile_picture_url") or "").strip()
    if direct:
        return direct
    business = row.get("business_profile") if isinstance(row.get("business_profile"), dict) else {}
    return str(business.get("profile_picture_url") or "").strip()


def create_upload_session(
    *,
    version: str,
    app_id: str,
    token: str,
    file_length: int,
    mime_type: str,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> str:
    query = urllib.parse.urlencode({"file_length": str(file_length), "file_type": mime_type})
    req = urllib.request.Request(
        graph_url(version, f"{app_id}/uploads") + "?" + query,
        data=b"",
        headers=auth_headers(token),
        method="POST",
    )
    payload = request_json(req, request_fn=request_fn)
    upload_id = str(payload.get("id") or "").strip()
    if not upload_id.startswith("upload:"):
        raise RuntimeError("WhatsApp resumable upload session returned no usable upload id")
    return upload_id


def upload_file_data(
    *,
    version: str,
    upload_id: str,
    token: str,
    jpeg: Path,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> str:
    headers = auth_headers(token)
    headers.update({"Content-Type": "image/jpeg", "file_offset": "0"})
    req = urllib.request.Request(
        graph_url(version, upload_id),
        data=jpeg.read_bytes(),
        headers=headers,
        method="POST",
    )
    payload = request_json(req, request_fn=request_fn, timeout=90)
    handle = str(payload.get("h") or "").strip()
    if not handle:
        raise RuntimeError("WhatsApp resumable upload returned no profile picture handle")
    return handle


def update_profile_picture(
    *,
    version: str,
    phone_number_id: str,
    token: str,
    picture_handle: str,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    body = json.dumps(
        {
            "messaging_product": "whatsapp",
            "profile_picture_handle": picture_handle,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    headers = auth_headers(token)
    headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(
        graph_url(version, f"{phone_number_id}/whatsapp_business_profile"),
        data=body,
        headers=headers,
        method="POST",
    )
    return request_json(req, request_fn=request_fn)


def update_acknowledged(payload: dict[str, Any]) -> bool:
    if payload.get("success") is True:
        return True
    data = payload.get("data")
    if isinstance(data, list) and data:
        return True
    return bool(payload)


def apply_profile_picture(
    *,
    version: str,
    app_id: str,
    phone_number_id: str,
    token: str,
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    source = source_asset_contract(AVATAR)
    before_payload = read_profile(
        version=version,
        phone_number_id=phone_number_id,
        token=token,
        request_fn=request_fn,
    )
    before_url = extract_profile_picture_url(before_payload)
    with tempfile.TemporaryDirectory() as raw:
        jpeg = Path(raw) / "whatsapp-avatar.jpg"
        upload = prepare_upload_jpeg(AVATAR, jpeg)
        upload_id = create_upload_session(
            version=version,
            app_id=app_id,
            token=token,
            file_length=int(upload["bytes"]),
            mime_type="image/jpeg",
            request_fn=request_fn,
        )
        picture_handle = upload_file_data(
            version=version,
            upload_id=upload_id,
            token=token,
            jpeg=jpeg,
            request_fn=request_fn,
        )
        update = update_profile_picture(
            version=version,
            phone_number_id=phone_number_id,
            token=token,
            picture_handle=picture_handle,
            request_fn=request_fn,
        )
    after_payload = read_profile(
        version=version,
        phone_number_id=phone_number_id,
        token=token,
        request_fn=request_fn,
    )
    after_url = extract_profile_picture_url(after_payload)
    ack = update_acknowledged(update)
    readback = bool(after_url)
    result = {
        "status": "CONFIRMED_REMOTE" if ack and readback else "REMOTE_UPDATE_NOT_FULLY_CONFIRMED",
        "at": utc_now(),
        "platform": "whatsapp",
        "scope": "business_profile_picture",
        "graph_version": version,
        "asset": source,
        "upload_transform": upload,
        "update_acknowledged": ack,
        "remote_readback_confirmed": readback,
        "before_profile_picture_present": bool(before_url),
        "after_profile_picture_present": bool(after_url),
        "remote_picture_url_changed": bool(before_url and after_url and before_url != after_url),
        "credential_persisted": False,
        "upload_handle_persisted": False,
    }
    write_state(result)
    if not ack:
        raise RuntimeError("WhatsApp business-profile update was not acknowledged")
    if not readback:
        raise RuntimeError("WhatsApp business-profile readback did not return a profile picture URL")
    return result


def dry_run() -> dict[str, Any]:
    deployment = load(DEPLOYMENT)
    whatsapp = deployment["platforms"]["whatsapp"]
    source = source_asset_contract(AVATAR)
    with tempfile.TemporaryDirectory() as raw:
        upload = prepare_upload_jpeg(AVATAR, Path(raw) / "whatsapp-avatar.jpg")
    return {
        "status": "DRY_RUN_READY",
        "platform": "whatsapp",
        "scope": "business_profile_picture",
        "asset": source,
        "upload_transform": upload,
        "live_status": whatsapp["live_status"],
        "live_apply_enabled": os.getenv(LIVE_ENABLE_ENV, "").strip().lower() == "true",
        "access_token_present": bool(os.getenv(TOKEN_ENV, "").strip()),
        "phone_number_id_present": bool(os.getenv(PHONE_ID_ENV, "").strip()),
        "meta_app_id_present": bool(os.getenv(APP_ID_ENV, "").strip()),
        "graph_version": os.getenv(GRAPH_VERSION_ENV, "").strip() or DEFAULT_GRAPH_VERSION,
        "remote_mutation_performed": False,
        "credentials_logged": False,
    }


def self_test() -> int:
    with tempfile.TemporaryDirectory() as raw:
        source = Path(raw) / "avatar.png"
        target = Path(raw) / "avatar.jpg"
        Image.new("RGBA", (512, 512), (247, 246, 243, 255)).save(source, "PNG")
        transformed = prepare_upload_jpeg(source, target)
        assert transformed["format"] == "JPEG"
        assert transformed["mime_type"] == "image/jpeg"
        assert (transformed["width"], transformed["height"]) == (512, 512)
        assert transformed["source_sha256"] == sha256(source)
        assert transformed["sha256"] == sha256(target)

    assert extract_profile_picture_url({"data": [{"profile_picture_url": "https://pps.example/a.jpg"}]}) == "https://pps.example/a.jpg"
    assert extract_profile_picture_url({"data": [{"business_profile": {"profile_picture_url": "https://pps.example/b.jpg"}}]}) == "https://pps.example/b.jpg"
    assert update_acknowledged({"success": True}) is True
    assert update_acknowledged({"data": [{"id": "profile"}]}) is True
    headers = auth_headers("fixture-secret-token")
    assert headers["Authorization"].endswith("fixture-secret-token")
    persisted = {"credential_persisted": False, "upload_handle_persisted": False}
    assert "fixture-secret-token" not in json.dumps(persisted)
    assert graph_url("v26.0", "123/uploads") == "https://graph.facebook.com/v26.0/123/uploads"
    print("VÂLCEA CLAR WhatsApp profile identity deployer self-test: PASS")
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
    missing = [
        name for name in (TOKEN_ENV, PHONE_ID_ENV, APP_ID_ENV)
        if not os.getenv(name, "").strip()
    ]
    if missing:
        print(json.dumps({"status": "BLOCKED_MISSING_ACCESS", "required_envs": missing}, ensure_ascii=False))
        return 2
    result = apply_profile_picture(
        version=os.getenv(GRAPH_VERSION_ENV, "").strip() or DEFAULT_GRAPH_VERSION,
        app_id=os.getenv(APP_ID_ENV, "").strip(),
        phone_number_id=os.getenv(PHONE_ID_ENV, "").strip(),
        token=os.getenv(TOKEN_ENV, "").strip(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
