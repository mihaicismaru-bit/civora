#!/usr/bin/env python3
"""Instagram editorial v1.2: entity-safe copy + premium feed identity."""
from __future__ import annotations

import argparse
import json
import re

import feed_identity_v1_1 as feed_identity
import instagram_editorial_v1_1 as impl


def contractor_pair(text: str) -> str | None:
    match = re.search(r"asocierii\s+(.+?)(?:,\s+cu\s+subcontractan|;|\.)", text, re.I)
    if not match:
        return None
    value = " ".join(match.group(1).split())
    value = re.sub(r"\bSRL\b", "", value, flags=re.I)
    value = re.sub(r"\s+[—–-]\s+", " + ", value)
    value = re.sub(r"\s+", " ", value).strip(" +")
    return value or None


# Keep the v1/v1.1 fact packaging intact. The v1.2 wrapper owns only entity
# normalization and the shared premium presentation layer used by preview and
# by the fail-closed publisher.
impl.contractor_pair = contractor_pair
impl.base.contractor_pair = contractor_pair
impl.base.render_cover = feed_identity.render_instagram_cover
impl.render_text_slide = feed_identity.render_instagram_text_slide


def self_test() -> int:
    assert contractor_pair("atribuit asocierii Ralunic SRL — Dimex-2000 Company SRL, cu subcontractanți") == "Ralunic + Dimex-2000 Company"
    assert contractor_pair("asocierii Alpha-Beta SRL - Gamma SRL, cu subcontractanți") == "Alpha-Beta + Gamma"
    assert impl.base.render_cover is feed_identity.render_instagram_cover
    assert impl.render_text_slide is feed_identity.render_instagram_text_slide
    feed_identity.self_test()
    result = impl.self_test()
    print("VÂLCEA CLAR Instagram editorial v1.2 premium feed identity: PASS")
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
