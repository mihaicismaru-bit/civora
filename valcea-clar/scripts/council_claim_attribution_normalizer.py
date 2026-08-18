#!/usr/bin/env python3
"""Complete explicit attribution metadata for deterministic HCL fact kernels.

The reader-facing sentence already names the speaker; Editorial Writer also
requires a machine-readable `attribution` field for every attributed statement.
This small normalizer keeps that invariant explicit and fail-closed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "editorial" / "facts_registry.json"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize(doc: dict[str, Any]) -> tuple[int, list[str]]:
    changed = 0
    story_ids: list[str] = []
    for item in doc.get("facts") or []:
        if not isinstance(item, dict) or not str(item.get("id") or "").startswith("rm-valcea-hcl-"):
            continue
        kernel = item.get("fact_kernel") if isinstance(item.get("fact_kernel"), dict) else {}
        touched = False
        for claim in kernel.get("claims") or []:
            if not isinstance(claim, dict) or claim.get("kind") != "attributed_statement" or claim.get("attribution"):
                continue
            text = str(claim.get("text") or "")
            if "CET Govora" in text:
                claim["attribution"] = "CET Govora S.A., prin adresa citată în HCL 305/2026"
            else:
                raise ValueError(f"unresolved_attribution:{item.get('id')}:{claim.get('id')}")
            changed += 1
            touched = True
        if touched:
            story_ids.append(str(item.get("id")))
    return changed, story_ids


def self_test() -> int:
    doc={"facts":[{"id":"rm-valcea-hcl-305-20260814","fact_kernel":{"claims":[{"id":"a","kind":"attributed_statement","text":"CET Govora a comunicat Primăriei că nu poate semna forma transmisă."}]}}]}
    count, ids=normalize(doc)
    assert count==1 and ids==["rm-valcea-hcl-305-20260814"]
    assert doc["facts"][0]["fact_kernel"]["claims"][0]["attribution"].startswith("CET Govora")
    print("VÂLCEA CLAR HCL claim attribution normalizer self-test: PASS")
    return 0


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    if args.self_test:
        return self_test()
    doc=load(FACTS)
    count, ids=normalize(doc)
    if args.apply and count:
        FACTS.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":"UPDATED" if args.apply and count else "NO_CHANGE","claims":count,"story_ids":ids},ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
