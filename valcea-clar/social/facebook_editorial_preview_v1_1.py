#!/usr/bin/env python3
"""Facebook editorial preview v1.1: preserve hyphenated company names."""
from __future__ import annotations

import argparse
import json
import re

import facebook_editorial_preview as impl


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


impl.contractor_pair = contractor_pair


def self_test() -> int:
    assert contractor_pair("asocierii Ralunic SRL — Dimex-2000 Company SRL, cu subcontractanți") == "Ralunic + Dimex-2000 Company"
    assert contractor_pair("asocierii Alpha-Beta SRL - Gamma SRL, cu subcontractanți") == "Alpha-Beta + Gamma"
    result = impl.self_test()
    print("VÂLCEA CLAR Facebook editorial v1.1 entity normalization: PASS")
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
