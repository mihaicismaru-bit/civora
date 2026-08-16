#!/usr/bin/env python3
"""Stamp canonical VÂLCEA CLAR identity lineage into durable native outboxes.

This is deliberately metadata-only. It does not alter copy, media, scheduling,
publication eligibility or platform-native formatting.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from native_identity import product_identity

ROOT = Path(__file__).resolve().parents[2]
SOCIAL = ROOT / "valcea-clar" / "social"
IDENTITY_SOURCE = "valcea-clar/social/native_platform_identity_system.json"
DURABLE_PLATFORMS = ("threads", "x", "linkedin", "telegram", "whatsapp", "youtube")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stamp_document(platform: str, outbox: dict[str, Any], state: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if platform not in DURABLE_PLATFORMS:
        raise ValueError(f"unsupported durable identity platform: {platform}")
    if outbox.get("platform") != platform:
        raise ValueError(f"{platform}: outbox platform mismatch")
    identity = product_identity(platform)
    expected_channel = f"valcea-{platform}"
    if identity.get("channel_id") != expected_channel:
        raise ValueError(f"{platform}: identity channel mismatch")

    items = outbox.get("items")
    if not isinstance(items, list):
        raise ValueError(f"{platform}: outbox items must be a list")
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"{platform}: outbox item {index} is not an object")
        item["identity"] = identity
    outbox["identity_source"] = IDENTITY_SOURCE
    outbox["identity_channel_id"] = expected_channel

    if state is not None:
        if state.get("platform") != platform:
            raise ValueError(f"{platform}: state platform mismatch")
        state["identity_source"] = IDENTITY_SOURCE
        state["identity_channel_id"] = expected_channel
    return outbox, state


def stamp_platform(platform: str) -> dict[str, Any]:
    outbox_path = SOCIAL / f"{platform}_outbox.json"
    state_path = SOCIAL / f"{platform}_state.json"
    if not outbox_path.exists():
        raise FileNotFoundError(outbox_path)
    outbox = load(outbox_path)
    state = load(state_path) if state_path.exists() else None
    outbox, state = stamp_document(platform, outbox, state)
    write(outbox_path, outbox)
    if state is not None:
        write(state_path, state)
    return {
        "platform": platform,
        "items": len(outbox.get("items", [])),
        "identity_channel_id": outbox["identity_channel_id"],
        "state_stamped": state is not None,
    }


def validate_stamped(platform: str, outbox: dict[str, Any], state: dict[str, Any] | None = None) -> list[str]:
    errors: list[str] = []
    expected = product_identity(platform)
    if outbox.get("identity_source") != IDENTITY_SOURCE:
        errors.append(f"{platform}:outbox_identity_source_missing")
    if outbox.get("identity_channel_id") != expected.get("channel_id"):
        errors.append(f"{platform}:outbox_identity_channel_drift")
    for index, item in enumerate(outbox.get("items", [])):
        if not isinstance(item, dict):
            errors.append(f"{platform}:item_{index}_not_object")
            continue
        identity = item.get("identity")
        if identity != expected:
            errors.append(f"{platform}:item_{index}_identity_drift")
    if state is not None:
        if state.get("identity_source") != IDENTITY_SOURCE:
            errors.append(f"{platform}:state_identity_source_missing")
        if state.get("identity_channel_id") != expected.get("channel_id"):
            errors.append(f"{platform}:state_identity_channel_drift")
    return errors


def self_test() -> int:
    outbox = {"platform": "x", "items": [{"id": "x-1", "posts": ["Test."]}]}
    state = {"platform": "x"}
    stamped, stamped_state = stamp_document("x", outbox, state)
    assert stamped["items"][0]["identity"]["product_role"] == "local_newswire"
    assert stamped["items"][0]["identity"]["presentation"]["brand_prefix_each_post"] is False
    assert stamped_state is not None
    assert validate_stamped("x", stamped, stamped_state) == []
    stamped["items"][0]["identity"] = {"channel_id": "wrong"}
    assert "x:item_0_identity_drift" in validate_stamped("x", stamped, stamped_state)
    print("VÂLCEA CLAR native outbox identity stamper self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=DURABLE_PLATFORMS, action="append")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    platforms = tuple(args.platform or DURABLE_PLATFORMS)
    results = []
    for platform in platforms:
        result = stamp_platform(platform)
        outbox = load(SOCIAL / f"{platform}_outbox.json")
        state_path = SOCIAL / f"{platform}_state.json"
        state = load(state_path) if state_path.exists() else None
        errors = validate_stamped(platform, outbox, state)
        if errors:
            for error in errors:
                print(f"ERROR {error}")
            return 1
        results.append(result)
    print(json.dumps({"status": "PASS", "identity_source": IDENTITY_SOURCE, "platforms": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
