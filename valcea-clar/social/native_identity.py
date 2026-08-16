#!/usr/bin/env python3
"""Canonical VÂLCEA CLAR identity lineage for native social products."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SYSTEM_PATH = ROOT / "valcea-clar" / "social" / "native_platform_identity_system.json"


def load_system() -> dict[str, Any]:
    value = json.loads(SYSTEM_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("native_platform_identity_system.json must contain an object")
    return value


def product_identity(platform: str) -> dict[str, Any]:
    system = load_system()
    platforms = system.get("platforms") if isinstance(system.get("platforms"), dict) else {}
    cfg = platforms.get(platform)
    if not isinstance(cfg, dict):
        raise RuntimeError(f"missing native identity configuration for platform: {platform}")
    common = system.get("common") if isinstance(system.get("common"), dict) else {}
    identity: dict[str, Any] = {
        "brand_source": str(system.get("brand_source") or ""),
        "profile_source": str(system.get("profile_source") or ""),
        "doctrine_source": str(system.get("doctrine_source") or ""),
        "native_identity_source": "valcea-clar/social/native_platform_identity_system.json",
        "channel_id": str(cfg.get("channel_id") or ""),
        "display_name": str(common.get("display_name") or ""),
        "identity_mode": str(cfg.get("identity_mode") or ""),
        "product_role": str(cfg.get("product_role") or ""),
    }
    for key in ("presentation", "visual", "thumbnail", "video", "audio"):
        value = cfg.get(key)
        if isinstance(value, dict):
            identity[key] = copy.deepcopy(value)
    return identity


def self_test() -> int:
    for platform in ("x", "threads", "linkedin", "tiktok", "youtube", "telegram", "whatsapp"):
        identity = product_identity(platform)
        assert identity["channel_id"] == f"valcea-{platform}"
        assert identity["display_name"] == "VÂLCEA CLAR"
        assert identity["brand_source"] == "valcea-clar/social/social_brand_system.json"
        assert identity["profile_source"] == "valcea-clar/social/profile_identity_system.json"
    assert product_identity("tiktok")["visual"]["brand_mark"] == "VC."
    assert product_identity("youtube")["thumbnail"]["brand_mark"] == "VC."
    print("VÂLCEA CLAR native identity helper self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
