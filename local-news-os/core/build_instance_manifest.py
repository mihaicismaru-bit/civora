#!/usr/bin/env python3
"""Build a deterministic runtime manifest from one LOCAL NEWS OS instance config."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("instance config must be a JSON object")
    return value


def stable_hash(value: dict) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build(cfg: dict) -> dict:
    instance_id = str(cfg["instance_id"])
    runtime = cfg["runtime"]
    return {
        "schema_version": "1.0",
        "instance_id": instance_id,
        "environment": cfg["environment"],
        "brand_name": cfg["brand"]["name"],
        "canonical_domain": cfg["canonical_domain"],
        "locale": cfg["locale"],
        "timezone": cfg["timezone"],
        "geography": cfg["geography"],
        "edition_schedule": cfg["edition_schedule"],
        "enabled_modules": sorted(k for k, v in cfg["modules"].items() if v),
        "social_channels": list(cfg["social_channels"]),
        "runtime": {
            "state_root": runtime["state_root"],
            "output_root": runtime["output_root"],
            "current_edition": runtime["current_edition"],
            "live_feed": runtime["live_feed"],
        },
        "packs": cfg["packs"],
        "policies": cfg["policies"],
        "config_sha256": stable_hash(cfg),
        "generator": "local_news_os_instance_manifest_v1",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("instance", help="instance id, e.g. valcea")
    parser.add_argument("--output", help="optional output path")
    args = parser.parse_args()

    config_path = ROOT / "local-news-os" / "instances" / args.instance / "instance.json"
    if not config_path.is_file():
        raise SystemExit(f"unknown instance: {args.instance}")
    cfg = load(config_path)
    if cfg.get("instance_id") != args.instance:
        raise SystemExit("instance id mismatch")
    manifest = build(cfg)
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
