#!/usr/bin/env python3
"""Facebook editorial preview v1.1: entity-safe copy + premium feed identity."""
from __future__ import annotations

import argparse
import json
import re

import facebook_editorial_preview as impl
import feed_identity_v1_1 as feed_identity


def contractor_pair(text: str) -> str | None:
    match = re.search(r"asocierii\s+(.+?)(?:,\s+cu\s+subcontractan|;|\.)", text, re.I)
    if not match:
        return None
    value = " ".join(match.group(1).split())
    value = re.sub(r"\bSRL\b", "", value, flags=re.I)
    # Only spaced separator dashes become ` + `; internal hyphens stay intact.
    value = re.sub(r"\s+[—–-]\s+", " + ", value)
    value = re.sub(r"\s+", " ", value).strip(" +")
    return value or None


# Preserve all verified packaging/copy logic from the base module. Only the
# name normalizer and deterministic presentation layer are upgraded here.
impl.contractor_pair = contractor_pair
impl.render = feed_identity.render_facebook


def self_test() -> int:
    assert contractor_pair("asocierii Ralunic SRL — Dimex-2000 Company SRL, cu subcontractanți") == "Ralunic + Dimex-2000 Company"
    assert contractor_pair("asocierii Alpha-Beta SRL - Gamma SRL, cu subcontractanți") == "Alpha-Beta + Gamma"
    assert impl.render is feed_identity.render_facebook
    feed_identity.self_test()
    result = impl.self_test()
    print("VÂLCEA CLAR Facebook editorial v1.1 premium feed identity: PASS")
    return result


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
