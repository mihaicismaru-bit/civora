#!/usr/bin/env python3
"""Fail closed when production-instance identity leaks into CORE_GENERIC source.

The forbidden vocabulary is derived from production instance configuration so the
guard itself contains no publication-specific names. Fixture/migration/
compatibility exceptions must be explicit repository-relative paths.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = ROOT / "local-news-os" / "core"
INSTANCES_ROOT = ROOT / "local-news-os" / "instances"

# PRS-074 permits explicit exceptions only for fixtures, migrations and
# compatibility adapters. Keep empty unless such a file genuinely exists.
ALLOWLIST: dict[str, str] = {}


def normalize(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def identity_strings(cfg: dict) -> list[str]:
    values: list[str] = []
    for key in ("instance_id", "canonical_domain"):
        value = cfg.get(key)
        if isinstance(value, str):
            values.append(value)

    brand = cfg.get("brand")
    if isinstance(brand, dict):
        for key in ("name", "short_name"):
            value = brand.get(key)
            if isinstance(value, str):
                values.append(value)

    geography = cfg.get("geography")
    if isinstance(geography, dict):
        stack = list(geography.values())
        while stack:
            value = stack.pop()
            if isinstance(value, str):
                values.append(value)
            elif isinstance(value, list):
                stack.extend(value)
            elif isinstance(value, dict):
                stack.extend(value.values())
    return values


def forbidden_tokens() -> tuple[str, ...]:
    tokens: set[str] = set()
    for path in sorted(INSTANCES_ROOT.glob("*/instance.json")):
        cfg = json.loads(path.read_text(encoding="utf-8"))
        if cfg.get("environment") != "production":
            continue
        for raw in identity_strings(cfg):
            value = normalize(raw).strip()
            if len(value) >= 5:
                tokens.add(value)
            for part in re.findall(r"[a-z0-9.-]+", value):
                if len(part) >= 5:
                    tokens.add(part)
    tokens.difference_update({"romania", "romanian"})
    return tuple(sorted(tokens, key=lambda item: (-len(item), item)))


def scan() -> list[str]:
    tokens = forbidden_tokens()
    errors: list[str] = []
    this_file = Path(__file__).resolve()
    for path in sorted(CORE_ROOT.rglob("*.py")):
        if path.resolve() == this_file:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel in ALLOWLIST:
            continue
        text = normalize(path.read_text(encoding="utf-8"))
        hits = [token for token in tokens if token in text]
        if hits:
            errors.append(f"{rel}: production identity in CORE_GENERIC: {', '.join(hits[:8])}")
    return errors


def self_test() -> None:
    tokens = forbidden_tokens()
    assert tokens, "at least one production identity token must be derived"
    print("CORE_GENERIC_HARDCODING_GUARD_SELF_TEST_PASS")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    errors = scan()
    report = {
        "status": "PASS" if not errors else "FAIL",
        "core_root": CORE_ROOT.relative_to(ROOT).as_posix(),
        "production_identity_token_count": len(forbidden_tokens()),
        "allowlist": ALLOWLIST,
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
