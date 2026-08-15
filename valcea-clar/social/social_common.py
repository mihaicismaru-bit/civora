#!/usr/bin/env python3
"""Shared fail-closed helpers for VÂLCEA CLAR social publishing adapters."""
from __future__ import annotations

import datetime as dt
import json
import urllib.parse
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOCIAL_ROOT = ROOT / "valcea-clar" / "social"
OUTBOX = SOCIAL_ROOT / "facebook_outbox.json"
PHOTO_ROOT = (SOCIAL_ROOT / "photos" / "approved").resolve()

CANONICAL_HOSTS = {"valceaclar.ro", "www.valceaclar.ro"}
ALLOWED_SOURCE_TYPES = {
    "staff",
    "reader",
    "official_press",
    "official_institution",
    "licensed_agency",
    "public_domain",
    "creative_commons",
}
ALLOWED_RIGHTS = {
    "owned",
    "written_permission",
    "press_use",
    "licensed",
    "public_domain",
    "creative_commons",
    "official_reuse_permission",
}


def utc_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def canonical_link(item: dict[str, Any]) -> str:
    link = str(item.get("link", "")).strip()
    parsed = urllib.parse.urlparse(link)
    if parsed.scheme != "https" or parsed.hostname not in CANONICAL_HOSTS:
        raise ValueError(f"non-canonical link for {item.get('id')}: {link}")
    return link


def photo_metadata(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("image")
    if not isinstance(value, dict):
        raise ValueError(f"social item {item.get('id')} has no image metadata")
    required = ("kind", "source_type", "credit", "rights_basis", "alt_text")
    missing = [key for key in required if not str(value.get(key, "")).strip()]
    if missing:
        raise ValueError(
            f"image metadata missing for {item.get('id')}: {', '.join(missing)}"
        )
    if value.get("kind") != "photograph":
        raise ValueError(f"{item.get('id')} is not backed by a real photograph")
    if value.get("synthetic") is not False:
        raise ValueError(f"{item.get('id')} synthetic/generated visual is forbidden")
    if value.get("subject_match") is not True:
        raise ValueError(f"{item.get('id')} photo does not match the story subject")
    if value.get("editor_approved") is not True:
        raise ValueError(f"{item.get('id')} photo lacks editorial approval")
    if value.get("source_type") not in ALLOWED_SOURCE_TYPES:
        raise ValueError(
            f"unsupported photo source_type for {item.get('id')}: "
            f"{value.get('source_type')}"
        )
    if value.get("rights_basis") not in ALLOWED_RIGHTS:
        raise ValueError(
            f"unsupported rights_basis for {item.get('id')}: "
            f"{value.get('rights_basis')}"
        )
    if (
        value.get("source_type") not in {"staff", "public_domain"}
        and not str(value.get("source_url", "")).strip()
    ):
        raise ValueError(f"external photo source_url missing for {item.get('id')}")
    return value


def local_image_path(item: dict[str, Any]) -> Path:
    photo_metadata(item)
    raw = str(item.get("image_path", "")).strip()
    if not raw:
        raise ValueError(f"social item {item.get('id')} has no image_path")
    path = (ROOT / raw).resolve()
    if path != PHOTO_ROOT and PHOTO_ROOT not in path.parents:
        raise ValueError(f"photo must be approved under {PHOTO_ROOT}: {raw}")
    if any(
        part.lower() in {"generated", "synthetic", "cards", "ai"}
        for part in path.parts
    ):
        raise ValueError(f"generated/card path is forbidden: {raw}")
    if path.suffix.lower() not in {".jpg", ".jpeg"} or not path.is_file():
        raise ValueError(f"approved JPEG photograph does not exist: {raw}")
    if not path.read_bytes()[:12].startswith(b"\xff\xd8\xff"):
        raise ValueError(f"invalid JPEG signature: {raw}")
    return path


def platform_config(item: dict[str, Any], platform: str) -> dict[str, Any] | None:
    platforms = item.get("platforms")
    if not isinstance(platforms, dict):
        # Backward compatibility: historical outbox entries stay Facebook-only.
        return {"status": item.get("status", "hold")} if platform == "facebook" else None
    value = platforms.get(platform)
    return value if isinstance(value, dict) else None


def platform_selected(item: dict[str, Any], platform: str) -> bool:
    return platform_config(item, platform) is not None


def platform_ready(item: dict[str, Any], platform: str) -> bool:
    config = platform_config(item, platform)
    return (
        item.get("status") == "ready"
        and isinstance(config, dict)
        and config.get("status") == "ready"
    )


def schedule_ready(item: dict[str, Any]) -> bool:
    raw = item.get("publish_after")
    if not raw:
        return True
    try:
        when = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid publish_after for {item.get('id')}: {raw}") from exc
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when <= dt.datetime.now(dt.timezone.utc)


def direct_photo_url(item: dict[str, Any], platform: str) -> str:
    config = platform_config(item, platform) or {}
    image = item.get("image") if isinstance(item.get("image"), dict) else {}
    candidates = [
        config.get("photo_url"),
        config.get("image_url"),
        image.get("direct_source_url"),
    ]
    for candidate in candidates:
        url = str(candidate or "").strip()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme == "https" and parsed.hostname:
            return url
    raise ValueError(f"{item.get('id')} has no HTTPS photo URL for {platform}")


def canonical_photo_url(item: dict[str, Any]) -> str:
    config = platform_config(item, "tiktok") or {}
    explicit = str(config.get("photo_url") or "").strip()
    if explicit:
        parsed = urllib.parse.urlparse(explicit)
        if parsed.scheme != "https" or parsed.hostname not in CANONICAL_HOSTS:
            raise ValueError(
                "TikTok photo URL must be hosted on the verified valceaclar.ro "
                f"domain: {explicit}"
            )
        return explicit
    filename = Path(str(item.get("image_path", ""))).name
    if not filename:
        raise ValueError(f"{item.get('id')} has no image filename")
    return f"https://valceaclar.ro/media/social/{urllib.parse.quote(filename)}"


def first_line(text: str) -> str:
    for line in str(text).splitlines():
        value = line.strip(" \t•-")
        if value:
            return value
    return ""


def utf16_units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def truncate_utf16(text: str, limit: int, suffix: str = "…") -> str:
    value = str(text).strip()
    if utf16_units(value) <= limit:
        return value
    budget = max(0, limit - utf16_units(suffix))
    chars: list[str] = []
    units = 0
    for char in value:
        size = utf16_units(char)
        if units + size > budget:
            break
        chars.append(char)
        units += size
    return "".join(chars).rstrip() + suffix


def compact_caption(message: str, link: str, credit: str, limit: int) -> str:
    parts = [str(message).strip(), str(link).strip()]
    if str(credit).strip():
        parts.append(f"Foto: {str(credit).strip()}")
    return truncate_utf16("\n\n".join(part for part in parts if part), limit)
