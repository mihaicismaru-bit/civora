#!/usr/bin/env python3
"""Instagram editorial v1.2 patch: preserve hyphenated company names.

This wraps v1.1 while replacing only contractor-name normalization. A spaced
separator dash becomes ` + `; internal hyphens such as Dimex-2000 are preserved.
"""
from __future__ import annotations

import argparse
import json
import re
from typing import Any

import instagram_editorial_v1_1 as impl


def contractor_pair(text: str) -> str | None:
    match = re.search(r"asocierii\s+(.+?)(?:,\s+cu\s+subcontractan|;|\.)", text, re.I)
    if not match:
        return None
    value = " ".join(match.group(1).split())
    value = re.sub(r"\bSRL\b", "", value, flags=re.I)
    # Replace only a dash used as a separator. Keep hyphens inside company names.
    value = re.sub(r"\s+[—–-]\s+", " + ", value)
    value = re.sub(r"\s+", " ", value).strip(" +")
    return value or None


# v1.1 package/self-test resolve this symbol dynamically from their module.
impl.contractor_pair = contractor_pair


def self_test() -> int:
    assert contractor_pair("atribuit asocierii Ralunic SRL — Dimex-2000 Company SRL, cu subcontractanți") == "Ralunic + Dimex-2000 Company"
    assert contractor_pair("asocierii Alpha-Beta SRL - Gamma SRL, cu subcontractanți") == "Alpha-Beta + Gamma"
    result = impl.self_test()
    print("VÂLCEA CLAR Instagram editorial v1.2 entity normalization: PASS")
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
