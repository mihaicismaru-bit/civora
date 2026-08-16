#!/usr/bin/env python3
"""Dispatch-contract v1.1 patch: resolve stories from Instagram base module."""
from __future__ import annotations

import argparse
import json

import build_editorial_dispatch_previews as impl


def story_map():
    result = {}
    for story in impl.ig.base.stories():
        result[str(story["id"])] = story
    return result


impl.story_map = story_map


def self_test() -> int:
    result = story_map()
    assert "luminos-fest-zavoi-20260815" in result
    assert "olanesti-bridge-monitor" in result
    base_result = impl.self_test()
    print("VÂLCEA CLAR editorial dispatch v1.1 story resolution: PASS")
    return base_result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    print(json.dumps(impl.build(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
